import os
import logging
import discord
from discord.ext import commands
from discord import app_commands

logger = logging.getLogger(__name__)

async def setup_bot():
    """Setup and configure the Discord bot with all necessary extensions."""
    # Set up intents
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    
    # Create bot instance
    bot = commands.Bot(command_prefix='!', intents=intents)
    
    # Set up sync command for application commands
    @bot.command()
    @commands.has_permissions(administrator=True)
    async def sync(ctx):
        """Sync application commands to the guild."""
        logger.info(f"Syncing commands to guild {ctx.guild.id}")
        await bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
        await ctx.send("Commands synced!")
    
    # On ready event
    @bot.event
    async def on_ready():
        """Called when the bot is ready and connected to Discord."""
        logger.info(f"{bot.user.name} has connected to Discord!")
        
        # Set bot activity
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, 
                name="GTA V RP tournaments"
            )
        )
    
    # Load cogs (extensions)
    cogs = [
        'cogs.tournaments',
        'cogs.moderation',
        'cogs.stats',
        'cogs.achievements'
    ]
    
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logger.info(f"Loaded extension: {cog}")
        except Exception as e:
            logger.error(f"Failed to load extension {cog}: {e}")
    
    return bot
