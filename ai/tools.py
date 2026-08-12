"""Інструменти (function calling), доступні агенту.

Кожен інструмент прив'язаний до домену (функції) і до ролі.
Агент бачить лише ті інструменти, які стосуються поточної функції — це і є
"роздільна промптація під кожну функцію".
"""
import os
from dataclasses import dataclass
from typing import Any, Callable

from aiogram import Bot
from aiogram.types import FSInputFile

import config
import db
from services import dates, payroll, reports, staffing

REGISTRY: dict[str, dict] = {}


@dataclass
class Ctx:
    bot: Bot
    user: dict | None          # рядок з таблиці users (None до реєстрації)
    tg_id: int
    is_manager: bool


def tool(name: str, description: str, params: dict, domains: list[str], manager: bool = False):
    def wrapper(fn: Callable):
        REGISTRY[name] = {
            "fn": fn,
            "manager": manager,
            "domains": set(domains),
            "spec": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": params,
                        "required": [k for k, v in params.items() if v.get("required")],
                        "additionalProperties": False,
                    },
                },
            },
        }
        # прибираємо службовий ключ 'required' зі схеми властивостей
        for prop in REGISTRY[name]["spec"]["function"]["parameters"]["properties"].values():
            prop.pop("required", None)
        return fn
    return wrapper


def tools_for(domain: str, is_manager: bool) -> list[dict]:
    out = []
    for meta in REGISTRY.values():
        if meta["manager"] != is_manager:
            continue
        if domain in meta["domains"]:
            out.append(meta["spec"])
    return out


async def dispatch(name: str, args: dict, ctx: Ctx) -> Any:
    meta = REGISTRY.get(name)
    if not meta:
        return {"error": f"Невідомий інструмент {name}"}
    try:
        return await meta["fn"](ctx, **args)
    except TypeError as e:
        return {"error": f"Некоректні аргументи: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Помилка виконання: {e}"}


# ---------- helpers ----------

STR = {"type": "string"}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}


def _req(schema: dict, desc: str) -> dict:
    return {**schema, "description": desc, "required": True}


def _opt(schema: dict, desc: str) -> dict:
    return {**schema, "description": desc}


async def _notify_managers(ctx: Ctx, text: str) -> None:
    for mid in config.MANAGER_IDS:
        try:
            await ctx.bot.send_message(mid, text)
        except Exception:  # noqa: BLE001,S110
            pass


async def _resolve_user(name_query: str) -> tuple[dict | None, list[dict]]:
    found = await db.search_users(name_query)
    if len(found) == 1:
        return found[0], found
    return None, found


async def _send(ctx: Ctx, tg_id: int, text: str) -> bool:
    try:
        await ctx.bot.send_message(tg_id, text)
        return True
    except Exception:  # noqa: BLE001
        return False


# =====================================================================
#                        РЕЄСТРАЦІЯ
# =====================================================================

@tool("register_employee", "Зареєструвати нового користувача. Потрібне ЛИШЕ ПІБ.",
      {"full_name": _req(STR, "Повне ПІБ, напр. 'Саша Гнездо'")},
      domains=["registration"])
async def register_employee(ctx: Ctx, full_name: str):
    from handlers import keyboards as kb   # локальний імпорт, щоб не було циклу

    if ctx.user:
        return {"error": "Користувач вже зареєстрований"}

    role = "manager" if ctx.is_manager else "employee"
    status = "active" if ctx.is_manager else "pending"
    # посаду НЕ просимо — її призначить керівник; поки що None
    uid = await db.create_user(ctx.tg_id, full_name, None, None, None,
                               role=role, status=status)

    if role == "employee":
        for mid in config.MANAGER_IDS:
            try:
                await ctx.bot.send_message(
                    mid,
                    f"🆕 <b>Нова заявка на реєстрацію</b>\n{full_name} (id {ctx.tg_id})",
                    reply_markup=kb.registration_kb(uid),
                )
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "user_id": uid, "status": "pending",
                "note": "Заявку надіслано керівнику. Посаду призначить керівник пізніше. "
                        "Скажи працівнику очікувати підтвердження."}

    return {"ok": True, "user_id": uid, "role": "manager", "status": "active",
            "note": "Керівника зареєстровано"}

    if ctx.user:
        return {"error": "Користувач вже зареєстрований"}

    role = "manager" if ctx.is_manager else "employee"
    status = "active" if ctx.is_manager else "pending"
    uid = await db.create_user(ctx.tg_id, full_name, position, phone, None,
                               role=role, status=status)

    if role == "employee":
        for mid in config.MANAGER_IDS:
            try:
                await ctx.bot.send_message(
                    mid,
                    f"🆕 <b>Нова заявка на реєстрацію</b>\n{full_name} — {position} "
                    f"(id {ctx.tg_id})",
                    reply_markup=kb.registration_kb(uid),
                )
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "user_id": uid, "status": "pending",
                "note": "Заявку надіслано керівнику. Скажи працівнику очікувати підтвердження."}

    return {"ok": True, "user_id": uid, "role": "manager", "status": "active",
            "note": "Керівника зареєстровано, меню відкрито"}


