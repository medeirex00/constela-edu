"""S_G_AJUSTE-2: o ajuste manual de UMA criança não faz a escola com a coleta parada parecer
em dia — nem no selo dos rankings, nem no cartaz e no certificado.

``frescor_ranking._datas_por_escola`` tomava a data do retrato ATUAL de cada aluno sem olhar
a origem: o ajuste manual (``Importacao.tipo == "manual"``, data = agora) virava "dado de
hoje" da escola. Com a coleta do Matific parada há 20 dias, corrigir o número de uma criança
mudava o selo de "dados de 22/10 (há 20 dias)" + "Dado com mais de 7 dias" para "dados de
hoje" + "Coleta parcial", e o cartaz passava a imprimir "Matemática de <hoje> (parte com dado
de 22/10)". Agora a data do dado de um aluno é a da última COLETA dele; o ajuste vem à parte
(``ajuste_manual_mais_recente_em``). Quem só tem ajuste manual (a escola sem integração, que
digita os números) continua com a data do ajuste. Dados fictícios; nada de rede.
"""
from datetime import date, datetime, time, timedelta

from app.core.tempo import hoje_br
from app.models import Importacao, PlataformaCredencial, SnapshotElefante, SnapshotMatific
from app.models.base import agora
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


def _frescor_de(db, escola, hoje=HOJE):
    return frescor_ranking.frescor_da_escola(db, escola, hoje)


# --- o serviço, com datas fixas ---------------------------------------------------------

def test_ajuste_de_uma_crianca_nao_renova_a_coleta_parada(db, escola_completa):
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    for aluno in (ana, *outros):
        _matific(db, escola.id, aluno.id, COLETA)
    antes = _frescor_de(db, escola)
    _matific(db, escola.id, ana.id, AJUSTE, tipo="manual", atividades=51)
    depois = _frescor_de(db, escola)

    bloco = depois["dimensoes"]["matematica"]
    assert bloco["estado"] == "desatualizado", \
        "um ajuste digitado para uma criança virou 'dado de hoje' da escola inteira"
    assert (bloco["dado_mais_recente_em"], bloco["dado_mais_antigo_em"]) == \
        ("2026-10-22", "2026-10-22")
    assert (bloco["dias_desde_dado"], bloco["alunos_com_dado"],
            bloco["alunos_com_dado_antigo"]) == (20, 3, 3)
    # O ajuste vem à parte, sem mudar o estado nem a data.
    assert bloco["ajuste_manual_mais_recente_em"] == "2026-11-11"
    assert antes["dimensoes"]["matematica"]["ajuste_manual_mais_recente_em"] is None
    # O cartaz e o certificado imprimem a data da coleta, como antes do ajuste.
    legenda = relatorios.legenda_data_dos_dados(depois, ["matematica"])
    assert legenda == relatorios.legenda_data_dos_dados(antes, ["matematica"])
    assert legenda == "Dados das plataformas: Matemática de 22/10/2026 (mais de 7 dias)"


def test_coleta_em_dia_continua_em_dia_e_o_ajuste_vem_a_parte(db, escola_completa):
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    recente = datetime(2026, 11, 8, 12, 0)
    for aluno in (ana, *outros):
        _elefante(db, escola.id, aluno.id, recente)
    _elefante(db, escola.id, ana.id, AJUSTE, tipo="manual", livros=9)
    bloco = _frescor_de(db, escola)["dimensoes"]["leitura"]
    assert (bloco["estado"], bloco["dado_mais_recente_em"], bloco["dias_desde_dado"]) == \
        ("em_dia", "2026-11-08", 3)
    assert bloco["ajuste_manual_mais_recente_em"] == "2026-11-11"


def test_ajuste_desmentido_pela_coleta_seguinte_nao_aparece(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _elefante(db, escola.id, ana.id, COLETA)
    _elefante(db, escola.id, ana.id, datetime(2026, 11, 1, 12, 0), tipo="manual")
    _elefante(db, escola.id, ana.id, datetime(2026, 11, 9, 12, 0))
    bloco = _frescor_de(db, escola)["dimensoes"]["leitura"]
    assert (bloco["estado"], bloco["dado_mais_recente_em"]) == ("em_dia", "2026-11-09")
    assert bloco["ajuste_manual_mais_recente_em"] is None


def test_escola_so_com_ajuste_manual_continua_como_antes(db, escola_completa):
    """Sem integração, a escola digita os números: o ajuste é o único dado e a data dele vale."""
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    for aluno in outros:
        _elefante(db, escola.id, aluno.id, COLETA, tipo="manual")
    _elefante(db, escola.id, ana.id, AJUSTE, tipo="manual")
    bloco = _frescor_de(db, escola)["dimensoes"]["leitura"]
    assert (bloco["estado"], bloco["dado_mais_recente_em"], bloco["dado_mais_antigo_em"]) == \
        ("parcial", "2026-11-11", "2026-10-22")
    assert (bloco["alunos_com_dado"], bloco["alunos_com_dado_antigo"]) == (3, 2)
    assert bloco["ajuste_manual_mais_recente_em"] is None


# --- pelas rotas: o ajuste do Admin Global (o "fale com o suporte") -------------------------

def _dia(dias_atras: int) -> datetime:
    """Meio da manhã de N dias atrás (dia de Brasília, igual ao ``hoje_br``)."""
    return datetime.combine(hoje_br() - timedelta(days=dias_atras), time(12, 0))


def _frescor(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/frescor")
    assert r.status_code == 200, r.text
    return r.json()


@no_ano_de_hoje
def test_rota_ajuste_matific_de_uma_crianca_nao_deixa_a_escola_em_dia(
        relogio_no_ano_letivo, cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    for aluno in (ana, *outros):
        _matific(db, escola.id, aluno.id, _dia(20), atividades=100 if aluno is ana else 50)
    antes = _frescor(cliente, escola.id)["dimensoes"]["matematica"]
    r = cliente_global.put(f"{API}/escolas/{escola.id}/matific/{ana.id}",
                           json={"atividades": 101, "estrelas": 404,
                                 "motivo": "acerto de um número"})
    assert r.status_code == 200, r.text
    depois = _frescor(cliente, escola.id)["dimensoes"]["matematica"]
    assert antes["estado"] == depois["estado"] == "desatualizado"
    assert depois["dado_mais_recente_em"] == antes["dado_mais_recente_em"] == \
        _dia(20).date().isoformat()
    assert (depois["dias_desde_dado"], depois["alunos_com_dado_antigo"]) == (20, 3)
    assert depois["ajuste_manual_mais_recente_em"] == hoje_br().isoformat()


def test_rota_ajuste_elefante_do_suporte_nao_deixa_a_escola_em_dia(
        cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    coleta = agora() - timedelta(days=20)
    for aluno in (ana, *outros):
        _elefante(db, escola.id, aluno.id, coleta)
    r = cliente_global.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}",
                           json={"livros_unicos": 5, "tempo_leitura_min": 50,
                                 "questoes_tentativas": 0, "questoes_acertos": 0,
                                 "livros_por_nivel": {"AA": 5},
                                 "motivo": "suporte: relatório contou em dobro"})
    assert r.status_code == 200, r.text
    bloco = _frescor(cliente, escola.id)["dimensoes"]["leitura"]
    assert bloco["estado"] == "desatualizado", bloco
    assert bloco["dado_mais_recente_em"] == frescor_ranking.dia_do_retrato(coleta).isoformat()
    assert bloco["alunos_com_dado_antigo"] == 3
    assert bloco["ajuste_manual_mais_recente_em"] == hoje_br().isoformat()
