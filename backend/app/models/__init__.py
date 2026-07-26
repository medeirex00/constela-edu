from app.models.academico import (
    Aluno,
    IdentidadeExterna,
    Matricula,
    Professor,
    Turma,
)
from app.models.avaliacao_externa import AvaliacaoExterna, ResultadoAvaliacao
from app.models.fonte_avaliacao import FonteAvaliacao
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
from app.models.rede import Rede
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
    "AvaliacaoExterna",
    "ResultadoAvaliacao",
    "FonteAvaliacao",
    "Configuracao",
    "ConversaIA",
    "DispositivoMovel",
    "EventoAluno",
    "IdentidadeExterna",
    "MensagemIA",
    "DificuldadeTurma",
    "Escola",
    "Rede",
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
