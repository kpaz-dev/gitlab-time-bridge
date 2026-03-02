import re
from typing import Optional


TIME_PATTERN = re.compile(
    r"added\s+(?P<time>(?:\d+\s*h(?:ours?)?)?(?:\s*\d+\s*m(?:in(?:utes?)?)?)?|\d+\s*m(?:in(?:utes?)?)?|\d+\s*h(?:ours?)?)\s+of\s+time\s+spent",
    re.IGNORECASE,
)


def parse_time_note(note: str) -> Optional[int]:
    """Parse GitLab time tracking note like 'added 1h of time spent' or 'added 30m of time spent'.

    Returns seconds if match is found, otherwise None.
    Supports formats: '1h', '30m', '1h 30m', '2 hours', '45 min'.
    """
    if not note:
        return None
    m = TIME_PATTERN.search(note)
    if not m:
        return None
    time_str = m.group("time").strip().lower()
    return parse_duration_to_seconds(time_str)


def parse_duration_to_seconds(s: str) -> Optional[int]:
    if not s:
        return None
    hours = 0
    minutes = 0
    # Match 'Xh' or 'X hours'
    mh = re.search(r"(\d+)\s*h(?:ours?)?", s)
    if mh:
        hours = int(mh.group(1))
    # Match 'Ym' or 'Y min'
    mm = re.search(r"(\d+)\s*m(?:in(?:utes?)?)?", s)
    if mm:
        minutes = int(mm.group(1))
    if hours == 0 and minutes == 0:
        # Maybe it's just a number without unit (assume minutes)
        monly = re.fullmatch(r"\d+", s)
        if monly:
            minutes = int(s)
        else:
            return None
    return hours * 3600 + minutes * 60
