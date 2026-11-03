from app.quest.models.catalogo import (
    QuestDesafio,
    QuestJornada,
    QuestMissao,
    QuestMundo,
)
from app.quest.models.limite import QuestLimiteAcesso
from app.quest.models.perfil import (
    QuestCredencialAluno,
    QuestPerfil,
    ResponsavelAluno,
)
from app.quest.models.progresso import (
    QuestHabilidade,
    QuestProgresso,
    QuestTentativa,
)

__all__ = [
    "QuestCredencialAluno",
    "QuestDesafio",
    "QuestHabilidade",
    "QuestJornada",
    "QuestLimiteAcesso",
    "QuestMissao",
    "QuestMundo",
    "QuestPerfil",
    "QuestProgresso",
    "QuestTentativa",
    "ResponsavelAluno",
]
