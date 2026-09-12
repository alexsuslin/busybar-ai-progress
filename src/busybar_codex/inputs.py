from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from queue import Empty, Full, Queue
from threading import Event, Thread

from busylib import AsyncBusyBar

from .config import Config
from .dashboard import input_actions

logger = logging.getLogger(__name__)


class DeviceInputs:
    """Local WebSocket receiver; only normalized controls cross into the daemon."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.queue: Queue[str | int] = Queue(maxsize=128)
        self.stop = Event()
        self.thread: Thread | None = None

    def start(self) -> None:
        self.thread = Thread(
            target=lambda: asyncio.run(self._run()), daemon=True, name="busybar-inputs"
        )
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def drain(self) -> list[str | int]:
        result: list[str | int] = []
        for _ in range(128):
            try:
                result.append(self.queue.get_nowait())
            except Empty:
                break
        return result

    async def _receive(self) -> None:
        client = AsyncBusyBar(
            self.config.base_url,
            token=self.config.token,
            timeout=self.config.request_timeout_seconds,
            max_retries=0,
            compatibility_mode="warn",
        )
        async with client:
            async for message in client.stream_status_ws():
                for action in input_actions(message):
                    with suppress(Full):
                        self.queue.put_nowait(action)

    async def _run(self) -> None:
        attempts = 0
        while not self.stop.is_set():
            task = asyncio.create_task(self._receive())
            started = asyncio.get_running_loop().time()
            while not task.done() and not self.stop.is_set():
                await asyncio.sleep(0.2)
            if self.stop.is_set():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                return
            except Exception as error:
                # Exceptions may contain the WebSocket URL and token. No traceback.
                logger.warning("input stream unavailable error=%s", type(error).__name__)
            if asyncio.get_running_loop().time() - started > 30:
                attempts = 0
            delay = min(2 ** min(attempts, 5), 30)
            attempts += 1
            for _ in range(delay * 5):
                if self.stop.is_set():
                    return
                await asyncio.sleep(0.2)
