"""Assistente Pedagógico (PRD §155–§172).

Regras inegociáveis:
  * O contexto é montado AQUI, no backend, somente com dados da escola do
    usuário — o isolamento multi-escolas vale também para a IA (§169).
  * O modelo recebe instruções para responder apenas com base nesse
    contexto e recusar qualquer outra coisa.
  * Toda conversa fica registrada em `conversas_ia`/`mensagens_ia`.
  * Se o provedor externo falhar (erro de rede, chave recusada, resposta fora do
    formato ou qualquer outra exceção dele), o provedor local responde — o
    assistente nunca sai do ar por causa de terceiros.

Provedor externo e LGPD (dados de crianças — decisão documentada):
  * O provedor PADRÃO é `local`: determinístico, sem rede, sem chave. Por
    padrão NENHUM dado de aluno sai da infraestrutura.
  * Um provedor externo (Anthropic/OpenAI) só é usado quando o Admin Global o
    liga para a escola com uma chave (opt-in por escola; P9 — o admin da escola
    vê o estado e pode desligar, `routers/ia.py`), ou quando o AMBIENTE do
    servidor (AI_PROVIDER) o define para quem não tem configuração própria.
  * Minimização de dados: mesmo nesse opt-in, NENHUM dado identificável de aluno
    sai para o provedor externo. Contexto e conversa (inclusive o histórico)
    passam por ``_Pseudonimizador`` antes de sair:
      - nome completo de qualquer aluno da escola -> "Aluno NNN" (sem diferenciar
        caixa nem acento: "joao pedro" casa "João Pedro");
      - na conversa, pedaço de nome (só o primeiro nome, só um sobrenome) ->
        "[nome omitido]" (no contexto, montado aqui, o nome só sai inteiro);
      - e-mail -> "[e-mail omitido]";
      - RA conhecido da ficha (na conversa) e qualquer número com 6+ dígitos
        (RA, CPF, RG, telefone, CEP; datas ficam), inclusive colado a letra
        ("RA123456789", "nº4321") -> "[identificador omitido]".
    A resposta é reidentificada (token -> nome) aqui, no backend. O provedor
    externo vê rótulos, turmas, notas, índices e o nome da escola.
  * Sem NER: nome de quem NÃO é aluno da escola (responsável, aluno de outra
    escola) ou apelido/grafia errada digitados na pergunta não são reconhecidos.
    Na conversa, pedaço de nome que coincide com palavra comum ("dias", "Rosa")
    também é omitido — privacidade antes de precisão. Para perguntar de um aluno,
    use o nome completo (o modo local tem o mesmo requisito).
"""
from __future__ import annotations

import logging
import re
import unicodedata

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

logger = logging.getLogger("constela.ia")

from app.core.security import (
    CIFRA_ANTERIOR,
    CIFRA_PRIMARIA,
    cifrar_segredo,
    decifrar_segredo,
    situacao_da_cifra,
)
from app.models import (
    Aluno,
    Configuracao,
    ConversaIA,
    Escola,
    Matricula,
    MensagemIA,
    Nota,
    Turma,
)
from app.services import evolucao, insights, scoring
from app.services import modulos as svc_modulos
from app.services.ia import ErroProvedorIA, obter_provedor
from app.services.ia.provedores import LocalProvedor

PROVEDORES_VALIDOS = ("local", "anthropic", "openai")
CONTINGENCIA = "local (contingência)"


class ConversaNaoEncontrada(LookupError):
    """A conversa pedida não existe ou não é de quem pergunta (a rota responde 404)."""


