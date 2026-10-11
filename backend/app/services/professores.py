"""Criação AUTOMÁTICA de contas de PROFESSOR a partir dos relatórios importados
(Lista Piloto e Elefante Letrado).

Cada nome vira um ``Professor`` (para o RBAC por turma) + um ``Usuario`` de login.
O @ segue uma convenção legível — Primeiro + Último nome, iniciais MAIÚSCULAS
("PaulaVilela") — porque nome de usuário não é segredo.

A SENHA nunca é derivada do nome (política da Fase 3A, ver `credenciais_professor`):
  * conta criada pela IMPORTAÇÃO nasce sem senha conhecida por ninguém; o acesso
    inicial é pelo link de redefinição de uso único (o próprio professor escolhe
    a senha);
  * quando uma ferramenta de gestão GERA credenciais (padronização, fusão de
    duplicados), a senha é aleatória e sai uma única vez, na folha entregue ao
    gestor — o mesmo que o cadastro manual de professor já fazia.

Idempotente: casa por NOME dentro da escola, então não duplica entre as duas
fontes nem em reimportações. Um campo com vários professores ("A, B; C") cria uma
conta para CADA um; o PRIMEIRO vira o titular da turma (``Turma.professor_id``),
que é o vínculo do RBAC (``permissoes.turmas_permitidas``).
"""
from __future__ import annotations

import logging
import re
import secrets
from collections import defaultdict

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import email_reservado_ao_dono
from app.core.security import gerar_senha_legivel, hash_senha, verificar_senha
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
# Normalização de nome PT-BR compartilhada com a deduplicação de alunos.
from app.services._nomes import (
    PARTICULAS as _PARTICULAS,
    chave_nome as _chave_nome,
    primeiro_token as _primeiro_token,
    sem_acento as _sem_acento,
    tokens as _tokens,
)

_log = logging.getLogger(__name__)
_DOMINIO = "professor.constelaedu.com"


def _cap_alnum(palavra: str) -> str:
    """Palavra só com letras/dígitos (sem acento), Primeira Maiúscula."""
    limpa = re.sub(r"[^A-Za-z0-9]", "", _sem_acento(palavra))
    return (limpa[:1].upper() + limpa[1:].lower()) if limpa else ""


def usuario_base_professor(nome: str) -> str | None:
    """O @ base na convenção legível, ou None se o nome não servir.

        Primeiro nome + Último sobrenome, iniciais MAIÚSCULAS (partículas não
        contam) → "PaulaNogueira", "SueliPrado"

    O login é acento/caixa-insensível (auth.py), então guardar em CamelCase é só
    exibição — a pessoa entra digitando de qualquer jeito. O @ NÃO é segredo:
    quem sabe o nome do professor sabe o @. Por isso a senha nunca deriva dele."""
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
    return (primeiro + ultimo)[:26]


def credenciais_professor(nome: str) -> tuple[str, str] | None:
    """(username_base, senha) para uma FOLHA de credenciais, ou None se o nome
    não servir. A senha é ALEATÓRIA (`gerar_senha_legivel`, três palavras + dois
    dígitos) e só existe em texto nesta folha, uma única vez.

    POR QUE NÃO MAIS A CONVENÇÃO. Até a Fase 3A a senha era o @ em minúsculas +
    "123" — e antes disso, o primeiro nome + "123". Qualquer pessoa que soubesse
    o nome de um professor sabia a senha dele; a regra estava escrita no código
    de um repositório público; não havia troca obrigatória no primeiro acesso; e
    a importação criava essas contas ATIVAS sem avisar ninguém — exatamente as
    que nunca têm a senha trocada. As contas antigas que ainda usam a senha da
    convenção são encontradas por `contas_com_senha_derivada`."""
    base = usuario_base_professor(nome)
    if base is None:
        return None
    return base, gerar_senha_legivel()


