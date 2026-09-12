# BUSY Bar Codex Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-first Python daemon that maps local Codex lifecycle hooks to `CODING...`, `QUESTION?`, and `DONE` images on a BUSY Bar, with faithful testing against the community emulator.

**Architecture:** Codex hooks synchronously normalize stdin JSON into privacy-safe event files and exit without contacting the device. A foreground daemon drains those files into a persisted per-session reducer, computes `question > coding > done`, and renders only state changes through an isolated BUSY Bar adapter. The adapter accepts either the USB device address, the emulator at `127.0.0.1:8080`, or the manager proxy at `127.0.0.1:8321`.

**Tech Stack:** Python 3.13, uv, busylib 2.x, Pillow, platformdirs, pytest, Ruff, Pyright, PowerShell, Node.js 24 for the external emulator.

**Spec:** `docs/superpowers/specs/2026-09-11-busybar-codex-status-design.md`

## Global Constraints

- Windows is the primary supported runtime for the first release; portable core code where practical.
- Default BUSY Bar address is `http://10.0.4.20`; emulator address is `http://127.0.0.1:8080`; manager proxy compatibility uses `http://127.0.0.1:8321`.
- Application name is `codex-status`; the front RGB assets are exactly 72×16 pixels.
- Aggregate precedence is `question > coding > done`; active records become stale after 24 hours by default.
- Hooks never contact hardware and always fail open with exit code `0` after recording a safe diagnostic when possible.
- Never persist or log prompt text, tool arguments, assistant messages, approval descriptions, authentication tokens, or `~/.codex/auth.json`.
- HTTP `409` means another application owns the display; retry with backoff without raising priority automatically.
- Exit codes are `0` for success, `1` for operational failure, and `2` for invalid configuration or input.
- Every change must pass `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright`.
- Hardware tests are opt-in and never run in GitHub Actions.

---

## File Map

```text
.codex/hooks.json                         Project-local Codex hook wiring
.github/workflows/ci.yml                  Windows/Linux quality gates
scripts/emulator.ps1                      Clone/build/start the external emulator
src/busybar_codex/__init__.py             Package version
src/busybar_codex/__main__.py             `python -m` entry point
src/busybar_codex/assets.py               Deterministic 72x16 asset generation
src/busybar_codex/busybar.py              BUSY Bar SDK boundary and retryable errors
src/busybar_codex/cli.py                  Public CLI commands and exit codes
src/busybar_codex/config.py               TOML/environment/CLI configuration
src/busybar_codex/daemon.py               Queue-to-reducer-to-display event loop
src/busybar_codex/events.py               Hook normalization and safe event model
src/busybar_codex/queue.py                Atomic one-file-per-event storage
src/busybar_codex/state.py                Session reducer, persistence, aggregation
src/busybar_codex/assets/*.png             Generated status images
tests/contract/test_hooks.py               Codex stdin contract and privacy tests
tests/integration/test_emulator.py         Opt-in emulator HTTP behavior
tests/unit/test_assets.py                  Image dimensions and determinism
tests/unit/test_busybar.py                 SDK adapter and 409 behavior
tests/unit/test_config.py                  Defaults and overrides
tests/unit/test_daemon.py                  Last-state-wins daemon behavior
tests/unit/test_events.py                  Hook-to-event normalization
tests/unit/test_queue.py                   Atomic queue behavior
tests/unit/test_state.py                   Reducer and aggregate precedence
AGENTS.md                                  Codex hook usage guidance
CHANGELOG.md                               Release history
CONTRIBUTING.md                            Development and test workflow
LICENSE                                    MIT license
README.md                                  Install, run, emulator, manager, hardware
SECURITY.md                                Privacy and vulnerability reporting
pyproject.toml                             Package, tools, dependencies
uv.lock                                    Reproducible dependency resolution
```

### Task 1: Package scaffold and typed configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/busybar_codex/__init__.py`
- Create: `src/busybar_codex/config.py`
- Create: `tests/unit/test_config.py`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `CHANGELOG.md`

**Interfaces:**
- Consumes: Environment variables and optional TOML at the platform-specific config path.
- Produces: `Config.load(path: Path | None = None, environ: Mapping[str, str] | None = None) -> Config`, `Config.base_url: str`, and platform-specific queue/state/cache/log paths.

- [ ] **Step 1: Write the package metadata and failing configuration tests**

```toml
[project]
name = "busybar-codex-status"
version = "0.1.0"
description = "Show local Codex lifecycle state on a BUSY Bar"
requires-python = ">=3.13"
dependencies = [
  "busylib>=2.1,<3",
  "pillow>=11,<13",
  "platformdirs>=4.3,<5",
]

[project.scripts]
busybar-codex = "busybar_codex.cli:main"

[dependency-groups]
dev = ["pytest>=8.4,<10", "pytest-cov>=6,<8", "ruff>=0.12,<1", "pyright>=1.1.400,<2"]

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/busybar_codex"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["emulator: requires BUSY Bar emulator", "hardware: requires physical BUSY Bar"]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.pyright]
pythonVersion = "3.13"
typeCheckingMode = "strict"
include = ["src", "tests"]
```

