"""Configurações centrais da aplicação.

Todos os valores podem ser sobrescritos por variáveis de ambiente ou
por um arquivo .env na raiz do backend. Nenhum segredo fica no código.
"""
import re
import secrets
import unicodedata
import warnings
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # /backend
PROJECT_ROOT = BASE_DIR.parent                            # raiz do monorepo

SECRET_KEY_INSEGURA = "TROQUE-ESTA-CHAVE-EM-PRODUCAO"

# Valores de EXEMPLO que já saíram publicados no repositório (o padrão do código, os
# .env.example e o docs/PUBLICAR.md, inclusive os que a documentação não mostra mais):
# qualquer um os conhece, então nunca são chave de verdade. Como SECRET_KEY, recusam o
# boot de produção e, em dev, viram a chave efêmera (como o padrão); como
# DATA_ENCRYPTION_KEY, entram em ``riscos_de_producao``. Um valor de exemplo novo num
# .env.example tem de entrar aqui: tests/test_config_producao.py lê os dois arquivos e
# reprova se algum valor deles passar pela trava de produção.
CHAVES_DE_EXEMPLO = frozenset({
    SECRET_KEY_INSEGURA,
    "gere-uma-chave-longa-e-aleatoria",
    "gere-outra-chave-longa-e-aleatoria",
    "outra-chave-longa-e-aleatoria-diferente",
})
_CHAVES_DE_EXEMPLO_NORMALIZADAS = frozenset(c.casefold() for c in CHAVES_DE_EXEMPLO)


def chave_de_exemplo(valor: str | None) -> bool:
    """O valor é uma das ``CHAVES_DE_EXEMPLO``, sem contar espaços nas pontas nem
    maiúsculas? Só compara; quem chama nunca escreve o valor em mensagem."""
    return (valor or "").strip().casefold() in _CHAVES_DE_EXEMPLO_NORMALIZADAS


# Valores de ENV reconhecidos, já normalizados (``normalizar_env``). Fora das duas
# listas o app roda como dev, e o log do boot avisa (``avisos_de_configuracao``).
ENV_DE_PRODUCAO = frozenset({"producao", "production", "prod"})
ENV_DE_DESENVOLVIMENTO = frozenset({"dev", "development", "desenvolvimento", "local",
                                    "test", "teste"})


