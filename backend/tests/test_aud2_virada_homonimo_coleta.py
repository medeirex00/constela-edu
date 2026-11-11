"""G_AJUSTE-3 — a coleta do Elefante não recria a duplicata homônima PROVADA.

O catálogo oficial tem dois títulos homônimos ("Cadê?" B/BB e "Chapeuzinho
Vermelho" I/K). Nas escolas com a linha ``legado`` antiga, a leitura de uma das
obras ficou nessa linha. A coleta seguinte traz a MESMA leitura (mesmo segundo,
mesmo tempo) e a resolve para a linha ``fonte`` do outro nível: como a
deduplicação de releitura olha só o ``livro_id``, ela era gravada de novo — dois
livros, o dobro de minutos e de pontos para a criança.

A regra que separa a duplicata do caso legítimo é a do serviço de saneamento
(``livros_homonimos_saneamento``): mesmo título homônimo do catálogo, uma linha
``legado`` e uma ``fonte``, instante idêntico ao segundo e o mesmo tempo. A
importação passa a usar ESSA regra (a mesma função) e trata o par como "já
constava", com aviso e auditoria. Instantes ou tempos diferentes continuam
sendo duas leituras (a criança leu as duas obras).

Dados fictícios. A "coleta" é o POST /importacoes/confirmar do relatório
individual do Elefante — o mesmo núcleo que a sincronização usa.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import EventoAluno, Leitura, Livro, LogAuditoria
from app.services import livros_homonimos_saneamento as san
from app.services.eventos import chave_evento

API = "/api/v1"
INSTANTE = datetime(2026, 3, 30, 20, 50, 43)
MOTIVO = "conferência do teste de regressão"
ACAO = "leitura.duplicata_homonima_evitada"

# (título, (id, nível) da obra que está na linha legado, (id, nível) da outra obra)
CADE = ("Cadê?", (4799, "BB"), (2356, "B"))
CHAPEU = ("Chapeuzinho Vermelho", (2304, "I"), (5539, "K"))


def _livro(db, escola_id, titulo, nivel, origem, elefante_id):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel,
                  nivel_fonte=nivel, origem_nivel=origem, elefante_id=elefante_id)
    db.add(livro)
    db.flush()
    return livro


def _leitura(db, escola_id, aluno_id, livro, quando=INSTANTE, tempo=5):
    db.add(Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id,
                   data=quando, tempo_leitura_min=tempo,
                   nivel_codigo=livro.nivel_codigo))
    db.add(EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=livro.titulo,
        livro_id=livro.id, tempo_segundos=tempo * 60,
        nivel_codigo=livro.nivel_codigo,
        chave_natural=chave_evento("elefante", "leitura", aluno_id, livro.titulo,
                                   quando)))
    db.flush()


def _linha(titulo, nivel, quando, tempo, **extra):
    return {"livro": titulo, "nivel": nivel, "data": quando.isoformat(),
            "tempo_livro_min": tempo, **extra}


def _coleta(cliente, escola_id, aluno, *dados):
    r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": d}
                   for d in dados]})
    assert r.status_code == 200, r.text
    return r.json()


def _leituras_de(db, aluno_id):
    db.expire_all()
    return [(l.livro_id, l.data.isoformat(), l.tempo_leitura_min) for l in db.execute(
        select(Leitura).where(Leitura.aluno_id == aluno_id).order_by(Leitura.id)
    ).scalars()]


def _cena(db, escola_completa, titulo_def=CADE, *, eid_legado=True, fonte=False):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    titulo, (eid_l, nivel_l), (eid_f, nivel_f) = titulo_def
    legado = _livro(db, escola.id, titulo, nivel_l, "legado",
                    eid_l if eid_legado else None)
    if fonte:
        _livro(db, escola.id, titulo, nivel_f, "fonte", eid_f)
    _leitura(db, escola.id, ana.id, legado, INSTANTE, 5)
    db.commit()
    return escola, ana, legado


def _avisos_homonimos(res):
    return [a for a in res.get("avisos", []) if "mesmo título" in a]


# ------------------------------------------------------------------ o defeito
def test_coleta_com_id_oficial_nao_grava_de_novo_a_leitura_do_legado(
        db, escola_completa, cliente):
    """A sonda do auditor: a coleta traz o id oficial certo (2356, nível B)."""
    escola, ana, _ = _cena(db, escola_completa)
    antes = _leituras_de(db, ana.id)

    res = _coleta(cliente, escola.id, ana,
                  _linha("Cadê?", "B", INSTANTE, 5, elefante_id=2356))

    assert _leituras_de(db, ana.id) == antes, \
        "a coleta gravou a MESMA leitura (mesmo segundo e tempo) uma segunda vez"
    avisos = _avisos_homonimos(res)
    assert len(avisos) == 1 and "Cadê?" in avisos[0] and ana.nome in avisos[0], \
        res.get("avisos")
    plano = san.dry_run(db, [escola.id], MOTIVO)
    assert plano["total_remocoes"] == 0, plano["classes"]


@pytest.mark.parametrize("titulo_def", [CADE, CHAPEU], ids=["cade", "chapeuzinho"])
@pytest.mark.parametrize("eid_legado", [True, False], ids=["legado_com_id", "legado_sem_id"])
@pytest.mark.parametrize("fonte", [True, False], ids=["fonte_existe", "fonte_nova"])
def test_coleta_sem_id_do_livro_nao_recria_o_par(
        db, escola_completa, cliente, titulo_def, eid_legado, fonte):
    """O caminho real: a API do Elefante não manda o id do livro — só título e
    nível. A linha cai no livro ``fonte`` do outro nível (novo ou existente)."""
    escola, ana, _ = _cena(db, escola_completa, titulo_def,
                           eid_legado=eid_legado, fonte=fonte)
    titulo, _, (_, nivel_outra) = titulo_def
    antes = _leituras_de(db, ana.id)

    res = _coleta(cliente, escola.id, ana, _linha(titulo, nivel_outra, INSTANTE, 5))

    assert _leituras_de(db, ana.id) == antes
    assert len(_avisos_homonimos(res)) == 1, res.get("avisos")


def test_par_ao_contrario_tambem_ja_constava(db, escola_completa, cliente):
    """A leitura está na linha ``fonte`` e a coleta a resolve para a ``legado``:
    é o mesmo par provado (o saneamento tiraria a linha nova, do legado)."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    fonte = _livro(db, escola.id, "Cadê?", "B", "fonte", 2356)
    _livro(db, escola.id, "Cadê?", "BB", "legado", 4799)
    _leitura(db, escola.id, ana.id, fonte, INSTANTE, 5)
    db.commit()
    antes = _leituras_de(db, ana.id)

    res = _coleta(cliente, escola.id, ana, _linha("Cadê?", "BB", INSTANTE, 5))

    assert _leituras_de(db, ana.id) == antes
    assert len(_avisos_homonimos(res)) == 1, res.get("avisos")


