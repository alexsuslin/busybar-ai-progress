import json
from pathlib import Path

import pytest

from busybar_codex.telemetry import CodexTelemetry, Telemetry, claude_telemetry


def test_claude_uses_live_fields_and_discards_private_content() -> None:
    data = claude_telemetry(
        {
            "model": {"id": "claude-sonnet-4-6"},
            "effort": {"level": "high"},
            "context_window": {"context_window_size": 1000000, "used_percentage": 25},
            "rate_limits": {"five_hour": {"used_percentage": 0, "resets_at": 2000000000}},
            "prompt": "PRIVATE",
            "transcript_path": "PRIVATE",
        }
    )
    assert data.provider == "anthropic"
    assert data.model == "claude-sonnet-4-6"
    assert data.effort == "high"
    assert data.context_percent == 25
    assert data.limits[0].used_percent == 0
    assert data.limits[0].window_minutes == 300
    assert "PRIVATE" not in data.to_json()
    assert Telemetry.from_json(data.to_json()) == data


@pytest.mark.parametrize("value", [None, -1, 101, True, float("nan"), "25"])
def test_invalid_percentage_is_unknown(value: object) -> None:
    assert claude_telemetry({"context_window": {"used_percentage": value}}).context_percent is None


def test_absent_claude_fields_are_unknown_not_defaults() -> None:
    data = claude_telemetry({})
    assert data.model is None
    assert data.effort is None
    assert data.context_percent is None
    assert data.limits == ()


def test_codex_uses_last_usage_and_session_specific_window(tmp_path: Path) -> None:
    path = tmp_path / "rollout-2026-a.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "a"}},
        {"type": "turn_context", "payload": {"model": "gpt-5.4", "effort": "xhigh"}},
        {"type": "response_item", "payload": {"content": "PRIVATE"}},
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "model_context_window": 200000,
                    "last_token_usage": {"total_tokens": 50000},
                    "total_token_usage": {"total_tokens": 900000},
                },
                "rate_limits": {
                    "primary": {"used_percent": 12, "window_minutes": 60, "resets_at": 2000000000}
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    source = CodexTelemetry(tmp_path)
    data = source.read("a")
    assert data.model == "gpt-5.4"
    assert data.provider == "openai"
    assert data.effort == "xhigh"
    assert data.context_percent == 25
    assert data.context_size == 200000
    assert data.limits[0].window_minutes == 60
    assert source.read("b").model is None
    assert "PRIVATE" not in data.to_json()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "low"}})
            + "\n"
        )
    changed = source.read("a")
    assert changed.model == "gpt-5.5"
    assert changed.context_percent is None


def test_codex_ignores_partial_lines_and_unsafe_session_paths(tmp_path: Path) -> None:
    (tmp_path / "rollout-a.jsonl").write_text('{"type":', encoding="utf-8")
    source = CodexTelemetry(tmp_path)
    assert source.read("a").model is None
    assert source.read("../auth").model is None


def test_expired_limits_are_not_presented_as_current() -> None:
    data = claude_telemetry(
        {
            "rate_limits": {
                "five_hour": {"used_percentage": 99, "resets_at": 100},
                "seven_day": {"used_percentage": 20, "resets_at": 200},
            }
        }
    )
    assert [limit.window_minutes for limit in data.current_limits(150)] == [10080]


def test_huge_integer_percentage_is_unknown() -> None:
    assert (
        claude_telemetry({"context_window": {"used_percentage": 10**400}}).context_percent is None
    )


def test_gap_cannot_attribute_recent_usage_to_old_model(tmp_path: Path) -> None:
    path = tmp_path / "rollout-a.jsonl"
    old = json.dumps({"type": "turn_context", "payload": {"model": "gpt-old", "effort": "low"}})
    new = json.dumps({"type": "turn_context", "payload": {"model": "gpt-new", "effort": "high"}})
    padding = json.dumps({"type": "response_item", "payload": {"content": "x" * 10000}}) + "\n"
    path.write_text(old + "\n" + padding * 20 + new + "\n" + padding * 200, encoding="utf-8")
    value = CodexTelemetry(tmp_path).read("a")
    assert value.model is None
    assert value.effort is None


