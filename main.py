"""Telegram-бот управління персоналом. Точка входу. Файл: main.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import config
import db
from ai import agent, tools
from handlers import buttons
from handlers import keyboards as kb
from handlers import menus
from services import dates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("staff_bot")

dp = Dispatcher()
chat = Router()   # вільний текст → AI-агент (реєструється ОСТАННІМ)


async def build_ctx(bot: Bot, tg_id: int) -> tools.Ctx:
    user = await db.get_user_by_tg(tg_id)
    return tools.Ctx(bot=bot, user=user, tg_id=tg_id, is_manager=config.is_manager(tg_id))


@chat.message(CommandStart())
async def cmd_start(message: Message):
    tg_id = message.from_user.id
    user = await db.get_user_by_tg(tg_id)
    is_mgr = config.is_manager(tg_id)

    if user and user["status"] == "active":
        await message.answer(
            f"Вітаю, {user['full_name']}! 👋",
            reply_markup=kb.menu_for(is_mgr),
        )
        await message.answer(menus.MANAGER_MENU if is_mgr else menus.EMPLOYEE_MENU)
        return

    if user and user["status"] == "pending":
        await message.answer("⏳ Ваша реєстрація на підтвердженні в керівника.")
        return

    if is_mgr:
        await message.answer(
            "Вітаю, керівнику! 👋\nВведіть ваше ПІБ і посаду для реєстрації — "
            "напр. «Тоха Сирний, директор»."
        )
    else:
        await message.answer(
            "Вітаю! Ви новий співробітник. 👋\nВведіть ваше ПІБ і посаду — "
            "напр. «Агент Панас, дизайнер»."
        )


@chat.message(Command("menu"))
async def cmd_menu(message: Message):
    is_mgr = config.is_manager(message.from_user.id)
    await message.answer(menus.MANAGER_MENU if is_mgr else menus.EMPLOYEE_MENU,
                         reply_markup=kb.menu_for(is_mgr))


@chat.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(menus.HELP)


@chat.message(Command("reset"))
async def cmd_reset(message: Message):
    await db.clear_history(message.from_user.id)
    await message.answer("Контекст діалогу очищено.")


@chat.message(F.text)
async def on_text(message: Message, bot: Bot):
    tg_id = message.from_user.id
    ctx = await build_ctx(bot, tg_id)

    if ctx.user and ctx.user["status"] == "pending":
        await message.answer("⏳ Ваша реєстрація ще на підтвердженні в керівника.")
        return
    if ctx.user and ctx.user["status"] == "fired":
        await message.answer("Ваш обліковий запис деактивовано.")
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        reply = await agent.handle(ctx, message.text)
    except Exception as e:  # noqa: BLE001
        log.exception("Помилка обробки повідомлення")
        reply = f"Сталася помилка при обробці запиту: {e}"

    # щойно зареєструвався керівник — одразу даємо йому клавіатуру
    fresh = await db.get_user_by_tg(tg_id)
    markup = None
    if fresh and not ctx.user and fresh["status"] == "active":
        markup = kb.menu_for(ctx.is_manager)

    await message.answer(reply, reply_markup=markup)


@chat.message()
async def on_other(message: Message):
    await message.answer("Я розумію лише текст. Напишіть повідомлення словами або скористайтесь меню.")


async def reminder_loop(bot: Bot) -> None:
    """Фоновий цикл: раз на 30 секунд надсилає прострочені нагадування."""
    while True:
        try:
            now = dates.now().strftime("%Y-%m-%d %H:%M")
            for r in await db.due_reminders(now):
                try:
                    await bot.send_message(r["tg_id"], f"⏰ Нагадування: {r['text']}")
                    await db.mark_reminder_sent(r["id"])
                except Exception:  # noqa: BLE001
                    log.warning("Не вдалось надіслати нагадування %s", r["id"])
        except Exception:  # noqa: BLE001
            log.exception("Помилка в циклі нагадувань")
        await asyncio.sleep(30)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не заданий у .env")
    if not config.OPENROUTER_API_KEY:
        raise SystemExit("OPENROUTER_API_KEY не заданий у .env")
    if not config.MANAGER_IDS:
        log.warning("MANAGER_IDS порожній — жоден користувач не буде керівником!")

    await db.init_db()

    # ВАЖЛИВО: кнопки — першим роутером, вільний текст — останнім,
    # інакше catch-all перехопить натискання кнопок.
    dp.include_router(buttons.router)
    dp.include_router(chat)

    bot = Bot(token=config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    asyncio.create_task(reminder_loop(bot))
    log.info("Бот запущено. Модель: %s", config.MODEL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