# =====================================================================
#                     ПРАЦІВНИК: облік часу
# =====================================================================

@tool("start_shift", "Відмітити початок зміни (прихід на роботу).", {},
      domains=["attendance"])
async def start_shift(ctx: Ctx):
    if await db.get_open_shift(ctx.user["id"]):
        return {"error": "Зміна вже відкрита. Спершу закрий її."}
    now = dates.now()
    await db.open_shift(ctx.user["id"], dates.iso(now.date()), now.strftime("%H:%M"))
    return {"ok": True, "started_at": now.strftime("%H:%M"), "day": dates.iso(now.date())}


@tool("end_shift", "Відмітити кінець зміни. Години рахуються автоматично.", {},
      domains=["attendance"])
async def end_shift(ctx: Ctx):
    shift = await db.get_open_shift(ctx.user["id"])
    if not shift:
        return {"error": "Немає відкритої зміни"}
    now = dates.now()
    h1, m1 = map(int, shift["start_at"].split(":"))
    minutes = (now.hour * 60 + now.minute) - (h1 * 60 + m1)
    if minutes < 0:
        minutes += 24 * 60
    hours = round(minutes / 60, 2)
    await db.close_shift(shift["id"], now.strftime("%H:%M"), hours)
    return {"ok": True, "hours": hours, "from": shift["start_at"], "to": now.strftime("%H:%M")}


@tool("log_shift", "Записати відпрацьовану зміну вручну (у т.ч. додаткову).",
      {"day": _req(STR, "Дата YYYY-MM-DD"),
       "hours": _req(NUM, "Кількість годин"),
       "kind": _opt(STR, "'regular' або 'extra' (додаткова зміна)"),
       "comment": _opt(STR, "Коментар")},
      domains=["attendance"])
async def log_shift(ctx: Ctx, day: str, hours: float, kind: str = "regular",
                    comment: str | None = None):
    d = dates.parse_date(day) or day
    kind = "extra" if kind == "extra" else "regular"
    await db.add_shift(ctx.user["id"], d, float(hours), kind, comment=comment)
    if kind == "extra":
        await _notify_managers(
            ctx, f"➕ {ctx.user['full_name']} записав додаткову зміну {dates.human(d)} — {hours} год."
        )
    return {"ok": True, "day": d, "hours": hours, "kind": kind}


@tool("my_hours", "Скільки працівник відпрацював за період.",
      {"period": _opt(STR, "Період: 'липень', 'цей тиждень', 'минулий місяць'")},
      domains=["attendance"])
async def my_hours(ctx: Ctx, period: str | None = None):
    d1, d2 = dates.parse_period(period or "")
    shifts = await db.shifts_between(d1, d2, user_id=ctx.user["id"])
    regular = sum(s["hours"] or 0 for s in shifts if s["kind"] == "regular")
    extra = sum(s["hours"] or 0 for s in shifts if s["kind"] == "extra")
    return {"period": dates.period_title(d1, d2), "days": len(shifts),
            "regular_hours": round(regular, 2), "extra_hours": round(extra, 2),
            "total_hours": round(regular + extra, 2)}


# =====================================================================
#                     ПРАЦІВНИК: заявки
# =====================================================================