```python
# tests/unit/test_config.py
from pathlib import Path

from busybar_codex.config import Config


def test_defaults_are_usb_safe(tmp_path: Path) -> None:
    config = Config.load(path=tmp_path / "missing.toml", environ={})
    assert config.base_url == "http://10.0.4.20"
    assert config.application_name == "codex-status"
    assert config.priority == 50
    assert config.stale_after_seconds == 86_400


def test_environment_overrides_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('address = "127.0.0.1:8080"\npriority = 40\n', encoding="utf-8")
    config = Config.load(
        path=path,
        environ={"BUSYBAR_CODEX_ADDRESS": "127.0.0.1:8321", "BUSYBAR_CODEX_PRIORITY": "60"},
    )
    assert config.base_url == "http://127.0.0.1:8321"
    assert config.priority == 60
```

- [ ] **Step 2: Lock dependencies and run the focused test to verify it fails**

Run: `uv lock && uv run pytest tests/unit/test_config.py -v`

Expected: collection fails because `busybar_codex.config` does not exist.

- [ ] **Step 3: Implement immutable configuration with URL normalization and validation**

```python
# src/busybar_codex/config.py
from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "busybar-codex-status"
DIRS = PlatformDirs(APP_NAME, "alexsuslin")


def _url(value: str) -> str:
    value = value.rstrip("/")
    return value if "://" in value else f"http://{value}"


@dataclass(frozen=True, slots=True)
class Config:
    base_url: str = "http://10.0.4.20"
    application_name: str = "codex-status"
    token: str | None = None
    priority: int = 50
    stale_after_seconds: int = 86_400
    poll_interval_seconds: float = 0.2
    request_timeout_seconds: float = 2.0
    log_level: str = "INFO"
    config_dir: Path = Path(DIRS.user_config_dir)
    state_dir: Path = Path(DIRS.user_state_dir)
    cache_dir: Path = Path(DIRS.user_cache_dir)
    log_dir: Path = Path(DIRS.user_log_dir)

    @classmethod
    def load(
        cls,
        path: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Config:
        env = os.environ if environ is None else environ
        config_path = path or Path(DIRS.user_config_dir) / "config.toml"
        raw = tomllib.loads(config_path.read_text("utf-8")) if config_path.exists() else {}
        address = env.get("BUSYBAR_CODEX_ADDRESS", str(raw.get("address", "10.0.4.20")))
        application_name = env.get(
            "BUSYBAR_CODEX_APPLICATION_NAME", str(raw.get("application_name", "codex-status"))
        )
        token_value = env.get("BUSYBAR_CODEX_TOKEN", raw.get("token"))
        priority = int(env.get("BUSYBAR_CODEX_PRIORITY", str(raw.get("priority", 50))))
        stale = int(
            env.get("BUSYBAR_CODEX_STALE_AFTER_SECONDS", str(raw.get("stale_after_seconds", 86_400)))
        )
        poll = float(
            env.get("BUSYBAR_CODEX_POLL_INTERVAL_SECONDS", str(raw.get("poll_interval_seconds", 0.2)))
        )
        timeout = float(
            env.get("BUSYBAR_CODEX_REQUEST_TIMEOUT_SECONDS", str(raw.get("request_timeout_seconds", 2.0)))
        )
        log_level = env.get("BUSYBAR_CODEX_LOG_LEVEL", str(raw.get("log_level", "INFO"))).upper()
        if not 1 <= priority <= 100:
            raise ValueError("priority must be between 1 and 100")
        if stale <= 0 or poll <= 0 or timeout <= 0:
            raise ValueError("timing values must be positive")
        if not application_name.strip():
            raise ValueError("application_name must not be empty")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid log_level")
        return cls(
            base_url=_url(address),
            application_name=application_name,
            token=str(token_value) if token_value else None,
            priority=priority,
            stale_after_seconds=stale,
            poll_interval_seconds=poll,
            request_timeout_seconds=timeout,
            log_level=log_level,
        )
```

Also add `__version__ = "0.1.0"`, an MIT `LICENSE`, an initial `CHANGELOG.md`, and ignore `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.pyright/`, `.coverage`, `htmlcov/`, `.dev/`, and generated Python caches.

- [ ] **Step 4: Run the configuration tests and all static gates**

Run: `uv run pytest tests/unit/test_config.py -v && uv run ruff check . && uv run ruff format --check . && uv run pyright`

Expected: all commands exit `0`.

- [ ] **Step 5: Commit the scaffold**

