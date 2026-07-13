from app.models.academico import Aluno, Matricula, Professor, Turma
from app.models.configuracao import (
    Configuracao,
    DificuldadeTurma,
    NivelDificuldade,
    PontuacaoNivelTurma,
    ReferenciaNormalizacao,
)
from app.models.dispositivo import DispositivoMovel
from app.models.escola import Escola
from app.models.ia import ConversaIA, MensagemIA
from app.models.nota import LogAuditoria, Nota
from app.models.plataformas import (
    EventoAluno,
    Importacao,
    Leitura,
    Livro,
    SnapshotElefante,
    SnapshotMatific,
    SyncMarcador,
)
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.models.token_reset import TokenResetSenha
from app.models.usuario import Usuario

__all__ = [
    "Aluno",
    "Configuracao",
    "ConversaIA",
    "DispositivoMovel",
    "EventoAluno",
    "MensagemIA",
    "DificuldadeTurma",
    "Escola",
    "Importacao",
    "SyncMarcador",
    "Leitura",
    "Livro",
    "LogAuditoria",
    "Matricula",
    "NivelDificuldade",
    "PontuacaoNivelTurma",
    "Nota",
    "Professor",
    "ReferenciaNormalizacao",
    "SnapshotElefante",
    "SnapshotMatific",
    "TokenResetSenha",
    "Turma",
    "Usuario",
]
