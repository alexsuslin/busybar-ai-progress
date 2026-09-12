from __future__ import annotations

from importlib.resources import files

from busylib import types

from .dashboard import DisplayFrame, WorkActivity
from .events import DisplayState
from .telemetry import number


def icon_png(provider: str) -> bytes:
    if provider not in {"openai", "anthropic"}:
        raise ValueError("unsupported provider")
    return files("busybar_codex").joinpath("assets", f"provider-{provider}.png").read_bytes()


def compact_duration(seconds: float) -> str:
    """Compact relative time, without displaying zero before a future reset."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 1440:
        hours, remainder = divmod(minutes, 60)
        return f"{hours}h {remainder}m" if remainder else f"{hours}h"
    return f"{minutes // 1440}d"


def frame_elements(frame: DisplayFrame) -> list[types.DisplayElement]:
    data = frame.telemetry
    activity = frame.activity if frame.state is DisplayState.CODING else None
    color = {
        DisplayState.CODING: "#2B7FFF",
        DisplayState.QUESTION: "#FFB000",
        DisplayState.DONE: "#36D17C",
    }[frame.state]
    if activity is not None:
        color = {
            WorkActivity.THINK: "#3FD8FF",
            WorkActivity.TOOL: "#2B7FFF",
            WorkActivity.CHECK: "#B58AFF",
            WorkActivity.COMPACT: "#79B8FF",
        }[activity]
    now = number(frame.now, 253402300799)
    stamp = data.usage_observed_at
    age = now - stamp if now is not None and stamp is not None and stamp <= now else None
    stale = age is not None and age >= 900
    windows = data.current_limits(now) if now is not None else data.limits

    def usage_color(percent: float) -> str:
        if stale or age is None:
            return "#777777"
        return "#FF6262" if percent >= 95 else "#FFB000" if percent >= 80 else "#3FD8FF"

    labels = {
        DisplayState.CODING: "CODING",
        DisplayState.QUESTION: "QUESTION?",
        DisplayState.DONE: "DONE",
    }
    if activity is not None:
        labels[DisplayState.CODING] = (
            "THINKING" if activity is WorkActivity.THINK else activity.value
        )
    front, back = types.DisplayName.FRONT, types.DisplayName.BACK
    elements: list[types.DisplayElement] = []

    def text(
        key: str,
        value: str,
        x: int,
        y: int,
        width: int,
        display: types.DisplayName = back,
        small: bool = False,
        ink: str | None = None,
    ) -> None:
        elements.append(
            types.TextElement(
                id=key,
                text=value,
                x=x,
                y=y,
                width=width,
                display=display,
                font="tiny" if small else "small",
                color=ink or (color if display == front else "#FFFFFF"),
                scroll_rate=12,
                scroll_start_delay=1000,
                scroll_repeat_delay=2000,
            )
        )

    def rectangle(
        key: str,
        x: int,
        y: int,
        width: int,
        height: int,
        fill: str,
        display: types.DisplayName,
    ) -> None:
        elements.append(
            types.RectangleElement(
                id=key,
                x=x,
                y=y,
                width=width,
                height=height,
                display=display,
                fill="solid",
                fill_colors=[fill],
                border_width=0,
            )
        )

    # Firmware upserts by ID: submit every element on every frame, even when hidden.
    rectangle("front-background", 0, 0, 72, 16, "#000000", front)
    rectangle("back-background", 0, 0, 160, 80, "#000000", back)
    for display in (front, back):
        elements.append(
            types.ImageElement(
                id=f"{display}-provider",
                x=0,
                y=0,
                display=display,
                path=f"provider-{data.provider or 'openai'}.png",
                opacity=100 if data.provider else 0,
            )
        )
    text("front-state", data.model.upper() if data.model else labels[frame.state], 14, 0, 56, front)
    short_state = {
        DisplayState.CODING: "RUN",
        DisplayState.QUESTION: "ASK",
        DisplayState.DONE: "DONE",
    }
    if activity is not None:
        short_state[DisplayState.CODING] = activity.value
    detail = (
        f"{frame.session_tag} {short_state[frame.state]}" if frame.session_tag else "NO SESSION"
    )
    text("front-session", detail, 14, 8, 56, front, small=True)
    levels = data.effort_levels
    active = (
        levels.index(data.effort) + 1 if data.effort is not None and data.effort in levels else 0
    )
    # Stable pixel IDs hide unused levels when capabilities disappear or shrink.
    for display, x in ((front, 71), (back, 159)):
        for index in range(8):
            rectangle(
                f"{display}-effort-{index}",
                x,
                13 - index,
                1,
                1,
                (color if index < active else "#444444")
                if index < len(levels) and active
                else "#000000",
                display,
            )
    rectangle("front-context-track", 0, 15, 72, 1, "#242424", front)
    context = data.context_percent or 0
    rectangle(
        "front-context-fill",
        0,
        15,
        max(1, round(72 * context / 100)),
        1,
        usage_color(context) if context else "#242424",
        front,
    )

    text("back-model", data.model or "MODEL N/A", 15, 0, 129)
    text("back-effort", "", 0, 13, 144)
    text("back-state", f"{labels[frame.state]}  {frame.session_tag or '-'}", 0, 12, 144, ink=color)
    text(
        "back-sessions",
        f"SESSIONS {frame.session_count}  QUESTIONS {frame.question_count}",
        0,
        22,
        144,
        small=True,
        ink="#FFB000" if frame.question_count else "#FFFFFF",
    )
    percent = f"{data.context_percent:.0f}%" if data.context_percent is not None else "N/A"
    size = f" / {data.context_size:,}" if data.context_size is not None else ""
    text(
        "back-context",
        f"CTX {percent}{size}",
        0,
        32,
        144,
        ink=usage_color(context) if data.context_percent is not None else "#777777",
    )
    for index in range(3):
        value = "LIMITS N/A" if index == 0 else ""
        ink = "#777777"
        if index < len(windows):
            window = windows[index]
            minutes = window.window_minutes
            duration = (
                f"{minutes // 1440}d"
                if minutes % 1440 == 0
                else f"{minutes // 60}h"
                if minutes % 60 == 0
                else f"{minutes}m"
            )
            reset = (
                compact_duration(window.resets_at - now)
                if window.resets_at is not None and now is not None
                else "N/A"
            )
            value = f"{duration} USED {window.used_percent:.0f}%  RESET {reset}"
            ink = usage_color(window.used_percent)
        text(
            "back-limits" if index == 0 else f"back-limit-{index}",
            value,
            0,
            42 + index * 9,
            144,
            small=True,
            ink=ink,
        )
    if data.context_percent is None and not windows:
        freshness = "DATA N/A"
    elif age is None:
        freshness = "AGE N/A"
    else:
        freshness = ("STALE " if stale else "DATA ") + compact_duration(age)
    text("back-freshness", freshness, 0, 69, 144, small=True, ink="#FFB000" if stale else "#777777")
    # Keep the old ID/type/display to explicitly hide the firmware-upserted hint.
    text("back-controls", "", 0, 69, 160, small=True)
    rectangle("back-context-track", 0, 79, 144, 1, "#444444", back)
    rectangle(
        "back-context-fill",
        0,
        79,
        max(1, round(144 * context / 100)),
        1,
        usage_color(context) if context else "#444444",
        back,
    )
    phase = frame.motion_phase
    phase = phase if type(phase) is int and 0 <= phase < 8 else None
    motion_x, motion_width, motion_color = 0, 12, "#000000"
    if phase is not None:
        motion_color = color
        if frame.state is DisplayState.CODING:
            motion_x = (0, 2, 4, 6, 8, 6, 4, 2)[phase]
            motion_width = 3
        elif frame.state is DisplayState.QUESTION:
            motion_x, motion_width = 2, 8
            motion_color = (
                "#805800",
                "#AA7500",
                "#D89400",
                "#FFB000",
                "#D89400",
                "#AA7500",
                "#805800",
                "#604200",
            )[phase]
        else:
            motion_width = min(12, (phase + 1) * 3)
    rectangle("front-motion", motion_x, 13, motion_width, 1, motion_color, front)
    rectangle("back-motion", 146 + motion_x, 18, motion_width, 1, motion_color, back)

    overview = frame.overview
    text(
        "back-overview-page",
        f"{overview.page}/{overview.pages}" if overview.sessions else "",
        146,
        10,
        12,
        small=True,
        ink="#777777",
    )
    for index in range(8):
        word, ink, selected = "", "#000000", False
        if index < len(overview.sessions):
            badge = overview.sessions[index]
            word = f"{badge.number:02d}"
            selected = f"#{badge.number:02d}" == frame.session_tag
            ink = (
                color
                if selected
                else {
                    DisplayState.CODING: "#2B7FFF",
                    DisplayState.QUESTION: "#FFB000",
                    DisplayState.DONE: "#36D17C",
                }[badge.state]
            )
        text(f"back-overview-{index}", word, 150, 21 + index * 7, 10, small=True, ink=ink)
        rectangle(
            f"back-overview-selected-{index}",
            146,
            23 + index * 7,
            2,
            2,
            "#FFFFFF" if selected else "#000000",
            back,
        )
    return elements
