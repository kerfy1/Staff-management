"""Конфігурація бота. Всі значення читаються з .env"""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID керівників через кому: MANAGER_IDS=123456789,987654321
MANAGER_IDS = {
    int(x) for x in os.getenv("MANAGER_IDS", "").replace(" ", "").split(",") if x.strip()
}

# --- OpenRouter (https://openrouter.ai/docs/quickstart) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")
APP_URL = os.getenv("APP_URL", "https://example.com")      # HTTP-Referer для рейтингів OpenRouter
APP_NAME = os.getenv("APP_NAME", "Staff Management Bot")   # X-Title

# --- База / час ---
DB_PATH = os.getenv("DB_PATH", "staff_bot.db")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Kyiv"))

# --- Правила оплати ---
DEFAULT_HOURLY_RATE = float(os.getenv("DEFAULT_HOURLY_RATE", "120"))   # грн/год за замовчуванням
SHIFT_NORM_HOURS = float(os.getenv("SHIFT_NORM_HOURS", "8"))           # норма годин у зміні
EXTRA_SHIFT_MULTIPLIER = float(os.getenv("EXTRA_SHIFT_MULTIPLIER", "1.5"))  # коеф. додаткової зміни
SICK_PAY_RATE = float(os.getenv("SICK_PAY_RATE", "0.7"))               # % оплати лікарняного
CURRENCY = os.getenv("CURRENCY", "грн")

# --- Технічне ---
HISTORY_DEPTH = int(os.getenv("HISTORY_DEPTH", "12"))   # скільки повідомлень діалогу пам'ятає агент
MAX_TOOL_STEPS = int(os.getenv("MAX_TOOL_STEPS", "6"))  # ліміт кроків tool-calling
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")


def is_manager(tg_id: int) -> bool:
    return tg_id in MANAGER_IDS