def lifecycle_row(kind: str, timestamp: str, turn: str = "turn-1") -> str:
    return (
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": timestamp,
                "payload": {"type": kind, "turn_id": turn, "last_agent_message": "PRIVATE"},
            }
        )
        + "\n"
    )


def test_codex_lifecycle_recovers_completion_without_stop_hook(tmp_path: Path) -> None:
    from busybar_codex.events import DisplayState

    path = tmp_path / "rollout-a.jsonl"
    path.write_text(
        lifecycle_row("task_started", "2026-09-12T06:30:00Z")
        + lifecycle_row("task_complete", "2026-09-12T06:46:00Z")
    )
    source = CodexTelemetry(tmp_path)
    events = source.read_lifecycle("a")
    event = events[-1] if events else None
    assert event is not None and event.state is DisplayState.DONE
    assert event.reason == "rollout_complete"
    assert event.turn_id == "turn-1"
    assert "PRIVATE" not in event.to_json()
    with path.open("a") as stream:
        stream.write(lifecycle_row("task_started", "2026-09-12T06:48:00Z", "turn-2"))
    events = source.read_lifecycle("a")
    event = events[-1] if events else None
    assert event is not None and event.state is DisplayState.CODING
    assert event.turn_id == "turn-2"


def test_codex_lifecycle_ignores_incomplete_line_then_reads_it_and_handles_truncation(
    tmp_path: Path,
) -> None:
    from busybar_codex.events import DisplayState

    path = tmp_path / "rollout-a.jsonl"
    started = lifecycle_row("task_started", "2026-09-12T06:30:00Z")
    path.write_text(started + lifecycle_row("task_complete", "2026-09-12T06:46:00Z").rstrip())
    source = CodexTelemetry(tmp_path)
    assert (event := next(iter(reversed(source.read_lifecycle("a"))), None)) is not None
    assert event.state is DisplayState.CODING
    with path.open("a") as stream:
        stream.write("\n")
    assert (event := next(iter(reversed(source.read_lifecycle("a"))), None)) is not None
    assert event.state is DisplayState.DONE
    path.write_text('{"type":')
    assert source.read_lifecycle("a") == ()
    assert source.read_lifecycle("../auth") == ()
    assert source.read_lifecycle("missing") == ()


def test_codex_lifecycle_does_not_reuse_old_terminal_across_gap_or_other_turn(
    tmp_path: Path,
) -> None:
    from busybar_codex.events import DisplayState

    path = tmp_path / "rollout-a.jsonl"
    path.write_text(
        lifecycle_row("task_complete", "2026-09-12T06:30:00Z")
        + (json.dumps({"type": "response_item", "payload": "x" * 10000}) + "\n") * 220
    )
    source = CodexTelemetry(tmp_path)
    assert source.read_lifecycle("a") == ()
    path.write_text(
        lifecycle_row("task_started", "2026-09-12T06:48:00Z", "turn-2")
        + lifecycle_row("task_complete", "2026-09-12T06:49:00Z", "turn-1")
    )
    events = source.read_lifecycle("a")
    event = events[-1] if events else None
    assert event is not None and event.state is DisplayState.CODING
    assert event.turn_id == "turn-2"


@pytest.mark.parametrize(
    "timestamp,turn",
    [
        ("invalid", "t"),
        ("9999-01-01T00:00:00Z", "t"),
        ("2026-09-12T00:00:00", "t"),
        (True, "t"),
        ("2026-09-12T00:00:00Z", "x" * 129),
        ("2026-09-12T00:00:00Z", True),
    ],
)
def test_codex_lifecycle_rejects_invalid_fields(
    tmp_path: Path, timestamp: object, turn: object
) -> None:
    (tmp_path / "rollout-a.jsonl").write_text(
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": timestamp,
                "payload": {"type": "task_complete", "turn_id": turn},
            }
        )
        + "\n"
    )
    assert CodexTelemetry(tmp_path).read_lifecycle("a") == ()


