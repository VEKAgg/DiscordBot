from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from src.database.database import db

router = APIRouter(tags=['health'])

BOT_STALE_SECONDS = 180


@router.get('/health')
async def health() -> dict:
    """Liveness of the API, its database and the bot (from the bot's status heartbeat). No auth."""
    db_ok = True
    bot: dict = {'online': False, 'updated_at': None, 'version': None}
    try:
        row = await db.fetch_one('SELECT version, updated_at FROM bot_status WHERE id = 1')
        if row:
            age = (datetime.now(UTC) - row['updated_at']).total_seconds()
            bot = {
                'online': age < BOT_STALE_SECONDS,
                'updated_at': row['updated_at'].isoformat(),
                'version': row['version'],
            }
    except Exception:
        db_ok = False
    return {'api': 'ok', 'db': 'ok' if db_ok else 'down', 'bot': bot}