```powershell
git add pyproject.toml uv.lock .gitignore LICENSE CHANGELOG.md src tests/unit/test_config.py
git -c commit.gpgsign=false commit -m "chore: scaffold Python project"
```

### Task 2: Privacy-safe hook normalization and atomic queue

**Files:**
- Create: `src/busybar_codex/events.py`
- Create: `src/busybar_codex/queue.py`
- Create: `tests/unit/test_events.py`
- Create: `tests/unit/test_queue.py`
- Create: `tests/contract/test_hooks.py`

**Interfaces:**
- Consumes: `Mapping[str, object]` decoded from one Codex hook stdin object.
- Produces: `SafeEvent`, `normalize_hook(payload, now) -> SafeEvent | None`, `EventQueue.put(event) -> Path`, and `EventQueue.drain() -> list[SafeEvent]`.

- [ ] **Step 1: Write failing transition, redaction, and queue tests**

```python
# tests/unit/test_events.py
from datetime import UTC, datetime

from busybar_codex.events import DisplayState, normalize_hook

NOW = datetime(2026, 9, 11, tzinfo=UTC)


def test_permission_request_becomes_question() -> None:
    event = normalize_hook({"hook_event_name": "PermissionRequest", "session_id": "s1"}, NOW)
    assert event is not None
    assert event.state is DisplayState.QUESTION


def test_prompt_content_is_not_serialized() -> None:
    event = normalize_hook(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "secret"}, NOW
    )
    assert event is not None
    assert "secret" not in event.to_json()
```

```python
# tests/unit/test_queue.py
from pathlib import Path

from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.queue import EventQueue


def test_queue_ignores_incomplete_temp_files(tmp_path: Path) -> None:
    queue = EventQueue(tmp_path)
    event = SafeEvent("s1", None, DisplayState.CODING, "2026-09-11T00:00:00+00:00", "prompt")
    queue.put(event)
    (tmp_path / "orphan.tmp").write_text("partial", encoding="utf-8")
    assert queue.drain() == [event]
    assert (tmp_path / "orphan.tmp").exists()
```

```python
# tests/contract/test_hooks.py
import json

from busybar_codex.events import DisplayState, normalize_hook


def test_request_user_input_pre_tool_use_is_question() -> None:
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "request_user_input",
        "tool_input": {"questions": [{"question": "private"}]},
    }
    event = normalize_hook(payload)
    assert event is not None
    assert event.state is DisplayState.QUESTION
    assert "private" not in event.to_json()


def test_unknown_hook_is_ignored() -> None:
    assert normalize_hook(json.loads('{"hook_event_name":"FutureHook"}')) is None
```

- [ ] **Step 2: Run the focused tests and verify missing modules fail**

Run: `uv run pytest tests/unit/test_events.py tests/unit/test_queue.py tests/contract/test_hooks.py -v`

Expected: collection fails for missing `events` and `queue` modules.

- [ ] **Step 3: Implement the safe event model and exact hook mapping**

```python
# src/busybar_codex/events.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class DisplayState(StrEnum):
    CODING = "coding"
    QUESTION = "question"
    DONE = "done"
    REGISTER = "register"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class SafeEvent:
    session_id: str
    turn_id: str | None
    state: DisplayState
    timestamp: str
    reason: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _asks_for_input(message: object) -> bool:
    if not isinstance(message, str):
        return False
    normalized = message.strip().casefold()
    # The escaped phrases also match Russian prompts: "reply with one" and "choose an option".
    phrases = (
        "please choose",
        "which option",
        "reply with",
        "\u043e\u0442\u0432\u0435\u0442\u044c \u043e\u0434\u043d\u0438\u043c",
        "\u0432\u044b\u0431\u0435\u0440\u0438 \u0432\u0430\u0440\u0438\u0430\u043d\u0442",
    )
    return normalized.endswith("?") or any(phrase in normalized for phrase in phrases)


def normalize_hook(
    payload: dict[str, Any], now: datetime | None = None
) -> SafeEvent | None:
    name = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(name, str) or not isinstance(session_id, str):
        return None
    mapping = {
        "UserPromptSubmit": (DisplayState.CODING, "prompt"),
        "PermissionRequest": (DisplayState.QUESTION, "permission"),
        "Interrupt": (DisplayState.DONE, "interrupted"),
        "SessionEnd": (DisplayState.REMOVE, "session_end"),
    }
    if name == "PreToolUse" and payload.get("tool_name") == "request_user_input":
        state, reason = DisplayState.QUESTION, "user_input"
    elif name == "PostToolUse":
        state, reason = DisplayState.CODING, "tool_complete"
    elif name == "Stop":
        asks = _asks_for_input(payload.get("last_assistant_message"))
        state, reason = (DisplayState.QUESTION, "final_question") if asks else (DisplayState.DONE, "stop")
    elif name == "SessionStart":
        state, reason = DisplayState.REGISTER, "session_start"
    elif name in mapping:
        state, reason = mapping[name]
    else:
        return None
    turn_id = payload.get("turn_id")
    stamp = (now or datetime.now(UTC)).isoformat()
    return SafeEvent(session_id, turn_id if isinstance(turn_id, str) else None, state, stamp, reason)
```

