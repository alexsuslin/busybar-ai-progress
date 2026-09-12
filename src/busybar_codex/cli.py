from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import replace
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
from .dashboard import DisplayFrame
from .events import DisplayState, SafeEvent, normalize_hook, valid_identifier
from .inputs import DeviceInputs
from .install import install_hooks, uninstall_hooks, wsl_paths
from .local import AlreadyRunningError, ControlInbox, InstanceLock, MetadataStore, atomic_write
from .queue import EventQueue
from .state import SessionReducer
from .telemetry import CodexTelemetry, Telemetry, claude_telemetry, label

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
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--no-input", action="store_true")
    run_parser.add_argument("--no-animation", action="store_true", help="disable status motion")
    run_parser.add_argument("--no-telemetry", action="store_true")
    run_parser.add_argument("--codex-sessions-dir", type=Path, action="append")
    commands.add_parser("claude-statusline")
    for command in ("install-hooks", "uninstall-hooks"):
        installer = commands.add_parser(command)
        installer.add_argument("--client", choices=["codex", "claude"], required=True)
        installer.add_argument("--target", type=Path)
        installer.add_argument("--wsl-distro")
    for action in sorted(ControlInbox.ACTIONS):
        commands.add_parser(action)
    commands.add_parser("hook")
    commands.add_parser("status")
    set_parser = commands.add_parser("set")
    set_parser.add_argument("--session", default="manual")
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
    if args.state_dir is not None:
        values["BUSYBAR_CODEX_STATE_DIR"] = str(args.state_dir)
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


