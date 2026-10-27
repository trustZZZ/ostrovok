.PHONY: up dev down seed data data-buildings data-hotels test eval demo guides guides-fetch clean db fe-dev be-dev

# Поднять весь стек: UI на http://localhost:8080
up:
	docker compose up --build

# Синоним, оставлен для совместимости
dev: up

# Остановить контейнеры
down:
	docker compose down

# Собрать демо-данные в ./data (локальный Python не нужен — работает внутри backend-образа).
# Запускается один раз после первой сборки: make data
data:
	docker compose --profile tools run --rm --build seed

# Синоним: раньше seed запускал локальный python scripts/fetch_data.py
seed: data

# Только здания: разбор OSM PBF ради реальных высот (building:levels, height).
# Не тянет shapefile и DEM, поэтому занимает около минуты.
data-buildings:
	docker compose --profile tools run --rm --build seed python /scripts/fetch_data.py --buildings-only

# Только отели: этажность и адреса перечитываются из PBF по osm_id.
# После этого backend нужно перезапустить — сид перечитает hotels.geojson.
data-hotels:
	docker compose --profile tools run --rm --build seed python /scripts/fetch_data.py --hotels-only

# Тесты в отдельном dev-образе: pytest не попадает в рантайм по требованиям правил
test:
	docker compose --profile tools run --rm --build test

# Замер качества характеристик. Стек должен быть поднят: docker compose up -d
eval:
	docker compose --profile tools run --rm seed python /scripts/evaluate.py

# Демо целиком одной командой: сбор -> ответы отельера -> поиск.
# Стек должен быть поднят. Данные не выдумываются: ответы отельера — имитация
# только для субъективных характеристик (питомцы, сторона номеров, балкон).
demo:
	docker compose --profile tools run --rm seed python /scripts/demo.py

# Партнёрские обзоры -> характеристики отелей (см. data/guides/CONTRACT.md).
# Читает снапшот из репозитория: сервис партнёра для запуска не нужен.
guides:
	docker compose --profile tools run --rm --build seed python /scripts/ingest_guides.py

# То же, но с обновлением снапшота у партнёра (нужны GUIDES_API_URL/TOKEN).
guides-fetch:
	docker compose --profile tools run --rm --build seed python /scripts/ingest_guides.py --fetch

# Полная очистка, включая том БД
clean:
	docker compose down -v

# Только БД (для разработки)
db:
	docker compose up db -d

# Frontend dev-сервер (Vite, без Docker)
fe-dev:
	npm run dev

# Backend dev-сервер (нужно локальное окружение с зависимостями из backend/pyproject.toml)
be-dev:
	cd backend && uvicorn app.main:app --reload
