"""Painel Público (PRD §104–§128).

Duas metades:
  * `/painel-publico/*` (autenticado, admin/coordenador) — configuração:
    ativar/desativar, escolher slides, intervalo, tamanho do ranking,
    gerar QR code e trocar o token (invalida o link antigo).
  * `/publico/{token}/*` (SEM login) — dados exibidos no telão/celular.
    Somente dados pedagógicos saem por aqui: nome, turma, notas, posição,
    conquistas. Nada de datas de nascimento, observações ou contatos. O nome
    do aluno sai ANONIMIZADO por padrão (primeiro nome + inicial), pois o link
    é público — a escola pode optar por nome completo (config `anonimizar`).
"""
import ipaddress
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, negar_secretaria
from app.models import (
    Aluno, Configuracao, Escola, Matricula, Nota,
    SnapshotElefante, Turma, Usuario,
)
from app.services import elegibilidade, evolucao as svc_evolucao
from app.services import gamificacao as svc_gami
from app.services import modulos as svc_modulos
from app.services import relatorios as svc_relatorios
from app.services import scoring
from app.services.audit import registrar

router = APIRouter(tags=["Painel Público"])

SLIDES_VALIDOS = ["ranking", "evolucao", "destaques", "mural"]
PADRAO = {
    "ativo": False,
    "slides": SLIDES_VALIDOS,
    "intervalo_s": 12,
    "max_posicoes": 10,
    # Telão SEM login: por padrão o nome do aluno sai anonimizado (primeiro nome
    # + inicial). Expor nome COMPLETO de criança num link público é risco
    # LGPD/ECA. A escola pode desligar (mostrar nome completo) com consentimento.
    "anonimizar": True,
}


def _slides_limpos(slides) -> list[str]:
    """Os slides de uma config: só os VÁLIDOS, sem repetição, na ordem em que a
    escola os escolheu. Vale na gravação e em toda leitura — uma config gravada
    antes do teto (com a lista repetida milhares de vezes) não pode continuar
    servindo essa lista ao telão sem login a cada consulta. Valor que não é
    lista (config corrompida) volta ao padrão."""
    if not isinstance(slides, (list, tuple)):
        return list(SLIDES_VALIDOS)
    limpos: list[str] = []
    for slide in slides:
        if slide in SLIDES_VALIDOS and slide not in limpos:
            limpos.append(slide)
    return limpos


def _config_row(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "painel_publico",
            Configuracao.chave == "valores",
        )
    ).scalar_one_or_none()


def _config(db: Session, escola_id: int) -> dict:
    row = _config_row(db, escola_id)
    valores = dict(PADRAO)
    if row:
        valores.update(row.valor or {})
    return valores


# Cache token->escola_id: evita varrer TODAS as configs de painel a cada poll do
# telão (~12s). É só uma DICA de performance — a correção vem sempre da validação
# (compare_digest contra o token real da escola), então um cache velho/errado
# nunca resolve para a escola errada; no máximo cai na varredura.
_cache_tokens: dict[str, int] = {}


def _escola_pelo_token(db: Session, token: str) -> tuple[Escola, dict] | None:
    """Resolve o token público para uma escola com painel ativo."""
    # Token real é token_urlsafe (ASCII). Rejeita não-ASCII antes de comparar:
    # secrets.compare_digest levanta TypeError com não-ASCII e este endpoint é sem
    # login — sem isto, um token com acento viraria 500 (deve ser 404).
    if not token or not token.isascii():
        return None

    def _validar(row) -> tuple[Escola, dict] | None:
        valores = row.valor or {}
        if not (valores.get("ativo")
                and secrets.compare_digest(str(valores.get("token", "")), token)):
            return None
        escola = db.get(Escola, row.escola_id)
        if escola is None or escola.status != "ativa":
            return None
        config = dict(PADRAO)
        config.update(valores)
        return escola, config

    # Caminho rápido: cache aponta a escola; valida com 1 consulta indexada.
    escola_id = _cache_tokens.get(token)
    if escola_id is not None:
        row = db.execute(
            select(Configuracao).where(
                Configuracao.escola_id == escola_id,
                Configuracao.namespace == "painel_publico",
                Configuracao.chave == "valores",
            )
        ).scalar_one_or_none()
        if row is not None and (resultado := _validar(row)) is not None:
            return resultado
        _cache_tokens.pop(token, None)   # entrada velha: cai para a varredura

    # Miss: varre uma vez e reconstrói o cache de tokens ativos.
    linhas = db.execute(
        select(Configuracao).where(
            Configuracao.namespace == "painel_publico",
            Configuracao.chave == "valores",
        )
    ).scalars().all()
    encontrado = None
    for row in linhas:
        valores = row.valor or {}
        tok = str(valores.get("token", ""))
        if valores.get("ativo") and tok:
            _cache_tokens[tok] = row.escola_id
        if encontrado is None and (resultado := _validar(row)) is not None:
            encontrado = resultado
    return encontrado


