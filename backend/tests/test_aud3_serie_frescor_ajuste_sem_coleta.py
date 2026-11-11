"""REV3-SERIE-1 (resíduo de S_G_AJUSTE-2): o ajuste manual da criança que a coleta NÃO trouxe
não faz a escola com a coleta parada parecer em dia.

``frescor_ranking._datas_por_escola`` decidia a data do dado POR ALUNO (última coleta, ou o
ajuste de quem não tem coleta) e tomava o maior: numa escola integrada com a coleta parada há
20 dias, o suporte (Admin Global) digitar o número de uma criança sem coleta (conta nova, não
casada) virava "dados de hoje" da escola inteira — estado "parcial" em vez de "desatualizado",
sem o aviso "Este ranking pode não refletir a situação atual", e o cartaz/certificado
imprimindo "<hoje> (parte com dado de 22/10)". Agora, quando a escola tem coleta, é a última
COLETA dela que dá a data e o estado; o ajuste mais novo que ela vem à parte
(``ajuste_manual_mais_recente_em``). A escola só com ajuste manual (sem integração) continua
como antes. Dados fictícios; nada de rede.
"""
from datetime import date, datetime, time, timedelta

import pytest

from app.core.tempo import hoje_br
from app.models import Importacao, PlataformaCredencial, SnapshotElefante, SnapshotMatific
from app.services import frescor_ranking, relatorios
from tests._ano_letivo import no_ano_de_hoje

API = "/api/v1"
HOJE = date(2026, 11, 11)
COLETA = datetime(2026, 10, 22, 12, 0)      # 09h de Brasília, há 20 dias
AJUSTE = datetime(2026, 11, 11, 12, 0)      # hoje


def _importacao(db, escola_id, plataforma, tipo):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma=plataforma, tipo=tipo,
                     qtd_alunos=1)
    db.add(imp)
    db.flush()
    return imp.id


def _matific(db, escola_id, aluno_id, quando, tipo="api", atividades=50):
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id,
                           importacao_id=_importacao(db, escola_id, "matific", tipo),
                           data_referencia=quando, atividades=atividades,
                           estrelas=4 * atividades, pontuacao_media=4.0))
    db.commit()


def _elefante(db, escola_id, aluno_id, quando, tipo="api", livros=10):
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id,
                            importacao_id=_importacao(db, escola_id, "elefante", tipo),
                            data_referencia=quando, livros_unicos=livros,
                            tempo_leitura_min=10 * livros, livros_por_nivel={"AA": livros}))
    db.commit()


_RETRATO = {"matematica": _matific, "leitura": _elefante}


def _bloco(db, escola, dimensao, hoje=HOJE):
    return frescor_ranking.frescor_da_escola(db, escola, hoje)["dimensoes"][dimensao]


# --- o serviço, com datas fixas ---------------------------------------------------------

@pytest.mark.parametrize("dimensao", ["matematica", "leitura"])
def test_ajuste_da_crianca_sem_coleta_nao_renova_a_escola_com_coleta_parada(
        db, escola_completa, dimensao):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    retrato = _RETRATO[dimensao]
    for aluno in (joao, sofia):
        retrato(db, escola.id, aluno.id, COLETA)
    antes = frescor_ranking.frescor_da_escola(db, escola, HOJE)
    # A Ana não veio na coleta (conta nova, não casada): o suporte digita o número dela hoje.
    retrato(db, escola.id, ana.id, AJUSTE, tipo="manual")
    depois = frescor_ranking.frescor_da_escola(db, escola, HOJE)

    bloco = depois["dimensoes"][dimensao]
    assert bloco["estado"] == "desatualizado", \
        "o ajuste manual de uma criança sem coleta virou 'dado de hoje' da escola com a coleta parada"
    assert (bloco["dado_mais_recente_em"], bloco["dado_mais_antigo_em"],
            bloco["dias_desde_dado"]) == ("2026-10-22", "2026-10-22", 20)
    # A Ana tem dado (o digitado, de hoje): conta, e não entre os antigos.
    assert (bloco["alunos_com_dado"], bloco["alunos_com_dado_antigo"]) == (3, 2)
    # O ajuste vem à parte, sem mudar o estado nem a data.
    assert bloco["ajuste_manual_mais_recente_em"] == "2026-11-11"
    assert antes["dimensoes"][dimensao]["ajuste_manual_mais_recente_em"] is None
    # O cartaz e o certificado continuam imprimindo a data da coleta.
    rotulo = {"matematica": "Matemática", "leitura": "Leitura"}[dimensao]
    legenda = relatorios.legenda_data_dos_dados(depois, [dimensao])
    assert legenda == relatorios.legenda_data_dos_dados(antes, [dimensao])
    assert legenda == f"Dados das plataformas: {rotulo} de 22/10/2026 (mais de 7 dias)"


