from __future__ import annotations

import math
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "busybar-codex-status"
DIRS = PlatformDirs(APP_NAME, "alexsuslin")


def _normalize_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("address must not be empty")
    return normalized if "://" in normalized else f"http://{normalized}"


def _raw_text(raw: Mapping[str, object], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved application settings."""

    base_url: str = "http://10.0.4.20"
    application_name: str = "codex-status"
    token: str | None = None
    priority: int = 50
    stale_after_seconds: int = 86_400
    poll_interval_seconds: float = 0.2
    request_timeout_seconds: float = 2.0
    log_level: str = "INFO"
    animations: bool = True
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
        """Load a TOML file and apply environment overrides."""

        env = os.environ if environ is None else environ
        config_dir = Path(env.get("BUSYBAR_CODEX_CONFIG_DIR", DIRS.user_config_dir))
        state_dir = Path(env.get("BUSYBAR_CODEX_STATE_DIR", DIRS.user_state_dir))
        cache_dir = Path(env.get("BUSYBAR_CODEX_CACHE_DIR", DIRS.user_cache_dir))
        log_dir = Path(env.get("BUSYBAR_CODEX_LOG_DIR", DIRS.user_log_dir))
        config_path = path or config_dir / "config.toml"
        raw: dict[str, object] = (
            tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        )

        address = env.get("BUSYBAR_CODEX_ADDRESS", _raw_text(raw, "address", "10.0.4.20"))
        application_name = env.get(
            "BUSYBAR_CODEX_APPLICATION_NAME",
            _raw_text(raw, "application_name", "codex-status"),
        ).strip()
        raw_token = raw.get("token")
        if raw_token is not None and not isinstance(raw_token, str):
            raise ValueError("token must be a string")
        token = env.get("BUSYBAR_CODEX_TOKEN", raw_token)
        priority = int(env.get("BUSYBAR_CODEX_PRIORITY", str(raw.get("priority", 50))))
        stale_after_seconds = int(
            env.get(
                "BUSYBAR_CODEX_STALE_AFTER_SECONDS",
                str(raw.get("stale_after_seconds", 86_400)),
            )
        )
        poll_interval_seconds = float(
            env.get(
                "BUSYBAR_CODEX_POLL_INTERVAL_SECONDS",
                str(raw.get("poll_interval_seconds", 0.2)),
            )
        )
        request_timeout_seconds = float(
            env.get(
                "BUSYBAR_CODEX_REQUEST_TIMEOUT_SECONDS",
                str(raw.get("request_timeout_seconds", 2.0)),
            )
        )
        log_level = env.get(
            "BUSYBAR_CODEX_LOG_LEVEL",
            _raw_text(raw, "log_level", "INFO"),
        ).upper()

        animation_value = env.get("BUSYBAR_CODEX_ANIMATIONS", raw.get("animations", True))
        if "BUSYBAR_CODEX_ANIMATIONS" in env:
            if not isinstance(animation_value, str) or animation_value.lower() not in {
                "0",
                "1",
                "false",
                "true",
            }:
                raise ValueError("animations must be true/false or 1/0")
            animations = animation_value.lower() in {"1", "true"}
        elif type(animation_value) is bool:
            animations = animation_value
        else:
            raise ValueError("animations must be a boolean")

        if not 1 <= priority <= 100:
            raise ValueError("priority must be between 1 and 100")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if not math.isfinite(request_timeout_seconds) or request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if not application_name:
            raise ValueError("application_name must not be empty")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid log_level")

        return cls(
            base_url=_normalize_url(address),
            application_name=application_name,
            token=token,
            priority=priority,
            stale_after_seconds=stale_after_seconds,
            poll_interval_seconds=poll_interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
            log_level=log_level,
            animations=animations,
            config_dir=config_dir,
            state_dir=state_dir,
            cache_dir=cache_dir,
            log_dir=log_dir,
        )
