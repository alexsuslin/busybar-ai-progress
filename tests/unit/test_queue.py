from pathlib import Path

from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.queue import EventQueue


def safe_event(session_id: str = "s1") -> SafeEvent:
    return SafeEvent(
        session_id=session_id,
        turn_id=None,
        state=DisplayState.CODING,
        timestamp="2026-09-11T00:00:00+00:00",
        reason="prompt",
    )


def test_put_commits_one_json_file_and_drain_removes_it(tmp_path: Path) -> None:
    queue = EventQueue(tmp_path)
    event = safe_event()

    committed = queue.put(event)

    assert committed.suffix == ".json"
    assert list(tmp_path.glob("*.tmp")) == []
    assert queue.drain() == [event]
    assert not committed.exists()


def test_drain_ignores_incomplete_temp_file(tmp_path: Path) -> None:
    queue = EventQueue(tmp_path)
    event = safe_event()
    queue.put(event)
    incomplete = tmp_path / "orphan.tmp"
    incomplete.write_text("partial", encoding="utf-8")

    assert queue.drain() == [event]
    assert incomplete.read_text(encoding="utf-8") == "partial"


def test_drain_quarantines_malformed_committed_file(tmp_path: Path) -> None:
    queue = EventQueue(tmp_path)
    malformed = tmp_path / "0001-bad.json"
    malformed.write_text("private malformed payload", encoding="utf-8")

    assert queue.drain() == []
    assert not malformed.exists()
    assert len(list((tmp_path / "rejected").glob("*.json"))) == 1


def test_drain_preserves_filename_order(tmp_path: Path) -> None:
    queue = EventQueue(tmp_path)
    first = safe_event("first")
    second = safe_event("second")
    (tmp_path / "0002.json").write_text(second.to_json(), encoding="utf-8")
    (tmp_path / "0001.json").write_text(first.to_json(), encoding="utf-8")

    assert queue.drain() == [first, second]