def test_releitura_listada_antes_da_leitura_provada_nao_entra(
        db, escola_completa, cliente):
    """O relatório pode listar primeiro a releitura (outro dia) e depois a
    leitura que já está no legado. A obra é a mesma: nada entra no ``fonte``."""
    escola, ana, _ = _cena(db, escola_completa)
    antes = _leituras_de(db, ana.id)

    res = _coleta(cliente, escola.id, ana,
                  _linha("Cadê?", "B", INSTANTE + timedelta(days=2), 7),
                  _linha("Cadê?", "B", INSTANTE, 5))

    assert _leituras_de(db, ana.id) == antes
    assert len(_avisos_homonimos(res)) == 1, res.get("avisos")


def test_auditoria_registra_o_par_evitado_sem_nome(db, escola_completa, cliente):
    escola, ana, legado = _cena(db, escola_completa)

    _coleta(cliente, escola.id, ana, _linha("Cadê?", "B", INSTANTE, 5))

    logs = list(db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == ACAO, LogAuditoria.escola_id == escola.id)).scalars())
    assert len(logs) == 1
    detalhes = logs[0].detalhes
    assert detalhes["qtd"] == 1
    item = detalhes["itens"][0]
    assert item["aluno_id"] == ana.id
    assert item["livro_existente_id"] == legado.id
    assert item["livro_existente_origem"] == "legado"
    assert item["livro_da_coleta_elefante_id"] == 2356
    assert item["data"] == INSTANTE.isoformat() and item["tempo_min"] == 5
    assert ana.nome not in str(detalhes)


