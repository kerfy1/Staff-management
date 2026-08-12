"""Обробники кнопок меню та inline-кнопок. Файл: handlers/buttons.py

Кнопки — це швидкі шорткати. Все, що потребує уточнення (дата, години, текст),
кнопка лише підказує формулювання, а виконує його той самий AI-агент.
"""
import config
import db
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from ai import client, tools
from handlers import keyboards as kb
from services import dates, staffing

router = Router()


async def _ctx(bot: Bot, tg_id: int) -> tools.Ctx:
    user = await db.get_user_by_tg(tg_id)
    return tools.Ctx(bot=bot, user=user, tg_id=tg_id, is_manager=config.is_manager(tg_id))


async def _guard(message: Message) -> dict | None:
    """Перевірка: зареєстрований і підтверджений."""
    user = await db.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("Спершу зареєструйтесь: напишіть своє ПІБ і посаду.")
        return None
    if user["status"] == "pending":
        await message.answer("⏳ Ваша реєстрація ще на підтвердженні в керівника.")
        return None
    if user["status"] == "fired":
        await message.answer("Ваш обліковий запис деактивовано.")
        return None
    return user


# =====================================================================
#                      КНОПКИ ПРАЦІВНИКА
# =====================================================================

@router.message(F.text == kb.B_START)
async def btn_start_shift(message: Message, bot: Bot):
    if not await _guard(message):
        return
    ctx = await _ctx(bot, message.from_user.id)
    res = await tools.start_shift(ctx)
    if res.get("error"):
        await message.answer(f"⚠️ {res['error']}")
    else:
        await message.answer(f"🟢 Зміну розпочато о {res['started_at']}. Гарної роботи!")


@router.message(F.text == kb.B_END)
async def btn_end_shift(message: Message, bot: Bot):
    if not await _guard(message):
        return
    ctx = await _ctx(bot, message.from_user.id)
    res = await tools.end_shift(ctx)
    if res.get("error"):
        await message.answer(f"⚠️ {res['error']}")
    else:
        await message.answer(
            f"🔴 Зміну завершено. {res['from']} — {res['to']}, відпрацьовано {res['hours']} год."
        )


@router.message(F.text == kb.B_HOURS)
async def btn_my_hours(message: Message, bot: Bot):
    if not await _guard(message):
        return
    ctx = await _ctx(bot, message.from_user.id)
    r = await tools.my_hours(ctx)
    await message.answer(
        f"📊 <b>{r['period']}</b>\n"
        f"Днів: {r['days']}\n"
        f"Годин звичайних: {r['regular_hours']}\n"
        f"Годин додаткових: {r['extra_hours']}\n"
        f"Разом: <b>{r['total_hours']}</b> год"
    )


@router.message(F.text == kb.B_SALARY)
async def btn_my_salary(message: Message, bot: Bot):
    if not await _guard(message):
        return
    ctx = await _ctx(bot, message.from_user.id)
    r = await tools.my_salary(ctx)
    if r.get("error"):
        await message.answer(f"⚠️ {r['error']}")
        return
    await message.answer(
        f"💵 <b>{r['period']}</b>\n"
        f"Ставка: {r['rate']} {r['currency']}/год\n"
        f"Годин: {r['regular_hours']} + {r['extra_hours']} додаткових\n"
        f"Лікарняні: {r['sick_days']} дн ({r['sick_pay']} {r['currency']})\n"
        f"Нараховано: <b>{r['total']} {r['currency']}</b>"
    )


@router.message(F.text == kb.B_EXTRA)
async def btn_extra(message: Message):
    if not await _guard(message):
        return
    await message.answer(
        "➕ Напишіть, коли і скільки:\n"
        "<i>напр. «додаткова зміна в суботу, 6 годин»</i>"
    )


@router.message(F.text == kb.B_DAYOFF)
async def btn_dayoff(message: Message):
    if not await _guard(message):
        return
    await message.answer(
        "🏖 На яку дату потрібен вихідний?\n<i>напр. «хочу вихідний 5 серпня»</i>"
    )