def senha_hash_sem_acesso() -> str:
    """Hash de uma senha aleatória de 256 bits que NINGUÉM recebe: a conta existe
    (para o vínculo professor ↔ turma), mas só entra quem receber o link de
    redefinição e escolher a própria senha."""
    return hash_senha(secrets.token_urlsafe(32))


def _variantes_123(radical: str) -> set[str]:
    """O radical + "123" na caixa original, minúscula, MAIÚSCULA e Capitalizada —
    as formas que a pessoa (ou quem cadastrou) digitaria ao seguir a regra."""
    radical = (radical or "").strip().lstrip("@")
    if not radical:
        return set()
    return {f"{r}123" for r in (radical, radical.lower(), radical.upper(),
                                radical.capitalize())}


def _senhas_da_convencao_antiga(nome: str, username: str | None, *,
                                nomes_antigos=(), usernames_antigos=()) -> set[str]:
    """As senhas que as convenções antigas teriam dado a esta conta — só para
    DETECTAR quem ainda as usa. Cobre as duas regras que existiram (@ + "123";
    primeiro nome + "123") e o @ com sufixo de desambiguação ("…2"), porque a
    senha nascia do @ BASE, antes do sufixo.

    Cada radical (primeiro nome, @ BASE CamelCase, @ da conta, @ sem sufixo) entra
    na caixa original, minúscula, MAIÚSCULA e Capitalizada ("AnaSilva123",
    "anasilva123", "ANASILVA123", "Anasilva123"). ``nomes_antigos`` e
    ``usernames_antigos`` são os que a conta JÁ teve (ver
    ``_identidades_antigas``): a senha nasceu do nome da época, não do atual.

    Nada de dicionário genérico: todo candidato sai do nome/@ da própria conta —
    senão contas sem relação com a convenção seriam marcadas."""
    radicais: set[str] = set()
    for n in (nome, *nomes_antigos):
        base = usuario_base_professor(n or "")
        if base:
            radicais.add(base)
        partes = [p for p in (n or "").split() if p]
        if partes:
            primeiro = _cap_alnum(partes[0])
            if primeiro:
                radicais.add(primeiro)
    for un in (username, *usernames_antigos):
        un = (un or "").strip().lstrip("@")
        if un:
            radicais.add(un)
            radicais.add(un.rstrip("0123456789"))
    candidatos: set[str] = set()
    for r in radicais:
        candidatos |= _variantes_123(r)
    candidatos.discard("123")
    return candidatos


def _identidades_antigas(db: Session, u: Usuario) -> tuple[set[str], set[str]]:
    """(nomes, @s) que esta conta JÁ teve, pelo que o banco registra de fato:

    * ``Professor.nome`` do cadastro ligado pelo e-mail (o vínculo do RBAC), na
      mesma escola quando a conta tem escola;
    * a auditoria das edições da conta (``PATCH /admin/usuarios/{id}``: o
      ``nome`` gravado em cada edição e o ``username`` ``{"de", "para"}``);
    * a auditoria das edições do cadastro de professor ligado
      (``professor.atualizado`` / ``professor.criado`` com ``entidade_id``: o
      ``nome`` gravado).

    Só LÊ. O que não deixou rastro (ex.: o @ re-caixado em lote, que só conta
    as contas) não tem como entrar.

    Limitação conhecida: o ``PATCH /admin/usuarios`` grava em ``nome`` o nome
    NOVO, e ``usuario.criado`` não grava nome; assim, o nome que a conta tinha
    ANTES da 1ª edição não fica na auditoria de usuário. Ele só entra se houver
    rastro no cadastro de professor ligado (``Professor.nome`` ou a auditoria
    dele). O ``professor.criado`` de ``routers/academico.py`` é gravado sem
    ``entidade_id`` e, por isso, não se liga à conta."""
    nomes: set[str] = set()
    usernames: set[str] = set()
    email = (u.email or "").strip().lower()
    prof_ids: list[int] = []
    if email:
        consulta = select(Professor).where(func.lower(Professor.email) == email)
        if u.escola_id is not None:
            consulta = consulta.where(Professor.escola_id == u.escola_id)
        for prof in db.execute(consulta).scalars():
            prof_ids.append(prof.id)
            if prof.nome:
                nomes.add(prof.nome)
    logs = db.execute(
        select(LogAuditoria.entidade, LogAuditoria.detalhes).where(
            ((LogAuditoria.entidade == "usuario") & (LogAuditoria.entidade_id == u.id))
            | ((LogAuditoria.entidade == "professor")
               & LogAuditoria.entidade_id.in_(prof_ids or [-1])))
    ).all()
    for _entidade, detalhes in logs:
        if not isinstance(detalhes, dict):
            continue
        if isinstance(detalhes.get("nome"), str):
            nomes.add(detalhes["nome"])
        troca = detalhes.get("username")
        if isinstance(troca, dict):
            for lado in ("de", "para"):
                if isinstance(troca.get(lado), str):
                    usernames.add(troca[lado])
    return nomes, usernames


