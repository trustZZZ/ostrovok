#!/usr/bin/env python3
"""Демо-сценарий одной командой: сбор -> ответы отельера -> поиск.

Зачем нужен: перед защитой и записью видео один прогон показывает всю цепочку
и заодно проверяет, что она живая. Ничего не выдумывает: характеристики
считаются теми же инструментами, что и в проде.

Что делает по шагам:

1. Ставит сбор характеристик для всех отелей (`POST /api/hotels/enrich-all`)
   и ждёт, пока граф закончит считать.
2. Отвечает на вопросы отельеру из inbox. Значения ответов — ИМИТАЦИЯ для
   демо: питомцы, сторона номеров, шумоизоляция и балконы из открытых данных
   не выводятся. В реальном кабинете (`/#/hotelier`) те же ответы вводит
   человек, и характеристика сохраняется с `source=hotelier`.
3. Показывает результат поиска по нескольким запросам с объяснениями.

Запуск (стек должен быть поднят: docker compose up -d):
    docker compose --profile tools run --rm seed python /scripts/demo.py

Полезные флаги: --skip-enrich (данные уже собраны), --timeout 600.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

API_BASE = os.getenv("ROUTELY_API", "http://backend:8000")

# Ответы отельера: первый вариант — «да», второй — «нет», выбор по чётности
# hotel_id. Разнообразие нужно, чтобы в выдаче были разные отели, а не все
# подряд. В реальном разборе ответ читает LLM (llm_client.parse_answer_with_llm),
# без ключа — детерминированное правило «есть "да" -> true».
DEMO_ANSWERS: dict[str, list[str]] = {
    "pet_friendly": [
        "Да, пускаем с небольшими собаками и кошками до 10 кг, доплата 500 рублей",
        "Нет, с животными не принимаем, кроме собак-поводырей",
    ],
    "room_west_windows": [
        "Да, категории «Люкс» и «Полулюкс» на 4-6 этажах выходят окнами на запад",
        "Нет, все номера выходят на восток или во двор",
    ],
    "room_silence": [
        "Да, в номерах шумоизоляция, часть номеров выходит во двор",
        "Нет, шумоизоляции нет, окна выходят на дорогу",
    ],
    "room_balcony": [
        "Да, балконы есть в категориях «Люкс» и «Апартаменты»",
        "Нет, балконов и террас нет",
    ],
}

DEFAULT_QUERIES = [
    "тихий номер с видом на закат недалеко от моря",
    "можно с котом и с балконом",
    "5 минут до пляжа без трассы",
]


def get(path: str) -> object:
    with httpx.Client(timeout=60.0) as client:
        response = client.get(f"{API_BASE}{path}")
        response.raise_for_status()
        return response.json()


def post(path: str, payload: dict | None = None) -> object:
    with httpx.Client(timeout=120.0) as client:
        response = client.post(f"{API_BASE}{path}", json=payload or {})
        response.raise_for_status()
        return response.json()


def step(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def wait_until_stable(sample, *, timeout: float, poll: float = 3.0, stable_rounds: int = 3) -> object:
    """Ждёт, пока число характеристик и вопросов перестанет меняться.

    Признак «граф закончил»: набор строк в БД и очередь вопросов отельеру
    три опроса подряд одинаковы. Фоновые задачи не отдают прогресс, поэтому
    наблюдаем только результат в API.
    """
    deadline = time.time() + timeout
    last = None
    same_rounds = 0
    while time.time() < deadline:
        current = sample()
        print(f"  характеристик: {current[0]}, вопросов отельеру: {current[1]}", flush=True)
        if current == last:
            same_rounds += 1
            if same_rounds >= stable_rounds:
                return current
        else:
            same_rounds = 0
            last = current
        time.sleep(poll)
    print(f"  не дождались стабилизации за {timeout:.0f} с — идём дальше с тем, что есть")
    return last


def snapshot() -> tuple[int, int, tuple[int, ...]]:
    """Состояние данных для определения «граф закончил».

    Одного числа вопросов мало: `node_ask` перед вставкой удаляет pending,
    поэтому очередь может пересоздаться с теми же количеством, но другими id.
    Сравниваем набор id, иначе ждём «стабильности» на середине работы.
    """
    hotels = get("/api/hotels")
    inbox = get("/api/hotelier/inbox")
    total = sum(len(hotel["features"]) for hotel in hotels)
    return total, len(inbox), tuple(sorted(question["id"] for question in inbox))


def answer_inbox(rounds: int = 4) -> int:
    """Отвечает на pending-вопросы демо-значениями.

    Ответы отправляются раундами: пока идёт сбор, другой поток может
    пересоздать очередь вопросов, и часть id станет неактуальной (404).
    Это не ошибка данных — просто повторяем по свежему списку.
    """
    answered = 0
    handled: set[int] = set()
    skipped: set[str] = set()

    for _ in range(rounds):
        inbox = get("/api/hotelier/inbox")
        todo = [question for question in inbox if question["id"] not in handled]
        if not todo:
            break

        progress = 0
        for question in todo:
            handled.add(question["id"])
            key = question["feature_key"]
            variants = DEMO_ANSWERS.get(key)
            if not variants:
                skipped.add(key)
                continue

            answer = variants[question["hotel_id"] % len(variants)]
            try:
                post(
                    f"/api/hotelier/{question['hotel_id']}/answer/{question['id']}",
                    {"answer": answer, "thread_id": question.get("thread_id")},
                )
            except httpx.HTTPStatusError as exc:
                print(f"  вопрос {question['id']} ({key}) уже неактуален: {exc.response.status_code}")
                continue

            answered += 1
            progress += 1
            print(f"  {question['hotel_name'][:28]:<28} {key:<18} -> {answer[:46]}")

        if progress == 0:
            break
        time.sleep(2.0)

    if skipped:
        print(f"  без демо-ответа остались: {', '.join(sorted(skipped))}")
    return answered


def describe(hotel: dict, limit: int = 3) -> str:
    parts = [f"{hotel['name']} (score {hotel['score']:.2f})"]
    explanation = hotel.get("explanation") or ""
    if explanation:
        parts.append(f"    {explanation[:400]}")
    return "\n".join(parts)


def run_search(queries: list[str], limit: int) -> None:
    for query in queries:
        step(f"ПОИСК: {query}")
        result = post("/api/search", {"query": query, "limit": limit})
        intent = result.get("intent") or {}
        recognized = ", ".join(f"{key}={value}" for key, value in intent.items())
        print(f"  распознано ({result.get('intent_source')}): {recognized or 'ничего'}")
        for line in result.get("agent_log") or []:
            print(f"  лог: {line}")
        hotels = result.get("hotels") or []
        if not hotels:
            print("  выдача пуста")
            continue
        for hotel in hotels[:limit]:
            print(describe(hotel))


def main() -> int:
    parser = argparse.ArgumentParser(description="Демо-сценарий Routely целиком")
    parser.add_argument("--skip-enrich", action="store_true", help="не пересобирать характеристики")
    parser.add_argument("--timeout", type=float, default=300.0, help="сколько ждать сбор, секунд")
    parser.add_argument("--limit", type=int, default=3, help="сколько отелей печатать в выдаче")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="свой поисковый запрос (можно повторять); по умолчанию — три демо-запроса",
    )
    args = parser.parse_args()

    queries = args.queries or DEFAULT_QUERIES

    step("ПРОВЕРКА СТЕКА")
    try:
        health = get("/health")
    except Exception as exc:  # noqa: BLE001 - внешний сервис
        print(f"API недоступен ({API_BASE}): {exc}")
        print("Поднимите стек: docker compose up -d")
        return 1
    print(f"  {health}")

    hotels = get("/api/hotels")
    if not hotels:
        print("  в базе нет отелей: сначала выполните сидирование (make up)")
        return 1
    print(f"  отелей в базе: {len(hotels)}")

    if args.skip_enrich:
        print("\n  сбор пропущен (--skip-enrich): используем то, что уже в БД")
    else:
        step("СБОР ХАРАКТЕРИСТИК")
        started = post("/api/hotels/enrich-all")
        print(f"  запущено задач: {started.get('started')}, ждём до {args.timeout:.0f} с")
        wait_until_stable(snapshot, timeout=args.timeout)

    step("КАБИНЕТ ОТЕЛЬЕРА: ИМИТАЦИЯ ОТВЕТОВ")
    answered = answer_inbox()
    if answered:
        wait_until_stable(snapshot, timeout=args.timeout)

    step("СОСТОЯНИЕ ДАННЫХ")
    hotels = get("/api/hotels")
    registry = get("/api/features")
    print(f"  отелей: {len(hotels)}, характеристик в реестре: {len(registry)}")
    for hotel in hotels:
        keys = sorted({feature["key"] for feature in hotel["features"]})
        print(f"  {hotel['name'][:28]:<28} {len(keys)} характеристик")
    stale = get("/api/hotels/stale")
    print(f"  устаревших характеристик (истёк TTL): {len(stale)}")

    run_search(queries, args.limit)

    step("ГОТОВО")
    print("  UI: http://localhost:8080/#/search  (кабинет отельера: /#/hotelier)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
