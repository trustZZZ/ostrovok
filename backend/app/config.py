from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://routely:routely@db:5432/routely"
    
    # LLM (DeepSeek через aitunnel)
    LLM_BASE_URL: str = "https://api.aitunnel.ru/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_API_KEY: str = "" # Вставьте ключ сюда или в .env
    
    # Fallback для совместимости с langchain_openai по умолчанию
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "deepseek-chat"
    
    # Режим отладки/демо (если True, LLM не вызывается, возвращаются заглушки)
    USE_MOCK_LLM: bool = False
    
    # GIS Data paths
    DEM_PATH: str = "./data/dem.tif" # Исправил на относительный путь для локального теста
    BUILDINGS_PATH: str = "./data/buildings.gpkg"
    
    class Config:
        env_file = ".env"

settings = Settings()