async def _create_request(ctx: Ctx, kind: str, date_from: str, date_to: str,
                          comment: str | None, title: str):
    d1 = dates.parse_date(date_from) or date_from
    d2 = dates.parse_date(date_to or date_from) or d1
    rid = await db.add_request(ctx.user["id"], kind, d1, d2, comment)
    await _notify_managers(
        ctx,
        f"📝 Заявка #{rid}: {title}\nПрацівник: {ctx.user['full_name']} "
        f"({ctx.user.get('group_name') or 'без групи'})\n"
        f"Період: {dates.human(d1)} — {dates.human(d2)}\n"
        f"Коментар: {comment or '—'}\n\nНапишіть «схвалити заявку {rid}» або «відхилити заявку {rid}».",
    )
    return {"ok": True, "request_id": rid, "from": d1, "to": d2, "status": "pending"}


@tool("request_day_off", "Запросити вихідний на дату або діапазон дат.",
      {"date_from": _req(STR, "Дата початку YYYY-MM-DD"),
       "date_to": _opt(STR, "Дата кінця YYYY-MM-DD (якщо один день — та сама)"),
       "comment": _opt(STR, "Причина")},
      domains=["requests"])
async def request_day_off(ctx: Ctx, date_from: str, date_to: str | None = None,
                          comment: str | None = None):
    return await _create_request(ctx, "dayoff", date_from, date_to or date_from, comment, "Вихідний")


@tool("request_sick_leave", "Запросити лікарняний від дати і до дати.",
      {"date_from": _req(STR, "Від YYYY-MM-DD"),
       "date_to": _req(STR, "До YYYY-MM-DD"),
       "comment": _opt(STR, "Коментар")},
      domains=["requests"])
async def request_sick_leave(ctx: Ctx, date_from: str, date_to: str, comment: str | None = None):
    return await _create_request(ctx, "sick", date_from, date_to, comment, "Лікарняний")


@tool("request_extra_shift", "Запросити додаткову зміну на дату (потребує погодження).",
      {"day": _req(STR, "Дата YYYY-MM-DD"),
       "hours": _opt(NUM, "Скільки годин"),
       "comment": _opt(STR, "Коментар")},
      domains=["requests"])
async def request_extra_shift(ctx: Ctx, day: str, hours: float | None = None,
                              comment: str | None = None):
    note = f"{hours} год. {comment or ''}".strip() if hours else comment
    return await _create_request(ctx, "extra_shift", day, day, note, "Додаткова зміна")


@tool("my_requests", "Показати мої заявки.",
      {"status": _opt(STR, "'pending', 'approved', 'rejected' або порожньо — всі")},
      domains=["requests"])
async def my_requests(ctx: Ctx, status: str | None = None):
    rows = await db.list_requests(status=status, user_id=ctx.user["id"])
    return [{"id": r["id"], "kind": r["kind"], "from": r["date_from"], "to": r["date_to"],
             "status": r["status"], "comment": r["comment"]} for r in rows]


@tool("answer_cover_offer", "Відповісти на пропозицію підмінити колегу.",
      {"accept": _req(BOOL, "true — погоджуюсь, false — відмовляюсь")},
      domains=["requests", "attendance"])
async def answer_cover_offer(ctx: Ctx, accept: bool):
    offer = await db.last_pending_offer(ctx.user["id"])
    if not offer:
        return {"error": "Немає активних пропозицій підміни"}
    await db.set_offer_status(offer["id"], "accepted" if accept else "declined")
    if accept:
        await db.add_shift(ctx.user["id"], offer["day"], config.SHIFT_NORM_HOURS, "extra",
                           comment="Підміна")
    verdict = "погодився" if accept else "відмовився"
    await _notify_managers(
        ctx, f"🔁 {ctx.user['full_name']} {verdict} вийти на підміну {dates.human(offer['day'])}."
    )
    return {"ok": True, "accepted": accept, "day": offer["day"]}


# =====================================================================
#                 ПРАЦІВНИК: нотатки / зарплата / нагадування
# =====================================================================

@tool("leave_note", "Залишити нотатку (повідомлення) для керівника.",
      {"text": _req(STR, "Текст нотатки")},
      domains=["notes"])
async def leave_note(ctx: Ctx, text: str):
    nid = await db.add_note(ctx.user["id"], text)
    await _notify_managers(ctx, f"🗒 Нотатка від {ctx.user['full_name']}:\n{text}")
    return {"ok": True, "note_id": nid}


@tool("my_salary", "Розрахувати мою зарплату за період.",
      {"period": _opt(STR, "Період, напр. 'липень'")},
      domains=["payroll"])
