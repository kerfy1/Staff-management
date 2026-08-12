"""Розбір українських дат: 'липень', 'завтра', 'минулий тиждень', '5 серпня'."""
import calendar
import re
from datetime import date, datetime, timedelta

import config

MONTHS = {
    "січень": 1, "січня": 1, "лютий": 2, "лютого": 2, "березень": 3, "березня": 3,
    "квітень": 4, "квітня": 4, "травень": 5, "травня": 5, "червень": 6, "червня": 6,
    "липень": 7, "липня": 7, "серпень": 8, "серпня": 8, "вересень": 9, "вересня": 9,
    "жовтень": 10, "жовтня": 10, "листопад": 11, "листопада": 11, "грудень": 12, "грудня": 12,
}
MONTHS_GEN = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
    7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
}
WEEKDAYS = {
    "понеділок": 0, "вівторок": 1, "середа": 2, "середу": 2, "четвер": 3,
    "п'ятниця": 4, "п'ятницю": 4, "пятниця": 4, "субота": 5, "суботу": 5,
    "неділя": 6, "неділю": 6,
}


def today() -> date:
    return datetime.now(config.TZ).date()


def now() -> datetime:
    return datetime.now(config.TZ)


def iso(d: date) -> str:
    return d.isoformat()


def human(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.day} {MONTHS_GEN[d.month]} {d.year}"


def month_bounds(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return iso(date(year, month, 1)), iso(date(year, month, last))


def parse_date(text: str, base: date | None = None) -> str | None:
    """Повертає ISO-дату або None. Розуміє ISO, 'завтра', '5 серпня', '05.08', 'у понеділок'."""
    if not text:
        return None
    t = text.strip().lower()
    base = base or today()

    # вже ISO
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t

    relative = {
        "сьогодні": 0, "сьогодня": 0, "завтра": 1, "післязавтра": 2,
        "позавтра": 2, "вчора": -1, "позавчора": -2,
    }
    for word, delta in relative.items():
        if word in t:
            return iso(base + timedelta(days=delta))

    # 05.08.2026 / 05.08 / 5/8
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
    if m:
        day, mon = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else base.year
        if year < 100:
            year += 2000
        try:
            return iso(date(year, mon, day))
        except ValueError:
            return None

    # "5 серпня" / "5 серпня 2026"
    m = re.search(r"\b(\d{1,2})\s+([а-яіїєґ']+)(?:\s+(\d{4}))?", t)
    if m and m.group(2) in MONTHS:
        day = int(m.group(1))
        mon = MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else base.year
        try:
            return iso(date(year, mon, day))
        except ValueError:
            return None

    # "у понеділок" — найближчий
    for word, idx in WEEKDAYS.items():
        if word in t:
            ahead = (idx - base.weekday()) % 7 or 7
            return iso(base + timedelta(days=ahead))
    return None


def parse_period(text: str, base: date | None = None) -> tuple[str, str]:
    """Повертає (date_from, date_to). За замовчуванням — поточний місяць."""
    base = base or today()
    t = (text or "").strip().lower()

    if not t or "поточний місяць" in t or "цей місяць" in t or "місяць" == t:
        return month_bounds(base.year, base.month)

    if "минул" in t and "місяц" in t:
        prev = base.replace(day=1) - timedelta(days=1)
        return month_bounds(prev.year, prev.month)

    if "тижд" in t:
        start = base - timedelta(days=base.weekday())
        if "минул" in t:
            start -= timedelta(days=7)
        return iso(start), iso(start + timedelta(days=6))

    if "сьогодні" in t:
        return iso(base), iso(base)

    if "вчора" in t:
        y = base - timedelta(days=1)
        return iso(y), iso(y)

    if "рік" in t or "року" in t:
        return iso(date(base.year, 1, 1)), iso(date(base.year, 12, 31))

    # "2026-07" або "07.2026"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m:
        return month_bounds(int(m.group(1)), int(m.group(2)))

    # назва місяця
    for word, mon in MONTHS.items():
        if word in t:
            year = base.year
            ym = re.search(r"\b(20\d{2})\b", t)
            if ym:
                year = int(ym.group(1))
            elif mon > base.month:      # "звіт за грудень" у липні -> минулий рік
                year -= 1
            return month_bounds(year, mon)

    # діапазон "з 1 по 15"
    m = re.search(r"з\s+(\d{1,2})\D+по\s+(\d{1,2})", t)
    if m:
        last = calendar.monthrange(base.year, base.month)[1]
        d1 = min(int(m.group(1)), last)
        d2 = min(int(m.group(2)), last)
        return iso(date(base.year, base.month, d1)), iso(date(base.year, base.month, d2))

    return month_bounds(base.year, base.month)


def period_title(date_from: str, date_to: str) -> str:
    return f"{human(date_from)} — {human(date_to)}"


def days_between(date_from: str, date_to: str) -> list[str]:
    d1, d2 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    return [iso(d1 + timedelta(days=i)) for i in range((d2 - d1).days + 1)]


def parse_datetime(text: str, base: datetime | None = None) -> str | None:
    """'завтра о 10:00' -> 'YYYY-MM-DD HH:MM'."""
    base = base or now()
    d = parse_date(text, base.date()) or iso(base.date())
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", text or "")
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    else:
        m2 = re.search(r"\bо\s+(\d{1,2})\b", (text or "").lower())
        hh, mm = (int(m2.group(1)), 0) if m2 else (9, 0)
    return f"{d} {hh:02d}:{mm:02d}"
