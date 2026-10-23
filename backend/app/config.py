"""
Конфигурация приложения.
"""
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://routely:routely@db:5432/routely"
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    USE_MOCK_LLM: bool = False
    
    # GIS Data paths
    DEM_PATH: str = "/data/dem.tif"
    BUILDINGS_PATH: str = "/data/buildings.gpkg"
    
    # Region
    REGION_BBOX: tuple = (54.7, 20.2, 55.0, 21.0)  # lat_min, lon_min, lat_max, lon_max
    
    class Config:
        env_file = ".env"

settings = Settings()
