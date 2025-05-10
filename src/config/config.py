import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
BOT_PREFIX = "!"
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")

# RSS Feed Configuration
RSS_FEEDS = {
    "tech_news": [
        "https://feeds.feedburner.com/TechCrunch",
        "https://www.wired.com/feed/rss",
        "https://www.theverge.com/rss/index.xml"
    ],
    "job_listings": [
        "https://stackoverflow.com/jobs/feed",
        "https://remoteok.io/remote-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss"
    ],
    "dev_blogs": [
        "https://dev.to/feed",
        "https://medium.com/feed/tag/programming",
        "https://blog.github.com/all.atom"
    ]
}

# Quiz Configuration
QUIZ_CATEGORIES = [
    "Programming",
    "Data Structures",
    "Algorithms",
    "System Design",
    "Web Development",
    "DevOps",
    "Cloud Computing",
    "Cybersecurity"
]

QUIZ_DIFFICULTY_LEVELS = ["Easy", "Medium", "Hard"]
MAX_QUIZ_QUESTIONS = 10
QUIZ_TIMEOUT_SECONDS = 30

# Trivia Configuration
TRIVIA_CATEGORIES = {
    "tech": "Technology",
    "programming": "Programming",
    "science": "Science",
    "general": "General Knowledge"
}

# Points and Rewards
POINTS_CONFIG = {
    "quiz_correct": 10,
    "trivia_correct": 5,
    "daily_streak": 20,
    "challenge_completion": 50,
    "mentor_session": 30
}

# Cooldowns (in seconds)
COOLDOWNS = {
    "quiz": 3600,  # 1 hour
    "trivia": 1800,  # 30 minutes
    "daily": 86400,  # 24 hours
    "challenge": 43200  # 12 hours
}

# Mentorship Configuration
MENTORSHIP_ROLES = [
    "Mentor",
    "Mentee"
]

MENTORSHIP_CATEGORIES = [
    "Software Development",
    "Data Science",
    "DevOps",
    "Cloud Architecture",
    "UI/UX Design",
    "Project Management",
    "Machine Learning"
]

# Logging Configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = "logs/bot.log"

# API Rate Limits (requests per minute)
RATE_LIMITS = {
    "rss_fetch": 5,
    "leetcode_api": 30,
    "github_api": 60
}

# Cache Configuration
CACHE_TTL = {
    "rss_feed": 900,  # 15 minutes
    "quiz_data": 3600,  # 1 hour
    "user_profile": 300,  # 5 minutes
    "leaderboard": 60  # 1 minute
}

# Feature Flags
FEATURES = {
    "mentorship": True,
    "challenges": True,
    "quizzes": True,
    "rss_feeds": True,
    "points_system": True,
    "leaderboard": True
} 