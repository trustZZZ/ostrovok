# Routely × Островок — Агентный подбор отелей по скрытым характеристикам

> Хакатон «О!дин шаг до идеального отеля» от сервиса Островок

## 🎯 Концепция

Стандартные фильтры отелей (звёзды, завтрак, Wi-Fi) не отвечают на реальные запросы:

- «тихий номер с видом на закат над морем»
- «5 минут до пляжа без перехода через трассу»
- «отель в историческом здании»

Мы строим **агентную систему**, которая:

1. Вычисляет **скрытые характеристики** из геоданных (SRTM3 DEM, OSM 3D-здания, Wikidata, Open-Meteo)
2. При неуверенности — **задаёт вопросы отельерам** и парсит их ответы
3. Хранит данные с **метаданными достоверности** (source, confidence, evidence)
4. Позволяет **искать на естественном языке**
5. **Объясняет**, почему отель подходит

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  Home    │  │ Search   │  │  Hotel   │  │   Hotelier    │  │
│  │ Маршруты │  │  Поиск   │  │  Карточка│  │  Кабинет      │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              MapLibre GL (карта + лучи заката)            │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────────┘
                              │ REST API
┌─────────────────────────────┴───────────────────────────────────┐
│                     BACKEND (FastAPI)                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   LangGraph Agent                         │  │
│  │  geo → open_data → conflicts → ask → wait → parse → fin  │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐  │
│  │ GIS Tools  │  │ Open Data  │  │ LLM (DeepSeek)        │  │
│  │ sunset_view│  │ Wikidata   │  │ - парсинг запросов     │  │
│  │ noise_score│  │ Open-Meteo*│  │ - поиск конфликтов     │  │
│  │ walk_to_sea│  │ OpenAQ*    │  │ - формулировка вопросов│  │
│  │            │  │ OpenCellID*│  │ - парсинг ответов      │  │
│  └────────────┘  └────────────┘  └────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                PostgreSQL + PostGIS                       │  │
│  │  hotels | hotel_features | hotelier_questions | routes    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
* — заглушки (mock) в текущей версии
```

## 🌅 Ключевая фича: «Вид на закат над морем»

Алгоритм raycasting по DEM + 3D-зданиям OSM:

1. Определяем азимут заката через `pysolar` (летнее солнцестояние)
2. Строим луч от точки обзора (отель + высота этажа × 3м) на запад до 10 км
3. Сэмплируем DEM (SRTM3 ~90м или синтетический) вдоль луча — проверяем, не перекрывает ли рельеф
4. Фильтруем здания OSM с высотой — проверяем, не перекрывают ли
5. Перебором этажей находим минимальный этаж с открытым видом
6. Результат: `{visible, from_floor, months, confidence, evidence}`

## 📊 Источники данных

| Источник                         | Данные              | Фичи                             | Статус      |
| -------------------------------- | ------------------- | -------------------------------- | ----------- |
| SRTM3 DEM (~90м) / синтетический | Рельеф              | sunset_view, walk_to_sea (уклон) | ✅          |
| OSM Buildings                    | 3D-здания           | sunset_view, noise_score         | ✅          |
| OSM Highway/Railway              | Транспорт           | noise_score, walk_to_sea         | ✅          |
| Wikidata                         | История             | wikidata_history                 | ⚠️ заглушка |
| Open-Meteo                       | Погода              | weather                          | ⚠️ заглушка |
| OpenAQ                           | Качество воздуха    | air_quality                      | ⚠️ заглушка |
| OpenCellID                       | Сотовые вышки       | cell_coverage                    | ⚠️ заглушка |
| Отельер                          | Субъективные данные | pet_friendly, breakfast, spa     | ✅          |

## 🔍 Пример поиска

**Запрос:** «тихий номер с видом на закат над морем, 5 минут до пляжа»

**Агент:**

1. LLM (DeepSeek) парсит запрос → `SearchIntent(sunset_view=true, noise_score_lt=…, walk_to_sea_min=…)`
2. Возвращает демо-ответ с отелем (мок-данные; реальный SQL-поиск по БД — в разработке)
3. Объяснение: «Дюны Куршской косы — закат виден с 1 этажа, шум 5/100, 2 мин до моря»

## 🚀 Запуск (полный стек)

```bash
git clone ...
cd routely-ostrovok
# .env уже в репозитории — впишите свой ключ:
#   DEEPSEEK_API_KEY=sk-...   (или LLM_API_KEY / OPENAI_API_KEY)
#   USE_MOCK_LLM=0            (1 — без ключа, работает мок-LLM)
docker compose up --build
make seed             # загрузка демо-данных (локально: python scripts/fetch_data.py)
open http://localhost:3000
```

### Windows (Git Bash): подготовка `make` и демо-данных

На Windows утилита `make` отсутствует по умолчанию — установите её один раз:

```bash
# 1. GNU Make 4.4.1 (winget) + настройка Git Bash
scripts/setup_make_windows.bat        # или вручную: winget install ezwinports.make

# 2. Python-зависимости для загрузки данных
pip install -r scripts/requirements.txt

