from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "mysql+pymysql://hotline_app:change_me@localhost:3306/hotline_ai?charset=utf8mb4"
    app_env: str = "development"
    knowledge_gateway_mode: str = "qdrant"
    qdrant_url: str = "http://127.0.0.1:8088"
    qdrant_api_key: str = ""
    qdrant_collection: str = "hotline_dispatch_v2"
    qdrant_timeout: float = 30.0
    llm_gateway_mode: str = "mock"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: float = 240.0
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    case_default_city: str = "广州市"
    case_default_district: str = "白云区"
    case_default_jurisdiction: str = "广州市白云区"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
