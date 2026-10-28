# Демо-стенд за системным nginx

Отдельный комплект конфигурации для сервера, где порт `8080` занят системным
nginx. Основной код проекта не меняется: здесь только запуск и проксирование.

## Схема

```
интернет
   │  :80 / :443
   ▼
┌──────────────────────────────────┐
│ nginx на хосте (системный)       │
│   location /api/agent/  (SSE)    │
│   location /api/                 │
│   location /                     │
└───────────────┬──────────────────┘
                │ 127.0.0.1:8081  (только loopback)
                ▼
┌──────────────────────────────────┐
│ frontend (nginx внутри контейнера│
│ слушает 8080)                    │
│   /      → SPA                   │
│   /api/  → backend:8000          │
└───────────────┬──────────────────┘
                │ внутри compose-сети
                ▼
┌──────────────────────────────────┐
│ backend (FastAPI, :8000)         │
└───────────────┬──────────────────┘
                │ внутри compose-сети
                ▼
┌──────────────────────────────────┐
│ db (PostGIS, :5432)              │
└──────────────────────────────────┘
```

Наружу опубликован **ровно один** порт — `127.0.0.1:8081`. Он привязан к
loopback, поэтому из интернета недоступен напрямую: до него дотягивается только
nginx на самом сервере. `db` и `backend` не имеют секции `ports` вовсе — они
видны только внутри compose-сети.

## Файлы

| Файл | Назначение |
| --- | --- |
| `docker-compose.yml` | стек без публикации портов, с фиксированным именем проекта и тома |
| `nginx/routely-site.conf` | готовый `server{}` — если домен отдаётся только этому приложению |
| `nginx/routely-locations.conf` | только `upstream` + `location` — если вставлять в существующий `server{}` |
| `.env.example` | адрес публикации на loopback, заметка про пароль существующего тома |

## Требования

- Docker Engine + Compose **v2.24 или новее** (`name:` и `env_file.required`).
  Проверка: `docker compose version`
- Если Compose старше: удалите блоки `env_file` у сервисов — все нужные
  переменные всё равно передаются через `environment` с подстановкой `${...}`,
  нужен только `.env` рядом с этим compose-файлом.
- Свободный порт `8081` на loopback: `ss -ltnp | grep 8081`
- Системный nginx с доступом к `/etc/nginx/sites-available/`

## Шаги

### 1. Скопировать папку на сервер

Папка должна лежать **внутри репозитория** — пути к коду и данным в compose
относительные (`../..`):

```
<repo>/deploy/demo/
```

### 2. (Опционально) свой .env

```bash
cd deploy/demo
cp .env.example .env
```

Обычно ничего менять не нужно: ключи LLM подхватываются из корневого `.env`,
без ключа работает мок-режим.

Диагностика занятого порта — если `8081` тоже занят, поменяйте в `.env`:

```bash
DEMO_BIND_PORT=8091
```

### 3. Поднять стек

```bash
cd deploy/demo
docker compose up -d --build
docker compose ps
```

Ожидаемо: `db` и `backend` — `healthy`, `frontend` — `running`.

Не запускайте одновременно корневой `docker-compose.yml` и этот файл: имя
проекта одно и то же (`ostrovok`), и они будут пересоздавать контейнеры друг
друга. Если стек уже был поднят из корня — сначала `docker compose down` там.

### 4. Проверить, что приложение живо на loopback

```bash
curl -sS http://127.0.0.1:8081/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/healthz
```

Ожидаемо: JSON `{"status":"ok",...}` и код `200`.

### 5. Подключить системный nginx

Вариант А — домен отдаётся только этому приложению:

