"""Bounded temporary export storage and UTF-8-safe attachment chunks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, BinaryIO


async def file_io(fn: Callable[..., Any], *args: Any) -> Any:
    """Finish an in-flight worker operation before cancellation lets its caller close the file."""
    # A scoped executor Future, not a detached Task: lifecycle-wide Task cancellation must not
    # cancel our completion signal while the worker still has the file open.
    future = asyncio.get_running_loop().run_in_executor(None, fn, *args)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            if future.cancelled():
                raise
            cancelled = True  # even repeated cancellation must wait until the worker releases the file
    if cancelled:
        raise asyncio.CancelledError
    return result


@dataclass
class ExportContent:
    body: BinaryIO
    header: bytes
    body_size: int
    header_offset: int = 0

    @property
    def size(self) -> int:
        return len(self.header) + self.body_size

    def read(self, size: int) -> bytes:
        prefix = self.header[self.header_offset : self.header_offset + size]
        self.header_offset += len(prefix)
        return prefix + self.body.read(size - len(prefix))

    def close(self) -> None:
        self.body.close()


async def utf8_chunks(stream, max_bytes: int) -> AsyncIterator[bytes]:
    """Bound bytes without splitting a multibyte character, even on a single enormous line."""
    if max_bytes < 4:
        raise ValueError('UTF-8 chunk size must be at least four bytes')
    pending = b''
    while True:
        chunk = pending + await file_io(stream.read, max_bytes - len(pending))
        if not chunk:
            return
        pending = b''
        try:
            chunk.decode('utf-8')
        except UnicodeDecodeError as exc:
            if exc.reason != 'unexpected end of data' or exc.end != len(chunk):
                raise ValueError('Export stream is not valid UTF-8') from None
            pending = chunk[exc.start :]
            chunk = chunk[: exc.start]
            if not chunk:
                raise ValueError('Export stream ends inside a UTF-8 character') from None
        yield chunk