async def my_salary(ctx: Ctx, period: str | None = None):
    d1, d2 = dates.parse_period(period or "")
    rows = await payroll.calculate(d1, d2, user_id=ctx.user["id"])
    if not rows:
        return {"error": "Немає даних за цей період"}
    r = rows[0]
    return {"period": dates.period_title(d1, d2), "rate": r.rate, "days": r.days_worked,
            "regular_hours": r.regular_hours, "extra_hours": r.extra_hours,
            "sick_days": r.sick_days, "sick_pay": round(r.sick_pay, 2),
            "total": r.total, "currency": config.CURRENCY}


@tool("set_reminder", "Створити нагадування для себе.",
      {"when": _req(STR, "Час 'YYYY-MM-DD HH:MM'"),
       "text": _req(STR, "Текст нагадування")},
      domains=["reminders"])
async def set_reminder_employee(ctx: Ctx, when: str, text: str):
    when_norm = when if len(when) > 10 else dates.parse_datetime(when)
    await db.add_reminder(ctx.user["id"], when_norm, text)
    return {"ok": True, "when": when_norm, "text": text}


# =====================================================================
#                     КЕРІВНИК: персонал і групи
# =====================================================================

@tool("find_employee", "Знайти працівника за частиною імені або прізвища.",
      {"name_query": _req(STR, "Частина ПІБ, напр. 'Кравець'")},
      domains=["staff", "approvals", "schedule", "comms", "reports"], manager=True)
async def find_employee(ctx: Ctx, name_query: str):
    found = await db.search_users(name_query)
    return [{"user_id": u["id"], "full_name": u["full_name"], "position": u["position"],
             "group": u.get("group_name") or "—", "rate": u["hourly_rate"],
             "status": u["status"]} for u in found]


@tool("create_group", "Створити групу (відділ).",
      {"name": _req(STR, "Назва групи, напр. 'Підтримка'")},
      domains=["staff"], manager=True)
async def create_group(ctx: Ctx, name: str):
    gid = await db.create_group(name)
    return {"ok": True, "group_id": gid, "name": name}


@tool("list_groups", "Список груп із кількістю людей.", {},
      domains=["staff", "reports", "comms", "schedule"], manager=True)
async def list_groups(ctx: Ctx):
    return [{"id": g["id"], "name": g["name"], "members": g["members"]}
            for g in await db.list_groups()]


@tool("assign_to_group", "Розподілити працівника в групу (шукає по частині імені).",
      {"name_query": _req(STR, "Частина ПІБ працівника"),
       "group_query": _req(STR, "Назва групи")},
      domains=["staff"], manager=True)
async def assign_to_group(ctx: Ctx, name_query: str, group_query: str):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний або відсутній працівник",
                "matches": [u["full_name"] for u in found]}
    group = await db.find_group(group_query)
    if not group:
        gid = await db.create_group(group_query)
        group = {"id": gid, "name": group_query}
    await db.set_user_group(user["id"], group["id"])
    await _send(ctx, user["tg_id"], f"✅ Вас розподілено у групу «{group['name']}».")
    return {"ok": True, "employee": user["full_name"], "group": group["name"]}


@tool("list_employees", "Список працівників (усіх або по групі).",
      {"group": _opt(STR, "Назва групи; порожньо — всі")},
      domains=["staff", "schedule", "comms"], manager=True)
async def list_employees(ctx: Ctx, group: str | None = None):
    gid = None
    if group:
        g = await db.find_group(group)
        if not g:
            return {"error": f"Групу '{group}' не знайдено"}
        gid = g["id"]
    return [{"full_name": u["full_name"], "position": u["position"],
             "group": u.get("group_name") or "—", "rate": u["hourly_rate"]}
            for u in await db.list_users(group_id=gid)]


@tool("set_rate", "Встановити погодинну ставку працівнику.",
      {"name_query": _req(STR, "Частина ПІБ"), "rate": _req(NUM, "Ставка, грн/год")},
      domains=["staff"], manager=True)
async def set_rate(ctx: Ctx, name_query: str, rate: float):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний працівник", "matches": [u["full_name"] for u in found]}
    await db.set_user_rate(user["id"], float(rate))
    return {"ok": True, "employee": user["full_name"], "rate": rate}


