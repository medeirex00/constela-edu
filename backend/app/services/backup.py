"""Backup e restauração por escola (PRD §18).

O backup é um JSON portátil (funciona igual em SQLite e PostgreSQL) com
todos os dados pedagógicos da escola. A restauração substitui os dados da
escola remapeando os IDs — nunca reutiliza IDs antigos, que podem já
pertencer a outra escola no mesmo banco.

Usuários NÃO entram no backup de dados: restaurar um arquivo antigo não
pode reverter senhas nem reativar contas desligadas (segurança > conveniência).
A referência a um usuário que viaja no arquivo (``REFERENCIAS_A_USUARIO``) volta
como veio se ele ainda existe, e vira NULL se não existe mais.

Pelo mesmo motivo, as configurações de SEGREDO e de ACESSO
(``SEGREDOS_DE_CONFIGURACAO``: o link do painel público, a chave de IA cifrada e a
sessão do Matific) não saem no arquivo — ele é baixado pelo admin da escola e
circula fora do banco — e a restauração NÃO as repõe nem as apaga: ficam como
estão. Antes, restaurar um backup anterior à troca do link reativava o link
antigo do painel (nomes de crianças num endereço sem senha) e devolvia cifras
mortas depois da rotação de chaves (e97, lacuna L1). Backups antigos, que ainda
trazem esses campos, continuam aceitos: eles são simplesmente ignorados.

As travas da sincronização (a política de criação de aluno e o vínculo da escola
externa) saem no arquivo, mas a restauração também as deixa como estão
(``PRESERVADAS_NA_RESTAURACAO``): repô-las do arquivo desfazia em silêncio o
"bloquear" e plantava um vínculo que a API recusa com 409.

REGRA DE OURO DA RESTAURAÇÃO (C-06): *nunca apagar o que não se sabe repor.*
A restauração deleta as linhas da escola e, como ``alunos.id`` tem
``ON DELETE CASCADE``, o banco apaga junto tabelas que podem não estar no
arquivo. Antes de tocar em qualquer linha, ``restaurar`` calcula as PERDAS
(``perdas_da_restauracao``) e aborta se houver alguma — em vez de destruir em
silêncio e responder "Backup restaurado com sucesso". A varredura é
ESTRUTURAL (segue o cascade no metadata), então uma tabela criada no futuro
entra no radar sozinha, sem depender de alguém lembrar de atualizar uma lista.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Configuracao,
    DificuldadeTurma,
    Escola,
    EventoAluno,
    IdentidadeExterna,
    Importacao,
    Leitura,
    Livro,
    LogAuditoria,
    Matricula,
    NivelDificuldade,
    PontuacaoNivelTurma,
    Nota,
    Professor,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    SyncMarcador,
    Turma,
    Usuario,
)
from app.services import politica_sync
from app.sync import escola_externa

# 2 = passou a carregar identidades externas, eventos e marcadores de sync.
# Arquivos da versão 1 continuam sendo aceitos: o que eles não cobrem é
# tratado pela mesma checagem de perdas (não é destruído em silêncio).
VERSAO_BACKUP = 2
VERSOES_ACEITAS = frozenset({1, 2})

# Ordem DUPLAMENTE significativa:
#   * inserção — pais antes dos filhos (FK precisa existir);
#   * exclusão — em ``reversed()``, filhos antes dos pais.
# Por isso ``identidades_externas``/``eventos_aluno`` ficam no fim: apontam para
# alunos, livros e importações, e precisam ser apagados ANTES deles.
# (``test_backup_restauracao_sem_perda`` prova as duas direções.)
MODELOS: list[tuple[str, type]] = [
    ("professores", Professor),
    ("turmas", Turma),
    ("alunos", Aluno),
    ("matriculas", Matricula),
    ("livros", Livro),
    ("leituras", Leitura),
    ("importacoes", Importacao),
    ("snapshots_matific", SnapshotMatific),
    ("snapshots_elefante", SnapshotElefante),
    ("niveis_dificuldade", NivelDificuldade),
    ("dificuldade_turma", DificuldadeTurma),
    ("pontuacao_nivel_turma", PontuacaoNivelTurma),
    ("referencias_normalizacao", ReferenciaNormalizacao),
    ("configuracoes", Configuracao),
    ("notas", Nota),
    # Identidade e histórico fino (v2). O mapa UUID↔aluno é o que impede a
    # próxima sincronização de voltar a casar POR NOME — perdê-lo reabria o P0
    # de alunos duplicados fechado em 7f6fe4e.
    ("identidades_externas", IdentidadeExterna),
    ("eventos_aluno", EventoAluno),
    ("sync_marcadores", SyncMarcador),
]

# Colunas que apontam para outras tabelas do backup (para remapear IDs)
FKS: dict[str, dict[str, str]] = {
    "turmas": {"professor_id": "professores"},
    "matriculas": {"aluno_id": "alunos", "turma_id": "turmas"},
    "leituras": {"aluno_id": "alunos", "livro_id": "livros"},
    "snapshots_matific": {"aluno_id": "alunos", "importacao_id": "importacoes"},
    "snapshots_elefante": {"aluno_id": "alunos", "importacao_id": "importacoes"},
    "dificuldade_turma": {"nivel_id": "niveis_dificuldade"},
    "pontuacao_nivel_turma": {"turma_id": "turmas"},
    "notas": {"aluno_id": "alunos"},
    "identidades_externas": {"aluno_id": "alunos"},
    "eventos_aluno": {"aluno_id": "alunos", "livro_id": "livros",
                      "importacao_id": "importacoes"},
}

# Tabelas que o cascade destruiria e que, DE PROPÓSITO, não entram no arquivo
# pedagógico: são de outro produto (Constela Quest) ou guardam vínculo com
# contas de usuário — e usuários nunca entram no backup (ver docstring). Em vez
# de exportá-las, a restauração é RECUSADA quando têm dado da escola.
# São as raízes do cascade: quest_progresso/quest_habilidades pendem de
# quest_perfis (FK NOT NULL), então bloquear a raiz já as protege.
PROTEGIDAS_POR_RECUSA: tuple[str, ...] = (
    "quest_perfis",
    "quest_credenciais_aluno",
    "quest_tentativas",
    "responsaveis_alunos",
)

# Nome legível de cada tabela, para a mensagem que o gestor lê na tela.
ROTULOS: dict[str, str] = {
    "quest_perfis": "perfis do Constela Quest (XP, nível, avatar)",
    "quest_credenciais_aluno": "logins das crianças no Constela Quest",
    "quest_tentativas": "respostas das crianças no Constela Quest",
    "responsaveis_alunos": "vínculos de responsáveis com alunos",
    "identidades_externas": "vínculos de identidade com Matific/Elefante",
    "eventos_aluno": "linha do tempo dos alunos",
    "sync_marcadores": "marcadores de sincronização",
}

# Colunas ignoradas na exportação (recriadas na restauração)
IGNORADAS = {"id", "escola_id", "usuario_id"}

# Chave, em ``backup.restaurado`` (log de auditoria), do mapa {id novo: ``_id`` do
# arquivo} das fichas recriadas — só números. É a linhagem que impede um arquivo
# anterior a outra restauração de trazer de volta a criança excluída de vez
# (``_excluidos_depois_do_backup``).
CHAVE_MAPA_ALUNOS = "alunos_id_anterior"


def _referencias_a_usuario(modelo) -> tuple[str, ...]:
    """Colunas do modelo que apontam para ``usuarios`` e SAEM no arquivo (fora de
    ``IGNORADAS``). Varredura ESTRUTURAL do metadata, como a das perdas: coluna
    nova com FK para ``usuarios`` entra no radar sozinha."""
    return tuple(coluna.name for coluna in modelo.__table__.columns
                 if coluna.name not in IGNORADAS
                 and any(fk.target_fullname.split(".")[0] == "usuarios"
                         for fk in coluna.foreign_keys))


# Referências a USUÁRIO que viajam no arquivo (hoje só
# ``identidades_externas.aposentada_por_id``, quem aposentou a conta duplicada).
# Usuários não entram no backup, então elas não são remapeadas: voltam como vieram
# quando o usuário ainda existe e viram NULL quando ele não existe mais — removido
# em definitivo depois do backup (DELETE /usuarios/{id}/permanente; na linha viva
# a FK é SET NULL) ou arquivo levado para outro banco. Antes o INSERT violava a FK
# e a restauração inteira voltava 400 "dados inconsistentes ou duplicados": o
# backup antigo, justamente o motivo de restaurar, deixava de ser restaurável (4ª
# revisão de integração do e97). O resto da linha (status, aposentada_em, motivo)
# fica como veio.
REFERENCIAS_A_USUARIO: dict[str, tuple[str, ...]] = {
    nome: colunas for nome, modelo in MODELOS
    if (colunas := _referencias_a_usuario(modelo))
}

# Configurações (namespace) que guardam SEGREDO ou dão ACESSO. Valor = campos do
# ``valor`` que não saem no arquivo; ``None`` = a linha inteira fica fora. Na
# restauração, as linhas atuais desses namespaces ficam INTACTAS e as do arquivo
# são ignoradas (inclusive as de backups antigos, que ainda trazem os segredos):
#   * painel_publico — o ``token`` é o link sem senha do telão. A linha inteira é
#     preservada (não só o token): desativar o painel guarda o token antigo, então
#     repor só o ``ativo`` do arquivo reabriria o link antigo; e o ``anonimizar``
#     do arquivo pularia a confirmação explícita de expor nomes completos;
#   * assistente — ``api_key_cifrada`` (cifra da DEK; a chave de um provedor nunca
#     pode ir para outro, então provedor e chave ficam juntos, como estão);
#   * matific_sessao — sessão do Matific cifrada (efêmera; a de outra conta ou de
#     antes da troca de credenciais não pode voltar).
SEGREDOS_DE_CONFIGURACAO: dict[str, tuple[str, ...] | None] = {
    "painel_publico": ("token",),
    "assistente": ("api_key_cifrada",),
    "matific_sessao": None,
}

# Namespaces que a restauração NÃO toca: as linhas atuais ficam intactas e as do
# arquivo são ignoradas. Além dos segredos/acesso acima, as duas TRAVAS da
# sincronização, que só o Admin Global grava (com auditoria de/para) e que são a
# mitigação da coleta mista (D8/A6):
#   * ``politica_sync.NAMESPACE`` — a política de criação de aluno. Restaurar um
#     arquivo de antes do "bloquear" a fazia voltar ao padrão "permitir" em
#     silêncio, e a coleta seguinte voltava a CRIAR fichas (irreversível);
#   * ``escola_externa.NAMESPACE`` — o vínculo da escola externa (D7). Restaurar
#     apagava o vínculo explícito ou regravava o de quando a escola tinha a escola
#     externa X, hoje de outra escola, sem a regra do 409
#     (``escolas_com_o_mesmo_vinculo``): as duas coletas paravam com
#     ``escola_externa_em_outra_escola``.
# Diferente dos segredos, essas linhas CONTINUAM saindo no arquivo (o export não
# muda); só a restauração deixa de repô-las.
PRESERVADAS_NA_RESTAURACAO: tuple[str, ...] = (
    *SEGREDOS_DE_CONFIGURACAO, politica_sync.NAMESPACE, escola_externa.NAMESPACE)


class RestauracaoBloqueada(Exception):
    """A restauração destruiria dados que o arquivo não consegue repor.

    ``perdas`` mapeia tabela -> nº de linhas da escola que seriam perdidas.
    Levantada ANTES de qualquer ``DELETE``: o banco fica intocado.
    """

    def __init__(self, perdas: dict[str, int]):
        self.perdas = perdas
        detalhe = "; ".join(f"{ROTULOS.get(t, t)}: {n} registro(s)"
                            for t, n in sorted(perdas.items()))
        super().__init__(
            "Restauração cancelada para não destruir dados que este arquivo não "
            f"contém — {detalhe}. Nada foi alterado. Para voltar a escola a um "
            "estado anterior por inteiro, use o backup do banco de dados "
            "(pg_dump), que cobre todas as tabelas.")


def _fecho_cascade(metadata, raizes: set[str]) -> set[str]:
    """Fecho transitivo de ``ON DELETE CASCADE`` a partir de ``raizes``.

    Apagar as raízes apaga, em cadeia, tudo o que este conjunto contém
    (ex.: alunos → quest_perfis → quest_progresso)."""
    alcancadas = set(raizes)
    while True:
        novas = {
            tabela.name
            for tabela in metadata.tables.values()
            if tabela.name not in alcancadas
            and any((fk.ondelete or "").upper() == "CASCADE"
                    and fk.column.table.name in alcancadas
                    for fk in tabela.foreign_keys)
        }
        if not novas:
            return alcancadas
        alcancadas |= novas


def _tabelas_destruidas(metadata) -> set[str]:
    """Toda tabela que uma restauração apaga: as deletadas diretamente (as do
    ``MODELOS``) mais o que o banco derruba por cascade."""
    return _fecho_cascade(metadata, {m.__tablename__ for _, m in MODELOS})


def _registrar_tabelas_protegidas() -> None:
    """Garante que as tabelas de ``PROTEGIDAS_POR_RECUSA`` estejam no metadata.

    Elas são consultadas POR NOME, e um nome só existe no metadata depois que o
    módulo que o declara é importado. ``app.models`` não importa o Quest, então
    quem chega em ``backup`` sem passar pelo ``main`` (um script de manutenção,
    uma tarefa de fila, um teste) veria ``KeyError`` — e o ``KeyError`` NÃO é
    tratado em ``admin.restaurar_backup``, virando 500. Importar aqui torna a
    pré-condição verdadeira em vez de deixá-la depender de efeito colateral de
    import alheio. Deliberadamente NÃO se tolera tabela ausente: engolir o erro
    seria voltar a destruir dado do Quest em silêncio — exatamente o C-06."""
    import app.quest.models  # noqa: F401  (popula Base.metadata)


def _contar(db: Session, tabela: str, escola_id: int) -> int:
    from app.core.database import Base  # noqa: E402  (evita ciclo no import)
    t = Base.metadata.tables[tabela]
    return int(db.execute(
        select(func.count()).select_from(t).where(t.c.escola_id == escola_id)
    ).scalar_one())


def perdas_da_restauracao(db: Session, escola_id: int,
                          tabelas_no_arquivo: set[str]) -> dict[str, int]:
    """Linhas da escola que a restauração APAGARIA sem conseguir repor.

    Um só conceito cobrindo os dois buracos:
      1. tabelas que o cascade destrói e que o formato não carrega (Quest,
         responsáveis);
      2. tabelas que o formato carrega mas que ESTE arquivo não traz — backup
         da versão 1, ou arquivo truncado. Sem isto, ``tabelas.get(nome, [])``
         apagaria a tabela e inseriria zero linha: a mesma perda silenciosa,
         por omissão.
    """
    _registrar_tabelas_protegidas()
    perdas: dict[str, int] = {}
    for nome in PROTEGIDAS_POR_RECUSA:
        quantas = _contar(db, nome, escola_id)
        if quantas:
            perdas[nome] = quantas
    for nome, modelo in MODELOS:
        if nome in tabelas_no_arquivo:
            continue
        quantas = int(db.execute(
            select(func.count()).select_from(modelo)
            .where(modelo.escola_id == escola_id)).scalar_one())
        if quantas:
            perdas[nome] = quantas
    return perdas


def _serializar(valor: Any) -> Any:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor


def _configuracao_sem_segredo(linha: dict) -> dict | None:
    """A linha de ``configuracoes`` como pode sair no arquivo: sem os campos de
    segredo (``SEGREDOS_DE_CONFIGURACAO``), ou ``None`` quando ela fica toda fora."""
    if linha.get("namespace") not in SEGREDOS_DE_CONFIGURACAO:
        return linha
    campos = SEGREDOS_DE_CONFIGURACAO[linha["namespace"]]
    if campos is None:
        return None
    valor = linha.get("valor")
    if isinstance(valor, dict):
        linha = {**linha, "valor": {k: v for k, v in valor.items() if k not in campos}}
    return linha


def exportar(db: Session, escola_id: int) -> dict:
    escola = db.get(Escola, escola_id)
    dados: dict[str, Any] = {
        "versao": VERSAO_BACKUP,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "escola": {"nome": escola.nome, "ano_letivo_ativo": escola.ano_letivo_ativo},
        # Marca do log no momento do arquivo: a restauração não traz de volta quem foi
        # excluído de vez DEPOIS dele (``_excluidos_depois_do_backup``). A régua é a
        # do log INTEIRO (``_ultimo_log``), a mesma das exclusões e da linhagem.
        "log_ate": _ultimo_log(db),
        "tabelas": {},
    }
    for nome, modelo in MODELOS:
        linhas = db.execute(
            select(modelo).where(modelo.escola_id == escola_id).order_by(modelo.id)
        ).scalars().all()
        dados["tabelas"][nome] = [
            {
                "_id": linha.id,
                **{
                    coluna.name: _serializar(getattr(linha, coluna.name))
                    for coluna in modelo.__table__.columns
                    if coluna.name not in IGNORADAS
                },
            }
            for linha in linhas
        ]
    dados["tabelas"]["configuracoes"] = [
        limpa for linha in dados["tabelas"]["configuracoes"]
        if (limpa := _configuracao_sem_segredo(linha)) is not None
    ]
    return dados


def _desserializar(modelo, campo: str, valor: Any) -> Any:
    if valor is None:
        return None
    tipo = modelo.__table__.columns[campo].type.python_type
    if tipo is datetime and isinstance(valor, str):
        return datetime.fromisoformat(valor)
    if tipo is date and isinstance(valor, str):
        return date.fromisoformat(valor)
    return valor


def _ultimo_log(db: Session) -> int:
    """O último id do log de auditoria INTEIRO, de qualquer escola: o ``log_ate`` do
    arquivo, que separa o "antes" do "depois" do backup.

    Global porque é a régua das exclusões e da linhagem
    (``_excluidos_depois_do_backup``), que valem em qualquer escola; o id do log é
    global e só cresce. Antes era o último id do log DESTA escola: a exclusão de vez
    feita em OUTRA escola antes do backup, com id maior que o último log desta, contava
    como "depois". O arquivo de A gerado depois que B excluiu de vez a cópia (a ficha de
    A viva e no arquivo) apagava a ficha de A na restauração, com o aviso "depois deste
    backup", e bastava baixar de novo (o ``backup.gerado`` do 1º download sobe a marca)
    para ela voltar (revisão adversarial do e97w-final).

    O arquivo sai para o admin da escola e passa a levar o contador do log inteiro: um
    número só, sem registro de outra escola (revela, no máximo, o volume do log). Os ids
    do log já são globais e o admin já vê os desta escola (``GET /notificacoes``)."""
    return int(db.execute(select(func.max(LogAuditoria.id))).scalar() or 0)


def _ligacoes_entre_restauracoes(db: Session) -> dict[int, set[int]]:
    """Linhagem das fichas, pelas restaurações de QUALQUER escola: cada restauração
    recria a ficha com id NOVO e grava em ``backup.restaurado`` o mapa {id novo:
    ``_id`` do arquivo} (``CHAVE_MAPA_ALUNOS``; preservado do expurgo). Devolve as
    ligações nos dois sentidos. Registro sem o mapa (restauração anterior a ele) ou
    com o mapa ilegível não liga nada.

    Não filtra pela escola de destino, como as exclusões
    (``_excluidos_depois_do_backup``): o arquivo da escola A gerado ANTES de uma
    restauração de A, restaurado na escola B, leva o id antigo, e só o log de A liga
    esse id ao id novo, que a exclusão de vez gravou. Com o filtro, a criança excluída
    de vez em A voltava em B sem aviso (revisão de integração do e97). No PostgreSQL o
    id do aluno é global e nunca volta a ser usado, então cada ligação é a mesma
    criança, seja qual for a escola do registro."""
    ligacoes: dict[int, set[int]] = {}
    for detalhes in db.execute(select(LogAuditoria.detalhes).where(
            LogAuditoria.acao == "backup.restaurado")).scalars():
        mapa = detalhes.get(CHAVE_MAPA_ALUNOS) if isinstance(detalhes, dict) else None
        if not isinstance(mapa, dict):
            continue
        for novo, antigo in mapa.items():
            try:
                novo, antigo = int(novo), int(antigo)
            except (TypeError, ValueError):
                continue
            ligacoes.setdefault(novo, set()).add(antigo)
            ligacoes.setdefault(antigo, set()).add(novo)
    return ligacoes


def _excluidos_depois_do_backup(db: Session, escola_id: int, log_ate: Any) -> set[int]:
    """Ids das fichas excluídas DE VEZ depois do backup, em QUALQUER escola.

    A prova é o ``aluno.excluido_permanente`` do log (preservado do expurgo:
    ``audit.ACOES_PRESERVADAS``), cujo ``entidade_id`` é o id da ficha. ``log_ate``
    (o último id do log INTEIRO, de qualquer escola, quando o arquivo foi gerado:
    ``_ultimo_log``; o id do log é global e só cresce) separa o "depois" sem comparar
    datas, com a mesma régua das exclusões e da linhagem; arquivo antigo, sem ele,
    confere toda exclusão permanente.

    ``escola_id`` é a escola de DESTINO da restauração e NÃO filtra as exclusões nem a
    linhagem: a rota não confere a origem do arquivo, e o arquivo da escola A
    restaurado na escola B trazia de volta, sem aviso, a criança que A excluiu de vez
    (o log da exclusão leva a escola de onde ela saiu).

    A restauração recria cada ficha com id novo: a exclusão feita depois de uma
    restauração grava o id NOVO, e um arquivo anterior a ela leva o ANTIGO. Por isso
    o conjunto segue a linhagem gravada pelas restaurações de qualquer escola
    (``_ligacoes_entre_restauracoes``), em cadeia: todo id que a mesma criança teve
    entra. No PostgreSQL um id nunca volta a ser usado, então cada id do conjunto é
    uma encarnação da criança excluída (nunca outra criança). (No SQLite de
    desenvolvimento, que reaproveita id, uma ficha com o id reaproveitado pode ficar
    de fora — com o aviso.)"""
    consulta = (select(LogAuditoria.entidade_id)
                .where(LogAuditoria.acao == "aluno.excluido_permanente",
                       LogAuditoria.entidade_id.is_not(None)))
    if isinstance(log_ate, int) and not isinstance(log_ate, bool):
        consulta = consulta.where(LogAuditoria.id > log_ate)
    excluidos = {int(i) for i in db.execute(consulta).scalars()}
    if not excluidos:
        return excluidos
    ligacoes = _ligacoes_entre_restauracoes(db)
    pendentes = list(excluidos)
    while pendentes:
        for outro in ligacoes.get(pendentes.pop(), ()):
            if outro not in excluidos:
                excluidos.add(outro)
                pendentes.append(outro)
    return excluidos


def restaurar(db: Session, escola_id: int, dados: dict,
              avisos: list[str] | None = None,
              mapa_alunos: dict[int, int] | None = None) -> dict[str, int]:
    """Substitui os dados pedagógicos da escola pelos do backup.

    Tudo acontece em uma única transação: ou restaura completo, ou nada.
    Retorna a contagem de linhas restauradas por tabela.

    Levanta ``RestauracaoBloqueada`` — ANTES de apagar coisa alguma — quando a
    operação destruiria dado que este arquivo não repõe (C-06).

    LGPD (art. 18, eliminação): a criança excluída de vez DEPOIS do backup (em
    qualquer escola) não volta, nem os dados dela (matrícula, leituras, retratos,
    notas, identidades, eventos); ``avisos`` (opcional) recebe quantas ficaram de
    fora, sem nome. Vale também para o arquivo gerado antes de outra restauração (que
    troca os ids das fichas), pela linhagem que cada restauração grava no log — a de
    qualquer escola (o arquivo de A anterior a uma restauração de A, restaurado em B):
    ``mapa_alunos`` (opcional) recebe o {id novo: ``_id`` do arquivo} das fichas
    recriadas, que quem chama grava em ``backup.restaurado`` (``CHAVE_MAPA_ALUNOS``).

    A ficha que um arquivo de A, restaurado em B, criou em B é a MESMA criança (a
    linhagem liga as duas). Decisão conservadora (art. 18: o pedido de eliminação vale
    para as cópias): excluída de vez uma delas, a outra não volta com um backup gerado
    ANTES da exclusão — nem a cópia de B pelo backup de B, nem a ficha de A pelo backup
    de A —, com o aviso "nesta ou em outra escola". A exclusão não apaga a ficha viva da
    outra escola (cada escola exclui a sua); só a restauração deixa de repô-la. O backup
    gerado DEPOIS da exclusão traz a ficha viva da outra escola como ela estava (a
    exclusão é anterior ao arquivo; ``log_ate`` é a marca do log inteiro: ``_ultimo_log``).

    Ressalva: restauração registrada sem esse mapa (anterior a ele) ou registro
    apagado quebra a linhagem — a criança excluída depois dela pode voltar sem aviso;
    confira a exclusão à mão.
    """
    if dados.get("versao") not in VERSOES_ACEITAS:
        raise ValueError("Versão de backup não suportada.")
    tabelas = dados.get("tabelas")
    if not isinstance(tabelas, dict):
        raise ValueError("Arquivo de backup inválido: bloco de tabelas ausente.")

    # PORTÃO (C-06): nada é apagado enquanto houver dado que não voltaria.
    perdas = perdas_da_restauracao(db, escola_id, set(tabelas))
    if perdas:
        raise RestauracaoBloqueada(perdas)
    excluidos = _excluidos_depois_do_backup(db, escola_id, dados.get("log_ate"))
    nao_restaurados: set[int] = set()

    # Apaga os dados atuais da escola (filhos antes dos pais) — menos as
    # configurações de segredo/acesso e as travas da sincronização
    # (``PRESERVADAS_NA_RESTAURACAO``), que a restauração não toca.
    preservadas = PRESERVADAS_NA_RESTAURACAO
    for nome, modelo in reversed(MODELOS):
        consulta = delete(modelo).where(modelo.escola_id == escola_id)
        if modelo is Configuracao:
            consulta = consulta.where(Configuracao.namespace.not_in(preservadas))
        db.execute(consulta)

    # Avisos que apontam para UMA criança viram lixo perigoso depois da troca:
    # `Notificacao.aluno_id` é um int solto (sem FK), e o banco reaproveita IDs
    # de linhas apagadas — o aviso antigo passaria a apontar para OUTRA criança,
    # aparecendo no mural do professor errado e com um link para o perfil
    # errado. São estado derivado (renascem do próximo evento), então some com
    # o dado que os originou. Os avisos da escola sem aluno_id ficam.
    from app.models import Notificacao  # noqa: E402  (evita ciclo no import)
    db.execute(delete(Notificacao).where(Notificacao.escola_id == escola_id,
                                         Notificacao.aluno_id.is_not(None)))

    contagem: dict[str, int] = {}
    mapas: dict[str, dict[int, int]] = {}  # tabela -> {id antigo: id novo}
    usuarios_existentes: dict[int, bool] = {}   # 1 consulta por usuário citado

    def _usuario_existe(valor: Any) -> bool:
        chave = int(valor)
        if chave not in usuarios_existentes:
            usuarios_existentes[chave] = db.get(Usuario, chave) is not None
        return usuarios_existentes[chave]

    for nome, modelo in MODELOS:
        mapas[nome] = {}
        linhas = tabelas.get(nome, [])
        restauradas = 0
        for linha in linhas:
            if not isinstance(linha, dict):
                raise ValueError(f"Linha inválida na tabela “{nome}”.")
            if modelo is Configuracao and linha.get("namespace") in preservadas:
                # segredo/acesso do arquivo (backup antigo) ou trava da sync: a
                # linha atual fica, a do arquivo nunca volta.
                continue
            id_antigo = linha.get("_id")
            if modelo is Aluno and id_antigo is not None and int(id_antigo) in excluidos:
                nao_restaurados.add(int(id_antigo))
                continue
            if any(tabela_pai == "alunos" and linha.get(campo_fk) is not None
                   and int(linha[campo_fk]) in nao_restaurados
                   for campo_fk, tabela_pai in FKS.get(nome, {}).items()):
                continue    # dado da criança excluída de vez (ver acima)
            campos = {
                campo: _desserializar(modelo, campo, valor)
                for campo, valor in linha.items()
                if campo != "_id" and campo in modelo.__table__.columns
            }
            # Remapeia chaves estrangeiras para os novos IDs
            for campo_fk, tabela_pai in FKS.get(nome, {}).items():
                antigo = campos.get(campo_fk)
                if antigo is not None:
                    novo = mapas[tabela_pai].get(int(antigo))
                    if novo is None:
                        raise ValueError(
                            f"Backup inconsistente: “{nome}.{campo_fk}” aponta para "
                            f"registro inexistente ({antigo})."
                        )
                    campos[campo_fk] = novo
            # Usuário que não existe mais (``REFERENCIAS_A_USUARIO``): só a
            # referência some; a linha volta inteira.
            for campo_usuario in REFERENCIAS_A_USUARIO.get(nome, ()):
                if campos.get(campo_usuario) is not None and not _usuario_existe(
                        campos[campo_usuario]):
                    campos[campo_usuario] = None
            objeto = modelo(escola_id=escola_id, **campos)
            db.add(objeto)
            db.flush()
            restauradas += 1
            if id_antigo is not None:
                mapas[nome][int(id_antigo)] = objeto.id
        contagem[nome] = restauradas
    if mapa_alunos is not None:
        mapa_alunos.update({novo: antigo for antigo, novo in mapas.get("alunos", {}).items()})
    if nao_restaurados and avisos is not None:
        # "nesta ou em outra escola": a exclusão pode ter sido de outra ficha da mesma
        # criança, em outra escola (a cópia que um arquivo restaurado levou para lá).
        avisos.append(f"{len(nao_restaurados)} criança(s) excluída(s) permanentemente "
                      "(nesta ou em outra escola) depois deste backup não foram "
                      "restauradas (direito de eliminação, LGPD art. 18).")
    return contagem