USO_NUNCA_USADA = "nunca_usada"
USO_USADA = "usada"
USO_INDETERMINADO = "indeterminada"

# Origem gravada na auditoria de cada invalidação feita pela etapa de deploy.
ORIGEM_ETAPA = "scripts/senhas_derivadas"


def _uso_da_conta(db: Session, u: Usuario) -> str:
    """Se a conta já foi usada — decide quem a etapa ``--so-nunca-usadas`` pode
    tocar sem afetar ninguém. ``ultimo_acesso`` é gravado em TODO login desde o
    início do sistema; mas um sinal de uso sem ele (presença em ``visto_em`` ou
    um registro de auditoria ``login``) quer dizer que os dados divergem — aí a
    conta é INDETERMINADA e fica fora da etapa automática."""
    if u.ultimo_acesso is not None:
        return USO_USADA
    if u.visto_em is not None:
        return USO_INDETERMINADO
    houve_login = db.execute(
        select(LogAuditoria.id).where(LogAuditoria.acao == "login",
                                      LogAuditoria.usuario_id == u.id).limit(1)
    ).first()
    return USO_INDETERMINADO if houve_login else USO_NUNCA_USADA


def _hash_conferivel(senha_hash: str | None) -> bool:
    """O hash está num formato que o verificador reconhece? ``verificar_senha``
    devolve False para hash malformado — sem esta checagem, uma conta assim
    passaria calada como "senha não derivada"."""
    from app.core.security import pwd_context
    try:
        return bool(senha_hash) and pwd_context.identify(senha_hash) is not None
    except (ValueError, TypeError):
        return False


def _classificar_contas(db: Session, escola_id: int | None, *,
                        globais: bool = False) -> tuple[list[dict], dict[int, str]]:
    """Toda conta com: ``derivada`` (True/False, ou None quando o hash não pôde
    ser conferido) e ``uso``; e, À PARTE, o hash lido de cada uma (a base da
    gravação compare-and-set — nunca vai para a saída). Só LÊ.

    TODOS os cargos, não só professor: a conta nasce professor na importação,
    mas pode ter sido promovida a coordenador ou admin mantendo a senha — e
    seria justamente a de maior alcance a ficar de fora. ``globais`` escolhe o
    outro lado: as contas de administração global ficam numa lista à parte e
    nunca entram na invalidação automática (travar o único admin global não tem
    volta pela interface).

    As EXCLUÍDAS entram também: a exclusão é lógica e a conta pode ser
    restaurada — sem esta varredura, voltaria ativa com a senha calculável.

    Com ``escola_id`` (o rollout por escola), as contas de REDE ficam de fora: a
    Secretaria guarda o ``escola_id`` de onde foi promovida, mas alcança a rede
    inteira e só o admin global gera o link dela — invalidá-la no rollout
    combinado com UMA escola tiraria o acesso do município sem que essa escola
    pudesse devolver. Ela entra na execução completa (sem ``escola_id``)."""
    consulta = select(Usuario).where(Usuario.is_global.is_(globais))
    if escola_id is not None:
        consulta = consulta.where(Usuario.escola_id == escola_id,
                                  Usuario.rede_id.is_(None))
    contas: list[dict] = []
    hashes: dict[int, str] = {}
    for u in db.execute(consulta.order_by(Usuario.id)).scalars():
        hashes[u.id] = u.senha_hash
        if not _hash_conferivel(u.senha_hash):
            derivada = None   # formato que o verificador não lê: não dá para afirmar
        else:
            nomes_antigos, usernames_antigos = _identidades_antigas(db, u)
            candidatos = _senhas_da_convencao_antiga(
                u.nome, u.username, nomes_antigos=nomes_antigos,
                usernames_antigos=usernames_antigos)
            derivada = any(verificar_senha(c, u.senha_hash) for c in sorted(candidatos))
        uso = _uso_da_conta(db, u)
        contas.append({"usuario_id": u.id, "escola_id": u.escola_id,
                       "usuario": u.username, "cargo": u.cargo, "status": u.status,
                       "rede_id": u.rede_id,
                       "derivada": derivada, "uso": uso,
                       "nunca_usada": uso == USO_NUNCA_USADA})
    return contas, hashes


