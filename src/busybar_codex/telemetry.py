from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from .events import DisplayState, SafeEvent, normalize_rollout_lifecycle


def object_map(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def number(value: object, maximum: float = 1e12) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= maximum and math.isfinite(value) else None


def label(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,79}", value):
        return value
    return None


@dataclass(frozen=True, slots=True)
class RateWindow:
    used_percent: float
    window_minutes: int
    resets_at: float | None = None


@dataclass(frozen=True, slots=True)
class Telemetry:
    model: str | None = None
    effort: str | None = None
    context_percent: float | None = None
    context_size: int | None = None
    limits: tuple[RateWindow, ...] = ()

    @property
    def provider(self) -> str | None:
        model = (self.model or "").lower()
        if "claude" in model:
            return "anthropic"
        if model.startswith(("gpt-", "o1", "o3", "o4", "openai/")):
            return "openai"
        return None

    def current_limits(self, now: float) -> tuple[RateWindow, ...]:
        return tuple(item for item in self.limits if item.resets_at is None or item.resets_at > now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> Telemetry:
        raw = object_map(json.loads(value))
        windows: list[RateWindow] = []
        items = raw.get("limits")
        if isinstance(items, list):
            for item in cast(list[object], items)[:3]:
                window = rate_window(object_map(item), "used_percent")
                if window is not None:
                    windows.append(window)
        size = number(raw.get("context_size"))
        return cls(
            label(raw.get("model")),
            effort_label(raw.get("effort")),
            number(raw.get("context_percent"), 100),
            int(size) if size else None,
            tuple(windows),
        )


def effort_label(value: object) -> str | None:
    return (
        value
        if isinstance(value, str)
        and value
        in {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        }
        else None
    )


def rate_window(
    raw: Mapping[str, object], key: str, minutes: int | None = None
) -> RateWindow | None:
    percent = number(raw.get(key), 100)
    duration = number(minutes if minutes is not None else raw.get("window_minutes"), 525600)
    if percent is None or not duration:
        return None
    return RateWindow(percent, int(duration), number(raw.get("resets_at")))


def claude_telemetry(raw: Mapping[str, object]) -> Telemetry:
    context = object_map(raw.get("context_window"))
    size = number(context.get("context_window_size"))
    rates = object_map(raw.get("rate_limits"))
    windows: list[RateWindow] = []
    for key, minutes in (("five_hour", 300), ("seven_day", 10080)):
        window = rate_window(object_map(rates.get(key)), "used_percentage", minutes)
        if window is not None:
            windows.append(window)
    return Telemetry(
        model=label(object_map(raw.get("model")).get("id")),
        effort=effort_label(object_map(raw.get("effort")).get("level")),
        context_percent=number(context.get("used_percentage"), 100),
        context_size=int(size) if size else None,
        limits=tuple(windows),
    )


class CodexTelemetry:
    """Best-effort local metadata; never copy, log or persist raw rollout records.

    Only files belonging to tracked session IDs are read. Each refresh reads at
    most 2 MiB per file. Missing/changed rollout schemas produce unknown fields.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._paths: dict[str, Path] = {}
        self._cache: dict[str, tuple[int, int, Telemetry, tuple[SafeEvent, ...]]] = {}

    def read(self, session_id: str) -> Telemetry:
        return self._snapshot(session_id)[0]

    def read_lifecycle(self, session_id: str) -> tuple[SafeEvent, ...]:
        return self._snapshot(session_id)[1]

    def _snapshot(self, session_id: str) -> tuple[Telemetry, tuple[SafeEvent, ...]]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", session_id):
            return Telemetry(), ()
        try:
            path = self._paths.get(session_id)
            if path is None or not path.is_file():
                # No paths from hook stdin are trusted or stored.
                path = next(self.directory.glob(f"**/rollout-*-{session_id}.jsonl"), None)
                if path is None:
                    path = next(self.directory.glob(f"**/rollout-{session_id}.jsonl"), None)
                if path is None:
                    return Telemetry(), ()
                if not path.resolve().is_relative_to(self.directory.resolve()):
                    return Telemetry(), ()
                self._paths[session_id] = path
            stat = path.stat()
            old = self._cache.get(session_id)
            if old is not None and old[:2] == (stat.st_mtime_ns, stat.st_size):
                return old[2], old[3]
            data, lifecycle = self._read_file(path, stat.st_size, session_id)
            self._cache[session_id] = (stat.st_mtime_ns, stat.st_size, data, lifecycle)
            return data, lifecycle
        except (OSError, ValueError):
            return Telemetry(), ()

    def _read_file(
        self, path: Path, size: int, session_id: str
    ) -> tuple[Telemetry, tuple[SafeEvent, ...]]:
        data = Telemetry()
        lifecycle: tuple[SafeEvent, ...] = ()
        with path.open("rb") as stream:
            # Read a small header for model information, then the recent tail.
            head = stream.read(min(size, 128 * 1024))
            start = max(len(head), size - 1792 * 1024)
            stream.seek(start)
            tail = stream.read(1792 * 1024)
        chunks = [head]
        if start == len(head):
            chunks = [head + tail]
        elif tail:
            # A skipped model change must not be replaced by the old header model.
            chunks = [tail.partition(b"\n")[2]]
        for chunk in chunks:
            for line in chunk.split(b"\n")[:-1]:
                # Ignore conversations without decoding their contents.
                if not any(
                    marker in line
                    for marker in (
                        b'"turn_context"',
                        b'"token_count"',
                        b'"task_started"',
                        b'"task_complete"',
                        b'"turn_aborted"',
                    )
                ):
                    continue
                try:
                    row = object_map(json.loads(line))
                except (ValueError, UnicodeError):
                    continue
                candidate = normalize_rollout_lifecycle(row, session_id)
                if (
                    candidate is None
                    and row.get("type") == "event_msg"
                    and object_map(row.get("payload")).get("type") == "task_started"
                ):
                    lifecycle = ()
                if candidate is not None and (
                    not lifecycle
                    or (
                        datetime.fromisoformat(candidate.timestamp)
                        >= datetime.fromisoformat(lifecycle[-1].timestamp)
                        and (
                            candidate.state is DisplayState.CODING
                            or candidate.turn_id == lifecycle[-1].turn_id
                        )
                    )
                ):
                    if candidate.state is DisplayState.CODING:
                        lifecycle = (candidate,)
                    else:
                        started = tuple(
                            event for event in lifecycle if event.state is DisplayState.CODING
                        )
                        lifecycle = (*started, candidate)
                raw = object_map(row.get("payload"))
                if row.get("type") == "turn_context":
                    model = label(raw.get("model"))
                    changed = model != data.model
                    data = Telemetry(
                        model,
                        effort_label(raw.get("effort")),
                        None if changed else data.context_percent,
                        None if changed else data.context_size,
                        data.limits,
                    )
                elif row.get("type") == "event_msg" and raw.get("type") == "token_count":
                    info = object_map(raw.get("info"))
                    size_value = number(info.get("model_context_window"))
                    used = number(object_map(info.get("last_token_usage")).get("total_tokens"))
                    rates = object_map(raw.get("rate_limits"))
                    windows: list[RateWindow] = []
                    for key in ("primary", "secondary"):
                        window = rate_window(object_map(rates.get(key)), "used_percent")
                        if window is not None:
                            windows.append(window)
                    data = Telemetry(
                        data.model,
                        data.effort,
                        min(100, used / size_value * 100)
                        if used is not None and size_value
                        else None,
                        int(size_value) if size_value else None,
                        tuple(windows),
                    )
        return data, lifecycle
