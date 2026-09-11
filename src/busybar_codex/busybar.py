from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, Protocol, cast
from urllib.parse import urlsplit

from busylib import BusyBar, converter, exceptions, types

from . import __version__
from .assets import bundled_asset
from .config import Config
from .events import DisplayState

AssetProvider = Callable[[DisplayState], Path]
RENDERABLE_STATES = (DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE)


class DisplayBusyError(RuntimeError):
    """Another BUSY Bar application currently owns the display."""


class DisplayUnavailableError(RuntimeError):
    """The BUSY Bar API cannot currently accept requests."""


class BusyBarClient(Protocol):
    def version(self) -> types.VersionInfo: ...

    def assets_upload(self, application_name: str, filename: str, data: bytes) -> object: ...

    def display_draw(self, display_data: types.DisplayElements) -> object: ...


def _redacted_address(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or "device"
    port = f":{parsed.port}" if parsed.port is not None else ""
    scheme = parsed.scheme or "http"
    return f"{scheme}://{hostname}{port}"


def _translate_error(error: exceptions.BusyBarError) -> NoReturn:
    if isinstance(error, exceptions.BusyBarAPIError) and error.status_code == 409:
        raise DisplayBusyError("display is owned by a higher-priority application") from error
    raise DisplayUnavailableError(type(error).__name__) from error


class BusyBarDisplay:
    """Upload and render status artwork through the official BUSY Bar client."""

    def __init__(
        self,
        client: BusyBarClient,
        application_name: str,
        priority: int,
        cache_dir: Path,
        device_key: str,
        asset_provider: AssetProvider = bundled_asset,
    ) -> None:
        self.client = client
        self.application_name = application_name
        self.priority = priority
        self.cache_dir = cache_dir
        self.device_key = _redacted_address(device_key)
        self.asset_provider = asset_provider
        self._asset_names: dict[DisplayState, str] = {}

    @classmethod
    def from_config(cls, config: Config) -> BusyBarDisplay:
        client = BusyBar(
            config.base_url,
            token=config.token,
            timeout=config.request_timeout_seconds,
            max_retries=0,
            compatibility_mode="warn",
        )
        return cls(
            client=cast(BusyBarClient, client),
            application_name=config.application_name,
            priority=config.priority,
            cache_dir=config.cache_dir,
            device_key=config.base_url,
        )

    def probe(self) -> str:
        try:
            version = self.client.version()
        except exceptions.BusyBarError as error:
            _translate_error(error)
        return version.api_semver or version.version or "unknown"

    def ensure_assets(self) -> None:
        assets = {state: self.asset_provider(state) for state in RENDERABLE_STATES}
        names = {state: path.name for state, path in assets.items()}
        receipt = {
            "application_name": self.application_name,
            "assets": {state.value: _sha256(path) for state, path in assets.items()},
            "device": self.device_key,
            "device_api_version": self.probe(),
            "package_version": __version__,
        }
        receipt_path = self.cache_dir / "upload-receipt.json"
        if _read_receipt(receipt_path) == receipt:
            self._asset_names = names
            return

        try:
            for state in RENDERABLE_STATES:
                path = assets[state]
                converted_name, payload = converter.convert_for_storage(
                    str(path), path.read_bytes()
                )
                safe_name = Path(converted_name).name
                self.client.assets_upload(self.application_name, safe_name, payload)
                names[state] = safe_name
        except exceptions.BusyBarError as error:
            _translate_error(error)

        _write_receipt(receipt_path, receipt)
        self._asset_names = names

    def render(self, state: DisplayState) -> None:
        if state not in RENDERABLE_STATES:
            raise ValueError(f"state is not renderable: {state}")
        if not self._asset_names:
            self.ensure_assets()
        element = types.ImageElement(
            id="codex-state",
            x=0,
            y=0,
            display=types.DisplayName.FRONT,
            path=self._asset_names[state],
        )
        payload = types.DisplayElements(
            application_name=self.application_name,
            priority=self.priority,
            elements=[element],
        )
        try:
            self.client.display_draw(payload)
        except exceptions.BusyBarError as error:
            _translate_error(error)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_receipt(path: Path) -> object | None:
    try:
        return cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def _write_receipt(path: Path, receipt: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(receipt, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
