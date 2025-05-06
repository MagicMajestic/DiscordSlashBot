import discord
from discord.ext import commands

async def is_tournament_manager(interaction: discord.Interaction) -> bool:
    """
    Check if the user has the Tournament Manager role or is an administrator.
    
    Args:
        interaction: Discord interaction to check permissions for
        
    Returns:
        bool: True if user has permission, False otherwise
    """
    # Check if user is administrator
    if interaction.user.guild_permissions.administrator:
        return True
    
    # Check for Tournament Manager role
    for role in interaction.user.roles:
        if role.name.lower() in ["tournament manager", "турнирный менеджер"]:
            return True
    
    return False

async def is_admin(interaction: discord.Interaction) -> bool:
    """
    Check if the user has administrator permissions.
    
    Args:
        interaction: Discord interaction to check permissions for
        
    Returns:
        bool: True if user is an administrator, False otherwise
    """
    return interaction.user.guild_permissions.administrator
