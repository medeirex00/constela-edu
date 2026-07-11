"""Isolamento multi-escola dos agregados do Quest (R5 / §11, Princípio 15).

`quest_progresso` e `quest_habilidades` NÃO têm coluna `escola_id` (tenancy
transitiva: a escola vem por `perfil_id`→`quest_perfis`, Estratégia B, sem
migração). Este é o TETO DE CONTRATO: prova que o helper obrigatório
(`app.quest.services.agregados`) escopa por escola e que a escola A nunca
enxerga os agregados da escola B. Um reader que consultasse por `perfil_id`
"solto" (sem o join) vazaria — e o teste `test_query_sem_join_vazaria` fixa
exatamente esse risco, justificando a existência do helper.
"""
import ast
from pathlib import Path

from sqlalchemy import select

from app.models import Aluno, Escola
from app.quest.models import (
    QuestHabilidade,
    QuestJornada,
    QuestMissao,
    QuestMundo,
    QuestPerfil,
    QuestProgresso,
)
from app.quest.services import agregados


def _catalogo_missao(db) -> QuestMissao:
    """Missão global mínima (mundo→jornada→missao), compartilhada pelas escolas."""
    mundo = QuestMundo(slug="mat", nome="Matemática")
    db.add(mundo)
    db.flush()
    jornada = QuestJornada(mundo_id=mundo.id, nome="Trilha 1", ano_escolar="3º Ano")
    db.add(jornada)
    db.flush()
    missao = QuestMissao(jornada_id=jornada.id, nome="Missão 1", status="publicada")
    db.add(missao)
    db.flush()
    return missao


def _escola_com_perfil(db, nome_escola, apelido, codigo_amigo) -> tuple:
    escola = Escola(nome=nome_escola, ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    aluno = Aluno(escola_id=escola.id, nome=f"Aluno {apelido}")
    db.add(aluno)
    db.flush()
    perfil = QuestPerfil(escola_id=escola.id, aluno_id=aluno.id,
                         apelido=apelido, codigo_amigo=codigo_amigo)
    db.add(perfil)
    db.flush()
    return escola, perfil


def _semear(db):
    """Duas escolas, cada uma com 1 perfil + 1 progresso + 1 habilidade."""
    missao = _catalogo_missao(db)
    escola_a, perfil_a = _escola_com_perfil(db, "ESCOLA A", "AstroA", "AMIGOA01")
    escola_b, perfil_b = _escola_com_perfil(db, "ESCOLA B", "AstroB", "AMIGOB01")

    db.add(QuestProgresso(perfil_id=perfil_a.id, missao_id=missao.id, estrelas=3))
    db.add(QuestProgresso(perfil_id=perfil_b.id, missao_id=missao.id, estrelas=1))
    db.add(QuestHabilidade(perfil_id=perfil_a.id, bncc_codigo="EF03MA01", dominio=90.0))
    db.add(QuestHabilidade(perfil_id=perfil_b.id, bncc_codigo="EF03MA01", dominio=10.0))
    db.flush()
    return escola_a, perfil_a, escola_b, perfil_b


def test_progresso_da_escola_so_ve_a_propria(db):
    escola_a, perfil_a, escola_b, perfil_b = _semear(db)

    linhas_a = db.execute(agregados.progresso_da_escola(escola_a.id)).scalars().all()
    linhas_b = db.execute(agregados.progresso_da_escola(escola_b.id)).scalars().all()

    assert [p.perfil_id for p in linhas_a] == [perfil_a.id]     # só a escola A
    assert [p.perfil_id for p in linhas_b] == [perfil_b.id]     # só a escola B
    assert linhas_a[0].estrelas == 3 and linhas_b[0].estrelas == 1


def test_habilidades_da_escola_so_ve_a_propria(db):
    escola_a, perfil_a, escola_b, perfil_b = _semear(db)

    linhas_a = db.execute(agregados.habilidades_da_escola(escola_a.id)).scalars().all()
    linhas_b = db.execute(agregados.habilidades_da_escola(escola_b.id)).scalars().all()

    assert [h.perfil_id for h in linhas_a] == [perfil_a.id]
    assert [h.perfil_id for h in linhas_b] == [perfil_b.id]
    assert linhas_a[0].dominio == 90.0 and linhas_b[0].dominio == 10.0


def test_escola_inexistente_nao_traz_nada(db):
    _semear(db)
    vazio = db.execute(agregados.progresso_da_escola(999_999)).scalars().all()
    assert vazio == []


def test_query_sem_join_vazaria(db):
    """Documenta POR QUE o helper existe: a tabela crua não tem escola_id, então
    uma consulta 'solta' (sem o join de agregados) mistura TODAS as escolas."""
    _semear(db)
    todas = db.execute(select(QuestProgresso)).scalars().all()
    # Sem o join por escola, as duas escolas aparecem juntas — o vazamento que
    # o helper (e este teto de contrato) impedem.
    assert len(todas) == 2


# ---------------------------------------------------------------------------
# Enforcement mecânico: a regra do §11 vira CATRACA, não só convenção verbal
# ---------------------------------------------------------------------------

_APP_DIR = Path(__file__).resolve().parents[1] / "app"
# Caminho EXATO do único módulo autorizado a montar o SELECT cru (não é por
# basename: um futuro app/**/agregados.py qualquer NÃO herda a isenção).
_ARQUIVO_SANCIONADO = Path("quest") / "services" / "agregados.py"
_MODELOS_PROTEGIDOS = {"QuestProgresso", "QuestHabilidade"}
_CONSTRUTORES_DE_QUERY = {"select", "query"}


def _alvo_da_chamada(no: ast.AST) -> str | None:
    """Nome do modelo em `select(X)` ou `select(X.coluna)` — None caso contrário."""
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name):
        return no.value.id
    return None


