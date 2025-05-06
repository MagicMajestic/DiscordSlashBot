import discord
import logging
from discord import app_commands
from discord.ext import commands
from typing import Optional
from utils.db import get_db
from utils.constants import ACHIEVEMENT_DESCRIPTIONS

logger = logging.getLogger(__name__)

class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(
        name="mystats",
        description="Показать вашу личную статистику участия в турнирах"
    )
    async def mystats(self, interaction: discord.Interaction):
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Get basic stats
            cursor.execute(
                """
                SELECT username, wins, losses 
                FROM players 
                WHERE user_id = ?
                """,
                (interaction.user.id,)
            )
            
            player = cursor.fetchone()
            
            if not player:
                # Player not found, create record
                cursor.execute(
                    "INSERT INTO players (user_id, username) VALUES (?, ?)",
                    (interaction.user.id, interaction.user.name)
                )
                db.commit()
                
                await interaction.response.send_message("У вас пока нет статистики турниров.", ephemeral=True)
                return
                
            # Get tournament participation
            cursor.execute(
                """
                SELECT t.name, ps.place
                FROM player_stats ps
                JOIN tournaments t ON ps.tournament_id = t.id
                WHERE ps.user_id = ?
                ORDER BY ps.place ASC, t.tournament_date DESC
                LIMIT 10
                """,
                (interaction.user.id,)
            )
            
            participations = cursor.fetchall()
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 Статистика игрока {player['username']}",
                description="Ваша статистика участия в турнирах",
                color=0x3498DB  # Blue
            )
            
            # Basic stats
            embed.add_field(name="Победы", value=str(player['wins']), inline=True)
            embed.add_field(name="Поражения", value=str(player['losses']), inline=True)
            
            if player['wins'] + player['losses'] > 0:
                win_rate = round(player['wins'] / (player['wins'] + player['losses']) * 100, 1)
                embed.add_field(name="Винрейт", value=f"{win_rate}%", inline=True)
            
            # Add tournament history if available
            if participations:
                history = ""
                for p in participations:
                    place_emoji = "🥇" if p['place'] == 1 else "🥈" if p['place'] == 2 else "🥉" if p['place'] == 3 else "🎮"
                    history += f"{place_emoji} {p['name']} - {p['place']} место\n"
                
                embed.add_field(name="История турниров", value=history, inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error retrieving player stats: {e}")
            await interaction.response.send_message("Произошла ошибка при получении статистики.", ephemeral=True)
    
    @app_commands.command(
        name="top-players",
        description="Показать топ игроков по победам"
    )
    async def top_players(self, interaction: discord.Interaction):
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Get top players
            cursor.execute(
                """
                SELECT username, wins, losses, user_id
                FROM players
                WHERE wins > 0
                ORDER BY wins DESC, losses ASC
                LIMIT 10
                """
            )
            
            top_players = cursor.fetchall()
            
            if not top_players:
                await interaction.response.send_message("Пока нет игроков с победами в турнирах.", ephemeral=True)
                return
                
            # Create embed
            embed = discord.Embed(
                title="🏆 Топ игроков по победам",
                description="Лучшие игроки сервера",
                color=0xF1C40F  # Gold
            )
            
            # Format top players list
            players_text = ""
            for i, player in enumerate(top_players):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
                
                if player['wins'] + player['losses'] > 0:
                    win_rate = round(player['wins'] / (player['wins'] + player['losses']) * 100, 1)
                    players_text += f"{medal} **{player['username']}** - {player['wins']} побед ({win_rate}% винрейт)\n"
                else:
                    players_text += f"{medal} **{player['username']}** - {player['wins']} побед\n"
            
            embed.add_field(name="Лидеры", value=players_text, inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error retrieving top players: {e}")
            await interaction.response.send_message("Произошла ошибка при получении топа игроков.", ephemeral=True)
    
    @app_commands.command(
        name="myachievements",
        description="Показать ваши достижения в турнирах"
    )
    async def myachievements(self, interaction: discord.Interaction):
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Get player achievements
            cursor.execute(
                """
                SELECT a.id, a.name, a.description, pa.earned_date
                FROM player_achievements pa
                JOIN achievements a ON pa.achievement_id = a.id
                WHERE pa.user_id = ?
                ORDER BY pa.earned_date DESC
                """,
                (interaction.user.id,)
            )
            
            achievements = cursor.fetchall()
            
            # Get available achievements
            cursor.execute("SELECT id, name, description FROM achievements ORDER BY id ASC")
            all_achievements = cursor.fetchall()
            
            # Create embed
            embed = discord.Embed(
                title="🏆 Ваши достижения",
                description="Полученные и доступные достижения",
                color=0xF1C40F  # Gold
            )
            
            # Format earned achievements
            if achievements:
                earned_text = ""
                for ach in achievements:
                    earned_date = ach['earned_date'].split()[0] if ach['earned_date'] else "Неизвестно"
                    earned_text += f"**{ach['name']}** - {ach['description']} (получено: {earned_date})\n"
                
                embed.add_field(name="Полученные достижения", value=earned_text, inline=False)
            else:
                embed.add_field(name="Полученные достижения", value="У вас пока нет достижений", inline=False)
            
            # Format available achievements
            earned_ids = [a['id'] for a in achievements]
            available_achievements = [a for a in all_achievements if a['id'] not in earned_ids]
            
            if available_achievements:
                available_text = ""
                for ach in available_achievements:
                    available_text += f"**{ach['name']}** - {ach['description']}\n"
                
                embed.add_field(name="Доступные достижения", value=available_text, inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error retrieving achievements: {e}")
            await interaction.response.send_message("Произошла ошибка при получении достижений.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