def _config_row(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(
        select(Configuracao).where(Configuracao.escola_id == escola_id,
                                   Configuracao.namespace == "assistente",
                                   Configuracao.chave == "valores")
    ).scalar_one_or_none()


def _chave_legivel(valores: dict) -> bool:
    """A chave de API salva abre com o anel de chaves atual? Depois de uma troca da
    DATA_ENCRYPTION_KEY sem recadastro, a cifra continua gravada mas nenhuma chave a
    abre: o assistente cai no modo local, e dizer "chave configurada" era mentira.
    Só a situação da cifra — o texto da chave não sai daqui."""
    return situacao_da_cifra(valores.get("api_key_cifrada")) in (CIFRA_PRIMARIA,
                                                                 CIFRA_ANTERIOR)


def config_assistente(db: Session, escola_id: int) -> dict:
    """Configuração do assistente salva pela interface (sem expor a chave).
    Escola sem configuração própria espelha o AMBIENTE — o que o status mostra
    é o que de fato responde."""
    from app.core.config import settings

    row = _config_row(db, escola_id)
    valores = dict(row.valor or {}) if row else {}
    if not valores.get("provedor"):
        return {
            "provedor": settings.AI_PROVIDER.strip().lower() or "local",
            "modelo": settings.AI_MODEL or "",
            "chave_definida": bool(settings.AI_API_KEY),
        }
    return {
        "provedor": valores["provedor"],
        "modelo": valores.get("modelo") or "",
        "chave_definida": _chave_legivel(valores),
    }


def salvar_config_assistente(db: Session, escola_id: int, provedor: str,
                             api_key: str | None, modelo: str | None) -> dict:
    """Grava provedor/modelo e a chave de API CIFRADA (``cifrar_segredo``: Fernet
    com a DATA_ENCRYPTION_KEY; a SECRET_KEY só decifra as cifras legadas).
    `api_key` vazio mantém a chave já salva DO MESMO provedor; ao trocar de
    provedor a chave antiga é descartada (a chave de um fornecedor nunca pode
    ser enviada a outro). Levanta ValueError quando falta a chave.
    NÃO faz commit — quem chama registra a auditoria e commita junto."""
    row = _config_row(db, escola_id)
    valores = dict(row.valor or {}) if row else {}
    api_key = (api_key or "").strip()
    provedor_anterior = valores.get("provedor") or "local"
    if provedor != provedor_anterior and not api_key:
        valores.pop("api_key_cifrada", None)
    if provedor != "local" and not api_key and not valores.get("api_key_cifrada"):
        raise ValueError("Informe a chave de API do provedor escolhido.")
    if provedor != "local" and not api_key and not _chave_legivel(valores):
        # "Manter a atual" manteria uma cifra que nada abre (DEK trocada): recusa sem
        # tocar no que está gravado (voltar às chaves antigas ainda a reabriria).
        raise ValueError("A chave de API salva não abre mais com a chave de cifra do "
                         "servidor (trocada desde que foi gravada): informe a chave de "
                         "API de novo.")

    valores["provedor"] = provedor
    valores["modelo"] = (modelo or "").strip()
    if api_key:
        valores["api_key_cifrada"] = cifrar_segredo(api_key)
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="assistente",
                           chave="valores", valor=valores)
        db.add(row)
    else:
        row.valor = valores
    db.flush()
    return {
        "provedor": provedor,
        "modelo": valores["modelo"],
        "chave_definida": _chave_legivel(valores),
    }


def _provedor_da_escola(db: Session, escola_id: int):
    """Provedor conforme a configuração da escola; sem ela, o do ambiente."""
    row = _config_row(db, escola_id)
    valores = dict(row.valor or {}) if row else {}
    if not valores.get("provedor"):
        return obter_provedor()
    return obter_provedor(
        provedor=valores["provedor"],
        api_key=decifrar_segredo(valores.get("api_key_cifrada")),
        modelo=valores.get("modelo") or None,
    )

MAX_MENSAGENS_CONTEXTO = 12  # últimas mensagens da conversa enviadas ao modelo

