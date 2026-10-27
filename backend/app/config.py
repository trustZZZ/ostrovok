from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend -> корень репозитория.
# Позволяет и docker-запуску, и локальному uvicorn находить ./data.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://routely:routely@db:5432/routely"

    # LLM (DeepSeek через aitunnel)
    LLM_BASE_URL: str = "https://api.aitunnel.ru/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_API_KEY: str = ""

    # Таймаут одного запроса к LLM, секунды. SDK без него ждёт ответа до 10 минут
    # и повторяет запрос, поэтому зависший провайдер блокировал POST /answer
    # на всё это время: ответ отельера не доходил до БД.
    LLM_TIMEOUT_S: float = 20.0

    # Fallback для совместимости с langchain_openai по умолчанию
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "deepseek-chat"

    # Режим отладки/демо (если True, LLM не вызывается, возвращаются заглушки)
    USE_MOCK_LLM: bool = False

    # GIS Data paths
    DEM_PATH: str = str(_REPO_ROOT / "data" / "dem.tif")
    BUILDINGS_PATH: str = str(_REPO_ROOT / "data" / "buildings.gpkg")
    NOISE_PATH: str = str(_REPO_ROOT / "data" / "noise_sources.geojson")
    BEACHES_PATH: str = str(_REPO_ROOT / "data" / "beaches.geojson")
    HOTELS_PATH: str = str(_REPO_ROOT / "data" / "hotels.geojson")
    # Каталог снапшотов партнёрских обзоров. Читается только ingest-скриптом:
    # в рантайме сервис в сеть партнёра не ходит, иначе демо зависело бы
    # от чужой доступности.
    GUIDES_PATH: str = str(_REPO_ROOT / "data" / "guides")

    @property
    def llm_api_key(self) -> str:
        """Ключ из любой из двух поддерживаемых переменных."""
        return self.LLM_API_KEY or self.OPENAI_API_KEY

    @property
    def llm_enabled(self) -> bool:
        """LLM используется, только если он не замокан и ключ реально задан."""
        return not self.USE_MOCK_LLM and bool(self.llm_api_key)


settings = Settings()
