import json
from app.config import settings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

def get_llm():
    """Инициализирует DeepSeek через OpenAI-совместимый клиент."""
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        openai_api_key=settings.llm_api_key or "dummy-key",
        openai_api_base=settings.LLM_BASE_URL,
        temperature=0.1, # Низкая температура для стабильного JSON и логики
        # Явный таймаут обязателен: по умолчанию SDK ждёт ответа до 10 минут
        # и повторяет запрос. Зависший вызов блокировал POST /answer, и ответ
        # отельера не попадал в БД (проверено на 12 отелях, см. HANDOFF №19).
        timeout=settings.LLM_TIMEOUT_S,
        max_retries=1,
        model_kwargs={"response_format": {"type": "json_object"}}  # Форсируем JSON
    )

async def generate_questions(conflicts: list[dict], features: dict) -> list[dict]:
    """Генерирует вопросы для отельера на основе найденных конфликтов."""
    if not settings.llm_enabled:
        return [{
            "id": "q_mock_1",
            "feature_key": "noise_level_verified",
            "question": "Мы заметили повышенный уровень шума по данным OSM. Подтверждаете ли вы, что в отеле есть шумоизолированные окна или тихий внутренний двор?",
            "expected_type": "boolean"
        }]

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Ты — агент сервиса бронирования отелей. Твоя задача: найти противоречия в данных и сформулировать 1-2 кратких, вежливых вопроса для отельера, чтобы уточнить информацию. Ответь строго в формате JSON массива объектов с полями: id, feature_key, question, expected_type (string|boolean|number)."),
        ("human", "Конфликты: {conflicts}\nТекущие данные: {features}")
    ])
    
    try:
        response = await llm.ainvoke(prompt.format(conflicts=json.dumps(conflicts, ensure_ascii=False), features=json.dumps(features, ensure_ascii=False)))
        # DeepSeek иногда оборачивает JSON в markdown, чистим его
        clean_json = response.content.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Ошибка LLM при генерации вопросов: {e}. Возвращаем fallback.")
        return [{"id": "q_fallback", "feature_key": "manual_check", "question": "Пожалуйста, подтвердите актуальность характеристик отеля.", "expected_type": "string"}]

async def parse_answer_with_llm(question: str, raw_answer: str, feature_key: str) -> dict:
    """Парсит свободный текст ответа отельера в структурированное значение."""
    if not settings.llm_enabled:
        return {"value": True if "да" in raw_answer.lower() else raw_answer, "confidence": 0.95}

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Извлеки из ответа отельера конкретное значение для характеристики '{feature_key}'. Верни JSON с полями: 'value' (строка, число или булево) и 'confidence' (float от 0.0 до 1.0)."),
        ("human", "Вопрос был: {question}\nОтвет отельера: {raw_answer}")
    ])
    
    try:
        response = await llm.ainvoke(prompt.format(feature_key=feature_key, question=question, raw_answer=raw_answer))
        clean_json = response.content.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Ошибка LLM при парсинге ответа: {e}.")
        return {"value": raw_answer, "confidence": 0.5}