"""Fast, rule-based checks that avoid an LLM or API call."""

import re

_TRIVIAL = re.compile(
    r"^(hi+|hey+|hello+|hiya|yo|sup|thanks?|thank you|thx|ty|ok(ay)?|cool|nice|great|"
    r"good (morning|afternoon|evening|night)|bye|goodbye|see you|how are you|"
    r"what'?s up|lol|haha+|yes|no|sure)[\s!.?]*$",
    re.IGNORECASE,
)

# Live data we can't provide yet -> "don't know".
_REALTIME = re.compile(
    r"\b(weather (today|tomorrow|tonight|now|in|at|like|this|forecast)|"
    r"(weather )?forecast for|humidity (today|now|in)|temperature (outside|today|now|in)|"
    r"(is it|will it) (going to )?(rain|snow)|"
    r"live score|score right now|stock price|share price|crypto price|bitcoin price|"
    r"traffic (now|today|in|on)|flight status)\b",
    re.IGNORECASE,
)

# Fallback when the LLM router is off or fails: things that are likely to have changed.
_NEEDS_SEARCH = re.compile(
    r"\b(latest|news|today|tonight|yesterday|current(ly)?|recent(ly)?|now|"
    r"this (week|month|year)|last (week|month|year)|20[2-3]\d|who won|winner|"
    r"highest|lowest|biggest|most|top \d+|record|box office|gross(ed|ing)?|"
    r"release(d| date)?|price of|ranking|election|ceo of|president of|prime minister)\b",
    re.IGNORECASE,
)


# The current date/time is in the system prompt, so these are plain chat.
_DATETIME = re.compile(
    r"\b(what('?s| is) (the )?(date|day|time|year|month)|today'?s date|what day is (it|today)|"
    r"(current|local) (date|time)|what time is it|which (day|year|month) is (it|today))\b",
    re.IGNORECASE,
)


def is_datetime_question(text: str) -> bool:
    return bool(_DATETIME.search(text))


def is_trivial(text: str) -> bool:
    """Greetings / acknowledgements: safe to skip moderation, routing and memory."""
    return bool(_TRIVIAL.match(text.strip()))


def is_realtime(text: str) -> bool:
    return bool(_REALTIME.search(text))


def likely_needs_search(text: str) -> bool:
    return bool(_NEEDS_SEARCH.search(text))
