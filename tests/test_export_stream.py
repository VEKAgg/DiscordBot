"""Bounded export storage, UTF-8 splitting, permission checks and cancellation cleanup."""

import asyncio
import io
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.cogs.external import export as module
from src.services.export_stream import ExportContent, file_io, utf8_chunks
from src.utils.outbound import SendOutcome, SendStatus


@pytest.mark.parametrize('text,size', [('abc🙂你好' * 20, 11), ('🙂' * 20, 4), ('single long line' * 100, 17)])
async def test_chunks_are_bounded_and_valid_utf8_without_losing_bytes(text, size):
    chunks = [part async for part in utf8_chunks(io.BytesIO(text.encode()), size)]
    assert b''.join(chunks) == text.encode()
    assert all(0 < len(part) <= size for part in chunks)
    assert all(part.decode('utf-8') for part in chunks)


async def test_incomplete_utf8_is_rejected_instead_of_truncated():
    with pytest.raises(ValueError, match='UTF-8'):
        _ = [part async for part in utf8_chunks(io.BytesIO(b'abc\xf0'), 4)]


async def test_file_io_cancellation_waits_for_worker_before_cleanup():
    started, finish = threading.Event(), threading.Event()

    def write():
        started.set()
        assert finish.wait(3)

    # This is test orchestration, not an untracked bot background task.
    task = asyncio.create_task(file_io(write))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()  # repeated shutdown/reload cancellation must also wait
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.fixture
def cog(monkeypatch, mock_bot):
    cog = module.ChatExport(mock_bot)
    monkeypatch.setattr(cog, '_is_healthy', lambda: True)
    monkeypatch.setattr(cog, '_can_read', lambda *_args: True)
    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock())
    return cog


def _channel(text, count):
    async def history(**_kwargs):
        for _ in range(count):
            yield SimpleNamespace(
                created_at=datetime.now(UTC),
                author=SimpleNamespace(name='owner', discriminator='0'),
                content=text,
                attachments=[],
                embeds=[],
            )

    return cast(Any, SimpleNamespace(id=1, name='test', history=history))


async def test_history_spools_to_disk_and_keeps_correct_header(cog, mock_user):
    content, count = await cog._export_channel(_channel('x' * 8000, 200), mock_user)
    assert content is not None and count == 200
    try:
        assert cast(Any, content.body)._rolled
        assert content.size > 1024 * 1024
        first = content.read(500)
        assert b'Messages: 200' in first and b'Channel: #test' in first
    finally:
        content.close()
    assert content.body.closed


async def test_storage_limit_stops_and_closes_temp_file(cog, mock_user, monkeypatch):
    stream = io.BytesIO()
    monkeypatch.setattr(module.tempfile, 'SpooledTemporaryFile', lambda **_kwargs: stream)
    monkeypatch.setattr(module, 'MAX_CHANNEL_BYTES', 64)
    assert await cog._export_channel(_channel('x' * 100, 10), mock_user) == (None, 0)
    assert cog._cancel_export and stream.closed


async def test_cancelled_collection_closes_temp_file(cog, mock_user, monkeypatch):
    stream = io.BytesIO()
    monkeypatch.setattr(module.tempfile, 'SpooledTemporaryFile', lambda **_kwargs: stream)

    async def history(**_kwargs):
        raise asyncio.CancelledError
        yield  # async generator interface

    channel = cast(Any, SimpleNamespace(id=1, name='test', history=history))
    with pytest.raises(asyncio.CancelledError):
        await cog._export_channel(channel, mock_user)
    assert stream.closed


async def test_sender_reads_one_bounded_part_and_closes_on_failure(cog, mock_user, monkeypatch):
    body = io.BytesIO(('🙂' * 20).encode())
    content = ExportContent(body, b'', len(body.getvalue()))
    parts = []

    async def dm(_owner, **kwargs):
        parts.append(kwargs['file'].fp.read())
        return SendOutcome(SendStatus.FORBIDDEN)

    monkeypatch.setattr(module, 'MAX_FILE_SIZE', 11)
    monkeypatch.setattr(module.outbound, 'dm', AsyncMock(side_effect=dm))
    assert not await cog._send_file_dm(mock_user, 'test.txt', content)
    assert len(parts) == 1 and len(parts[0]) <= 11
    assert body.closed


async def test_permission_revocation_stops_before_next_part(cog, mock_user, monkeypatch):
    content = ExportContent(io.BytesIO(b'x' * 50), b'', 50)
    send = AsyncMock(return_value=SendOutcome(SendStatus.SENT))
    monkeypatch.setattr(module, 'MAX_FILE_SIZE', 11)
    monkeypatch.setattr(module.outbound, 'dm', send)
    monkeypatch.setattr(cog, '_can_read', lambda *_args: send.await_count == 0)
    assert not await cog._send_file_dm(mock_user, 'test.txt', content, channel=_channel('', 0))
    assert send.await_count == 1 and content.body.closed


def test_live_permission_check_rejects_member_who_left():
    guild = SimpleNamespace(get_member=lambda _uid: None, me=object())
    channel = cast(Any, SimpleNamespace(guild=guild))
    assert not module.ChatExport._can_read(channel, cast(Any, SimpleNamespace(id=123)))


async def test_successful_split_delivers_all_bytes_with_unique_keys(cog, mock_user, monkeypatch):
    text = ('Hello🙂world你好' * 20).encode()
    content = ExportContent(io.BytesIO(text), b'Header\n', len(text))
    parts, keys = [], []

    async def dm(_owner, **kwargs):
        parts.append(kwargs['file'].fp.read())
        keys.append(kwargs['dedupe_key'])
        return SendOutcome(SendStatus.SENT)

    monkeypatch.setattr(module, 'MAX_FILE_SIZE', 19)
    monkeypatch.setattr(module.outbound, 'dm', AsyncMock(side_effect=dm))
    cog._status_key = 'run-1'
    assert await cog._send_file_dm(mock_user, 'test.txt', content)
    assert b''.join(parts) == b'Header\n' + text
    assert all(len(part) <= 19 for part in parts)
    assert len(keys) == len(set(keys))
    assert content.body.closed


async def test_upload_timeout_closes_buffer_and_marks_cancelled(cog, mock_interaction, monkeypatch):
    content = ExportContent(io.BytesIO(b'body'), b'header', 4)
    monkeypatch.setattr(cog, '_export_channel', AsyncMock(return_value=(content, 1)))
    monkeypatch.setattr(cog, '_send_file_dm', AsyncMock(side_effect=TimeoutError))
    progress = AsyncMock(return_value=SendOutcome(SendStatus.SENT))
    monkeypatch.setattr(module.outbound, 'upsert_status', progress)
    await cog._perform_export(mock_interaction, [_channel('', 0)], None)
    assert content.body.closed and cog._cancel_export
    assert 'cancelled' in progress.call_args.kwargs['content']
