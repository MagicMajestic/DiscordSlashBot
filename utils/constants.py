# Discord channel IDs from environment variables
import os

# Get channel IDs from environment variables or use default placeholders
TOURNAMENT_APPROVAL_CHANNEL = int(os.getenv('TOURNAMENT_APPROVAL_CHANNEL', '0'))
PRIVATE_TOURNAMENTS_CHANNEL = int(os.getenv('PRIVATE_TOURNAMENTS_CHANNEL', '0'))
PUBLIC_TOURNAMENTS_CHANNEL = int(os.getenv('PUBLIC_TOURNAMENTS_CHANNEL', '0'))
TOURNAMENT_RESULTS_CHANNEL = int(os.getenv('TOURNAMENT_RESULTS_CHANNEL', '0'))

# Achievement descriptions for reference
ACHIEVEMENT_DESCRIPTIONS = {
    "revolver_king": "Выиграйте 3 турнира с револьверами",
    "sniper_legend": "Выиграйте снайперский турнир",
    "tournament_beast": "Выиграйте 5 турниров подряд"
}

# Embed colors
COLORS = {
    "RED": 0xE74C3C,       # Красный — криминальные турниры
    "BLUE": 0x3498DB,      # Синий — турниры гос. фракций
    "GOLD": 0xF1C40F,      # Золото — эмбеды с победителями
    "GREY": 0x808080,      # Серый — отклонённые заявки / отказ
    "PURPLE": 0x9B59B6,    # Фиолетовый — частные турниры
    "ORANGE": 0xE67E22     # Оранжевый — турниры "Криминал vs Гос"
}
