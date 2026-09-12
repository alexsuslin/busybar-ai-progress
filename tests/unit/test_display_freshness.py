import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from busylib import types

from busybar_codex.dashboard import DisplayFrame, WorkActivity
from busybar_codex.events import DisplayState
from busybar_codex.local import MetadataStore
from busybar_codex.rendering import frame_elements
from busybar_codex.telemetry import CodexTelemetry, Telemetry, claude_telemetry


def test_claude_receipt_time_is_transient_and_only_for_usage(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path)
    store.write("a", claude_telemetry({"context_window": {"used_percentage": 0}}))
    path = next(tmp_path.glob("*.json"))
    stamp = datetime.now(UTC).timestamp() - 100
    os.utime(path, (stamp, stamp))
    data = store.read("a")
    assert data.usage_observed_at == pytest.approx(stamp)
    assert "usage_observed_at" not in data.to_json()
    assert Telemetry.from_json(data.to_json()).usage_observed_at is None
    store.write("a", claude_telemetry({"model": {"id": "claude-example"}}))
    assert store.read("a").usage_observed_at is None


@pytest.mark.parametrize("value", [True, -1, 10**400, float("nan"), float("inf"), "1000"])
def test_invalid_usage_timestamps_are_unknown(value: object) -> None:
    data = Telemetry(usage_observed_at=value)  # type: ignore[arg-type]
    assert data.usage_observed_at is None


def test_codex_uses_usage_record_time_not_file_activity(tmp_path: Path) -> None:
    path = tmp_path / "rollout-a.jsonl"
    timestamp = "2026-09-12T06:30:00Z"
    path.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": timestamp,
                "payload": {
                    "type": "token_count",
                    "info": {
                        "model_context_window": 1000,
                        "last_token_usage": {"total_tokens": 100},
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source = CodexTelemetry(tmp_path)
    expected = datetime(2026, 9, 12, 6, 30, tzinfo=UTC).timestamp()
    assert source.read("a").usage_observed_at == expected
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "turn_context",
                    "timestamp": "2026-09-12T07:00:00Z",
                    "payload": {"model": "gpt-example"},
                }
            )
            + "\n"
        )
    assert source.read("a").usage_observed_at == expected


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-09-12T06:30:00", True])
def test_codex_missing_or_invalid_timestamp_does_not_invent_freshness(
    tmp_path: Path, timestamp: object
) -> None:
    (tmp_path / "rollout-a.jsonl").write_text(
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": timestamp,
                "payload": {
                    "type": "token_count",
                    "info": {
                        "model_context_window": 1000,
                        "last_token_usage": {"total_tokens": 100},
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert CodexTelemetry(tmp_path).read("a").usage_observed_at is None


@pytest.mark.parametrize(
    "activity,color",
    [
        (WorkActivity.THINK, "#3FD8FFFF"),
        (WorkActivity.TOOL, "#2B7FFFFF"),
        (WorkActivity.CHECK, "#B58AFFFF"),
        (WorkActivity.COMPACT, "#79B8FFFF"),
    ],
)
def test_activity_accents_keep_text_and_question_precedence(
    activity: WorkActivity, color: str
) -> None:
    for state, expected in [
        (DisplayState.CODING, color),
        (DisplayState.QUESTION, "#FFB000FF"),
        (DisplayState.DONE, "#36D17CFF"),
    ]:
        elements = frame_elements(DisplayFrame(state, "#01", 1, 0, Telemetry(), activity=activity))
        for key in ("front-session", "back-state"):
            element = next(item for item in elements if item.id == key)
            assert isinstance(element, types.TextElement)
            assert element.color == expected


@pytest.mark.parametrize(
    "stamp,now,label",
    [
        (1000, 1050, "DATA <1m"),
        (1000, 1899, "DATA 14m"),
        (1000, 1900, "STALE 15m"),
        (1000, 8200, "STALE 2h"),
        (None, 1900, "AGE N/A"),
        (2000, 1900, "AGE N/A"),
    ],
)
def test_usage_age_is_explicit_and_stale_context_is_muted(
    stamp: float | None, now: float, label: str
) -> None:
    data = Telemetry(context_percent=85, usage_observed_at=stamp)
    elements = frame_elements(DisplayFrame(DisplayState.CODING, "#01", 1, 0, data, now=now))
    age = next(item for item in elements if item.id == "back-freshness")
    assert isinstance(age, types.TextElement) and age.text == label
    if label.startswith("STALE"):
        for key in ("front-context-fill", "back-context-fill"):
            fill = next(item for item in elements if item.id == key)
            assert isinstance(fill, types.RectangleElement) and fill.fill_colors == ["#777777FF"]


def test_reset_rows_use_actual_windows_and_expired_usage_disappears() -> None:
    from busybar_codex.telemetry import RateWindow

    data = Telemetry(
        limits=(RateWindow(95, 60, 4660), RateWindow(40, 2880, 173800)), usage_observed_at=1000
    )
    elements = frame_elements(DisplayFrame(DisplayState.QUESTION, "#01", 1, 1, data, now=1000))
    rows = [
        item
        for item in elements
        if isinstance(item, types.TextElement) and item.id in {"back-limits", "back-limit-1"}
    ]
    assert [item.text for item in rows] == ["1h USED 95%  RESET 1h 1m", "2d USED 40%  RESET 2d"]
    assert rows[0].color == "#FF6262FF"
    later = frame_elements(DisplayFrame(DisplayState.QUESTION, "#01", 1, 1, data, now=173800))
    assert {(item.id, type(item), item.display) for item in later} == {
        (item.id, type(item), item.display) for item in elements
    }
    assert (
        next(
            item
            for item in later
            if isinstance(item, types.TextElement) and item.id == "back-limits"
        ).text
        == "LIMITS N/A"
    )
    assert (
        next(
            item
            for item in later
            if isinstance(item, types.TextElement) and item.id == "back-limit-1"
        ).text
        == ""
    )


@pytest.mark.parametrize("minutes,label", [(1500, "25h"), (1501, "1501m"), (90, "90m")])
def test_rate_window_duration_is_exact(minutes: int, label: str) -> None:
    from busybar_codex.telemetry import RateWindow

    data = Telemetry(limits=(RateWindow(50, minutes),))
    elements = frame_elements(DisplayFrame(DisplayState.CODING, "#01", 1, 0, data, now=1000))
    row = next(item for item in elements if item.id == "back-limits")
    assert isinstance(row, types.TextElement) and row.text.startswith(f"{label} USED")
