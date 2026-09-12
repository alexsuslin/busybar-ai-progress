from datetime import UTC, datetime, timedelta
from pathlib import Path

from busybar_codex.dashboard import Dashboard, input_actions
from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.state import SessionReducer


def reducer() -> SessionReducer:
    result = SessionReducer(86400)
    for session, state in [("a", DisplayState.CODING), ("b", DisplayState.QUESTION)]:
        result.apply(SafeEvent(session, None, state, datetime.now(UTC).isoformat(), "prompt"))
    return result


def test_selection_preserves_identity_and_wraps() -> None:
    sessions = reducer()
    dashboard = Dashboard()
    selected = dashboard.select(sessions)
    assert selected is not None
    assert selected.session_id == "b"
    dashboard.move(1, sessions)
    selected = dashboard.select(sessions)
    assert selected is not None
    assert selected.session_id == "a"
    dashboard.move(-1, sessions)
    selected = dashboard.select(sessions)
    assert selected is not None
    assert selected.session_id == "b"
    del sessions.records["b"]
    selected = dashboard.select(sessions)
    assert selected is not None
    assert selected.session_id == "a"


def test_explicit_hide_survives_new_events_and_rotation() -> None:
    dashboard = Dashboard()
    dashboard.action("hide", reducer())
    dashboard.move(1, reducer())
    assert dashboard.hidden
    dashboard.action("show", reducer())
    assert not dashboard.hidden


def test_only_start_press_dismisses_and_encoder_delta_is_preserved() -> None:
    assert input_actions(
        {
            "updates": [
                {"input": {"button_event": {"button": "START", "action": "PRESS"}}},
                {"input": {"button_event": {"button": "START", "action": "RELEASE"}}},
                {"input": {"button_event": {"button": "OK", "action": "PRESS"}}},
                {"input": {"encoder_event": {"delta": -2}}},
            ]
        }
    ) == ["dismiss", -2]
    assert input_actions({"updates": [None, {"input": {"encoder_event": {"delta": True}}}]}) == []


def test_dial_follows_visible_numbers_instead_of_raw_ids() -> None:
    sessions = SessionReducer(86400)
    timestamp = datetime.now(UTC).isoformat()
    for session_id in ("z", "a", "m"):
        sessions.apply(SafeEvent(session_id, None, DisplayState.CODING, timestamp, "prompt"))
    dashboard = Dashboard()
    selected = dashboard.select(sessions)
    assert selected is not None and sessions.session_label(selected.session_id) == "#01"
    for expected in ("#02", "#03", "#01"):
        dashboard.move(1, sessions)
        selected = dashboard.select(sessions)
        assert selected is not None and sessions.session_label(selected.session_id) == expected


def test_new_session_replaces_old_done_and_question_gets_attention() -> None:
    sessions = SessionReducer(86400)
    now = datetime.now(UTC)
    sessions.apply(SafeEvent("old", None, DisplayState.DONE, now.isoformat(), "stop"))
    dashboard = Dashboard()
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "old"
    sessions.apply(
        SafeEvent(
            "new",
            None,
            DisplayState.REGISTER,
            (now + timedelta(seconds=1)).isoformat(),
            "session_start",
        )
    )
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "new"
    sessions.apply(
        SafeEvent(
            "old", None, DisplayState.CODING, (now + timedelta(seconds=1.5)).isoformat(), "prompt"
        )
    )
    sessions.apply(
        SafeEvent(
            "old",
            None,
            DisplayState.QUESTION,
            (now + timedelta(seconds=2)).isoformat(),
            "user_input",
        )
    )
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "old"


def test_manual_selection_is_held_then_returns_to_active_session() -> None:
    sessions = reducer()
    clock = [10.0]
    dashboard = Dashboard(clock=lambda: clock[0])
    dashboard.move(1, sessions)
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
    clock[0] += 29
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
    clock[0] += 2
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "b"


def test_dismiss_skips_selected_card_and_reopens_only_for_new_activity(tmp_path: Path) -> None:
    sessions = reducer()
    dashboard = Dashboard()
    dashboard.action("dismiss", sessions)
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
    dashboard.move(1, sessions)
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
    snapshot = tmp_path / "state.json"
    sessions.save(snapshot)
    sessions = SessionReducer.load(snapshot, 86400)
    dashboard = Dashboard()
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
    original = sessions.records["b"]
    sessions.apply(SafeEvent("b", None, original.state, original.timestamp, original.reason))
    sessions.apply(
        SafeEvent("b", None, DisplayState.REGISTER, datetime.now(UTC).isoformat(), "session_start")
    )
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
    sessions.apply(
        SafeEvent("b", None, DisplayState.QUESTION, datetime.now(UTC).isoformat(), "user_input")
    )
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "b"
    assert sessions.session_label("b") == "#02"


def test_dismiss_last_card_cannot_be_restored_with_dial_or_show() -> None:
    sessions = reducer()
    dashboard = Dashboard()
    dashboard.action("dismiss", sessions)
    dashboard.action("dismiss", sessions)
    assert dashboard.select(sessions) is None
    dashboard.action("show", sessions)
    dashboard.move(1, sessions)
    assert dashboard.select(sessions) is None
    assert len(sessions.records) == 2


def test_dismissed_running_card_returns_on_next_tool_completion() -> None:
    sessions = SessionReducer(86400)
    now = datetime.now(UTC)
    sessions.apply(SafeEvent("a", "t1", DisplayState.CODING, now.isoformat(), "prompt"))
    dashboard = Dashboard()
    dashboard.action("dismiss", sessions)
    assert dashboard.select(sessions) is None
    sessions.apply(
        SafeEvent(
            "a",
            "t1",
            DisplayState.CODING,
            (now + timedelta(seconds=1)).isoformat(),
            "tool_complete",
        )
    )
    assert (chosen := dashboard.select(sessions)) is not None and chosen.session_id == "a"
