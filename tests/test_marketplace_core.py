"""Offline protocol, source isolation and explicit submission regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest
from aiohttp import web

from src.cogs.marketplace.marketplace import Marketplace
from src.services.marketplace_core import BASE, CoreClient, CoreError, MarketplaceSync
from src.services.marketplace_ingestion import MarketplaceIngestion, available_channels


async def test_client_wire_contract_and_no_redirect_key_forwarding():
    seen = []

    async def handler(request):
        seen.append(
            (
                request.method,
                request.headers.get('X-Veka-Service-Key'),
                request.headers.get('Idempotency-Key'),
                await request.json(),
            )
        )
        return web.json_response({'schema_version': 1, 'request_id': 'test', 'ok': True})

    async def redirect(_request):
        return web.Response(status=302, headers={'Location': 'https://not-contacted.example/'})

    app = web.Application()
    app.router.add_put(BASE + '/test', handler)
    app.router.add_get(BASE + '/redirect', redirect)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = CoreClient(f'http://127.0.0.1:{port}', 'fake-key', 'test-installation')
    try:
        assert (await client.request('PUT', BASE + '/test', body={'amount_minor': '1200'}, key='immutable'))['ok']
        assert seen == [('PUT', 'fake-key', 'immutable', {'amount_minor': '1200'})]
        with pytest.raises(CoreError) as error:
            await client.request('GET', BASE + '/redirect')
        assert error.value.status == 302
    finally:
        await client.close()
        await runner.cleanup()


@pytest.mark.parametrize('origin', ['https://user:secret@example.test', 'https://example.test/path', 'file:///tmp/a'])
def test_service_origin_validation(origin):
    with pytest.raises(ValueError):
        CoreClient(origin, 'fake-key', 'installation')


async def test_missing_config_is_not_silent_success():
    with pytest.raises(CoreError, match='core_unconfigured'):
        await CoreClient('', '', '').request('GET', BASE + '/bindings')


async def test_ordinary_text_chat_never_imports(mock_bot, mock_guild, mock_user, monkeypatch):
    cog = Marketplace(mock_bot)
    save = AsyncMock()
    monkeypatch.setattr(cog.ingestion, 'save', save)
    message = SimpleNamespace(
        channel=MagicMock(spec=nextcord.TextChannel),
        guild=mock_guild,
        id=1,
        author=mock_user,
        content='Selling something USD 20',
    )
    await cog.on_message(message)
    save.assert_not_awaited()


async def test_forum_ingestion_is_private_unknown_price_and_silent(monkeypatch, mock_bot, mock_db, mock_guild):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    cog = Marketplace(mock_bot)
    monkeypatch.setattr(
        cog.sync, 'binding', AsyncMock(return_value={'mode': 'forum', 'categories': [], 'default_category_id': None})
    )
    save = AsyncMock()
    monkeypatch.setattr(cog.ingestion, 'save', save)
    starter = SimpleNamespace(
        author=SimpleNamespace(id=123, bot=False), webhook_id=None, content='RTX 4090', attachments=[], edited_at=None
    )
    thread = SimpleNamespace(
        guild=mock_guild,
        parent_id=30,
        id=40,
        owner_id=123,
        archived=False,
        locked=False,
        name='Graphics card',
        applied_tags=[],
        fetch_message=AsyncMock(return_value=starter),
    )
    await cog._ingest_forum_thread(thread)
    args = save.call_args.kwargs
    assert args['price'] is None and args['category_id'] is None
    assert args['guild_id'] == mock_guild.id and args['channel_id'] == 30
    assert 'consent' not in args


async def test_reads_never_fall_back_to_global_context(mock_db, mock_interaction):
    sync = MarketplaceSync(MagicMock(), mock_db)
    repository = MarketplaceIngestion(sync, mock_db)
    await repository.rows(mock_interaction, listing_id='private')
    sql, guild_id, channels, viewer, listing_id = mock_db.fetch.call_args.args
    assert guild_id == mock_interaction.guild.id and viewer == str(mock_interaction.user.id)
    assert 'l.guild_id=$1' in sql and 'l.origin_channel_id=ANY($2::bigint[])' in sql
    assert 'core_moderation' in sql and "interval '300 seconds'" in sql
    assert listing_id == 'private'
    mock_interaction.guild = None
    mock_db.fetch.reset_mock()
    assert await repository.rows(mock_interaction) == []
    mock_db.fetch.assert_not_awaited()


def test_channel_permissions_are_member_specific(mock_interaction):
    allowed, denied = MagicMock(), MagicMock()
    allowed.id, denied.id = 1, 2
    allowed.permissions_for.return_value = nextcord.Permissions(view_channel=True, read_message_history=True)
    denied.permissions_for.return_value = nextcord.Permissions.none()
    mock_interaction.guild.channels = [allowed, denied]
    assert available_channels(mock_interaction) == [1]


async def test_view_never_posts_source_content_publicly(mock_bot, mock_interaction, monkeypatch):
    cog = Marketplace(mock_bot)
    monkeypatch.setattr(cog.ingestion, 'rows', AsyncMock(return_value=[]))
    await Marketplace.mp_view.callback(cog, mock_interaction, 'private')
    assert mock_interaction.response.send_message.call_args.kwargs['ephemeral'] is True


def test_prices_have_explicit_currency():
    assert Marketplace._price('Keyboard AED 150.00', '') == (150, 'AED')
    assert Marketplace._price('GPU INR 2000', '') == (2000, 'INR')
    assert Marketplace._price('RTX 4090', '') == (None, None)