# ---------------------------------------------------------------------------
# Configuração (autenticado)
# ---------------------------------------------------------------------------

# A Secretaria fica de fora (leitura também): a configuração traz o link com o
# token do painel, e o painel pode exibir o nome completo das crianças — dado
# individual que ela não vê (LGPD). Só a gestão da própria escola e o admin global.
config_router = APIRouter(prefix="/escolas/{escola_id}/painel-publico",
                          tags=["Painel Público"],
                          dependencies=[Depends(negar_secretaria)])


class PainelConfigIn(BaseModel):
    ativo: bool
    # Teto = os slides que existem: a tela manda caixas de seleção sem repetição;
    # uma lista maior só vem de chamada direta (ou cliente com defeito).
    slides: list[str] = Field(default=SLIDES_VALIDOS, max_length=len(SLIDES_VALIDOS))
    intervalo_s: int = Field(default=12, ge=4, le=120)
    max_posicoes: int = Field(default=10, ge=3, le=50)
    # Padrão seguro: anonimiza o nome no telão público (ver PADRAO).
    anonimizar: bool = True
    # Gesto consciente EXIGIDO pelo servidor para passar de protegido→exposto
    # (não é persistido; é um flag da ação, não configuração).
    confirmar_exposicao: bool = False


# Host que o navegador põe na origem da tela (``window.location.origin``): nome ASCII em
# minúsculas ou IPv6 — nada de ``%``, ``\``, ``@`` nem Unicode.
_RE_HOST_DA_ORIGEM = re.compile(r"[a-z0-9.-]+|[0-9a-f:.]+")


def _base_configurada() -> str | None:
    """``PUBLIC_BASE_URL`` definido DE PROPÓSITO (no ambiente ou no ``.env``), sem a barra
    final — None quando vale o padrão do código. O pydantic-settings só põe em
    ``model_fields_set`` o valor que veio de fora; o padrão fica de fora."""
    if "PUBLIC_BASE_URL" in settings.model_fields_set:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    return None


def _ip_de_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _origem_de_loopback(origem: str) -> str | None:
    """A origem REMONTADA (``esquema://host[:porta]``, do host e da porta já validados)
    quando ela é http(s) de loopback — ``localhost``, ``*.localhost`` menos
    ``tauri.localhost``, IP de loopback — e nada além disso; senão None.

    A origem tem de ser exatamente a remontada (no máximo com a barra final): ficam de
    fora caminho, consulta, fragmento, credencial (mesmo vazia: ``http://:@``), barra
    invertida, maiúscula e porta escrita de outro jeito (``:08050``) ou fora de 0–65535.
    É o que impede o Python e o navegador de lerem hosts diferentes no mesmo texto: para
    o navegador, ``http://evil.com\\.localhost`` é ``evil.com``."""
    try:
        partes = urlsplit(origem)
        porta = partes.port          # ValueError: porta não numérica ou fora de 0–65535
    except ValueError:
        return None
    host = partes.hostname or ""
    nome = host.rstrip(".")
    if (partes.scheme not in ("http", "https") or not _RE_HOST_DA_ORIGEM.fullmatch(host)
            or not (nome == "localhost"
                    or (nome.endswith(".localhost") and nome != "tauri.localhost")
                    or _ip_de_loopback(nome))):
        return None
    netloc = f"[{host}]" if ":" in host else host
    if porta is not None:
        netloc = f"{netloc}:{porta}"
    base = f"{partes.scheme}://{netloc}"
    return base if origem in (base, f"{base}/") else None


def base_do_link_publico(origem: str | None) -> str:
    """Base do link público — o texto, o Copiar, o Abrir e o QR. QUEM DECIDE É O
    SERVIDOR, nesta ordem:

    1. ``PUBLIC_BASE_URL`` definido de propósito (ambiente ou ``.env``) vence SEMPRE: é o
       endereço que o operador escolheu para os outros aparelhos (domínio da escola, IP
       da rede local). A instalação pelo docker-compose cai sempre aqui.
    2. Sem ele, a origem da tela, SÓ quando é http(s) de loopback (demo, ambiente de
       teste, desenvolvimento) — senão o link de uma instalação local apontava para a
       produção, onde o token local não existe. A base é remontada do host e da porta
       validados (``_origem_de_loopback``); qualquer outra origem é IGNORADA, então este
       parâmetro nunca põe um domínio de fora no link. O app de desktop
       (``http://tauri.localhost`` no Windows) NÃO é loopback aqui — ele fala com o
       servidor de verdade (mesma exceção de ``core.config.origem_de_desenvolvimento``).
    3. Senão, o domínio publicado (o padrão do código).

    Limite do passo 2: o link em loopback só abre neste computador (no celular,
    ``localhost`` é o próprio celular). Para ler o QR com outro aparelho, defina
    ``PUBLIC_BASE_URL``."""
    configurada = _base_configurada()
    if configurada is not None:
        return configurada
    local = _origem_de_loopback(origem) if origem else None
    return local or settings.PUBLIC_BASE_URL.rstrip("/")


