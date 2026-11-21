"""Loads prompt files from app/prompts (plain files, editable without touching code)."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


@lru_cache
def load_prompt(name: str) -> str:
    return _strip_front_matter((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


@lru_cache
def load_templates() -> dict[str, str]:
    with (PROMPTS_DIR / "templates.yaml").open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def template(key: str) -> str:
    return load_templates()[key]


def local_now(timezone: str | None) -> datetime:
    """Current time in the user's timezone (from the browser); UTC if unknown."""
    try:
        tz = ZoneInfo(timezone) if timezone else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def describe_now(now: datetime) -> str:
    """e.g. 'Saturday, 21 November 2026, 10:42 (Asia/Kolkata, UTC+05:30)'."""
    offset = now.strftime("%z")
    offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    return f"{now:%A}, {now.day} {now:%B %Y, %H:%M} ({now.tzinfo}, {offset})"


def system_prompt(assistant_name: str, now: datetime) -> str:
    return load_prompt("system_base").format(assistant_name=assistant_name, now=describe_now(now))
