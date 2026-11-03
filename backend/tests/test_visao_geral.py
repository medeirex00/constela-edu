"""GET /escolas/{id}/visao-geral — os indicadores da Visão Geral (identidade v2).

O que este arquivo trava:
* os números são os do Relatório por Período (paridade de livros, tempo e atividades);
* "ativo" no Matific é GANHO > 0 — ter retrato com ganho 0 não conta (o relatório
  conta, em ``alunos.com_atividade``; aqui não);
* a comparação é a MESMA quantidade de dias desde o início do período anterior, e só
  sai quando as duas janelas estão medidas (senão ``null``); na Leitura, os dias de
  fato cobertos pela coleta; no Matific, base semanas antes do início não é completa;
* sem coleta é ``null``, nunca 0 (Elefante não visto, Matific sem intervalo medido);
* Leitura com a coleta parada no meio do período sai declarada: ``cobertura``
  "parcial" e ``coletado_ate`` (a mesma régua que desliga a comparação);
* módulo fora do plano: ``contratado=false`` e sem números;
* professor recortado pelas turmas dele, Secretaria negada, outra escola negada;
* sem lista de alunos e sem auditoria por visualização.

Hoje fixo: quarta, 14/10/2026 (4º bimestre: 05/10 a 31/12). Nomes fictícios.
"""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Escola, EventoAluno, Importacao, Leitura, Livro,
                        LogAuditoria, Matricula, ModuloRede, Professor, Rede,
                        SnapshotElefante, SnapshotMatific, Turma, Usuario)
from app.services import relatorios_periodo as rp
from app.services import visao_geral as svc
from app.services.eventos import chave_evento

API = "/api/v1"
HOJE = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    from app.routers import visao_geral as rota
    monkeypatch.setattr(rota, "hoje_br", lambda: HOJE)


# ----------------------------------------------------------------- sementes
def _importacao(db, escola_id, plataforma):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma=plataforma,
                     tipo="seed", arquivo_original=None, qtd_alunos=0,
                     qtd_erros=0, tempo_ms=0, status="concluida")
    db.add(imp)
    db.flush()
    return imp


def _leitura(db, escola_id, aluno_id, titulo, quando, tempo):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id,
                   data=quando, tempo_leitura_min=tempo, nivel_codigo="D"))
    db.flush()
    return livro


def _evento(db, escola_id, aluno_id, livro, quando):
    db.add(EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=livro.titulo,
        livro_id=livro.id, tempo_segundos=300, nivel_codigo=livro.nivel_codigo,
        chave_natural=chave_evento("elefante", "leitura", aluno_id, livro.titulo,
                                   quando, "")))
    db.flush()


def _coleta_elefante(db, escola_id, aluno_id, quando):
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id,
                            importacao_id=_importacao(db, escola_id, "elefante").id,
                            data_referencia=quando, livros_unicos=0,
                            tempo_leitura_min=0, questoes_tentativas=0,
                            questoes_acertos=0, livros_por_nivel={}))
    db.flush()


def _matific(db, escola_id, aluno_id, quando, atividades, estrelas=None):
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id,
                           importacao_id=_importacao(db, escola_id, "matific").id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=atividades * 4 if estrelas is None else estrelas,
                           pontuacao_media=0.0))
    db.flush()


def _cenario(db, escola_completa, *, elefante=True, matific=True):
    """A (leu e fez Matific), B (leu só no 3º bimestre; Matific com ganho 0 agora),
    C (leu; nunca teve Matific)."""
    eid = escola_completa["escola"].id
    a, b, c = (x.id for x in escola_completa["alunos"])
    if elefante:
        _leitura(db, eid, a, "Livro Ficticio 1", datetime(2026, 10, 7, 10, 0), 12)
        _leitura(db, eid, c, "Livro Ficticio 2", datetime(2026, 10, 10, 15, 0), 8)
        _leitura(db, eid, b, "Livro Ficticio 3", datetime(2026, 7, 28, 10, 0), 5)
        _leitura(db, eid, b, "Livro Ficticio 4", datetime(2026, 8, 10, 10, 0), 9)
        # a coleta das 0h10 de 14/10 (03h10 UTC) mede até 13/10
        _coleta_elefante(db, eid, a, datetime(2026, 10, 14, 3, 10))
    if matific:
        for quando, va, vb in ((datetime(2026, 7, 23, 3, 10), 2, 1),
                               (datetime(2026, 8, 1, 3, 10), 6, 1),
                               (datetime(2026, 10, 4, 3, 10), 10, 7),
                               (datetime(2026, 10, 13, 3, 10), 15, 7)):
            _matific(db, eid, a, quando, va)
            _matific(db, eid, b, quando, vb)
    db.commit()
    return eid, a, b, c


