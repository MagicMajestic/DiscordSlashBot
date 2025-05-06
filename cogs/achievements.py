import discord
import logging
from discord import app_commands
from discord.ext import commands
from typing import Optional
from utils.db import get_db
from utils.permissions import is_admin
from utils.constants import ACHIEVEMENT_DESCRIPTIONS

logger = logging.getLogger(__name__)

class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.init_achievements()
        
    def init_achievements(self):
        """Initialize the achievements in the database if they don't exist."""
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Check if achievements table is empty
            cursor.execute("SELECT COUNT(*) FROM achievements")
            count = cursor.fetchone()[0]
            
            if count == 0:
                # Add default achievements
                achievements = [
                    (1, "Король ревиков", "Выиграйте 3 турнира с револьверами"),
                    (2, "Снайпер-легенда", "Выиграйте снайперский турнир"),
                    (3, "Турнирный зверь", "Выиграйте 5 турниров подряд")
                ]
                
                cursor.executemany(
                    "INSERT INTO achievements (id, name, description) VALUES (?, ?, ?)",
                    achievements
                )
                
                db.commit()
                logger.info("Initialized default achievements")
        except Exception as e:
            logger.error(f"Error initializing achievements: {e}")
            db.rollback()
    
    @app_commands.command(
        name="achievement-add",
        description="Добавить новое достижение (только для администраторов)"
    )
    @app_commands.describe(
        name="Название достижения",
        description="Описание достижения"
    )
    async def achievement_add(self, interaction: discord.Interaction, name: str, description: str):
        # Check admin permissions
        if not await is_admin(interaction):
            await interaction.response.send_message("У вас нет прав для создания достижений!", ephemeral=True)
            return
            
        # Validate inputs
        if len(name) < 3 or len(name) > 50:
            await interaction.response.send_message("Название достижения должно содержать от 3 до 50 символов.", ephemeral=True)
            return
            
        if len(description) < 5 or len(description) > 200:
            await interaction.response.send_message("Описание достижения должно содержать от 5 до 200 символов.", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Check if achievement with same name already exists
            cursor.execute("SELECT COUNT(*) FROM achievements WHERE name = ?", (name,))
            if cursor.fetchone()[0] > 0:
                await interaction.response.send_message("Достижение с таким названием уже существует!", ephemeral=True)
                return
                
            # Add achievement
            cursor.execute(
                "INSERT INTO achievements (name, description) VALUES (?, ?)",
                (name, description)
            )
            
            db.commit()
            
            await interaction.response.send_message(f"Достижение **{name}** успешно добавлено!", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error adding achievement: {e}")
            db.rollback()
            await interaction.response.send_message("Произошла ошибка при добавлении достижения.", ephemeral=True)
    
    @app_commands.command(
        name="achievement-grant",
        description="Выдать достижение игроку (только для администраторов)"
    )
    @app_commands.describe(
        user="Игрок, которому выдается достижение",
        achievement_id="ID достижения"
    )
    async def achievement_grant(self, interaction: discord.Interaction, user: discord.Member, achievement_id: int):
        # Check admin permissions
        if not await is_admin(interaction):
            await interaction.response.send_message("У вас нет прав для выдачи достижений!", ephemeral=True)
            return
            
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Check if achievement exists
            cursor.execute("SELECT * FROM achievements WHERE id = ?", (achievement_id,))
            achievement = cursor.fetchone()
            
            if not achievement:
                await interaction.response.send_message(f"Достижение с ID {achievement_id} не найдено!", ephemeral=True)
                return
                
            # Check if player already has this achievement
            cursor.execute(
                "SELECT COUNT(*) FROM player_achievements WHERE user_id = ? AND achievement_id = ?",
                (user.id, achievement_id)
            )
            
            if cursor.fetchone()[0] > 0:
                await interaction.response.send_message(f"Игрок уже имеет это достижение!", ephemeral=True)
                return
                
            # Ensure player exists in players table
            cursor.execute(
                "INSERT OR IGNORE INTO players (user_id, username) VALUES (?, ?)",
                (user.id, user.name)
            )
                
            # Grant achievement
            cursor.execute(
                "INSERT INTO player_achievements (user_id, achievement_id, earned_date) VALUES (?, ?, datetime('now'))",
                (user.id, achievement_id)
            )
            
            db.commit()
            
            # Notify player
            try:
                embed = discord.Embed(
                    title="🏆 Достижение разблокировано!",
                    description=f"Вы получили достижение **{achievement['name']}**!",
                    color=0xF1C40F  # Gold
                )
                embed.add_field(name="Описание", value=achievement['description'])
                
                await user.send(embed=embed)
            except:
                logger.warning(f"Could not send DM to user {user.id} about achievement")
            
            await interaction.response.send_message(
                f"Достижение **{achievement['name']}** успешно выдано игроку {user.mention}!",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error granting achievement: {e}")
            db.rollback()
            await interaction.response.send_message("Произошла ошибка при выдаче достижения.", ephemeral=True)
    
    @app_commands.command(
        name="achievement-list",
        description="Показать список всех доступных достижений"
    )
    async def achievement_list(self, interaction: discord.Interaction):
        # Get database connection
        db = get_db()
        cursor = db.cursor()
        
        try:
            # Get all achievements
            cursor.execute("SELECT * FROM achievements ORDER BY id ASC")
            achievements = cursor.fetchall()
            
            if not achievements:
                await interaction.response.send_message("В системе пока нет достижений.", ephemeral=True)
                return
                
            # Create embed
            embed = discord.Embed(
                title="🏆 Список достижений",
                description="Все доступные достижения на сервере",
                color=0xF1C40F  # Gold
            )
            
            # Format achievements list
            achievements_text = ""
            for ach in achievements:
                achievements_text += f"**{ach['id']}: {ach['name']}** - {ach['description']}\n"
            
            embed.add_field(name="Доступные достижения", value=achievements_text, inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error listing achievements: {e}")
            await interaction.response.send_message("Произошла ошибка при получении списка достижений.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
