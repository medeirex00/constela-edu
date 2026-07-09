"""Configurações centrais da aplicação.

Todos os valores podem ser sobrescritos por variáveis de ambiente ou
por um arquivo .env na raiz do backend. Nenhum segredo fica no código.
"""
import secrets
import warnings
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # /backend
PROJECT_ROOT = BASE_DIR.parent                            # raiz do monorepo

SECRET_KEY_INSEGURA = "TROQUE-ESTA-CHAVE-EM-PRODUCAO"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Constela Edu — Gestão e Premiação Escolar"
    API_V1_PREFIX: str = "/api/v1"

    # "dev" (padrão, tudo aberto para desenvolvimento) ou "producao"
    # (fail-closed: exige SECRET_KEY e DATABASE_URL próprios; sem /docs).
    ENV: str = "dev"

    # SQLite hoje; troque a URL para PostgreSQL sem alterar o restante do código.
    # Ex.: postgresql+psycopg://usuario:senha@host:5432/sgpe
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'database' / 'sgpe.db'}"

    # Pool de conexões (só afeta bancos de rede, ex.: PostgreSQL em produção).
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800

    SECRET_KEY: str = SECRET_KEY_INSEGURA
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # jornada escolar

    # Documentação interativa (/docs, /redoc, /openapi.json). Desligada por
    # padrão: só liga com DOCS_HABILITADOS=true no ambiente de desenvolvimento.
    DOCS_HABILITADOS: bool = False

    @property
    def em_producao(self) -> bool:
        return self.ENV.lower() in ("producao", "production", "prod")

    @model_validator(mode="after")
    def _validar_producao(self) -> "Settings":
        """Fail-closed: uma instância de produção nunca sobe com o segredo
        padrão nem em SQLite efêmero — melhor recusar a subir do que ficar
        vulnerável em silêncio. Em dev, um segredo aleatório efêmero
        substitui o valor conhecido do repositório (com aviso)."""
        if self.SECRET_KEY == SECRET_KEY_INSEGURA or len(self.SECRET_KEY) < 32:
            if self.em_producao:
                raise RuntimeError(
                    "SECRET_KEY inseguro ou ausente. Defina SECRET_KEY (>=32 "
                    "caracteres aleatórios) no ambiente antes de subir em "
                    "produção — veja .env.example."
                )
            warnings.warn(
                "SECRET_KEY não definido: usando chave aleatória efêmera de "
                "desenvolvimento (as sessões caem a cada reinício). Defina "
                "SECRET_KEY no .env para persistir.",
                stacklevel=2,
            )
            object.__setattr__(self, "SECRET_KEY", secrets.token_urlsafe(48))
        if self.em_producao and self.DATABASE_URL.startswith("sqlite"):
            raise RuntimeError(
                "Em produção, defina DATABASE_URL para um banco persistente "
                "(ex.: postgresql+psycopg://...). O SQLite padrão é efêmero."
            )
        return self

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

    # Endereço público do frontend — usado no link e no QR code do Painel
    # Público. O padrão é o domínio de PRODUÇÃO: um deploy sem esta variável
    # (ex.: Railway) geraria links "localhost" que não abrem em nenhum outro
    # aparelho. Para desenvolvimento local, defina no .env:
    # PUBLIC_BASE_URL=http://localhost:5173
    PUBLIC_BASE_URL: str = "https://www.constelaedu.com"

    # --- Constela Quest (plataforma dos alunos) ---------------------------
    # Endereço público do app dos alunos — vai dentro do QR dos cartões de
    # acesso. Em desenvolvimento: QUEST_BASE_URL=http://localhost:5174
    QUEST_BASE_URL: str = "https://quest.constelaedu.com"
    # Sessão longa (criança não redigita credencial toda aula); revogável a
    # qualquer momento regenerando o cartão (token_version).
    QUEST_SESSAO_DIAS: int = 30

    # Assistente de IA (PRD §154): provedor trocável, isolado em app/services/ia.
    # "local" responde com regras determinísticas usando apenas o banco —
    # funciona sem chave e serve de contingência quando o provedor externo falha.
    AI_PROVIDER: str = "local"  # local | anthropic | openai
    AI_API_KEY: str = ""
    AI_MODEL: str = ""  # vazio = padrão do provedor
    AI_MAX_TOKENS: int = 1024


settings = Settings()
