"""
Агентный граф на LangGraph.
Поток: geo → open_data → conflicts → [ask → wait → parse] → finalize → END
"""
from typing import TypedDict, Any, Optional
from dataclasses import asdict
from shapely.geometry import Point
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from app.config import settings
from app.llm_utils import generate_questions, parse_answer_with_llm

# ==============================================================================
# ЗАГЛУШКИ ДЛЯ ДЕМОНСТРАЦИИ (Замените на реальные импорты из вашего проекта)
# ==============================================================================
async def get_hotel(hotel_id: int):
    class MockHotel:
        def __init__(self):
            self.id = hotel_id
            self.lon = 20.4832
            self.lat = 54.9605
            self.floors = 4
            self.geom = Point(self.lon, self.lat)  # В реальности: Point(lon, lat) из БД
            self.name = "Zelenogradsk Premium"
    return MockHotel()

async def load_buildings(): return None
async def load_osm_layers(): return None
async def fetch_wikidata(name, lat, lon): return {"history": "Построено в 19 веке"}
async def fetch_weather(lat, lon): return {"temp": 18, "condition": "clear"}
async def fetch_air_quality(lat, lon): return {"aqi": 25, "status": "good"}
async def fetch_cell_coverage(lat, lon): return {"signal": "excellent"}
async def save_feature(hotel_id: int, key: str, value: Any): 
    print(f"💾 [DB MOCK] Сохранено: hotel={hotel_id}, key={key}")
# ==============================================================================


class AgentState(TypedDict):
    hotel_id: int
    features: dict[str, Any]
    pending_features: list[str]
    questions: list[dict]
    conflicts: list[dict]
    log: list[str]
    answers: Optional[dict]


async def node_geo(state: AgentState) -> dict:
    """Запуск GIS-инструментов: sunset_view, noise_score, walk_to_sea."""
    try:
        from app.tools.sunset_view import compute_sunset_view
        from app.tools.noise_score import compute_noise_score
        from app.tools.walk_to_sea import compute_walk_to_sea
    except ImportError:
        # Fallback, если модули еще не созданы
        def compute_sunset_view(**kwargs): return {"visible": True, "from_floor": 2, "confidence": 0.9}
        def compute_noise_score(**kwargs): return {"score": 15, "level": "Тихо", "confidence": 0.95}
        def compute_walk_to_sea(**kwargs): return {"minutes": 3.2, "confidence": 0.9}

    hotel = await get_hotel(state["hotel_id"])
    features = {}
    
    try:
        sunset = compute_sunset_view(
            hotel_lon=hotel.lon, hotel_lat=hotel.lat, total_floors=hotel.floors,
            dem_path=settings.DEM_PATH, buildings_gdf=await load_buildings(),
        )
        # compute_sunset_view возвращает датакласс SunsetViewResult — приводим к dict
        features["sunset_view"] = asdict(sunset) if not isinstance(sunset, dict) else sunset

        features["noise_score"] = compute_noise_score(
            hotel_geom=hotel.geom,
            osm_layers=(await load_osm_layers()) or {},
        )
        features["walk_to_sea"] = compute_walk_to_sea(hotel_lon=hotel.lon, hotel_lat=hotel.lat, dem_path=settings.DEM_PATH)
    except Exception as e:
        print(f"⚠️ Ошибка в node_geo: {e}. Используем демо-данные.")
        features["sunset_view"] = {"visible": True, "from_floor": 2, "confidence": 0.9}
        features["noise_score"] = {"score": 15, "level": "Тихо", "confidence": 0.95}
        features["walk_to_sea"] = {"minutes": 3.2, "confidence": 0.9}

    return {
        "features": {**state.get("features", {}), **features},
        "log": state["log"] + [
            f"🛰️ sunset_view: visible={features['sunset_view'].get('visible')}",
            f"🤫 noise_score: {features['noise_score'].get('score')}/100",
            f"🚶 walk_to_sea: {features['walk_to_sea'].get('minutes')} мин",
        ],
    }


