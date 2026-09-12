from datetime import UTC, datetime, timedelta
from pathlib import Path

from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.state import SessionReducer

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def event(
    session_id: str,
    state: DisplayState,
    *,
    age_seconds: int = 0,
    reason: str = "prompt",
    turn_id: str | None = None,
) -> SafeEvent:
    return SafeEvent(
        session_id=session_id,
        turn_id=turn_id,
        state=state,
        timestamp=(NOW - timedelta(seconds=age_seconds)).isoformat(),
        reason=reason,
    )


def test_question_wins_across_sessions() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("coding", DisplayState.CODING))
    reducer.apply(event("waiting", DisplayState.QUESTION))

    assert reducer.aggregate(NOW) is DisplayState.QUESTION


def test_coding_wins_when_other_sessions_are_done() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("finished", DisplayState.DONE))
    reducer.apply(event("active", DisplayState.CODING))

    assert reducer.aggregate(NOW) is DisplayState.CODING


def test_done_is_default_and_only_finished_state() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    assert reducer.aggregate(NOW) is DisplayState.DONE

    reducer.apply(event("finished", DisplayState.DONE))
    assert reducer.aggregate(NOW) is DisplayState.DONE


def test_post_tool_resumes_only_a_question_session() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("waiting", DisplayState.QUESTION))
    reducer.apply(event("waiting", DisplayState.CODING, reason="tool_complete"))
    reducer.apply(event("finished", DisplayState.DONE))
    reducer.apply(event("finished", DisplayState.CODING, reason="tool_complete"))

    assert reducer.records["waiting"].state is DisplayState.CODING
    assert reducer.records["finished"].state is DisplayState.DONE


def test_session_start_registers_without_overriding_existing_state() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("new", DisplayState.REGISTER, reason="session_start"))
    reducer.apply(event("active", DisplayState.CODING))
    reducer.apply(event("active", DisplayState.REGISTER, reason="session_start"))

    assert reducer.records["new"].state is DisplayState.DONE
    assert reducer.records["active"].state is DisplayState.CODING


def test_session_end_removes_record() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("s1", DisplayState.CODING))

    reducer.apply(event("s1", DisplayState.REMOVE, reason="session_end"))

    assert "s1" not in reducer.records
    assert reducer.aggregate(NOW) is DisplayState.DONE


def test_stale_active_session_is_pruned() -> None:
    reducer = SessionReducer(stale_after_seconds=60)
    reducer.apply(event("old", DisplayState.CODING, age_seconds=61))

    assert reducer.aggregate(NOW) is DisplayState.DONE
    assert "old" not in reducer.records


def test_older_event_does_not_replace_newer_state() -> None:
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("s1", DisplayState.QUESTION, age_seconds=1))

    reducer.apply(event("s1", DisplayState.CODING, age_seconds=2))

    assert reducer.records["s1"].state is DisplayState.QUESTION


def test_snapshot_round_trip_preserves_safe_records(tmp_path: Path) -> None:
    snapshot = tmp_path / "state.json"
    reducer = SessionReducer(stale_after_seconds=86_400)
    reducer.apply(event("s1", DisplayState.QUESTION, turn_id="t1"))

    reducer.save(snapshot)
    restored = SessionReducer.load(snapshot, stale_after_seconds=86_400)

    assert restored.records == reducer.records
    assert list(tmp_path.glob("*.tmp")) == []


def test_missing_snapshot_loads_empty(tmp_path: Path) -> None:
    restored = SessionReducer.load(tmp_path / "missing.json", stale_after_seconds=86_400)

    assert restored.records == {}


