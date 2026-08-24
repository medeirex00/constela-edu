"""Configurações centrais da aplicação.

Todos os valores podem ser sobrescritos por variáveis de ambiente ou
por um arquivo .env na raiz do backend. Nenhum segredo fica no código.
"""
import re
import secrets
import warnings
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # /backend
PROJECT_ROOT = BASE_DIR.parent                            # raiz do monorepo

SECRET_KEY_INSEGURA = "TROQUE-ESTA-CHAVE-EM-PRODUCAO"

# Um único endereço, sem espaço/vírgula/curinga — só para VALIDAR configuração
# (não é validação de e-mail de usuário, que passa pelo EmailStr do Pydantic).
_RE_EMAIL_SIMPLES = re.compile(r"[^@\s,;*]+@[^@\s,;*]+\.[^@\s,;*]+")


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
    # Chave DEDICADA para cifrar segredos em repouso (credenciais de plataforma,
    # chave de IA, cookies do robô), separada da SECRET_KEY que assina os JWT.
    # Opcional: se vazia, usa-se a SECRET_KEY (comportamento anterior). Definir
    # em produção reduz o raio de um vazamento e permite rotação independente;
    # dados já cifrados com a SECRET_KEY continuam legíveis (MultiFernet).
    DATA_ENCRYPTION_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # jornada escolar

    # Validade do link de redefinição de senha (uso único). Curto por
    # segurança: tempo suficiente para o usuário abrir o link e escolher a
    # senha, sem deixar um link válido perdido por horas.
    RESET_SENHA_EXPIRA_MIN: int = 60

    # Rate limiting — nº de proxies CONFIÁVEIS à frente do backend que APPENDam
    # o X-Forwarded-For (nginx do compose = 1; edge do Railway = 1). O IP real
    # do cliente é a Nª entrada A PARTIR DA DIREITA do XFF; as entradas à
    # esquerda podem ser forjadas pelo cliente e são ignoradas (anti-spoofing).
    # 0 = não confiar no XFF (usar só o IP do peer TCP direto).
    TRUSTED_PROXY_HOPS: int = 1

    # Documentação interativa (/docs, /redoc, /openapi.json). Desligada por
    # padrão: só liga com DOCS_HABILITADOS=true no ambiente de desenvolvimento.
    DOCS_HABILITADOS: bool = False

    # Conta do DONO da plataforma (acesso global a TODAS as redes). VAZIO por
    # padrão e SEM default no código: um ambiente novo — município novo,
    # staging, homologação, restauração de desastre — nunca nasce com uma conta
    # administrativa implícita que alguém possa reivindicar criando um usuário
    # com aquele e-mail (era o furo do e-mail cravado em database.py).
    # Vazio = `_promover_admin_global` não faz NADA (fail-closed). Declarado =
    # o e-mail vira RESERVADO: rotas de escola não podem criar conta com ele.
    ADMIN_GLOBAL_EMAIL: str = ""

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
        # ADMIN_GLOBAL_EMAIL, quando declarado, concede is_global — o maior
        # privilégio do sistema. Um valor malformado (lista, curinga, espaço)
        # jamais casaria com uma conta e a promoção falharia EM SILÊNCIO: em
        # produção é melhor recusar a subir (mesma régua do SECRET_KEY).
        email_dono = (self.ADMIN_GLOBAL_EMAIL or "").strip().lower()
        if email_dono and not _RE_EMAIL_SIMPLES.fullmatch(email_dono):
            if self.em_producao:
                raise RuntimeError(
                    "ADMIN_GLOBAL_EMAIL inválido: informe UM endereço de "
                    "e-mail (sem listas, curingas ou espaços) ou deixe a "
                    "variável vazia."
                )
            warnings.warn(
                "ADMIN_GLOBAL_EMAIL inválido — ignorado (nenhuma conta será "
                "promovida a administrador global).",
                stacklevel=2,
            )
            email_dono = ""
        object.__setattr__(self, "ADMIN_GLOBAL_EMAIL", email_dono)
        return self

    UPLOADS_DIR: Path = PROJECT_ROOT / "uploads"
    EXPORTS_DIR: Path = PROJECT_ROOT / "exports"
    # Retenção das cópias de relatórios em /exports (contêm nomes de alunos):
    # expurgadas após N dias para não acumular PII indefinidamente (LGPD). 0
    # desliga o expurgo. O download em si nunca depende da cópia.
    EXPORTS_RETENCAO_DIAS: int = 7

    CORS_ORIGINS: list[str] = [
        # Produção (front cross-origin: Vercel + Railway). O default vive no
        # código — como PUBLIC_BASE_URL/QUEST_BASE_URL — para que um deploy sem
        # CORS_ORIGINS no ambiente NÃO suba bloqueando todas as chamadas do
        # navegador. Setar CORS_ORIGINS no provedor passa a ser opcional (para
        # restringir), não obrigatório.
        "https://www.constelaedu.com",
        "https://quest.constelaedu.com",
        # Desenvolvimento local (web Vite).
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # App desktop (Tauri): o WebView usa uma origem própria por plataforma
        # — cross-origin em TODOS os ambientes, inclusive produção.
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
    # LGPD (retenção/minimização): conversas do assistente são apagadas depois
    # de IA_RETENCAO_DIAS a partir de created_at. São dados derivados; a fonte
    # oficial (notas/snapshots) é a autoritativa.
    IA_RETENCAO_DIAS: int = 90

    # --- Sincronização automática de plataformas (módulo app/sync) --------
    # O worker roda no processo da API como thread de fundo. DESLIGADO por
    # padrão (fail-safe): ligue com SYNC_SCHEDULER_ENABLED=true em produção
    # depois de configurar credenciais. Sem escolas configuradas, é inócuo.
    SYNC_SCHEDULER_ENABLED: bool = False
    SYNC_WORKERS: int = 1              # execuções simultâneas (Playwright é pesado)
    SYNC_POLL_S: int = 30             # intervalo de varredura da fila
    SYNC_MAX_TENTATIVAS: int = 3      # tentativas antes de desistir (erro recuperável)
    SYNC_BACKOFF_BASE_S: int = 60     # backoff exponencial: base * 2**(tentativa-1)
    SYNC_TIMEOUT_S: int = 180         # teto por execução (login+download)
    SYNC_LENTO_S: int = 120           # acima disso, alerta "sincronização lenta"
    # Robô de avaliações externas: teto de fontes coletadas por rodada do
    # scheduler — evita que muitas fontes (ou uma lenta) estagnem a fila de sync,
    # já que a coleta roda embutida na mesma thread. O resto vai na próxima rodada.
    AVALIACOES_COLETA_POR_RODADA: int = 3
    # Uma execução presa em "executando" além disso é considerada ÓRFÃ (worker
    # morto/redeploy no meio) e é recuperada: finalizada como erro e re-enfileirada.
    # Bem acima do teto real de uma execução, para nunca abortar uma sync viva.
    SYNC_TRAVADA_S: int = 1800        # 30 min

    # Proxy de SAÍDA do robô (Playwright). VAZIO por padrão. Existe porque
    # algumas plataformas (ex.: Matific) protegem o login com reCAPTCHA v3, que
    # PONTUA a sessão pela reputação do IP + sinais de automação: de um IP de
    # DATACENTER (Railway) o score é baixo e o login com credencial VÁLIDA é
    # recusado como se fosse senha errada. Roteando por um IP residencial/móvel
    # reputável o score sobe e o login passa. Formato:
    # "http://usuario:senha@host:porta" (ou socks5://...). Só o robô usa; a API
    # continua saindo direto. Se vazio, sem proxy (comportamento atual).
    SYNC_PROXY_URL: str = ""

    # --- Observabilidade (logs estruturados, métricas, Sentry) ------------
    LOG_JSON: bool = True           # logs em JSON (uma linha por evento)
    LOG_LEVEL: str = "INFO"
    APP_VERSION: str = "1.0.0"      # release: vai nos logs, no /health e no Sentry
    METRICS_ENABLED: bool = True    # expõe /metrics (formato Prometheus)
    # Protege /metrics: se definido, o scrape exige Authorization: Bearer <token>.
    # Vazio + produção = /metrics recusa (fail-closed), pois métricas operacionais
    # não podem ficar públicas. Vazio + dev = aberto (conveniência local).
    METRICS_TOKEN: str = ""
    SENTRY_DSN: str = ""            # vazio = Sentry desligado
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0   # 0..1 — amostragem do tracing
    SENTRY_ENVIRONMENT: str = ""    # vazio = usa o ENV


settings = Settings()


def email_reservado_ao_dono(email: str | None) -> bool:
    """O e-mail é o da conta do DONO declarada em ``ADMIN_GLOBAL_EMAIL``?

    Existe para fechar a REIVINDICAÇÃO da conta do dono: quem administra UMA
    escola não pode criar um usuário com esse e-mail e esperar a promoção a
    ``is_global`` no próximo boot. Sem a variável declarada devolve sempre
    False — nada é reservado, porque nada é promovido.
    """
    reservado = (settings.ADMIN_GLOBAL_EMAIL or "").strip().lower()
    return bool(reservado) and (email or "").strip().lower() == reservado
