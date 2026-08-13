"""Pure model for user-configurable check-ins (no tk/ctk).

A check-in Question has an id, prompt text, an AnswerSpec (how it's answered) and
a Cadence (how often to ask). Parsing is tolerant so a malformed config entry is
dropped, never crashes the app.
"""
from dataclasses import dataclass

# Answer types
SCALE = "scale"       # numeric min..max (small ranges render as faces)
CHOICES = "choices"   # a few fixed options
NOTE = "note"         # free text only
ANSWER_TYPES = (SCALE, CHOICES, NOTE)

# Cadence types
TIMES_PER_DAY = "times_per_day"
PER_DAY = "per_day"
PER_WEEK = "per_week"
CADENCE_TYPES = (TIMES_PER_DAY, PER_DAY, PER_WEEK)

SECONDS_PER_DAY = 86400
DEFAULT_SCALE_MIN, DEFAULT_SCALE_MAX = 1, 5


@dataclass
class AnswerSpec:
    type: str
    min: int = DEFAULT_SCALE_MIN
    max: int = DEFAULT_SCALE_MAX
    min_label: str = ""
    max_label: str = ""
    options: tuple = ()
    allow_note: bool = True


@dataclass
class Cadence:
    type: str
    count: int = 1


@dataclass
class Question:
    id: str
    text: str
    answer: AnswerSpec
    cadence: Cadence
    enabled: bool = True


def _parse_answer(raw):
    if not isinstance(raw, dict):
        return None
    t = raw.get("type")
    if t not in ANSWER_TYPES:
        return None
    if t == CHOICES and not raw.get("options"):
        return None
    return AnswerSpec(
        type=t,
        min=int(raw.get("min", DEFAULT_SCALE_MIN)),
        max=int(raw.get("max", DEFAULT_SCALE_MAX)),
        min_label=str(raw.get("min_label", "")),
        max_label=str(raw.get("max_label", "")),
        options=tuple(raw.get("options", ()) or ()),
        allow_note=bool(raw.get("allow_note", True)),
    )


def _parse_cadence(raw):
    raw = raw if isinstance(raw, dict) else {}
    t = raw.get("type", PER_DAY)
    if t not in CADENCE_TYPES:
        t = PER_DAY
    return Cadence(type=t, count=int(raw.get("count", 1)))


def parse_questions(raw_list):
    """Turn the stored config list into typed Questions, dropping malformed entries."""
    out = []
    for raw in raw_list or []:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("text"):
            continue
        answer = _parse_answer(raw.get("answer"))
        if answer is None:
            continue
        out.append(Question(
            id=str(raw["id"]), text=str(raw["text"]), answer=answer,
            cadence=_parse_cadence(raw.get("cadence")),
            enabled=bool(raw.get("enabled", True))))
    return out


def cadence_interval_seconds(cadence, active_window_seconds):
    """Average spacing between asks for this cadence (a target, not a hard clock)."""
    count = max(1, cadence.count)
    if cadence.type == TIMES_PER_DAY:
        return active_window_seconds / count
    if cadence.type == PER_WEEK:
        return 7 * SECONDS_PER_DAY / count
    return SECONDS_PER_DAY / count          # PER_DAY (default)


def answer_is_valid(spec, value):
    if spec.type == SCALE:
        return isinstance(value, int) and spec.min <= value <= spec.max
    if spec.type == CHOICES:
        return value in spec.options
    return value is None                    # NOTE: the text lives in the note field
