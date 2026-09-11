from pathlib import Path


def test_emulator_server_is_started_from_repository_root() -> None:
    script = Path("scripts/emulator.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $emulatorRoot "server.js"' in script
    assert "Push-Location $emulatorRoot" in script