Implement `EventQueue.put` with `tempfile.NamedTemporaryFile(delete=False, dir=queue_dir)`, `flush`, `os.fsync`, and `os.replace`; name committed files with Windows-safe, lexically ordered `time.time_ns()` plus `uuid.uuid4().hex`, for example `1789056000000000000-a1b2.json`. Implement `drain` by sorting only `*.json`, parsing each into `SafeEvent`, deleting successfully parsed files, and quarantining malformed files to `rejected/` without logging their contents.

- [ ] **Step 4: Run queue and hook tests**

Run: `uv run pytest tests/unit/test_events.py tests/unit/test_queue.py tests/contract/test_hooks.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the hook boundary**

```powershell
git add src/busybar_codex/events.py src/busybar_codex/queue.py tests/unit tests/contract
git -c commit.gpgsign=false commit -m "feat: capture privacy-safe Codex events"
```

### Task 3: Session reducer, aggregate state, and crash recovery

**Files:**
- Create: `src/busybar_codex/state.py`
- Create: `tests/unit/test_state.py`

**Interfaces:**
- Consumes: ordered `SafeEvent` instances.
- Produces: `SessionReducer.apply(event) -> DisplayState`, `SessionReducer.aggregate(now) -> DisplayState`, `SessionReducer.save(path) -> None`, and `SessionReducer.load(path, stale_after) -> SessionReducer`.

- [ ] **Step 1: Write failing reducer tests**

```python
# tests/unit/test_state.py
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.state import SessionReducer

NOW = datetime(2026, 9, 11, tzinfo=UTC)


def event(session: str, state: DisplayState, age: int = 0) -> SafeEvent:
    stamp = (NOW - timedelta(seconds=age)).isoformat()
    return SafeEvent(session, None, state, stamp, "test")


def test_question_wins_across_sessions() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("coding", DisplayState.CODING))
    reducer.apply(event("waiting", DisplayState.QUESTION))
    assert reducer.aggregate(NOW) is DisplayState.QUESTION


def test_stale_active_session_falls_back_to_done() -> None:
    reducer = SessionReducer(stale_after_seconds=60)
    reducer.apply(event("old", DisplayState.CODING, age=61))
    assert reducer.aggregate(NOW) is DisplayState.DONE


def test_post_tool_only_resumes_a_question_session() -> None:
    reducer = SessionReducer(stale_after_seconds=60)
    reducer.apply(event("done", DisplayState.DONE))
    reducer.apply(replace(event("done", DisplayState.CODING), reason="tool_complete"))
    assert reducer.aggregate(NOW) is DisplayState.DONE
```

- [ ] **Step 2: Run the reducer tests and verify they fail**

Run: `uv run pytest tests/unit/test_state.py -v`

Expected: collection fails because `busybar_codex.state` does not exist.

- [ ] **Step 3: Implement reducer semantics and atomic snapshot persistence**

```python
# src/busybar_codex/state.py
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .events import DisplayState, SafeEvent


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    turn_id: str | None
    state: DisplayState
    timestamp: str
    reason: str


class SessionReducer:
    def __init__(self, stale_after_seconds: int, records: dict[str, SessionRecord] | None = None) -> None:
        self.stale_after_seconds = stale_after_seconds
        self.records = records or {}

    def apply(self, event: SafeEvent) -> DisplayState:
        previous = self.records.get(event.session_id)
        if event.state is DisplayState.REMOVE:
            self.records.pop(event.session_id, None)
        elif event.state is DisplayState.REGISTER:
            self.records.setdefault(
                event.session_id,
                SessionRecord(
                    event.session_id,
                    event.turn_id,
                    DisplayState.DONE,
                    event.timestamp,
                    event.reason,
                ),
            )
        elif event.reason == "tool_complete" and (
            previous is None or previous.state is not DisplayState.QUESTION
        ):
            pass
        else:
            self.records[event.session_id] = SessionRecord(**asdict(event))
        return self.aggregate()

    def aggregate(self, now: datetime | None = None) -> DisplayState:
        instant = now or datetime.now(UTC)
        fresh = [
            record
            for record in self.records.values()
            if (instant - datetime.fromisoformat(record.timestamp)).total_seconds()
            <= self.stale_after_seconds
        ]
        if any(record.state is DisplayState.QUESTION for record in fresh):
            return DisplayState.QUESTION
        if any(record.state is DisplayState.CODING for record in fresh):
            return DisplayState.CODING
        return DisplayState.DONE
