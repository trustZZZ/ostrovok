"""
Агентный граф на LangGraph.

Поток:
geo → open_data → conflicts → [ask → wait → parse] → finalize → END

Узел `wait` использует langgraph.types.interrupt для human-in-the-loop.
"""
from typing import TypedDict, Any, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt


class AgentState(TypedDict):
    hotel_id: int
    features: dict[str, Any]
    pending_features: list[str]
    questions: list[dict]
    conflicts: list[dict]
    log: list[str]
    answers: dict | None


async def node_geo(state: AgentState) -> dict:
    """
    Запуск GIS-инструментов: sunset_view, noise_score, walk_to_sea.
    Это параллелизуемые вычисления по геоданным.
    """
    from app.tools.sunset_view import compute_sunset_view
    from app.tools.noise_score import compute_noise_score
    from app.tools.walk_to_sea import compute_walk_to_sea
    
    hotel = await get_hotel(state["hotel_id"])
    features = {}
    
    # Sunset view (ключевая фича!)
    features["sunset_view"] = compute_sunset_view(
        hotel_lon=hotel.lon,
        hotel_lat=hotel.lat,
        total_floors=hotel.floors,
        dem_path=settings.DEM_PATH,
        buildings_gdf=await load_buildings(),
    )
    
    # Noise score
    features["noise_score"] = compute_noise_score(
        hotel_geom=hotel.geom,
        osm_layers=await load_osm_layers(),
    )
    
    # Walk to sea
    features["walk_to_sea"] = compute_walk_to_sea(
        hotel_lon=hotel.lon,
        hotel_lat=hotel.lat,
        dem_path=settings.DEM_PATH,
    )
    
    return {
        "features": {**state.get("features", {}), **features},
        "log": state["log"] + [
            f"🛰️ sunset_view: visible={features['sunset_view'].visible}",
            f"🤫 noise_score: {features['noise_score']['score']}/100",
            f"🚶 walk_to_sea: {features['walk_to_sea']['minutes']} мин",
        ],
    }


async def node_open_data(state: AgentState) -> dict:
    """
    Загрузка данных из открытых API: Wikidata, Open-Meteo, OpenAQ, OpenCellID.
    Все запросы асинхронные через httpx.
    """
    hotel = await get_hotel(state["hotel_id"])
    features = dict(state.get("features", {}))
    
    # Wikidata — историческая справка
    features["wikidata_history"] = await fetch_wikidata(hotel.name, hotel.lat, hotel.lon)
    
    # Open-Meteo — климат
    features["weather"] = await fetch_weather(hotel.lat, hotel.lon)
    
    # OpenAQ — качество воздуха
    features["air_quality"] = await fetch_air_quality(hotel.lat, hotel.lon)
    
    # OpenCellID — покрытие связи
    features["cell_coverage"] = await fetch_cell_coverage(hotel.lat, hotel.lon)
    
    return {
        "features": features,
        "log": state["log"] + [
            "🏛️ wikidata: загружено",
            "☀️ weather: загружено",
            "🌿 air_quality: загружено",
            "📶 cell_coverage: загружено",
        ],
    }


async def node_conflicts(state: AgentState) -> dict:
    """
    LLM-агент ищет противоречия между источниками.
    Например: noise_score=70, но в карточке 'тихий район'.
    """
    features = state["features"]
    
    # Простая логика конфликтов (без LLM для демо)
    conflicts = []
    
    # Пример: если noise_score > 50, но отель позиционируется как тихий
    noise = features.get("noise_score", {}).get("score", 0)
    if noise > 50:
        conflicts.append({
            "type": "noise_vs_positioning",
            "severity": "medium",
            "message": f"Шум {noise}/100, но отель может позиционироваться как тихий",
        })
    
    # Пример: sunset_view не виден, но фасад на запад
    sunset = features.get("sunset_view", {})
    if not sunset.get("visible", True):
        conflicts.append({
            "type": "sunset_vs_facade",
            "severity": "low",
            "message": "Фасад на запад, но закат не виден (здания перекрывают)",
        })
    
    questions = []
    if conflicts:
        # LLM формулирует вопросы по конфликтам
        questions = await generate_questions(conflicts, features)
    
    return {
        "conflicts": conflicts,
        "questions": questions,
        "log": state["log"] + [
            f"⚠️ Найдено конфликтов: {len(conflicts)}",
            f"❓ Сформировано вопросов: {len(questions)}",
        ],
    }


async def node_ask(state: AgentState) -> dict:
    """Формулирует вопросы для отельера."""
    # Вопросы уже сформированы в node_conflicts
    return {"log": state["log"] + ["📋 Вопросы отправлены отельеру"]}


async def node_wait(state: AgentState) -> dict:
    """
    Узел ожидания ответа. Граф останавливается здесь через interrupt(),
    пока отельер не ответит через UI.
    """
    answer = interrupt({
        "type": "hotelier_questions",
        "questions": state["questions"],
        "hotel_id": state["hotel_id"],
    })
    return {"answers": answer}


async def node_parse(state: AgentState) -> dict:
    """
    LLM парсит свободный ответ отельера в структурированный JSON.
    """
    answers = state.get("answers", {})
    features = dict(state.get("features", {}))
    
    for question in state["questions"]:
        raw_answer = answers.get(question["id"], "")
        if raw_answer:
            # LLM парсинг
            parsed = await parse_answer_with_llm(
                question=question["question"],
                raw_answer=raw_answer,
                feature_key=question["feature_key"],
            )
            features[question["feature_key"]] = {
                "value": parsed,
                "source": "hotelier",
                "confidence": 0.92,
            }
    
    return {
        "features": features,
        "log": state["log"] + ["🤖 Ответы отельера распарсены LLM"],
    }


async def node_finalize(state: AgentState) -> dict:
    """
    Пересчёт confidence, запись всех фич в БД.
    """
    features = state["features"]
    
    # Сохраняем в БД
    for key, value in features.items():
        await save_feature(state["hotel_id"], key, value)
    
    return {
        "log": state["log"] + [
            f"✅ Сохранено {len(features)} характеристик в БД",
        ],
    }


def build_graph():
    """Собирает агентный граф."""
    g = StateGraph(AgentState)
    
    g.add_node("geo", node_geo)
    g.add_node("open_data", node_open_data)
    g.add_node("conflicts", node_conflicts)
    g.add_node("ask", node_ask)
    g.add_node("wait", node_wait)
    g.add_node("parse", node_parse)
    g.add_node("finalize", node_finalize)
    
    g.set_entry_point("geo")
    g.add_edge("geo", "open_data")
    g.add_edge("open_data", "conflicts")
    g.add_conditional_edges(
        "conflicts",
        lambda s: "ask" if s.get("questions") else "finalize",
    )
    g.add_edge("ask", "wait")
    g.add_edge("wait", "parse")
    g.add_edge("parse", "finalize")
    g.add_edge("finalize", END)
    
    return g.compile(checkpointer=MemorySaver())


# Глобальный инстанс графа
agent_graph = build_graph()
