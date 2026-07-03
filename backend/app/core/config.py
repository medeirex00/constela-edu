"""Configurações centrais da aplicação.

Todos os valores podem ser sobrescritos por variáveis de ambiente ou
por um arquivo .env na raiz do backend. Nenhum segredo fica no código.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # /backend
PROJECT_ROOT = BASE_DIR.parent                            # raiz do monorepo


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Constela Edu — Gestão e Premiação Escolar"
    API_V1_PREFIX: str = "/api/v1"

    # SQLite hoje; troque a URL para PostgreSQL sem alterar o restante do código.
    # Ex.: postgresql+psycopg://usuario:senha@host:5432/sgpe
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'database' / 'sgpe.db'}"

    SECRET_KEY: str = "TROQUE-ESTA-CHAVE-EM-PRODUCAO"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # jornada escolar

    UPLOADS_DIR: Path = PROJECT_ROOT / "uploads"
    EXPORTS_DIR: Path = PROJECT_ROOT / "exports"

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # App desktop (Tauri): o WebView usa uma origem própria por plataforma
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]

    # Endereço público do frontend — usado nos QR codes do Painel Público.
    PUBLIC_BASE_URL: str = "http://localhost:5173"

    # Assistente de IA (PRD §154): provedor trocável, isolado em app/services/ia.
    # "local" responde com regras determinísticas usando apenas o banco —
    # funciona sem chave e serve de contingência quando o provedor externo falha.
    AI_PROVIDER: str = "local"  # local | anthropic | openai
    AI_API_KEY: str = ""
    AI_MODEL: str = ""  # vazio = padrão do provedor
    AI_MAX_TOKENS: int = 1024


settings = Settings()