@tool("set_position", "Призначити або змінити посаду працівнику.",
      {"name_query": _req(STR, "Частина ПІБ"),
       "position": _req(STR, "Назва посади, напр. 'спеціаліст'")},
      domains=["staff"], manager=True)
async def set_position(ctx: Ctx, name_query: str, position: str):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний працівник", "matches": [u["full_name"] for u in found]}
    await db.execute("UPDATE users SET position = ? WHERE id = ?", (position.strip(), user["id"]))
    return {"ok": True, "employee": user["full_name"], "position": position.strip()}


@tool("fire_employee", "Позначити працівника як звільненого (деактивувати).",
      {"name_query": _req(STR, "Частина ПІБ")},
      domains=["staff"], manager=True)
async def fire_employee(ctx: Ctx, name_query: str):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний працівник", "matches": [u["full_name"] for u in found]}
    await db.set_user_status(user["id"], "fired")
    return {"ok": True, "employee": user["full_name"], "status": "fired"}


# =====================================================================
#                     КЕРІВНИК: заявки та нотатки
# =====================================================================

@tool("list_pending_requests", "Заявки, що очікують рішення.", {},
      domains=["approvals"], manager=True)
async def list_pending_requests(ctx: Ctx):
    rows = await db.list_requests(status="pending")
    return [{"request_id": r["id"], "employee": r["full_name"], "kind": r["kind"],
             "from": r["date_from"], "to": r["date_to"], "comment": r["comment"],
             "group": r.get("group_name") or "—"} for r in rows]


@tool("approve_request", "Схвалити заявку за її номером.",
      {"request_id": _req(NUM, "Номер заявки")},
      domains=["approvals"], manager=True)
async def approve_request(ctx: Ctx, request_id: int):
    r = await db.get_request(int(request_id))
    if not r:
        return {"error": "Заявку не знайдено"}
    await db.decide_request(r["id"], "approved", ctx.tg_id)
    if r["kind"] == "extra_shift":
        await db.add_shift(r["user_id"], r["date_from"], config.SHIFT_NORM_HOURS, "extra",
                           comment="Погоджена додаткова зміна")
    kind_ua = {"dayoff": "вихідний", "sick": "лікарняний", "extra_shift": "додаткову зміну"}
    await _send(ctx, r["tg_id"],
                f"✅ Керівник схвалив вашу заявку #{r['id']} на {kind_ua.get(r['kind'], r['kind'])} "
                f"({dates.human(r['date_from'])} — {dates.human(r['date_to'])}).")
    return {"ok": True, "request_id": r["id"], "employee": r["full_name"], "status": "approved"}


@tool("reject_request", "Відхилити заявку.",
      {"request_id": _req(NUM, "Номер заявки"), "reason": _opt(STR, "Причина відмови")},
      domains=["approvals"], manager=True)
async def reject_request(ctx: Ctx, request_id: int, reason: str | None = None):
    r = await db.get_request(int(request_id))
    if not r:
        return {"error": "Заявку не знайдено"}
    await db.decide_request(r["id"], "rejected", ctx.tg_id)
    await _send(ctx, r["tg_id"],
                f"❌ Керівник відхилив вашу заявку #{r['id']}."
                + (f"\nПричина: {reason}" if reason else ""))
    return {"ok": True, "request_id": r["id"], "employee": r["full_name"], "status": "rejected"}


@tool("list_notes", "Нотатки від працівників.",
      {"unread_only": _opt(BOOL, "Лише непрочитані (за замовчуванням так)")},
      domains=["approvals"], manager=True)
async def list_notes_tool(ctx: Ctx, unread_only: bool = True):
    rows = await db.list_notes(unread_only=unread_only)
    await db.mark_notes_read()
    return [{"employee": n["full_name"], "text": n["text"], "created_at": n["created_at"]}
            for n in rows]


# =====================================================================
#                     КЕРІВНИК: графік і заміни
# =====================================================================

@tool("mark_absence", "Відмітити, що працівник не виходить на роботу в певний день.",
      {"name_query": _req(STR, "Частина ПІБ, напр. 'Кравець'"),
       "day": _req(STR, "Дата YYYY-MM-DD"),
       "reason": _opt(STR, "Причина")},
      domains=["schedule"], manager=True)
