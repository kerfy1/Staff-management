"""Підрахунок зарплати за період."""
from dataclasses import dataclass, field

import config
import db
from services import dates


@dataclass
class PayrollRow:
    user_id: int
    full_name: str
    group_name: str
    rate: float
    regular_hours: float = 0.0
    extra_hours: float = 0.0
    days_worked: int = 0
    sick_days: int = 0
    dayoff_days: int = 0
    absences: int = 0

    @property
    def base_pay(self) -> float:
        return self.regular_hours * self.rate

    @property
    def extra_pay(self) -> float:
        return self.extra_hours * self.rate * config.EXTRA_SHIFT_MULTIPLIER

    @property
    def sick_pay(self) -> float:
        return self.sick_days * config.SHIFT_NORM_HOURS * self.rate * config.SICK_PAY_RATE

    @property
    def total(self) -> float:
        return round(self.base_pay + self.extra_pay + self.sick_pay, 2)

    @property
    def total_hours(self) -> float:
        return round(self.regular_hours + self.extra_hours, 2)


async def calculate(date_from: str, date_to: str, group_id: int | None = None,
                    user_id: int | None = None) -> list[PayrollRow]:
    users = await db.list_users(group_id=group_id)
    if user_id:
        users = [u for u in users if u["id"] == user_id]

    rows: dict[int, PayrollRow] = {
        u["id"]: PayrollRow(
            user_id=u["id"],
            full_name=u["full_name"],
            group_name=u.get("group_name") or "—",
            rate=float(u.get("hourly_rate") or config.DEFAULT_HOURLY_RATE),
        )
        for u in users
    }

    for s in await db.shifts_between(date_from, date_to, group_id=group_id):
        row = rows.get(s["user_id"])
        if not row or not s.get("hours"):
            continue
        hours = float(s["hours"])
        if s["kind"] == "extra":
            row.extra_hours += hours
        else:
            row.regular_hours += hours
        row.days_worked += 1

    period_days = set(dates.days_between(date_from, date_to))
    for r in await db.list_requests(status="approved", date_from=date_from, date_to=date_to):
        row = rows.get(r["user_id"])
        if not row:
            continue
        overlap = len(set(dates.days_between(r["date_from"], r["date_to"])) & period_days)
        if r["kind"] == "sick":
            row.sick_days += overlap
        elif r["kind"] == "dayoff":
            row.dayoff_days += overlap

    for a in await db.absences_between(date_from, date_to):
        row = rows.get(a["user_id"])
        if row:
            row.absences += 1

    for r in rows.values():
        r.regular_hours = round(r.regular_hours, 2)
        r.extra_hours = round(r.extra_hours, 2)

    return sorted(rows.values(), key=lambda r: r.full_name)


async def summary_text(row: PayrollRow, date_from: str, date_to: str) -> str:
    c = config.CURRENCY
    return (
        f"Період: {dates.period_title(date_from, date_to)}\n"
        f"Відпрацьовано днів: {row.days_worked}\n"
        f"Годин (звичайні): {row.regular_hours}\n"
        f"Годин (додаткові, ×{config.EXTRA_SHIFT_MULTIPLIER}): {row.extra_hours}\n"
        f"Ставка: {row.rate} {c}/год\n"
        f"Лікарняні: {row.sick_days} дн. ({round(row.sick_pay, 2)} {c})\n"
        f"Вихідні: {row.dayoff_days} дн.\n"
        f"Разом до виплати: {row.total} {c}"
    )
