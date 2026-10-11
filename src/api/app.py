"""FastAPI application factory for the dashboard API (own process; never imports cogs)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import settings
from src.api.discord_client import discord_client
from src.api.errors import error_response, install_error_handlers
from src.api.routes import (
    feeds,
    guilds,
    health,
    honeypots,
    marketplace,
    massunban,
    me,
    moderation,
    modules,
    privacy,
    stats,
)
from src.api.routes import settings as settings_routes
from src.core.runtime_state import runtime_state
from src.database.database import db

logger = logging.getLogger('VEKA.api')


class BodyLimitMiddleware:
    """Reject request bodies over ``max_bytes`` by counting the bytes actually received (chunked bodies
    and missing or lying Content-Length included). The (small) body is buffered first and replayed to the
    app, so the 413 uses the normal error envelope instead of a framework parse error."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') in ('GET', 'HEAD', 'OPTIONS', 'DELETE'):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get('headers') or [])
        declared = headers.get(b'content-length', b'')
        if declared.isdigit() and int(declared) > self.max_bytes:
            await error_response(413, 'payload_too_large', 'Request body is too large.')(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body', b'')
            size += len(body)
            if size > self.max_bytes:
                await error_response(413, 'payload_too_large', 'Request body is too large.')(scope, receive, send)
                return
            chunks.append(body)
            if not message.get('more_body', False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)


async def _keep_db_connected() -> None:
    """The API has no health loop of its own: retry the pool until it exists (then stop)."""
    delay = 2.0
    while db.pool is None:
        try:
            await db.connect()
            runtime_state.db_available = True
            logger.info('API database pool established')
            return
        except Exception as exc:
            logger.warning('API could not connect to the database (%s); retrying in %.0fs', type(exc).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # One pool for this process: the shared `db` singleton (services import it).
    task = asyncio.create_task(_keep_db_connected())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await discord_client.close()
    await db.close()


def create_app() -> FastAPI:
    docs = settings.docs_enabled
    app = FastAPI(
        title='VEKA Dashboard API',
        version='1.0.0',
        lifespan=lifespan,
        openapi_url='/v1/openapi.json' if docs else None,
        docs_url='/v1/docs' if docs else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'],
            allow_headers=['Authorization', 'Content-Type', 'If-Match', 'X-Service-Token', 'X-Acting-User'],
        )

    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)

    for router in (
        health.router,
        modules.router,
        me.router,
        guilds.router,
        settings_routes.router,
        moderation.router,
        massunban.router,
        privacy.router,
        marketplace.router,
        honeypots.router,
        stats.router,
        feeds.router,
    ):
        app.include_router(router, prefix='/v1')
    return app


app = create_app()