def _get(cliente, eid, **params):
    return cliente.get(f"{API}/escolas/{eid}/visao-geral", params=params)


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


# ============================================================================
# O contrato e os números
# ============================================================================
def test_contrato_completo_do_bimestre_em_curso(cliente, db, escola_completa):
    eid, *_ = _cenario(db, escola_completa)
    r = _get(cliente, eid)                       # padrão: periodo=bimestre
    assert r.status_code == 200, r.text
    assert r.json() == {
        "periodo": {"chave": "bimestre", "rotulo": "4º bimestre (05/10 a 31/12)",
                    "inicio": "2026-10-05", "fim": "2026-12-31",
                    "dias_decorridos": 10, "dias_total": 88},
        "comparacao": {"rotulo": "mesmo ponto do 3º bimestre",
                       "inicio": "2026-07-24", "fim": "2026-08-02"},
        # A e C leram; só A ganhou no Matific (B tem retrato com ganho 0).
        "alunos": {"total": 3, "ativos": 2, "ativos_anterior": 2,
                   "ativos_leitura": 2, "ativos_matematica": 1},
        # a coleta das 0h10 de 14/10 mede até 13/10 = a véspera de hoje: completa
        "leitura": {"contratado": True, "livros": 2, "livros_anterior": 1,
                    "tempo_min": 20, "tempo_min_anterior": 5,
                    "cobertura": "completa", "coletado_ate": "2026-10-13"},
        "matematica": {"contratado": True, "atividades": 5, "atividades_anterior": 4,
                       "cobertura": "completa"},
        # a fonte mais atrasada (Matific, 13/10 03h10 UTC)
        "atualizado_em": "2026-10-13T03:10:00+00:00",
    }


def test_comparacao_e_a_mesma_quantidade_de_dias(cliente, db, escola_completa):
    eid, *_ = _cenario(db, escola_completa)
    corpo = _get(cliente, eid).json()
    ini = date.fromisoformat(corpo["comparacao"]["inicio"])
    fim = date.fromisoformat(corpo["comparacao"]["fim"])
    assert (fim - ini).days + 1 == corpo["periodo"]["dias_decorridos"] == 10
    # O livro de B em 10/08 é do 3º bimestre, mas depois do "mesmo ponto": não entra.
    assert corpo["leitura"]["livros_anterior"] == 1


def test_paridade_com_o_relatorio_por_periodo(db, escola_completa):
    """Mesma janela, mesmos livros, tempo e atividades — e o viés do relatório
    (ganho 0 contado como ativo) NÃO é copiado."""
    eid, *_ = _cenario(db, escola_completa)
    escola = escola_completa["escola"]
    rel = rp.gerar(db, eid, preset="bimestre", plataformas=("elefante", "matific"),
                   hoje=HOJE)
    vg = svc.visao_geral(db, escola, preset="bimestre",
                         modulos={"leitura", "matematica"}, turma_ids=None, hoje=HOJE)
    assert vg["leitura"]["livros"] == rel["elefante"]["livros_novos"] == 2
    assert vg["leitura"]["tempo_min"] == rel["elefante"]["tempo_min"] == 20
    assert vg["matematica"]["atividades"] == rel["matific"]["atividades"] == 5
    assert vg["alunos"]["total"] == rel["alunos"]["considerados"] == 3
    assert rel["alunos"]["com_atividade"] == 3      # o relatório conta B (ganho 0)
    assert vg["alunos"]["ativos"] == 2              # aqui, não


