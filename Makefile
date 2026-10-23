.PHONY: dev seed test clean

# Запуск всех сервисов
dev:
	docker compose up --build

# Загрузка демо-данных и precompute фич
seed:
	docker compose exec backend python -m scripts.seed_db

# Запуск тестов
test:
	docker compose exec backend pytest -v

# Очистка
clean:
	docker compose down -v
	rm -rf data/*.tif data/*.gpkg

# Только БД (для разработки)
db:
	docker compose up db -d

# Fetch данных из OSM
fetch:
	docker compose exec backend python -m scripts.fetch_data

# Frontend dev
fe-dev:
	cd frontend && npm run dev

# Backend dev
be-dev:
	cd backend && uvicorn app.main:app --reload
