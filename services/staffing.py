"""Підбір персоналу: пошук заміни за принципом 'найменше відпрацьованих годин'."""
import config
import db
from services import dates


async def rank_candidates(day: str, group_id: int | None = None,
                          exclude_user_id: int | None = None) -> list[dict]:
    """Кандидати на зміну, відсортовані за зростанням годин у поточному місяці."""
    d = dates.parse_date(day) or dates.iso(dates.today())
    period_from, period_to = dates.month_bounds(int(d[:4]), int(d[5:7]))

    candidates = []
    for u in await db.list_users(group_id=group_id):
        if exclude_user_id and u["id"] == exclude_user_id:
            continue
        if await db.is_unavailable(u["id"], d):
            continue
        # вже має зміну в цей день?
        busy = await db.fetch_one(
            "SELECT 1 AS x FROM shifts WHERE user_id = ? AND day = ?", (u["id"], d)
        )
        if busy:
            continue
        hours = await db.total_hours(u["id"], period_from, period_to)
        candidates.append({
            "user_id": u["id"],
            "tg_id": u["tg_id"],
            "full_name": u["full_name"],
            "group_name": u.get("group_name") or "—",
            "hours_month": round(hours, 2),
        })

    candidates.sort(key=lambda c: (c["hours_month"], c["full_name"]))
    return candidates


async def workload(date_from: str, date_to: str, group_id: int | None = None) -> list[dict]:
    """Навантаження по людях за період — для оптимізації розподілу."""
    out = []
    for u in await db.list_users(group_id=group_id):
        hours = await db.total_hours(u["id"], date_from, date_to)
        out.append({
            "full_name": u["full_name"],
            "group_name": u.get("group_name") or "—",
            "hours": round(hours, 2),
            "shifts": len(await db.shifts_between(date_from, date_to, user_id=u["id"])),
        })
    out.sort(key=lambda x: x["hours"])
    return out