```

Add `save` using sibling `.tmp`, `flush`, `os.fsync`, and `os.replace`. Add `load` that returns an empty reducer for a missing snapshot and raises `ValueError("invalid state snapshot")` without including corrupt file contents.

- [ ] **Step 4: Run reducer and persistence tests**

Run: `uv run pytest tests/unit/test_state.py -v`

Expected: precedence, staleness, removal, idempotency, guarded `PostToolUse`, save, and reload all pass.

- [ ] **Step 5: Commit the reducer**

```powershell
git add src/busybar_codex/state.py tests/unit/test_state.py
git -c commit.gpgsign=false commit -m "feat: reduce concurrent Codex session state"
```

### Task 4: Deterministic 72×16 assets

**Files:**
- Create: `src/busybar_codex/assets.py`
- Create: `src/busybar_codex/assets/.gitkeep`
- Create: `tests/unit/test_assets.py`
- Generate: `src/busybar_codex/assets/coding.png`
- Generate: `src/busybar_codex/assets/question.png`
- Generate: `src/busybar_codex/assets/done.png`

**Interfaces:**
- Consumes: `DisplayState` and an output directory.
- Produces: `render_assets(output_dir: Path) -> dict[DisplayState, Path]` and `bundled_asset(state) -> Path`.

- [ ] **Step 1: Write failing dimension and reproducibility tests**

```python
# tests/unit/test_assets.py
import hashlib
from pathlib import Path

from PIL import Image

from busybar_codex.assets import render_assets
from busybar_codex.events import DisplayState


def test_assets_are_rgb_72_by_16(tmp_path: Path) -> None:
    paths = render_assets(tmp_path)
    assert set(paths) == {DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE}
    for path in paths.values():
        with Image.open(path) as image:
            assert image.size == (72, 16)
            assert image.mode == "RGB"


def test_rendering_is_byte_deterministic(tmp_path: Path) -> None:
    first = render_assets(tmp_path / "first")
    second = render_assets(tmp_path / "second")
    digest = lambda path: hashlib.sha256(path.read_bytes()).digest()
    assert {state: digest(path) for state, path in first.items()} == {
        state: digest(path) for state, path in second.items()
    }
```

- [ ] **Step 2: Run asset tests and verify they fail**

Run: `uv run pytest tests/unit/test_assets.py -v`

Expected: collection fails because `busybar_codex.assets` does not exist.

- [ ] **Step 3: Implement a deterministic pixel-style renderer**

Use Pillow's bundled default bitmap font, a black background, fixed coordinates, and fixed colors: coding cyan `#2B7FFF`, question amber `#FFB000`, done green `#36D17C`. Draw labels `CODING`, `QUESTION`, and `DONE` centered after measuring with `textbbox`; omit punctuation when it would exceed 72 pixels. Save PNGs with fixed arguments `optimize=False` and `compress_level=9`, and expose packaged paths via `importlib.resources.files("busybar_codex") / "assets"`.

```python
def render_assets(output_dir: Path) -> dict[DisplayState, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[DisplayState, Path] = {}
    for state, (label, color) in STYLES.items():
        image = Image.new("RGB", (72, 16), "black")
        draw = ImageDraw.Draw(image)
        box = draw.textbbox((0, 0), label, font=FONT)
        x = (72 - (box[2] - box[0])) // 2
        y = (16 - (box[3] - box[1])) // 2 - box[1]
        draw.text((x, y), label, font=FONT, fill=color)
        path = output_dir / f"{state.value}.png"
        image.save(path, format="PNG", optimize=False, compress_level=9)
        rendered[state] = path
    return rendered
```

- [ ] **Step 4: Generate bundled images and run tests twice**

Run: `uv run python -c "from pathlib import Path; from busybar_codex.assets import render_assets; render_assets(Path('src/busybar_codex/assets'))"`

Run: `uv run pytest tests/unit/test_assets.py -v && uv run pytest tests/unit/test_assets.py -v`

Expected: all tests pass twice and exactly three PNG files remain tracked.

- [ ] **Step 5: Commit the assets**

```powershell
git add src/busybar_codex/assets.py src/busybar_codex/assets tests/unit/test_assets.py
git -c commit.gpgsign=false commit -m "feat: add deterministic status artwork"
```

### Task 5: BUSY Bar adapter with emulator and manager compatibility

**Files:**
- Create: `src/busybar_codex/busybar.py`
- Create: `tests/unit/test_busybar.py`
- Create: `tests/integration/test_emulator.py`

**Interfaces:**
- Consumes: `Config`, packaged PNG paths, and `DisplayState`.
- Produces: `BusyBarDisplay.probe() -> str`, `BusyBarDisplay.ensure_assets() -> None`, `BusyBarDisplay.render(state) -> None`, `DisplayBusyError`, and `DisplayUnavailableError`.

