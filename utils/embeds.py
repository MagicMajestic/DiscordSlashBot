import discord
import datetime

def create_private_tournament_embed(tournament):
    """
    Create an embed for a private tournament announcement.
    
    Args:
        tournament: Dictionary with tournament data from the database
        
    Returns:
        discord.Embed: Formatted embed for the tournament
    """
    embed = discord.Embed(
        title=f"🔫 **{tournament['name']}**",
        description=f"Частный турнир на {tournament['weapon_type']}!",
        color=0x9B59B6  # Purple for private tournaments
    )
    
    # Format tournament date
    if isinstance(tournament['tournament_date'], str):
        tournament_date = tournament['tournament_date']
    else:
        tournament_date = tournament['tournament_date'].strftime("%d.%m.%Y, %H:%M")
    
    embed.add_field(name="Дата", value=tournament_date, inline=True)
    embed.add_field(name="Участники", value=f"0/{tournament['max_participants']}", inline=True)
    
    if tournament['entry_fee'] > 0:
        embed.add_field(name="Вступительный взнос", value=f"{tournament['entry_fee']}$ (передать организатору)", inline=False)
    
    embed.add_field(name="Организатор", value=f"<@{tournament['creator_id']}> ({tournament['creator_name']})", inline=False)
    
    return embed

def create_public_tournament_embed(tournament):
    """
    Create an embed for a public tournament announcement.
    
    Args:
        tournament: Dictionary with tournament data from the database
        
    Returns:
        discord.Embed: Formatted embed for the tournament
    """
    embed = discord.Embed(
        title=f"🏆 **{tournament['name']}**",
        description=f"Публичный турнир между организациями!",
        color=0xE67E22  # Orange for public tournaments
    )
    
    # Format tournament date
    if isinstance(tournament['tournament_date'], str):
        tournament_date = tournament['tournament_date']
    else:
        tournament_date = tournament['tournament_date'].strftime("%d.%m.%Y, %H:%M")
    
    embed.add_field(name="Дата", value=tournament_date, inline=True)
    embed.add_field(name="Участников на команду", value=str(tournament['participants_per_team']), inline=True)
    
    if tournament['entry_fee'] > 0:
        embed.add_field(name="Вступительный взнос", value=f"{tournament['entry_fee']}$ (передать организатору)", inline=False)
    
    embed.add_field(name="Правила", value=tournament['rules'], inline=False)
    embed.add_field(name="Организатор", value=f"<@{tournament['creator_id']}> ({tournament['creator_name']})", inline=False)
    
    return embed

def create_tournament_notification_embed(tournament):
    """
    Create an embed for tournament notification.
    
    Args:
        tournament: Dictionary with tournament data from the database
        
    Returns:
        discord.Embed: Formatted embed for the notification
    """
    if tournament['type'] == 'private':
        color = 0x9B59B6  # Purple for private tournaments
    else:
        color = 0xE67E22  # Orange for public tournaments
    
    embed = discord.Embed(
        title=f"⏰ Турнир скоро начнется: {tournament['name']}",
        description="До начала турнира осталось менее 15 минут!",
        color=color
    )
    
    # Format tournament date
    if isinstance(tournament['tournament_date'], str):
        tournament_date = tournament['tournament_date']
    else:
        tournament_date = tournament['tournament_date'].strftime("%d.%m.%Y, %H:%M")
    
    embed.add_field(name="Дата и время", value=tournament_date, inline=True)
    
    return embed

def create_match_result_embed(match, score_team1, score_team2):
    """
    Create an embed for match results.
    
    Args:
        match: Dictionary with match data from the database
        score_team1: Score for team 1
        score_team2: Score for team 2
        
    Returns:
        discord.Embed: Formatted embed for the match results
    """
    embed = discord.Embed(
        title=f"🏁 Результаты матча: {match['tournament_name']}",
        description=f"Матч #{match['id']} завершен!",
        color=0xF1C40F  # Gold for results
    )
    
    # Determine if this is a team match or player match
    if match.get('team1_name') and match.get('team2_name'):
        # Team match
        embed.add_field(name=match['team1_name'], value=str(score_team1), inline=True)
        embed.add_field(name="VS", value="-", inline=True)
        embed.add_field(name=match['team2_name'], value=str(score_team2), inline=True)
        
        # Determine winner
        if score_team1 > score_team2:
            embed.add_field(name="Победитель", value=match['team1_name'], inline=False)
        elif score_team2 > score_team1:
            embed.add_field(name="Победитель", value=match['team2_name'], inline=False)
        else:
            embed.add_field(name="Результат", value="Ничья", inline=False)
    else:
        # Player match
        player1_name = f"<@{match['player1_id']}>"
        player2_name = f"<@{match['player2_id']}>"
        
        embed.add_field(name=player1_name, value=str(score_team1), inline=True)
        embed.add_field(name="VS", value="-", inline=True)
        embed.add_field(name=player2_name, value=str(score_team2), inline=True)
        
        # Determine winner
        if score_team1 > score_team2:
            embed.add_field(name="Победитель", value=player1_name, inline=False)
        elif score_team2 > score_team1:
            embed.add_field(name="Победитель", value=player2_name, inline=False)
        else:
            embed.add_field(name="Результат", value="Ничья", inline=False)
    
    # Add notes if available
    if match.get('notes') and match['notes'].strip():
        embed.add_field(name="Заметки", value=match['notes'], inline=False)
    
    return embed
