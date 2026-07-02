from app.models.academico import Aluno, Matricula, Professor, Turma
from app.models.configuracao import (
    Configuracao,
    DificuldadeTurma,
    NivelDificuldade,
    ReferenciaNormalizacao,
)
from app.models.escola import Escola
from app.models.nota import LogAuditoria, Nota
from app.models.plataformas import (
    Importacao,
    Leitura,
    Livro,
    SnapshotElefante,
    SnapshotMatific,
)
from app.models.usuario import Usuario

__all__ = [
    "Aluno",
    "Configuracao",
    "DificuldadeTurma",
    "Escola",
    "Importacao",
    "Leitura",
    "Livro",
    "LogAuditoria",
    "Matricula",
    "NivelDificuldade",
    "Nota",
    "Professor",
    "ReferenciaNormalizacao",
    "SnapshotElefante",
    "SnapshotMatific",
    "Turma",
    "Usuario",
]