async def node_open_data(state: AgentState) -> dict:
    """Загрузка данных из открытых API."""
    hotel = await get_hotel(state["hotel_id"])
    features = dict(state.get("features", {}))
    log = list(state.get("log", []))
    
    apis = [
        ("wikidata_history", fetch_wikidata(hotel.name, hotel.lat, hotel.lon)),
        ("weather", fetch_weather(hotel.lat, hotel.lon)),
        ("air_quality", fetch_air_quality(hotel.lat, hotel.lon)),
        ("cell_coverage", fetch_cell_coverage(hotel.lat, hotel.lon)),
    ]
    
    for key, coro in apis:
        try:
            features[key] = await coro
            log.append(f"✅ {key}: загружено")
        except Exception as e:
            print(f"⚠️ Ошибка загрузки {key}: {e}")
            features[key] = {"error": "unavailable", "confidence": 0.0}
            log.append(f"❌ {key}: ошибка загрузки")
    
    return {"features": features, "log": log}


async def node_conflicts(state: AgentState) -> dict:
    """LLM-агент ищет противоречия между источниками."""
    features = state.get("features", {})
    conflicts = []
    
    noise = features.get("noise_score", {}).get("score", 0)
    if isinstance(noise, (int, float)) and noise > 50:
        conflicts.append({
            "type": "noise_vs_positioning",
            "severity": "medium",
            "message": f"Шум {noise}/100, но отель может позиционироваться как тихий",
        })
    
    sunset = features.get("sunset_view", {})
    if isinstance(sunset, dict) and not sunset.get("visible", True):
        conflicts.append({
            "type": "sunset_vs_facade",
            "severity": "low",
            "message": "Фасад на запад, но закат не виден (здания перекрывают)",
        })
    
    questions = []
    if conflicts:
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
    """Формулирует вопросы для отельера (логический маркер)."""
    return {"log": state["log"] + ["📋 Вопросы отправлены отельеру"]}


async def node_wait(state: AgentState) -> dict:
    """
    Узел ожидания ответа. Граф останавливается здесь через interrupt(),
    пока отельер не ответит через UI.
    """
    # Если ответы уже есть (граф возобновлен), пропускаем interrupt
    if state.get("answers"):
        return {"log": state["log"] + ["⏭️ Пропуск ожидания, ответы уже получены"]}
    
    # Вызов interrupt приостанавливает граф и возвращает управление API
    answer = interrupt({
        "type": "hotelier_questions",
        "questions": state["questions"],
        "hotel_id": state["hotel_id"],
    })
    return {"answers": answer}


async def node_parse(state: AgentState) -> dict:
    """LLM парсит свободный ответ отельера в структурированный JSON."""
    answers = state.get("answers") or {}
    features = dict(state.get("features", {}))
    log = list(state.get("log", []))
    
    for question in state.get("questions", []):
        # Ответ может прийти по id вопроса (запуск из графа) или по feature_key (resume из роутера отельера)
        raw_answer = answers.get(question["id"]) or answers.get(question["feature_key"], "")
        if raw_answer:
            try:
                parsed = await parse_answer_with_llm(
                    question=question["question"],
                    raw_answer=str(raw_answer),
                    feature_key=question["feature_key"],
                )
                features[question["feature_key"]] = {
                    "value": parsed.get("value", raw_answer),
                    "source": "hotelier",
                    "confidence": parsed.get("confidence", 0.92),
                }
                log.append(f"🤖 Распарсен ответ для {question['feature_key']}")
            except Exception as e:
                print(f"⚠️ Ошибка парсинга: {e}")
                features[question["feature_key"]] = {"value": raw_answer, "source": "hotelier_raw", "confidence": 0.5}
    
    return {"features": features, "log": log}


async def node_finalize(state: AgentState) -> dict:
    """Пересчёт confidence, запись всех фич в БД."""
    features = state.get("features", {})
    log = list(state.get("log", []))
    
    saved_count = 0
    for key, value in features.items():
        try:
            await save_feature(state["hotel_id"], key, value)
            saved_count += 1
        except Exception as e:
            print(f"⚠️ Ошибка сохранения {key}: {e}")
    
    return {
        "log": log + [f"✅ Сохранено {saved_count} характеристик в БД"],
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
    
    # Условный переход: если есть вопросы → ask, иначе сразу finalize
    g.add_conditional_edges(
        "conflicts",
        lambda s: "ask" if s.get("questions") else "finalize",
    )
    
    g.add_edge("ask", "wait")
    g.add_edge("wait", "parse")
    g.add_edge("parse", "finalize")
    g.add_edge("finalize", END)
    
    # MemorySaver позволяет возобновлять граф после interrupt по thread_id
    return g.compile(checkpointer=MemorySaver())

# Глобальный инстанс графа
agent_graph = build_graph()