def _com_url(valores: dict, origem: str | None = None) -> dict:
    token = valores.get("token")
    return {
        "ativo": valores.get("ativo", False),
        "slides": _slides_limpos(valores.get("slides", SLIDES_VALIDOS)),
        "intervalo_s": valores.get("intervalo_s", 12),
        "max_posicoes": valores.get("max_posicoes", 10),
        "anonimizar": valores.get("anonimizar", True),
        "url": f"{base_do_link_publico(origem)}/p/{token}" if token else None,
    }


# ``origem`` (consulta, opcional) em todo endpoint que devolve o link: a origem da tela,
# que o servidor aceita ou ignora (``base_do_link_publico``).
@config_router.get("")
def obter_config(
    origem: str | None = None,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    return _com_url(_config(db, escola_id), origem)


@config_router.put("")
def salvar_config(
    dados: PainelConfigIn,
    origem: str | None = None,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    slides = _slides_limpos(dados.slides)
    if not slides:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Escolha pelo menos um slide para o painel.")
    row = _config_row(db, escola_id)
    anterior = dict((row.valor or {}) if row else {})
    estava_ativo = bool(anterior.get("ativo"))
    # Barreira de SERVIDOR: só passa de protegido→exposto (nome completo de
    # criança em link sem senha) com confirmação explícita — defesa contra
    # cliente antigo/chamada direta que burle o aviso do navegador.
    if (bool(anterior.get("anonimizar", True)) and not dados.anonimizar
            and not dados.confirmar_exposicao):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Para exibir o nome completo das crianças no telão público (link "
            "sem senha), é preciso confirmar a exposição explicitamente.")
    valores = dict(anterior)
    valores.update(dados.model_dump(exclude={"confirmar_exposicao"}))
    valores["slides"] = slides
    # (RE)ATIVAR o painel = "gerar um novo painel público": sempre nasce um
    # endereço NOVO, então qualquer QR/link gerado antes deixa de funcionar na
    # hora (o token antigo não resolve mais). Editar/ajustar um painel que JÁ
    # está ativo preserva o endereço em uso — não derruba o telão no meio.
    if valores["ativo"] and (not estava_ativo or not valores.get("token")):
        valores["token"] = secrets.token_urlsafe(9)
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="painel_publico",
                           chave="valores", valor=valores)
        db.add(row)
    else:
        row.valor = valores
    registrar(db, "painel_publico.configurado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"ativo": valores["ativo"], "slides": slides,
                        "anonimizar": valores.get("anonimizar", True)})
    db.commit()
    invalidar_cache_painel(escola_id)   # reflete a nova config/token no telão já
    return _com_url(valores, origem)