INSTRUCOES = """Você é o Assistente Pedagógico do Constela Edu (sistema de
gestão e premiação escolar) de uma escola brasileira de ensino fundamental.

REGRAS OBRIGATÓRIAS:
1. Responda SOMENTE com base nos dados do sistema apresentados abaixo.
   Eles são a única fonte de verdade. Se a informação não estiver lá,
   diga claramente que não há dados suficientes no sistema.
2. Nunca invente números, nomes ou fatos. Nunca use conhecimento externo
   sobre alunos ou escolas.
3. Recuse com educação perguntas fora do contexto pedagógico desta escola.
4. Responda em português do Brasil, em tom profissional e acolhedor,
   pensado para professores e coordenadores.
5. Ao citar um dado, seja específico (nome, número, posição).

DADOS DO SISTEMA (fonte única de verdade):
"""


def montar_contexto(db: Session, escola_id: int) -> str:
    """Fotografia textual dos dados da escola — tudo que a IA pode "ver"."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo

    ranking = db.execute(
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: aluno arquivado/inativo NUNCA entra no contexto da IA —
        # sua Nota órfã (arquivar não a apaga) não pode reintroduzir o nome dele,
        # inclusive na ida ao provedor externo. Mesmo filtro do ranking/painel.
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo")
        .order_by(Nota.posicao)
    ).all()

    # CONTRATO: o que a rede não assinou não entra no contexto — nem a nota, nem
    # o pódio, nem os ganhos daquela plataforma. Com provedor externo o contexto
    # sai da infraestrutura (minimização), e o modo local responderia "os
    # melhores no Matific" a uma rede que só contratou Leitura. Escola sem rede
    # (ou com os dois módulos) segue com tudo, como sempre.
    contratadas = scoring.dimensoes_contratadas(db, escola)
    com_matematica = "matematica" in contratadas
    com_leitura = "leitura" in contratadas

    def por_plataforma(nota: Nota) -> str:
        partes = []
        if com_matematica:
            partes.append(f", Matific {nota.nota_matific:.1f}")
        if com_leitura:
            partes.append(f", Elefante {nota.nota_elefante:.1f}")
        return "".join(partes)

    linhas_ranking = [
        f"- {nota.posicao}º: {aluno.nome} ({turma.nome}) — geral {nota.nota_geral:.1f}"
        f"{por_plataforma(nota)}"
        for nota, aluno, turma in ranking[:15]
    ]
    # Pódios por PLATAFORMA — para perguntas "melhores do Matific/Elefante".
    def podio(metrica) -> list[str]:
        ordenado = sorted(ranking, key=lambda r: metrica(r[0]), reverse=True)
        return [
            f"- {i}º: {aluno.nome} ({turma.nome}) — nota {metrica(nota):.1f}"
            for i, (nota, aluno, turma) in enumerate(ordenado[:10], start=1)
        ]
    linhas_alunos = [
        f"- {aluno.nome}: turma {turma.nome}, {nota.posicao}º lugar, "
        f"geral {nota.nota_geral:.1f}{por_plataforma(nota)}"
        for nota, aluno, turma in ranking
    ]

    def ganhos_do_periodo(ganhos: dict) -> str:
        partes = []
        if com_matematica:
            partes.append(f"+{ganhos['atividades']:.0f} atividades")
        if com_leitura:
            partes.append(f"+{ganhos['livros']:.0f} livros")
        return ", ".join(partes)

    itens_evolucao = evolucao.ranking_evolucao(db, escola_id, dias=30)[:10]
    linhas_evolucao = [
        f"- {item.posicao}º: {item.nome} ({item.turma}) — evolução {item.nota_evolucao:.1f} "
        f"({ganhos_do_periodo(item.ganhos)})"
        for item in itens_evolucao
    ]

    indices = insights.indices_da_escola(db, escola_id)
    linhas_indices = [
        f"- {item['nome']} ({item['turma']}): engajamento {item['engajamento']}, "
        f"evolução {item['evolucao']}, persistência {item['persistencia']}"
        for item in indices
    ]

    alertas = insights.alertas_da_escola(db, escola_id)
    linhas_alertas = [f"- [{alerta['gravidade']}] {alerta['texto']}" for alerta in alertas]

    resumo_escola = evolucao.resumo_escola(db, escola_id)
    linhas_turmas = [
        f"- {t['turma']['nome']} ({t['turma']['ano_escolar']}): {t['total_alunos']} alunos, "
        f"média geral {t['media_geral']:.1f}"
        + (f", {t['indicadores']['livros_unicos']} livros lidos" if com_leitura else "")
        for t in resumo_escola["turmas"] if t
    ]

    def secao(nome: str, linhas: list[str], vazio: str) -> str:
        corpo = "\n".join(linhas) if linhas else vazio
        return f"### {nome}\n{corpo}\n"

    # O que ficou fora do plano é dito com todas as letras (sem dado de criança):
    # o modelo e o modo local respondem "não faz parte do plano", em vez de "não
    # há dados" ou de um pódio vindo de retrato antigo.
    fora_do_plano = [
        f"- {svc_modulos.CATALOGO[modulo]['nome']}: não faz parte do plano desta rede; "
        "o sistema não tem dados dela para responder."
        for modulo, contratado in (("leitura", com_leitura),
                                   ("matematica", com_matematica))
        if not contratado
    ]

    return "\n".join([
        secao("RESUMO", [
            f"- Escola: {escola.nome} (ano letivo {ano})",
            f"- Alunos com nota: {len(ranking)}",
            f"- Turmas: {len(resumo_escola['turmas'])}",
            f"- Alertas ativos: {len(alertas)}",
        ], "- Sem dados."),
        *([secao("FORA_DO_PLANO", fora_do_plano, "")] if fora_do_plano else []),
        secao("RANKING", linhas_ranking, "- Nenhuma nota calculada ainda."),
        *([secao("RANKING_MATIFIC", podio(lambda n: n.nota_matific),
                 "- Nenhuma nota calculada ainda.")] if com_matematica else []),
        *([secao("RANKING_ELEFANTE", podio(lambda n: n.nota_elefante),
                 "- Nenhuma nota calculada ainda.")] if com_leitura else []),
        secao("EVOLUCAO", linhas_evolucao, "- Sem dados de evolução no período."),
        secao("INDICES", linhas_indices, "- Sem índices calculados."),
        secao("ALERTAS", linhas_alertas, "- Nenhum alerta no momento."),
        secao("TURMAS", linhas_turmas, "- Nenhuma turma cadastrada."),
        secao("ALUNOS", linhas_alunos, "- Nenhum aluno com nota."),
    ])


# --- Pseudonimização para provedores externos (LGPD) --------------------------

# Provedores que enviam o contexto para fora da infraestrutura. Só para eles a
# pseudonimização é aplicada; o `local` roda no próprio backend com nomes reais.
_PROVEDORES_EXTERNOS = ("anthropic", "openai")

_OMITIDO_NOME = "[nome omitido]"
_OMITIDO_EMAIL = "[e-mail omitido]"
_OMITIDO_ID = "[identificador omitido]"

_NOTA_PSEUDONIMO = (
    "\n\nIMPORTANTE: cada aluno aparece por um identificador fixo "
    '(ex.: "Aluno 007"). Refira-se aos alunos EXATAMENTE por esse identificador, '
    "sem alterá-lo, traduzi-lo ou inventar nomes. "
    f'"{_OMITIDO_NOME}", "{_OMITIDO_EMAIL}" e "{_OMITIDO_ID}" marcam dados '
    "pessoais retirados por privacidade: não tente adivinhá-los. Se a pergunta "
    "depender de um aluno citado só em parte, peça o nome completo dele."
)

# Palavra = sequência de letras (com acento). Dígitos, "_" e pontuação separam.
_RE_PALAVRA = re.compile(r"[^\W\d_]+")
# Entre as palavras de um nome completo: só espaço/pontuação (nada de letra ou
# dígito): "Ana  Souza", "Ana-Souza", "D'Ávila" e "Ana" + quebra + "Souza" casam.
_RE_ENTRE_PALAVRAS_DO_NOME = re.compile(r"[\W_]+")
# Partículas e sufixos de nome que, SOZINHOS, não identificam ninguém: ficam no
# texto (mas contam dentro do nome completo, que vira token inteiro).
_NAO_SAO_PEDACO_DE_NOME = frozenset({
    "de", "da", "do", "das", "dos", "e", "di", "du", "del", "della", "der",
    "van", "von", "la", "le", "y", "filho", "filha", "neto", "neta", "junior",
    "jr", "sobrinho", "sobrinha"})
_TAM_MIN_PEDACO = 3            # "Ana", "Léo": primeiro nome curto também sai
_RE_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
# Número "de documento": dígitos com . - / no meio e DV "X" opcional no fim. As
# bordas são de DÍGITO, não de palavra: número colado a letra ("RA123456789",
# "nº123456789-0", "ra_4321", "123456789SP") também é avaliado. O "X" só conta
# como DV quando não começa uma palavra ("4321xis" -> "4321" + "xis").
_RE_NUMERO = re.compile(r"(?<!\d)\d(?:[.\-/]?\d)*(?:-?[xX](?![^\W\d_]))?(?!\d)")
_RE_DIGITOS = re.compile(r"\d+")
_RE_DATA = re.compile(r"\d{1,2}[./\-]\d{1,2}(?:[./\-]\d{2,4})?"
                      r"|\d{4}[./\-]\d{1,2}[./\-]\d{1,2}")
_MIN_DIGITOS_IDENTIFICADOR = 6  # RA (9+), CPF (11), RG (8+), telefone (8+), CEP (8)
_TAM_MIN_ID_CONHECIDO = 4       # RA/RM curto da ficha: casado pelo valor (e dígitos)
_CAMPOS_ID_DA_FICHA = ("ra", "rm")


def _sem_acento(texto: str) -> str:
    """Chave de comparação: sem acento e sem caixa ("JOÃO" -> "joao")."""
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").casefold()


def _canonico_id(valor) -> str:
    """Identificador só com letras/dígitos, sem zeros à esquerda: "000.123-4" e
    "1234" são o mesmo RA."""
    return re.sub(r"[^0-9a-z]", "", _sem_acento(str(valor or ""))).lstrip("0")


class _Pseudonimizador:
    """Tira do texto todo dado identificável de aluno antes do provedor externo.

    Montado uma vez por pergunta com o mapa {nome real: token} e os
    identificadores conhecidos (RA/RM da ficha). Ordem: e-mail, números de
    documento e, por último, nomes, numa varredura por PALAVRA (sem acento e sem
    caixa): a sequência mais longa que forma o nome completo de um aluno vira o
    token dele; na CONVERSA, qualquer outra palavra que seja pedaço de nome de
    aluno vira "[nome omitido]". Linear no tamanho do texto (o contexto de uma
    escola grande tem milhares de nomes).

    ``conversa=False`` é o CONTEXTO, montado aqui a partir do banco: nele o nome
    do aluno só aparece inteiro (``Aluno.nome``, coberto pelo mapa) e não há ficha.
    Não troca pedaço de nome nem RA curto ali, para não estragar os textos fixos
    ("há 12 dias" com um aluno de sobrenome Dias; "português do Brasil"), as
    turmas e as contagens. E-mail e número longo saem mesmo assim."""

    def __init__(self, mapa: dict[str, str], identificadores=()):
        self._nomes: dict[str, list[tuple[tuple[str, ...], str]]] = {}
        self._pedacos: set[str] = set()
        for nome, token in mapa.items():
            chaves = tuple(_sem_acento(p) for p in
                           _RE_PALAVRA.findall(unicodedata.normalize("NFC", nome or "")))
            if not chaves:
                continue
            self._nomes.setdefault(chaves[0], []).append((chaves, token))
            self._pedacos.update(c for c in chaves if len(c) >= _TAM_MIN_PEDACO
                                 and c not in _NAO_SAO_PEDACO_DE_NOME)
        for candidatos in self._nomes.values():
            candidatos.sort(key=lambda par: len(par[0]), reverse=True)  # mais longo 1º
        self._ids: set[str] = set()
        for canonico in map(_canonico_id, identificadores):
            # RA/RM gravado com letra ("A1234", "123456789SP"): o número escrito
            # no texto é casado também pelos dígitos seguidos dele.
            for chave in (canonico, *(d.lstrip("0") for d in _RE_DIGITOS.findall(canonico))):
                if len(chave) >= _TAM_MIN_ID_CONHECIDO:
                    self._ids.add(chave)

    def __call__(self, texto: str, *, conversa: bool = True) -> str:
        texto = unicodedata.normalize("NFC", texto or "")
        texto = _RE_EMAIL.sub(_OMITIDO_EMAIL, texto)
        texto = _RE_NUMERO.sub(lambda achado: self._numero(achado, conversa), texto)
        return self._nomes_no_texto(texto, conversa)

    def _numero(self, achado: re.Match, conversa: bool) -> str:
        bruto = achado.group(0)
        if conversa and self._ids:
            canonico = _canonico_id(bruto)
            # "4321X" com a ficha "4321": o X digitado como DV não salva o RA.
            if canonico in self._ids or canonico.removesuffix("x") in self._ids:
                return _OMITIDO_ID
        digitos = sum(ch.isdigit() for ch in bruto)
        if digitos >= _MIN_DIGITOS_IDENTIFICADOR and not _RE_DATA.fullmatch(bruto):
            return _OMITIDO_ID
        return bruto

    def _nomes_no_texto(self, texto: str, conversa: bool) -> str:
        palavras = [(m.start(), m.end(), _sem_acento(m.group(0)))
                    for m in _RE_PALAVRA.finditer(texto)]
        saida: list[str] = []
        cursor = i = 0
        while i < len(palavras):
            inicio, fim, chave = palavras[i]
            troca, avanco = None, 1
            for chaves, token in self._nomes.get(chave, ()):
                if self._casa_nome(texto, palavras, i, chaves):
                    troca, avanco = token, len(chaves)
                    fim = palavras[i + avanco - 1][1]
                    break
            if troca is None and conversa and chave in self._pedacos:
                troca = _OMITIDO_NOME
            if troca is not None:
                saida.append(texto[cursor:inicio])
                saida.append(troca)
                cursor = fim
            i += avanco
        saida.append(texto[cursor:])
        return "".join(saida)

    @staticmethod
    def _casa_nome(texto: str, palavras: list, i: int, chaves: tuple[str, ...]) -> bool:
        if i + len(chaves) > len(palavras):
            return False
        for j, chave in enumerate(chaves):
            if palavras[i + j][2] != chave:
                return False
            if j and not _RE_ENTRE_PALAVRAS_DO_NOME.fullmatch(
                    texto[palavras[i + j - 1][1]:palavras[i + j][0]]):
                return False
        return True


def _alunos_da_escola(escola_id: int):
    """Filtro dos alunos cujo dado pode aparecer no contexto da escola: os dela
    (QUALQUER status) e quem tem nota ou matrícula nela, mesmo com a ficha hoje
    noutra escola (o ranking do contexto parte de ``Nota.escola_id``)."""
    return or_(
        Aluno.escola_id == escola_id,
        Aluno.id.in_(select(Nota.aluno_id).where(Nota.escola_id == escola_id)),
        Aluno.id.in_(select(Matricula.aluno_id).where(Matricula.escola_id == escola_id)),
    )


def _identificadores_da_ficha(db: Session, escola_id: int) -> list[str]:
    """RA/RM gravados na ficha dos alunos da escola."""
    fichas = db.execute(
        select(Aluno.ficha).where(_alunos_da_escola(escola_id))).scalars().all()
    return [str(ficha[campo]) for ficha in fichas if isinstance(ficha, dict)
            for campo in _CAMPOS_ID_DA_FICHA if ficha.get(campo)]


def _mapa_pseudonimos(db: Session, escola_id: int) -> dict[str, str]:
    """{nome_real: "Aluno NNN"} para TODOS os alunos da escola (QUALQUER status).

    Rede de segurança: o mapa cobre até arquivados/inativos de propósito — se
    algum nome escapar por qualquer seção do contexto, ele ainda é trocado por
    token antes de sair para o provedor externo (nunca vaza nome real). Cobre
    também quem tem nota/matrícula na escola com a ficha noutra.
    Ordem estável (por nome) e largura fixa com zeros à esquerda: nenhum token é
    prefixo de outro, então a reidentificação por substituição direta é exata."""
    nomes = db.execute(
        select(Aluno.nome).where(_alunos_da_escola(escola_id))
        .distinct().order_by(Aluno.nome)
    ).scalars().all()
    largura = max(2, len(str(len(nomes) or 1)))
    return {nome: f"Aluno {i:0{largura}d}" for i, nome in enumerate(nomes, start=1)}


def _pseudonimizar(texto: str, mapa: dict[str, str], identificadores=(), *,
                   conversa: bool = True) -> str:
    """Atalho de uma chamada só (testes/diagnóstico); ``perguntar`` monta o
    ``_Pseudonimizador`` uma vez e o aplica a contexto e conversa."""
    return _Pseudonimizador(mapa, identificadores)(texto, conversa=conversa)


def _reidentificar(texto: str, mapa: dict[str, str]) -> str:
    """Volta token -> nome real na resposta. Tokens têm largura fixa (nenhum é
    prefixo de outro), então a substituição direta é segura."""
    for nome, token in mapa.items():
        texto = texto.replace(token, nome)
    return texto


def _contingencia(sistema: str, mensagens: list[dict]) -> tuple[str, str]:
    return LocalProvedor().responder(sistema, mensagens), CONTINGENCIA


def _responder(db: Session, escola_id: int, sistema: str,
               mensagens: list[dict]) -> tuple[str, str]:
    """(resposta, quem respondeu) pelo provedor da escola. Quando o externo falha,
    responde o modo local (``CONTINGENCIA``): o assistente nunca sai do ar.

    Antes da chamada ao provedor EXTERNO, faz o commit da transação (até aqui, só
    leituras): durante a rede (no máximo ``ia.provedores.PRAZO_TOTAL_S``, a chamada
    inteira), a conexão do banco volta ao pool em vez de ficar presa "idle in
    transaction"."""
    try:
        # A criação pode falhar (ex.: chave ausente/errada): cai no modo local.
        provedor = _provedor_da_escola(db, escola_id)
    except ErroProvedorIA as erro:
        logger.warning("Provedor de IA indisponível; usando modo local: %s",
                       erro, exc_info=True)
        return _contingencia(sistema, mensagens)
    if provedor.nome not in _PROVEDORES_EXTERNOS:
        return provedor.responder(sistema, mensagens), provedor.nome

    # LGPD: nenhum dado identificável de criança (nome, pedaço de nome, RA,
    # e-mail, nº de documento) sai para provedor externo. Limpa contexto +
    # conversa inteira (histórico incluso); reidentifica aqui.
    mapa = _mapa_pseudonimos(db, escola_id)
    pseudonimizar = _Pseudonimizador(mapa, _identificadores_da_ficha(db, escola_id))
    sistema_env = pseudonimizar(sistema, conversa=False) + _NOTA_PSEUDONIMO
    mensagens_env = [
        {"papel": m["papel"], "conteudo": pseudonimizar(m["conteudo"])}
        for m in mensagens
    ]
    db.commit()
    try:
        resposta = _reidentificar(provedor.responder(sistema_env, mensagens_env), mapa)
    except ErroProvedorIA as erro:
        logger.warning("Provedor de IA indisponível; usando modo local: %s",
                       erro, exc_info=True)
        return _contingencia(sistema, mensagens)
    except Exception:  # noqa: BLE001 — terceiro fora do contrato: o plano B responde
        # Exceção que o provedor não converteu em ErroProvedorIA (formato novo da
        # resposta, defeito do SDK): vai ao log de erro, e quem pergunta não vê 500.
        logger.exception("Falha inesperada no provedor de IA externo; usando modo local")
        return _contingencia(sistema, mensagens)
    return resposta, provedor.nome


