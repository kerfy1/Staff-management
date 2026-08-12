"""Клієнт OpenRouter.

Docs: https://openrouter.ai/docs/quickstart
      https://openrouter.ai/docs/client-sdks/overview
OpenRouter сумісний з OpenAI SDK — достатньо змінити base_url і ключ.
"""
from openai import AsyncOpenAI

import config

client = AsyncOpenAI(
    base_url=config.OPENROUTER_BASE_URL,
    api_key=config.OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": config.APP_URL,   # опціонально: рейтинги на openrouter.ai
        "X-Title": config.APP_NAME,
    },
)


async def chat(messages: list[dict], tools: list[dict] | None = None,
               temperature: float = 0.2, model: str | None = None):
    kwargs = {
        "model": model or config.MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return await client.chat.completions.create(**kwargs)


async def ask(system: str, user: str, temperature: float = 0.0) -> str:
    """Простий одноразовий запит без інструментів (для роутера/класифікації)."""
    resp = await chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()