def _leituras_cruas(arvore: ast.AST) -> list[int]:
    """Linhas com select(Quest…)/query(Quest…) sobre um agregado protegido.

    Usa AST (não regex) de propósito: assim menções em docstring/comentário —
    como as que descrevem esta própria regra nos modelos — NÃO contam; só a
    construção real da query conta."""
    linhas = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call) or not no.args:
            continue
        func = no.func
        nome_func = (func.id if isinstance(func, ast.Name)
                     else func.attr if isinstance(func, ast.Attribute) else None)
        if nome_func in _CONSTRUTORES_DE_QUERY \
                and _alvo_da_chamada(no.args[0]) in _MODELOS_PROTEGIDOS:
            linhas.append(no.lineno)
    return linhas


def test_leitura_dos_agregados_so_pelo_helper():
    """Enforcement REAL do isolamento transitivo (R5/§11): NENHUM módulo de
    produção monta um SELECT sobre quest_progresso/quest_habilidades fora de
    `app.quest.services.agregados`. Isto transforma a convenção em gate: um
    reader que consulte por `perfil_id` 'solto' (sem o join por escola) faz
    ESTE teste falhar — antes de vazar entre escolas em produção. Barra o
    bypass acidental pelo nome direto do modelo; uma evasão DELIBERADA (alias de
    import ou acesso qualificado, `select(m.QuestProgresso)`) escaparia — não é
    o alvo, que é o esquecimento honesto."""
    infratores = []
    for py in _APP_DIR.rglob("*.py"):
        if py.relative_to(_APP_DIR) == _ARQUIVO_SANCIONADO:
            continue
        arvore = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        infratores += [f"{py.relative_to(_APP_DIR)}:{linha}"
                       for linha in _leituras_cruas(arvore)]
    assert not infratores, (
        "Leitura crua de quest_progresso/quest_habilidades FORA de agregados.py "
        "(viola o isolamento transitivo §11/R5 — use app.quest.services.agregados):\n"
        + "\n".join(infratores))
