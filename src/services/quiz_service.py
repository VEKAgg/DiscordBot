import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger('VEKA.quiz')


class QuizService:
    def __init__(self, bot):
        self.bot = bot

    async def _disabled(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError('Quiz features are disabled for the current deployment.')

    create_quiz = _disabled
    get_random_quiz = _disabled
    record_quiz_attempt = _disabled
    get_user_stats = _disabled
    check_daily_taken = _disabled
    get_time_until_next_daily = _disabled
    get_daily_quiz = _disabled
    get_leaderboard = _disabled
    get_category_stats = _disabled
    get_daily_challenge = _disabled