def test_coleta_em_dia_e_ajuste_da_crianca_sem_coleta_vem_a_parte(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    for aluno in (joao, sofia):
        _matific(db, escola.id, aluno.id, datetime(2026, 11, 8, 12, 0))
    _matific(db, escola.id, ana.id, AJUSTE, tipo="manual")
    bloco = _bloco(db, escola, "matematica")
    assert (bloco["estado"], bloco["dado_mais_recente_em"], bloco["dias_desde_dado"]) == \
        ("em_dia", "2026-11-08", 3)
    assert (bloco["alunos_com_dado"], bloco["alunos_com_dado_antigo"]) == (3, 0)
    assert bloco["ajuste_manual_mais_recente_em"] == "2026-11-11"


def test_ajuste_antigo_da_crianca_sem_coleta_deixa_a_escola_parcial_sem_ser_citado(
        db, escola_completa):
    """A coleta está em dia; a criança sem coleta só tem um ajuste de 20 dias atrás: o dado
    dela é antigo (parcial), e o ajuste, mais velho que a última coleta, não é "novidade"."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    for aluno in (joao, sofia):
        _elefante(db, escola.id, aluno.id, datetime(2026, 11, 9, 12, 0))
    _elefante(db, escola.id, ana.id, COLETA, tipo="manual")
    bloco = _bloco(db, escola, "leitura")
    assert (bloco["estado"], bloco["dado_mais_recente_em"], bloco["dado_mais_antigo_em"]) == \
        ("parcial", "2026-11-09", "2026-10-22")
    assert (bloco["alunos_com_dado"], bloco["alunos_com_dado_antigo"]) == (3, 1)
    assert bloco["ajuste_manual_mais_recente_em"] is None


def test_ajuste_mais_velho_que_a_ultima_coleta_da_escola_nao_e_citado(db, escola_completa):
    """O ajuste do suporte de 01/11 vale para a Ana (a coleta dela é de 22/10), mas a escola
    tem coleta de 09/11: o selo diz "dados de 09/11" e não cita um ajuste anterior a ela."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _matific(db, escola.id, ana.id, COLETA)
    _matific(db, escola.id, ana.id, datetime(2026, 11, 1, 12, 0), tipo="manual")
    for aluno in (joao, sofia):
        _matific(db, escola.id, aluno.id, datetime(2026, 11, 9, 12, 0))
    bloco = _bloco(db, escola, "matematica")
    assert (bloco["estado"], bloco["dado_mais_recente_em"], bloco["dado_mais_antigo_em"]) == \
        ("parcial", "2026-11-09", "2026-10-22")
    assert bloco["ajuste_manual_mais_recente_em"] is None


# --- pela rota: o suporte digita o número da criança que a coleta não trouxe ---------------

def _dia(dias_atras: int) -> datetime:
    """Meio da manhã de N dias atrás (dia de Brasília, igual ao ``hoje_br``)."""
    return datetime.combine(hoje_br() - timedelta(days=dias_atras), time(12, 0))


def _frescor(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/frescor")
    assert r.status_code == 200, r.text
    return r.json()["dimensoes"]


@no_ano_de_hoje
def test_rota_suporte_digita_crianca_sem_coleta_no_matific(
        relogio_no_ano_letivo, cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="matific",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    for aluno in (joao, sofia):
        _matific(db, escola.id, aluno.id, _dia(20))
    antes = _frescor(cliente, escola.id)["matematica"]
    # O coordenador recebe "fale com o suporte"; o Admin Global faz o ajuste.
    r_coord = cliente.put(f"{API}/escolas/{escola.id}/matific/{ana.id}",
                          json={"atividades": 30, "estrelas": 120, "motivo": "conta nova"})
    assert r_coord.status_code == 403, r_coord.text
    r = cliente_global.put(f"{API}/escolas/{escola.id}/matific/{ana.id}",
                           json={"atividades": 30, "estrelas": 120,
                                 "motivo": "suporte: a conta não veio na coleta"})
    assert r.status_code == 200, r.text
    depois = _frescor(cliente, escola.id)["matematica"]
    assert antes["estado"] == depois["estado"] == "desatualizado", depois
    assert depois["dado_mais_recente_em"] == antes["dado_mais_recente_em"] == \
        _dia(20).date().isoformat()
    assert (depois["dias_desde_dado"], depois["alunos_com_dado"],
            depois["alunos_com_dado_antigo"]) == (20, 3, 2)
    assert depois["ajuste_manual_mais_recente_em"] == hoje_br().isoformat()


def test_rota_suporte_digita_crianca_sem_coleta_no_elefante(
        cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    coleta = datetime.combine(hoje_br() - timedelta(days=20), time(12, 0))
    for aluno in (joao, sofia):
        _elefante(db, escola.id, aluno.id, coleta)
    r = cliente_global.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}",
                           json={"livros_unicos": 5, "tempo_leitura_min": 50,
                                 "questoes_tentativas": 0, "questoes_acertos": 0,
                                 "livros_por_nivel": {"AA": 5},
                                 "motivo": "suporte: a conta não veio na coleta"})
    assert r.status_code == 200, r.text
    bloco = _frescor(cliente, escola.id)["leitura"]
    assert bloco["estado"] == "desatualizado", bloco
    assert bloco["dado_mais_recente_em"] == frescor_ranking.dia_do_retrato(coleta).isoformat()
    assert (bloco["alunos_com_dado"], bloco["alunos_com_dado_antigo"]) == (3, 2)
    assert bloco["ajuste_manual_mais_recente_em"] == hoje_br().isoformat()
