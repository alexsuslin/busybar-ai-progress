from __future__ import annotations

from importlib.resources import files

from busylib import types

from .dashboard import DisplayFrame
from .events import DisplayState


def icon_png(provider: str) -> bytes:
    if provider not in {"openai", "anthropic"}:
        raise ValueError("unsupported provider")
    return files("busybar_codex").joinpath("assets", f"provider-{provider}.png").read_bytes()


def frame_elements(frame: DisplayFrame) -> list[types.DisplayElement]:
    data = frame.telemetry
    color = {
        DisplayState.CODING: "#2B7FFF",
        DisplayState.QUESTION: "#FFB000",
        DisplayState.DONE: "#36D17C",
    }[frame.state]
    labels = {
        DisplayState.CODING: "CODING",
        DisplayState.QUESTION: "QUESTION?",
        DisplayState.DONE: "DONE",
    }
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
                color=color if display == front else "#FFFFFF",
                scroll_rate=12,
                scroll_start_delay=1000,
                scroll_repeat_delay=2000,
            )
        )

    def rectangle(
        key: str, x: int, y: int, width: int, height: int, fill: str, display: types.DisplayName
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
    text("front-state", data.model.upper() if data.model else labels[frame.state], 14, 0, 58, front)
    short_state = {
        DisplayState.CODING: "RUN",
        DisplayState.QUESTION: "ASK",
        DisplayState.DONE: "DONE",
    }
    detail = (
        f"{frame.session_tag} {short_state[frame.state]} {(data.effort or 'N/A').upper()}"
        if frame.session_tag
        else "NO SESSION"
    )
    text("front-session", detail, 14, 8, 58, front, small=True)
    rectangle("front-context-track", 0, 15, 72, 1, "#242424", front)
    context = data.context_percent or 0
    rectangle(
        "front-context-fill",
        0,
        15,
        max(1, round(72 * context / 100)),
        1,
        ("#FFB000" if context >= 80 else color) if context else "#242424",
        front,
    )

    text("back-model", data.model or "MODEL N/A", 15, 0, 129)
    text("back-effort", f"REASONING {data.effort or 'N/A'}", 0, 13, 144)
    text("back-state", f"{labels[frame.state]}  {frame.session_tag or '-'}", 0, 25, 144)
    text(
        "back-sessions",
        f"SESSIONS {frame.session_count}  QUESTIONS {frame.question_count}",
        0,
        36,
        144,
        small=True,
    )
    percent = f"{data.context_percent:.0f}%" if data.context_percent is not None else "N/A"
    size = f" / {data.context_size:,}" if data.context_size is not None else ""
    text("back-context", f"CTX {percent}{size}", 0, 46, 144)
    limits: list[str] = []
    for window in data.limits:
        minutes = window.window_minutes
        duration = (
            f"{minutes // 1440}d"
            if minutes % 1440 == 0
            else f"{minutes // 60}h"
            if minutes % 60 == 0
            else f"{minutes}m"
        )
        limits.append(f"{duration} {window.used_percent:.0f}%")
    text("back-limits", "USED " + "  ".join(limits) if limits else "LIMITS N/A", 0, 58, 144)
    # Keep the old ID/type/display to explicitly hide the firmware-upserted hint.
    text("back-controls", "", 0, 69, 160, small=True)
    rectangle("back-context-track", 0, 79, 144, 1, "#444444", back)
    rectangle(
        "back-context-fill",
        0,
        79,
        max(1, round(144 * context / 100)),
        1,
        "#FFFFFF" if context else "#444444",
        back,
    )
    return elements