def test_malformed_new_start_cannot_leave_previous_completion_current(tmp_path: Path) -> None:
    (tmp_path / "rollout-a.jsonl").write_text(
        lifecycle_row("task_complete", "2026-09-12T06:30:00Z")
        + json.dumps(
            {
                "type": "event_msg",
                "timestamp": "invalid",
                "payload": {"type": "task_started", "turn_id": "t2"},
            }
        )
        + "\n"
    )
    assert CodexTelemetry(tmp_path).read_lifecycle("a") == ()


def test_codex_interruption_is_terminal(tmp_path: Path) -> None:
    from busybar_codex.events import DisplayState

    (tmp_path / "rollout-a.jsonl").write_text(
        lifecycle_row("task_started", "2026-09-12T06:30:00Z")
        + lifecycle_row("turn_aborted", "2026-09-12T06:31:00Z")
    )
    event = CodexTelemetry(tmp_path).read_lifecycle("a")[-1]
    assert event.state is DisplayState.DONE
    assert event.reason == "rollout_interrupted"


def test_future_marker_does_not_mask_later_valid_completion(tmp_path: Path) -> None:
    (tmp_path / "rollout-a.jsonl").write_text(
        lifecycle_row("task_started", "2026-09-12T06:30:00Z")
        + lifecycle_row("task_complete", "9999-01-01T00:00:00Z")
        + lifecycle_row("task_complete", "2026-09-12T06:31:00Z")
    )
    event = CodexTelemetry(tmp_path).read_lifecycle("a")[-1]
    assert event.timestamp == "2026-09-12T06:31:00+00:00"


def test_telemetry_effort_capabilities_round_trip_and_old_records() -> None:
    value = Telemetry.from_json(
        '{"model":"gpt-example","effort":"high",'
        '"effort_levels":["low","medium","high","xhigh","ultra"]}'
    )
    assert value.effort_levels == ("low", "medium", "high", "xhigh", "ultra")
    assert Telemetry.from_json(value.to_json()) == value
    assert Telemetry.from_json('{"effort":"high"}').effort_levels == ()


@pytest.mark.parametrize(
    "levels",
    [
        None,
        True,
        "low",
        ["low", True],
        ["low", "unknown"],
        ["low", "low"],
        ["high", "low"],
        ["low"] * 9,
        [["low"]],
        ["LOW"],
        [" low"],
        ["low"],
    ],
)
def test_invalid_or_mismatched_effort_capabilities_are_unknown(levels: object) -> None:
    value = Telemetry.from_json(json.dumps({"effort": "high", "effort_levels": levels}))
    assert value.effort_levels == ()


def write_model_catalog(path: Path, models: object) -> None:
    path.write_text(json.dumps({"models": models}), encoding="utf-8")


def model_capability(slug: str, efforts: tuple[str, ...]) -> dict[str, object]:
    return {
        "slug": slug,
        "base_instructions": "PRIVATE",
        "supported_reasoning_levels": [
            {"effort": effort, "description": "PRIVATE"} for effort in efforts
        ],
    }