- [ ] **Step 1: Write failing adapter tests with an injected SDK client**

```python
# tests/unit/test_busybar.py
from pathlib import Path

import pytest

from busybar_codex.busybar import BusyBarDisplay, DisplayBusyError
from busybar_codex.events import DisplayState


class FakeClient:
    def __init__(self) -> None:
        self.draws: list[object] = []

    def version(self) -> object:
        return type("Version", (), {"version": "25.0.0"})()

    def assets_upload(self, **kwargs: object) -> None:
        return None

    def display_draw(self, elements: object) -> None:
        self.draws.append(elements)


def test_render_uses_stable_application_name(tmp_path: Path) -> None:
    client = FakeClient()
    display = BusyBarDisplay(client, "codex-status", 50, lambda _state: tmp_path / "asset.png")
    display.render(DisplayState.DONE)
    assert len(client.draws) == 1
    assert getattr(client.draws[0], "application_name") == "codex-status"


def test_409_is_classified_as_busy(tmp_path: Path) -> None:
    class ConflictClient(FakeClient):
        def display_draw(self, elements: object) -> None:
            raise RuntimeError("409 Conflict")

    display = BusyBarDisplay(
        ConflictClient(), "codex-status", 50, lambda _state: tmp_path / "asset.png"
    )
    with pytest.raises(DisplayBusyError):
        display.render(DisplayState.CODING)
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run: `uv run pytest tests/unit/test_busybar.py -v`

Expected: collection fails because `busybar_codex.busybar` does not exist.

- [ ] **Step 3: Implement the SDK boundary**

Construct `busylib.BusyBar` from the normalized base URL with the scheme removed only if the SDK requires a host. Upload each PNG using `busylib.converter.convert_for_storage`, always passing the configured application name. Render one front `ImageElement` with stable id `codex-state`, `(x, y) = (0, 0)`, packaged asset path, and configured priority. Store an atomic JSON upload receipt in `Config.cache_dir` keyed by redacted address, API version, application name, package version, and the three asset SHA-256 hashes; skip upload only when that exact receipt matches. Translate SDK/HTTP exceptions containing status `409` into `DisplayBusyError`; translate timeouts and connection failures into `DisplayUnavailableError`; redact URL credentials and tokens from messages.

- [ ] **Step 4: Add an opt-in emulator contract test**

```python
# tests/integration/test_emulator.py
import os

import pytest

from busybar_codex.busybar import BusyBarDisplay
from busybar_codex.config import Config
from busybar_codex.events import DisplayState

pytestmark = pytest.mark.emulator


@pytest.mark.skipif("BUSYBAR_EMULATOR_URL" not in os.environ, reason="emulator not requested")
def test_all_states_render_on_emulator() -> None:
    config = Config.load(environ={"BUSYBAR_CODEX_ADDRESS": os.environ["BUSYBAR_EMULATOR_URL"]})
    display = BusyBarDisplay.from_config(config)
    assert display.probe()
    display.ensure_assets()
    for state in (DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE):
        display.render(state)
```

Also use emulator endpoint `POST /api/_scenario/steal` with priority `99` for a second integration test asserting our priority `50` draw becomes `DisplayBusyError`, then call `POST /api/_scenario/reset` in `finally`.

- [ ] **Step 5: Run unit tests; leave emulator test skipped until Task 7**

Run: `uv run pytest tests/unit/test_busybar.py tests/integration/test_emulator.py -v`

Expected: unit tests pass and emulator tests are skipped without `BUSYBAR_EMULATOR_URL`.

- [ ] **Step 6: Commit the adapter**

```powershell
git add src/busybar_codex/busybar.py tests/unit/test_busybar.py tests/integration/test_emulator.py
git -c commit.gpgsign=false commit -m "feat: render states through BUSY Bar API"
```

### Task 6: Daemon, CLI, and Codex hooks

**Files:**
- Create: `src/busybar_codex/daemon.py`
- Create: `src/busybar_codex/cli.py`
- Create: `src/busybar_codex/__main__.py`
- Create: `tests/unit/test_daemon.py`
- Create: `tests/contract/test_cli.py`
- Create: `.codex/hooks.json`
- Create: `AGENTS.md`

**Interfaces:**
- Consumes: `Config`, `EventQueue`, `SessionReducer`, and a display implementing `render(DisplayState) -> None`.
- Produces: `StatusDaemon(queue, reducer, display, snapshot_path)`, `StatusDaemon.step() -> DisplayState`, `StatusDaemon.run() -> None`, and `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing last-state-wins and fail-open CLI tests**

