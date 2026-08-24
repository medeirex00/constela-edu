"""Backup e restauração por escola (PRD §18).

O backup é um JSON portátil (funciona igual em SQLite e PostgreSQL) com
todos os dados pedagógicos da escola. A restauração substitui os dados da
escola remapeando os IDs — nunca reutiliza IDs antigos, que podem já
pertencer a outra escola no mesmo banco.

Usuários NÃO entram no backup de dados: restaurar um arquivo antigo não
pode reverter senhas nem reativar contas desligadas (segurança > conveniência).

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
)

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


def exportar(db: Session, escola_id: int) -> dict:
    escola = db.get(Escola, escola_id)
    dados: dict[str, Any] = {
        "versao": VERSAO_BACKUP,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "escola": {"nome": escola.nome, "ano_letivo_ativo": escola.ano_letivo_ativo},
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


def restaurar(db: Session, escola_id: int, dados: dict) -> dict[str, int]:
    """Substitui os dados pedagógicos da escola pelos do backup.

    Tudo acontece em uma única transação: ou restaura completo, ou nada.
    Retorna a contagem de linhas restauradas por tabela.

    Levanta ``RestauracaoBloqueada`` — ANTES de apagar coisa alguma — quando a
    operação destruiria dado que este arquivo não repõe (C-06).
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

    # Apaga os dados atuais da escola (filhos antes dos pais)
    for nome, modelo in reversed(MODELOS):
        db.execute(delete(modelo).where(modelo.escola_id == escola_id))

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
    for nome, modelo in MODELOS:
        mapas[nome] = {}
        linhas = tabelas.get(nome, [])
        for linha in linhas:
            if not isinstance(linha, dict):
                raise ValueError(f"Linha inválida na tabela “{nome}”.")
            id_antigo = linha.get("_id")
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
            objeto = modelo(escola_id=escola_id, **campos)
            db.add(objeto)
            db.flush()
            if id_antigo is not None:
                mapas[nome][int(id_antigo)] = objeto.id
        contagem[nome] = len(linhas)
    return contagem