async def mark_absence(ctx: Ctx, name_query: str, day: str, reason: str | None = None):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний працівник", "matches": [u["full_name"] for u in found]}
    d = dates.parse_date(day) or day
    await db.add_absence(user["id"], d, reason, ctx.tg_id)
    await _send(ctx, user["tg_id"],
                f"ℹ️ Керівник відмітив, що ви не виходите на роботу {dates.human(d)}."
                + (f" Причина: {reason}" if reason else ""))
    return {"ok": True, "employee": user["full_name"], "day": d,
            "group": user.get("group_name") or "—",
            "hint": "Запитай керівника, чи шукати заміну на цей день"}


@tool("find_replacement",
      "Підібрати заміну на день: обирає працівника з НАЙМЕНШОЮ кількістю годин у базі "
      "і сам пише йому в Telegram пропозицію вийти.",
      {"day": _req(STR, "Дата YYYY-MM-DD"),
       "group": _opt(STR, "Група, у межах якої шукати"),
       "exclude_name": _opt(STR, "Кого замінюємо (виключити з пошуку)")},
      domains=["schedule"], manager=True)
async def find_replacement(ctx: Ctx, day: str, group: str | None = None,
                           exclude_name: str | None = None):
    d = dates.parse_date(day) or day

    gid = None
    if group:
        g = await db.find_group(group)
        gid = g["id"] if g else None

    absent = None
    if exclude_name:
        absent, _ = await _resolve_user(exclude_name)
        if absent and gid is None and absent.get("group_id"):
            gid = absent["group_id"]   # шукаємо в тій самій групі

    candidates = await staffing.rank_candidates(
        d, group_id=gid, exclude_user_id=absent["id"] if absent else None
    )
    if not candidates:
        return {"error": "Вільних кандидатів на цей день немає"}

    best = candidates[0]
    await db.add_cover_offer(best["user_id"], absent["id"] if absent else None, d)
    text = (
        f"🔁 Пропозиція підміни на {dates.human(d)}"
        + (f" (замість {absent['full_name']})" if absent else "")
        + f".\nУ вас найменше годин цього місяця ({best['hours_month']} год), тому пропонуємо вам.\n"
          "Відповідайте «так, можу» або «ні, не можу»."
    )
    sent = await _send(ctx, best["tg_id"], text)
    return {"ok": True, "chosen": best["full_name"], "hours_month": best["hours_month"],
            "group": best["group_name"], "message_sent": sent,
            "other_candidates": [f"{c['full_name']} ({c['hours_month']} год)"
                                 for c in candidates[1:4]]}


@tool("log_shift_for", "Записати зміну працівнику (за нього).",
      {"name_query": _req(STR, "Частина ПІБ"),
       "day": _req(STR, "Дата YYYY-MM-DD"),
       "hours": _req(NUM, "Годин"),
       "kind": _opt(STR, "'regular' або 'extra'")},
      domains=["schedule"], manager=True)
async def log_shift_for(ctx: Ctx, name_query: str, day: str, hours: float,
                        kind: str = "regular"):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний працівник", "matches": [u["full_name"] for u in found]}
    d = dates.parse_date(day) or day
    await db.add_shift(user["id"], d, float(hours), "extra" if kind == "extra" else "regular")
    return {"ok": True, "employee": user["full_name"], "day": d, "hours": hours, "kind": kind}


@tool("schedule_overview", "Навантаження команди за період: години та кількість змін по людях.",
      {"period": _opt(STR, "Період, напр. 'липень', 'цей тиждень'"),
       "group": _opt(STR, "Група")},
      domains=["schedule"], manager=True)
async def schedule_overview(ctx: Ctx, period: str | None = None, group: str | None = None):
    d1, d2 = dates.parse_period(period or "")
    gid = None
    if group:
        g = await db.find_group(group)
        gid = g["id"] if g else None
    rows = await staffing.workload(d1, d2, group_id=gid)
    absences = await db.absences_between(d1, d2)
    return {"period": dates.period_title(d1, d2), "workload": rows,
            "absences": [{"day": a["day"], "employee": a["full_name"]} for a in absences]}


# =====================================================================
#                     КЕРІВНИК: звіти (файли)
# =====================================================================

@tool("report_file", "Сформувати і надіслати керівнику звіт по персоналу у файлі Excel.",
      {"period": _opt(STR, "Період, напр. 'липень', 'минулий тиждень'"),
       "group": _opt(STR, "Група; порожньо — вся фірма")},
      domains=["reports"], manager=True)
