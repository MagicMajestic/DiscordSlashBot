import discord
import logging

logger = logging.getLogger(__name__)


def create_tournament_bracket_embed(tournament_id, tournament_name, matches, match_type='BO1', round_name=None):
    """
    Create an embed with a textual representation of a tournament bracket.
    
    Args:
        tournament_id: ID of the tournament
        tournament_name: Name of the tournament
        matches: List of match dictionaries with match data
        match_type: Type of matches (BO1, BO3, BO5, BO7)
        round_name: Name of the specific round (optional)
        
    Returns:
        discord.Embed: Formatted embed for the tournament bracket
    """
    # Determine if this is a team tournament by checking first match
    is_team_tournament = False
    if matches and (matches[0].get('team1_name') or matches[0].get('team2_name')):
        is_team_tournament = True
    
    # Group matches by rounds
    rounds = {}
    for match in matches:
        round_num = match.get('round', 0)
        if round_num not in rounds:
            rounds[round_num] = []
        rounds[round_num].append(match)
    
    # Sort rounds in ascending order
    sorted_rounds = sorted(rounds.keys())
    
    # Initialize the embed
    embed = discord.Embed(
        title=f"🏆 Турнирная сетка: {tournament_name}",
        description=f"ID турнира: #{tournament_id} | Формат: {match_type}" + (f" | {round_name}" if round_name else ""),
        color=0xF1C40F  # Gold
    )
    
    # Add each round to the embed
    for round_num in sorted_rounds:
        # Format round name based on the round number
        if round_num == max(sorted_rounds):
            round_title = "Финал"
        elif round_num == max(sorted_rounds) - 1:
            round_title = "Полуфинал"
        elif round_num == max(sorted_rounds) - 2:
            round_title = "Четвертьфинал"
        else:
            round_title = f"Раунд {round_num}"
        
        # Format matches for this round
        matches_text = ""
        for match in sorted(rounds[round_num], key=lambda m: m.get('id', 0)):
            match_id = match.get('id', '?')
            
            # Format match participants based on tournament type
            if is_team_tournament:
                team1 = match.get('team1_name', '?')
                team2 = match.get('team2_name', '?')
                
                # Add scores if match is completed
                if match.get('completed', 0) == 1:
                    score1 = match.get('team1_score', 0)
                    score2 = match.get('team2_score', 0)
                    matches_text += f"Матч #{match_id}: {team1} **{score1}** - **{score2}** {team2}\n"
                else:
                    matches_text += f"Матч #{match_id}: {team1} vs {team2}\n"
            else:
                # Individual tournament
                # Используем ID для тегов и имя как запасной вариант
                player1_id = match.get('player1_id')
                player2_id = match.get('player2_id')
                player1_name = match.get('player1_name', '?')
                player2_name = match.get('player2_name', '?')
                
                # Форматируем для отображения - предпочитаем теги, но используем имена если теги не работают
                player1 = f"<@{player1_id}>" if player1_id else player1_name if player1_name != '?' else '?'
                player2 = f"<@{player2_id}>" if player2_id else player2_name if player2_name != '?' else '?'
                
                # Add scores if match is completed
                if match.get('completed', 0) == 1:
                    score1 = match.get('team1_score', 0)
                    score2 = match.get('team2_score', 0)
                    matches_text += f"Матч #{match_id}: {player1} **{score1}** - **{score2}** {player2}\n"
                else:
                    matches_text += f"Матч #{match_id}: {player1} vs {player2}\n"
        
        # Add the formatted matches to the embed
        embed.add_field(name=round_title, value=matches_text or "Нет матчей", inline=False)
    
    return embed


def generate_tournament_bracket(tournament_id):
    """
    Generate a tournament bracket based on matches in the database.
    
    Args:
        tournament_id: ID of the tournament
        
    Returns:
        tuple: (success, embed or error message)
    """
    from utils.db import get_db
    
    # Get database connection
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Get tournament info
        cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        tournament = cursor.fetchone()
        
        if not tournament:
            return (False, "Турнир не найден")
        
        # Get all matches for this tournament including player information
        cursor.execute(
            """SELECT m.*, 
                  t1.team_name as team1_name, t2.team_name as team2_name,
                  p1.username as player1_name, p2.username as player2_name
               FROM tournament_matches m 
               LEFT JOIN tournament_teams t1 ON m.team1_id = t1.id 
               LEFT JOIN tournament_teams t2 ON m.team2_id = t2.id 
               LEFT JOIN players p1 ON m.player1_id = p1.user_id
               LEFT JOIN players p2 ON m.player2_id = p2.user_id
               WHERE m.tournament_id = ? 
               ORDER BY m.round, m.id""", 
            (tournament_id,)
        )
        
        matches = cursor.fetchall()
        
        if not matches:
            logger.warning(f"No matches found for tournament {tournament_id}")
            return (False, "Для этого турнира еще не создано матчей")
        
        # Create the bracket embed
        embed = create_tournament_bracket_embed(
            tournament_id, 
            tournament['name'],
            matches,
            tournament.get('match_type', 'BO1')
        )
        
        return (True, embed)
        
    except Exception as e:
        logger.error(f"Error generating tournament bracket: {e}")
        return (False, f"Ошибка при создании турнирной сетки: {str(e)}")
