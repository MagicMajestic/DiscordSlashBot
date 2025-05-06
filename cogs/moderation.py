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
from utils.constants import TOURNAMENT_RESULTS_CHANNEL

logger = logging.getLogger(__name__)

class TournamentResultModal(discord.ui.Modal, title="Результат матча"):
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
        super().__init__()
        self.match_id = match_id
        
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
                SELECT m.*, t.name as tournament_name, t.id as tournament_id,
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
                
            # Determine winner
            winner_id = None
            if score_team1 > score_team2:
                winner_id = match['team1_id']
                loser_id = match['team2_id']
            elif score_team2 > score_team1:
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
                    
                    # Determine winner
                    if score_team1 > score_team2:
                        winner_id = player1_id
                        loser_id = player2_id
                    elif score_team2 > score_team1:
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
                        
                        # Update player_stats table
                        cursor.execute(
                            "INSERT INTO player_stats (user_id, tournament_id, place) VALUES (?, ?, ?)",
                            (winner_id, match['tournament_id'], 1)
                        )
                        
                        cursor.execute(
                            "INSERT INTO player_stats (user_id, tournament_id, place) VALUES (?, ?, ?)",
                            (loser_id, match['tournament_id'], 2)
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
                await results_channel.send(embed=embed)
            
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


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
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
        # Verify permissions
        if not await is_tournament_manager(interaction):
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
            
        try:
            # Check if there are any uncompleted matches
            cursor.execute(
                "SELECT COUNT(*) FROM tournament_matches WHERE tournament_id = ? AND completed = 0",
                (tournament_id,)
            )
            
            if cursor.fetchone()[0] > 0:
                await interaction.response.send_message(
                    "Есть незавершенные матчи в текущем раунде. Пожалуйста, завершите их перед переходом к следующему раунду.", 
                    ephemeral=True
                )
                return
                
            # Get current round
            cursor.execute(
                "SELECT MAX(round) as current_round FROM tournament_matches WHERE tournament_id = ?",
                (tournament_id,)
            )
            
            current_round = cursor.fetchone()['current_round'] or 0
            next_round = current_round + 1
            
            # Get winners from current round
            if current_round > 0:
                cursor.execute(
                    """
                    SELECT 
                        CASE 
                            WHEN team1_score > team2_score THEN team1_id
                            WHEN team2_score > team1_score THEN team2_id
                            ELSE NULL
                        END as winner_id,
                        CASE 
                            WHEN team1_score > team2_score THEN player1_id
                            WHEN team2_score > team1_score THEN player2_id
                            ELSE NULL
                        END as winner_player_id
                    FROM tournament_matches 
                    WHERE tournament_id = ? AND round = ?
                    """,
                    (tournament_id, current_round)
                )
                
                winners = cursor.fetchall()
                
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
                                # Update tournament winner
                                cursor.execute(
                                    "UPDATE tournaments SET winner_team_id = ? WHERE id = ?",
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
                                # Update tournament winner
                                cursor.execute(
                                    "UPDATE tournaments SET winner_id = ? WHERE id = ?",
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
                        
                    # Create matches
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
                        
                    # Create matches
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
            
        except Exception as e:
            logger.error(f"Error creating next matches: {e}")
            db.rollback()
            await interaction.response.send_message("Произошла ошибка при создании следующего раунда.", ephemeral=True)
    
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