@router.message(F.text == kb.B_SICK)
async def btn_sick(message: Message):
    if not await _guard(message):
        return
    await message.answer(
        "🏥 Вкажіть період лікарняного:\n<i>напр. «лікарняний з 10 по 14 серпня»</i>"
    )


@router.message(F.text == kb.B_NOTE)
async def btn_note(message: Message):
    if not await _guard(message):
        return
    await message.answer(
        "📝 Напишіть нотатку — я передам керівнику:\n"
        "<i>напр. «передай керівнику, що зламався принтер»</i>"
    )


# =====================================================================
#                       КНОПКИ КЕРІВНИКА
# =====================================================================

@router.message(F.text == kb.M_GROUPS)
async def btn_groups(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    groups = await tools.list_groups(ctx)
    if not groups:
        await message.answer("Груп ще немає. Напишіть: «створити групу Дизайнери».")
        return
    lines = "\n".join(f"• {g['name']} — {g['members']} осіб" for g in groups)
    await message.answer(f"👥 <b>Групи</b>\n{lines}\n\n<i>«створити групу Х» / «додай Панаса в Дизайнери»</i>")


@router.message(F.text == kb.M_STAFF)
async def btn_staff(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    rows = await tools.list_employees(ctx)
    if not rows:
        await message.answer("Ще немає працівників.")
        return
    lines = "\n".join(
        f"• {u['full_name']} — {u['position'] or '—'} · {u['group']} · {u['rate']} грн/год"
        for u in rows
    )
    await message.answer(f"👤 <b>Персонал</b>\n{lines}")


@router.message(F.text == kb.M_REQUESTS)
async def btn_requests(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    rows = await tools.list_pending_requests(ctx)
    if not rows:
        await message.answer("Немає нових заявок ✅")
        return
    kind_ua = {"dayoff": "🏖 Вихідний", "sick": "🏥 Лікарняний", "extra_shift": "➕ Додаткова зміна"}
    for r in rows:
        await message.answer(
            f"<b>Заявка #{r['request_id']}</b> — {kind_ua.get(r['kind'], r['kind'])}\n"
            f"{r['employee']} ({r['group']})\n"
            f"{dates.human(r['from'])} — {dates.human(r['to'])}\n"
            f"Коментар: {r['comment'] or '—'}",
            reply_markup=kb.request_kb(r["request_id"]),
        )


@router.message(F.text == kb.M_NOTES)
async def btn_notes(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    rows = await tools.list_notes_tool(ctx)
    if not rows:
        await message.answer("Нових нотаток немає 📭")
        return
    lines = "\n\n".join(f"🗒 <b>{n['employee']}</b>\n{n['text']}" for n in rows)
    await message.answer(lines)


@router.message(F.text == kb.M_REPORT)
async def btn_report(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    await message.answer("Формую звіт за поточний місяць…")
    res = await tools.report_file(ctx)
    if res.get("error"):
        await message.answer(f"⚠️ {res['error']}")
        return
    await message.answer(
        f"Працівників: {res['employees']} · Годин: {res['total_hours']} · "
        f"Нараховано: {res['total_payroll']} грн\n"
        f"<i>Інший період: «звіт за липень» або «звіт по групі Дизайнери за минулий тиждень»</i>"
    )


@router.message(F.text == kb.M_PAYROLL)
async def btn_payroll(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    await message.answer("Формую бланк зарплати за поточний місяць…")
    res = await tools.payroll_file(ctx)
    if res.get("error"):
        await message.answer(f"⚠️ {res['error']}")
        return
    await message.answer(
        f"Разом до виплати: <b>{res['total_payroll']} {res['currency']}</b>\n"
        f"<i>Інший період: «бланк зарплати за липень»</i>"
    )


@router.message(F.text == kb.M_REPLACE)
async def btn_replace(message: Message):
    await message.answer(
        "🔁 На яку дату шукати заміну?\n"
        "<i>напр. «знайди заміну на завтра» або «Панас завтра не виходить»</i>\n"
        "Агент сам обере людину з найменшою кількістю годин і напише їй."
    )


@router.message(F.text == kb.M_OPTIMIZE)
async def btn_optimize(message: Message, bot: Bot):
    ctx = await _ctx(bot, message.from_user.id)
    d1, d2 = dates.parse_period("")
    load = await staffing.workload(d1, d2)
    if not load:
        await message.answer("Ще немає даних для аналізу.")
        return
    await message.answer("🤖 Аналізую навантаження…")

    facts = "\n".join(
        f"- {r['full_name']} ({r['group_name']}): {r['hours']} год, змін {r['shifts']}"
        for r in load
    )
    system = (
        "Ти — аналітик з планування персоналу. Отримуєш навантаження команди за період. "
        "Українською, стисло: 1) хто перевантажений, 2) хто недовантажений, "
        "3) 2-3 конкретні рекомендації з перерозподілу змін. Не вигадуй даних поза списком. "
        "Без вступів, одразу по суті, до 120 слів."
    )
    try:
        answer = await client.ask(
            system, f"Період: {dates.period_title(d1, d2)}\nДані:\n{facts}"
        )
    except Exception as e:  # noqa: BLE001
        answer = f"Не вдалось звернутись до моделі: {e}"
    await message.answer(f"🤖 <b>Оптимізація</b>\n{answer}")


# =====================================================================
#                          INLINE-КНОПКИ
# =====================================================================

@router.callback_query(F.data.startswith("reg:"))
async def cb_registration(cb: CallbackQuery, bot: Bot):
    if not config.is_manager(cb.from_user.id):
        await cb.answer("Лише для керівника", show_alert=True)
        return

    _, action, uid = cb.data.split(":")
    user = await db.get_user(int(uid))
    if not user:
        await cb.answer("Користувача не знайдено", show_alert=True)
        return

    if action == "no":
        await db.set_user_status(user["id"], "fired")
        await cb.message.edit_text(f"❌ Реєстрацію відхилено: {user['full_name']}")
        try:
            await bot.send_message(user["tg_id"], "❌ Керівник відхилив вашу реєстрацію.")
        except Exception:  # noqa: BLE001
            pass
        await cb.answer()
        return

    groups = await db.list_groups()
    if not groups:
        await db.set_user_status(user["id"], "active")
        await cb.message.edit_text(
            f"✅ Прийнято: {user['full_name']}.\nГруп ще немає — створіть: «створити групу Дизайнери»."
        )
        await bot.send_message(user["tg_id"], "✅ Реєстрацію підтверджено!",
                               reply_markup=kb.employee_menu())
        await cb.answer()
        return

    await cb.message.edit_text(
        f"✅ Прийнято: {user['full_name']}\nУ яку групу розподілити?",
        reply_markup=kb.groups_kb(user["id"], groups),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("grp:"))
async def cb_group(cb: CallbackQuery, bot: Bot):
    if not config.is_manager(cb.from_user.id):
        await cb.answer("Лише для керівника", show_alert=True)
        return

    _, uid, gid = cb.data.split(":")
    user = await db.get_user(int(uid))
    if not user:
        await cb.answer("Користувача не знайдено", show_alert=True)
        return

    await db.set_user_status(user["id"], "active")
    group_name = "без групи"
    if int(gid) > 0:
        await db.set_user_group(user["id"], int(gid))
        g = await db.fetch_one("SELECT name FROM groups WHERE id = ?", (int(gid),))
        group_name = g["name"] if g else "—"

    await cb.message.edit_text(f"✅ {user['full_name']} → група «{group_name}»")
    await bot.send_message(
        user["tg_id"],
        f"✅ Реєстрацію підтверджено! Вас додано до групи «{group_name}».",
        reply_markup=kb.employee_menu(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("req:"))
async def cb_request(cb: CallbackQuery, bot: Bot):
    if not config.is_manager(cb.from_user.id):
        await cb.answer("Лише для керівника", show_alert=True)
        return

    _, action, rid = cb.data.split(":")
    ctx = await _ctx(bot, cb.from_user.id)
    if action == "ok":
        res = await tools.approve_request(ctx, int(rid))
        mark = "✅ Схвалено"
    else:
        res = await tools.reject_request(ctx, int(rid))
        mark = "❌ Відхилено"

    if res.get("error"):
        await cb.answer(res["error"], show_alert=True)
        return

    await cb.message.edit_text(f"{cb.message.text}\n\n{mark} — {res['employee']}")
    await cb.answer()