def normalizar_env(valor: str | None) -> str:
    """ENV sem espaços nas pontas, em minúsculas e sem acento: ``"Produção "`` vira
    ``"producao"``. Um espaço colado no painel ou o acento desligavam em silêncio todas
    as travas de produção."""
    decomposto = unicodedata.normalize("NFKD", (valor or "").strip().casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


# Um único endereço, sem espaço/vírgula/curinga — só para VALIDAR configuração
# (não é validação de e-mail de usuário, que passa pelo EmailStr do Pydantic).
_RE_EMAIL_SIMPLES = re.compile(r"[^@\s,;*]+@[^@\s,;*]+\.[^@\s,;*]+")


def separar_chaves(valor: str | None) -> list[str]:
    """Lista de chaves separadas por vírgula (DATA_ENCRYPTION_KEYS_ANTERIORES):
    sem espaços nas pontas, sem vazias e sem repetidas, na ordem dada."""
    vistas: list[str] = []
    for parte in (valor or "").split(","):
        chave = parte.strip()
        if chave and chave not in vistas:
            vistas.append(chave)
    return vistas


def origem_de_desenvolvimento(origem: str | None) -> bool:
    """A origem é de desenvolvimento local — http(s) em ``localhost`` ou num subdomínio
    dele (``app.localhost``: os navegadores resolvem para o loopback), num endereço de
    loopback (127.0.0.0/8, ``[::1]``) ou em ``0.0.0.0`` — ou a origem opaca ``null``
    (arquivo aberto do disco, iframe em sandbox)? É o que sai do CORS em produção (A3,
    lacuna L4).

    O app desktop NÃO conta: ``tauri://localhost`` tem esquema próprio e
    ``http(s)://tauri.localhost`` é o host do WebView do Tauri, que usa essas origens em
    TODOS os ambientes, inclusive produção."""
    if (origem or "").strip().lower() == "null":
        return True
    try:
        partes = urlsplit((origem or "").strip())
        host = (partes.hostname or "").rstrip(".")
    except ValueError:
        return False
    if partes.scheme.lower() not in ("http", "https") or not host:
        return False
    if host == "localhost" or (host.endswith(".localhost") and host != "tauri.localhost"):
        return True
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Constela Edu — Gestão e Premiação Escolar"
    API_V1_PREFIX: str = "/api/v1"

    # "dev" (padrão, para desenvolvimento) ou "producao" (fail-closed: exige
    # SECRET_KEY e DATABASE_URL próprios e NÃO migra na importação — o schema vem
    # de `python -m scripts.migrate`, rodado ANTES do servidor: pre-deploy do
    # Railway ou entrypoint.sh). Em produção o boot também RECUSA a configuração
    # perigosa de ``riscos_de_producao`` (DEK ausente ou igual à SECRET_KEY, CORS
    # com curinga, /docs ligado); em dev ela só vira aviso no log. O /metrics fecha
    # sem METRICS_TOKEN em QUALQUER ENV, e o /docs só liga com DOCS_HABILITADOS=true.
    # Sequência segura em docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md.
    ENV: str = "dev"

    # --- Migrações e prontidão do schema (app/core/migracoes.py) -------------
    # Espera máxima de UMA migração por lock de tabela (PostgreSQL). Uma DDL na
    # fila de lock bloqueia todas as consultas seguintes à mesma tabela: melhor
    # falhar e reverter em segundos do que travar o site esperando.
    MIGRACAO_LOCK_TIMEOUT: str = "5s"
    # Espera pela VEZ de migrar (advisory lock): dois migradores ao mesmo tempo
    # (2 workers, 2 réplicas, dois deploys) se enfileiram em vez de correr.
    MIGRACAO_ESPERA_VEZ: str = "120s"
    # scripts.migrate: tentativas quando a falha é espera de lock (55P03).
    MIGRACAO_TENTATIVAS: int = 3
    MIGRACAO_PAUSA_S: float = 5.0
    # Revisões do banco DESCONHECIDAS por este código que o operador declara
    # compatíveis (lista separada por vírgula, ids exatos). Só para servir código
    # mais antigo sobre um schema mais novo e ADITIVO (rollback sem descer o
    # schema). Vazio = fail-closed: banco adiante do código não fica pronto no boot.
    SCHEMA_ADIANTE_ACEITO: str = ""

    # SQLite hoje; troque a URL para PostgreSQL sem alterar o restante do código.
    # Ex.: postgresql+psycopg://usuario:senha@host:5432/sgpe
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'database' / 'sgpe.db'}"

    # Pool de conexões (só afeta bancos de rede, ex.: PostgreSQL em produção).
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    # Conexão do pool parada há MAIS que isto (segundos) é testada com um ping antes de
    # ser entregue; a usada há menos vai direto (em produção cada ida ao banco custa
    # ~195 ms, e o ping a cada retirada era uma ida a mais em toda requisição). ``0``
    # = ping em toda retirada (o ``pool_pre_ping`` de antes). Ver
    # ``database.instalar_ping_por_ociosidade``. Não afeta o SQLite.
    DB_PING_OCIOSO_S: float = 30
    # Prazo (segundos) para ABRIR uma conexão nova com o PostgreSQL — o
    # ``connect_timeout`` da libpq, passado ao psycopg pelo engine. Sem ele, um
    # banco que não responde (host fora, rede parada) prende o worker no
    # handshake pelo padrão do driver (130 s no psycopg 3.2 da imagem). ``0`` (ou
    # negativo) = sem prazo do app (volta a esse padrão); o driver não aceita menos
    # de 2 s. Um ``connect_timeout`` escrito na própria DATABASE_URL prevalece
    # sobre este, e a variável ``PGCONNECT_TIMEOUT`` da libpq também, quando
    # definida e não vazia no ambiente. Não afeta o SQLite.
    DB_CONNECT_TIMEOUT: int = 10

    SECRET_KEY: str = SECRET_KEY_INSEGURA
    # Chave DEDICADA para cifrar segredos em repouso (credenciais de plataforma,
    # chave de IA, cookies do robô), separada da SECRET_KEY que assina os JWT.
    # OBRIGATÓRIA com ENV=producao: ausente, de exemplo ou igual à SECRET_KEY, o
    # boot recusa (``riscos_de_producao``). Só em dev pode ficar vazia, e então a
    # SECRET_KEY cifra (comportamento anterior, com aviso no boot). Separada, reduz
    # o raio de um vazamento e gira sem derrubar sessões; dados já cifrados com a
    # SECRET_KEY continuam legíveis (MultiFernet).
    DATA_ENCRYPTION_KEY: str = ""
    # Rotação PLANEJADA da cifra em repouso (app/core/security.py; sequência em
    # scripts/recifrar_segredos.py). As duas são SÓ DE DECIFRA: nada é cifrado com
    # elas, e NENHUMA assina ou valida JWT (aceitar a SECRET_KEY antiga no login
    # aceitaria token forjado com ela).
    #   DATA_ENCRYPTION_KEYS_ANTERIORES: DEKs anteriores, separadas por vírgula
    #     (sem vírgula dentro da chave). Também conferem o hash do código do Quest.
    #   CHAVE_CIFRA_LEGADA_ANTERIOR: a SECRET_KEY anterior, só para ler as cifras
    #     LEGADAS (feitas antes da DATA_ENCRYPTION_KEY, ou sem ela).
    # Depois de `recifrar_segredos --executar` com 100% na primária, APAGUE as duas.
    DATA_ENCRYPTION_KEYS_ANTERIORES: str = ""
    CHAVE_CIFRA_LEGADA_ANTERIOR: str = ""
    # Calculado pelo validador abaixo (o valor do ambiente é ignorado): True quando
    # a SECRET_KEY é a aleatória EFÊMERA de desenvolvimento (cai a cada reinício,
    # e com ela as sessões e as cifras legadas). Vai para o /sistema/diagnostico.
    SECRET_KEY_EFEMERA: bool = False
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

    # Tetos de FALHAS do /auth/login do Edu (app/core/rate_limit.py), persistentes
    # na tabela de limites do Quest (dimensões edu_login_ip_falha e
    # edu_login_global_falha): valem entre os workers e sobrevivem ao deploy.
    #   POR IP (IPv6 agrupado em /64): EDU_LOGIN_TETO_IP_FALHAS falhas, em qualquer
    #     conta, em EDU_LOGIN_TETO_IP_JANELA_S segundos bloqueiam o IP por uma janela.
    #   GLOBAL (todos os IPs somados): EDU_LOGIN_TETO_GLOBAL_FALHAS falhas em
    #     EDU_LOGIN_TETO_GLOBAL_JANELA_S segundos suspendem o login da API inteira
    #     (429) por uma janela e geram um log de alerta. Trade-off aceito: com poucos
    #     IPs um atacante trava o login de todos por janelas seguidas; as sessões já
    #     abertas seguem valendo. Suba o teto aqui se o uso real chegar perto dele
    #     (ver docs/lgpd/SESSAO-E-MFA.md).
    # Janela de 60 s a 1 h, como no Quest: menos que isso não freia nada; mais, e um
    # teto global atingido deixaria o login parado por horas. Teto ≥ 1 (zero barraria
    # todo login). Os limites por (conta, IP) e por conta continuam fixos e só em
    # memória.
    EDU_LOGIN_TETO_IP_FALHAS: int = Field(default=50, ge=1)
    EDU_LOGIN_TETO_IP_JANELA_S: int = Field(default=300, ge=60, le=3600)
    EDU_LOGIN_TETO_GLOBAL_FALHAS: int = Field(default=400, ge=1)
    EDU_LOGIN_TETO_GLOBAL_JANELA_S: int = Field(default=300, ge=60, le=3600)

    # Teto do corpo da requisição, conferido ANTES da autenticação (o FastAPI lê o
    # corpo antes das dependências). Ver app/core/limite_corpo.py. Formulário
    # urlencoded = login; multipart grande = só as rotas de 150 MB (avaliações,
    # INEP) e com token válido; outros = JSON (a confirmação de importação manda as
    # linhas do arquivo) e o multipart das demais rotas (a maior é o backup, 25 MB).
    LIMITE_CORPO_FORMULARIO_BYTES: int = 64 * 1024
    LIMITE_CORPO_MULTIPART_BYTES: int = 160 * 1024 * 1024
    LIMITE_CORPO_OUTROS_BYTES: int = 32 * 1024 * 1024

    # Documentação interativa (/docs, /redoc, /openapi.json). Desligada por
    # padrão: só liga com DOCS_HABILITADOS=true no ambiente de desenvolvimento.
    # Com ENV=producao, true faz o boot recusar (``riscos_de_producao``).
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
        return normalizar_env(self.ENV) in ENV_DE_PRODUCAO

    @model_validator(mode="after")
    def _validar_producao(self) -> "Settings":
        """Fail-closed: uma instância de produção nunca sobe com o segredo
        padrão nem em SQLite efêmero — melhor recusar a subir do que ficar
        vulnerável em silêncio. Em dev, um segredo aleatório efêmero
        substitui o valor conhecido do repositório (com aviso)."""
        object.__setattr__(self, "SECRET_KEY_EFEMERA", False)   # nunca do ambiente
        # O padrão do código e os valores dos .env.example são públicos: assinar JWT
        # com eles deixaria qualquer um forjar o token de um administrador.
        if chave_de_exemplo(self.SECRET_KEY) or len(self.SECRET_KEY) < 32:
            if self.em_producao:
                raise RuntimeError(
                    "SECRET_KEY inseguro ou ausente (vazia, com menos de 32 "
                    "caracteres ou um valor de exemplo do repositório). Defina "
                    "SECRET_KEY (>=32 caracteres aleatórios, gerados por você) no "
                    "ambiente antes de subir em produção — veja .env.example."
                )
            warnings.warn(
                "SECRET_KEY não definido (vazio, curto ou valor de exemplo): usando "
                "chave aleatória efêmera de desenvolvimento (as sessões caem a cada "
                "reinício). Defina SECRET_KEY no .env para persistir.",
                stacklevel=2,
            )
            object.__setattr__(self, "SECRET_KEY", secrets.token_urlsafe(48))
            object.__setattr__(self, "SECRET_KEY_EFEMERA", True)
        self._validar_chaves_anteriores()
        self._validar_url_do_banco()
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
        self._validar_tetos_do_login()
        # Por último: as recusas acima (SECRET_KEY, chaves anteriores, SQLite,
        # ADMIN_GLOBAL_EMAIL, tetos do login) continuam com a mensagem de sempre.
        riscos = self.riscos_de_producao()
        if riscos and self.em_producao:
            raise RuntimeError(
                "Configuração de produção recusada (ENV=producao): "
                + " | ".join(riscos)
                + " Corrija as variáveis antes de subir — veja "
                  "docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md."
            )
        return self

    def riscos_de_producao(self) -> list[str]:
        """Configuração que uma instância de PRODUÇÃO não pode ter (A3, critério 9).

        Em ``ENV=producao`` o boot recusa (``_validar_producao``); em dev cada item vira
        aviso no log do boot (``registrar_avisos_de_configuracao``) — a produção já rodou
        sem ENV, e o aviso é o que mostra o que o ``ENV=producao`` vai recusar. As frases
        dizem QUAL variável e por quê, nunca o valor.

        A DEK curta segue só como aviso (``security.avisos_da_cifra``): trocá-la exige a
        recifragem, e recusar o boot por isso travaria o ``ENV=producao`` sem ganho.

        A SECRET_KEY curta de verdade já virou a efêmera (dev) ou recusou o boot
        (``_validar_producao``); aqui chega a que só tem 32+ caracteres contando espaços,
        tabs e quebras de linha — em branco, qualquer um assina o JWT. Em dev fica como
        está (a produção roda sem ENV, e trocar a chave derrubaria as sessões e as cifras
        legadas) e vira aviso."""
        riscos: list[str] = []
        if len((self.SECRET_KEY or "").strip()) < 32:
            riscos.append(
                "SECRET_KEY com menos de 32 caracteres além de espaços e quebras de linha: "
                "uma chave em branco deixa qualquer um assinar o JWT de um administrador; "
                "gere uma chave aleatória (secrets.token_urlsafe(48)).")
        dek = (self.DATA_ENCRYPTION_KEY or "").strip()
        if not dek:
            riscos.append(
                "DATA_ENCRYPTION_KEY ausente: defina uma chave própria (32+ caracteres "
                "aleatórios, diferente da SECRET_KEY) para cifrar os segredos em repouso.")
        elif chave_de_exemplo(dek):
            riscos.append(
                "DATA_ENCRYPTION_KEY de exemplo: o valor está publicado no repositório "
                "(.env.example) e decifra as credenciais das escolas; gere uma chave "
                "própria (32+ caracteres aleatórios, diferente da SECRET_KEY).")
        elif dek in (self.SECRET_KEY, self.SECRET_KEY.strip()):
            riscos.append(
                "DATA_ENCRYPTION_KEY igual à SECRET_KEY: a cifra em repouso cai na chave "
                "que assina os JWT; use uma chave própria.")
        if any("*" in (origem or "") for origem in self.CORS_ORIGINS):
            riscos.append(
                "CORS_ORIGINS com curinga '*': liste explicitamente as origens do front "
                "(array JSON).")
        if self.DOCS_HABILITADOS:
            riscos.append(
                "DOCS_HABILITADOS=true: /docs, /redoc e /openapi.json publicam o mapa da "
                "API; desligue (remova a variável).")
        return riscos

    def _validar_url_do_banco(self) -> None:
        """A DATABASE_URL tem de ser lida pelo SQLAlchemy. Malformada (sem o '@' entre
        senha e host, espaço antes do esquema), o ``create_engine`` do import de
        app.core.database levantava um erro com o TEXTO da URL — a senha ia crua para
        o log do deploy, antes do logging do app. Vale em qualquer ENV: a produção
        roda sem ENV e cairia do mesmo jeito. A recusa sai FORA do ``except``, para a
        exceção original (com a URL) não ir junto como contexto; nunca leva o valor."""
        from sqlalchemy.engine import make_url

        try:
            make_url(self.DATABASE_URL)
            legivel = True
        except Exception:  # noqa: BLE001 — ArgumentError/ValueError: forma errada
            legivel = False
        if not legivel:
            raise RuntimeError(
                "DATABASE_URL malformada: confira o formato "
                "postgresql+psycopg://usuario:senha@host:porta/banco, sem espaço nas "
                "pontas (o valor não é exibido: ele contém a senha).")

    def _validar_chaves_anteriores(self) -> None:
        """Uma chave ANTERIOR igual à DATA_ENCRYPTION_KEY ou à SECRET_KEY ATUAL quer
        dizer que a rotação não foi feita (ou que a variável errada foi colada): em
        produção, recusar a subir; em dev, avisar — o anel de app.core.security já
        ignora repetidas e vazias. A mensagem nunca leva o valor."""
        atuais = {c for c in ((self.DATA_ENCRYPTION_KEY or "").strip(),
                              self.SECRET_KEY, self.SECRET_KEY.strip()) if c}
        legado = self.CHAVE_CIFRA_LEGADA_ANTERIOR or ""
        anteriores = separar_chaves(self.DATA_ENCRYPTION_KEYS_ANTERIORES)
        anteriores += [c for c in (legado, legado.strip()) if c]
        if not any(c in atuais for c in anteriores):
            return
        mensagem = ("DATA_ENCRYPTION_KEYS_ANTERIORES/CHAVE_CIFRA_LEGADA_ANTERIOR contém a "
                    "DATA_ENCRYPTION_KEY ou a SECRET_KEY ATUAL: a chave anterior tem de ser "
                    "a que saiu (ou fique vazia).")
        if self.em_producao:
            raise RuntimeError(mensagem + " Corrija as variáveis antes de subir.")
        warnings.warn(mensagem + " Ignorada.", stacklevel=2)

    def _validar_tetos_do_login(self) -> None:
        """O teto de falhas POR IP tem de ficar abaixo do teto GLOBAL do login do Edu:
        com EDU_LOGIN_TETO_IP_FALHAS >= EDU_LOGIN_TETO_GLOBAL_FALHAS, um IP só (ou uma
        rede IPv6 /64) chega ao teto global antes do próprio e trava o login de todos.
        Em produção, recusar a subir; em dev, avisar (os valores ficam como estão —
        cada um sozinho é válido). A mensagem diz as variáveis, não os valores."""
        if self.EDU_LOGIN_TETO_IP_FALHAS < self.EDU_LOGIN_TETO_GLOBAL_FALHAS:
            return
        padrao = {nome: type(self).model_fields[nome].default
                  for nome in ("EDU_LOGIN_TETO_IP_FALHAS", "EDU_LOGIN_TETO_GLOBAL_FALHAS")}
        mensagem = ("EDU_LOGIN_TETO_IP_FALHAS maior ou igual a EDU_LOGIN_TETO_GLOBAL_FALHAS: "
                    "as falhas de um único IP bastariam para suspender o login de todos. "
                    "O teto por IP tem de ser menor que o global (padrões: "
                    f"{padrao['EDU_LOGIN_TETO_IP_FALHAS']} e "
                    f"{padrao['EDU_LOGIN_TETO_GLOBAL_FALHAS']}).")
        if self.em_producao:
            raise RuntimeError(mensagem + " Corrija as variáveis antes de subir.")
        warnings.warn(mensagem, stacklevel=2)

    @model_validator(mode="after")
    def _resolver_armazenamento(self) -> "Settings":
        """Pastas de arquivos: UPLOADS_DIR/EXPORTS_DIR explícitos > DADOS_DIR >
        volume do Railway (RAILWAY_VOLUME_MOUNT_PATH) > raiz do repositório (dev).
        Os NOMES das subpastas (uploads/, exports/) não mudam."""
        base = (self.DADOS_DIR
                or (Path(self.RAILWAY_VOLUME_MOUNT_PATH)
                    if self.RAILWAY_VOLUME_MOUNT_PATH.strip() else None)
                or PROJECT_ROOT)
        if self.UPLOADS_DIR is None:
            object.__setattr__(self, "UPLOADS_DIR", Path(base) / "uploads")
        if self.EXPORTS_DIR is None:
            object.__setattr__(self, "EXPORTS_DIR", Path(base) / "exports")
        return self

    @model_validator(mode="after")
    def _cors_por_ambiente(self) -> "Settings":
        """CORS por ENV (A3, lacuna L4): em produção as origens de desenvolvimento local
        (``origem_de_desenvolvimento``) saem da lista — do padrão do código e também de
        um CORS_ORIGINS explícito, sem derrubar o boot (o padrão as traz para o dev).
        As removidas ficam em CORS_ORIGINS_REMOVIDAS, só para o log do boot. O curinga
        '*' não é removido: recusa o boot (``riscos_de_producao``)."""
        object.__setattr__(self, "CORS_ORIGINS_REMOVIDAS", [])   # nunca do ambiente
        if not self.em_producao:
            return self
        removidas = [o for o in self.CORS_ORIGINS if origem_de_desenvolvimento(o)]
        if removidas:
            object.__setattr__(self, "CORS_ORIGINS",
                               [o for o in self.CORS_ORIGINS if o not in removidas])
            object.__setattr__(self, "CORS_ORIGINS_REMOVIDAS", removidas)
        return self

    # --- Armazenamento em disco (originais importados, cópias de relatórios) --
    # Base das pastas que a API grava. A imagem Docker define DADOS_DIR=/dados;
    # no Railway, SEM volume, esse disco é do contêiner e some a cada deploy.
    # Anexe o volume em /dados (docs/operacao/ARMAZENAMENTO.md). O diagnóstico
    # GET /api/v1/sistema/diagnostico informa se as pastas estão no volume.
    DADOS_DIR: Path | None = None
    # Injetada pelo Railway quando há volume anexado (não defina à mão). Só vira
    # base se DADOS_DIR não estiver definido; o diagnóstico a usa para dizer se o
    # armazenamento é persistente.
    RAILWAY_VOLUME_MOUNT_PATH: str = ""
    # Vazios = derivados da base acima (<base>/uploads e <base>/exports).
    UPLOADS_DIR: Path | None = None
    EXPORTS_DIR: Path | None = None
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
        # Desenvolvimento local (web Vite). Com ENV=producao saem da lista
        # (``_cors_por_ambiente``), mesmo se vierem num CORS_ORIGINS explícito.
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # App desktop (Tauri): o WebView usa uma origem própria por plataforma
        # — cross-origin em TODOS os ambientes, inclusive produção.
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]
    # Calculado por ``_cors_por_ambiente`` (o valor do ambiente é ignorado): as
    # origens de desenvolvimento local tiradas do CORS em produção. Vai para o log.
    CORS_ORIGINS_REMOVIDAS: list[str] = []

    # Endereço público do frontend — usado no link e no QR code do Painel
    # Público e da vitrine da rede. O padrão é o domínio de PRODUÇÃO: um deploy
    # sem esta variável (ex.: Railway) geraria links "localhost" que não abrem em
    # nenhum outro aparelho. Definida no ambiente ou no .env, ela vale SEMPRE;
    # sem ela, a tela aberta em loopback gera o link com a própria origem
    # (routers/publico.base_do_link_publico).
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

    # --- Diagnóstico do robô no boot (app/core/automacao.py) --------------
    # Uma vez por processo, em thread de fundo: GET a ipinfo.io/ipapi.co (IP de
    # saída) e abrir o Chromium e as páginas de login, sem credenciais. LIGADO por
    # padrão — é o que a produção faz hoje; não defina lá. Os testes
    # (tests/conftest.py) e o E2E (apps/web/playwright*.config.ts) desligam com
    # "false": sem isso o pytest e o uvicorn do E2E saíam para a internet a partir
    # do runner. TEXTO, não bool, pelo mesmo motivo de AVALIACOES_ROBO_HABILITADO;
    # quem interpreta é ``automacao.verificacao_no_boot_ligada`` (só os valores de
    # "desligado" desligam; vazio ou fora da lista mantém o padrão, com aviso).
    AUTOMACAO_VERIFICAR_NO_BOOT: str = "true"

    # --- Sincronização automática de plataformas (módulo app/sync) --------
    # O worker roda no processo da API como thread de fundo. DESLIGADO por
    # padrão (fail-safe): ligue com SYNC_SCHEDULER_ENABLED=true em produção
    # depois de configurar credenciais. Sem escolas configuradas, é inócuo.
    SYNC_SCHEDULER_ENABLED: bool = False
    # Mesmo LIGADO, o agendador RECUSA subir (log claro, app de pé) quando um
    # pré-requisito CRÍTICO de app/sync/prerequisitos.py falha. Este valor passa
    # por cima da recusa — só por decisão do dono (docs/sync/REATIVAR-AGENDADOR.md).
    # TEXTO, não bool, pelo mesmo motivo de AVALIACOES_ROBO_HABILITADO: um valor
    # inválido no painel do deploy não pode derrubar a API no boot; quem
    # interpreta é ``prerequisitos.forcar_habilitado`` (fora da lista = não força).
    # Nunca liga o agendador sozinho e nunca fura a trava do schema errado no boot.
    SYNC_SCHEDULER_FORCAR: str = "false"
    SYNC_WORKERS: int = 1              # execuções simultâneas (Playwright é pesado)
    SYNC_POLL_S: int = 30             # intervalo de varredura da fila
    SYNC_MAX_TENTATIVAS: int = 3      # tentativas antes de desistir (erro recuperável)
    SYNC_BACKOFF_BASE_S: int = 60     # backoff exponencial: base * 2**(tentativa-1)
    SYNC_TIMEOUT_S: int = 180         # teto por PASSO do navegador (login, página, download)
    # Teto de tempo TOTAL da coleta de uma execução (asyncio.wait_for em volta
    # do conector). Estourou: a execução termina 'erro' (código 'timeout') com
    # alerta e nunca fica 'executando'. Folga sobre a mais longa já vista (a #407
    # do Elefante levou ~17 min numa recoleta completa).
    SYNC_TETO_EXECUCAO_S: int = 2700  # 45 min
    SYNC_LENTO_S: int = 120           # acima disso, alerta "sincronização lenta"
    # Semântica do ``end_date`` do Placar do Matific (não confirmada com a
    # plataforma): 'desconhecida' (padrão) | 'inclusiva' | 'exclusiva'. Com
    # 'desconhecida', período de 1 dia (início = fim) é recusado e intervalos de
    # 2+ dias seguem como sempre; com as outras duas, o pedido ao Matific e a data
    # do retrato seguem a semântica, na sync e no placar ao vivo. TEXTO (não
    # Literal): valor fora da lista vale 'desconhecida' em vez de derrubar o boot.
    MATIFIC_END_DATE: str = "desconhecida"
    # Robô de avaliações externas: teto de fontes coletadas por rodada do
    # scheduler — evita que muitas fontes (ou uma lenta) estagnem a fila de sync,
    # já que a coleta roda embutida na mesma thread. O resto vai na próxima rodada.
    AVALIACOES_COLETA_POR_RODADA: int = 3
    # O robô AUTOMÁTICO de avaliações externas (fontes_avaliacao) grava números
    # SEM prévia e roda embutido no agendador. DESLIGADO por padrão: ligar o
    # agendador não o liga junto. Os indicadores oficiais entram pela importação
    # com prévia e desfazer (services/indicadores). TEXTO, não bool: quem
    # interpreta é ``avaliacoes.robo_habilitado`` (qualquer valor fora da lista de
    # "ligado" = desligado). Como bool, um "sim" ou um valor vazio no painel do
    # deploy levantava ValidationError no import e derrubava a API no boot.
    AVALIACOES_ROBO_HABILITADO: str = "false"
    # Janela do pré-requisito do agendador (prerequisitos.teto_coerente e
    # execucoes_presas) e do sinal de vida de quem espera na FILA. Bem acima do teto
    # real de uma execução: precisa passar do SYNC_TETO_EXECUCAO_S (45 min, só a
    # coleta) com folga para a aplicação e o recálculo. Duas vezes este valor é
    # também por quanto tempo uma execução viva continua dando sinal de vida.
    SYNC_TRAVADA_S: int = 3600        # 60 min
    # Uma execução em "executando" sem nenhum registro no log dela há mais que isto
    # é considerada ÓRFÃ (worker morto/redeploy no meio) e é liberada. Quem está vivo
    # dá sinal 6 vezes nessa janela (service._sinal_de_vida_enquanto_roda), então uma
    # coleta longa não é reivindicada e a morta sai em minutos.
    SYNC_SEM_SINAL_S: int = 900       # 15 min

    # Proxy de SAÍDA do robô (Playwright). VAZIO por padrão e sem uso em
    # produção. A Matific protege o login com reCAPTCHA v3, que pontua a sessão
    # pela reputação do IP: de um IP de datacenter (Railway) o login com
    # credencial válida pode ser recusado. Rotear por outro IP para passar no
    # CAPTCHA NÃO é alternativa aceita aqui (controle de segurança do
    # fornecedor; termos de uso a confirmar) — ver docs/operacao/
    # COLETA-PLATAFORMAS.md: exportação oficial pela escola ou acordo com o
    # fornecedor. Formato, se um dia houver proxy autorizado:
    # "http://usuario:senha@host:porta" (ou socks5://...). Só o robô usa.
    SYNC_PROXY_URL: str = ""

    # --- Observabilidade (logs estruturados, métricas, Sentry) ------------
    LOG_JSON: bool = True           # logs em JSON (uma linha por evento)
    LOG_LEVEL: str = "INFO"
    APP_VERSION: str = "1.0.0"      # release: vai nos logs, no /health e no Sentry
    METRICS_ENABLED: bool = True    # expõe /metrics (formato Prometheus)
    # Protege /metrics: se definido, o scrape exige Authorization: Bearer <token>.
    # Vazio = /metrics responde 404 (fail-closed) EM QUALQUER ENV: a produção já
    # rodou sem ENV (= "dev") e, com a regra antiga "aberto em dev", a telemetria
    # ficava pública na internet. Métricas operacionais nunca ficam públicas por
    # omissão de configuração.
    METRICS_TOKEN: str = ""
    # Só para desenvolvimento local: abre /metrics sem token. Ignorado com
    # ENV=producao (lá, sem token, continua 404).
    METRICS_PUBLICO: bool = False
    SENTRY_DSN: str = ""            # vazio = Sentry desligado
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0   # 0..1 — amostragem do tracing
    SENTRY_ENVIRONMENT: str = ""    # vazio = usa o ENV


