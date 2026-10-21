"""Race-time durations stored as seconds, read and written as "H:MM:SS" strings.

LLMs and humans both handle "3:45:00" far better than ISO-8601 durations, so the
public representation is always a clock string.
"""

from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema


def parse_duration(value: object) -> int:
    """Parse "H:MM:SS", "MM:SS", or a number of seconds into whole seconds."""
    if isinstance(value, bool):
        raise ValueError("duration cannot be a boolean")
    if isinstance(value, (int, float)):
        seconds = int(value)
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if not 1 <= len(parts) <= 3 or not all(p.strip().isdigit() for p in parts):
            raise ValueError(f"expected H:MM:SS or MM:SS, got {value!r}")
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
    else:
        raise ValueError(f"cannot parse duration from {value!r}")
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return seconds


def format_duration(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


Duration = Annotated[
    int,
    BeforeValidator(parse_duration),
    PlainSerializer(format_duration, return_type=str),
    WithJsonSchema({"type": "string", "description": 'Clock time, e.g. "3:45:00" or "24:30"'}),
]
