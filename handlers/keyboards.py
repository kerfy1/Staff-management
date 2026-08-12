"""Клавіатури. Файл: handlers/keyboards.py"""
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

# ---------- тексти кнопок (використовуються і в хендлерах) ----------
# працівник
B_START = "🟢 Почати зміну"
B_END = "🔴 Завершити зміну"
B_EXTRA = "➕ Додаткова зміна"
B_HOURS = "📊 Мої години"
B_DAYOFF = "🏖 Вихідний"
B_SICK = "🏥 Лікарняний"
B_NOTE = "📝 Нотатка керівнику"
B_SALARY = "💵 Моя зарплата"

# керівник
M_GROUPS = "👥 Групи"
M_REQUESTS = "✅ Заявки"
M_REPORT = "📊 Звіт"
M_PAYROLL = "💰 Зарплата"
M_OPTIMIZE = "🤖 Оптимізація"
M_REPLACE = "🔁 Знайти заміну"
M_NOTES = "📨 Нотатки"
M_STAFF = "👤 Персонал"


def employee_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=B_START), KeyboardButton(text=B_END)],
            [KeyboardButton(text=B_EXTRA), KeyboardButton(text=B_HOURS)],
            [KeyboardButton(text=B_DAYOFF), KeyboardButton(text=B_SICK)],
            [KeyboardButton(text=B_NOTE), KeyboardButton(text=B_SALARY)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Або просто напишіть текстом…",
    )


def manager_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=M_GROUPS), KeyboardButton(text=M_REQUESTS)],
            [KeyboardButton(text=M_REPORT), KeyboardButton(text=M_PAYROLL)],
            [KeyboardButton(text=M_OPTIMIZE), KeyboardButton(text=M_REPLACE)],
            [KeyboardButton(text=M_NOTES), KeyboardButton(text=M_STAFF)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Або напишіть: «звіт за липень»…",
    )


def menu_for(is_manager: bool) -> ReplyKeyboardMarkup:
    return manager_menu() if is_manager else employee_menu()


# ---------- inline ----------

def registration_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Прийняти", callback_data=f"reg:ok:{user_id}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reg:no:{user_id}"),
    ]])


def groups_kb(user_id: int, groups: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=g["name"], callback_data=f"grp:{user_id}:{g['id']}")]
            for g in groups]
    rows.append([InlineKeyboardButton(text="— Без групи —",
                                      callback_data=f"grp:{user_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Схвалити", callback_data=f"req:ok:{request_id}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"req:no:{request_id}"),
    ]])