async def report_file(ctx: Ctx, period: str | None = None, group: str | None = None):
    d1, d2 = dates.parse_period(period or "")
    gid = None
    if group:
        g = await db.find_group(group)
        if not g:
            return {"error": f"Групу '{group}' не знайдено"}
        gid = g["id"]

    path = await reports.build_report(d1, d2, group_id=gid)
    rows = await payroll.calculate(d1, d2, group_id=gid)
    await ctx.bot.send_document(
        ctx.tg_id, FSInputFile(path, filename=os.path.basename(path)),
        caption=f"📊 Звіт за {dates.period_title(d1, d2)}"
                + (f" · група «{group}»" if group else " · вся фірма"),
    )
    return {"ok": True, "file_sent": True, "period": dates.period_title(d1, d2),
            "employees": len(rows),
            "total_hours": round(sum(r.total_hours for r in rows), 2),
            "total_payroll": round(sum(r.total for r in rows), 2)}


@tool("payroll_file", "Сформувати бланк для перевірки зарплати (Excel з формулами) і надіслати.",
      {"period": _opt(STR, "Період, напр. 'липень'"),
       "group": _opt(STR, "Група; порожньо — вся фірма")},
      domains=["reports"], manager=True)
async def payroll_file(ctx: Ctx, period: str | None = None, group: str | None = None):
    d1, d2 = dates.parse_period(period or "")
    gid = None
    if group:
        g = await db.find_group(group)
        if not g:
            return {"error": f"Групу '{group}' не знайдено"}
        gid = g["id"]

    path = await reports.build_payroll_sheet(d1, d2, group_id=gid)
    rows = await payroll.calculate(d1, d2, group_id=gid)
    await ctx.bot.send_document(
        ctx.tg_id, FSInputFile(path, filename=os.path.basename(path)),
        caption=f"🧾 Бланк зарплати за {dates.period_title(d1, d2)}. "
                f"Жовті комірки можна правити — суми перерахуються формулами.",
    )
    return {"ok": True, "file_sent": True, "employees": len(rows),
            "total_payroll": round(sum(r.total for r in rows), 2),
            "currency": config.CURRENCY}


# =====================================================================
#                     КЕРІВНИК: комунікації
# =====================================================================

@tool("message_employee", "Надіслати повідомлення конкретному працівнику.",
      {"name_query": _req(STR, "Частина ПІБ"), "text": _req(STR, "Текст повідомлення")},
      domains=["comms"], manager=True)
async def message_employee(ctx: Ctx, name_query: str, text: str):
    user, found = await _resolve_user(name_query)
    if not user:
        return {"error": "Неоднозначний працівник", "matches": [u["full_name"] for u in found]}
    ok = await _send(ctx, user["tg_id"], f"📢 Повідомлення від керівника:\n{text}")
    return {"ok": ok, "employee": user["full_name"]}


@tool("broadcast", "Надіслати повідомлення всій групі або всій фірмі.",
      {"text": _req(STR, "Текст повідомлення"),
       "group": _opt(STR, "Назва групи; порожньо — всім працівникам")},
      domains=["comms"], manager=True)
async def broadcast(ctx: Ctx, text: str, group: str | None = None):
    gid = None
    label = "всій фірмі"
    if group:
        g = await db.find_group(group)
        if not g:
            return {"error": f"Групу '{group}' не знайдено"}
        gid, label = g["id"], f"групі «{g['name']}»"

    users = await db.list_users(group_id=gid)
    header = f"📢 Оголошення для {label}:\n"
    delivered = 0
    for u in users:
        if u["tg_id"] == ctx.tg_id:
            continue
        if await _send(ctx, u["tg_id"], header + text):
            delivered += 1
    return {"ok": True, "target": label, "delivered": delivered, "total": len(users)}


@tool("set_reminder_manager", "Створити нагадування для керівника.",
      {"when": _req(STR, "Час 'YYYY-MM-DD HH:MM'"), "text": _req(STR, "Текст")},
      domains=["reminders", "comms", "schedule"], manager=True)
async def set_reminder_manager(ctx: Ctx, when: str, text: str):
    when_norm = when if len(when) > 10 else dates.parse_datetime(when)
    await db.add_reminder(ctx.user["id"], when_norm, text)
    return {"ok": True, "when": when_norm, "text": text}
