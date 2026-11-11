"""``vincular_livros_catalogo --congelar-niveis --aplicar`` × nível do livro corrigido
no meio (G_SCRIPTS-7).

O backfill promete gravar na leitura "exatamente" o nível que ela já vale
(``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)``). Mas a análise lê o nível
do livro num momento e o UPDATE grava esse valor depois, sem conferir que o livro
ainda está nele: se o Admin Global corrige o livro (PATCH /livros) ou a coleta
restaura o nível oficial nesse intervalo, a leitura — que já valia o nível novo
pelo ``coalesce`` — ficava congelada no VELHO, e a nota da criança caía em
silêncio na próxima conta.

Agora o UPDATE só congela a leitura cujo livro AINDA está no nível analisado (e a
escola fica travada durante a gravação, no PostgreSQL); a que mudou fica como
está (nula, seguindo o nível atual do livro) e a auditoria conta o que de fato
foi gravado. A intercalação é a da sonda da auditoria: as funções do próprio
script e uma 2ª sessão fazendo o que a API grava. Dados fictícios.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Leitura, Livro, LogAuditoria
from scripts import vincular_livros_catalogo as script


def _efetivo(db, leitura_id: int) -> str:
    db.expire_all()
    return db.execute(
        select(func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo))
        .join(Livro, Livro.id == Leitura.livro_id)
        .where(Leitura.id == leitura_id)).scalar_one()


def _cena(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    corrigido = Livro(escola_id=escola.id, titulo="Livro Fictício Seis", nivel_codigo="K")
    estavel = Livro(escola_id=escola.id, titulo="Livro Fictício Sete", nivel_codigo="D")
    db.add_all([corrigido, estavel])
    db.flush()
    # Leituras anteriores ao congelamento (nível nulo): valem o nível atual do livro.
    l1 = Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=corrigido.id)
    l2 = Leitura(escola_id=escola.id, aluno_id=joao.id, livro_id=estavel.id)
    db.add_all([l1, l2])
    db.commit()
    return escola, corrigido.id, l1.id, l2.id


def test_livro_corrigido_entre_a_analise_e_o_update_nao_congela_o_nivel_velho(
        db, escola_completa):
    escola, livro_id, leitura_corrigida, leitura_estavel = _cena(db, escola_completa)

    relatorio = script.analisar_congelamento(db, escola.id, escola.nome)
    assert {n: len(ids) for n, ids in relatorio.por_nivel.items()} == {"K": 1, "D": 1}

    # A API, em outra sessão: o Admin Global corrige o livro de K para M.
    with Session(bind=db.get_bind()) as api:
        api.get(Livro, livro_id).nivel_codigo = "M"
        api.commit()
    assert _efetivo(db, leitura_corrigida) == "M"      # o valor da leitura AGORA

    congeladas = script.congelar(db, relatorio)

    # A leitura do livro corrigido continua valendo M (não foi congelada em K).
    assert _efetivo(db, leitura_corrigida) == "M"
    assert db.get(Leitura, leitura_corrigida).nivel_codigo in (None, "M")
    # A do livro que não mudou é congelada normalmente.
    assert db.get(Leitura, leitura_estavel).nivel_codigo == "D"
    assert congeladas == 1

    # A auditoria conta o que foi gravado, não o que a análise previa.
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "leitura.nivel_congelado")).scalars().one()
    assert log.detalhes["qtd"] == 1
    assert log.detalhes["por_nivel"] == {"D": 1}
    assert log.detalhes["puladas"] == 1


def test_rodar_de_novo_congela_o_nivel_atual(db, escola_completa):
    """A leitura que ficou de fora numa corrida é congelada na próxima passada,
    com o nível que ela vale então."""
    escola, livro_id, leitura_corrigida, _ = _cena(db, escola_completa)
    relatorio = script.analisar_congelamento(db, escola.id, escola.nome)
    with Session(bind=db.get_bind()) as api:
        api.get(Livro, livro_id).nivel_codigo = "M"
        api.commit()
    script.congelar(db, relatorio)

    assert script.congelar(db, script.analisar_congelamento(db, escola.id, escola.nome)) == 1
    db.expire_all()
    assert db.get(Leitura, leitura_corrigida).nivel_codigo == "M"


def test_sem_corrida_o_congelamento_e_o_de_sempre(db, escola_completa):
    escola, _, leitura_corrigida, leitura_estavel = _cena(db, escola_completa)
    assert script.congelar(db, script.analisar_congelamento(db, escola.id, escola.nome)) == 2
    db.expire_all()
    assert (db.get(Leitura, leitura_corrigida).nivel_codigo,
            db.get(Leitura, leitura_estavel).nivel_codigo) == ("K", "D")
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "leitura.nivel_congelado")).scalars().one()
    assert log.detalhes["por_nivel"] == {"D": 1, "K": 1}
    assert log.detalhes["puladas"] == 0
