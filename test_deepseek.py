"""
Тест подключения к DeepSeek через OpenAI-совместимый API (aitunnel).

Проверяет:
1. Наличие ключа и base_url в .env
2. Реальный запрос к модели deepseek-chat
3. Выводит ответ модели или понятную ошибку

Не требует дополнительных зависимостей (использует только requests).

Запуск:
    python test_deepseek.py
"""
import os
import sys
from pathlib import Path

import requests

# --- Загрузка .env без python-dotenv (чтобы тест работал сразу) ---
def load_env(path: str = ".env") -> dict:
    """Простой парсер .env: KEY=VALUE, поддержка # комментариев и кавычек."""
    env = {}
    env_path = Path(path)
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        env[key] = value
    return env


env = load_env()

# Приоритет ключей: DEEPSEEK_API_KEY -> LLM_API_KEY -> OPENAI_API_KEY
API_KEY = (
    os.getenv("DEEPSEEK_API_KEY")
    or os.getenv("LLM_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or env.get("DEEPSEEK_API_KEY")
    or env.get("LLM_API_KEY")
    or env.get("OPENAI_API_KEY")
)
BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("OPENAI_API_BASE")
    or env.get("LLM_BASE_URL")
    or env.get("OPENAI_API_BASE")
    or "https://api.aitunnel.ru/v1"
)
MODEL = os.getenv("LLM_MODEL") or env.get("LLM_MODEL") or "deepseek-chat"


def main() -> int:
    print("🔌 Проверка подключения к DeepSeek (aitunnel)...")
    print("-" * 60)

    # 1. Проверяем наличие ключа
    if not API_KEY:
        print("❌ Не найден API-ключ в .env")
        print("   Добавьте одну из переменных:")
        print("   DEEPSEEK_API_KEY=sk-...")
        print("   LLM_API_KEY=sk-...")
        print("   OPENAI_API_KEY=sk-...")
        return 1

    # Маскируем ключ для вывода
    masked_key = API_KEY[:8] + "..." + API_KEY[-4:] if len(API_KEY) > 12 else "***"
    print(f"✅ API-ключ найден: {masked_key}")
    print(f"✅ Base URL: {BASE_URL}")
    print(f"✅ Модель:   {MODEL}")

    # 2. Делаем реальный запрос к /chat/completions
    url = BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Ты — ассистент. Отвечай кратко."},
            {"role": "user", "content": "Ответь одним словом: работает ли подключение?"},
        ],
        "temperature": 0.1,
        "max_tokens": 50,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    print("\n⏳ Отправляем тестовый запрос...")
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.exceptions.RequestException as e:
        print(f"❌ Сетевая ошибка: {e}")
        print("   Проверьте доступность LLM_BASE_URL и интернет-соединение.")
        return 1

    if resp.status_code != 200:
        print(f"❌ API вернул HTTP {resp.status_code}:")
        print(resp.text[:500])
        print()
        print("Возможные причины:")
        print("  • Неверный или истёкший API-ключ в .env (401)")
        print("  • Неверный LLM_BASE_URL (404)")
        print("  • Неверное имя модели LLM_MODEL (400)")
        return 1

    data = resp.json()
    try:
        answer = data["choices"][0]["message"]["content"].strip()
        model_used = data.get("model", MODEL)
        usage = data.get("usage", {})
    except (KeyError, IndexError, TypeError):
        print("❌ Неожиданный формат ответа API:")
        print(resp.text[:500])
        return 1

    print("✅ Успех! Ответ от DeepSeek:")
    print("-" * 60)
    print(answer)
    print("-" * 60)
    print(f"ℹ️ Модель: {model_used} | Токенов: {usage.get('total_tokens', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())