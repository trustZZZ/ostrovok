# syntax=docker/dockerfile:1

# ---------- builder: компиляторы и dev-заголовки остаются здесь ----------
FROM python:3.11.10-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./

# Ставим только рантайм-зависимости: dev-extras (pytest) в образ не попадают.
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb')); open('requirements.txt', 'w').write('\n'.join(d['project']['dependencies']))" \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt

# ---------- runtime: без компиляторов и без тестовых пакетов ----------
FROM python:3.11.10-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /install /usr/local

# libexpat1 нужен колесу rasterio (единственная системная зависимость,
# которой нет в slim-образе); остальные .so приходят внутри manylinux-колёс.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

WORKDIR /app
COPY --chown=app:app . .

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