def write_effort_rollout(path: Path, model: str, effort: str = "high") -> None:
    path.write_text(
        json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort}}) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "levels",
    [
        ("low", "medium", "high", "xhigh", "ultra"),
        ("low", "medium", "high", "xhigh", "max", "ultra"),
    ],
)
def test_codex_effort_capabilities_use_exact_current_model(
    tmp_path: Path, levels: tuple[str, ...]
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    rollout = sessions / "rollout-a.jsonl"
    write_effort_rollout(rollout, "gpt-6-astra")
    write_model_catalog(tmp_path / "models_cache.json", [model_capability("gpt-6-astra", levels)])
    source = CodexTelemetry(sessions)
    value = source.read("a")
    assert value.effort_levels == levels
    assert value.effort_levels.index("high") == 2
    assert "PRIVATE" not in value.to_json()
    write_effort_rollout(rollout, "openai/gpt-6-astra")
    assert source.read("a").effort_levels == ()
    write_effort_rollout(rollout, "gpt-6-astra", "none")
    assert source.read("a").effort_levels == ()


def test_catalog_replacement_truncation_and_removal_invalidate_levels(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    write_effort_rollout(sessions / "rollout-a.jsonl", "gpt-example")
    catalog = tmp_path / "models_cache.json"
    source = CodexTelemetry(sessions)
    assert source.read("a").effort_levels == ()
    write_model_catalog(catalog, [model_capability("gpt-example", ("low", "high"))])
    assert source.read("a").effort_levels == ("low", "high")
    replacement = tmp_path / "replacement.json"
    write_model_catalog(replacement, [model_capability("gpt-example", ("medium", "high"))])
    replacement.replace(catalog)
    assert source.read("a").effort_levels == ("medium", "high")
    catalog.write_text('{"models":', encoding="utf-8")
    assert source.read("a").effort_levels == ()
    write_model_catalog(catalog, [model_capability("gpt-example", ("low", "high"))])
    assert source.read("a").effort_levels == ("low", "high")
    catalog.unlink()
    assert source.read("a").effort_levels == ()


@pytest.mark.parametrize(
    "models",
    [
        None,
        True,
        {},
        [{}],
        [{"slug": "gpt-example", "supported_reasoning_levels": True}],
        [{"slug": "gpt-example", "supported_reasoning_levels": [{"effort": True}]}],
        [model_capability("gpt-example", ("high", "low"))],
        [model_capability("gpt-example", ("low", "high", "high"))],
        [model_capability("gpt-example", ("high", "new"))],
        [model_capability("gpt-example", ("high",))] * 2,
        [model_capability("gpt-example", ("high",))]
        + [model_capability(f"gpt-{index}", ("high",)) for index in range(256)],
    ],
)
def test_invalid_catalog_capabilities_fail_safe(tmp_path: Path, models: object) -> None:
    write_effort_rollout(tmp_path / "rollout-a.jsonl", "gpt-example")
    catalog = tmp_path / "catalog.json"
    write_model_catalog(catalog, models)
    assert CodexTelemetry(tmp_path, catalog_path=catalog).read("a").effort_levels == ()


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps(
            {
                "models": [model_capability("gpt-example", ("high",))],
                "unused": " " * (2 * 1024 * 1024),
            }
        ).encode(),
        b"[" * 2000 + b"]" * 2000,
        b'{"models":' + b"9" * 5000 + b"}",
        b"\xff",
    ],
    ids=["oversize", "nested", "huge_integer", "invalid_utf8"],
)
def test_oversize_nested_and_malformed_catalog_is_unknown(tmp_path: Path, raw: bytes) -> None:
    write_effort_rollout(tmp_path / "rollout-a.jsonl", "gpt-example")
    catalog = tmp_path / "catalog.json"
    catalog.write_bytes(raw)
    assert CodexTelemetry(tmp_path, catalog_path=catalog).read("a").effort_levels == ()


def test_rollout_gap_and_truncation_drop_effort_capabilities(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-a.jsonl"
    write_effort_rollout(rollout, "gpt-example")
    catalog = tmp_path / "catalog.json"
    write_model_catalog(catalog, [model_capability("gpt-example", ("low", "high"))])
    source = CodexTelemetry(tmp_path, catalog_path=catalog)
    assert source.read("a").effort_levels == ("low", "high")
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write((json.dumps({"type": "response_item", "payload": "x" * 10000}) + "\n") * 220)
    assert source.read("a").effort_levels == ()
    write_effort_rollout(rollout, "gpt-example")
    assert source.read("a").effort_levels == ("low", "high")
    rollout.write_text('{"type":', encoding="utf-8")
    assert source.read("a").effort_levels == ()


def test_replaced_rollout_with_same_size_and_mtime_drops_old_model_levels(tmp_path: Path) -> None:
    import os

    rollout = tmp_path / "rollout-a.jsonl"
    write_effort_rollout(rollout, "gpt-first")
    catalog = tmp_path / "catalog.json"
    write_model_catalog(catalog, [model_capability("gpt-first", ("low", "high"))])
    source = CodexTelemetry(tmp_path, catalog_path=catalog)
    assert source.read("a").effort_levels == ("low", "high")
    original = rollout.stat()
    replacement = tmp_path / "replacement.jsonl"
    write_effort_rollout(replacement, "gpt-other")
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    replacement.replace(rollout)
    assert rollout.stat().st_size == original.st_size
    assert source.read("a").model == "gpt-other"
    assert source.read("a").effort_levels == ()
