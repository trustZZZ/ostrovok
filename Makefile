.PHONY: up dev down seed data test clean db fe-dev be-dev

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

# Тесты в отдельном dev-образе: pytest не попадает в рантайм по требованиям правил
test:
	docker compose --profile tools run --rm --build test

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
