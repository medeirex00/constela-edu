"""Aplicar ao histórico: o nível das leituras e as notas caem JUNTOS (S_G_AJUSTE-3).

O PATCH /livros com ``aplicar_ao_historico`` gravava em commits separados: a correção
do livro, depois o histórico renivelado com a auditoria, e só então o recálculo da
escola, com o commit dele. Se o recálculo falhava (queda de conexão, tempo esgotado),
a resposta era 500 com o histórico já reescrito e as notas e posições antigas. Na
retentativa, nenhuma leitura estava em outro nível (``atualizadas == 0``): o recálculo
não rodava e a resposta dizia "Aplicar ao histórico não mudou nada".

Agora a correção do livro continua na trava da escola (4711) e é confirmada primeiro —
ela vale para as próximas leituras, um estado coerente por si. O retroativo (reescrever
o nível das leituras, a auditoria e o recálculo) é UMA transação sob a trava da
escola (4711 antes das escritas e do recálculo). Falha no recálculo desfaz o
retroativo inteiro, e a retentativa encontra as leituras ainda no nível velho e aplica
tudo. Dados fictícios.
"""
from datetime import datetime

from sqlalchemy import select

from app.models import Importacao, Leitura, Livro, LogAuditoria, Nota, SnapshotElefante
from app.services import scoring

API = "/api/v1"
LIDO_EM = datetime(2026, 9, 10, 10, 0)
CORPO = {"nivel_codigo": "Z", "aplicar_ao_historico": True,
         "motivo": "nível oficial é Z, não AA"}


def _notas(db, escola_id: int) -> dict:
    db.expire_all()
    return {n.aluno_id: (round(n.nota_elefante or 0, 3), n.posicao)
            for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()}


def _cenario(db, escola_completa) -> tuple[int, int]:
    """Três crianças, um livro cada (AA, M, H) e o mesmo retrato do Elefante: o nível
    do livro decide a ordem. O livro de AA é o que o Admin Global corrige para Z."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="api", qtd_alunos=3)
    db.add(imp)
    db.flush()
    corrigido = None
    for aluno, (titulo, nivel) in zip((ana, joao, sofia),
                                      (("Livro Inventado AA", "AA"), ("Livro Inventado M", "M"),
                                       ("Livro Inventado H", "H"))):
        livro = Livro(escola_id=escola.id, titulo=titulo, nivel_codigo=nivel)
        db.add(livro)
        db.flush()
        corrigido = corrigido or livro.id
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                       data=LIDO_EM, tempo_leitura_min=10, nivel_codigo=nivel))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=LIDO_EM, livros_unicos=1, tempo_leitura_min=10,
                                questoes_tentativas=0, questoes_acertos=0,
                                livros_por_nivel={nivel: 1}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola.id, corrigido


def _patch(cliente, url: str) -> int:
    try:
        return cliente.patch(url, json=CORPO).status_code
    except RuntimeError:
        return 500


def test_falha_no_recalculo_nao_deixa_historico_renivelado_com_notas_velhas(
        cliente_global, db, escola_completa, monkeypatch):
    escola_id, livro_id = _cenario(db, escola_completa)
    antes = _notas(db, escola_id)
    url = f"{API}/escolas/{escola_id}/livros/{livro_id}"

    real = scoring.recalcular_escola
    chamadas = {"n": 0}

    def _falha_uma_vez(*a, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("falha simulada no recálculo (queda de conexão)")
        return real(*a, **k)

    monkeypatch.setattr(scoring, "recalcular_escola", _falha_uma_vez)

    assert _patch(cliente_global, url) == 500
    db.expire_all()
    nivel_da_leitura = db.execute(select(Leitura.nivel_codigo).where(
        Leitura.livro_id == livro_id)).scalar_one()
    acoes = db.execute(select(LogAuditoria.acao).where(LogAuditoria.acao.in_(
        ["livro.atualizado", "livro.historico_renivelado"]))).scalars().all()
    # A correção do livro (vale para as próximas leituras) ficou; o retroativo, não:
    # leitura no nível velho, sem auditoria de histórico, notas como estavam.
    assert db.get(Livro, livro_id).nivel_codigo == "Z"
    assert (nivel_da_leitura, sorted(acoes)) == ("AA", ["livro.atualizado"]), (
        f"histórico renivelado ({nivel_da_leitura}) sem o recálculo das notas: {acoes}")
    assert _notas(db, escola_id) == antes

    # A retentativa aplica o retroativo inteiro: reescreve a leitura e recalcula.
    r = cliente_global.patch(url, json=CORPO)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["leituras_atualizadas"], corpo["historico_preservado"]) == (1, False), corpo
    assert "não mudou nada" not in corpo["aviso_correcao"]
    depois = _notas(db, escola_id)

    monkeypatch.setattr(scoring, "recalcular_escola", real)
    real(db, escola_id)
    verdade = _notas(db, escola_id)
    assert verdade != antes, "cenário inválido: o nível não mexe na nota"
    assert depois == verdade, "a retentativa deixou as notas velhas"


def test_retroativo_sem_falha_reescreve_audita_e_recalcula_na_mesma_resposta(
        cliente_global, db, escola_completa):
    escola_id, livro_id = _cenario(db, escola_completa)
    antes = _notas(db, escola_id)
    r = cliente_global.patch(f"{API}/escolas/{escola_id}/livros/{livro_id}", json=CORPO)
    assert r.status_code == 200, r.text
    assert r.json()["leituras_atualizadas"] == 1
    db.expire_all()
    assert db.execute(select(Leitura.nivel_codigo).where(
        Leitura.livro_id == livro_id)).scalar_one() == "Z"
    renivelado = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.historico_renivelado")).scalars().one()
    assert renivelado.detalhes["de"] == {"AA": 1}
    assert _notas(db, escola_id) != antes