def test_ganho_zero_nao_conta_como_ativo(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    for aluno, antes, depois in ((a, 3, 3), (b, 4, 4)):   # retrato com ganho 0
        _matific(db, eid, aluno, datetime(2026, 10, 4, 3, 10), antes)
        _matific(db, eid, aluno, datetime(2026, 10, 13, 3, 10), depois)
    db.commit()
    corpo = _get(cliente, eid).json()
    assert corpo["matematica"]["atividades"] == 0
    assert corpo["matematica"]["cobertura"] == "completa"
    assert corpo["alunos"]["ativos_matematica"] == 0
    assert corpo["alunos"]["ativos"] == 0


def test_periodo_fechado_e_comparacao_so_com_as_mesmas_plataformas(cliente, db,
                                                                   escola_completa):
    """3º bimestre (fechado): comparado com os 73 primeiros dias do 2º. Lá o Matific
    não tem coleta → atividades_anterior nulo, e por isso ativos_anterior também (a
    comparação de ativos só vale com as mesmas plataformas medidas)."""
    eid, *_ = _cenario(db, escola_completa)
    corpo = _get(cliente, eid, periodo="bimestre_3").json()
    assert corpo["periodo"] == {"chave": "bimestre_3",
                                "rotulo": "3º bimestre (24/07 a 04/10)",
                                "inicio": "2026-07-24", "fim": "2026-10-04",
                                "dias_decorridos": 73, "dias_total": 73}
    assert corpo["comparacao"] == {"rotulo": "mesmo ponto do 2º bimestre",
                                   "inicio": "2026-04-23", "fim": "2026-07-04"}
    assert corpo["leitura"]["livros"] == 2 and corpo["leitura"]["tempo_min"] == 14
    assert corpo["leitura"]["livros_anterior"] == 0      # Elefante visto, ninguém leu
    # Período fechado, coletado além do fim (13/10 ≥ 03/10): completo.
    assert corpo["leitura"]["cobertura"] == "completa"
    assert corpo["matematica"]["atividades"] == 8 + 6
    assert corpo["matematica"]["atividades_anterior"] is None
    assert corpo["alunos"]["ativos"] == 2                # B (leitura+Matific) e A
    assert corpo["alunos"]["ativos_anterior"] is None


@pytest.mark.parametrize("periodo", ["bimestre_1", "ano_letivo", "semestre", "30dias",
                                     "mes_anterior", "bimestre_anterior"])
def test_sem_periodo_anterior_equivalente_a_comparacao_e_nula(cliente, db,
                                                              escola_completa, periodo):
    eid, *_ = _cenario(db, escola_completa)
    corpo = _get(cliente, eid, periodo=periodo).json()
    assert corpo["comparacao"] is None
    assert corpo["alunos"]["ativos_anterior"] is None
    assert corpo["leitura"]["livros_anterior"] is None
    assert corpo["leitura"]["tempo_min_anterior"] is None
    assert corpo["matematica"]["atividades_anterior"] is None


def test_primeiro_bimestre_nao_compara_com_o_ano_anterior(db, escola_completa):
    escola = escola_completa["escola"]
    vg = svc.visao_geral(db, escola, preset="bimestre", modulos={"leitura"},
                         turma_ids=None, hoje=date(2026, 3, 10))
    assert vg["periodo"]["inicio"] == "2026-02-02"
    assert vg["comparacao"] is None


def test_periodo_que_ainda_nao_comecou(db, escola_completa):
    escola = escola_completa["escola"]
    vg = svc.visao_geral(db, escola, preset="bimestre_4", modulos={"leitura"},
                         turma_ids=None, hoje=date(2026, 9, 1))
    assert vg["periodo"]["dias_decorridos"] == 0
    assert vg["comparacao"] is None
    assert vg["leitura"]["cobertura"] == "sem_dado"
    assert vg["leitura"]["coletado_ate"] is None


def test_mes_e_semana_comparam_com_o_anterior(db, escola_completa):
    escola = escola_completa["escola"]
    mes = svc.visao_geral(db, escola, preset="mes", modulos=set(), turma_ids=None,
                          hoje=HOJE)
    assert mes["comparacao"] == {"rotulo": "mesmo ponto do mês anterior",
                                 "inicio": "2026-09-01", "fim": "2026-09-14"}
    semana = svc.visao_geral(db, escola, preset="semana", modulos=set(),
                             turma_ids=None, hoje=HOJE)
    assert semana["periodo"]["inicio"] == "2026-10-12"
    assert semana["comparacao"] == {"rotulo": "mesmo ponto da semana anterior",
                                    "inicio": "2026-10-05", "fim": "2026-10-07"}


# ============================================================================
# Ausência não é zero
# ============================================================================
def test_matific_parado_e_cobertura_parcial(cliente, db, escola_completa):
    """A última coleta é de 06/10 com hoje em 14/10: número parcial, sem comparação."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _matific(db, eid, a, datetime(2026, 7, 23, 3, 10), 1)
    _matific(db, eid, a, datetime(2026, 8, 1, 3, 10), 3)
    _matific(db, eid, a, datetime(2026, 10, 4, 3, 10), 10)
    _matific(db, eid, a, datetime(2026, 10, 6, 3, 10), 12)
    db.commit()
    m = _get(cliente, eid).json()["matematica"]
    assert m == {"contratado": True, "atividades": 2, "atividades_anterior": None,
                 "cobertura": "parcial"}


def test_matific_que_parou_para_um_aluno_e_parcial(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _matific(db, eid, a, datetime(2026, 10, 4, 3, 10), 10)
    _matific(db, eid, a, datetime(2026, 10, 13, 3, 10), 12)
    _matific(db, eid, b, datetime(2026, 9, 20, 3, 10), 4)   # coletado antes, nada agora
    db.commit()
    assert _get(cliente, eid).json()["matematica"]["cobertura"] == "parcial"


def test_matific_sem_coleta_e_sem_dado(cliente, db, escola_completa):
    eid, *_ = _cenario(db, escola_completa, matific=False)
    corpo = _get(cliente, eid).json()
    assert corpo["matematica"] == {"contratado": True, "atividades": None,
                                   "atividades_anterior": None, "cobertura": "sem_dado"}
    assert corpo["alunos"]["ativos_matematica"] is None
    assert corpo["alunos"]["ativos"] == 2                   # só a leitura mede
    # As duas janelas medem a MESMA plataforma (só a leitura): a comparação vale.
    assert corpo["alunos"]["ativos_anterior"] == 1


def test_uma_coleta_so_nao_mede_nada(cliente, db, escola_completa):
    """Sem coleta antes do período, uma coleta dentro dele não tem com o que comparar:
    sem número (o ``sem_intervalo`` do relatório), nunca zero."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _matific(db, eid, a, datetime(2026, 10, 13, 3, 10), 40)
    db.commit()
    m = _get(cliente, eid).json()["matematica"]
    assert m["atividades"] is None and m["cobertura"] == "sem_dado"


def test_elefante_nunca_coletado_e_sem_dado(cliente, db, escola_completa):
    eid, *_ = _cenario(db, escola_completa, elefante=False)
    corpo = _get(cliente, eid).json()
    assert corpo["leitura"] == {"contratado": True, "livros": None,
                                "livros_anterior": None, "tempo_min": None,
                                "tempo_min_anterior": None,
                                "cobertura": "sem_dado", "coletado_ate": None}
    assert corpo["alunos"]["ativos_leitura"] is None
    assert corpo["alunos"]["ativos"] == 1                   # só o Matific (A)
    assert corpo["alunos"]["ativos_anterior"] == 1          # Matific nas duas janelas
    assert corpo["atualizado_em"] == "2026-10-13T03:10:00+00:00"


def test_elefante_parado_antes_do_periodo_e_sem_dado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _leitura(db, eid, a, "Livro Antigo Ficticio", datetime(2026, 9, 20, 10, 0), 7)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 1, 3, 10))
    db.commit()
    corpo = _get(cliente, eid).json()
    assert corpo["leitura"]["livros"] is None
    assert corpo["leitura"]["cobertura"] == "sem_dado"
    # A data da coleta sai mesmo sem número: a das 0h10 de 01/10 mede até 30/09.
    assert corpo["leitura"]["coletado_ate"] == "2026-09-30"
    # No 3º bimestre (já visto), a mesma fonte tem número — mas visto só até 30/09
    # de um período que vai até 04/10: parcial.
    b3 = _get(cliente, eid, periodo="bimestre_3").json()["leitura"]
    assert b3["livros"] == 1
    assert b3["cobertura"] == "parcial" and b3["coletado_ate"] == "2026-09-30"


