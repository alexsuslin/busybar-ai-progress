from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import NoReturn, Protocol, TextIO, cast
from urllib.parse import urlsplit

from . import __version__
from .assets import render_assets
from .busybar import BusyBarDisplay, DisplayBusyError, DisplayUnavailableError
from .config import Config
from .daemon import StateDisplay, StatusDaemon
from .events import DisplayState, SafeEvent, normalize_hook
from .queue import EventQueue
from .state import SessionReducer

MAX_HOOK_BYTES = 1024 * 1024
logger = logging.getLogger(__name__)


class DisplayProbe(Protocol):
    def probe(self) -> str: ...


DisplayFactory = Callable[[Config], DisplayProbe]


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _parser() -> Parser:
    parser = Parser(prog="busybar-codex")
    parser.add_argument("--address")
    parser.add_argument("--priority", type=int)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("hook")
    commands.add_parser("status")
    set_parser = commands.add_parser("set")
    set_parser.add_argument("state", choices=[state.value for state in _renderable_states()])
    commands.add_parser("doctor")
    assets_parser = commands.add_parser("render-assets")
    assets_parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("assets"),
    )
    return parser


def _renderable_states() -> tuple[DisplayState, DisplayState, DisplayState]:
    return DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE


def _resolved_config(
    args: argparse.Namespace,
    environ: Mapping[str, str] | None,
) -> Config:
    values = dict(os.environ if environ is None else environ)
    address = cast(str | None, args.address)
    priority = cast(int | None, args.priority)
    if address is not None:
        values["BUSYBAR_CODEX_ADDRESS"] = address
    if priority is not None:
        values["BUSYBAR_CODEX_PRIORITY"] = str(priority)
    return Config.load(path=cast(Path | None, args.config), environ=values)


def _configure_logging(config: Config) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    package_logger = logging.getLogger("busybar_codex")
    package_logger.setLevel(config.log_level)
    log_path = config.log_dir / "busybar-codex.log"
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == log_path.resolve()
        for handler in package_logger.handlers
    ):
        return
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    package_logger.addHandler(handler)


def _hook(config: Config, stream: TextIO) -> int:
    try:
        raw = stream.read(MAX_HOOK_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_HOOK_BYTES:
            logger.warning("hook payload rejected reason=too_large")
            return 0
        decoded = cast(object, json.loads(raw))
        if not isinstance(decoded, dict):
            logger.warning("hook payload rejected reason=not_object")
            return 0
        event = normalize_hook(cast(dict[str, object], decoded))
        if event is not None:
            EventQueue(config.state_dir / "queue").put(event)
    except (OSError, UnicodeError, ValueError):
        logger.warning("hook payload rejected reason=invalid")
    return 0


def _set(config: Config, state_name: str, stdout: TextIO) -> int:
    state = DisplayState(state_name)
    event = SafeEvent(
        session_id="manual",
        turn_id=None,
        state=state,
        timestamp=datetime.now(UTC).isoformat(),
        reason="manual",
    )
    EventQueue(config.state_dir / "queue").put(event)
    stdout.write(f"queued: {state.value}\n")
    return 0


def _load_reducer(config: Config) -> SessionReducer:
    return SessionReducer.load(
        config.state_dir / "sessions.json",
        stale_after_seconds=config.stale_after_seconds,
    )


def _redacted_address(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{hostname}{port}{path}"


def _status(config: Config, stdout: TextIO, display_factory: DisplayFactory) -> int:
    reducer = _load_reducer(config)
    state = reducer.aggregate()
    try:
        api_version = display_factory(config).probe()
        connectivity = "online"
    except (DisplayBusyError, DisplayUnavailableError):
        api_version = None
        connectivity = "offline"
    stdout.write(
        json.dumps(
            {"state": state.value, "device": connectivity, "api_version": api_version},
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _doctor(config: Config, stdout: TextIO, display_factory: DisplayFactory) -> int:
    stdout.write(f"python: ok ({sys.version_info.major}.{sys.version_info.minor})\n")
    stdout.write(f"package: ok ({__version__})\n")
    stdout.write(f"address: {_redacted_address(config.base_url)}\n")
    try:
        for directory in (config.config_dir, config.state_dir, config.cache_dir, config.log_dir):
            directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        stdout.write(f"paths: unavailable ({type(error).__name__})\n")
        return 1
    stdout.write("paths: ok\n")
    hooks_path = Path.cwd() / ".codex" / "hooks.json"
    stdout.write(f"hooks: {'ok' if hooks_path.is_file() else 'missing'}\n")
    try:
        version = display_factory(config).probe()
    except (DisplayBusyError, DisplayUnavailableError) as error:
        stdout.write(f"device: unavailable ({type(error).__name__})\n")
        return 1
    stdout.write(f"device: ok (API {version})\n")
    return 0


def _run(config: Config, display_factory: DisplayFactory) -> int:
    reducer = _load_reducer(config)
    display = cast(StateDisplay, display_factory(config))
    daemon = StatusDaemon(
        queue=EventQueue(config.state_dir / "queue"),
        reducer=reducer,
        display=display,
        snapshot_path=config.state_dir / "sessions.json",
        poll_interval_seconds=config.poll_interval_seconds,
    )
    try:
        daemon.run()
    except KeyboardInterrupt:
        return 0
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    display_factory: DisplayFactory | None = None,
) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    factory = display_factory or BusyBarDisplay.from_config
    try:
        args = _parser().parse_args(argv)
        config = _resolved_config(args, environ)
        _configure_logging(config)
        command = cast(str, args.command)
        if command == "hook":
            return _hook(config, input_stream)
        if command == "set":
            return _set(config, cast(str, args.state), output_stream)
        if command == "status":
            return _status(config, output_stream, factory)
        if command == "doctor":
            return _doctor(config, output_stream, factory)
        if command == "render-assets":
            render_assets(cast(Path, args.output))
            return 0
        if command == "run":
            return _run(config, factory)
    except UsageError:
        error_stream.write("invalid arguments\n")
        return 2
    except ValueError:
        error_stream.write("invalid configuration or state\n")
        return 2
    except OSError as error:
        error_stream.write(f"operational failure: {type(error).__name__}\n")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
