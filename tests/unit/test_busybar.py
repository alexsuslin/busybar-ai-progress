from collections.abc import Callable
from pathlib import Path

import pytest
from busylib import exceptions, types

from busybar_codex.assets import render_assets
from busybar_codex.busybar import BusyBarDisplay, DisplayBusyError, DisplayUnavailableError
from busybar_codex.events import DisplayState


class FakeClient:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes]] = []
        self.draws: list[types.DisplayElements] = []
        self.version_calls = 0

    def version(self) -> types.VersionInfo:
        self.version_calls += 1
        return types.VersionInfo(api_semver="25.0.0", version="1.0.0")

    def assets_upload(self, application_name: str, filename: str, data: bytes) -> object:
        self.uploads.append((application_name, filename, data))
        return object()

    def display_draw(self, display_data: types.DisplayElements) -> object:
        self.draws.append(display_data)
        return object()


def provider(tmp_path: Path) -> Callable[[DisplayState], Path]:
    assets = render_assets(tmp_path / "assets")
    return assets.__getitem__


def display(tmp_path: Path, client: FakeClient) -> BusyBarDisplay:
    return BusyBarDisplay(
        client=client,
        application_name="codex-status",
        priority=50,
        cache_dir=tmp_path / "cache",
        device_key="http://127.0.0.1:8080",
        asset_provider=provider(tmp_path),
    )


def test_probe_prefers_device_api_semver(tmp_path: Path) -> None:
    client = FakeClient()

    assert display(tmp_path, client).probe() == "25.0.0"


def test_ensure_assets_uploads_safe_filenames_once(tmp_path: Path) -> None:
    client = FakeClient()
    adapter = display(tmp_path, client)

    adapter.ensure_assets()
    adapter.ensure_assets()

    assert [(app, name) for app, name, _data in client.uploads] == [
        ("codex-status", "coding.png"),
        ("codex-status", "question.png"),
        ("codex-status", "done.png"),
    ]
    assert len(list((tmp_path / "cache").glob("*.tmp"))) == 0


def test_matching_upload_receipt_skips_upload_after_restart(tmp_path: Path) -> None:
    first_client = FakeClient()
    display(tmp_path, first_client).ensure_assets()
    second_client = FakeClient()

    display(tmp_path, second_client).ensure_assets()

    assert len(first_client.uploads) == 3
    assert second_client.uploads == []


def test_render_uses_owned_front_image_element(tmp_path: Path) -> None:
    client = FakeClient()
    adapter = display(tmp_path, client)

    adapter.render(DisplayState.DONE)

    assert len(client.draws) == 1
    payload = client.draws[0]
    assert payload.application_name == "codex-status"
    assert payload.priority == 50
    assert len(payload.elements) == 1
    element = payload.elements[0]
    assert isinstance(element, types.ImageElement)
    assert element.id == "codex-state"
    assert element.display is types.DisplayName.FRONT
    assert element.path == "done.png"


def test_http_409_is_screen_busy_not_unavailable(tmp_path: Path) -> None:
    class ConflictClient(FakeClient):
        def display_draw(self, display_data: types.DisplayElements) -> object:
            raise exceptions.BusyBarAPIError("priority conflict", status_code=409)

    with pytest.raises(DisplayBusyError):
        display(tmp_path, ConflictClient()).render(DisplayState.CODING)


def test_transport_error_is_unavailable(tmp_path: Path) -> None:
    class OfflineClient(FakeClient):
        def version(self) -> types.VersionInfo:
            raise exceptions.BusyBarRequestError("offline")

    with pytest.raises(DisplayUnavailableError, match="BusyBarRequestError"):
        display(tmp_path, OfflineClient()).probe()


def test_control_state_cannot_be_rendered(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not renderable"):
        display(tmp_path, FakeClient()).render(DisplayState.REGISTER)