def _sem_flag(conta: dict) -> dict:
    return {k: v for k, v in conta.items() if k != "derivada"}


def classificar_senhas_derivadas(db: Session, escola_id: int | None = None) -> dict:
    """A classificação ÚNICA da etapa — uma passada de bcrypt por conta, que o
    diagnóstico, a conferência do ``--esperado`` e a gravação reaproveitam
    (antes eram 2–3 passadas, minutos de CPU cada). Só LÊ. Devolve:

    * ``derivadas``: contas não globais COM escola e senha derivada — as únicas
      que a invalidação automática pode tocar;
    * ``sem_escola``: contas não globais SEM escola e senha derivada — nunca
      tocadas aqui (nenhuma tela de escola gera o link delas): a recuperação é
      manual, pelo admin global (``scripts/link_redefinicao.py``);
    * ``globais``: administração global com senha derivada (só na execução
      completa) — troca manual;
    * ``nao_verificaveis``: hash em formato desconhecido — fora da etapa;
    * ``hashes_lidos``: ``{usuario_id: hash}`` do momento da leitura, para a
      gravação compare-and-set. NUNCA sai na saída nem na auditoria."""
    contas, hashes = _classificar_contas(db, escola_id)
    derivadas = [c for c in contas if c["derivada"] is True]
    globais: list[dict] = []
    if escola_id is None:
        contas_globais, _ = _classificar_contas(db, None, globais=True)
        globais = [_sem_flag(c) for c in contas_globais if c["derivada"] is True]
    return {
        "derivadas": [_sem_flag(c) for c in derivadas if c["escola_id"] is not None],
        "sem_escola": [_sem_flag(c) for c in derivadas if c["escola_id"] is None],
        "globais": globais,
        "nao_verificaveis": [_sem_flag(c) for c in contas if c["derivada"] is None],
        "hashes_lidos": hashes,
    }


def contas_com_senha_derivada(db: Session, escola_id: int | None = None) -> list[dict]:
    """Contas (de qualquer cargo, não globais) cuja senha ainda é a da convenção
    antiga de professor (derivável do nome). Só LÊ — confere o hash bcrypt contra
    os candidatos; nada é gravado e nenhuma senha sai daqui. Inclui as SEM escola,
    que a invalidação automática não toca (ver ``classificar_senhas_derivadas``).

    Cada conta vem com ``uso`` (``nunca_usada`` | ``usada`` | ``indeterminada``)
    e ``nunca_usada`` (só True quando o uso é inequívoco)."""
    c = classificar_senhas_derivadas(db, escola_id)
    return sorted(c["derivadas"] + c["sem_escola"], key=lambda x: x["usuario_id"])


