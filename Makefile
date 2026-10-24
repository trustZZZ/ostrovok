.PHONY: dev seed test clean db fetch fe-dev be-dev

# Запуск всех сервисов
dev:
	docker compose up --build

# Загрузка демо-данных (локально; требует: pip install -r scripts/requirements.txt)
seed:
	python scripts/fetch_data.py

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

# Fetch данных из OSM (локально)
fetch:
	python scripts/fetch_data.py

# Frontend dev (исходники в корне репозитория)
fe-dev:
	npm run dev

# Backend dev
be-dev:
	cd backend && uvicorn app.main:app --reload