```python
# tests/unit/test_daemon.py
from pathlib import Path

from busybar_codex.daemon import StatusDaemon
from busybar_codex.events import DisplayState
from busybar_codex.queue import EventQueue
from busybar_codex.state import SessionReducer


class RecordingDisplay:
    def __init__(self) -> None:
        self.states: list[DisplayState] = []

    def render(self, state: DisplayState) -> None:
        self.states.append(state)


def test_daemon_renders_only_aggregate_changes(tmp_path: Path) -> None:
    display = RecordingDisplay()
    daemon = StatusDaemon(
        EventQueue(tmp_path / "queue"),
        SessionReducer(stale_after_seconds=86_400),
        display,
        tmp_path / "state.json",
    )
    daemon.inject("s1", DisplayState.CODING)
    daemon.step()
    daemon.inject("s2", DisplayState.CODING)
    daemon.step()
    assert display.states == [DisplayState.CODING]
```

```python
# tests/contract/test_cli.py
import io

from busybar_codex.cli import main


def test_malformed_hook_input_fails_open(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json"))
    assert main(["hook"]) == 0


def test_set_rejects_unknown_state() -> None:
    assert main(["set", "unknown"]) == 2
```

- [ ] **Step 2: Run daemon/CLI tests and verify they fail**

Run: `uv run pytest tests/unit/test_daemon.py tests/contract/test_cli.py -v`

Expected: collection fails for missing daemon and CLI modules.

- [ ] **Step 3: Implement one-step daemon processing and bounded retry state**

`step` drains all committed queue events, applies them in filename order, persists once, calculates the aggregate once, and renders only when it differs from `_last_rendered` or `_needs_reconnect_render` is true. On `DisplayBusyError`, keep the pending aggregate and set the next attempt using exponential delays `1, 2, 4, 8, 16, 30` seconds plus injected jitter. On `DisplayUnavailableError`, use the same cap. Successful rendering resets the attempt counter. `run` catches unexpected operational exceptions, logs exception type without event content, and waits via an injected `Event.wait` so shutdown is testable.

- [ ] **Step 4: Implement the argparse CLI**

Create subcommands `run`, `hook`, `status`, `set {coding,question,done}`, `doctor`, and `render-assets`; add global `--address`, `--priority`, and `--config`. `hook` reads at most 1 MiB from stdin, catches JSON/validation/filesystem failures, writes only a sanitized diagnostic, and returns `0`. `doctor` reports Python, package version, resolved redacted address, writable local paths, hook-file presence, API compatibility, and returns `1` only for failed required checks. `status` emits aggregate state and connectivity without sessions' prompt data. Configure a `logging.handlers.RotatingFileHandler` in `Config.log_dir` with a 1 MiB limit and three backups, and ensure log records contain only event types, reason codes, state, exception classes, and redacted addresses. Add `__main__.py` containing `raise SystemExit(main())`.

- [ ] **Step 5: Wire project-local hooks**

```json
{
  "description": "Reflect Codex lifecycle state on a BUSY Bar.",
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 3}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 3}]}],
    "PermissionRequest": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 3}]}],
    "PreToolUse": [{"matcher": "^request_user_input$", "hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 3}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 3}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 3}]}],
    "Interrupt": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 1}]}],
    "SessionEnd": [{"hooks": [{"type": "command", "command": "uv run --project \"$(git rev-parse --show-toplevel)\" busybar-codex hook", "commandWindows": "powershell -NoProfile -Command \"$r = git rev-parse --show-toplevel; uv run --project $r busybar-codex hook\"", "timeout": 1}]}]
  }
}
```

Validate the resulting JSON against the installed Codex hook loader and inspect it with `/hooks`; commands must work when Codex starts in a repository subdirectory.

Document in `AGENTS.md` that blocking questions should use `request_user_input` when available, and that hooks may never log raw stdin or contact external services.

- [ ] **Step 6: Run daemon, CLI, and hook tests**

Run: `uv run pytest tests/unit/test_daemon.py tests/contract -v`

Expected: all tests pass; malformed and unknown input never writes raw content and hook exit code remains `0`.

- [ ] **Step 7: Commit the runtime**

```powershell
git add src/busybar_codex/daemon.py src/busybar_codex/cli.py tests .codex/hooks.json AGENTS.md
git -c commit.gpgsign=false commit -m "feat: run Codex status daemon and hooks"
```

### Task 7: Emulator workflow and end-to-end verification

**Files:**
- Create: `scripts/emulator.ps1`
- Modify: `.gitignore`
- Create: `README.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `.github/workflows/ci.yml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Node.js 22+, npm, Git, and the external `maxswinkels/busybar-emulator` repository.
- Produces: repeatable local emulator startup and documented USB/manager/emulator workflows.

- [ ] **Step 1: Add a PowerShell emulator bootstrap with explicit actions**

