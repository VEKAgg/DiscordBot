from datetime import datetime
from pydantic import BaseModel

class User(BaseModel):
    _id: int  # Discord User ID
    username: str
    joined_at: datetime
    guild_id: int
    messages_sent: int = 0
    xp: int = 0
    level: int = 1