def test_session_numbers_survive_updates_removal_and_restart(tmp_path: Path) -> None:
    reducer = SessionReducer(86400)
    reducer.apply(event("z", DisplayState.CODING))
    reducer.apply(event("a", DisplayState.QUESTION))
    assert reducer.session_label("z") == "#01"
    assert reducer.session_label("a") == "#02"
    reducer.apply(event("z", DisplayState.DONE))
    assert reducer.session_label("z") == "#01"
    reducer.apply(event("z", DisplayState.REMOVE))
    snapshot = tmp_path / "state.json"
    reducer.save(snapshot)
    restored = SessionReducer.load(snapshot, 86400)
    assert restored.session_label("a") == "#02"
    restored.apply(event("new", DisplayState.CODING))
    assert restored.session_label("new") == "#03"


def test_old_snapshot_receives_stable_readable_numbers(tmp_path: Path) -> None:
    import json
    from dataclasses import asdict

    snapshot = tmp_path / "state.json"
    snapshot.write_text(
        json.dumps(
            {
                "version": 1,
                "records": [
                    asdict(event("a", DisplayState.DONE)),
                    asdict(event("b", DisplayState.CODING)),
                ],
            }
        )
    )
    restored = SessionReducer.load(snapshot, 86400)
    assert restored.session_label("a") == "#01"
    assert restored.session_label("b") == "#02"


def test_invalid_number_snapshot_is_rejected(tmp_path: Path) -> None:
    import json

    import pytest

    snapshot = tmp_path / "state.json"
    reducer = SessionReducer(86400)
    reducer.apply(event("a", DisplayState.DONE))
    reducer.apply(event("b", DisplayState.DONE))
    reducer.save(snapshot)
    original = json.loads(snapshot.read_text())
    for numbers, counter in [
        ({"a": True, "b": 2}, 3),
        ({"a": 1, "b": 1}, 3),
        ({"a": 1, "b": 2}, 2),
        ({"a": 1}, 3),
    ]:
        snapshot.write_text(
            json.dumps({**original, "session_numbers": numbers, "next_session_number": counter})
        )
        with pytest.raises(ValueError):
            SessionReducer.load(snapshot, 86400)


def test_number_counter_survives_empty_snapshot(tmp_path: Path) -> None:
    reducer = SessionReducer(60)
    reducer.apply(event("old", DisplayState.CODING, age_seconds=61))
    reducer.aggregate(NOW)
    snapshot = tmp_path / "state.json"
    reducer.save(snapshot)
    restored = SessionReducer.load(snapshot, 60)
    restored.apply(event("new", DisplayState.CODING))
    assert restored.session_label("new") == "#02"


def test_late_tool_completion_does_not_resume_final_question() -> None:
    reducer = SessionReducer(86400)
    reducer.apply(event("s1", DisplayState.QUESTION, reason="final_question", age_seconds=1))
    reducer.apply(event("s1", DisplayState.CODING, reason="tool_complete"))
    assert reducer.records["s1"].state is DisplayState.QUESTION


def test_other_turn_tool_completion_does_not_resume_question() -> None:
    reducer = SessionReducer(86400)
    reducer.apply(event("s1", DisplayState.QUESTION, reason="user_input", turn_id="new"))
    reducer.apply(event("s1", DisplayState.CODING, reason="tool_complete", turn_id="old"))
    assert reducer.records["s1"].state is DisplayState.QUESTION


def test_invalid_dismissal_snapshot_is_rejected(tmp_path: Path) -> None:
    import json

    import pytest

    snapshot = tmp_path / "state.json"
    reducer = SessionReducer(86400)
    reducer.apply(event("a", DisplayState.DONE))
    reducer.save(snapshot)
    original = json.loads(snapshot.read_text())
    invalid_dismissals: list[object] = [
        [],
        {"missing": NOW.isoformat()},
        {"a": True},
        {"a": "2026-09-11T12:00:00"},
        {"a": "invalid"},
    ]
    for dismissed in invalid_dismissals:
        snapshot.write_text(json.dumps({**original, "dismissed": dismissed}))
        with pytest.raises(ValueError):
            SessionReducer.load(snapshot, 86400)