```powershell
param(
    [ValidateSet("install", "start")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$emulatorDir = Join-Path $repoRoot ".dev\busybar-emulator"

if ($Action -eq "install") {
    if (-not (Test-Path -LiteralPath $emulatorDir)) {
        git clone https://github.com/maxswinkels/busybar-emulator.git $emulatorDir
    }
    Push-Location (Join-Path $emulatorDir "web")
    try {
        npm install
        npm run build
    } finally {
        Pop-Location
    }
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $emulatorDir "server.js"))) {
    throw "Emulator is not installed. Run: .\scripts\emulator.ps1 install"
}

Push-Location $emulatorDir
try {
    node server.js
} finally {
    Pop-Location
}
```

The script must resolve `C:\Program Files\nodejs\node.exe` and `npm.cmd` as fallbacks when the current Windows process has a stale `PATH`.

- [ ] **Step 2: Install and launch the emulator**

Run: `.\scripts\emulator.ps1 install`

Expected: frontend build succeeds in `.dev/busybar-emulator/web/dist`.

Run in a dedicated terminal: `.\scripts\emulator.ps1 start`

Expected: emulator serves `http://127.0.0.1:8080` and its `/api/version` response reports an API semantic version.

- [ ] **Step 3: Run emulator integration tests**

Run: `$env:BUSYBAR_EMULATOR_URL='http://127.0.0.1:8080'; uv run pytest -m emulator tests/integration/test_emulator.py -v`

Expected: all three images render; the scenario endpoint forces a 409 that is classified as busy; reset restores normal rendering.

- [ ] **Step 4: Document the complete operator workflow**

`README.md` must contain exact commands for `uv sync`, asset generation, `busybar-codex doctor`, foreground daemon startup, trusting `.codex/hooks.json` through Codex `/hooks`, emulator install/start, USB at `10.0.4.20`, and manager proxy at `127.0.0.1:8321`. State that the emulator is unofficial, front-display focused, and does not replace final hardware smoke tests. `SECURITY.md` must list excluded sensitive fields and private disclosure guidance. `CONTRIBUTING.md` must list all quality commands and mark emulator/hardware tests as opt-in.

- [ ] **Step 5: Add Windows and Linux CI**

```yaml
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    strategy:
      matrix:
        os: [windows-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.13"
      - run: uv sync --locked --all-groups
      - run: uv run pytest -m "not emulator and not hardware"
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pyright
```

- [ ] **Step 6: Run the complete local quality gate**

Run: `uv run pytest -m "not hardware" && uv run ruff check . && uv run ruff format --check . && uv run pyright`

Expected: all unit, contract, and emulator tests pass with zero lint, format, or type errors.

- [ ] **Step 7: Run optional hardware smoke tests when the BUSY Bar is connected**

Run: `$env:BUSYBAR_CODEX_ADDRESS='http://10.0.4.20'; uv run busybar-codex doctor`

Run: `uv run busybar-codex set coding; uv run busybar-codex set question; uv run busybar-codex set done`

Expected: the front panel displays each corresponding image, disconnect/reconnect restores the latest state, and another higher-priority application remains respected.

- [ ] **Step 8: Commit the development workflow and release-ready documentation**

```powershell
git add scripts/emulator.ps1 .gitignore README.md CONTRIBUTING.md SECURITY.md .github/workflows/ci.yml CHANGELOG.md
git -c commit.gpgsign=false commit -m "docs: add emulator and release workflow"
```

### Task 8: Final audit and version 0.1.0 readiness

**Files:**
- Modify only files implicated by audit failures.

**Interfaces:**
- Consumes: complete repository and design specification.
- Produces: verified `0.1.0` working tree with no unreviewed generated or sensitive files.

- [ ] **Step 1: Audit privacy and placeholders**

Run: `rg -n "prompt|tool_input|last_assistant_message|auth\.json" src tests README.md SECURITY.md`

Expected: sensitive names occur only in normalization tests or ephemeral in-memory extraction; no raw values are persisted or logged; no unfinished markers remain.

- [ ] **Step 2: Verify repository contents and generated assets**

Run: `git status --short; git ls-files; uv run busybar-codex render-assets; git diff --exit-code`

Expected: no `.dev`, cache, credentials, or local state is tracked; regenerating assets produces no diff.

- [ ] **Step 3: Run final automated verification**

Run: `uv run pytest -m "not hardware" && uv run ruff check . && uv run ruff format --check . && uv run pyright`

Expected: every command exits `0` with emulator running.

- [ ] **Step 4: Verify CLI help and diagnostics**

Run: `uv run busybar-codex --help; uv run busybar-codex status; uv run busybar-codex doctor`

Expected: help lists all six commands; status contains no conversation content; doctor distinguishes emulator/device reachability from configuration errors.

- [ ] **Step 5: Record final implementation commit if the audit changed files**

```powershell
git add src tests README.md SECURITY.md CONTRIBUTING.md CHANGELOG.md
git -c commit.gpgsign=false commit -m "fix: complete release readiness audit"
```