def test_elefante_atrasado_nao_compara(cliente, db, escola_completa):
    """Coleta de 08/10 com hoje em 14/10: o período atual perdeu os últimos dias, o
    anterior sairia inteiro — a comparação seria injusta, então sai nula."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _leitura(db, eid, a, "Livro Ficticio Atual", datetime(2026, 10, 6, 10, 0), 4)
    _leitura(db, eid, b, "Livro Ficticio Antes", datetime(2026, 7, 25, 10, 0), 4)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 8, 3, 10))
    db.commit()
    leitura = _get(cliente, eid).json()["leitura"]
    assert leitura["livros"] == 1
    assert leitura["livros_anterior"] is None
    # E o número não passa pelo total do bimestre: declara até onde conta.
    assert leitura["cobertura"] == "parcial"
    assert leitura["coletado_ate"] == "2026-10-07"     # a coleta de 08/10 0h10


def test_leitura_parada_no_meio_do_bimestre_sai_parcial_com_o_matific_em_dia(
        cliente, db, escola_completa, monkeypatch):
    """O cenário da auditoria: hoje 30/10, o Elefante coletado pela última vez em 08/10
    e o Matific em dia. Antes, a Leitura saía com número e sem nenhum aviso (o Matific,
    ``completa``, também não avisava) e o cartão parecia o total do bimestre."""
    from app.routers import visao_geral as rota
    monkeypatch.setattr(rota, "hoje_br", lambda: date(2026, 10, 30))
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _leitura(db, eid, a, "Livro Ficticio Parado", datetime(2026, 10, 6, 10, 0), 4)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 8, 3, 10))
    for aluno, antes, depois in ((a, 10, 15), (b, 7, 9)):
        _matific(db, eid, aluno, datetime(2026, 10, 4, 3, 10), antes)
        _matific(db, eid, aluno, datetime(2026, 10, 30, 3, 10), depois)
    db.commit()
    r = _get(cliente, eid)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["leitura"] == {"contratado": True, "livros": 1, "livros_anterior": None,
                                "tempo_min": 4, "tempo_min_anterior": None,
                                "cobertura": "parcial", "coletado_ate": "2026-10-07"}
    assert corpo["matematica"]["cobertura"] == "completa"
    # "Alunos ativos" soma a Leitura até 07/10 com o Matific até hoje: a tela usa a
    # cobertura da Leitura para avisar também nesse cartão.
    assert corpo["alunos"]["ativos_leitura"] == 1
    assert corpo["alunos"]["ativos_matematica"] == 2

    # Coletado de novo até a véspera: completa, com a data nova.
    _coleta_elefante(db, eid, a, datetime(2026, 10, 30, 3, 10))
    db.commit()
    leitura = _get(cliente, eid).json()["leitura"]
    assert leitura["cobertura"] == "completa"
    assert leitura["coletado_ate"] == "2026-10-29"


def test_releitura_conta_como_aluno_ativo_mas_nao_como_livro(cliente, db,
                                                             escola_completa):
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    livro = _leitura(db, eid, a, "Livro Relido Ficticio", datetime(2026, 8, 1, 10, 0), 6)
    _evento(db, eid, a, livro, datetime(2026, 10, 9, 10, 0))
    _coleta_elefante(db, eid, a, datetime(2026, 10, 14, 3, 10))
    db.commit()
    corpo = _get(cliente, eid).json()
    assert corpo["leitura"]["livros"] == 0
    assert corpo["alunos"]["ativos_leitura"] == 1


# ============================================================================
# Módulos, permissões e o que NÃO sai
# ============================================================================
def test_modulo_fora_do_plano_sai_sem_numeros(cliente, db, escola_completa):
    eid, *_ = _cenario(db, escola_completa)
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE FICTICIA SO LEITURA")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    corpo = _get(cliente, eid).json()
    assert corpo["matematica"] == {"contratado": False, "atividades": None,
                                   "atividades_anterior": None, "cobertura": "sem_dado"}
    assert corpo["alunos"]["ativos_matematica"] is None
    assert corpo["alunos"]["ativos"] == 2 and corpo["alunos"]["ativos_anterior"] == 1
    # a data do dado também não olha a plataforma fora do plano
    assert corpo["atualizado_em"] == "2026-10-14T03:10:00+00:00"

    db.add(ModuloRede(rede_id=rede.id, modulo="leitura", ativo=False))
    db.commit()
    corpo = _get(cliente, eid).json()
    assert corpo["leitura"]["contratado"] is False and corpo["leitura"]["livros"] is None
    assert corpo["leitura"]["cobertura"] == "sem_dado"
    assert corpo["leitura"]["coletado_ate"] is None     # nem olha a fonte fora do plano
    assert corpo["alunos"] == {"total": 3, "ativos": None, "ativos_anterior": None,
                               "ativos_leitura": None, "ativos_matematica": None}
    assert corpo["atualizado_em"] is None


def _professor(db, escola, turma, email):
    prof = Professor(escola_id=escola.id, nome="Prof Ficticio", email=email)
    db.add(prof)
    db.flush()
    turma.professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Prof Ficticio", email=email,
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()


def test_professor_ve_so_as_turmas_dele(db, escola_completa):
    eid, *_ = _cenario(db, escola_completa)
    escola = escola_completa["escola"]
    outra = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(outra)
    db.flush()
    d = Aluno(escola_id=eid, nome="Crianca Ficticia da Outra Turma")
    db.add(d)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=d.id, turma_id=outra.id, ano_letivo=2026))
    _leitura(db, eid, d.id, "Livro Ficticio da Outra Turma",
             datetime(2026, 10, 8, 10, 0), 30)
    db.commit()
    _professor(db, escola, escola_completa["turma"], "prof.vg@teste.local")
    _professor(db, escola, outra, "prof2.vg@teste.local")

    meu = _get(_login("prof.vg@teste.local"), eid).json()
    assert meu["alunos"]["total"] == 3
    assert meu["leitura"]["livros"] == 2 and meu["leitura"]["tempo_min"] == 20

    assert meu["leitura"]["cobertura"] == "completa"

    dela = _get(_login("prof2.vg@teste.local"), eid).json()
    assert dela["alunos"]["total"] == 1
    assert dela["leitura"]["livros"] == 1 and dela["leitura"]["tempo_min"] == 30
    # A cobertura é a dos alunos DELA: nenhuma coleta, só a leitura de 08/10.
    assert dela["leitura"]["cobertura"] == "parcial"
    assert dela["leitura"]["coletado_ate"] == "2026-10-08"
    assert dela["matematica"]["atividades"] is None      # a turma dela não tem Matific


def test_secretaria_e_negada(db, escola_completa):
    eid, *_ = _cenario(db, escola_completa)
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE FICTICIA")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=eid, rede_id=rede.id, nome="Secretaria",
                   email="sec.vg@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    r = _get(_login("sec.vg@teste.local"), eid)
    assert r.status_code == 403
    assert "Secretaria" in r.json()["detail"]


def test_outra_escola_e_negada(cliente, db, escola_completa):
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    assert _get(cliente, outra.id).status_code == 403
    assert _get(cliente, 999_999).status_code == 404
    assert TestClient(app).get(
        f"{API}/escolas/{escola_completa['escola'].id}/visao-geral").status_code == 401


@pytest.mark.parametrize("periodo", ["tudo", "personalizado", "trimestre_7", "x" * 40])
def test_periodo_sem_as_duas_pontas_ou_inexistente_e_422(cliente, db, escola_completa,
                                                         periodo):
    r = _get(cliente, escola_completa["escola"].id, periodo=periodo)
    assert r.status_code == 422


def test_sem_lista_de_alunos_e_sem_auditoria(cliente, db, escola_completa):
    eid, *_ = _cenario(db, escola_completa)
    antes = db.execute(select(func.count()).select_from(LogAuditoria)).scalar()
    r = _get(cliente, eid)
    assert r.status_code == 200
    depois = db.execute(select(func.count()).select_from(LogAuditoria)).scalar()
    assert depois == antes, "visualização não grava auditoria"
    for aluno in escola_completa["alunos"]:
        assert aluno.nome not in r.text
    assert "aluno_id" not in r.text and "por_aluno" not in r.text


# ============================================================================
# Comparação e cobertura honestas (revisão da identidade v2)
# ============================================================================
def test_comparacao_da_leitura_mede_os_dias_cobertos_pela_coleta(db, escola_completa):
    """A coleta das 0h10 mede o dia ANTERIOR: com hoje em 06/10, o 4º bimestre só foi
    visto em 05/10 (1 dia). Comparar com os 2 primeiros dias do 3º bimestre dava
    1 × 2 (▼50%) no mesmo ritmo de 1 livro por dia; em 31/10, 26 × 27."""
    escola = escola_completa["escola"]
    eid = escola.id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    for k in range(27):                       # 24/07 a 19/08: 1 livro por dia
        _leitura(db, eid, a, f"Livro Ficticio 3B {k}",
                 datetime(2026, 7, 24, 10, 0) + timedelta(days=k), 10)
    # B só releu, no 2º dia do 3º bimestre: ativo na faixa de 2 dias, fora da de 1.
    relido = _leitura(db, eid, b, "Livro Ficticio Relido 1B",
                      datetime(2026, 3, 10, 10, 0), 5)
    _evento(db, eid, b, relido, datetime(2026, 7, 25, 10, 0))
    _leitura(db, eid, a, "Livro Ficticio 4B 0", datetime(2026, 10, 5, 10, 0), 10)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 6, 3, 10))   # mede até 05/10
    db.commit()
    vg = svc.visao_geral(db, escola, preset="bimestre", modulos={"leitura"},
                         turma_ids=None, hoje=date(2026, 10, 6))
    assert vg["periodo"]["dias_decorridos"] == 2
    assert vg["leitura"]["livros"] == 1 and vg["leitura"]["livros_anterior"] == 1
    assert vg["leitura"]["tempo_min"] == 10 and vg["leitura"]["tempo_min_anterior"] == 10
    assert vg["alunos"]["ativos"] == 1 and vg["alunos"]["ativos_anterior"] == 1
    # O campo "comparacao" continua o geral (os dias decorridos), sem campo novo.
    assert vg["comparacao"]["inicio"] == "2026-07-24"
    assert vg["comparacao"]["fim"] == "2026-07-25"

    for k in range(1, 26):                    # 06/10 a 30/10
        _leitura(db, eid, a, f"Livro Ficticio 4B {k}",
                 datetime(2026, 10, 5, 10, 0) + timedelta(days=k), 10)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 31, 3, 10))  # mede até 30/10
    db.commit()
    vg = svc.visao_geral(db, escola, preset="bimestre", modulos={"leitura"},
                         turma_ids=None, hoje=date(2026, 10, 31))
    assert vg["periodo"]["dias_decorridos"] == 27
    assert vg["leitura"]["livros"] == 26 and vg["leitura"]["livros_anterior"] == 26
    assert vg["leitura"]["tempo_min"] == vg["leitura"]["tempo_min_anterior"] == 260
    assert vg["alunos"]["ativos"] == 1 and vg["alunos"]["ativos_anterior"] == 2


def test_base_do_matific_semanas_antes_do_inicio_nao_e_completa(cliente, db,
                                                                escola_completa):
    """Retratos de 20/09 (10) e 13/10 (30): a regra oficial mede desde 20/09, então o
    ganho inclui duas semanas do 3º bimestre. O número é o do relatório (que declara
    ``regra_oficial``); aqui a cobertura não pode sair ``completa`` — e por isso a
    comparação também não sai."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _matific(db, eid, a, datetime(2026, 9, 20, 3, 10), 10)
    _matific(db, eid, a, datetime(2026, 10, 13, 3, 10), 30)
    db.commit()
    m = _get(cliente, eid).json()["matematica"]
    assert m["atividades"] == 20 and m["cobertura"] == "parcial"
    rel = rp.gerar(db, eid, preset="bimestre", plataformas=("matific",), hoje=HOJE)
    assert rel["matific"]["atividades"] == 20
    assert rel["matific"]["cobertura"]["status"] == "regra_oficial"

    # Mesmo com o "mesmo ponto do 3º bimestre" medido (23/07 → 01/08), sem comparação.
    _matific(db, eid, a, datetime(2026, 7, 23, 3, 10), 2)
    _matific(db, eid, a, datetime(2026, 8, 1, 3, 10), 6)
    db.commit()
    m = _get(cliente, eid).json()["matematica"]
    assert m == {"contratado": True, "atividades": 20, "atividades_anterior": None,
                 "cobertura": "parcial"}


def test_base_do_matific_na_vespera_do_inicio_segue_completa(cliente, db,
                                                             escola_completa):
    """A tolerância da borda: a coleta de 04/10 00h10 (mede até 03/10) ainda é a base
    do 4º bimestre; a de 03/10 00h10 (mede até 02/10) já é antiga demais."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _matific(db, eid, a, datetime(2026, 10, 4, 3, 10), 10)
    _matific(db, eid, a, datetime(2026, 10, 13, 3, 10), 15)
    db.commit()
    assert _get(cliente, eid).json()["matematica"]["cobertura"] == "completa"
    _matific(db, eid, b, datetime(2026, 10, 3, 3, 10), 1)
    _matific(db, eid, b, datetime(2026, 10, 13, 3, 10), 2)
    db.commit()
    m = _get(cliente, eid).json()["matematica"]
    assert m["atividades"] == 6 and m["cobertura"] == "parcial"
