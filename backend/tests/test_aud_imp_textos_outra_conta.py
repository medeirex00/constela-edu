"""Auditoria (frente importação): o texto de "outra conta leva ao mesmo aluno".

IMPORTACAO-11 / REVERIFICACAO-2: o motivo ``outra_identidade_na_plataforma`` nasce
por três caminhos (``identidade_aluno._para_aluno``): a ficha já tem outra conta;
outra conta DESTE relatório leva a ela; ou uma conta numa pendência aberta leva a
ela. O texto do backend (``MOTIVOS``) — que vai para os avisos do /confirmar e para o
``motivo_texto`` da fila — e o da triagem automática (``MULTI_IDENTIDADE``) diziam
que "o aluno encontrado já tem outra conta nesta plataforma" / "a ficha já tem outra
conta", também quando a ficha não tem conta nenhuma: quem decidia procurava uma conta
que não existe. Dados fictícios.
"""
from sqlalchemy import func, select

from tests.test_importacao_previa_motivo import (
    PLACAR_SOFIA_DUAS, PLACAR_SOFIA_UMA, _analise, _confirmar, _corpo_padrao)

API = "/api/v1"
FALSOS = ("já tem outra conta", "ja tem outra conta")


def _sem_falso(textos):
    return [t for t in textos if any(f in (t or "") for f in FALSOS)]


def test_ficha_sem_conta_nao_e_dita_com_outra_conta(cliente, db, escola_completa):
    from app.models import Aluno, IdentidadeExterna

    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    sofia = db.execute(select(Aluno).where(Aluno.escola_id == eid,
                                           Aluno.nome == "Sofia Almeida Duarte")).scalar_one()
    a1 = _analise(cliente, eid, PLACAR_SOFIA_DUAS)
    r1 = _confirmar(cliente, eid, a1, _corpo_padrao(a1, turma))
    a2 = _analise(cliente, eid, PLACAR_SOFIA_UMA)
    r2 = _confirmar(cliente, eid, a2, _corpo_padrao(a2, turma))
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(IdentidadeExterna).where(
        IdentidadeExterna.aluno_id == sofia.id)) == 0
    avisos = [a for a in r1["avisos"] + r2["avisos"] if "Sofia" in a]
    assert avisos and not _sem_falso(avisos), avisos
    fila = cliente.get(f"{API}/escolas/{eid}/importacoes/revisoes").json()
    da_sofia = [r for r in fila if r["motivo"] == "outra_identidade_na_plataforma"]
    assert da_sofia
    assert not _sem_falso([r["motivo_texto"] for r in da_sofia]), da_sofia
    triagens = [(r.get("triagem") or {}).get("motivo_texto") for r in da_sofia]
    assert any(triagens) and not _sem_falso(triagens), triagens


def test_o_texto_cobre_os_tres_caminhos():
    """O texto continua verdadeiro quando a ficha TEM outra conta (já vinculada),
    e diz também os outros dois caminhos (este relatório, uma pendência)."""
    from app.services import identidade_aluno as ida
    from app.services import triagem_revisoes as tri

    texto = ida.MOTIVOS["outra_identidade_na_plataforma"]
    assert "outra conta" in texto
    for caminho in ("já vinculada", "neste relatório", "pendência"):
        assert caminho in texto, texto
    triagem = tri.TEXTO[tri.MULTI_IDENTIDADE]
    for caminho in ("já vinculada", "pendência"):
        assert caminho in triagem, triagem