def _hook(
    config: Config, stream: TextIO, *, statusline: bool = False, stdout: TextIO | None = None
) -> int:
    try:
        raw = stream.read(MAX_HOOK_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_HOOK_BYTES:
            logger.warning("hook payload rejected reason=too_large")
            return 0
        decoded = cast(object, json.loads(raw))
        if not isinstance(decoded, dict):
            logger.warning("hook payload rejected reason=not_object")
            return 0
        payload = cast(dict[str, object], decoded)
        if statusline:
            session_id = payload.get("session_id")
            if isinstance(session_id, str) and 0 < len(session_id) <= 128:
                data = claude_telemetry(payload)
                MetadataStore(config.state_dir / "metadata").write(session_id, data)
                if stdout is not None:
                    percent = (
                        f"{data.context_percent:.0f}%"
                        if data.context_percent is not None
                        else "N/A"
                    )
                    stdout.write(
                        f"{data.model or 'MODEL N/A'} | {data.effort or 'N/A'} | CTX {percent}\n"
                    )
            return 0
        event = normalize_hook(payload)
        if event is not None:
            model = label(payload.get("model"))
            if model is not None:
                MetadataStore(config.state_dir / "hints").write(
                    event.session_id, Telemetry(model=model)
                )
            EventQueue(config.state_dir / "queue").put(event)
    except (OSError, UnicodeError, ValueError, RecursionError):
        logger.warning("hook payload rejected reason=invalid")
    return 0


def _set(config: Config, state_name: str, stdout: TextIO, session: str = "manual") -> int:
    if not valid_identifier(session):
        raise ValueError("invalid session identifier")
    state = DisplayState(state_name)
    event = SafeEvent(
        session_id=session,
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
    source = telemetry_source(config)
    sessions = [
        {
            "id": reducer.session_label(record.session_id),
            "state": record.state.value,
            "dismissed": record.session_id in reducer.dismissed,
            "telemetry": json.loads(source(record.session_id).to_json()),
        }
        for record in sorted(
            reducer.records.values(), key=lambda r: reducer.session_number(r.session_id)
        )
    ]
    stdout.write(
        json.dumps(
            {
                "state": state.value,
                "device": connectivity,
                "api_version": api_version,
                "sessions": sessions,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _doctor(
    config: Config,
    stdout: TextIO,
    display_factory: DisplayFactory,
    environ: Mapping[str, str] | None = None,
) -> int:
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
    stdout.write(f"hooks (project): {'found' if hooks_path.is_file() else 'missing'}\n")
    env = os.environ if environ is None else environ
    global_hooks = Path(env.get("CODEX_HOME", str(Path.home() / ".codex"))) / "hooks.json"
    stdout.write(f"hooks (global Codex): {'found' if global_hooks.is_file() else 'missing'}\n")
    if not global_hooks.is_file():
        stdout.write("setup: run install-hooks --client codex for other projects\n")
    stdout.write("hook trust: not checked; review BUSY Bar entries in Codex /hooks\n")
    try:
        version = display_factory(config).probe()
    except (DisplayBusyError, DisplayUnavailableError) as error:
        stdout.write(f"device: unavailable ({type(error).__name__})\n")
        return 1
    stdout.write(f"device: ok (API {version})\n")
    return 0


def _codex_sources(config: Config, directories: list[Path] | None = None) -> list[CodexTelemetry]:
    roots = [Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"]
    try:
        configured = json.loads((config.state_dir / "codex-roots.json").read_text(encoding="utf-8"))
        if isinstance(configured, list):
            roots.extend(
                Path(value)
                for value in cast(list[object], configured)[:16]
                if isinstance(value, str)
            )
    except (OSError, ValueError):
        pass
    return [CodexTelemetry(path) for path in dict.fromkeys(roots + (directories or []))]


def lifecycle_source(
    config: Config,
    directories: list[Path] | None = None,
    *,
    sources: list[CodexTelemetry] | None = None,
) -> Callable[[str], tuple[SafeEvent, ...]]:
    readers = sources if sources is not None else _codex_sources(config, directories)
    cache: dict[str, tuple[float, tuple[SafeEvent, ...]]] = {}

    def read(session_id: str) -> tuple[SafeEvent, ...]:
        now = time.monotonic()
        old = cache.get(session_id)
        if old is not None and now - old[0] < 2:
            return old[1]
        candidates = [events for source in readers if (events := source.read_lifecycle(session_id))]
        events = max(
            candidates, key=lambda rows: datetime.fromisoformat(rows[-1].timestamp), default=()
        )
        cache[session_id] = (now, events)
        return events

    return read


def telemetry_source(
    config: Config,
    directories: list[Path] | None = None,
    *,
    sources: list[CodexTelemetry] | None = None,
) -> Callable[[str], Telemetry]:
    codex_sources = sources if sources is not None else _codex_sources(config, directories)
    store = MetadataStore(config.state_dir / "metadata")
    hints = MetadataStore(config.state_dir / "hints")
    cache: dict[str, tuple[float, Telemetry]] = {}

    def read(session_id: str) -> Telemetry:
        now = time.monotonic()
        old = cache.get(session_id)
        if old is not None and now - old[0] < 2:
            return old[1]
        data = store.read(session_id)
        if data == Telemetry():
            for source in codex_sources:
                data = source.read(session_id)
                if data != Telemetry():
                    break
        hint = hints.read(session_id)
        if data.model is None and hint.provider == "anthropic":
            data = replace(data, model=hint.model)
        cache[session_id] = (now, data)
        return data

    return read


def _run(config: Config, display_factory: DisplayFactory, args: argparse.Namespace) -> int:
    with InstanceLock(config.state_dir / "daemon.lock"):
        reducer = _load_reducer(config)
        display = cast(StateDisplay, display_factory(config))
        inputs = DeviceInputs(config)
        inbox = ControlInbox(config.state_dir / "controls")

        def controls() -> list[str | int]:
            return inbox.drain() + inputs.drain()

        renderer = display.render_frame if isinstance(display, BusyBarDisplay) else None
        sources = _codex_sources(config, cast(list[Path] | None, args.codex_sessions_dir))
        daemon = StatusDaemon(
            queue=EventQueue(config.state_dir / "queue"),
            reducer=reducer,
            display=display,
            snapshot_path=config.state_dir / "sessions.json",
            poll_interval_seconds=config.poll_interval_seconds,
            frame_renderer=renderer,
            animations=config.animations and not args.no_animation,
            controls=controls,
            lifecycle=None if args.no_telemetry else lifecycle_source(config, sources=sources),
            telemetry=(None if args.no_telemetry else telemetry_source(config, sources=sources)),
        )
        if not args.no_input:
            inputs.start()
        try:
            daemon.run()
        except KeyboardInterrupt:
            pass
        finally:
            inputs.close()
            if renderer is not None:
                with suppress(DisplayBusyError, DisplayUnavailableError):
                    renderer(DisplayFrame(DisplayState.DONE, None, 0, 0, Telemetry(), hidden=True))
            if isinstance(display, BusyBarDisplay):
                display.close()
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
        command = cast(str, args.command)
        if command in {"hook", "claude-statusline"}:
            try:
                config = _resolved_config(args, environ)
                return _hook(
                    config,
                    input_stream,
                    statusline=command == "claude-statusline",
                    stdout=output_stream,
                )
            except (OSError, ValueError):
                return 0
        config = _resolved_config(args, environ)
        _configure_logging(config)
        if command in {"install-hooks", "uninstall-hooks"}:
            client_name = cast(str, args.client)
            variable = "CODEX_HOME" if client_name == "codex" else "CLAUDE_CONFIG_DIR"
            env = os.environ if environ is None else environ
            home = Path(env.get(variable, str(Path.home() / f".{client_name}")))
            target = cast(Path | None, args.target) or home / (
                "hooks.json" if client_name == "codex" else "settings.json"
            )
            executable = None
            if args.wsl_distro is not None:
                wsl_target, executable = wsl_paths(client_name, cast(str, args.wsl_distro))
                target = cast(Path | None, args.target) or wsl_target
                if command == "install-hooks" and client_name == "codex":
                    roots_path = config.state_dir / "codex-roots.json"
                    roots: list[str] = []
                    try:
                        existing = json.loads(roots_path.read_text(encoding="utf-8"))
                        if isinstance(existing, list):
                            roots = [
                                item
                                for item in cast(list[object], existing)
                                if isinstance(item, str)
                            ][:15]
                    except (OSError, ValueError):
                        pass
                    root = str(wsl_target.parent / "sessions")
                    atomic_write(roots_path, json.dumps(list(dict.fromkeys([*roots, root]))))
            if command == "install-hooks":
                installed = install_hooks(
                    client_name, target, config.state_dir, wsl_executable=executable
                )
                output_stream.write("hooks: installed; restart the AI app and review /hooks\n")
                if not installed:
                    output_stream.write("statusline: existing command preserved; see README\n")
            else:
                uninstall_hooks(client_name, target, config.state_dir, wsl_executable=executable)
                output_stream.write("hooks: removed\n")
            return 0
        if command == "set":
            return _set(config, cast(str, args.state), output_stream, cast(str, args.session))
        if command in ControlInbox.ACTIONS:
            ControlInbox(config.state_dir / "controls").put(command)
            output_stream.write(f"queued: {command}\n")
            return 0
        if command == "status":
            return _status(config, output_stream, factory)
        if command == "doctor":
            return _doctor(config, output_stream, factory, environ)
        if command == "render-assets":
            render_assets(cast(Path, args.output))
            return 0
        if command == "run":
            return _run(config, factory, args)
    except UsageError:
        error_stream.write("invalid arguments\n")
        return 2
    except ValueError:
        error_stream.write("invalid configuration or state\n")
        return 2
    except AlreadyRunningError:
        error_stream.write(
            "BUSY Bar is already running for this state directory. "
            "Stop that instance (Ctrl+C in its terminal) before starting another.\n"
        )
        return 1
    except OSError as error:
        error_stream.write(f"operational failure: {type(error).__name__}\n")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
