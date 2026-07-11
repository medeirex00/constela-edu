"""Leitura ESCOPADA dos agregados de progresso/habilidade do aluno.

`quest_progresso` e `quest_habilidades` NÃO têm coluna `escola_id` — a escola
é derivada por `perfil_id`→`quest_perfis` (tenancy transitiva, §11 / Estratégia
B, sem migração de schema). Para o isolamento multi-escola (Princípio 15)
valer, TODO reader desses agregados DEVE partir destas funções, que já embutem
o JOIN obrigatório em `quest_perfis` + o filtro por `escola_id`.

Consultar `quest_progresso`/`quest_habilidades` por `perfil_id` "solto" (sem
esse join) é proibido, e a regra é **catraca mecânica**, não só convenção:
`test_leitura_dos_agregados_so_pelo_helper` (em `test_quest_isolamento`) faz o
build falhar se algum módulo fora daqui montar `select`/`query` sobre esses
modelos — barra o bypass acidental pelo nome direto (uma evasão deliberada por
alias/import qualificado escaparia; não é o alvo). Denormalizar `escola_id` na
tabela exigiria um ADR (governança ADR-0001).

Nota (evolução Q4+): quando surgirem rotas do ALUNO lendo o próprio progresso
(escopo por `perfil_id`, não por escola), o helper irmão — ex. `progresso_do_
perfil(perfil_id)` — nasce AQUI, para continuar dentro do arquivo sancionado
pela catraca. Não existe reader assim hoje.
"""
from __future__ import annotations

from sqlalchemy import Select, select

from app.quest.models import QuestHabilidade, QuestPerfil, QuestProgresso


def progresso_da_escola(escola_id: int) -> Select:
    """SELECT de quest_progresso escopado por escola (join em quest_perfis)."""
    return (
        select(QuestProgresso)
        .join(QuestPerfil, QuestProgresso.perfil_id == QuestPerfil.id)
        .where(QuestPerfil.escola_id == escola_id)
    )


def habilidades_da_escola(escola_id: int) -> Select:
    """SELECT de quest_habilidades escopado por escola (join em quest_perfis)."""
    return (
        select(QuestHabilidade)
        .join(QuestPerfil, QuestHabilidade.perfil_id == QuestPerfil.id)
        .where(QuestPerfil.escola_id == escola_id)
    )