settings = Settings()


def avisos_de_configuracao(config: Settings | None = None) -> list[str]:
    """Frases para o log do boot (nunca com valor de variável). Em dev: o que o
    ``ENV=producao`` recusaria (``riscos_de_producao``), um ENV que não é nem dev nem
    produção (o app roda como dev, sem as travas) e o /metrics aberto pelo
    METRICS_PUBLICO. Em produção, nada: o que é perigoso já fez o boot recusar, e o
    METRICS_PUBLICO é ignorado."""
    config = config or settings
    if config.em_producao:
        return []
    avisos = [f"o ENV=producao recusaria o boot — {risco}"
              for risco in config.riscos_de_producao()]
    if normalizar_env(config.ENV) not in ENV_DE_DESENVOLVIMENTO:
        avisos.append(
            "ENV com valor não reconhecido (nem dev nem producao): o app roda em modo "
            "dev — migra no import e nenhuma trava de produção vale. Use ENV=producao "
            "na produção ou ENV=dev.")
    if config.METRICS_PUBLICO:
        avisos.append(
            "METRICS_PUBLICO=true: neste modo dev o /metrics responde sem token. É opção "
            "só do desenvolvimento local; remova a variável (com ENV=producao ela é "
            "ignorada).")
    return avisos


def registrar_avisos_de_configuracao(logger, config: Settings | None = None) -> int:
    """Escreve os avisos de ``avisos_de_configuracao`` no log (boot). Devolve quantos.
    Em produção, diz também (INFO: com o padrão do código é o esperado) quais origens
    de desenvolvimento local saíram do CORS — origem não é segredo."""
    config = config or settings
    if config.CORS_ORIGINS_REMOVIDAS:
        logger.info("Configuração: CORS de produção sem as origens de desenvolvimento "
                    "local (%s).", ", ".join(config.CORS_ORIGINS_REMOVIDAS))
    avisos = avisos_de_configuracao(config)
    for aviso in avisos:
        logger.warning("Configuração: %s", aviso)
    return len(avisos)


def email_reservado_ao_dono(email: str | None) -> bool:
    """O e-mail é o da conta do DONO declarada em ``ADMIN_GLOBAL_EMAIL``?

    Existe para fechar a REIVINDICAÇÃO da conta do dono: quem administra UMA
    escola não pode criar um usuário com esse e-mail e esperar a promoção a
    ``is_global`` no próximo boot. Sem a variável declarada devolve sempre
    False — nada é reservado, porque nada é promovido.
    """
    reservado = (settings.ADMIN_GLOBAL_EMAIL or "").strip().lower()
    return bool(reservado) and (email or "").strip().lower() == reservado
