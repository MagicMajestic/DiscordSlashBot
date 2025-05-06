import discord
import logging
import asyncio
import datetime
from discord import app_commands
from discord.ext import commands
from typing import Optional
from utils.db import get_db
from utils.permissions import is_tournament_manager, is_admin
from utils.embeds import create_match_result_embed
from utils.constants import TOURNAMENT_RESULTS_CHANNEL, PRIVATE_TOURNAMENTS_CHANNEL, PUBLIC_TOURNAMENTS_CHANNEL

logger = logging.getLogger(__name__)

class TournamentResultModal(discord.ui.Modal):
    score_team1 = discord.ui.TextInput(
        label="Очки команды 1",
        style=discord.TextStyle.short,
        placeholder="Введите количество очков...",
        required=True,
        min_length=1,
        max_length=5
    )
    
    score_team2 = discord.ui.TextInput(
        label="Очки команды 2",
        style=discord.TextStyle.short,
        placeholder="Введите количество очков...",
        required=True,
        min_length=1,
        max_length=5
    )
    
    notes = discord.ui.TextInput(
        label="Заметки",
        style=discord.TextStyle.paragraph,
        placeholder="Дополнительная информация о матче (опционально)",
        required=False,
        max_length=1000
    )
    
    def __init__(self, match_id: int):
        # Получаем информацию о матче и формате матча
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute(
                """
                SELECT t.match_type, t.name
                FROM tournament_matches m
                JOIN tournaments t ON m.tournament_id = t.id
                WHERE m.id = ?
                """,
                (match_id,)
            )
            match_info = cursor.fetchone()
            match_type = match_info['match_type'] if match_info else 'BO1'
            tournament_name = match_info['name'] if match_info else ''
            
            title = f"Результат матча ({match_type})"
            if tournament_name:
                title += f" - {tournament_name}"
        except Exception as e:
            logger.error(f"Error getting match info: {e}")
            title = "Результат матча"
            match_type = 'BO1'
        
        # Обновляем подсказку для поля ввода в зависимости от типа матча
        super().__init__(title=title)
        self.match_id = match_id
        
        # Обновляем подсказку в зависимости от типа матча
        wins_needed = 1
        if match_type == 'BO3':
            wins_needed = 2
            self.score_team1.placeholder = f"Введите кол-во побед (нужно {wins_needed} для победы)"
            self.score_team2.placeholder = f"Введите кол-во побед (нужно {wins_needed} для победы)"
        elif match_type == 'BO5':
            wins_needed = 3
            self.score_team1.placeholder = f"Введите кол-во побед (нужно {wins_needed} для победы)"
            self.score_team2.placeholder = f"Введите кол-во побед (нужно {wins_needed} для победы)"
        elif match_type == 'BO7':
            wins_needed = 4
            self.score_team1.placeholder = f"Введите кол-во побед (нужно {wins_needed} для победы)"
            self.score_team2.placeholder = f"Введите кол-во побед (нужно {wins_needed} для победы)"
        else:
            self.score_team1.placeholder = "Введите количество очков..."
            self.score_team2.placeholder = "Введите количество очков..."
        
    async def on_submit(self, interaction: discord.Interaction):
        # Verify permissions
        if not await is_tournament_manager(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        try:
            score_team1 = int(self.score_team1.value)
            score_team2 = int(self.score_team2.value)
        except ValueError:
            await interaction.response.send_message("Очки должны быть целыми числами!", ephemeral=True)
            return
            
        if score_team1 < 0 or score_team2 < 0:
            await interaction.response.send_message("Очки не могут быть отрицательными!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Update match result
            cursor.execute(
                """
                UPDATE tournament_matches 
                SET team1_score = ?, team2_score = ?, notes = ?, completed = 1, completion_date = ?
                WHERE id = ?
                """,
                (score_team1, score_team2, self.notes.value, datetime.datetime.now(), self.match_id)
            )
            
            # Get match and tournament details
            cursor.execute(
                """
                SELECT m.*, t.name as tournament_name, t.id as tournament_id, t.match_type,
                       team1.team_name as team1_name, team2.team_name as team2_name
                FROM tournament_matches m
                JOIN tournaments t ON m.tournament_id = t.id
                LEFT JOIN tournament_teams team1 ON m.team1_id = team1.id
                LEFT JOIN tournament_teams team2 ON m.team2_id = team2.id
                WHERE m.id = ?
                """,
                (self.match_id,)
            )
            
            match = cursor.fetchone()
            
            if not match:
                await interaction.response.send_message("Матч не найден!", ephemeral=True)
                return
                
            # Determine winner based on match type
            winner_id = None
            match_type = match.get('match_type', 'BO1')
            
            # Определяем нужное количество побед в зависимости от типа матча
            wins_needed = 1  # Default for BO1
            if match_type == 'BO3':
                wins_needed = 2
            elif match_type == 'BO5':
                wins_needed = 3
            elif match_type == 'BO7':
                wins_needed = 4
            
            # Проверяем, есть ли победитель
            if score_team1 >= wins_needed:
                winner_id = match['team1_id']
                loser_id = match['team2_id']
            elif score_team2 >= wins_needed:
                winner_id = match['team2_id']
                loser_id = match['team1_id']
            
            # If this is a private tournament (1v1), update player stats
            if match.get('team1_id') is None and match.get('team2_id') is None:
                # Get player IDs
                cursor.execute(
                    "SELECT player1_id, player2_id FROM tournament_matches WHERE id = ?",
                    (self.match_id,)
                )
                player_match = cursor.fetchone()
                
                if player_match:
                    player1_id = player_match['player1_id']
                    player2_id = player_match['player2_id']
                    
                    # Determine winner based on match type for player tournament
                    match_type = match.get('match_type', 'BO1')
                    
                    # Определяем нужное количество побед в зависимости от типа матча
                    wins_needed = 1  # Default for BO1
                    if match_type == 'BO3':
                        wins_needed = 2
                    elif match_type == 'BO5':
                        wins_needed = 3
                    elif match_type == 'BO7':
                        wins_needed = 4
                    
                    # Проверяем, есть ли победитель
                    if score_team1 >= wins_needed:
                        winner_id = player1_id
                        loser_id = player2_id
                    elif score_team2 >= wins_needed:
                        winner_id = player2_id
                        loser_id = player1_id
                    
                    # Check if this is a duel tournament (only 2 players) in BO3/BO5/BO7 format
                    cursor.execute(
                        """
                        SELECT t.match_type, COUNT(DISTINCT p.user_id) as player_count,
                               SUM(CASE WHEN m.player1_id = ? AND m.team1_score > m.team2_score THEN 1 ELSE 0 END) as player1_wins,
                               SUM(CASE WHEN m.player2_id = ? AND m.team2_score > m.team1_score THEN 1 ELSE 0 END) as player2_wins
                        FROM tournaments t
                        JOIN tournament_participants p ON t.id = p.tournament_id
                        LEFT JOIN tournament_matches m ON t.id = m.tournament_id AND m.completed = 1
                        WHERE t.id = ? AND t.match_type IN ('BO3', 'BO5', 'BO7')
                        GROUP BY t.id
                        """,
                        (player1_id, player2_id, match['tournament_id'])
                    )
                    
                    tournament_data = cursor.fetchone()
                    is_duel_tournament = tournament_data and tournament_data['player_count'] == 2
                    
                    if is_duel_tournament:
                        logger.info(f"Duel tournament detected: {match['tournament_id']}, match_type: {tournament_data['match_type']}")
                        
                        # Получаем количество побед для каждого игрока
                        player1_wins = tournament_data['player1_wins'] or 0
                        player2_wins = tournament_data['player2_wins'] or 0
                        
                        logger.info(f"Current score: Player1 ({player1_id}) - {player1_wins} wins, Player2 ({player2_id}) - {player2_wins} wins")
                        
                        # Если текущий матч выиграл первый игрок
                        if score_team1 > score_team2:
                            player1_wins += 1
                        # Если текущий матч выиграл второй игрок
                        elif score_team2 > score_team1:
                            player2_wins += 1
                            
                        logger.info(f"Updated score: Player1 - {player1_wins} wins, Player2 - {player2_wins} wins")
                        
                        # Проверяем, достаточно ли побед для завершения дуэли
                        if player1_wins >= wins_needed:
                            logger.info(f"Player1 ({player1_id}) has won the duel tournament with {player1_wins} wins")
                            winner_id = player1_id
                            loser_id = player2_id
                        elif player2_wins >= wins_needed:
                            logger.info(f"Player2 ({player2_id}) has won the duel tournament with {player2_wins} wins")
                            winner_id = player2_id
                            loser_id = player1_id
                    
                    # Update player stats if there's a winner
                    if winner_id:
                        # Update winner stats
                        cursor.execute(
                            "UPDATE players SET wins = wins + 1 WHERE user_id = ?",
                            (winner_id,)
                        )
                        
                        # Update loser stats
                        cursor.execute(
                            "UPDATE players SET losses = losses + 1 WHERE user_id = ?",
                            (loser_id,)
                        )
                        
                        # Если это дуэльный турнир и кто-то выиграл, обновляем статус турнира
                        if is_duel_tournament and (player1_wins >= wins_needed or player2_wins >= wins_needed):
                            logger.info(f"Updating tournament {match['tournament_id']} as completed with winner {winner_id}")
                            cursor.execute(
                                "UPDATE tournaments SET winner_id = ?, status = 'completed' WHERE id = ?",
                                (winner_id, match['tournament_id'])
                            )
                        
                        # Get tournament type
                        cursor.execute(
                            "SELECT type FROM tournaments WHERE id = ?",
                            (match['tournament_id'],)
                        )
                        tournament = cursor.fetchone()
                        tournament_type = tournament['type'] if tournament else 'private'
                        
                        # Update player_stats table
                        cursor.execute(
                            "INSERT INTO player_stats (user_id, tournament_id, place, tournament_type) VALUES (?, ?, ?, ?)",
                            (winner_id, match['tournament_id'], 1, tournament_type)
                        )
                        
                        cursor.execute(
                            "INSERT INTO player_stats (user_id, tournament_id, place, tournament_type) VALUES (?, ?, ?, ?)",
                            (loser_id, match['tournament_id'], 2, tournament_type)
                        )
                        
                        # Check for achievements
                        await self.check_achievements(interaction.client, winner_id, match['tournament_id'], cursor)
            
            # Commit changes
            db.commit()
            
            # Create result embed
            embed = create_match_result_embed(match, score_team1, score_team2)
            
            # Send to results channel
            results_channel = interaction.client.get_channel(TOURNAMENT_RESULTS_CHANNEL)
            if results_channel:
                # Получаем информацию о турнире
                cursor.execute("SELECT * FROM tournaments WHERE id = ?", (match['tournament_id'],))
                tournament = cursor.fetchone()
                
                # Добавляем эмбед с информацией о типе матча
                match_info = ""
                if tournament:
                    match_type = tournament.get('match_type', 'BO1')
                    if match_type == 'BO1':
                        match_info = "Одиночный матч"
                    elif match_type == 'BO3':
                        match_info = f"Матч до 2 побед ({match_type})"
                    elif match_type == 'BO5':
                        match_info = f"Матч до 3 побед ({match_type})"
                    elif match_type == 'BO7':
                        match_info = f"Матч до 4 побед ({match_type})"
                    
                    # Добавляем информацию о формате матча
                    embed.add_field(name="Формат матча", value=match_info, inline=False)
                
                # Отправляем уведомление о результатах
                await results_channel.send(embed=embed)
                
                # Обновляем и публикуем сетку турнира
                if tournament:
                    from utils.brackets import generate_tournament_bracket
                    success, bracket = generate_tournament_bracket(match['tournament_id'])
                    
                    if success:
                        await results_channel.send(embed=bracket)
            
            await interaction.response.send_message("Результаты матча успешно сохранены!", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error setting match result: {e}")
            db.rollback()
            await interaction.response.send_message("Произошла ошибка при сохранении результатов.", ephemeral=True)
    
    async def check_achievements(self, bot, user_id, tournament_id, cursor):
        """Check if player earned any achievements and award them if needed."""
        # Check for revolver tournament wins ("Король ревиков")
        cursor.execute(
            """
            SELECT COUNT(*) as wins FROM player_stats ps
            JOIN tournaments t ON ps.tournament_id = t.id
            WHERE ps.user_id = ? AND ps.place = 1
            AND (t.weapon_type LIKE '%револьвер%' OR t.weapon_type LIKE '%revolver%')
            """,
            (user_id,)
        )
        
        revolver_wins = cursor.fetchone()['wins']
        
        if revolver_wins >= 3:
            # Check if already has achievement
            cursor.execute(
                "SELECT COUNT(*) FROM player_achievements WHERE user_id = ? AND achievement_id = 1",
                (user_id,)
            )
            
            if cursor.fetchone()[0] == 0:
                # Award achievement
                cursor.execute(
                    "INSERT INTO player_achievements (user_id, achievement_id, earned_date) VALUES (?, 1, ?)",
                    (user_id, datetime.datetime.now())
                )
                
                # Notify player
                try:
                    user = await bot.fetch_user(user_id)
                    embed = discord.Embed(
                        title="🏆 Достижение разблокировано!",
                        description="Вы получили достижение **Король ревиков**!",
                        color=0xF1C40F  # Gold
                    )
                    embed.add_field(name="Описание", value="Выиграйте 3 турнира с револьверами")
                    
                    await user.send(embed=embed)
                except:
                    logger.error(f"Could not send achievement notification to user {user_id}")
        
        # Check for sniper tournament win
        cursor.execute(
            """
            SELECT COUNT(*) as wins FROM player_stats ps
            JOIN tournaments t ON ps.tournament_id = t.id
            WHERE ps.user_id = ? AND ps.place = 1
            AND (t.weapon_type LIKE '%снайпер%' OR t.weapon_type LIKE '%sniper%')
            """,
            (user_id,)
        )
        
        sniper_wins = cursor.fetchone()['wins']
        
        if sniper_wins >= 1:
            # Check if already has achievement
            cursor.execute(
                "SELECT COUNT(*) FROM player_achievements WHERE user_id = ? AND achievement_id = 2",
                (user_id,)
            )
            
            if cursor.fetchone()[0] == 0:
                # Award achievement
                cursor.execute(
                    "INSERT INTO player_achievements (user_id, achievement_id, earned_date) VALUES (?, 2, ?)",
                    (user_id, datetime.datetime.now())
                )
                
                # Notify player
                try:
                    user = await bot.fetch_user(user_id)
                    embed = discord.Embed(
                        title="🏆 Достижение разблокировано!",
                        description="Вы получили достижение **Снайпер-легенда**!",
                        color=0xF1C40F  # Gold
                    )
                    embed.add_field(name="Описание", value="Выиграйте снайперский турнир")
                    
                    await user.send(embed=embed)
                except:
                    logger.error(f"Could not send achievement notification to user {user_id}")
        
        # Check for consecutive wins
        cursor.execute(
            """
            SELECT tournament_id, place
            FROM player_stats
            WHERE user_id = ?
            ORDER BY tournament_id DESC
            LIMIT 5
            """,
            (user_id,)
        )
        
        results = cursor.fetchall()
        consecutive_wins = 0
        
        for result in results:
            if result['place'] == 1:
                consecutive_wins += 1
            else:
                break
                
        if consecutive_wins >= 5:
            # Check if already has achievement
            cursor.execute(
                "SELECT COUNT(*) FROM player_achievements WHERE user_id = ? AND achievement_id = 3",
                (user_id,)
            )
            
            if cursor.fetchone()[0] == 0:
                # Award achievement
                cursor.execute(
                    "INSERT INTO player_achievements (user_id, achievement_id, earned_date) VALUES (?, 3, ?)",
                    (user_id, datetime.datetime.now())
                )
                
                # Notify player
                try:
                    user = await bot.fetch_user(user_id)
                    embed = discord.Embed(
                        title="🏆 Достижение разблокировано!",
                        description="Вы получили достижение **Турнирный зверь**!",
                        color=0xF1C40F  # Gold
                    )
                    embed.add_field(name="Описание", value="Выиграйте 5 турниров подряд")
                    
                    await user.send(embed=embed)
                except:
                    logger.error(f"Could not send achievement notification to user {user_id}")


class TournamentRescheduleModal(discord.ui.Modal):
    new_date = discord.ui.TextInput(
        label="Новая дата и время",
        style=discord.TextStyle.short,
        placeholder="Введите в формате ДД.ММ.ГГГГ ЧЧ:ММ (напр.: 20.05.2025 21:00)",
        required=True,
        min_length=16,
        max_length=16
    )
    
    reason = discord.ui.TextInput(
        label="Причина переноса",
        style=discord.TextStyle.paragraph,
        placeholder="Укажите причину переноса турнира...",
        required=True,
        max_length=1000
    )
    
    def __init__(self, tournament_id: int):
        super().__init__(title="Перенос турнира")
        self.tournament_id = tournament_id
        
    async def on_submit(self, interaction: discord.Interaction):
        # Сначала отложим ответ на взаимодействие
        await interaction.response.defer(ephemeral=True)
        
        # Verify permissions
        if not await is_tournament_manager(interaction) and not await is_admin(interaction):
            await interaction.followup.send("У вас нет прав для этого действия!", ephemeral=True)
            return
        
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Parse new date
            try:
                parsed_date = datetime.datetime.strptime(self.new_date.value, "%d.%m.%Y %H:%M")
            except ValueError:
                await interaction.followup.send(
                    "Некорректный формат даты. Используйте формат ДД.ММ.ГГГГ ЧЧ:ММ (например: 20.05.2025 21:00)", 
                    ephemeral=True
                )
                return
                
            # Check if date is in the future
            if parsed_date <= datetime.datetime.now():
                await interaction.followup.send("Дата турнира должна быть в будущем.", ephemeral=True)
                return
            
            # Check if tournament exists
            cursor.execute("SELECT * FROM tournaments WHERE id = ?", (self.tournament_id,))
            tournament = cursor.fetchone()
            
            if not tournament:
                await interaction.followup.send(f"Турнир с ID {self.tournament_id} не найден!", ephemeral=True)
                return
            
            # Store old date for notification
            old_date = None
            if 'tournament_date' in tournament:
                if isinstance(tournament['tournament_date'], str):
                    old_date = tournament['tournament_date']
                else:
                    old_date = tournament['tournament_date'].strftime("%d.%m.%Y, %H:%M")
            
            # Update tournament date
            cursor.execute(
                "UPDATE tournaments SET tournament_date = ? WHERE id = ?",
                (parsed_date.strftime('%Y-%m-%d %H:%M:%S'), self.tournament_id)
            )
            
            db.commit()
            
            # Get participants to notify them
            cursor.execute(
                "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                (self.tournament_id,)
            )
            
            participants = cursor.fetchall()
            
            # Create notification embed
            embed = discord.Embed(
                title=f"Турнир перенесен: {tournament['name']}",
                description=f"Турнир был перенесен на новую дату.",
                color=0x3498DB  # Blue
            )
            
            embed.add_field(name="ID Турнира", value=f"#{self.tournament_id}", inline=True)
            
            if old_date:
                embed.add_field(name="Старая дата", value=old_date, inline=True)
                
            embed.add_field(name="Новая дата", value=self.new_date.value, inline=True)
            embed.add_field(name="Причина", value=self.reason.value, inline=False)
            embed.add_field(name="Действие выполнено", value=f"<@{interaction.user.id}>", inline=False)
            
            # Notify participants via DM
            participant_mentions = ""
            for participant in participants:
                try:
                    user = await interaction.client.fetch_user(participant['user_id'])
                    if user:
                        participant_mentions += f"<@{participant['user_id']}> "
                        await user.send(embed=embed)
                except Exception as e:
                    logger.error(f"Could not send DM to user {participant['user_id']}: {e}")
            
            # Send notification to the appropriate channel based on tournament type
            if tournament['type'] == 'private':
                channel_id = PRIVATE_TOURNAMENTS_CHANNEL
            else:
                channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                
            channel = interaction.client.get_channel(channel_id)
            if channel:
                await channel.send(content=f"**ВНИМАНИЕ! ТУРНИР ПЕРЕНЕСЕН!** {participant_mentions}", embed=embed)
            
            await interaction.followup.send("Турнир успешно перенесен на новую дату! Участники уведомлены.", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error rescheduling tournament: {e}")
            db.rollback()
            await interaction.followup.send("Произошла ошибка при переносе турнира.", ephemeral=True)


class TournamentCancelModal(discord.ui.Modal):
    reason = discord.ui.TextInput(
        label="Причина отмены",
        style=discord.TextStyle.paragraph,
        placeholder="Укажите причину отмены турнира...",
        required=True,
        max_length=1000
    )
    
    def __init__(self, tournament_id: int):
        super().__init__(title="Отмена турнира")
        self.tournament_id = tournament_id
        
    async def on_submit(self, interaction: discord.Interaction):
        # Сначала отложим ответ на взаимодействие
        await interaction.response.defer(ephemeral=True)
        
        # Verify permissions
        if not await is_tournament_manager(interaction) and not await is_admin(interaction):
            await interaction.followup.send("У вас нет прав для этого действия!", ephemeral=True)
            return
        
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Check if tournament exists
            cursor.execute("SELECT * FROM tournaments WHERE id = ?", (self.tournament_id,))
            tournament = cursor.fetchone()
            
            if not tournament:
                await interaction.followup.send(f"Турнир с ID {self.tournament_id} не найден!", ephemeral=True)
                return
            
            # Проверяем, что турнир не завершен
            if tournament['status'] == 'completed':
                await interaction.followup.send("Нельзя отменить завершенный турнир!", ephemeral=True)
                return
            
            # Меняем статус турнира на 'cancelled'
            cursor.execute(
                "UPDATE tournaments SET status = 'cancelled', cancellation_reason = ? WHERE id = ?",
                (self.reason.value, self.tournament_id)
            )
            
            # Получаем список участников для уведомления
            cursor.execute(
                "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                (self.tournament_id,)
            )
            
            participants = cursor.fetchall()
            
            # Создаем эмбед с уведомлением об отмене
            embed = discord.Embed(
                title=f"Турнир отменен: {tournament['name']}",
                description=f"Турнир ID {self.tournament_id} был отменен.",
                color=0xE74C3C  # Красный - для отмены
            )
            
            embed.add_field(name="ID Турнира", value=f"#{self.tournament_id}", inline=True)
            embed.add_field(name="Название", value=tournament['name'], inline=True)
            
            # Добавляем информацию о дате турнира
            if 'tournament_date' in tournament:
                if isinstance(tournament['tournament_date'], str):
                    tournament_date = tournament['tournament_date']
                else:
                    tournament_date = tournament['tournament_date'].strftime("%d.%m.%Y, %H:%M")
                embed.add_field(name="Дата", value=tournament_date, inline=True)
            
            embed.add_field(name="Причина отмены", value=self.reason.value, inline=False)
            embed.add_field(name="Действие выполнено", value=f"<@{interaction.user.id}>", inline=False)
            
            # Уведомляем участников через DM
            participant_mentions = ""
            for participant in participants:
                try:
                    user = await interaction.client.fetch_user(participant['user_id'])
                    if user:
                        participant_mentions += f"<@{participant['user_id']}> "
                        await user.send(embed=embed)
                except Exception as e:
                    logger.error(f"Could not send DM to user {participant['user_id']}: {e}")
            
            # Отправляем уведомление в соответствующий канал
            if tournament['type'] == 'private':
                channel_id = PRIVATE_TOURNAMENTS_CHANNEL
            else:
                channel_id = PUBLIC_TOURNAMENTS_CHANNEL
                
            channel = interaction.client.get_channel(channel_id)
            if channel:
                await channel.send(content=f"**ВНИМАНИЕ! ТУРНИР ОТМЕНЕН!** {participant_mentions}", embed=embed)
            
            db.commit()
            await interaction.followup.send("Турнир успешно отменен. Участники уведомлены.", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error cancelling tournament: {e}")
            db.rollback()
            await interaction.followup.send("Произошла ошибка при отмене турнира.", ephemeral=True)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.processed_interactions = set()
    
    @app_commands.command(
        name="tournament-cancel",
        description="Отменить турнир"
    )
    @app_commands.describe(
        tournament_id="ID турнира"
    )
    async def tournament_cancel(self, interaction: discord.Interaction, tournament_id: int):
        # Verify permissions
        if not await is_tournament_manager(interaction) and not await is_admin(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        # Check if tournament exists
        cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        tournament = cursor.fetchone()
        
        if not tournament:
            await interaction.response.send_message(f"Турнир с ID {tournament_id} не найден!", ephemeral=True)
            return
        
        # Check if tournament is completed or already cancelled
        if tournament['status'] == 'completed':
            await interaction.response.send_message("Нельзя отменить завершенный турнир!", ephemeral=True)
            return
        
        if tournament['status'] == 'cancelled':
            await interaction.response.send_message("Этот турнир уже отменен!", ephemeral=True)
            return
            
        # Create a modal for cancellation reason
        modal = TournamentCancelModal(tournament_id)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(
        name="tournament-reschedule",
        description="Перенести турнир на другую дату"
    )
    @app_commands.describe(
        tournament_id="ID турнира"
    )
    async def tournament_reschedule(self, interaction: discord.Interaction, tournament_id: int):
        # Verify permissions
        if not await is_tournament_manager(interaction) and not await is_admin(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        # Check if tournament exists
        cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        tournament = cursor.fetchone()
        
        if not tournament:
            await interaction.response.send_message(f"Турнир с ID {tournament_id} не найден!", ephemeral=True)
            return
        
        # Check if tournament is completed
        if tournament['status'] == 'completed':
            await interaction.response.send_message("Нельзя перенести завершенный турнир!", ephemeral=True)
            return
            
        # Create a modal for new date and reason
        modal = TournamentRescheduleModal(tournament_id)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(
        name="tournament-set-result",
        description="Установить результат матча"
    )
    @app_commands.describe(
        match_id="ID матча"
    )
    async def tournament_set_result(self, interaction: discord.Interaction, match_id: int):
        # Verify permissions
        if not await is_tournament_manager(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        # Check if match exists
        cursor.execute("SELECT * FROM tournament_matches WHERE id = ?", (match_id,))
        match = cursor.fetchone()
        
        if not match:
            await interaction.response.send_message(f"Матч с ID {match_id} не найден!", ephemeral=True)
            return
            
        if match['completed'] == 1:
            await interaction.response.send_message("Этот матч уже завершен!", ephemeral=True)
            return
            
        # Show modal for entering results
        modal = TournamentResultModal(match_id)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(
        name="tournament-penalty",
        description="Выдать штраф игроку или команде"
    )
    @app_commands.describe(
        user="Игрок, которому выдается штраф",
        points="Количество штрафных очков",
        reason="Причина штрафа"
    )
    async def tournament_penalty(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member, 
        points: int,
        reason: str
    ):
        # Verify permissions
        if not await is_tournament_manager(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        if points <= 0:
            await interaction.response.send_message("Количество штрафных очков должно быть положительным числом!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Record penalty
            cursor.execute(
                """
                INSERT INTO player_penalties (user_id, points, reason, issued_by, issue_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user.id, points, reason, interaction.user.id, datetime.datetime.now())
            )
            
            db.commit()
            
            # Create penalty embed
            embed = discord.Embed(
                title="⚠️ Штраф выдан",
                description=f"Игроку {user.mention} выдан штраф",
                color=0xE74C3C  # Red
            )
            
            embed.add_field(name="Штрафные очки", value=str(points), inline=True)
            embed.add_field(name="Причина", value=reason, inline=True)
            embed.add_field(name="Выдал", value=interaction.user.mention, inline=True)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error issuing penalty: {e}")
            db.rollback()
            await interaction.response.send_message("Произошла ошибка при выдаче штрафа.", ephemeral=True)
    
    @app_commands.command(
        name="tournament-next-match",
        description="Перейти к следующему матчу турнира"
    )
    @app_commands.describe(
        tournament_id="ID турнира"
    )
    async def tournament_next_match(self, interaction: discord.Interaction, tournament_id: int):
        """Создает матчи следующего раунда турнира."""
        # Проверяем, не обрабатывали ли мы уже это взаимодействие
        interaction_id = str(interaction.id)
        if interaction_id in self.processed_interactions:
            logger.warning(f"Skipping duplicate next match interaction {interaction_id}")
            await interaction.response.send_message("Это действие уже выполняется", ephemeral=True)
            return
            
        # Помечаем взаимодействие как обработанное
        self.processed_interactions.add(interaction_id)
        logger.info(f"Processing next match request for tournament {tournament_id}, interaction ID: {interaction_id}")
        
        # Проверяем права пользователя
        if not await is_tournament_manager(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия!", ephemeral=True)
            return
            
        # Подключаемся к базе данных
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Проверяем, существует ли турнир
            cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
            tournament = cursor.fetchone()
            
            if not tournament:
                await interaction.response.send_message(f"Турнир с ID {tournament_id} не найден!", ephemeral=True)
                return
                
            # Проверяем, завершен ли уже турнир
            if tournament['status'] == 'completed':
                logger.info(f"Tournament {tournament_id} is already completed, cannot create next match")
                await interaction.response.send_message(
                    "Турнир уже завершен и имеет победителя. Создание новых матчей невозможно.", 
                    ephemeral=True
                )
                return
                
            # Проверяем, есть ли незавершенные матчи
            cursor.execute(
                "SELECT COUNT(*) as count FROM tournament_matches WHERE tournament_id = ? AND completed = 0",
                (tournament_id,)
            )
            
            uncompleted_count = cursor.fetchone()['count']
            if uncompleted_count > 0:
                await interaction.response.send_message(
                    "Есть незавершенные матчи в текущем раунде. Пожалуйста, завершите их перед переходом к следующему раунду.", 
                    ephemeral=True
                )
                return
                
            # Определяем текущий раунд
            cursor.execute(
                "SELECT MAX(round) as current_round FROM tournament_matches WHERE tournament_id = ?",
                (tournament_id,)
            )
            
            current_round = cursor.fetchone()['current_round'] or 0
            next_round = current_round + 1
            
            # Определяем тип матча и необходимое количество побед
            match_type = tournament.get('match_type', 'BO1')
            wins_needed = 1  # По умолчанию для BO1
            if match_type == 'BO3':
                wins_needed = 2
            elif match_type == 'BO5':
                wins_needed = 3
            elif match_type == 'BO7':
                wins_needed = 4
            
            # Определяем победителей текущего раунда
            winners = []
            
            # Проверяем, является ли это дуэльным турниром с форматом BO3/BO5/BO7
            is_duel_tournament = False
            
            # Определяем количество участников
            if tournament['type'] == 'private':
                cursor.execute(
                    "SELECT COUNT(DISTINCT user_id) as count FROM tournament_participants WHERE tournament_id = ?",
                    (tournament_id,)
                )
                participant_count = cursor.fetchone()['count']
            else:
                cursor.execute(
                    "SELECT COUNT(DISTINCT id) as count FROM tournament_teams WHERE tournament_id = ?",
                    (tournament_id,)
                )
                participant_count = cursor.fetchone()['count']
                
            is_duel_tournament = participant_count == 2
            
            logger.info(f"Tournament {tournament_id} has {participant_count} participants, is_duel_tournament={is_duel_tournament}")
            
            # Если это первый раунд (current_round = 0), то создаем начальные матчи
            if current_round == 0:
                # Создание первого раунда матчей
                if tournament['type'] == 'private':
                    # Получаем список участников
                    cursor.execute(
                        "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                        (tournament_id,)
                    )
                    
                    participants = [p['user_id'] for p in cursor.fetchall()]
                    
                    if len(participants) < 2:
                        await interaction.response.send_message("Недостаточно участников для начала турнира.", ephemeral=True)
                        return
                    
                    # Особый случай для дуэльных турниров (только 2 игрока) в формате BO3/BO5/BO7
                    if len(participants) == 2 and match_type in ['BO3', 'BO5', 'BO7']:
                        logger.info(f"Creating duel tournament with match type {match_type} for participants {participants}")
                        
                        matches_to_create = 1  # По умолчанию создаем 1 матч (для BO1)
                        
                        if match_type == 'BO3':
                            matches_to_create = 3
                        elif match_type == 'BO5':
                            matches_to_create = 5
                        elif match_type == 'BO7':
                            matches_to_create = 7
                        
                        # Создаем необходимое количество матчей между одними и теми же игроками
                        for i in range(matches_to_create):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, player1_id, player2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    1,  # Все матчи в 1 раунде для BO3/BO5/BO7 дуэлей
                                    participants[0], 
                                    participants[1],
                                    datetime.datetime.now()
                                )
                            )
                        
                        logger.info(f"Created {matches_to_create} matches for duel tournament {tournament_id}")
                    else:
                        # Стандартное создание матчей для турнира
                        for i in range(0, len(participants), 2):
                            if i + 1 < len(participants):
                                cursor.execute(
                                    """
                                    INSERT INTO tournament_matches 
                                    (tournament_id, round, player1_id, player2_id, creation_date)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        tournament_id, 
                                        next_round, 
                                        participants[i], 
                                        participants[i+1],
                                        datetime.datetime.now()
                                    )
                                )
                else:
                    # Командный турнир
                    # Получаем все команды
                    cursor.execute(
                        "SELECT id FROM tournament_teams WHERE tournament_id = ?",
                        (tournament_id,)
                    )
                    
                    teams = [t['id'] for t in cursor.fetchall()]
                    
                    if len(teams) < 2:
                        await interaction.response.send_message("Недостаточно команд для начала турнира.", ephemeral=True)
                        return
                    
                    # Особый случай для дуэльных командных турниров (только 2 команды) в формате BO3/BO5/BO7
                    if len(teams) == 2 and match_type in ['BO3', 'BO5', 'BO7']:
                        logger.info(f"Creating duel team tournament with match type {match_type} for teams {teams}")
                        
                        matches_to_create = 1  # По умолчанию создаем 1 матч (для BO1)
                        
                        if match_type == 'BO3':
                            matches_to_create = 3
                        elif match_type == 'BO5':
                            matches_to_create = 5
                        elif match_type == 'BO7':
                            matches_to_create = 7
                        
                        # Создаем необходимое количество матчей между одними и теми же командами
                        for i in range(matches_to_create):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, team1_id, team2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    1,  # Все матчи в 1 раунде для BO3/BO5/BO7 дуэлей
                                    teams[0], 
                                    teams[1],
                                    datetime.datetime.now()
                                )
                            )
                        
                        logger.info(f"Created {matches_to_create} matches for duel team tournament {tournament_id}")
                    else:
                        # Стандартное создание матчей для турнира
                        for i in range(0, len(teams), 2):
                            if i + 1 < len(teams):
                                cursor.execute(
                                    """
                                    INSERT INTO tournament_matches 
                                    (tournament_id, round, team1_id, team2_id, creation_date)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        tournament_id, 
                                        next_round, 
                                        teams[i], 
                                        teams[i+1],
                                        datetime.datetime.now()
                                    )
                                )
            else:
                # Обработка дуэльного турнира
                if is_duel_tournament and match_type in ['BO3', 'BO5', 'BO7']:
                    if tournament['type'] == 'private':
                        # Получаем ID участников
                        cursor.execute(
                            "SELECT user_id FROM tournament_participants WHERE tournament_id = ? LIMIT 2",
                            (tournament_id,)
                        )
                        participants = cursor.fetchall()
                        
                        if len(participants) != 2:
                            logger.error(f"Expected 2 participants in duel tournament {tournament_id}, but found {len(participants)}")
                            await interaction.response.send_message(
                                "Ошибка: некорректное количество участников для дуэльного турнира.", 
                                ephemeral=True
                            )
                            return
                            
                        player1_id = participants[0]['user_id']
                        player2_id = participants[1]['user_id']
                        
                        # Подсчитываем победы для каждого игрока
                        cursor.execute(
                            """
                            SELECT 
                                SUM(CASE WHEN team1_score > team2_score THEN 1 ELSE 0 END) as player1_wins,
                                SUM(CASE WHEN team2_score > team1_score THEN 1 ELSE 0 END) as player2_wins
                            FROM tournament_matches 
                            WHERE tournament_id = ? AND completed = 1 AND (player1_id = ? OR player2_id = ?)
                            """,
                            (tournament_id, player1_id, player1_id)
                        )
                        
                        win_counts = cursor.fetchone()
                        player1_wins = win_counts['player1_wins'] or 0
                        player2_wins = win_counts['player2_wins'] or 0
                        
                        logger.info(f"Duel tournament {tournament_id} score: Player1 ({player1_id}) - {player1_wins}, Player2 ({player2_id}) - {player2_wins}")
                        
                        # Проверяем, есть ли победитель
                        if player1_wins >= wins_needed:
                            # Игрок 1 победил в дуэли
                            cursor.execute(
                                "UPDATE tournaments SET winner_id = ?, status = 'completed' WHERE id = ?",
                                (player1_id, tournament_id)
                            )
                            
                            # Создаем embed с результатами
                            cursor.execute(
                                "SELECT username FROM players WHERE user_id = ?",
                                (player1_id,)
                            )
                            winner_name = cursor.fetchone()['username']
                            
                            embed = discord.Embed(
                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                description=f"Турнир завершен!",
                                color=0xF1C40F  # Gold
                            )
                            
                            embed.add_field(name="Победитель", value=f"<@{player1_id}> ({winner_name})", inline=False)
                            embed.add_field(name="Счет", value=f"{player1_wins}:{player2_wins}", inline=False)
                            
                            # Отправляем результаты
                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                            if results_channel:
                                await results_channel.send(embed=embed)
                            
                            await interaction.response.send_message("Турнир завершен! Победитель определен и объявлен.", ephemeral=True)
                            db.commit()
                            return
                        elif player2_wins >= wins_needed:
                            # Игрок 2 победил в дуэли
                            cursor.execute(
                                "UPDATE tournaments SET winner_id = ?, status = 'completed' WHERE id = ?",
                                (player2_id, tournament_id)
                            )
                            
                            # Создаем embed с результатами
                            cursor.execute(
                                "SELECT username FROM players WHERE user_id = ?",
                                (player2_id,)
                            )
                            winner_name = cursor.fetchone()['username']
                            
                            embed = discord.Embed(
                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                description=f"Турнир завершен!",
                                color=0xF1C40F  # Gold
                            )
                            
                            embed.add_field(name="Победитель", value=f"<@{player2_id}> ({winner_name})", inline=False)
                            embed.add_field(name="Счет", value=f"{player2_wins}:{player1_wins}", inline=False)
                            
                            # Отправляем результаты
                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                            if results_channel:
                                await results_channel.send(embed=embed)
                            
                            await interaction.response.send_message("Турнир завершен! Победитель определен и объявлен.", ephemeral=True)
                            db.commit()
                            return
                    else:
                        # Командный турнир
                        cursor.execute(
                            "SELECT id FROM tournament_teams WHERE tournament_id = ? LIMIT 2",
                            (tournament_id,)
                        )
                        teams = cursor.fetchall()
                        
                        if len(teams) != 2:
                            logger.error(f"Expected 2 teams in duel tournament {tournament_id}, but found {len(teams)}")
                            await interaction.response.send_message(
                                "Ошибка: некорректное количество команд для дуэльного турнира.", 
                                ephemeral=True
                            )
                            return
                            
                        team1_id = teams[0]['id']
                        team2_id = teams[1]['id']
                        
                        # Подсчитываем победы для каждой команды
                        cursor.execute(
                            """
                            SELECT 
                                SUM(CASE WHEN team1_score > team2_score THEN 1 ELSE 0 END) as team1_wins,
                                SUM(CASE WHEN team2_score > team1_score THEN 1 ELSE 0 END) as team2_wins
                            FROM tournament_matches 
                            WHERE tournament_id = ? AND completed = 1 AND (team1_id = ? OR team2_id = ?)
                            """,
                            (tournament_id, team1_id, team1_id)
                        )
                        
                        win_counts = cursor.fetchone()
                        team1_wins = win_counts['team1_wins'] or 0
                        team2_wins = win_counts['team2_wins'] or 0
                        
                        logger.info(f"Duel team tournament {tournament_id} score: Team1 ({team1_id}) - {team1_wins}, Team2 ({team2_id}) - {team2_wins}")
                        
                        # Проверяем, есть ли победитель
                        if team1_wins >= wins_needed:
                            # Команда 1 победила в дуэли
                            cursor.execute(
                                "UPDATE tournaments SET winner_team_id = ?, status = 'completed' WHERE id = ?",
                                (team1_id, tournament_id)
                            )
                            
                            # Создаем embed с результатами
                            cursor.execute(
                                "SELECT team_name FROM tournament_teams WHERE id = ?",
                                (team1_id,)
                            )
                            winner_name = cursor.fetchone()['team_name']
                            
                            embed = discord.Embed(
                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                description=f"Турнир завершен!",
                                color=0xF1C40F  # Gold
                            )
                            
                            embed.add_field(name="Победитель", value=winner_name, inline=False)
                            embed.add_field(name="Счет", value=f"{team1_wins}:{team2_wins}", inline=False)
                            
                            # Отправляем результаты
                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                            if results_channel:
                                await results_channel.send(embed=embed)
                            
                            await interaction.response.send_message("Турнир завершен! Победитель определен и объявлен.", ephemeral=True)
                            db.commit()
                            return
                        elif team2_wins >= wins_needed:
                            # Команда 2 победила в дуэли
                            cursor.execute(
                                "UPDATE tournaments SET winner_team_id = ?, status = 'completed' WHERE id = ?",
                                (team2_id, tournament_id)
                            )
                            
                            # Создаем embed с результатами
                            cursor.execute(
                                "SELECT team_name FROM tournament_teams WHERE id = ?",
                                (team2_id,)
                            )
                            winner_name = cursor.fetchone()['team_name']
                            
                            embed = discord.Embed(
                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                description=f"Турнир завершен!",
                                color=0xF1C40F  # Gold
                            )
                            
                            embed.add_field(name="Победитель", value=winner_name, inline=False)
                            embed.add_field(name="Счет", value=f"{team2_wins}:{team1_wins}", inline=False)
                            
                            # Отправляем результаты
                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                            if results_channel:
                                await results_channel.send(embed=embed)
                            
                            await interaction.response.send_message("Турнир завершен! Победитель определен и объявлен.", ephemeral=True)
                            db.commit()
                            return
                
                # Получаем победителей текущего раунда для обычных (не дуэльных) турниров
                if tournament['type'] == 'private':
                    # Индивидуальный турнир
                    cursor.execute(
                        """
                        SELECT 
                            CASE 
                                WHEN team1_score > team2_score THEN player1_id
                                WHEN team2_score > team1_score THEN player2_id
                                ELSE NULL
                            END as player_id
                        FROM tournament_matches 
                        WHERE tournament_id = ? AND round = ? AND completed = 1
                        """,
                        (tournament_id, current_round)
                    )
                    
                    player_winners = cursor.fetchall()
                    winners = [{'player_id': pw['player_id']} for pw in player_winners if pw['player_id'] is not None]
                else:
                    # Командный турнир
                    cursor.execute(
                        """
                        SELECT 
                            CASE 
                                WHEN team1_score > team2_score THEN team1_id
                                WHEN team2_score > team1_score THEN team2_id
                                ELSE NULL
                            END as team_id
                        FROM tournament_matches 
                        WHERE tournament_id = ? AND round = ? AND completed = 1
                        """,
                        (tournament_id, current_round)
                    )
                    
                    team_winners = cursor.fetchall()
                    winners = [{'team_id': tw['team_id']} for tw in team_winners if tw['team_id'] is not None]
                
                # Проверяем, достаточно ли победителей для следующего раунда
                if len(winners) < 2:
                    # Турнир завершен - определяем общего победителя
                    if len(winners) == 1:
                        if tournament['type'] == 'private':
                            player_id = winners[0]['player_id']
                            
                            # Обновляем статус турнира и записываем победителя
                            cursor.execute(
                                "UPDATE tournaments SET winner_id = ?, status = 'completed' WHERE id = ?",
                                (player_id, tournament_id)
                            )
                            
                            # Создаем embed с результатами
                            cursor.execute(
                                "SELECT username FROM players WHERE user_id = ?",
                                (player_id,)
                            )
                            winner_name = cursor.fetchone()['username']
                            
                            embed = discord.Embed(
                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                description=f"Турнир завершен!",
                                color=0xF1C40F  # Gold
                            )
                            
                            embed.add_field(name="Победитель", value=f"<@{player_id}> ({winner_name})", inline=False)
                        else:
                            team_id = winners[0]['team_id']
                            
                            # Обновляем статус турнира и записываем победителя
                            cursor.execute(
                                "UPDATE tournaments SET winner_team_id = ?, status = 'completed' WHERE id = ?",
                                (team_id, tournament_id)
                            )
                            
                            # Создаем embed с результатами
                            cursor.execute(
                                "SELECT team_name FROM tournament_teams WHERE id = ?",
                                (team_id,)
                            )
                            winner_name = cursor.fetchone()['team_name']
                            
                            embed = discord.Embed(
                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                description=f"Турнир завершен!",
                                color=0xF1C40F  # Gold
                            )
                            
                            embed.add_field(name="Победитель", value=winner_name, inline=False)
                        
                        # Отправляем результаты
                        results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                        if results_channel:
                            await results_channel.send(embed=embed)
                        
                        await interaction.response.send_message("Турнир завершен! Победитель определен и объявлен.", ephemeral=True)
                        db.commit()
                        return
                    else:
                        await interaction.response.send_message("Не удалось определить победителей текущего раунда.", ephemeral=True)
                        return
                
                # Создаем матчи для следующего раунда
                if tournament['type'] == 'private':
                    # Индивидуальный турнир
                    player_ids = [w['player_id'] for w in winners]
                    
                    for i in range(0, len(player_ids), 2):
                        if i + 1 < len(player_ids):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, player1_id, player2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    next_round, 
                                    player_ids[i], 
                                    player_ids[i+1],
                                    datetime.datetime.now()
                                )
                            )
                else:
                    # Командный турнир
                    team_ids = [w['team_id'] for w in winners]
                    
                    for i in range(0, len(team_ids), 2):
                        if i + 1 < len(team_ids):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, team1_id, team2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    next_round, 
                                    team_ids[i], 
                                    team_ids[i+1],
                                    datetime.datetime.now()
                                )
                            )
            
            # Получаем информацию о созданных матчах для отображения
            if tournament['type'] == 'private':
                cursor.execute(
                    """
                    SELECT m.id, p1.username as player1_name, p2.username as player2_name
                    FROM tournament_matches m
                    JOIN players p1 ON m.player1_id = p1.user_id
                    JOIN players p2 ON m.player2_id = p2.user_id
                    WHERE m.tournament_id = ? AND m.round = ?
                    """,
                    (tournament_id, next_round)
                )
            else:
                cursor.execute(
                    """
                    SELECT m.id, t1.team_name as team1_name, t2.team_name as team2_name
                    FROM tournament_matches m
                    JOIN tournament_teams t1 ON m.team1_id = t1.id
                    JOIN tournament_teams t2 ON m.team2_id = t2.id
                    WHERE m.tournament_id = ? AND m.round = ?
                    """,
                    (tournament_id, next_round)
                )
                    
            new_matches = cursor.fetchall()
            
            # Создаем embed с новыми матчами
            embed = discord.Embed(
                title=f"Раунд {next_round}: {tournament['name']}",
                description="Новые матчи созданы:",
                color=0x3498DB  # Blue
            )
            
            for match in new_matches:
                if tournament['type'] == 'private':
                    embed.add_field(
                        name=f"Матч {match['id']}", 
                        value=f"{match['player1_name']} vs {match['player2_name']}", 
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"Матч {match['id']}", 
                        value=f"{match['team1_name']} vs {match['team2_name']}", 
                        inline=False
                    )
            
            # Обновляем статус турнира, если это первый раунд
            if current_round == 0:
                cursor.execute(
                    "UPDATE tournaments SET started = 1 WHERE id = ?",
                    (tournament_id,)
                )
            
            db.commit()
            
            # Отправляем уведомления участникам
            channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
            if channel:
                if tournament['type'] == 'private':
                    # Формируем список упоминаний участников
                    match_participants = set()
                    for match in new_matches:
                        cursor.execute(
                            "SELECT player1_id, player2_id FROM tournament_matches WHERE id = ?", 
                            (match['id'],)
                        )
                        match_data = cursor.fetchone()
                        if match_data:
                            if match_data['player1_id']:
                                match_participants.add(match_data['player1_id'])
                            if match_data['player2_id']:
                                match_participants.add(match_data['player2_id'])
                    
                    mentions = ' '.join([f"<@{p_id}>" for p_id in match_participants])
                    if mentions:
                        match_notification = discord.Embed(
                            title=f"⚡ Новый раунд в турнире {tournament['name']}",
                            description=f"Ваши матчи созданы! Проверьте сетку турнира, чтобы найти свой матч.",
                            color=0x1ABC9C  # Teal
                        )
                        await channel.send(mentions, embed=match_notification)
                else:
                    # Для командных турниров без тегов
                    match_notification = discord.Embed(
                        title=f"⚡ Новый раунд в турнире {tournament['name']}",
                        description=f"Новые матчи созданы! Представители команд, проверьте сетку турнира.",
                        color=0x1ABC9C  # Teal
                    )
                    await channel.send(embed=match_notification)
            
            # Обновляем и отправляем турнирную сетку
            from utils.brackets import generate_tournament_bracket
            success, bracket = generate_tournament_bracket(tournament_id)
            
            if success and channel:
                await channel.send(embed=bracket)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error creating next matches: {e}\n{error_details}")
            db.rollback()
            
            # Отправляем более информативное сообщение об ошибке
            try:
                await interaction.response.send_message(
                    f"Произошла ошибка при создании следующего раунда: {str(e)}", 
                    ephemeral=True
                )
            except discord.errors.InteractionResponded:
                await interaction.followup.send(
                    f"Произошла ошибка при создании следующего раунда: {str(e)}", 
                    ephemeral=True
                )
                
                # Handle team tournaments vs player tournaments differently
                if tournament['type'] == 'public':
                    # Team tournament
                    if len(winners) < 2:
                        # Tournament is complete - announce overall winner
                        if len(winners) == 1 and winners[0]['winner_id'] is not None:
                            # Get winning team name
                            cursor.execute(
                                "SELECT team_name FROM tournament_teams WHERE id = ?",
                                (winners[0]['winner_id'],)
                            )
                            
                            winner_team = cursor.fetchone()
                            
                            if winner_team:
                                # Update tournament winner and status
                                cursor.execute(
                                    "UPDATE tournaments SET winner_team_id = ?, status = 'completed' WHERE id = ?",
                                    (winners[0]['winner_id'], tournament_id)
                                )
                                
                                # Create final results embed
                                embed = discord.Embed(
                                    title=f"🏆 Результаты турнира: {tournament['name']}",
                                    description=f"Турнир завершен!",
                                    color=0xF1C40F  # Gold
                                )
                                
                                embed.add_field(name="Победитель", value=winner_team['team_name'], inline=False)
                                
                                # Send to results channel
                                results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                                if results_channel:
                                    await results_channel.send(embed=embed)
                                
                                await interaction.response.send_message("Турнир завершен! Победитель объявлен.", ephemeral=True)
                                db.commit()
                                return
                        elif current_round > 0:  # Проверяем, что это не первый раунд
                            # Если это был финальный раунд (осталось меньше 2 победителей)
                            # Проверяем, есть ли матчи в текущем раунде
                            cursor.execute(
                                "SELECT COUNT(*) as match_count FROM tournament_matches WHERE tournament_id = ? AND round = ?",
                                (tournament_id, current_round)
                            )
                            match_count = cursor.fetchone()['match_count']
                            
                            if match_count == 1:
                                # Это был финальный матч - пытаемся определить победителя
                                cursor.execute(
                                    """
                                    SELECT team1_id, team2_id, team1_score, team2_score 
                                    FROM tournament_matches 
                                    WHERE tournament_id = ? AND round = ? AND completed = 1
                                    LIMIT 1
                                    """,
                                    (tournament_id, current_round)
                                )
                                final_match = cursor.fetchone()
                                
                                if final_match:
                                    winner_id = None
                                    if final_match['team1_score'] > final_match['team2_score']:
                                        winner_id = final_match['team1_id']
                                    else:
                                        winner_id = final_match['team2_id']
                                    
                                    if winner_id:
                                        # Get winning team name
                                        cursor.execute(
                                            "SELECT team_name FROM tournament_teams WHERE id = ?",
                                            (winner_id,)
                                        )
                                        
                                        winner_team = cursor.fetchone()
                                        
                                        if winner_team:
                                            # Update tournament winner and status
                                            cursor.execute(
                                                "UPDATE tournaments SET winner_team_id = ?, status = 'completed' WHERE id = ?",
                                                (winner_id, tournament_id)
                                            )
                                            
                                            # Create final results embed
                                            embed = discord.Embed(
                                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                                description=f"Турнир завершен!",
                                                color=0xF1C40F  # Gold
                                            )
                                            
                                            embed.add_field(name="Победитель", value=winner_team['team_name'], inline=False)
                                            
                                            # Send to results channel
                                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                                            if results_channel:
                                                await results_channel.send(embed=embed)
                                            
                                            await interaction.response.send_message("Турнир завершен! Победитель объявлен.", ephemeral=True)
                                            db.commit()
                                            return
                        
                        await interaction.response.send_message("Недостаточно победителей для создания следующего раунда.", ephemeral=True)
                        return
                    
                    # Create matches for next round
                    for i in range(0, len(winners), 2):
                        if i + 1 < len(winners):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, team1_id, team2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    next_round, 
                                    winners[i]['winner_id'], 
                                    winners[i+1]['winner_id'],
                                    datetime.datetime.now()
                                )
                            )
                
                else:
                    # Player tournament
                    if len(winners) < 2:
                        # Tournament is complete - announce overall winner
                        if len(winners) == 1 and winners[0]['winner_player_id'] is not None:
                            # Get winning player name
                            cursor.execute(
                                "SELECT username FROM players WHERE user_id = ?",
                                (winners[0]['winner_player_id'],)
                            )
                            
                            winner_player = cursor.fetchone()
                            
                            if winner_player:
                                # Update tournament winner and status
                                cursor.execute(
                                    "UPDATE tournaments SET winner_id = ?, status = 'completed' WHERE id = ?",
                                    (winners[0]['winner_player_id'], tournament_id)
                                )
                                
                                # Create final results embed
                                embed = discord.Embed(
                                    title=f"🏆 Результаты турнира: {tournament['name']}",
                                    description=f"Турнир завершен!",
                                    color=0xF1C40F  # Gold
                                )
                                
                                embed.add_field(name="Победитель", value=f"<@{winners[0]['winner_player_id']}> ({winner_player['username']})", inline=False)
                                
                                # Send to results channel
                                results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                                if results_channel:
                                    await results_channel.send(embed=embed)
                                
                                await interaction.response.send_message("Турнир завершен! Победитель объявлен.", ephemeral=True)
                                db.commit()
                                return
                        elif current_round > 0:  # Проверяем, что это не первый раунд
                            # Если это был финальный раунд (осталось меньше 2 победителей)
                            # Проверяем, есть ли матчи в текущем раунде
                            cursor.execute(
                                "SELECT COUNT(*) as match_count FROM tournament_matches WHERE tournament_id = ? AND round = ?",
                                (tournament_id, current_round)
                            )
                            match_count = cursor.fetchone()['match_count']
                            
                            if match_count == 1:
                                # Это был финальный матч - пытаемся определить победителя
                                cursor.execute(
                                    """
                                    SELECT player1_id, player2_id, team1_score, team2_score 
                                    FROM tournament_matches 
                                    WHERE tournament_id = ? AND round = ? AND completed = 1
                                    LIMIT 1
                                    """,
                                    (tournament_id, current_round)
                                )
                                final_match = cursor.fetchone()
                                
                                if final_match:
                                    winner_id = None
                                    if final_match['team1_score'] > final_match['team2_score']:
                                        winner_id = final_match['player1_id']
                                    else:
                                        winner_id = final_match['player2_id']
                                    
                                    if winner_id:
                                        # Get winning player name
                                        cursor.execute(
                                            "SELECT username FROM players WHERE user_id = ?",
                                            (winner_id,)
                                        )
                                        
                                        winner_player = cursor.fetchone()
                                        
                                        if winner_player:
                                            # Update tournament winner and status
                                            cursor.execute(
                                                "UPDATE tournaments SET winner_id = ?, status = 'completed' WHERE id = ?",
                                                (winner_id, tournament_id)
                                            )
                                            
                                            # Create final results embed
                                            embed = discord.Embed(
                                                title=f"🏆 Результаты турнира: {tournament['name']}",
                                                description=f"Турнир завершен!",
                                                color=0xF1C40F  # Gold
                                            )
                                            
                                            embed.add_field(name="Победитель", value=f"<@{winner_id}> ({winner_player['username']})", inline=False)
                                            
                                            # Send to results channel
                                            results_channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
                                            if results_channel:
                                                await results_channel.send(embed=embed)
                                            
                                            await interaction.response.send_message("Турнир завершен! Победитель объявлен.", ephemeral=True)
                                            db.commit()
                                            return
                        
                        await interaction.response.send_message("Недостаточно победителей для создания следующего раунда.", ephemeral=True)
                        return
                    
                    # Create matches for next round
                    for i in range(0, len(winners), 2):
                        if i + 1 < len(winners):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, player1_id, player2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    next_round, 
                                    winners[i]['winner_player_id'], 
                                    winners[i+1]['winner_player_id'],
                                    datetime.datetime.now()
                                )
                            )
            
            else:
                # First round - create initial matches
                if tournament['type'] == 'private':
                    # Get all participants
                    cursor.execute(
                        "SELECT user_id FROM tournament_participants WHERE tournament_id = ?",
                        (tournament_id,)
                    )
                    
                    participants = [p['user_id'] for p in cursor.fetchall()]
                    
                    if len(participants) < 2:
                        await interaction.response.send_message("Недостаточно участников для начала турнира.", ephemeral=True)
                        return
                    
                    # Особый случай для дуэльных турниров (только 2 игрока) в формате BO3/BO5/BO7
                    if len(participants) == 2 and tournament.get('match_type', 'BO1') in ['BO3', 'BO5', 'BO7']:
                        logger.info(f"Creating duel tournament with match type {tournament.get('match_type')} for participants {participants}")
                        
                        match_type = tournament.get('match_type')
                        matches_to_create = 1  # По умолчанию создаем 1 матч (для BO1)
                        
                        if match_type == 'BO3':
                            matches_to_create = 3
                        elif match_type == 'BO5':
                            matches_to_create = 5
                        elif match_type == 'BO7':
                            matches_to_create = 7
                        
                        # Создаем необходимое количество матчей между одними и теми же игроками
                        for i in range(matches_to_create):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, player1_id, player2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    1,  # Все матчи в 1 раунде для BO3/BO5/BO7 дуэлей
                                    participants[0], 
                                    participants[1],
                                    datetime.datetime.now()
                                )
                            )
                        
                        logger.info(f"Created {matches_to_create} matches for duel tournament {tournament_id}")
                    else:
                        # Стандартное создание матчей для турнира
                        for i in range(0, len(participants), 2):
                            if i + 1 < len(participants):
                                cursor.execute(
                                    """
                                    INSERT INTO tournament_matches 
                                    (tournament_id, round, player1_id, player2_id, creation_date)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        tournament_id, 
                                        next_round, 
                                        participants[i], 
                                        participants[i+1],
                                        datetime.datetime.now()
                                    )
                                )
                
                else:
                    # Get all teams
                    cursor.execute(
                        "SELECT id FROM tournament_teams WHERE tournament_id = ?",
                        (tournament_id,)
                    )
                    
                    teams = [t['id'] for t in cursor.fetchall()]
                    
                    if len(teams) < 2:
                        await interaction.response.send_message("Недостаточно команд для начала турнира.", ephemeral=True)
                        return
                    
                    # Особый случай для дуэльных командных турниров (только 2 команды) в формате BO3/BO5/BO7
                    if len(teams) == 2 and tournament.get('match_type', 'BO1') in ['BO3', 'BO5', 'BO7']:
                        logger.info(f"Creating duel team tournament with match type {tournament.get('match_type')} for teams {teams}")
                        
                        match_type = tournament.get('match_type')
                        matches_to_create = 1  # По умолчанию создаем 1 матч (для BO1)
                        
                        if match_type == 'BO3':
                            matches_to_create = 3
                        elif match_type == 'BO5':
                            matches_to_create = 5
                        elif match_type == 'BO7':
                            matches_to_create = 7
                        
                        # Создаем необходимое количество матчей между одними и теми же командами
                        for i in range(matches_to_create):
                            cursor.execute(
                                """
                                INSERT INTO tournament_matches 
                                (tournament_id, round, team1_id, team2_id, creation_date)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    tournament_id, 
                                    1,  # Все матчи в 1 раунде для BO3/BO5/BO7 дуэлей
                                    teams[0], 
                                    teams[1],
                                    datetime.datetime.now()
                                )
                            )
                        
                        logger.info(f"Created {matches_to_create} matches for duel team tournament {tournament_id}")
                    else:
                        # Стандартное создание матчей для турнира
                        for i in range(0, len(teams), 2):
                            if i + 1 < len(teams):
                                cursor.execute(
                                    """
                                    INSERT INTO tournament_matches 
                                    (tournament_id, round, team1_id, team2_id, creation_date)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        tournament_id, 
                                        next_round, 
                                        teams[i], 
                                        teams[i+1],
                                        datetime.datetime.now()
                                    )
                                )
            
            db.commit()
            
            # Get new matches for display
            if tournament['type'] == 'private':
                cursor.execute(
                    """
                    SELECT m.id, p1.username as player1_name, p2.username as player2_name
                    FROM tournament_matches m
                    JOIN players p1 ON m.player1_id = p1.user_id
                    JOIN players p2 ON m.player2_id = p2.user_id
                    WHERE m.tournament_id = ? AND m.round = ?
                    """,
                    (tournament_id, next_round)
                )
            else:
                cursor.execute(
                    """
                    SELECT m.id, t1.team_name as team1_name, t2.team_name as team2_name
                    FROM tournament_matches m
                    JOIN tournament_teams t1 ON m.team1_id = t1.id
                    JOIN tournament_teams t2 ON m.team2_id = t2.id
                    WHERE m.tournament_id = ? AND m.round = ?
                    """,
                    (tournament_id, next_round)
                )
                
            new_matches = cursor.fetchall()
            
            # Create embed with new matches
            embed = discord.Embed(
                title=f"Раунд {next_round}: {tournament['name']}",
                description="Новые матчи созданы:",
                color=0x3498DB  # Blue
            )
            
            for match in new_matches:
                if tournament['type'] == 'private':
                    embed.add_field(
                        name=f"Матч {match['id']}", 
                        value=f"{match['player1_name']} vs {match['player2_name']}", 
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"Матч {match['id']}", 
                        value=f"{match['team1_name']} vs {match['team2_name']}", 
                        inline=False
                    )
            
            await interaction.response.send_message(embed=embed)
            
            # Отправляем уведомления о начале матча участникам
            channel = self.bot.get_channel(TOURNAMENT_RESULTS_CHANNEL)
            if channel:
                if tournament['type'] == 'private':
                    # Получаем всех участников и тегаем их
                    match_participants = set()
                    for match in new_matches:
                        cursor.execute(
                            """SELECT player1_id, player2_id FROM tournament_matches WHERE id = ?""", 
                            (match['id'],)
                        )
                        match_data = cursor.fetchone()
                        if match_data and match_data['player1_id']:
                            match_participants.add(match_data['player1_id'])
                        if match_data and match_data['player2_id']:
                            match_participants.add(match_data['player2_id'])
                    
                    # Формируем упоминания и отправляем уведомление
                    mentions = ' '.join([f"<@{p_id}>" for p_id in match_participants])
                    if mentions:
                        match_notification = discord.Embed(
                            title=f"⚡ Новый раунд в турнире {tournament['name']}",
                            description=f"Ваши матчи созданы! Проверьте сетку турнира, чтобы найти свой матч.",
                            color=0x1ABC9C  # Teal
                        )
                        await channel.send(mentions, embed=match_notification)
                else:
                    # Для командных турниров просто отправляем уведомление без тегов
                    match_notification = discord.Embed(
                        title=f"⚡ Новый раунд в турнире {tournament['name']}",
                        description=f"Новые матчи созданы! Представители команд, проверьте сетку турнира.",
                        color=0x1ABC9C  # Teal
                    )
                    await channel.send(embed=match_notification)
            
            # Обновляем и публикуем турнирную сетку
            from utils.brackets import generate_tournament_bracket
            success, bracket = generate_tournament_bracket(tournament_id)
            
            if success and channel:
                await channel.send(embed=bracket)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error creating next matches: {e}\n{error_details}")
            db.rollback()
            
            # Отправляем более информативное сообщение об ошибке
            try:
                await interaction.response.send_message(
                    f"Произошла ошибка при создании следующего раунда: {str(e)}", 
                    ephemeral=True
                )
            except discord.errors.InteractionResponded:
                await interaction.followup.send(
                    f"Произошла ошибка при создании следующего раунда: {str(e)}", 
                    ephemeral=True
                )
    
    @app_commands.command(
        name="tournament-undo",
        description="Отменить результат матча"
    )
    @app_commands.describe(
        match_id="ID матча"
    )
    async def tournament_undo(self, interaction: discord.Interaction, match_id: int):
        # Verify permissions
        if not await is_admin(interaction):
            await interaction.response.send_message("У вас нет прав для этого действия! Требуются права администратора.", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        # Check if match exists
        cursor.execute("SELECT * FROM tournament_matches WHERE id = ?", (match_id,))
        match = cursor.fetchone()
        
        if not match:
            await interaction.response.send_message(f"Матч с ID {match_id} не найден!", ephemeral=True)
            return
            
        if match['completed'] == 0:
            await interaction.response.send_message("Этот матч еще не завершен!", ephemeral=True)
            return
            
        # Check if there are matches in next round that depend on this one
        cursor.execute(
            "SELECT COUNT(*) FROM tournament_matches WHERE tournament_id = ? AND round > ?",
            (match['tournament_id'], match['round'])
        )
        
        if cursor.fetchone()[0] > 0:
            # Ask for confirmation
            embed = discord.Embed(
                title="⚠️ Внимание!",
                description=(
                    "Существуют матчи в следующих раундах, которые зависят от результата этого матча. "
                    "Отмена результата приведет к сбросу всех последующих раундов. Продолжить?"
                ),
                color=0xE74C3C  # Red
            )
            
            view = discord.ui.View(timeout=60)
            
            async def confirm_callback(interaction: discord.Interaction):
                # Delete matches in subsequent rounds
                cursor.execute(
                    "DELETE FROM tournament_matches WHERE tournament_id = ? AND round > ?",
                    (match['tournament_id'], match['round'])
                )
                
                # Reset match result
                cursor.execute(
                    "UPDATE tournament_matches SET team1_score = NULL, team2_score = NULL, notes = NULL, completed = 0, completion_date = NULL WHERE id = ?",
                    (match_id,)
                )
                
                # If this is a private tournament, update player stats
                if match.get('player1_id') is not None and match.get('player2_id') is not None:
                    # Determine winner from the match results
                    player1_id = match['player1_id']
                    player2_id = match['player2_id']
                    
                    if match['team1_score'] > match['team2_score']:
                        winner_id = player1_id
                        loser_id = player2_id
                    elif match['team2_score'] > match['team1_score']:
                        winner_id = player2_id
                        loser_id = player1_id
                    else:
                        winner_id = None
                        loser_id = None
                    
                    # If there was a winner, update stats
                    if winner_id:
                        # Update winner stats
                        cursor.execute(
                            "UPDATE players SET wins = wins - 1 WHERE user_id = ? AND wins > 0",
                            (winner_id,)
                        )
                        
                        # Update loser stats
                        cursor.execute(
                            "UPDATE players SET losses = losses - 1 WHERE user_id = ? AND losses > 0",
                            (loser_id,)
                        )
                        
                        # Remove from player_stats table
                        cursor.execute(
                            "DELETE FROM player_stats WHERE user_id IN (?, ?) AND tournament_id = ?",
                            (winner_id, loser_id, match['tournament_id'])
                        )
                
                db.commit()
                
                await interaction.response.send_message("Результат матча успешно отменен и все последующие раунды сброшены.", ephemeral=True)
            
            async def cancel_callback(interaction: discord.Interaction):
                await interaction.response.send_message("Отмена действия.", ephemeral=True)
            
            confirm_button = discord.ui.Button(label="Подтвердить", style=discord.ButtonStyle.danger)
            confirm_button.callback = confirm_callback
            
            cancel_button = discord.ui.Button(label="Отмена", style=discord.ButtonStyle.secondary)
            cancel_button.callback = cancel_callback
            
            view.add_item(confirm_button)
            view.add_item(cancel_button)
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        else:
            try:
                # Reset match result
                cursor.execute(
                    "UPDATE tournament_matches SET team1_score = NULL, team2_score = NULL, notes = NULL, completed = 0, completion_date = NULL WHERE id = ?",
                    (match_id,)
                )
                
                # If this is a private tournament, update player stats
                if match.get('player1_id') is not None and match.get('player2_id') is not None:
                    # Determine winner from the match results
                    player1_id = match['player1_id']
                    player2_id = match['player2_id']
                    
                    if match['team1_score'] > match['team2_score']:
                        winner_id = player1_id
                        loser_id = player2_id
                    elif match['team2_score'] > match['team1_score']:
                        winner_id = player2_id
                        loser_id = player1_id
                    else:
                        winner_id = None
                        loser_id = None
                    
                    # If there was a winner, update stats
                    if winner_id:
                        # Update winner stats
                        cursor.execute(
                            "UPDATE players SET wins = wins - 1 WHERE user_id = ? AND wins > 0",
                            (winner_id,)
                        )
                        
                        # Update loser stats
                        cursor.execute(
                            "UPDATE players SET losses = losses - 1 WHERE user_id = ? AND losses > 0",
                            (loser_id,)
                        )
                        
                        # Remove from player_stats table
                        cursor.execute(
                            "DELETE FROM player_stats WHERE user_id IN (?, ?) AND tournament_id = ?",
                            (winner_id, loser_id, match['tournament_id'])
                        )
                
                db.commit()
                
                await interaction.response.send_message("Результат матча успешно отменен.", ephemeral=True)
                
            except Exception as e:
                logger.error(f"Error undoing match result: {e}")
                db.rollback()
                await interaction.response.send_message("Произошла ошибка при отмене результата матча.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