@config_router.post("/novo-token")
def trocar_token(
    origem: str | None = None,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Gera um novo endereço público — o link antigo deixa de funcionar."""
    row = _config_row(db, escola_id)
    valores = dict((row.valor or {}) if row else dict(PADRAO))
    valores["token"] = secrets.token_urlsafe(9)
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="painel_publico",
                           chave="valores", valor=valores)
        db.add(row)
    else:
        row.valor = valores
    registrar(db, "painel_publico.token_trocado", escola_id=escola_id, usuario_id=usuario.id)
    db.commit()
    invalidar_cache_painel(escola_id)   # o link antigo cai imediatamente
    return _com_url(valores, origem)


@config_router.get("/qr")
def qr_code(
    origem: str | None = None,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """QR code (SVG) apontando para o painel público (PRD §118) — o mesmo link que o GET
    devolve para a mesma ``origem`` (ver ``base_do_link_publico``)."""
    import segno

    valores = _config(db, escola_id)
    token = valores.get("token")
    if not valores.get("ativo") or not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Ative o painel público antes de gerar o QR code.")
    url = f"{base_do_link_publico(origem)}/p/{token}"
    qr = segno.make(url, error="m")
    import io
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=6, dark="#1B2A4A", border=2)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="painel_publico_qr.svg"'},
    )


# ---------------------------------------------------------------------------
# Acesso público (sem login) — somente dados pedagógicos
# ---------------------------------------------------------------------------

# Telão e vitrine são endereços SEM login feitos para circular (QR para as
# famílias) e podem trazer nome de criança: nenhuma resposta daqui pode ser
# indexada nem arquivada por buscador (a cópia guardada sobreviveria à troca do
# token). As páginas do front que as consomem têm a mesma marca na borda
# (vercel.json e nginx.conf, só nas rotas /p/ e /rede/p/) e no <meta robots>.
NAO_INDEXAR = "noindex, nofollow, noarchive"


def _sem_indexacao(response: Response) -> None:
    response.headers["X-Robots-Tag"] = NAO_INDEXAR


publico_router = APIRouter(prefix="/publico", tags=["Painel Público"],
                           dependencies=[Depends(_sem_indexacao)])


def _turmas_premiaveis(db: Session, escola: Escola) -> list[int]:
    """As turmas da escola que CONCORREM (1º ao 5º ano) no ano letivo ativo.

    AS FASES NÃO CONCORREM — e o telão é a única superfície que qualquer pessoa
    abre sem senha. Todo caminho deste módulo que lista ou abre criança passa
    por aqui: ranking, evolução, destaques/mural e o perfil público. A regra
    mora em `services/elegibilidade.py` (fonte única); aqui só se aplica."""
    return elegibilidade.turmas_premiaveis(db, escola.id, escola.ano_letivo_ativo)


def _slides_ativos(config: dict) -> set[str]:
    """Slides ligados pela escola. O servidor só monta o que eles exibem: o
    token é público, então desligar o slide do ranking tem de tirar o ranking
    da resposta (e o perfil público de quem só aparecia nele), não só do
    carrossel."""
    return set(_slides_limpos(config.get("slides", SLIDES_VALIDOS)))


def _com_algum_dado():
    """Filtro do slide `ranking` (e do perfil público de quem aparece nele): só
    a criança com dado de ALGUMA plataforma contratada.

    AUSÊNCIA NÃO É ZERO (scoring.py, invariante 2): sem isto, a escola sem
    coleta (ou com menos crianças com dado que o tamanho do ranking) montava no
    telão sem login um pódio com nome, medalha e "0,00" de quem nunca abriu
    plataforma nenhuma — e, com todas empatadas em zero, a ordem saía do
    desempate alfabético. O SNAPSHOT ZERADO continua (invariante 3: abriu e
    ainda não produziu é zero legítimo — `aferido_*` é a EXISTÊNCIA do
    snapshot, nunca `nota > 0`). E é coerente com a trava de módulo: a dimensão
    de módulo fora do plano é carimbada `aferido=False` pelo motor, então quem
    só tem dado dela também fica de fora. A posição exibida segue a CARIMBADA
    (`Nota.posicao`, a mesma do perfil e do Ranking Geral): pode pular um
    número no fim da lista, entre os zerados — não é renumerada aqui."""
    return or_(Nota.aferido_leitura.is_(True), Nota.aferido_matematica.is_(True))


# Ganho do "Aluno do Dia/Semana/Mês" → plataforma (vocabulário de
# ``modulos.PLATAFORMA_MODULO``): os chips "+N atividades" / "+N livros" de um
# módulo fora do plano não saem no telão.
_PLATAFORMA_DO_GANHO = {
    "atividades": "matific", "estrelas": "matific",
    "livros": "elefante", "tempo_leitura_min": "elefante", "acertos": "elefante",
    "pontos_dificuldade": "elefante",
}


def _destaques_no_plano(destaques, fora: set[str]):
    """Os destaques do telão sem os ganhos das plataformas ``fora`` do plano.
    Só filtra a resposta; quem é destaque (e a nota dele) não muda."""
    if not fora or not isinstance(destaques, dict):
        return destaques
    return {
        janela: ({**item, "ganhos": {
            chave: valor for chave, valor in (item.get("ganhos") or {}).items()
            if _PLATAFORMA_DO_GANHO.get(chave) not in fora}}
            if isinstance(item, dict) else item)
        for janela, item in destaques.items()
    }


def _dados_publicos(db: Session, escola: Escola, config: dict) -> dict:
    limite = int(config.get("max_posicoes", 10))
    ativos = _slides_ativos(config)
    # Telão sem login: nome anonimizado por padrão (primeiro nome + inicial).
    anonimizar = bool(config.get("anonimizar", True))
    nome_pub = (svc_gami.anonimizar_nome if anonimizar else (lambda n: n))
    # K-anonimato: no modo anônimo, a TURMA também é omitida — senão "Ana B." +
    # turma + posição identifica a criança numa turma pequena (LGPD/ECA).
    turma_pub = (lambda _t: None) if anonimizar else (lambda t: t)
    # Um corte só, para TODAS as listas do telão (ranking, evolução, destaques
    # e mural): uma consulta barata por montagem, absorvida pelo cache de 60 s.
    premiaveis = _turmas_premiaveis(db, escola)
    ranking = db.execute(
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: painel PÚBLICO (sem login) nunca pode listar criança
        # arquivada/excluída — a Nota órfã dela não some no recálculo.
        .where(Nota.escola_id == escola.id, Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        # AS FASES NÃO CONCORREM: a premiação é do 1º ao 5º ano. O corte tem de
        # ser repetido aqui porque o painel PÚBLICO monta a lista por conta
        # própria, sem passar por `rankings._ranking` — e a Nota já carimbada de
        # quem saiu da população não some no recálculo, igual à do arquivado
        # logo acima. Sem isto, a tela SEM LOGIN seria o único lugar da rede
        # ainda mostrando a Educação Infantil disputando.
        # Pela MATRÍCULA, não por `Turma`: a segunda consulta não dá JOIN em
        # Turma, e um filtro por `Turma.id` ali viraria produto cartesiano.
        .where(Matricula.turma_id.in_(premiaveis))
        # Ausência não é zero: só quem tem dado de alguma plataforma contratada.
        .where(_com_algum_dado())
        .order_by(Nota.posicao)
        .limit(limite)
    ).all() if "ranking" in ativos else []

    # Telão PÚBLICO: base_no_periodo=True → só o crescimento DENTRO da janela
    # conta (regra justa das premiações). Sem isso, no começo do piloto o
    # acumulado de vida da criança apareceria como "evolução" (caso Antonella).
    # Só quem REALMENTE cresceu (>0) aparece — no início, quando todos empatam
    # em 0, o slide fica vazio em vez de exibir alunos por acaso (sem dado).
    # AS FASES NÃO CONCORREM aqui também: `turma_ids` só RECORTA a lista (a
    # régua continua a da escola inteira, a nota de cada criança é a mesma do
    # sistema) e a posição é renumerada entre quem concorre.
    evolucao_itens = [
        it for it in svc_evolucao.ranking_evolucao(
            db, escola.id, dias=30, base_no_periodo=True, turma_ids=premiaveis)
        if it.nota_evolucao > 0
    ][:limite] if "evolucao" in ativos else []
    # Destaques ("Aluno do Dia/Semana/Mês") e eventos do mural: o mesmo corte —
    # a Educação Infantil não disputa o pódio do telão nem é nomeada nele.
    mural = (svc_gami.mural(db, escola.id, anonimizar=anonimizar, base_no_periodo=True,
                            turma_ids=premiaveis)
             if ativos & {"destaques", "mural"} else {"destaques": [], "eventos": []})

    # Estatísticas REAIS da escola (agregadas dos snapshots atuais — nada é
    # inventado): faixa de indicadores do painel. Custo absorvido pelo cache
    # TTL_PAINEL_S do endpoint.
    # Matific é contador DO ANO (``scoring.snapshots_matific_do_ano``): o retrato
    # de outro ano letivo não soma nas estrelas/atividades do telão.
    # CONTRATO: a plataforma de módulo que a rede não contratou não aparece no
    # telão — o número dela sai `null` (a faixa mostra "—") e nem é somado.
    # A POPULAÇÃO é uma só para a faixa inteira: a criança ATIVA e matriculada no ano
    # letivo — a que "alunos" conta, e a mesma do Painel da coordenação
    # (``rankings.montar_dashboard``). O retrato não é apagado quando a criança sai da
    # escola (é o histórico), e o "atual" de cada uma varre a escola inteira: sem o
    # corte, os livros da criança transferida ou arquivada seguiam somando no telão
    # sem login, ao lado de um "alunos" que já não a contava. Uma matrícula por ano
    # (``uq_matricula_aluno_ano``), então o tamanho da coorte é o total de alunos.
    fora = svc_modulos.plataformas_fora_do_plano(svc_modulos.modulos_da_escola(db, escola))
    coorte = set(db.execute(
        select(Matricula.aluno_id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola.id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).scalars())
    snaps_m = ([] if "matific" in fora else [
        s for aid, s in scoring.snapshots_matific_do_ano(
            db, escola.id, escola.ano_letivo_ativo).items() if aid in coorte])
    snaps_e = ([] if "elefante" in fora else [
        s for aid, s in scoring._snapshots_atuais(
            db, escola.id, SnapshotElefante).items() if aid in coorte])
    estatisticas = {
        "alunos": len(coorte),
        "atividades": (None if "matific" in fora
                       else int(sum(s.atividades for s in snaps_m))),
        # As estrelas que CONTAM (no máximo 5 por atividade: o teto do motor,
        # ``scoring.estrelas_que_contam``) — o telão bate com a nota e os rankings.
        "estrelas": (None if "matific" in fora
                     else int(sum(scoring.estrelas_que_contam(s) for s in snaps_m))),
        "livros": (None if "elefante" in fora
                   else int(sum(s.livros_unicos for s in snaps_e))),
    }

    return {
        "escola": {
            "nome": escola.nome,
            "cor_primaria": svc_relatorios.cor_primaria(db, escola.id),
        },
        "slides": _slides_limpos(config.get("slides", SLIDES_VALIDOS)),
        "intervalo_s": config.get("intervalo_s", 12),
        "ranking": [
            {
                "posicao": nota.posicao,
                "aluno_id": aluno.id,
                "nome": nome_pub(aluno.nome),
                "turma": turma_pub(turma.nome),
                "nota_geral": nota.nota_geral,
            }
            for nota, aluno, turma in ranking
        ],
        "evolucao": [
            {
                "posicao": item.posicao,
                "aluno_id": item.aluno_id,
                "nome": nome_pub(item.nome),
                "turma": turma_pub(item.turma),
                "nota_evolucao": item.nota_evolucao,
            }
            for item in evolucao_itens
        ],
        "destaques": (_destaques_no_plano(mural["destaques"], fora)
                      if "destaques" in ativos else []),
        "estatisticas": estatisticas,
        "mural": [
            {"icone": evento["icone"], "texto": evento["texto"]}
            for evento in (mural["eventos"][:10] if "mural" in ativos else [])
        ],
    }


# Cache em memória do painel público (por escola). O telão faz polling a cada
# poucos segundos e a recomputação é cara (mural + rankings); um TTL curto
# absorve os polls sem servir dados velhos. Por worker uvicorn — aceitável,
# pois os dados mudam poucas vezes por semana. Cada entrada guarda a
# ASSINATURA da config que a gerou (`_assinatura_config`): o PUT da gestão só
# invalida o cache do worker que o atendeu, então os outros workers têm de
# perceber sozinhos que a config mudou (proteção do nome, slides, tamanho).
TTL_PAINEL_S = 60
_cache_painel: dict[int, tuple[float, tuple, dict]] = {}
# Ids exibidos no painel (por escola). Cacheados para o perfil público NÃO
# recomputar a evolução da escola inteira a cada abertura de aluno (mesmo TTL).
_cache_visiveis: dict[int, tuple[float, tuple, set[int]]] = {}

# GERAÇÃO do cache: cada `invalidar_cache_painel` avança a da escola (ou a global,
# quando invalida todas). A montagem anota a geração ANTES de ler o banco e só grava
# no cache se ela não mudou. Sem isto, uma montagem que começou antes do commit de um
# arquivamento (ela leva segundos) lia a criança ainda ativa e gravava o resultado
# DEPOIS da invalidação, valendo pelo TTL inteiro no mesmo processo — a invalidação
# do próprio worker se perdia. (Entre workers, a desatualização de até TTL_PAINEL_S
# continua aceita por desenho.)
_geracao_lock = threading.Lock()
_geracao_global = 0
_geracao_por_escola: dict[int, int] = {}


def _geracao(escola_id: int) -> tuple[int, int]:
    with _geracao_lock:
        return _geracao_global, _geracao_por_escola.get(escola_id, 0)


def _guardar(cache: dict, escola_id: int, geracao: tuple[int, int], entrada: tuple) -> None:
    """Grava a montagem no cache só se nenhuma invalidação chegou enquanto ela era
    feita; senão, o resultado vale só para a resposta que já estava a caminho."""
    with _geracao_lock:
        if (_geracao_global, _geracao_por_escola.get(escola_id, 0)) == geracao:
            cache[escola_id] = entrada


def _assinatura_config(config: dict) -> tuple:
    """O que da config muda o que o telão publica (e quem pode ter o perfil
    aberto). A config é relida do banco a cada requisição em
    `_escola_pelo_token`, então comparar a assinatura custa zero e faz a
    proteção do nome e o desligar de um slide valerem em TODOS os workers na
    requisição seguinte, não só depois do TTL."""
    return (
        bool(config.get("anonimizar", True)),
        tuple(_slides_limpos(config.get("slides", SLIDES_VALIDOS))),
        int(config.get("max_posicoes", 10)),
        config.get("intervalo_s", 12),
    )


def _do_cache(cache: dict, escola_id: int, agora: float, assinatura: tuple):
    """A entrada do cache, se ainda vale: dentro do TTL e gerada pela MESMA
    config. Senão, None (o chamador recalcula e regrava)."""
    em_cache = cache.get(escola_id)
    if (em_cache and agora - em_cache[0] < TTL_PAINEL_S
            and em_cache[1] == assinatura):
        return em_cache[2]
    return None


@publico_router.get("/{token}/painel")
def painel_publico(token: str, response: Response, db: Session = Depends(get_db)):
    resolvido = _escola_pelo_token(db, token)
    if resolvido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Painel não encontrado ou desativado.")
    escola, config = resolvido
    agora = time.monotonic()
    assinatura = _assinatura_config(config)
    dados = _do_cache(_cache_painel, escola.id, agora, assinatura)
    if dados is None:
        geracao = _geracao(escola.id)          # ANTES de ler o banco
        dados = _dados_publicos(db, escola, config)
        _guardar(_cache_painel, escola.id, geracao, (agora, assinatura, dados))
    # NUNCA cachear no navegador/CDN: DESLIGAR o painel (ou trocar o token) tem que
    # bloquear NA HORA, e o payload pode conter nome de criança (anonimizar=False).
    # O cache em memória (_cache_painel) já absorve os polls do telão no servidor.
    response.headers["Cache-Control"] = "no-store"
    return dados


def invalidar_cache_painel(escola_id: int | None = None) -> None:
    """Chamado após recálculo/importação/troca de config para o painel refletir
    logo (inclui o cache de tokens, caso o token tenha rotacionado/desativado).
    Avança a geração: a montagem que estava em andamento não grava no cache."""
    global _geracao_global
    with _geracao_lock:
        if escola_id is None:
            _geracao_global += 1
        else:
            _geracao_por_escola[escola_id] = _geracao_por_escola.get(escola_id, 0) + 1
    if escola_id is None:
        _cache_painel.clear()
        _cache_visiveis.clear()
        _cache_tokens.clear()
    else:
        _cache_painel.pop(escola_id, None)
        _cache_visiveis.pop(escola_id, None)
        # Remove os tokens que apontavam para esta escola (podem ter mudado).
        for tok in [t for t, eid in _cache_tokens.items() if eid == escola_id]:
            _cache_tokens.pop(tok, None)


def _ids_visiveis(db: Session, escola: Escola, config: dict) -> set[int]:
    """Ids dos alunos REALMENTE exibidos no painel (ranking + evolução, top-N).

    O perfil público só abre para quem já aparece no telão. Sem isto, o token
    público (impresso no QR do telão) permitiria varrer aluno_id=1,2,3… e coletar
    nome+notas de TODA a escola — IDOR/enumeração de PII de crianças.

    Resultado cacheado por TTL_PAINEL_S: sem cache, cada abertura de perfil
    recomputaria a evolução da escola inteira (consulta cara, sem login)."""
    agora = time.monotonic()
    assinatura = _assinatura_config(config)
    em_cache = _do_cache(_cache_visiveis, escola.id, agora, assinatura)
    if em_cache is not None:
        return em_cache
    geracao = _geracao(escola.id)              # ANTES de ler o banco (ver _guardar)
    limite = int(config.get("max_posicoes", 10))
    ativos = _slides_ativos(config)
    # AS FASES NÃO CONCORREM: o conjunto tem de casar com o que o telão exibe
    # (`_dados_publicos`), senão abriria o perfil de quem não está no telão.
    premiaveis = _turmas_premiaveis(db, escola)
    ids: set[int] = set() if "ranking" not in ativos else set(db.execute(
        select(Aluno.id)
        .join(Nota, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .where(Nota.escola_id == escola.id,
               Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        # AS FASES NÃO CONCORREM: a premiação é do 1º ao 5º ano. O corte tem de
        # ser repetido aqui porque o painel PÚBLICO monta a lista por conta
        # própria, sem passar por `rankings._ranking` — e a Nota já carimbada de
        # quem saiu da população não some no recálculo, igual à do arquivado
        # logo acima. Sem isto, a tela SEM LOGIN seria o único lugar da rede
        # ainda mostrando a Educação Infantil disputando.
        # Pela MATRÍCULA, não por `Turma`: a segunda consulta não dá JOIN em
        # Turma, e um filtro por `Turma.id` ali viraria produto cartesiano.
        .where(Matricula.turma_id.in_(premiaveis))
        # O mesmo corte do slide: quem não tem dado não está no telão, então o
        # perfil público dele não abre.
        .where(_com_algum_dado())
        .order_by(Nota.posicao)
        .limit(limite)
    ).scalars())
    # A evolução também é exibida (slide próprio) — seus alunos podem ser abertos.
    # base_no_periodo=True + só quem cresceu (>0): mesma regra do payload público
    # (não expõe, no começo do piloto, quem só tem acumulado como "evolução" nem
    # abre perfil de aluno que não aparece de fato no telão). Mesmo recorte das
    # Fases do payload: sem ele, a criança da Fase que lidera o crescimento
    # entraria aqui e o perfil público dela abriria (200).
    if "evolucao" not in ativos:
        _guardar(_cache_visiveis, escola.id, geracao, (agora, assinatura, ids))
        return ids
    for item in [it for it in svc_evolucao.ranking_evolucao(
            db, escola.id, dias=30, base_no_periodo=True, turma_ids=premiaveis)
            if it.nota_evolucao > 0][:limite]:
        ids.add(item.aluno_id)
    _guardar(_cache_visiveis, escola.id, geracao, (agora, assinatura, ids))
    return ids


@publico_router.get("/{token}/alunos/{aluno_id}")
def perfil_publico(token: str, aluno_id: int, response: Response,
                   db: Session = Depends(get_db)):
    """Perfil público restrito a dados pedagógicos (PRD §120)."""
    # Nunca cachear: pode ter nome de criança (anonimizar=False) e o desligar/
    # trocar token tem que bloquear na hora — não sobreviver no cache de borda.
    response.headers["Cache-Control"] = "no-store"
    resolvido = _escola_pelo_token(db, token)
    if resolvido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Painel não encontrado ou desativado.")
    escola, config = resolvido
    aluno = db.get(Aluno, aluno_id)
    # Só alunos exibidos no painel: bloqueia enumeração por aluno_id sequencial.
    if (aluno is None or aluno.escola_id != escola.id or aluno.status != "ativo"
            or aluno_id not in _ids_visiveis(db, escola, config)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    # AS FASES NÃO CONCORREM — e o perfil público só existe para quem concorre
    # no telão. `_ids_visiveis` já não as inclui; esta é a segunda linha: um
    # slide futuro que esqueça o corte não reabre o perfil de uma criança da
    # Educação Infantil. Mesma resposta e mesma mensagem do 404 acima: o link
    # público não revela se a criança existe nem em que etapa ela está.
    if db.execute(
        select(Matricula.id)
        .where(Matricula.aluno_id == aluno_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Matricula.turma_id.in_(_turmas_premiaveis(db, escola)))
        .limit(1)
    ).first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo)
    ).first()
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()
    gamificacao = svc_gami.gamificacao_do_aluno(db, escola.id, aluno_id)

    # Estritamente pedagógico: nome, turma, notas e conquistas. O nome sai
    # anonimizado por padrão (mesma regra do telão) — este link é público.
    anonimizar = bool(config.get("anonimizar", True))
    # CONTRATO: nota de plataforma de módulo fora do plano sai nula (mesma regra
    # de ``rankings._ranking`` e do perfil autenticado).
    fora = svc_modulos.plataformas_fora_do_plano(svc_modulos.modulos_da_escola(db, escola))
    # AUSÊNCIA NÃO É ZERO (scoring.py, invariante 2): o motor grava 0.0 na nota
    # da matéria em que a criança NÃO é aferida. Sem o corte, quem só usa o
    # Matific aparecia com "Leitura 0,0" nesta página aberta a qualquer um. A
    # nota sai nula (a página mostra "—") e o `aferido_*` vai junto, como no
    # Ranking Geral; o retrato ZERADO (aferido, abriu e não produziu) segue 0,0.
    aferido_l = bool(nota is not None and nota.aferido_leitura)
    aferido_m = bool(nota is not None and nota.aferido_matematica)
    return {
        "nome": svc_gami.anonimizar_nome(aluno.nome) if anonimizar else aluno.nome,
        # K-anonimato: turma omitida no modo anônimo (não reidentificar).
        "turma": None if anonimizar else (matricula[1].nome if matricula else None),
        "posicao": nota.posicao if nota else None,
        "nota_matific": (nota.nota_matific
                         if aferido_m and "matific" not in fora else None),
        "nota_elefante": (nota.nota_elefante
                          if aferido_l and "elefante" not in fora else None),
        "aferido_leitura": aferido_l,
        "aferido_matematica": aferido_m,
        "nota_geral": nota.nota_geral if nota else 0.0,
        "nivel": gamificacao["nivel"],
        "xp": gamificacao["xp"],
        "conquistas": [
            {"nome": c["nome"], "icone": c["icone"], "descricao": c["descricao"]}
            for c in gamificacao["conquistas"] if c["atingida"]
        ],
        "escola": escola.nome,
    }


@publico_router.get("/rede/{token}")
def painel_publico_rede(token: str, response: Response, db: Session = Depends(get_db)):
    """Vitrine PÚBLICA da Secretaria (sem login): as melhores escolas da rede em
    leitura e matemática. Só agregado por ESCOLA — nunca nome de criança."""
    from app.services import rede as svc_rede

    rede = svc_rede.rede_pelo_token_publico(db, token)
    if rede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Painel público não encontrado ou desativado.")
    # NUNCA cachear: DESLIGAR a vitrine (token=None) tem que bloquear NA HORA. Com
    # cache, o link continuava servindo o quadro antigo por minutos após o desligar.
    response.headers["Cache-Control"] = "no-store"
    return svc_rede.painel_publico_rede(db, rede.id)


# O router "pai" agrega os dois para o main.py registrar de uma vez
router.include_router(config_router)
router.include_router(publico_router)
