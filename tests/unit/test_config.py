from pathlib import Path

import pytest

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
        environ={
            "BUSYBAR_CODEX_ADDRESS": "127.0.0.1:8321",
            "BUSYBAR_CODEX_PRIORITY": "60",
        },
    )

    assert config.base_url == "http://127.0.0.1:8321"
    assert config.priority == 60


@pytest.mark.parametrize("priority", ["0", "101"])
def test_priority_must_be_in_device_range(tmp_path: Path, priority: str) -> None:
    with pytest.raises(ValueError, match="priority must be between 1 and 100"):
        Config.load(
            path=tmp_path / "missing.toml",
            environ={"BUSYBAR_CODEX_PRIORITY": priority},
        )


def test_environment_can_supply_private_token(tmp_path: Path) -> None:
    config = Config.load(
        path=tmp_path / "missing.toml",
        environ={"BUSYBAR_CODEX_TOKEN": "private-token"},
    )

    assert config.token == "private-token"