def contas_globais_com_senha_derivada(db: Session) -> list[dict]:
    """Contas de ADMINISTRAÇÃO GLOBAL com a senha da convenção: só para o
    diagnóstico — a troca é manual (ver ``_classificar_contas``)."""
    contas, _ = _classificar_contas(db, None, globais=True)
    return [_sem_flag(c) for c in contas if c["derivada"] is True]


def contas_nao_verificaveis(db: Session, escola_id: int | None = None) -> list[dict]:
    """Contas de professor cujo hash não pôde ser conferido — impossível dizer se
    a senha é a derivada. Nunca entram na invalidação automática."""
    contas, _ = _classificar_contas(db, escola_id)
    return [_sem_flag(c) for c in contas if c["derivada"] is None]


def alvos_da_invalidacao(classificacao: dict, *, so_nunca_usadas: bool = False) -> list[dict]:
    """As contas que ``invalidar_senhas_derivadas`` tocaria com esta
    classificação — o número que o operador confere no ``--esperado``."""
    derivadas = classificacao["derivadas"]
    if so_nunca_usadas:
        return [c for c in derivadas if c["uso"] == USO_NUNCA_USADA]
    return list(derivadas)


class EsperadoDivergente(Exception):
    """O número de alvos não é o que o operador conferiu no diagnóstico — nada
    foi gravado."""

    def __init__(self, esperado: int, encontrados: int):
        super().__init__(f"esperado {esperado}, encontrados {encontrados}")
        self.esperado = esperado
        self.encontrados = encontrados


