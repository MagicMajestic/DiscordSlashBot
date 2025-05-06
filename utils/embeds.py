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
    
    # Добавление ID турнира в основные поля
    embed.add_field(name="ID Турнира", value=f"#{tournament['id']}", inline=True)
    embed.add_field(name="Дата", value=tournament_date, inline=True)
    embed.add_field(name="Тип матчей", value=tournament.get('match_type', 'BO1'), inline=True)
    embed.add_field(name="Участники", value=f"0/{tournament['max_participants']}", inline=True)
    
    if tournament['entry_fee'] > 0:
        embed.add_field(name="Вступительный взнос", value=f"{tournament['entry_fee']}$ (передать организатору)", inline=False)
    
    embed.add_field(name="Организатор", value=f"<@{tournament['creator_id']}> ({tournament['creator_name']})", inline=False)
    
    # Добавление футера с ID для удобства использования в командах
    embed.set_footer(text=f"Для взаимодействия с этим турниром используйте ID: {tournament['id']}")
    
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
    
    # Добавление ID турнира в основные поля
    embed.add_field(name="ID Турнира", value=f"#{tournament['id']}", inline=True)
    embed.add_field(name="Дата", value=tournament_date, inline=True)
    embed.add_field(name="Тип матчей", value=tournament.get('match_type', 'BO1'), inline=True)
    embed.add_field(name="Участников на команду", value=str(tournament['participants_per_team']), inline=True)
    
    if tournament['entry_fee'] > 0:
        embed.add_field(name="Вступительный взнос", value=f"{tournament['entry_fee']}$ (передать организатору)", inline=False)
    
    embed.add_field(name="Правила", value=tournament['rules'], inline=False)
    embed.add_field(name="Организатор", value=f"<@{tournament['creator_id']}> ({tournament['creator_name']})", inline=False)
    
    # Добавление футера с ID для удобства использования в командах
    embed.set_footer(text=f"Для взаимодействия с этим турниром используйте ID: {tournament['id']}")
    
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
    
    # Добавление ID турнира, даты и типа матча
    embed.add_field(name="ID Турнира", value=f"#{tournament['id']}", inline=True)
    embed.add_field(name="Дата и время", value=tournament_date, inline=True)
    embed.add_field(name="Тип матчей", value=tournament.get('match_type', 'BO1'), inline=True)
    
    # Добавление футера с ID для удобства использования в командах
    embed.set_footer(text=f"Для взаимодействия с этим турниром используйте ID: {tournament['id']}")
    
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
    
    # Добавляем ID турнира для удобного отслеживания
    embed.add_field(name="ID Турнира", value=f"#{match['tournament_id']}", inline=True)
    embed.add_field(name="Раунд", value=f"{match.get('round', '?')}", inline=True)
    embed.add_field(name="Тип матча", value=match.get('match_type', 'BO1'), inline=True)
    
    # Determine if this is a team match or player match
    if match.get('team1_name') and match.get('team2_name'):
        # Team match
        embed.add_field(name=match['team1_name'], value=str(score_team1), inline=True)
        embed.add_field(name="VS", value="-", inline=True)
        embed.add_field(name=match['team2_name'], value=str(score_team2), inline=True)
        
        # Определяем количество побед, необходимое для победы в матче
        match_type = match.get('match_type', 'BO1')
        wins_needed = 1  # Default for BO1
        if match_type == 'BO3':
            wins_needed = 2
        elif match_type == 'BO5':
            wins_needed = 3
        elif match_type == 'BO7':
            wins_needed = 4
            
        # Determine winner
        if score_team1 >= wins_needed:
            embed.add_field(name="Победитель", value=match['team1_name'], inline=False)
            winner_id = match.get('team1_id', None)
            winner_type = 'Команда'
        elif score_team2 >= wins_needed:
            embed.add_field(name="Победитель", value=match['team2_name'], inline=False)
            winner_id = match.get('team2_id', None)
            winner_type = 'Команда'
        else:
            # Матч еще не завершен, показываем текущий счет
            embed.add_field(name="Текущий счет", value=f"{score_team1} - {score_team2}", inline=False)
            winner_id = None
            winner_type = None
    else:
        # Player match
        player1_name = f"<@{match['player1_id']}>"
        player2_name = f"<@{match['player2_id']}>"
        
        embed.add_field(name=player1_name, value=str(score_team1), inline=True)
        embed.add_field(name="VS", value="-", inline=True)
        embed.add_field(name=player2_name, value=str(score_team2), inline=True)
        
        # Определяем количество побед, необходимое для победы в матче
        match_type = match.get('match_type', 'BO1')
        wins_needed = 1  # Default for BO1
        if match_type == 'BO3':
            wins_needed = 2
        elif match_type == 'BO5':
            wins_needed = 3
        elif match_type == 'BO7':
            wins_needed = 4
            
        # Determine winner
        if score_team1 >= wins_needed:
            embed.add_field(name="Победитель", value=player1_name, inline=False)
            winner_id = match.get('player1_id', None)
            winner_type = 'Игрок'
        elif score_team2 >= wins_needed:
            embed.add_field(name="Победитель", value=player2_name, inline=False)
            winner_id = match.get('player2_id', None) 
            winner_type = 'Игрок'
        else:
            # Матч еще не завершен, показываем текущий счет
            embed.add_field(name="Текущий счет", value=f"{score_team1} - {score_team2}", inline=False)
            winner_id = None
            winner_type = None
    
    # Добавляем информацию о следующем раунде
    if winner_id:
        if winner_type == 'Игрок':
            winner_display = f"<@{winner_id}>"
        else:
            winner_display = f"{winner_type} ID {winner_id}"
        embed.add_field(name="Следующий раунд", value=f"{winner_display} переходит в следующий раунд", inline=False)
    
    # Add notes if available
    if match.get('notes') and match['notes'].strip():
        embed.add_field(name="Заметки", value=match['notes'], inline=False)
    
    # Добавление футера с ID турнира и матча
    embed.set_footer(text=f"Турнир #{match['tournament_id']} | Матч #{match['id']}")
    
    return embed
