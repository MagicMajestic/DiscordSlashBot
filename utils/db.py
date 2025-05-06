import sqlite3
import os
import logging
from sqlite3 import Connection

# Set up logging
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "tournaments.db"

def dict_factory(cursor, row):
    """Convert database row objects to a dictionary."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db() -> Connection:
    """Get a connection to the database with row factory set to dict_factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    return conn

def create_tables():
    """Create database tables if they don't exist."""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Create players table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0
        )
        ''')
        
        # Create tournaments table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,  -- "private" / "public"
            weapon_type TEXT,
            rules TEXT,
            prize INTEGER DEFAULT 0,
            entry_fee INTEGER DEFAULT 0,
            tournament_date DATETIME,
            max_participants INTEGER,
            participants_per_team INTEGER,
            creator_id INTEGER,
            winner_id INTEGER,
            winner_team_id INTEGER,
            status TEXT DEFAULT 'pending',  -- "pending" / "approved" / "rejected" / "completed"
            approved_by INTEGER,
            rejection_reason TEXT,
            creation_date DATETIME,
            notification_sent INTEGER DEFAULT 0,
            FOREIGN KEY (creator_id) REFERENCES players(user_id),
            FOREIGN KEY (winner_id) REFERENCES players(user_id)
        )
        ''')
        
        # Create tournament participants table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournament_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER,
            user_id INTEGER,
            join_date DATETIME,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
            FOREIGN KEY (user_id) REFERENCES players(user_id)
        )
        ''')
        
        # Create tournament teams table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournament_teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER,
            team_name TEXT,
            captain_id INTEGER,
            registration_date DATETIME,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
            FOREIGN KEY (captain_id) REFERENCES players(user_id)
        )
        ''')
        
        # Create tournament matches table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournament_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER,
            round INTEGER,
            team1_id INTEGER,
            team2_id INTEGER,
            player1_id INTEGER,
            player2_id INTEGER,
            team1_score INTEGER,
            team2_score INTEGER,
            completed INTEGER DEFAULT 0,
            notes TEXT,
            creation_date DATETIME,
            completion_date DATETIME,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
            FOREIGN KEY (team1_id) REFERENCES tournament_teams(id),
            FOREIGN KEY (team2_id) REFERENCES tournament_teams(id),
            FOREIGN KEY (player1_id) REFERENCES players(user_id),
            FOREIGN KEY (player2_id) REFERENCES players(user_id)
        )
        ''')
        
        # Create player_stats table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tournament_id INTEGER,
            place INTEGER,
            FOREIGN KEY (user_id) REFERENCES players(user_id),
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
        )
        ''')
        
        # Create achievements table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT
        )
        ''')
        
        # Create player_achievements table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            achievement_id INTEGER,
            earned_date DATETIME,
            FOREIGN KEY (user_id) REFERENCES players(user_id),
            FOREIGN KEY (achievement_id) REFERENCES achievements(id)
        )
        ''')
        
        # Create player_penalties table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_penalties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            points INTEGER,
            reason TEXT,
            issued_by INTEGER,
            issue_date DATETIME,
            FOREIGN KEY (user_id) REFERENCES players(user_id),
            FOREIGN KEY (issued_by) REFERENCES players(user_id)
        )
        ''')
        
        conn.commit()
        logger.info("Database tables created successfully")
        
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        conn.rollback()
        
    finally:
        conn.close()