def invalidar_senhas_derivadas(db: Session, escola_id: int | None = None, *,
                               aplicar: bool = False,
                               so_nunca_usadas: bool = False,
                               esperado: int | None = None,
                               classificacao: dict | None = None,
                               origem: str = ORIGEM_ETAPA) -> dict:
    """Etapa de deploy: tira de circulação a senha derivável. Sem ``aplicar`` é
    só o diagnóstico (padrão). Com ``aplicar``, cada conta achada recebe uma senha
    que ninguém conhece e perde as sessões abertas; o professor volta a entrar
    pelo link de redefinição (botão "Gerar link de redefinição" em Usuários).
    Não bloqueia ninguém para sempre e não cria senha conhecida de reserva.
    ``so_nunca_usadas`` limita a invalidação às contas que nunca entraram — as que
    não afetam ninguém; as já usadas continuam listadas em ``contas``.

    * ``classificacao``: a de ``classificar_senhas_derivadas`` que o chamador já
      fez (o diagnóstico) — reaproveitada, sem nova passada de bcrypt.
    * ``esperado``: com ``aplicar``, o número de alvos que o operador conferiu;
      se divergir, levanta ``EsperadoDivergente`` ANTES de gravar qualquer coisa.
    * Contas SEM escola nunca são tocadas: voltam em ``sem_escola``.
    * Gravação COMPARE-AND-SET: a senha só é trocada se o hash ainda for o lido
      na classificação (``UPDATE … WHERE id = :id AND senha_hash = :lido``), e o
      ``token_version`` sobe na MESMA instrução. Quem trocou a senha no meio da
      execução não é sobrescrito: volta em ``trocadas_durante``.

    NÃO commita — quem chama decide (transação única: falha no meio = rollback
    de tudo)."""
    from sqlalchemy.orm.util import identity_key

    from app.services.audit import registrar

    if classificacao is None:
        classificacao = classificar_senhas_derivadas(db, escola_id)
    achadas = classificacao["derivadas"]
    alvos = alvos_da_invalidacao(classificacao, so_nunca_usadas=so_nunca_usadas)
    if aplicar and esperado is not None and esperado != len(alvos):
        raise EsperadoDivergente(esperado, len(alvos))
    invalidadas: list[dict] = []
    trocadas: list[dict] = []
    if aplicar:
        lidos = classificacao["hashes_lidos"]
        for item in alvos:
            uid = item["usuario_id"]
            resultado = db.execute(
                update(Usuario)
                .where(Usuario.id == uid, Usuario.senha_hash == lidos[uid])
                .values(senha_hash=senha_hash_sem_acesso(),
                        token_version=func.coalesce(Usuario.token_version, 0) + 1)
                .execution_options(synchronize_session=False))
            if resultado.rowcount != 1:
                trocadas.append(item)     # a senha mudou desde a leitura: não toca
                continue
            # A instância já carregada nesta sessão (se houver) relê hash e versão.
            carregada = db.identity_map.get(identity_key(Usuario, uid))
            if carregada is not None:
                db.expire(carregada, ["senha_hash", "token_version"])
            registrar(db, "usuario.senha_derivada_invalidada", escola_id=item["escola_id"],
                      entidade="usuario", entidade_id=uid,
                      detalhes={"uso": item["uso"], "origem": origem})
            invalidadas.append(item)
    return {"encontradas": len(achadas), "aplicado": aplicar,
            "alvos": len(alvos),
            "invalidadas": len(invalidadas) if aplicar else 0,
            "trocadas_durante": trocadas,
            "contas": achadas,
            "sem_escola": classificacao["sem_escola"],
            "por_uso": {uso: sum(1 for c in achadas if c["uso"] == uso)
                        for uso in (USO_NUNCA_USADA, USO_USADA, USO_INDETERMINADO)}}


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
        # O e-mail reservado ao dono (ADMIN_GLOBAL_EMAIL) é promovido a
        # `is_global` no boot: nunca pode sair GERADO para uma conta de
        # professor (a folha entrega a senha ao gestor; a importação cria a
        # conta e a coordenação gera o link de redefinição).
        if (db.execute(consulta).first() is None
                and not email_reservado_ao_dono(email)):
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
    """A conta de login de um Professor: SÓ a conta de PROFESSOR desta escola
    (sem rede, não global). A fusão de duplicados APAGA ou REESCREVE (@, e-mail
    e senha, devolvida na folha) a conta que sai daqui — sem o recorte, um
    Professor cadastrado com o e-mail da Secretaria (que guarda o `escola_id` de
    origem), do coordenador ou do admin desta escola levava a fusão a apagar
    essa conta ou a entregar a senha nova dela ao gestor."""
    email = (prof.email or "").strip().lower()
    if not email or email_reservado_ao_dono(email):
        return None
    return db.execute(
        select(Usuario).where(Usuario.escola_id == escola_id,
                              func.lower(Usuario.email) == email,
                              Usuario.cargo == "professor",
                              Usuario.rede_id.is_(None),
                              Usuario.is_global.is_(False))
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
    user_base = usuario_base_professor(nome)
    if user_base is None:
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

    # A conta nasce SEM senha conhecida (ninguém recebe nada da importação). O
    # professor entra pela primeira vez pelo link de redefinição, escolhendo a
    # própria senha — antes, ela nascia com a senha derivada do nome.
    senha_hash = senha_hash_sem_acesso()
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

def _candidatos(db: Session, escola_id: int) -> list[tuple[Professor, Professor, str]]:
    """Pares (loser, survivor, confiança) da MESMA pessoa: um nome que é
    subconjunto ESTRITO de EXATAMENTE UM nome mais completo do mesmo primeiro
    nome. ``confiança``:
      * "alta"    — o loser é o primeiro nome SOZINHO ('PAULA' → 'PAULA BENEDITA
                    VILELA NOGUEIRA'): é sempre a mesma pessoa (fonte real da
                    duplicata do Matific);
      * "revisar" — o loser já tem sobrenome ('Ana Lucia' → 'Ana Lucia Ferreira
                    de Camargo' É a pessoa, mas 'Ana Paula' → 'Ana Paula Souza'
                    PODE ser outra). Não dá para decidir por algoritmo — quem
                    confirma é o gestor, no botão "Corrigir professores
                    duplicados" (cada fusão tem sua caixa de seleção).

    Subconjunto de DOIS nomes diferentes (homônimas) → ambíguo, nunca entra."""
    profs = list(db.execute(
        select(Professor).where(Professor.escola_id == escola_id)).scalars())
    grupos: dict[str, list[Professor]] = defaultdict(list)
    for p in profs:
        grupos[_primeiro_token(p.nome)].append(p)

    pares: list[tuple[Professor, Professor, str]] = []
    for primeiro, grupo in grupos.items():
        if not primeiro or len(grupo) < 2:
            continue
        # Titular de cada NOME (conjunto de tokens) = o de MENOR id. Gêmeos
        # exatos (mesmo nome, id maior) fundem nele.
        titular_por_tokens: dict[frozenset, Professor] = {}
        for p in sorted(grupo, key=lambda x: x.id):
            titular_por_tokens.setdefault(_tokens(p.nome), p)
        for p in grupo:
            tk = _tokens(p.nome)
            titular = titular_por_tokens[tk]
            if p.id != titular.id:
                pares.append((p, titular, "revisar"))  # gêmeo exato do mesmo nome
                continue
            # Nomes DISTINTOS (por tokens) que contêm ESTRITAMENTE este. Se houver
            # exatamente UM, é o completo da mesma pessoa (subconjunto do único).
            maiores = {_tokens(q.nome) for q in grupo if _tokens(q.nome) > tk}
            if len(maiores) == 1:
                survivor = titular_por_tokens[next(iter(maiores))]
                pares.append((p, survivor, "alta" if len(tk) == 1 else "revisar"))
    return pares


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


# Marcador da prévia de deduplicação no lugar da senha (ver `plano_deduplicacao`).
SENHA_GERADA_AO_APLICAR = "(gerada ao aplicar)"


def plano_deduplicacao(db: Session, escola_id: int) -> list[dict]:
    """PRÉVIA (read-only) — UMA linha por candidato a fusão: qual nome sai, em
    qual fica, a confiança (alta/revisar), o novo @/senha do que fica e as turmas
    que serão movidas. Nada é alterado; o gestor marca quais confirmar."""
    preview: list[dict] = []
    for loser, survivor, confianca in _candidatos(db, escola_id):
        base = usuario_base_professor(survivor.nome)
        su = _usuario_do_professor(db, escola_id, survivor)
        # Conta JÁ USADA não troca @/senha (preserva o que a professora definiu).
        ativa = su is not None and su.ultimo_acesso is not None
        turmas = list(db.execute(
            select(Turma.nome).where(Turma.escola_id == escola_id,
                                     Turma.professor_id == loser.id)
        ).scalars().all())
        preview.append({
            "loser_id": loser.id,
            "apagar": loser.nome,
            "manter": survivor.nome,
            "confianca": confianca,   # "alta" | "revisar"
            "usuario_novo": su.username if ativa and su else base,
            # A prévia NÃO carrega senha: a senha nova é sorteada só ao aplicar e
            # sai uma vez, na folha. Antes vinha aqui a senha derivada do nome —
            # em claro, numa tela que é só de conferência. O front só testa
            # `null` ("senha mantida"); o texto deixa claro que não é senha.
            "senha_nova": None if ativa else (SENHA_GERADA_AO_APLICAR if base else None),
            "turmas_movidas": turmas,
        })
    return preview


def aplicar_deduplicacao(db: Session, escola_id: int,
                         loser_ids: list[int]) -> list[dict]:
    """APLICA só as fusões CONFIRMADAS (``loser_ids``): move as turmas de cada
    duplicado para o que fica, apaga as contas duplicadas e padroniza o @/senha do
    que fica (guardando quem já usava a conta). Devolve a folha de credenciais.
    NÃO commita — quem chama decide (o endpoint faz o commit)."""
    escolhidos = set(loser_ids or [])
    # Agrupa os losers escolhidos por survivor (um survivor pode absorver vários).
    por_survivor: dict[int, list[Professor]] = defaultdict(list)
    for loser, survivor, _c in _candidatos(db, escola_id):
        if loser.id in escolhidos:
            por_survivor[survivor.id].append(loser)

    folha: list[dict] = []
    for survivor_id, losers in por_survivor.items():
        survivor = db.get(Professor, survivor_id)
        if survivor is None:
            continue
        ids = [l.id for l in losers]
        # 1) as turmas dos duplicados passam para o que fica (antes de apagar).
        db.execute(update(Turma).where(Turma.escola_id == escola_id,
                                       Turma.professor_id.in_(ids))
                   .values(professor_id=survivor.id))
        # 2) apaga as contas duplicadas (Usuario + Professor) — NUNCA a conta
        #    do que FICA: dois cadastros podem apontar para a MESMA conta de
        #    professor (vínculo); apagar a do duplicado seria apagar a dela.
        conta_que_fica = _usuario_do_professor(db, escola_id, survivor)
        for loser in losers:
            u = _usuario_do_professor(db, escola_id, loser)
            if u is not None and (conta_que_fica is None
                                  or u.id != conta_que_fica.id):
                _apagar_conta(db, u)
            db.delete(loser)
        # 3) padroniza @ e senha do survivor — SÓ se a conta nunca foi usada
        #    (se já entrou, preserva a senha e a sessão; folha = "senha mantida").
        cred = credenciais_professor(survivor.nome)
        su = _usuario_do_professor(db, escola_id, survivor)
        if su is not None and su.ultimo_acesso is not None:
            folha.append({"nome": survivor.nome, "usuario": su.username, "senha": None})
        elif cred and su is not None:
            base, senha = cred
            username, email = _identidade_livre(db, base, escola_id, excluir_id=su.id)
            su.username, su.email = username, email
            su.senha_hash = hash_senha(senha)
            su.token_version = (su.token_version or 0) + 1  # invalida sessões antigas
            survivor.email = email
            folha.append({"nome": survivor.nome, "usuario": username, "senha": senha})
        else:
            folha.append({"nome": survivor.nome, "usuario": None, "senha": None})
    return folha


def padronizar_usernames(db: Session, escola_id: int) -> list[dict]:
    """Coloca o @ de TODA conta de professor na convenção CamelCase (Primeiro+
    Último sobrenome). Contas antigas nasceram minúsculas (@paulanogueira) e o
    dedup só regenera as que funde — esta função arruma as demais.

    Conta JÁ USADA (``ultimo_acesso``): só RE-CAIXA o @ (o login é case-insensível,
    então não quebra) e MANTÉM a senha/sessão. Conta nunca usada: regenera @ +
    senha na convenção. Devolve a folha (nome · @ · senha; senha=None = mantida).
    NÃO commita."""
    folha: list[dict] = []
    professores = list(db.execute(
        select(Professor).where(Professor.escola_id == escola_id)).scalars())
    for prof in professores:
        u = _usuario_do_professor(db, escola_id, prof)
        if u is None or u.cargo != "professor":
            continue
        cred = credenciais_professor(prof.nome)
        if cred is None:
            continue
        base, senha = cred                       # base = @ CamelCase da convenção
        atual = u.username or ""
        if atual == base:
            continue                             # já está na convenção
        if u.ultimo_acesso is not None:
            # Conta usada: só re-caixa se for a MESMA identidade (mesmo minúsculo);
            # trocar por um @ diferente quebraria o login dela — aí não mexe.
            if atual.lower() == base.lower():
                u.username = base
                folha.append({"nome": prof.nome, "usuario": base, "senha": None})
            continue
        # Conta nunca usada: regenera @ + senha na convenção.
        username, email = _identidade_livre(db, base, escola_id, excluir_id=u.id)
        u.username, u.email = username, email
        u.senha_hash = hash_senha(senha)
        u.token_version = (u.token_version or 0) + 1
        prof.email = email
        folha.append({"nome": prof.nome, "usuario": username, "senha": senha})
    return folha
