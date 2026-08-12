"""Агент: спочатку роутер визначає функцію (домен), далі під неї підставляється
власний системний промпт і власний набір інструментів."""
import json
import logging

import config
import db
from ai import client, prompts, tools
from services import dates

log = logging.getLogger(__name__)

EMPLOYEE_DOMAINS = set(prompts.EMPLOYEE)
MANAGER_DOMAINS = set(prompts.MANAGER)
WEEKDAYS_UA = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"]


async def route(text: str, is_manager: bool) -> str:
    """Класифікація наміру → домен (функція)."""
    allowed = MANAGER_DOMAINS if is_manager else EMPLOYEE_DOMAINS
    role = "КЕРІВНИК" if is_manager else "ПРАЦІВНИК"
    try:
        raw = await client.ask(
            prompts.ROUTER,
            f"Роль співрозмовника: {role}\nПовідомлення: {text}\nДомен:",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Роутер недоступний: %s", e)
        return "smalltalk"

    domain = raw.strip().lower().split()[0].strip(".,:\"'") if raw.strip() else "smalltalk"
    return domain if domain in allowed else "smalltalk"


def _context(user: dict | None, is_manager: bool) -> dict:
    now = dates.now()
    return {
        "today": dates.iso(now.date()),
        "weekday": WEEKDAYS_UA[now.weekday()],
        "time": now.strftime("%H:%M"),
        "name": (user or {}).get("full_name", "новий користувач"),
        "role": "керівник" if is_manager else "працівник",
        "group": (user or {}).get("group_name") or "не призначена",
        "user_id": (user or {}).get("id", "—"),
    }


async def handle(ctx: tools.Ctx, text: str) -> str:
    """Обробка одного повідомлення користувача. Повертає текст відповіді."""
    # 1. Незареєстрований → жорстко домен реєстрації
    if ctx.user is None:
        domain = "registration"
        system = prompts.REGISTRATION.format(**_context(None, ctx.is_manager))
        tool_specs = [tools.REGISTRY["register_employee"]["spec"]]
    else:
        domain = await route(text, ctx.is_manager)
        system = prompts.get_prompt(domain, ctx.is_manager).format(
            **_context(ctx.user, ctx.is_manager)
        )
        tool_specs = tools.tools_for(domain, ctx.is_manager)

    log.info("tg=%s domain=%s tools=%s", ctx.tg_id, domain, len(tool_specs))

    history = await db.get_history(ctx.tg_id, config.HISTORY_DEPTH)
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": text})

    reply = ""
    for _ in range(config.MAX_TOOL_STEPS):
        resp = await client.chat(messages, tools=tool_specs or None)
        msg = resp.choices[0].message

        if not msg.tool_calls:
            reply = msg.content or "Не зрозумів запит. Уточніть, будь ласка."
            break

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await tools.dispatch(tc.function.name, args, ctx)
            log.info("tool=%s args=%s -> %s", tc.function.name, args, result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
    else:
        reply = "Забагато кроків обробки. Сформулюйте запит простіше."

    await db.add_history(ctx.tg_id, "user", text)
    await db.add_history(ctx.tg_id, "assistant", reply)
    return reply
