"""Criação AUTOMÁTICA de contas de PROFESSOR a partir dos relatórios importados
(Lista Piloto e Elefante Letrado).

Cada nome vira um ``Professor`` (para o RBAC por turma) + um ``Usuario`` de login
na convenção pedida pelo gestor:
    usuário = Primeiro + Último nome, iniciais MAIÚSCULAS  → ex.: "PaulaVilela"
    senha   = Primeiro nome + "123"                        → ex.: "Paula123"

Idempotente: casa por NOME dentro da escola, então não duplica entre as duas
fontes nem em reimportações. Um campo com vários professores ("A, B; C") cria uma
conta para CADA um; o PRIMEIRO vira o titular da turma (``Turma.professor_id``),
que é o vínculo do RBAC (``permissoes.turmas_permitidas``).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_senha
from app.models import (
    ConversaIA,
    DispositivoMovel,
    Importacao,
    LogAuditoria,
    MensagemIA,
    Professor,
    Turma,
    Usuario,
)

_log = logging.getLogger(__name__)
_DOMINIO = "professor.constelaedu.com"
# Partículas que não contam como sobrenome (Sueli Macedo DO Prado → "Prado").
_PARTICULAS = {"de", "do", "da", "dos", "das", "e"}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


def _chave_nome(nome: str) -> str:
    """Chave de identidade do professor: sem acento, caixa e espaços normalizados.
    Casa 'Antônio Silva' com 'Antonio  SILVA' — a MESMA pessoa entre as fontes."""
    return _sem_acento(" ".join((nome or "").split())).casefold()


def _tokens(nome: str) -> frozenset[str]:
    """Conjunto de palavras normalizadas (sem partículas) — base da reconciliação
    nome curto ↔ nome completo ('PAULA' ⊂ 'PAULA BENEDITA VILELA NOGUEIRA')."""
    return frozenset(
        _sem_acento(p).casefold()
        for p in (nome or "").split()
        if _sem_acento(p).casefold() not in _PARTICULAS and any(c.isalnum() for c in p)
    )


def _primeiro_token(nome: str) -> str:
    partes = (nome or "").split()
    return _sem_acento(partes[0]).casefold() if partes else ""


def _cap_alnum(palavra: str) -> str:
    """Palavra só com letras/dígitos (sem acento), Primeira Maiúscula."""
    limpa = re.sub(r"[^A-Za-z0-9]", "", _sem_acento(palavra))
    return (limpa[:1].upper() + limpa[1:].lower()) if limpa else ""


def credenciais_professor(nome: str) -> tuple[str, str] | None:
    """(username_base CamelCase, senha) na convenção pedida pelo dono, ou None
    se o nome não servir.

        usuário = Primeiro nome + Último sobrenome, iniciais MAIÚSCULAS
                  (partículas não contam) → "PaulaNogueira", "SueliPrado"
        senha   = o MESMO usuário em minúsculas + "123" → "paulanogueira123"

    O login é acento/caixa-insensível (auth.py), então guardar em CamelCase é só
    exibição — a pessoa entra digitando de qualquer jeito."""
    partes = [p for p in (nome or "").split() if p]
    if not partes:
        return None
    primeiro = _cap_alnum(partes[0])
    # Último sobrenome REAL (ignora de/do/da/…): "Sueli Macedo do Prado" → Prado.
    sobrenomes = [p for p in partes[1:]
                  if _sem_acento(p).casefold() not in _PARTICULAS]
    ultimo = _cap_alnum(sobrenomes[-1]) if sobrenomes else ""
    if not primeiro:
        return None
    # Deixa folga p/ sufixo de desambiguação (Usuario.username é String(30)).
    base = (primeiro + ultimo)[:26]
    return base, f"{base.lower()}123"


def nomes_de_professores(texto: str) -> list[str]:
    """Separa vários professores de um campo ('A, B; C / D e E') e limpa/dedup."""
    bruto = re.split(r"[,;/]|\se\s|&", texto or "")
    vistos: set[str] = set()
    saida: list[str] = []
    for n in bruto:
        n = " ".join(n.split()).strip(" .-")
        chave = _sem_acento(n).casefold()
        if len(n) >= 3 and any(c.isalpha() for c in n) and chave not in vistos:
            vistos.add(chave)
            saida.append(n)
    return saida


def _identidade_livre(db: Session, base: str, escola_id: int,
                      excluir_id: int | None = None) -> tuple[str, str]:
    """(username, email) AMBOS livres na rede — Usuario.username E Usuario.email
    são unique. O username sai em CamelCase (``base``, para exibição com iniciais
    maiúsculas); o e-mail é sempre minúsculo. A checagem de disponibilidade é
    acento/caixa-insensível (o login também é). Sufixa 2,3… até achar par livre.
    ``excluir_id`` ignora a própria conta ao renomear (não colide consigo mesma).
    Pré-checagem otimista: a corrida real é resolvida pela UNIQUE + retry."""
    i = 1
    while True:
        username = base if i == 1 else f"{base}{i}"
        email = f"{username.lower()}@{_DOMINIO}"
        consulta = select(Usuario.id).where(
            (func.lower(Usuario.username) == username.lower())
            | (func.lower(Usuario.email) == email))
        if excluir_id is not None:
            consulta = consulta.where(Usuario.id != excluir_id)
        if db.execute(consulta).first() is None:
            return username, email
        i += 1


def _reconciliar(nome: str, existentes: list[Professor]) -> Professor | None:
    """Acha o Professor existente que é a MESMA pessoa que ``nome``. Só reconcilia
    o caso REAL da duplicação: um dos lados é o PRIMEIRO NOME SOZINHO (o Matific
    manda 'PAULA'; a Lista Piloto, 'PAULA BENEDITA VILELA NOGUEIRA'). Exige mesmo
    primeiro nome, subconjunto de tokens e EXATAMENTE UM candidato.

    Nunca funde dois nomes que já têm sobrenome: 'Ana Paula' e 'Ana Paula Souza'
    são pessoas diferentes (ambos ≥2 tokens), então ficam separados."""
    tokens_novo = _tokens(nome)
    if not tokens_novo:
        return None
    primeiro = _primeiro_token(nome)
    candidatos = [
        p for p in existentes
        if _primeiro_token(p.nome) == primeiro
        and (tokens_novo <= _tokens(p.nome) or _tokens(p.nome) <= tokens_novo)
        # A duplicação real é 'primeiro nome só' × 'nome completo'. Se AMBOS já
        # têm sobrenome, são identidades distintas — não reconcilia.
        and min(len(tokens_novo), len(_tokens(p.nome))) == 1
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _usuario_do_professor(db: Session, escola_id: int, prof: Professor) -> Usuario | None:
    return db.execute(
        select(Usuario).where(Usuario.escola_id == escola_id,
                              func.lower(Usuario.email) == (prof.email or "").lower())
    ).scalars().first()


def _promover_ao_nome_completo(db: Session, escola_id: int, prof: Professor,
                               nome_completo: str) -> None:
    """Um nome MAIS completo chegou para um professor já existente: adota o nome
    cheio no cadastro e na conta — SÓ o nome de exibição. NÃO rotaciona @/senha:
    a credencial pode já ter sido entregue à professora (uma folha impressa com
    'Paula/paula123' não pode parar de funcionar sozinha numa importação). A
    padronização do @ para 'PrimeiroÚltimo' é feita pela ferramenta explícita
    'Corrigir professores duplicados', que devolve a folha nova ao gestor."""
    prof.nome = nome_completo
    usuario = _usuario_do_professor(db, escola_id, prof)
    if usuario is not None:
        usuario.nome = nome_completo


def garantir_professor(db: Session, escola_id: int, nome: str) -> tuple[Professor | None, bool]:
    """Acha (por nome NORMALIZADO na escola) ou CRIA o Professor + o Usuario de
    login. Devolve (professor, criado_agora). Idempotente e à prova de corrida:
    NUNCA deixa a sessão poluída (usa SAVEPOINT) nem duplica a conta.

    Além do match acento-insensível (``_chave_nome``), RECONCILIA nome curto ↔
    nome completo (Matific manda 'PAULA'; a Lista Piloto, o nome cheio) para não
    criar duas contas da mesma professora — a causa das duplicatas."""
    nome = " ".join((nome or "").split())
    cred = credenciais_professor(nome)
    if cred is None:
        return None, False

    # Poucas dezenas de professores por escola: carregar e casar em Python é
    # barato e portável (SQL não tem unaccent garantido em SQLite/Postgres).
    existentes = list(db.execute(
        select(Professor).where(Professor.escola_id == escola_id)).scalars())
    alvo = _chave_nome(nome)
    for p in existentes:
        if _chave_nome(p.nome) == alvo:
            return p, False

    # Mesma pessoa escrita de forma mais curta/completa entre as fontes.
    match = _reconciliar(nome, existentes)
    if match is not None:
        if len(_tokens(nome)) > len(_tokens(match.nome)):
            _promover_ao_nome_completo(db, escola_id, match, nome)
        return match, False

    user_base, senha = cred
    senha_hash = hash_senha(senha)
    # Retry: se DUAS escolas criarem o mesmo username ao mesmo tempo, a UNIQUE do
    # banco barra uma; o SAVEPOINT desfaz só ESTE professor (não o import de
    # alunos) e recalculamos o username já vendo a linha que a outra commitou.
    for _ in range(8):
        username, email = _identidade_livre(db, user_base, escola_id)
        prof = Professor(escola_id=escola_id, nome=nome, email=email)
        usuario = Usuario(escola_id=escola_id, nome=nome, email=email,
                          username=username, senha_hash=senha_hash,
                          cargo="professor", status="ativo")
        try:
            with db.begin_nested():
                db.add(prof)
                db.add(usuario)
                db.flush()
            return prof, True
        except IntegrityError:
            continue  # corrida: username/email levado por outra transação
    _log.warning("professor não criado após colisões repetidas de username")
    return None, False


def garantir_professores_da_turma(db: Session, escola_id: int, turma,
                                  professores_texto: str) -> int:
    """Cria as contas de TODOS os professores do campo e vincula o PRIMEIRO como
    titular da turma (se ela ainda não tiver). Devolve quantas contas criou agora."""
    criados = 0
    titular: Professor | None = None
    for nome in nomes_de_professores(professores_texto):
        prof, novo = garantir_professor(db, escola_id, nome)
        if prof is None:
            continue
        criados += int(novo)
        if titular is None:
            titular = prof
    if titular is not None and turma is not None \
            and getattr(turma, "professor_id", None) is None:
        turma.professor_id = titular.id
    return criados


# --- Deduplicação de professores (limpeza do que já duplicou) ------------------

def _clusters_duplicados(db: Session, escola_id: int) -> list[tuple[Professor, list[Professor]]]:
    """Agrupa os professores duplicados da escola: cada tupla é (survivor, losers)
    onde o survivor é o nome MAIS COMPLETO e os losers são as grafias mais curtas
    da MESMA pessoa. Só funde o inequívoco: um nome curto que é subconjunto de
    DOIS nomes completos diferentes (homônimos) NÃO é fundido."""
    profs = list(db.execute(
        select(Professor).where(Professor.escola_id == escola_id)).scalars())
    grupos: dict[str, list[Professor]] = defaultdict(list)
    for p in profs:
        grupos[_primeiro_token(p.nome)].append(p)

    clusters: list[tuple[Professor, list[Professor]]] = []
    for primeiro, grupo in grupos.items():
        if not primeiro or len(grupo) < 2:
            continue
        # 'Completos' já têm sobrenome (≥2 tokens): cada um é uma IDENTIDADE — só
        # se fundem se forem IDÊNTICOS. 'Curtos' são o primeiro nome sozinho (a
        # forma que o Matific manda) — a única fonte real de duplicata.
        completos = [p for p in grupo if len(_tokens(p.nome)) >= 2]
        curtos = [p for p in grupo if len(_tokens(p.nome)) == 1]
        # Colapsa completos de tokens IDÊNTICOS (mesma pessoa): sobra 1 (menor id).
        canon: list[Professor] = []
        losers: dict[int, list[Professor]] = {}
        for m in sorted(completos, key=lambda p: p.id):
            gemeo = next((c for c in canon if _tokens(c.nome) == _tokens(m.nome)), None)
            if gemeo is None:
                canon.append(m)
                losers[m.id] = []
            else:
                losers[gemeo.id].append(m)
        # Cada nome curto funde no ÚNICO completo do grupo. Se há DOIS completos
        # com sobrenomes diferentes (homônimas: Maria Silva × Maria Souza), o
        # curto 'Maria' é ambíguo → NÃO funde (nunca junta pessoas diferentes).
        for curto in curtos:
            if len(canon) == 1:
                losers[canon[0].id].append(curto)
        for survivor in canon:
            if losers[survivor.id]:
                clusters.append((survivor, losers[survivor.id]))
    return clusters


def _apagar_conta(db: Session, usuario: Usuario) -> None:
    """Remove a conta duplicada preservando a história institucional (autoria das
    importações e logs some, mas os registros ficam) — igual à exclusão
    permanente do admin."""
    db.execute(update(Importacao).where(Importacao.usuario_id == usuario.id)
               .values(usuario_id=None))
    db.execute(update(LogAuditoria).where(LogAuditoria.usuario_id == usuario.id)
               .values(usuario_id=None))
    conversas = select(ConversaIA.id).where(ConversaIA.usuario_id == usuario.id)
    db.execute(delete(MensagemIA).where(MensagemIA.conversa_id.in_(conversas)))
    db.execute(delete(ConversaIA).where(ConversaIA.usuario_id == usuario.id))
    db.execute(delete(DispositivoMovel).where(DispositivoMovel.usuario_id == usuario.id))
    db.delete(usuario)


def plano_deduplicacao(db: Session, escola_id: int) -> list[dict]:
    """PRÉVIA (read-only) do que a correção fará: para cada pessoa duplicada, qual
    nome fica, o novo @ e senha, as turmas que serão movidas e quais contas serão
    apagadas. Nada é alterado aqui — é o que o gestor vê ANTES de confirmar."""
    preview: list[dict] = []
    for survivor, losers in _clusters_duplicados(db, escola_id):
        cred = credenciais_professor(survivor.nome)
        su = _usuario_do_professor(db, escola_id, survivor)
        # Conta JÁ USADA não tem o @/senha trocados (preserva o que a professora
        # já definiu) — a prévia reflete isso: mostra o @ atual e senha mantida.
        ativa = su is not None and su.ultimo_acesso is not None
        loser_ids = [l.id for l in losers]
        turmas = list(db.execute(
            select(Turma.nome).where(Turma.escola_id == escola_id,
                                     Turma.professor_id.in_(loser_ids))
        ).scalars().all())
        preview.append({
            "manter": survivor.nome,
            "usuario_novo": (su.username if ativa and su else
                             (cred[0] if cred else None)),
            "senha_nova": None if ativa else (cred[1] if cred else None),
            "turmas_movidas": turmas,
            "apagar": [{"nome": l.nome} for l in losers],
        })
    return preview


def aplicar_deduplicacao(db: Session, escola_id: int) -> list[dict]:
    """APLICA a correção: move as turmas dos losers para o survivor, apaga as
    contas duplicadas e regenera o @ (CamelCase) + senha (usuário+123) do
    survivor na convenção. Devolve a folha de credenciais (nome, @, senha) para o
    gestor entregar. NÃO commita — quem chama decide (endpoint faz o commit)."""
    folha: list[dict] = []
    for survivor, losers in _clusters_duplicados(db, escola_id):
        loser_ids = [l.id for l in losers]
        # 1) as turmas dos duplicados passam para o survivor (antes de apagar).
        db.execute(update(Turma).where(Turma.escola_id == escola_id,
                                       Turma.professor_id.in_(loser_ids))
                   .values(professor_id=survivor.id))
        # 2) apaga as contas duplicadas (Usuario + Professor).
        for loser in losers:
            u = _usuario_do_professor(db, escola_id, loser)
            if u is not None:
                _apagar_conta(db, u)
            db.delete(loser)
        # 3) padroniza @ e senha do survivor — SÓ se a conta nunca foi usada.
        #    Se a professora já entrou (ultimo_acesso), a senha dela é preservada
        #    (não sobrescreve com o padrão nem derruba a sessão): mostra o @ atual
        #    na folha com "senha mantida".
        cred = credenciais_professor(survivor.nome)
        su = _usuario_do_professor(db, escola_id, survivor)
        entrada = {"nome": survivor.nome, "usuario": None, "senha": None}
        if su is not None and su.ultimo_acesso is not None:
            entrada = {"nome": survivor.nome, "usuario": su.username, "senha": None}
        elif cred and su is not None:
            base, senha = cred
            username, email = _identidade_livre(db, base, escola_id, excluir_id=su.id)
            su.username, su.email = username, email
            su.senha_hash = hash_senha(senha)
            su.token_version = (su.token_version or 0) + 1  # invalida sessões antigas
            survivor.email = email
            entrada = {"nome": survivor.nome, "usuario": username, "senha": senha}
        folha.append(entrada)
    return folha