```bash
sudo cp nginx/routely-site.conf /etc/nginx/sites-available/routely.conf
sudo sed -i 's/demo\.example\.com/ваш.домен.ru/' /etc/nginx/sites-available/routely.conf
sudo ln -s /etc/nginx/sites-available/routely.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Вариант Б — домен уже обслуживается другим сайтом: перенесите `upstream` в
контекст `http{}`, а `location`-блоки — внутрь существующего `server{}`
(подробнее в шапке `nginx/routely-locations.conf`).

Проверка до DNS:

```bash
curl -sS -H 'Host: ваш.домен.ru' http://127.0.0.1/health
```

Для TLS — блок-заготовка в конце `routely-site.conf` плюс `certbot`; если
сертификаты уже выданы на другой `server{}`, просто добавьте `location` туда.

### 6. Прогреть данные для демо

Пустая база отдаст отели без характеристик. Запустите сбор (фоновая задача,
отвечает сразу) и дайте ему время:

```bash
curl -sS -X POST 'http://127.0.0.1:8081/api/hotels/enrich-all?limit=12'
```

Проверка через пару минут — у отеля должны появиться характеристики. `id`
берётся из списка: нумерация начинается не с единицы.

```bash
curl -sS http://127.0.0.1:8081/api/hotels | head -c 600
curl -sS http://127.0.0.1:8081/api/hotels/<id>/features
```

Если том `ostrovok_pgdata` уже содержит прогретые данные (стек запускался
раньше), шаг можно пропустить.

### 7. (Опционально) Партнёрские обзоры

Характеристика «закатная точка рядом» приходит из снапшота `data/guides/`:

```bash
docker compose --profile tools run --rm seed python /scripts/ingest_guides.py
```

### 8. Проверить, что наружу ничего лишнего не торчит

```bash
ss -ltnp | grep -E ':(8080|8081|8000|5432)\b'
docker compose ps --format 'table {{.Service}}\t{{.Ports}}'
```

Ожидаемо: в списке портов только `127.0.0.1:8081->8080/tcp` у `frontend`.
У `db` и `backend` публикаций быть не должно. Если на `8080` что-то слушает —
это как раз системный nginx, и это нормально.

## Диагностика

| Симптом | Причина | Что делать |
| --- | --- | --- |
| `bind: address already in use` на `8080` | стек запускается из корневого compose, где порт публикуется | использовать этот файл; либо `APP_PORT=8091` в корневом `.env` |
| тот же текст на `8081` | порт занят другим сервисом | `DEMO_BIND_PORT=8091` в `deploy/demo/.env` |
| `502 Bad Gateway` от внешнего nginx | контейнер не поднялся или порт в `upstream` другой | `curl 127.0.0.1:8081/health`; `docker compose ps` |
| `404` на `/api/...` | в nginx нет `location /api/` либо в `proxy_pass` добавлен завершающий `/` | `proxy_pass http://routely_app;` — без слэша |
| пустые карточки отелей | данные не прогреты | шаг 6 |
| SSE отдаётся одним куском | буферизация на промежуточном уровне | `proxy_buffering off` в `location /api/agent/`, проверить оба nginx |
| `failed to read dockerfile` при сборке | запуск не из `deploy/demo/` | `cd deploy/demo` перед `docker compose up` |
| `password authentication failed` после смены `.env` | пароль БД задаётся только при создании тома | вернуть прежний пароль или пересоздать том |

Логи (команды из папки `deploy/demo`):

```bash
docker compose logs -f backend
docker compose logs -f frontend
sudo tail -f /var/log/nginx/error.log
```

## Если nginx сам работает в контейнере

Тогда `127.0.0.1` внутри контейнера nginx — это он сам, а не хост. Варианты:

1. Подключить оба стека к общей внешней сети и обращаться по имени сервиса:
   в `docker network create demo-edge`, затем добавить её в `frontend` здесь и
   в контейнер nginx, а в `upstream` указать `server frontend:8080;`.
2. Оставить публикацию на loopback и запустить nginx с
   `--network host` (только Linux).

Первый вариант аккуратнее: порты не публикуются вообще.

## Что здесь не меняется

- Код приложения, `Dockerfile`, `frontend/nginx.conf`, `features.yaml` — без правок.
- Образы и версии те же, что в корневом compose: `postgis:16-3.4`,
  `python:3.11.10-slim-bookworm`, `node:20.18.1-alpine`,
  `nginxinc/nginx-unprivileged:1.27-alpine`.
- `backend` по-прежнему монтируется из `../../backend:/app`: правки кода на
  сервере подхватываются после `docker compose restart backend`, без пересборки.
