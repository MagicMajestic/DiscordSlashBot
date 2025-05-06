import discord
import logging
import asyncio
import datetime
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional, List
from utils.db import get_db, create_tables
from utils.embeds import (
    create_private_tournament_embed, 
    create_public_tournament_embed,
    create_tournament_notification_embed
)
from utils.brackets import generate_tournament_bracket
from utils.permissions import is_tournament_manager, is_admin
from utils.constants import (
    TOURNAMENT_APPROVAL_CHANNEL, 
    PRIVATE_TOURNAMENTS_CHANNEL, 
    PUBLIC_TOURNAMENTS_CHANNEL,
    TOURNAMENT_RESULTS_CHANNEL
)

logger = logging.getLogger(__name__)

class TournamentView(discord.ui.View):
    def __init__(self, tournament_id: int, type_: str):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.type = type_
        
    @discord.ui.button(label="Участвовать", style=discord.ButtonStyle.primary, custom_id="join_tournament")
    async def join_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Сначала подтвердим получение взаимодействия
        await interaction.response.defer(ephemeral=True)
        
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Check if user is already registered
            cursor.execute(
                "SELECT COUNT(*) as count FROM tournament_participants WHERE tournament_id = ? AND user_id = ?",
                (self.tournament_id, interaction.user.id)
            )
            
            result = cursor.fetchone()
            if result and result.get('count', 0) > 0:
                await interaction.followup.send("Вы уже зарегистрированы на этот турнир!", ephemeral=True)
                return
                
            # First get max participants from the tournament
            cursor.execute(
                "SELECT max_participants FROM tournaments WHERE id = ?",
                (self.tournament_id,)
            )
            tournament_info = cursor.fetchone()
            if not tournament_info or 'max_participants' not in tournament_info:
                await interaction.followup.send("Ошибка: турнир не найден или данные повреждены.", ephemeral=True)
                return
                
            max_participants = tournament_info['max_participants']
                
            # Then check participant count
            cursor.execute(
                "SELECT COUNT(*) as count FROM tournament_participants WHERE tournament_id = ?",
                (self.tournament_id,)
            )
            
            participant_result = cursor.fetchone()
            participant_count = participant_result.get('count', 0) if participant_result else 0
            
            if participant_count >= max_participants:
                await interaction.followup.send("Турнир уже заполнен!", ephemeral=True)
                return
                
            # Add player to tournament
            # First ensure player exists in players table
            cursor.execute(
                "INSERT OR IGNORE INTO players (user_id, username) VALUES (?, ?)",
                (interaction.user.id, interaction.user.display_name)
            )
            
            # Then add to tournament participants
            cursor.execute(
                "INSERT INTO tournament_participants (tournament_id, user_id, join_date) VALUES (?, ?, ?)",
                (self.tournament_id, interaction.user.id, datetime.datetime.now())
            )
            
            db.commit()
            
            # Get entry fee
            cursor.execute("SELECT entry_fee FROM tournaments WHERE id = ?", (self.tournament_id,))
            fee_result = cursor.fetchone()
            entry_fee = fee_result.get('entry_fee', 0) if fee_result else 0
            
            if entry_fee > 0:
                await interaction.followup.send(
                    f"Вы успешно зарегистрированы! Пожалуйста, передайте вступительный взнос в размере {entry_fee}$ организатору турнира перед началом.", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send("Вы успешно зарегистрированы на турнир!", ephemeral=True)
                
            # Update tournament embed
            cursor.execute(
                "SELECT COUNT(*) as count FROM tournament_participants WHERE tournament_id = ?",
                (self.tournament_id,)
            )
            current_result = cursor.fetchone()
            current_participants = current_result.get('count', 0) if current_result else 0
            
            # Find the original message to edit it
            channel = interaction.channel
            if channel:
                async for message in channel.history(limit=100):
                    if message.author.id == interaction.client.user.id and len(message.embeds) > 0:
                        embed = message.embeds[0]
                        for i, field in enumerate(embed.fields):
                            if field.name == "Участники":
                                embed.set_field_at(
                                    index=i,
                                    name="Участники",
                                    value=f"{current_participants}/{max_participants}",
                                    inline=True
                                )
                                await message.edit(embed=embed)
                                break
                        break
                    
        except Exception as e:
            logger.error(f"Error registering user for tournament: {e}")
            db.rollback()
            await interaction.followup.send("Произошла ошибка при регистрации. Пожалуйста, попробуйте позже.", ephemeral=True)


class ApprovalView(discord.ui.View):
    def __init__(self, tournament_id: int, bot: commands.Bot):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.bot = bot
        
    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.green, custom_id="approve_tournament")
    async def approve_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Сначала отложим ответ на взаимодействие
        await interaction.response.defer(ephemeral=True)
        
        # Verify permissions
        if not await is_tournament_manager(interaction):
            await interaction.followup.send("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Update tournament status
            cursor.execute(
                "UPDATE tournaments SET status = 'approved', approved_by = ? WHERE id = ?",
                (interaction.user.id, self.tournament_id)
            )
            
            # Get tournament details
            cursor.execute(
                """
                SELECT t.*, u.username as creator_name 
                FROM tournaments t
                JOIN players u ON t.creator_id = u.user_id
                WHERE t.id = ?
                """,
                (self.tournament_id,)
            )
            
            tournament = cursor.fetchone()
            if not tournament:
                await interaction.followup.send("Ошибка: турнир не найден.", ephemeral=True)
                return
                
            db.commit()
            
            # Find the right channel to post the tournament in
            if tournament.get('type') == 'private':
                channel_id = PRIVATE_TOURNAMENTS_CHANNEL
                embed = create_private_tournament_embed(tournament)
            else:
                channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                embed = create_public_tournament_embed(tournament)
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.error(f"Could not find channel with ID {channel_id}")
                await interaction.followup.send("Канал для публикации турнира не найден!", ephemeral=True)
                return
                
            # Post the tournament in the appropriate channel
            await channel.send(
                embed=embed,
                view=TournamentView(tournament_id=self.tournament_id, type_=tournament.get('type', 'private'))
            )
            
            # Disable the buttons and edit the message
            for child in self.children:
                child.disabled = True
                
            if interaction.message:
                await interaction.message.edit(view=self)
            
            await interaction.followup.send("Турнир одобрен и опубликован!", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error approving tournament: {e}")
            db.rollback()
            await interaction.followup.send("Произошла ошибка при одобрении турнира.", ephemeral=True)
    
    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.red, custom_id="reject_tournament")
    async def reject_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verify permissions
        if not await is_tournament_manager(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        # Create a modal for rejection reason
        try:
            modal = RejectTournamentModal(self.tournament_id, self)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Error sending rejection modal: {e}")
            await interaction.response.send_message("Произошла ошибка при отклонении турнира.", ephemeral=True)


class RejectTournamentModal(discord.ui.Modal):
    reason = discord.ui.TextInput(
        label="Укажите причину отклонения турнира",
        style=discord.TextStyle.paragraph,
        placeholder="Введите причину, почему турнир отклонен...",
        required=True,
        max_length=1000
    )
    
    def __init__(self, tournament_id: int, view: ApprovalView):
        super().__init__(title="Причина отклонения")
        self.tournament_id = tournament_id
        self.approval_view = view
        
    async def on_submit(self, interaction: discord.Interaction):
        # Сначала отложим ответ на взаимодействие
        await interaction.response.defer(ephemeral=True)
        
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Update tournament status
            cursor.execute(
                "UPDATE tournaments SET status = 'rejected', rejection_reason = ? WHERE id = ?",
                (self.reason.value, self.tournament_id)
            )
            
            # Get tournament creator to notify them
            cursor.execute(
                "SELECT creator_id FROM tournaments WHERE id = ?",
                (self.tournament_id,)
            )
            
            result = cursor.fetchone()
            if not result or 'creator_id' not in result:
                await interaction.followup.send("Ошибка: турнир не найден или данные повреждены.", ephemeral=True)
                return
                
            creator_id = result['creator_id']
            db.commit()
            
            # Create rejection embed
            embed = discord.Embed(
                title="Ваш турнир отклонен",
                description=f"К сожалению, ваш турнир был отклонен модератором.",
                color=0x808080  # Grey color for rejected tournaments
            )
            
            embed.add_field(name="Причина отклонения:", value=self.reason.value)
            
            # Notify creator via DM
            try:
                creator = await interaction.client.fetch_user(creator_id)
                if creator:
                    await creator.send(embed=embed)
            except Exception as e:
                logger.error(f"Could not send DM to user {creator_id}: {e}")
            
            # Disable the buttons and edit the message
            if interaction.message:
                for child in self.approval_view.children:
                    child.disabled = True
                await interaction.message.edit(view=self.approval_view)
            
            await interaction.followup.send("Турнир отклонен, создатель уведомлен о причине.", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error rejecting tournament: {e}")
            db.rollback()
            await interaction.followup.send("Произошла ошибка при отклонении турнира.", ephemeral=True)


class Tournaments(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        create_tables()  # Initialize database tables
        self.processed_interactions = set()  # Для отслеживания обработанных взаимодействий
        self.check_upcoming_tournaments.start()
        
    def cog_unload(self):
        self.check_upcoming_tournaments.cancel()
    
    @tasks.loop(minutes=1)  # Уменьшим интервал для быстрого тестирования
    async def check_upcoming_tournaments(self):
        """Check for tournaments starting soon and send notifications."""
        logger.info("Running check_upcoming_tournaments task...")
        db = get_db()
        cursor = db.cursor()
        
        now = datetime.datetime.now()
        logger.info(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Логируем состояние турнира 10000
        cursor.execute(
            "SELECT id, name, status, tournament_date, started FROM tournaments WHERE id = 10000"
        )
        tournament_10000 = cursor.fetchone()
        if tournament_10000:
            logger.info(f"Tournament 10000 status: {tournament_10000}")
        
        # 0. Проверка одобренных турниров на недостаточное количество участников
        await self.check_approved_tournaments_participants()
        
        # 1. Get tournaments starting in the next 15 minutes (for notifications)
        notification_threshold = now + datetime.timedelta(minutes=15)
        
        cursor.execute(
            """
            SELECT t.*, u.username as creator_name 
            FROM tournaments t
            JOIN players u ON t.creator_id = u.user_id
            WHERE t.tournament_date BETWEEN ? AND ?
            AND t.status = 'approved'
            AND t.notification_sent = 0
            """,
            (now.strftime('%Y-%m-%d %H:%M:%S'), notification_threshold.strftime('%Y-%m-%d %H:%M:%S'))
        )
        
        upcoming_tournaments = cursor.fetchall()
        
        for tournament in upcoming_tournaments:
            # Mark notification as sent
            cursor.execute(
                "UPDATE tournaments SET notification_sent = 1 WHERE id = ?",
                (tournament['id'],)
            )
            
            # Get participants to mention
            cursor.execute(
                "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                (tournament['id'],)
            )
            
            participants = cursor.fetchall()
            participant_mentions = " ".join([f"<@{p['user_id']}>" for p in participants])
            
            # Get the appropriate channel
            if tournament['type'] == 'private':
                channel_id = PRIVATE_TOURNAMENTS_CHANNEL
            else:
                channel_id = PUBLIC_TOURNAMENTS_CHANNEL
            
            channel = self.bot.get_channel(channel_id)
            if channel:
                embed = create_tournament_notification_embed(tournament)
                await channel.send(content=f"**ВНИМАНИЕ! ТУРНИР СКОРО НАЧНЕТСЯ!** {participant_mentions}", embed=embed)
        
        # 2. Get tournaments that should have started but status is still 'approved'
        # Сначала проверим, есть ли турниры, которые должны начаться
        cursor.execute(
            """
            SELECT id, name, tournament_date
            FROM tournaments 
            WHERE tournament_date <= ?
            AND status = 'approved'
            AND started = 0
            """,
            (now.strftime('%Y-%m-%d %H:%M:%S'),)
        )
        
        pending_tournaments = cursor.fetchall()
        
        logger.info(f"Found {len(pending_tournaments)} tournaments that should start: {pending_tournaments}")
        
        # Теперь получим полную информацию с данными создателя
        cursor.execute(
            """
            SELECT t.*, u.username as creator_name 
            FROM tournaments t
            LEFT JOIN players u ON t.creator_id = u.user_id
            WHERE t.tournament_date <= ?
            AND t.status = 'approved'
            AND t.started = 0
            """,
            (now.strftime('%Y-%m-%d %H:%M:%S'),)
        )
        
        started_tournaments = cursor.fetchall()
        logger.info(f"After JOIN with players: {len(started_tournaments)} tournaments")
        
        for tournament in started_tournaments:
            logger.info(f"Starting tournament {tournament['id']} - {tournament['name']}")
            
            try:
                # Mark tournament as started
                cursor.execute(
                    "UPDATE tournaments SET started = 1, status = 'in_progress' WHERE id = ?",
                    (tournament['id'],)
                )
                
                # Выберем канал для коммуникации в зависимости от типа турнира
                if tournament['type'] == 'private':
                    channel_id = PRIVATE_TOURNAMENTS_CHANNEL
                else:
                    channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                                
                # Получаем всех участников турнира
                cursor.execute(
                    "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                    (tournament['id'],)
                )
                
                participants = cursor.fetchall()
                
                # Need at least 2 participants for a tournament
                if len(participants) < 2:
                    logger.warning(f"Tournament {tournament['id']} has less than 2 participants, cancelling")
                    
                    # Отменяем турнир из-за недостаточного количества участников
                    cursor.execute(
                        "UPDATE tournaments SET status = 'cancelled', cancellation_reason = ? WHERE id = ?",
                        ("Недостаточно участников для начала турнира", tournament['id'])
                    )
                    
                    # Фиксируем транзакцию
                    db.commit()
                    
                    # Отправляем уведомление об отмене турнира
                    channel = self.bot.get_channel(channel_id)
                    
                    if channel:
                        embed = discord.Embed(
                            title=f"❌ Турнир отменен: {tournament['name']}",
                            description=f"Турнир был автоматически отменен из-за недостаточного количества участников.",
                            color=0xE74C3C  # Red
                        )
                        
                        embed.add_field(
                            name="Статистика участников", 
                            value=f"Зарегистрировано: {len(participants)}\nМинимум требуется: 2", 
                            inline=False
                        )
                        
                        # Упоминаем всех зарегистрированных участников и создателя
                        mentions = ' '.join([f"<@{p['user_id']}>" for p in participants])
                        if tournament.get('creator_id'):
                            mentions += f" <@{tournament['creator_id']}>"
                            
                        await channel.send(content=f"**ВНИМАНИЕ! ТУРНИР ОТМЕНЕН!** {mentions}", embed=embed)
                        
                    # Пропускаем дальнейшую обработку этого турнира
                    continue

                # Начинаем создание матчей в зависимости от типа турнира
                if tournament['type'] == 'private':
                    
                    # Create initial matches for the first round - shuffle participants for random matchmaking
                    import random
                    participant_ids = [p['user_id'] for p in participants]
                    random.shuffle(participant_ids)
                    
                    # Create matches by pairing participants
                    for i in range(0, len(participant_ids), 2):
                        if i + 1 < len(participant_ids):  # Make sure we have a pair
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, player1_id, player2_id, creation_date)
                                VALUES (?, 1, ?, ?, ?)
                                """,
                                (
                                    tournament['id'], 
                                    participant_ids[i], 
                                    participant_ids[i+1],
                                    datetime.datetime.now()
                                )
                            )
                        else:  # Odd number of participants, one gets a bye
                            # In the future, implement proper bye handling
                            logger.info(f"Player {participant_ids[i]} gets a bye in first round")
                
                # For public tournaments (team-based)
                else:
                    cursor.execute(
                        "SELECT id, team_name FROM tournament_teams WHERE tournament_id = ?",
                        (tournament['id'],)
                    )
                    
                    teams = cursor.fetchall()
                    
                    # Need at least 2 teams for a tournament
                    if len(teams) < 2:
                        logger.warning(f"Tournament {tournament['id']} has less than 2 teams, cancelling")
                        
                        # Отменяем турнир из-за недостаточного количества команд
                        cursor.execute(
                            "UPDATE tournaments SET status = 'cancelled', cancellation_reason = ? WHERE id = ?",
                            ("Недостаточно команд для начала турнира", tournament['id'])
                        )
                        
                        # Отправляем уведомление об отмене турнира
                        channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                        channel = self.bot.get_channel(channel_id)
                        
                        if channel:
                            embed = discord.Embed(
                                title=f"❌ Турнир отменен: {tournament['name']}",
                                description=f"Турнир был автоматически отменен из-за недостаточного количества команд.",
                                color=0xE74C3C  # Red
                            )
                            
                            # Уведомляем о проблеме и упоминаем создателя
                            mentions = ""
                            if tournament.get('creator_id'):
                                mentions = f"<@{tournament['creator_id']}>"
                                
                            await channel.send(mentions, embed=embed)
                            
                        # Пропускаем дальнейшую обработку этого турнира
                        continue
                    
                    # Create initial matches for the first round - shuffle teams for random matchmaking
                    import random
                    team_ids = [t['id'] for t in teams]
                    random.shuffle(team_ids)
                    
                    # Create matches by pairing teams
                    for i in range(0, len(team_ids), 2):
                        if i + 1 < len(team_ids):  # Make sure we have a pair
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, team1_id, team2_id, creation_date)
                                VALUES (?, 1, ?, ?, ?)
                                """,
                                (
                                    tournament['id'], 
                                    team_ids[i], 
                                    team_ids[i+1],
                                    datetime.datetime.now()
                                )
                            )
                        else:  # Odd number of teams, one gets a bye
                            # In the future, implement proper bye handling
                            logger.info(f"Team {team_ids[i]} gets a bye in first round") 
                
                # Вначале убедимся, что есть матчи для турнира
                # Проверим, сколько матчей создалось
                cursor.execute(
                    "SELECT COUNT(*) as count FROM tournament_matches WHERE tournament_id = ?",
                    (tournament['id'],)
                )
                match_count = cursor.fetchone()['count']
                logger.info(f"Created {match_count} matches for tournament {tournament['id']}")
                
                # Зафиксируем транзакцию, чтобы матчи стали доступны для следующего запроса
                db.commit()
                
                # Генерируем турнирную сетку
                success, bracket = generate_tournament_bracket(tournament['id'])
                
                # Логируем успешное создание турнирной сетки
                logger.info(f"Tournament {tournament['id']} - {tournament['name']} bracket generation: {success}")
                
                if success:
                    # Send bracket to the appropriate channel
                    if tournament['type'] == 'private':
                        channel_id = PRIVATE_TOURNAMENTS_CHANNEL
                    else:
                        channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                        
                    channel = self.bot.get_channel(channel_id)
                    
                    # Получаем тип матчей (BO1, BO3 и т.д.)
                    match_type = tournament.get('match_type', 'BO1')
                    
                    # Логируем настройки турнира и его сообщение о запуске
                    tournament_start_message = f"""
                    🎮 Турнир начался: {tournament['name']}
                    Турнирная сетка сформирована. Первые матчи созданы!
                    
                    Формат матчей: {match_type}
                    Тип турнира: {tournament['type']}
                    """
                    
                    logger.info(tournament_start_message)
                    
                    # Get participants to mention
                    cursor.execute(
                        "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                        (tournament['id'],)
                    )
                    
                    participants = cursor.fetchall()
                    mentions = ' '.join([f"<@{p['user_id']}>" for p in participants])
                    
                    # Логируем участников
                    logger.info(f"Tournament {tournament['id']} participants: {participants}")
                    
                    # Создаем эмбед для сообщения о начале турнира
                    tournament_start_embed = discord.Embed(
                        title=f"🎮 Турнир начался: {tournament['name']}",
                        description=f"Турнирная сетка сформирована. Первые матчи созданы!",
                        color=0x2ECC71  # Green
                    )
                    
                    # Добавляем информацию о типе матчей (BO1, BO3 и т.д.)
                    if match_type == 'BO1':
                        match_desc = "Матчи проводятся до 1 победы"
                    elif match_type == 'BO3':
                        match_desc = "Матчи проводятся до 2 побед"
                    elif match_type == 'BO5':
                        match_desc = "Матчи проводятся до 3 побед"
                    elif match_type == 'BO7':
                        match_desc = "Матчи проводятся до 4 побед"
                    else:
                        match_desc = "Одиночные матчи"
                    
                    tournament_start_embed.add_field(
                        name="Формат матчей", 
                        value=f"{match_type}: {match_desc}", 
                        inline=False
                    )
                    
                    # Добавляем прямое упоминание всех участников
                    if participants:
                        tournament_start_embed.add_field(
                            name="Участники", 
                            value=mentions if len(mentions) <= 1024 else "Слишком много участников для отображения", 
                            inline=False
                        )
                    
                    # Show where to find match ID and other info
                    tournament_start_embed.add_field(
                        name="Как найти свой матч?", 
                        value="Посмотрите свой ID в турнирной сетке ниже. Используйте этот ID для отправки результатов через команду `/tournament-set-result`.", 
                        inline=False
                    )
                    
                    tournament_start_embed.set_footer(text=f"Турнир ID: {tournament['id']}")
                    
                    if channel:
                        # Отправляем уведомление о начале турнира
                        try:
                            await channel.send(
                                f"🏆 **ТУРНИР НАЧАЛСЯ!** Участники: {mentions}", 
                                embeds=[tournament_start_embed, bracket]
                            )
                            
                            # Отправляем в канал результатов также
                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                            if results_channel:
                                await results_channel.send(
                                    f"🏆 **ТУРНИР НАЧАЛСЯ!** Следите за результатами.", 
                                    embeds=[tournament_start_embed, bracket]
                                )
                            
                            logger.info(f"Successfully sent tournament start notification and bracket for tournament {tournament['id']}")
                        except Exception as e:
                            logger.error(f"Error sending tournament start notification: {e}")
                    else:
                        # Логируем, что не удалось найти канал, но иначе всё работает
                        logger.warning(f"Cannot find channel {channel_id} to send tournament start notification")
                        logger.info(f"Would have sent tournament start notification for {tournament['name']} (ID: {tournament['id']})")
                        logger.info(f"Tournament bracket would contain {len(participants)} participants")
                    
                        
            except Exception as e:
                logger.error(f"Error starting tournament {tournament['id']}: {e}")
                # Don't roll back - we want to keep the 'started' flag true to prevent repeated errors
                # But also don't mark the tournament as in_progress if it failed
                cursor.execute(
                    "UPDATE tournaments SET started = 1 WHERE id = ?",
                    (tournament['id'],)
                )
        
        db.commit()
    
    async def check_approved_tournaments_participants(self):
        """Проверка одобренных турниров на недостаточное количество участников."""
        db = get_db()
        cursor = db.cursor()
        
        # Получаем все одобренные турниры
        cursor.execute(
            """
            SELECT t.*, u.username as creator_name 
            FROM tournaments t
            JOIN players u ON t.creator_id = u.user_id
            WHERE t.status = 'approved'
            AND t.started = 0
            """
        )
        
        approved_tournaments = cursor.fetchall()
        
        for tournament in approved_tournaments:
            logger.info(f"Checking participants for tournament {tournament['id']} - {tournament['name']}")
            
            # Проверяем достаточное ли количество участников
            if tournament['type'] == 'private':
                # Для индивидуальных турниров
                cursor.execute(
                    "SELECT COUNT(*) as count FROM tournament_participants WHERE tournament_id = ?",
                    (tournament['id'],)
                )
                
                count = cursor.fetchone()['count']
                
                # Нужно минимум 2 участника
                if count < 2:
                    deadline = datetime.datetime.strptime(tournament['tournament_date'], "%Y-%m-%d %H:%M:%S") - datetime.timedelta(hours=1)
                    now = datetime.datetime.now()
                    
                    # Если осталось меньше часа, отменяем турнир
                    if now >= deadline:
                        logger.warning(f"Tournament {tournament['id']} has less than 2 participants and less than 1 hour left, cancelling")
                        
                        # Отменяем турнир из-за недостаточного количества участников
                        cursor.execute(
                            "UPDATE tournaments SET status = 'cancelled', cancellation_reason = ? WHERE id = ?",
                            ("Недостаточно участников для проведения турнира", tournament['id'])
                        )
                        
                        # Получаем список участников для уведомления
                        cursor.execute(
                            "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                            (tournament['id'],)
                        )
                        
                        participants = cursor.fetchall()
                        
                        # Отправляем уведомление об отмене турнира
                        channel_id = PRIVATE_TOURNAMENTS_CHANNEL
                        channel = self.bot.get_channel(channel_id)
                        
                        if channel:
                            embed = discord.Embed(
                                title=f"❌ Турнир отменен: {tournament['name']}",
                                description=f"Турнир был автоматически отменен из-за недостаточного количества участников.",
                                color=0xE74C3C  # Red
                            )
                            
                            embed.add_field(name="Организатор", value=f"<@{tournament['creator_id']}>", inline=True)
                            embed.add_field(name="Минимальное количество участников", value="2", inline=True)
                            embed.add_field(name="Зарегистрировано", value=str(count), inline=True)
                            
                            # Упоминаем всех зарегистрированных участников и создателя
                            mentions = ' '.join([f"<@{p['user_id']}>" for p in participants])
                            if tournament.get('creator_id'):
                                mentions += f" <@{tournament['creator_id']}>"
                                
                            await channel.send(mentions, embed=embed)
            
            else:
                # Для командных турниров
                cursor.execute(
                    "SELECT COUNT(*) as count FROM tournament_teams WHERE tournament_id = ?",
                    (tournament['id'],)
                )
                
                count = cursor.fetchone()['count']
                
                # Нужно минимум 2 команды
                if count < 2:
                    deadline = datetime.datetime.strptime(tournament['tournament_date'], "%Y-%m-%d %H:%M:%S") - datetime.timedelta(hours=1)
                    now = datetime.datetime.now()
                    
                    # Если осталось меньше часа, отменяем турнир
                    if now >= deadline:
                        logger.warning(f"Tournament {tournament['id']} has less than 2 teams and less than 1 hour left, cancelling")
                        
                        # Отменяем турнир из-за недостаточного количества команд
                        cursor.execute(
                            "UPDATE tournaments SET status = 'cancelled', cancellation_reason = ? WHERE id = ?",
                            ("Недостаточно команд для проведения турнира", tournament['id'])
                        )
                        
                        # Отправляем уведомление об отмене турнира
                        channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                        channel = self.bot.get_channel(channel_id)
                        
                        if channel:
                            embed = discord.Embed(
                                title=f"❌ Турнир отменен: {tournament['name']}",
                                description=f"Турнир был автоматически отменен из-за недостаточного количества команд.",
                                color=0xE74C3C  # Red
                            )
                            
                            embed.add_field(name="Организатор", value=f"<@{tournament['creator_id']}>", inline=True)
                            embed.add_field(name="Минимальное количество команд", value="2", inline=True)
                            embed.add_field(name="Зарегистрировано", value=str(count), inline=True)
                            
                            # Уведомляем о проблеме и упоминаем создателя
                            mentions = ""
                            if tournament.get('creator_id'):
                                mentions = f"<@{tournament['creator_id']}>"
                                
                            await channel.send(mentions, embed=embed)
        
        # Сохраняем изменения
        db.commit()
    
    @check_upcoming_tournaments.before_loop
    async def before_check_upcoming_tournaments(self):
        # Wait until the bot is ready
        await self.bot.wait_until_ready()
        
        # Логируем, что задача запущена
        logger.info("check_upcoming_tournaments task is initialized and will be running periodically")
    
    @app_commands.command(
        name="tournament-create-private",
        description="Создать частный турнир (напр., 'Король ревиков')"
    )
    @app_commands.describe(
        name="Название турнира",
        weapon_type="Тип оружия",
        match_type="Тип матчей: BO1 (до 1 победы), BO3 (до 2 побед), BO5 (до 3 побед), BO7 (до 4 побед)",
        entry_fee="Вступительный взнос (опционально)",
        tournament_date="Дата и время проведения (ДД.ММ.ГГГГ ЧЧ:ММ)",
        max_participants="Максимальное количество участников"
    )
    async def tournament_create_private(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        weapon_type: str, 
        match_type: str,
        tournament_date: str,
        max_participants: int,
        entry_fee: Optional[int] = 0
    ):
        # Проверяем, не обрабатывали ли мы уже это взаимодействие
        interaction_id = str(interaction.id)
        if interaction_id in self.processed_interactions:
            logger.warning(f"Skipping duplicate interaction {interaction_id}")
            return
            
        # Помечаем взаимодействие как обработанное
        self.processed_interactions.add(interaction_id)
        logger.info(f"Processing private tournament creation, interaction ID: {interaction_id}")
        
        try:
            # Parse date
            try:
                parsed_date = datetime.datetime.strptime(tournament_date, "%d.%m.%Y %H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "Некорректный формат даты. Используйте формат ДД.ММ.ГГГГ ЧЧ:ММ (например: 20.05.2025 21:00)", 
                    ephemeral=True
                )
                return
                
            # Validate inputs
            if len(name) < 3 or len(name) > 100:
                await interaction.response.send_message("Название турнира должно содержать от 3 до 100 символов.", ephemeral=True)
                return
                
            if len(weapon_type) < 2 or len(weapon_type) > 50:
                await interaction.response.send_message("Тип оружия должен содержать от 2 до 50 символов.", ephemeral=True)
                return
                
            if max_participants < 2:
                await interaction.response.send_message("Количество участников должно быть не менее 2.", ephemeral=True)
                return
                
            if entry_fee < 0:
                await interaction.response.send_message("Вступительный взнос не может быть отрицательным.", ephemeral=True)
                return
                
            # Check if date is in the future
            if parsed_date <= datetime.datetime.now():
                await interaction.response.send_message("Дата турнира должна быть в будущем.", ephemeral=True)
                return
            
            # Get database connection
            db = get_db()
            cursor = db.cursor()
            
            # Проверка типа матча
            valid_types = ["BO1", "BO3", "BO5", "BO7"]
            if match_type.upper() not in valid_types:
                await interaction.response.send_message(
                    f"Неверный тип матчей. Поддерживаемые типы: {', '.join(valid_types)}",
                    ephemeral=True
                )
                return
            
            # Create tournament in the database
            cursor.execute(
                """
                INSERT INTO tournaments 
                (name, type, weapon_type, entry_fee, tournament_date, max_participants, creator_id, status, creation_date, match_type) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, 
                    'private', 
                    weapon_type,
                    entry_fee,
                    parsed_date.strftime('%Y-%m-%d %H:%M:%S'),
                    max_participants,
                    interaction.user.id,
                    'pending',
                    datetime.datetime.now(),
                    match_type.upper()
                )
            )
            
            tournament_id = cursor.lastrowid
            
            # Add creator to players table if not exists
            cursor.execute(
                "INSERT OR IGNORE INTO players (user_id, username) VALUES (?, ?)",
                (interaction.user.id, interaction.user.name)
            )
            
            db.commit()
            
            # Create embed for moderation
            embed = discord.Embed(
                title=f"🔹 Заявка на новый частный турнир",
                description=f"Создатель: {interaction.user.mention}",
                color=0x9B59B6  # Purple
            )
            
            embed.add_field(name="Название", value=name, inline=True)
            embed.add_field(name="Тип оружия", value=weapon_type, inline=True)
            embed.add_field(name="Тип матчей", value=match_type.upper(), inline=True)
            embed.add_field(name="Дата", value=tournament_date, inline=True)
            embed.add_field(name="Макс. участников", value=str(max_participants), inline=True)
            embed.add_field(name="Вступительный взнос", value=f"{entry_fee}$" if entry_fee > 0 else "Нет", inline=True)
            
            # Send to moderation channel
            approval_channel = self.bot.get_channel(TOURNAMENT_APPROVAL_CHANNEL)
            if not approval_channel:
                logger.error(f"Approval channel {TOURNAMENT_APPROVAL_CHANNEL} not found")
                await interaction.response.send_message(
                    "Не удалось найти канал для модерации турниров. Обратитесь к администратору.", 
                    ephemeral=True
                )
                return
                
            await approval_channel.send(
                embed=embed,
                view=ApprovalView(tournament_id=tournament_id, bot=self.bot)
            )
            
            await interaction.response.send_message(
                "Заявка на создание турнира отправлена на модерацию. Вы получите уведомление, когда она будет рассмотрена.", 
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error creating private tournament: {e}")
            await interaction.response.send_message(
                "Произошла ошибка при создании турнира. Пожалуйста, попробуйте позже.", 
                ephemeral=True
            )
    
    @app_commands.command(
        name="tournament-create-public",
        description="Создать публичный турнир между организациями (напр., 'Копы vs Банды')"
    )
    @app_commands.describe(
        name="Название турнира",
        rules="Условия и правила турнира",
        match_type="Тип матчей: BO1 (до 1 победы), BO3 (до 2 побед), BO5 (до 3 побед), BO7 (до 4 побед)",
        participants_per_team="Количество участников от каждой стороны",
        tournament_date="Дата и время проведения (ДД.ММ.ГГГГ ЧЧ:ММ)",
        entry_fee="Вступительный взнос (опционально)"
    )
    async def tournament_create_public(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        rules: str,
        match_type: str,
        participants_per_team: int,
        tournament_date: str,
        entry_fee: Optional[int] = 0
    ):
        # Проверяем, не обрабатывали ли мы уже это взаимодействие
        interaction_id = str(interaction.id)
        if interaction_id in self.processed_interactions:
            logger.warning(f"Skipping duplicate interaction {interaction_id}")
            return
            
        # Помечаем взаимодействие как обработанное
        self.processed_interactions.add(interaction_id)
        logger.info(f"Processing public tournament creation, interaction ID: {interaction_id}")
        
        try:
            # Parse date
            try:
                parsed_date = datetime.datetime.strptime(tournament_date, "%d.%m.%Y %H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "Некорректный формат даты. Используйте формат ДД.ММ.ГГГГ ЧЧ:ММ (например: 20.05.2025 21:00)", 
                    ephemeral=True
                )
                return
                
            # Validate inputs
            if len(name) < 3 or len(name) > 100:
                await interaction.response.send_message("Название турнира должно содержать от 3 до 100 символов.", ephemeral=True)
                return
                
            if len(rules) < 10 or len(rules) > 1000:
                await interaction.response.send_message("Правила турнира должны содержать от 10 до 1000 символов.", ephemeral=True)
                return
                
            if participants_per_team < 1:
                await interaction.response.send_message("Количество участников от стороны должно быть не менее 1.", ephemeral=True)
                return
                
            if entry_fee < 0:
                await interaction.response.send_message("Вступительный взнос не может быть отрицательным.", ephemeral=True)
                return
                
            # Check if date is in the future
            if parsed_date <= datetime.datetime.now():
                await interaction.response.send_message("Дата турнира должна быть в будущем.", ephemeral=True)
                return
            
            # Get database connection
            db = get_db()
            cursor = db.cursor()
            
            # Валидация типа матча
            valid_types = ["BO1", "BO3", "BO5", "BO7"]
            if match_type.upper() not in valid_types:
                await interaction.response.send_message(
                    f"Неверный тип матчей. Поддерживаемые типы: {', '.join(valid_types)}",
                    ephemeral=True
                )
                return

            # Create tournament in the database - use max_participants as participants_per_team * 2 for now
            cursor.execute(
                """
                INSERT INTO tournaments 
                (name, type, rules, entry_fee, tournament_date, max_participants, participants_per_team, creator_id, status, creation_date, match_type) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, 
                    'public', 
                    rules,
                    entry_fee,
                    parsed_date.strftime('%Y-%m-%d %H:%M:%S'),
                    participants_per_team * 2,  # Max participants is participants per team * 2 teams
                    participants_per_team,
                    interaction.user.id,
                    'pending',
                    datetime.datetime.now(),
                    match_type.upper()
                )
            )
            
            tournament_id = cursor.lastrowid
            
            # Add creator to players table if not exists
            cursor.execute(
                "INSERT OR IGNORE INTO players (user_id, username) VALUES (?, ?)",
                (interaction.user.id, interaction.user.name)
            )
            
            db.commit()
            
            # Create embed for moderation
            embed = discord.Embed(
                title=f"🔹 Заявка на новый публичный турнир",
                description=f"Создатель: {interaction.user.mention}",
                color=0xE67E22  # Orange
            )
            
            embed.add_field(name="Название", value=name, inline=True)
            embed.add_field(name="Дата", value=tournament_date, inline=True)
            embed.add_field(name="Тип матчей", value=match_type.upper(), inline=True)
            embed.add_field(name="Участников от стороны", value=str(participants_per_team), inline=True)
            embed.add_field(name="Вступительный взнос", value=f"{entry_fee}$" if entry_fee > 0 else "Нет", inline=True)
            embed.add_field(name="Правила", value=rules, inline=False)
            
            # Send to moderation channel
            approval_channel = self.bot.get_channel(TOURNAMENT_APPROVAL_CHANNEL)
            if not approval_channel:
                logger.error(f"Approval channel {TOURNAMENT_APPROVAL_CHANNEL} not found")
                await interaction.response.send_message(
                    "Не удалось найти канал для модерации турниров. Обратитесь к администратору.", 
                    ephemeral=True
                )
                return
                
            await approval_channel.send(
                embed=embed,
                view=ApprovalView(tournament_id=tournament_id, bot=self.bot)
            )
            
            await interaction.response.send_message(
                "Заявка на создание публичного турнира отправлена на модерацию. Вы получите уведомление, когда она будет рассмотрена.", 
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error creating public tournament: {e}")
            await interaction.response.send_message(
                "Произошла ошибка при создании турнира. Пожалуйста, попробуйте позже.", 
                ephemeral=True
            )
    
    @app_commands.command(
        name="tournament-join-public",
        description="Зарегистрировать команду на публичный турнир"
    )
    @app_commands.describe(
        team_name="Название команды или фракции"
    )
    async def tournament_join_public(
        self,
        interaction: discord.Interaction,
        team_name: str
    ):
        # Проверяем, не обрабатывали ли мы уже это взаимодействие
        interaction_id = str(interaction.id)
        if interaction_id in self.processed_interactions:
            logger.warning(f"Skipping duplicate interaction {interaction_id}")
            return
            
        # Помечаем взаимодействие как обработанное
        self.processed_interactions.add(interaction_id)
        logger.info(f"Processing tournament registration, interaction ID: {interaction_id}")
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        # Get active public tournaments
        cursor.execute(
            """
            SELECT id, name FROM tournaments 
            WHERE type = 'public' AND status = 'approved' AND tournament_date > ?
            """,
            (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),)
        )
        
        active_tournaments = cursor.fetchall()
        
        if not active_tournaments:
            await interaction.response.send_message("В настоящее время нет активных публичных турниров.", ephemeral=True)
            return
            
        # Create a view for tournament selection
        view = discord.ui.View(timeout=300)
        
        # Add a select menu with tournaments
        select = discord.ui.Select(
            placeholder="Выберите турнир для регистрации",
            options=[
                discord.SelectOption(label=t['name'], value=str(t['id'])) 
                for t in active_tournaments
            ]
        )
        
        async def select_callback(interaction: discord.Interaction):
            # Get selected tournament
            tournament_id = int(select.values[0])
            
            # Check if the team is already registered
            cursor.execute(
                "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ? AND team_name = ?",
                (tournament_id, team_name)
            )
            
            if cursor.fetchone()[0] > 0:
                await interaction.response.send_message(f"Команда '{team_name}' уже зарегистрирована на этот турнир!", ephemeral=True)
                return
                
            # Check if there's room for more teams
            cursor.execute(
                """
                SELECT COUNT(*) as team_count, (SELECT participants_per_team FROM tournaments WHERE id = ?) as max_teams
                FROM tournament_teams
                WHERE tournament_id = ?
                """,
                (tournament_id, tournament_id)
            )
            
            result = cursor.fetchone()
            if result and result['team_count'] >= 2:  # Currently supporting only 2 teams
                await interaction.response.send_message("Все места для команд в этом турнире уже заняты!", ephemeral=True)
                return
            
            # Add team to tournament
            try:
                cursor.execute(
                    "INSERT INTO tournament_teams (tournament_id, team_name, captain_id, registration_date) VALUES (?, ?, ?, ?)",
                    (tournament_id, team_name, interaction.user.id, datetime.datetime.now())
                )
                
                db.commit()
                
                # Get tournament details
                cursor.execute("SELECT name FROM tournaments WHERE id = ?", (tournament_id,))
                tournament_name = cursor.fetchone()['name']
                
                # Create embed to notify mods for approval
                embed = discord.Embed(
                    title=f"🔹 Заявка на участие в публичном турнире",
                    description=f"Капитан: {interaction.user.mention}",
                    color=0xE67E22  # Orange
                )
                
                embed.add_field(name="Турнир", value=tournament_name, inline=True)
                embed.add_field(name="Команда", value=team_name, inline=True)
                
                # Send to moderation channel
                approval_channel = self.bot.get_channel(TOURNAMENT_APPROVAL_CHANNEL)
                if approval_channel:
                    await approval_channel.send(embed=embed)
                
                await interaction.response.send_message(
                    f"Заявка на участие команды '{team_name}' в турнире отправлена на рассмотрение.",
                    ephemeral=True
                )
                
            except Exception as e:
                logger.error(f"Error registering team for tournament: {e}")
                db.rollback()
                await interaction.response.send_message("Произошла ошибка при регистрации команды.", ephemeral=True)
        
        select.callback = select_callback
        view.add_item(select)
        
        await interaction.response.send_message("Выберите турнир для регистрации команды:", view=view, ephemeral=True)
        
    @app_commands.command(
        name="tournament-bracket",
        description="Показать турнирную сетку"
    )
    @app_commands.describe(
        tournament_id="ID турнира"
    )
    async def tournament_bracket(self, interaction: discord.Interaction, tournament_id: int):
        await interaction.response.defer(ephemeral=False)  # Откладываем ответ, но показываем его всем
        
        try:
            # Создаем турнирную сетку
            success, result = generate_tournament_bracket(tournament_id)
            
            if success:
                await interaction.followup.send(embed=result)
            else:
                await interaction.followup.send(result, ephemeral=True)
        except Exception as e:
            logger.error(f"Error displaying tournament bracket: {e}")
            await interaction.followup.send("Произошла ошибка при отображении турнирной сетки.", ephemeral=True)

    @app_commands.command(
        name="tournament-team-add",
        description="Добавить команду на публичный турнир (только для организаторов)"
    )
    @app_commands.describe(
        tournament_id="ID публичного турнира",
        team_name="Название команды",
        members="Участники команды через запятую, например: @user1, @user2, @user3"
    )
    @app_commands.check(is_tournament_manager)
    async def tournament_team_add(self, interaction: discord.Interaction, tournament_id: int, team_name: str, members: str):
        await interaction.response.defer(ephemeral=True)
        
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Проверяем, что турнир существует и является публичным
            cursor.execute(
                "SELECT * FROM tournaments WHERE id = ? AND type = 'public' AND status = 'approved'",
                (tournament_id,)
            )
            tournament = cursor.fetchone()
            
            if not tournament:
                await interaction.followup.send("Публичный турнир с указанным ID не найден или не подтвержден.", ephemeral=True)
                return
            
            # Проверяем, что команда с таким названием еще не зарегистрирована
            cursor.execute(
                "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ? AND team_name = ?",
                (tournament_id, team_name)
            )
            
            if cursor.fetchone()[0] > 0:
                await interaction.followup.send(f"Команда '{team_name}' уже зарегистрирована на этот турнир!", ephemeral=True)
                return
            
            # Извлекаем ID участников из строки с упоминаниями
            member_ids = []
            for member_mention in members.split(','):
                member_mention = member_mention.strip()
                if member_mention.startswith('<@') and member_mention.endswith('>'):
                    user_id = member_mention[2:-1]
                    if user_id.startswith('!'):
                        user_id = user_id[1:]
                    try:
                        member_ids.append(int(user_id))
                    except ValueError:
                        continue
            
            # Проверяем, что количество участников соответствует требованиям турнира
            if len(member_ids) != tournament['participants_per_team']:
                await interaction.followup.send(
                    f"Количество участников команды ({len(member_ids)}) не соответствует требованиям турнира ({tournament['participants_per_team']})",
                    ephemeral=True
                )
                return
            
            # Регистрируем команду
            cursor.execute(
                "INSERT INTO tournament_teams (tournament_id, team_name, captain_id, registration_date) VALUES (?, ?, ?, ?)",
                (tournament_id, team_name, member_ids[0], datetime.datetime.now())
            )
            
            team_id = cursor.lastrowid
            
            # Добавляем всех участников
            for user_id in member_ids:
                # Добавляем участника в таблицу players, если его еще нет
                cursor.execute(
                    "INSERT OR IGNORE INTO players (user_id, username) VALUES (?, ?)",
                    (user_id, f"User{user_id}")
                )
                
                # Добавляем участие в турнире
                cursor.execute(
                    "INSERT INTO tournament_participants (tournament_id, user_id, join_date) VALUES (?, ?, ?)",
                    (tournament_id, user_id, datetime.datetime.now())
                )
            
            db.commit()
            
            # Отправляем сообщение об успешной регистрации
            members_mentions = ", ".join([f"<@{user_id}>" for user_id in member_ids])
            await interaction.followup.send(
                f"✅ Команда '{team_name}' успешно зарегистрирована на турнир #{tournament_id}!\n"
                f"Участники: {members_mentions}",
                ephemeral=False
            )
            
            # Обновляем сообщение с анонсом турнира
            channel = self.bot.get_channel(PUBLIC_TOURNAMENTS_CHANNEL)
            if channel:
                try:
                    async for message in channel.history(limit=200):
                        for embed in message.embeds:
                            if embed.fields and any(field.name == "ID Турнира" and field.value == f"#{tournament_id}" for field in embed.fields):
                                # Получаем количество зарегистрированных команд
                                cursor.execute(
                                    "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ?",
                                    (tournament_id,)
                                )
                                team_count = cursor.fetchone()[0]
                                
                                # Обновляем embed с новым количеством команд
                                new_embed = discord.Embed(
                                    title=embed.title,
                                    description=embed.description,
                                    color=embed.color
                                )
                                
                                for field in embed.fields:
                                    if field.name == "Зарегистрировано команд":
                                        new_embed.add_field(name=field.name, value=f"{team_count}", inline=field.inline)
                                    else:
                                        new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
                                
                                await message.edit(embed=new_embed)
                                break
                except Exception as e:
                    logger.error(f"Error updating tournament message: {e}")
            
        except Exception as e:
            logger.error(f"Error registering team: {e}")
            db.rollback()
            await interaction.followup.send(f"Произошла ошибка при регистрации команды: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tournaments(bot))