def _conversa_do_usuario(db: Session, conversa_id: int, escola_id: int,
                         usuario_id: int) -> ConversaIA:
    conversa = db.get(ConversaIA, conversa_id)
    if conversa is None or conversa.escola_id != escola_id \
            or conversa.usuario_id != usuario_id:
        raise ConversaNaoEncontrada("Conversa não encontrada.")
    return conversa


def perguntar(db: Session, escola_id: int, usuario_id: int,
              pergunta: str, conversa_id: int | None = None) -> dict:
    """Fluxo completo: contexto → provedor → registro da conversa.

    Primeiro só LÊ (conversa, histórico, contexto); a conversa nova e as duas
    mensagens são gravadas DEPOIS da resposta, numa transação curta (com provedor
    externo, ``_responder`` encerra a de leitura antes da rede).

    Levanta ``ConversaNaoEncontrada`` quando ``conversa_id`` não é de quem pergunta
    (ou deixou de existir enquanto o provedor respondia)."""
    if conversa_id is not None:
        _conversa_do_usuario(db, conversa_id, escola_id, usuario_id)
        historico = db.execute(
            select(MensagemIA).where(MensagemIA.conversa_id == conversa_id)
            .order_by(MensagemIA.id.desc()).limit(MAX_MENSAGENS_CONTEXTO)
        ).scalars().all()
    else:
        historico = []
    mensagens = [
        {"papel": m.papel, "conteudo": m.conteudo} for m in reversed(historico)
    ]
    mensagens.append({"papel": "usuario", "conteudo": pergunta})

    sistema = INSTRUCOES + montar_contexto(db, escola_id)
    resposta, provedor_usado = _responder(db, escola_id, sistema, mensagens)

    if conversa_id is not None:
        # Relida: a conversa pode ter sido apagada enquanto o provedor respondia
        # (retenção, exclusão da conta): 404, não mensagem órfã.
        conversa = _conversa_do_usuario(db, conversa_id, escola_id, usuario_id)
    else:
        titulo = pergunta.strip()[:80] or "Nova conversa"
        conversa = ConversaIA(escola_id=escola_id, usuario_id=usuario_id, titulo=titulo)
        db.add(conversa)
        db.flush()
    conversa.provedor = provedor_usado
    db.add(MensagemIA(conversa_id=conversa.id, papel="usuario", conteudo=pergunta))
    db.add(MensagemIA(conversa_id=conversa.id, papel="assistente", conteudo=resposta))
    db.commit()

    return {
        "conversa_id": conversa.id,
        "titulo": conversa.titulo,
        "provedor": provedor_usado,
        "resposta": resposta,
    }


def purgar_conversas_ia_expiradas(db: Session, dias: int | None = None) -> int:
    """Retenção LGPD (direito ao esquecimento / minimização): apaga conversas do
    assistente com created_at mais antigo que `dias` (padrão
    settings.IA_RETENCAO_DIAS). A cascata (migração 0003) remove as mensagens
    junto. Idempotente. Devolve o nº de conversas apagadas."""
    from app.core.config import settings
    dias = settings.IA_RETENCAO_DIAS if dias is None else dias
    # created_at é gravado em UTC mas a coluna DateTime (sem tz) devolve NAIVE do
    # banco (SQLite/Postgres); usa corte NAIVE em UTC para casar a comparação.
    # synchronize_session=False: DELETE puro em SQL (a cascata 0003 apaga as
    # mensagens), sem avaliar a condição contra objetos em memória.
    corte = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dias)
    resultado = db.execute(
        delete(ConversaIA)
        .where(ConversaIA.created_at < corte)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return resultado.rowcount or 0