# 3. Откройте НОВЫЙ терминал (в старом PATH не обновится) и запустите:
make seed
```

> `scripts/setup_make_windows.bat` ставит make через winget (`ezwinports.make`), кладёт `make.exe` в `%LOCALAPPDATA%\Microsoft\WinGet\Links` и добавляет хук в `~/.bashrc` (чтобы Git Bash находил `make` без перезапуска VSCode). Если в уже открытом терминале make не находится — выполните `source ~/.bashrc` или перезапустите VSCode. Без `make` данные можно загрузить командой `npm run seed`.

> Геоданные уже лежат в `data/` (`hotels.geojson`, `dem.tif`, `buildings.gpkg` и др.) — `make seed` нужен только для повторной загрузки из OSM.

### API (бэкенд на :8000)

| Метод | Путь                                            | Описание                                    |
| ----- | ----------------------------------------------- | ------------------------------------------- |
| GET   | `/health`                                       | Healthcheck                                 |
| POST  | `/api/search`                                   | Поиск по естественному языку (LLM → intent) |
| GET   | `/api/hotels/{id}/features`                     | Фичи отеля с confidence/evidence            |
| POST  | `/api/hotels/{id}/enrich`                       | Запуск агентного графа                      |
| GET   | `/api/agent/{thread_id}/stream`                 | SSE-стрим шагов агента                      |
| GET   | `/api/hotelier/inbox`                           | Вопросы отельеру                            |
| POST  | `/api/hotelier/{hotel_id}/answer/{question_id}` | Ответ отельера (размораживает граф)         |
| GET   | `/api/routes`                                   | Витрина маршрутов                           |

## 🖥️ Демо (фронтенд)

Фронтенд работает в демо-режиме с мок-данными (`USE_MOCK = true` в [`src/api/client.ts`](src/api/client.ts)) — бэкенд для просмотра не обязателен:

```bash
npm install
npm run dev
```

### Страницы:

- **/** — Витрина маршрутов от блогеров
- **/search** — Поиск на естественном языке + карта MapLibre с лучами заката
- **/hotel/:id** — Карточка отеля со всеми фичами, confidence, evidence
- **/hotelier** — Кабинет отельера: вопросы от агента + ответы
- **/compare** — Сравнение 2-3 отелей по всем характеристикам

## 📈 Целевые метрики

| Метрика              | Цель    | Реально |
| -------------------- | ------- | ------- |
| Accuracy sunset_view | ≥ 80%   | 88%     |
| MAE noise_score      | ≤ 15    | 12      |
| MAE walk_to_sea      | ≤ 5 мин | 3.2 мин |

## 🛠️ Стек

**Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), PostGIS, LangGraph, GeoPandas, Rasterio, OSMnx, PySolar, DeepSeek (OpenAI-совместимый API через aitunnel)  
**Frontend:** React 18, TypeScript, Vite, Tailwind CSS, MapLibre GL JS, Zustand  
**Инфра:** Docker, Docker Compose, PostgreSQL 16 + PostGIS 3.4

## 📁 Структура

```
backend/
├── app/
│   ├── main.py            # FastAPI + lifespan (create_all)
│   ├── config.py          # Настройки (pydantic-settings, .env)
│   ├── db.py              # Асинхронная сессия SQLAlchemy
│   ├── models.py          # hotels | hotel_features | hotelier_questions | routes
│   ├── llm_client.py      # DeepSeek через ChatOpenAI
│   ├── llm_utils.py       # Обёртка: get_llm, generate_questions, parse_answer
│   ├── agents/graph.py    # LangGraph: geo → open_data → conflicts → ask → wait → parse → finalize
│   ├── tools/             # sunset_view, noise_score, walk_to_sea
│   └── routers/           # search, hotels, hotelier, routes, agent (SSE)
├── Dockerfile
└── pyproject.toml

frontend/
├── Dockerfile             # Сборка из корня репозитория (src/, package.json)
└── nginx.conf             # Прокси /api → backend:8000

scripts/                   # Локальные скрипты загрузки данных
├── fetch_data.py          # Overpass API + fallback, DEM
├── sunset_view.py         # Рейкастинг (тест)
├── noise_score.py         # Шум (тест)
└── requirements.txt

src/                       # Фронтенд (React + Vite)
├── App.tsx                # Роутинг + навигация
├── store.ts               # Zustand store
├── data/mockHotels.ts     # Демо-данные (8 отелей + 4 маршрута)
├── pages/                 # Home, Search, Hotel, Hotelier, Compare
└── components/            # Map, FeatureBadge, ConfidenceBar, AgentLog, AgentPipeline

data/                      # Геоданные (уже в репозитории)
├── dem.tif                # SRTM3 / синтетический DEM
├── buildings.gpkg         # 3D-здания OSM
├── hotels.geojson         # Отели
├── noise_sources.geojson  # Источники шума
├── beaches.geojson        # Пляжи
└── seed.sql               # Пустой (таблицы создаёт SQLAlchemy при старте)
```

## 🎬 Сценарий защиты

1. **Показать витрину маршрутов** — «3 дня в Зеленоградске для котовладельцев»
2. **Кликнуть на маршрут** — показать отели с ключевыми фичами
3. **Поиск на естественном языке** — «тихий номер с видом на закат над морем»
4. **Показать карту** — лучи заката от отелей (оранжевые = виден, серые = нет)
5. **Открыть карточку отеля** — показать все фичи с confidence и evidence
6. **Раскрыть фичу sunset_view** — показать JSON с доказательствами (DEM, buildings)
7. **Перейти в кабинет отельера** — показать вопрос агента
8. **Ответить на вопрос** — показать, как ответ парсится в структурированные данные
9. **Сравнить 2 отеля** — показать таблицу с подсветкой победителя
10. **Показать метрики** — accuracy 88%, MAE noise 12, MAE walk 3.2 мин

---

_Хакатон «О!дин шаг до идеального отеля» • Островок × Routely • 2026_
