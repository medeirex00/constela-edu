"""Backup e restauração por escola (PRD §18).

O backup é um JSON portátil (funciona igual em SQLite e PostgreSQL) com
todos os dados pedagógicos da escola. A restauração substitui os dados da
escola remapeando os IDs — nunca reutiliza IDs antigos, que podem já
pertencer a outra escola no mesmo banco.

Usuários NÃO entram no backup de dados: restaurar um arquivo antigo não
pode reverter senhas nem reativar contas desligadas (segurança > conveniência).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Configuracao,
    DificuldadeTurma,
    Escola,
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
    Turma,
)

VERSAO_BACKUP = 1

# Ordem respeita as chaves estrangeiras (pais antes dos filhos)
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
}

# Colunas ignoradas na exportação (recriadas na restauração)
IGNORADAS = {"id", "escola_id", "usuario_id"}


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
    """
    if dados.get("versao") != VERSAO_BACKUP:
        raise ValueError("Versão de backup não suportada.")
    tabelas = dados.get("tabelas")
    if not isinstance(tabelas, dict):
        raise ValueError("Arquivo de backup inválido: bloco de tabelas ausente.")

    # Apaga os dados atuais da escola (filhos antes dos pais)
    for nome, modelo in reversed(MODELOS):
        db.execute(delete(modelo).where(modelo.escola_id == escola_id))

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