def test_coleta_repetida_continua_sem_duplicar(db, escola_completa, cliente):
    escola, ana, _ = _cena(db, escola_completa)
    antes = _leituras_de(db, ana.id)
    for _ in range(2):
        _coleta(cliente, escola.id, ana, _linha("Cadê?", "B", INSTANTE, 5))
    assert _leituras_de(db, ana.id) == antes


# ---------------------------------------------------- o caso legítimo continua
@pytest.mark.parametrize("quando,tempo", [
    (INSTANTE + timedelta(hours=1), 5),     # outro instante: leu as duas obras
    (INSTANTE + timedelta(seconds=30), 5),  # "provável" não é provado
    (INSTANTE, 6),                          # mesmo segundo, tempo diferente
    (INSTANTE, None),                       # sem tempo: não há como provar
], ids=["outra_hora", "30s", "outro_tempo", "sem_tempo"])
def test_sem_a_prova_as_duas_leituras_ficam(db, escola_completa, cliente,
                                            quando, tempo):
    escola, ana, _ = _cena(db, escola_completa)

    res = _coleta(cliente, escola.id, ana, _linha("Cadê?", "B", quando, tempo))

    assert len(_leituras_de(db, ana.id)) == 2
    assert _avisos_homonimos(res) == []


def test_duas_linhas_fonte_nao_sao_o_par_auditado(db, escola_completa, cliente):
    """Escola que nasceu reconciliada (as duas linhas ``fonte``): fora do padrão
    legado+fonte, como no saneamento — a leitura nova entra."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    b = _livro(db, escola.id, "Cadê?", "B", "fonte", 2356)
    _livro(db, escola.id, "Cadê?", "BB", "fonte", 4799)
    _leitura(db, escola.id, ana.id, b, INSTANTE, 5)
    db.commit()

    _coleta(cliente, escola.id, ana, _linha("Cadê?", "BB", INSTANTE, 5))

    assert len(_leituras_de(db, ana.id)) == 2


def test_aluno_diferente_no_mesmo_segundo_nao_e_par(db, escola_completa, cliente):
    escola, ana, _ = _cena(db, escola_completa)
    joao = escola_completa["alunos"][1]

    _coleta(cliente, escola.id, joao, _linha("Cadê?", "B", INSTANTE, 5))

    assert len(_leituras_de(db, joao.id)) == 1
    assert len(_leituras_de(db, ana.id)) == 1


# ------------------------------------------------- a regra é UMA, e pura
def test_regra_pura_e_a_mesma_do_saneamento():
    ambiguos = san.titulos_auditados()
    legado = san.LadoDoPar(livro_id=1, origem="legado", elefante_id=4799,
                           data=INSTANTE, tempo=5)
    fonte = san.LadoDoPar(livro_id=2, origem="fonte", elefante_id=2356,
                          data=INSTANTE, tempo=5)
    assert san.recusa_do_par("cade?", legado, fonte, ambiguos=ambiguos) == ""
    # livro ainda sem id (criado nesta coleta) também é "outro livro"
    novo = san.LadoDoPar(livro_id=None, origem="fonte", elefante_id=2356,
                         data=INSTANTE, tempo=5)
    assert san.recusa_do_par("cade?", legado, novo, ambiguos=ambiguos) == ""
    um_segundo = san.LadoDoPar(livro_id=2, origem="fonte", elefante_id=2356,
                               data=INSTANTE + timedelta(seconds=1), tempo=5)
    assert san.PROVAVEL in san.recusa_do_par("cade?", legado, um_segundo,
                                             ambiguos=ambiguos)
    assert "origem" in san.recusa_do_par(
        "cade?", san.LadoDoPar(1, "fonte", 4799, INSTANTE, 5), fonte,
        ambiguos=ambiguos)
    assert "homônimos" in san.recusa_do_par("o menino", legado, fonte,
                                            ambiguos=ambiguos)
    assert "elefante_id" in san.recusa_do_par(
        "cade?", legado, san.LadoDoPar(2, "fonte", 9999, INSTANTE, 5),
        ambiguos=ambiguos)
    assert "MESMO livro" in san.recusa_do_par(
        "cade?", legado, san.LadoDoPar(1, "fonte", 2356, INSTANTE, 5),
        ambiguos=ambiguos)
