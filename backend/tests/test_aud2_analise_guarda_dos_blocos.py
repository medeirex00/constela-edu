"""REV2-ANALISE-1 (revisão do G_GRUPO-2): o ano letivo da rede não mede de novo, a cada
pedido, os blocos do calendário que não mudaram.

A proteção por blocos (ed91ca24) mede, além do período, cada bloco dentro dele (no ano
letivo, a folga de janeiro e os bimestres que já começaram). Na rede fictícia de 28 escolas
(PG local, segunda chamada), ``/redes/{id}/analise/plataformas?periodo=ano_letivo`` passou
de ~2,4 s para ~5,6 s — e essa é a rota do Panorama, das Escolas, da ficha e de
Plataformas; o diagnóstico e a relação usam a mesma medição. Agora a medida de cada escola
em cada bloco é GUARDADA por pouco tempo, com uma chave que leva tudo o que a decide.

O que estes testes sustentam:

* TETO DE CUSTO (determinístico, sem relógio): o ano letivo pedido de novo mede só o
  período — o mesmo número de medidas e o mesmo número de partes na consulta das leituras
  de um bimestre sozinho; a ficha da escola, o diagnóstico e a relação reaproveitam os
  blocos da rede; e a resposta é a MESMA da medida do zero;
* a guarda nunca devolve marca velha quando o dado muda — e, na proteção por blocos, a
  marca velha é vazamento: uma coleta de janeiro chegada depois (a folga passa a ter UMA
  criança ativa), a fusão de duas fichas (os retratos passam de uma criança para outra, sem
  linha nova), a criança inativada, a importação marcada "sem questões" ou apagada, a troca
  de série da turma, do ano letivo, dos módulos ou do dia;
* bancos diferentes não se misturam (os mesmos ids com outros números).

Dados INVENTADOS. Nenhuma rede externa.
"""
from collections import Counter
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (Aluno, Importacao, Matricula, ModuloRede, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services.analise import plataformas as svc
from tests.test_analise_base import (ler, livros, nova_escola, nova_rede, retrato_elefante,
                                     retrato_matific, turma_com_alunos)
from tests.test_aud2_analise_janelas import API, _login

HOJE = date(2026, 10, 5)            # o 4º bimestre começa hoje: 5 blocos no ano letivo
# Por escola: o ano letivo e os 5 blocos (a folga de janeiro e os 4 bimestres).
MEDIDAS_DO_ANO = 6
COLETAS = ((datetime(2026, 1, 20, 3, 20), 0), (datetime(2026, 3, 2, 3, 20), 10),
           (datetime(2026, 6, 1, 3, 20), 20), (datetime(2026, 9, 1, 3, 20), 30),
           (datetime(2026, 10, 1, 3, 20), 40))


@pytest.fixture(autouse=True)
def _guarda_limpa(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    svc.limpar_cache_dos_blocos()
    yield
    svc.limpar_cache_dos_blocos()


def _escola(db, rede, nome, inep, n=6):
    escola = nova_escola(db, rede, nome, inep)
    alunos = turma_com_alunos(db, escola, "3º Ano", n)
    for a in alunos:
        for quando, atividades in COLETAS:
            retrato_matific(db, escola, a, quando, atividades=atividades,
                            estrelas=3 * atividades)
        retrato_elefante(db, escola, a, datetime(2026, 3, 2, 3, 10), tentativas=10, acertos=5)
        retrato_elefante(db, escola, a, datetime(2026, 9, 28, 3, 10), tentativas=30, acertos=20)
    k_livros = livros(db, escola, 2, "K")
    for a in alunos:
        ler(db, escola, a, k_livros, datetime(2026, 5, 10, 14, 0))
    return escola, alunos


def _mundo(db):
    """Duas escolas iguais (6 crianças no 3º ano, todas ativas em todos os bimestres) e, na
    ALFA, uma ficha INATIVA (fora da coorte) com uma coleta de janeiro."""
    rede = nova_rede(db, nome="Rede Fictícia da Guarda", codigo="3599973", codmun="9973")
    alfa, alunos_alfa = _escola(db, rede, "EMEF Fictícia Alfa da Guarda", "35997301")
    beta, alunos_beta = _escola(db, rede, "EMEF Fictícia Beta da Guarda", "35997302")
    (sombra,) = turma_com_alunos(db, alfa, "3º Ano", 1, nome_turma="3º Ano Sombra")
    sombra.status = "inativo"
    retrato_matific(db, alfa, sombra, datetime(2026, 1, 25, 3, 20), atividades=4, estrelas=11)
    db.commit()
    return {"rede": rede, "alfa": alfa, "beta": beta, "alunos_alfa": alunos_alfa,
            "alunos_beta": alunos_beta, "sombra": sombra}


@pytest.fixture()
def medidas(monkeypatch):
    """Cada medida de escola feita (período ou bloco): (escola, início, fim da janela)."""
    feitas: list[tuple] = []
    original = svc._medir_escola

    def _espiao(prep, coorte, lidos, hoje):
        feitas.append((prep.contagem.escola.id, prep.janela.inicio, prep.janela.fim))
        return original(prep, coorte, lidos, hoje)
    monkeypatch.setattr(svc, "_medir_escola", _espiao)
    return feitas


def _ano(db, rede, **kw):
    return svc.plataformas_da_rede(db, rede, hoje=kw.pop("hoje", HOJE), **kw)


def _do_zero(db, rede, **kw):
    svc.limpar_cache_dos_blocos()
    return _ano(db, rede, **kw)


def _sql_das_leituras(db, funcao) -> str:
    vistos: list[str] = []

    def _anota(_c, _cur, sql, *_a):
        if "primeiras" in sql:
            vistos.append(sql)
    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", _anota)
    try:
        funcao()
    finally:
        event.remove(motor, "before_cursor_execute", _anota)
    assert len(vistos) == 1, len(vistos)
    return vistos[0].lower()


# --- Teto de custo ---------------------------------------------------------------------------

def test_ano_letivo_pedido_de_novo_mede_so_o_periodo(db, medidas):
    m = _mundo(db)
    frio = _ano(db, m["rede"])
    blocos_e_periodo = len(medidas)
    assert blocos_e_periodo == 2 * MEDIDAS_DO_ANO    # 2 escolas × (o ano + 5 blocos)
    medidas.clear()
    quente = _ano(db, m["rede"])
    assert quente == frio
    assert len(medidas) == 2, medidas                # só o ano letivo de cada escola
    medidas.clear()
    _ano(db, m["rede"], preset="bimestre_3")
    assert len(medidas) == 2                         # o mesmo custo de um bimestre sozinho
    # A consulta das leituras do ano letivo de novo tem as partes de UM período.
    sql_quente = _sql_das_leituras(db, lambda: _ano(db, m["rede"]))
    sql_bimestre = _sql_das_leituras(db, lambda: _ano(db, m["rede"], preset="bimestre_3"))
    assert sql_quente.count("union all") == sql_bimestre.count("union all")


def test_serie_ficha_diagnostico_e_relacao_reaproveitam_os_blocos(db, escola_completa,
                                                                  medidas):
    m = _mundo(db)
    sec = _login(db, "sec.guarda@ficticio.local", cargo="coordenador", rede_id=m["rede"].id)
    base = f"{API}/redes/{m['rede'].id}/analise"
    r = sec.get(f"{base}/plataformas", params={"periodo": "ano_letivo"})
    assert r.status_code == 200, r.text
    pedidos = ((f"{base}/plataformas", {"periodo": "ano_letivo", "serie": 3}, 2),
               (f"{API}/escolas/{m['alfa'].id}/analise", {"periodo": "ano_letivo"}, 1),
               (f"{base}/diagnostico", {"periodo": "ano_letivo"}, 2),
               (f"{base}/relacao", {"indicador": "saresp", "periodo": "ano_letivo"}, None))
    quentes = []
    for url, params, esperadas in pedidos:
        medidas.clear()
        quente = sec.get(url, params=params)
        assert quente.status_code == 200, (url, quente.text)
        anos = {(i, f) for _e, i, f in medidas}
        assert len(anos) <= 1, (url, medidas)        # nenhum bloco medido de novo
        if esperadas is not None:
            assert len(medidas) == esperadas, (url, medidas)
        quentes.append(quente)
    # A mesma resposta da medida do zero (a guarda limpa antes de cada uma).
    for (url, params, _), quente in zip(pedidos, quentes):
        svc.limpar_cache_dos_blocos()
        frio = sec.get(url, params=params)
        sem_hora = [{k: v for k, v in x.json().items() if k != "gerado_em"}
                    for x in (quente, frio)]
        assert sem_hora[0] == sem_hora[1], url


# --- A guarda não devolve marca velha ----------------------------------------------------------

def _nova_importacao(db, escola, plataforma="matific"):
    imp = Importacao(escola_id=escola.id, usuario_id=None, plataforma=plataforma, tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def test_coleta_de_janeiro_chegada_depois_esconde_o_ano(db):
    """Uma criança passa a ter atividade na folga de janeiro (uma coleta antiga importada
    depois): a folga a esconde (1 criança), e o ano letivo tem de esconder também."""
    m = _mundo(db)
    antes = _ano(db, m["rede"])["rede"]["matific"]
    assert antes["estrelas_por_aluno"] is not None, antes
    alvo = m["alunos_alfa"][0]
    db.add(SnapshotMatific(escola_id=m["alfa"].id, aluno_id=alvo.id,
                           importacao_id=_nova_importacao(db, m["alfa"]).id,
                           data_referencia=datetime(2026, 1, 28, 3, 20), atividades=3,
                           estrelas=9, pontuacao_media=0.0))
    db.commit()
    depois = _ano(db, m["rede"])
    assert depois == _do_zero(db, m["rede"])
    for bloco in (depois["rede"]["matific"], depois["escolas"][0]["matific"]):
        assert bloco["estrelas_por_aluno"] is None, bloco
        assert "estrelas_por_aluno" in bloco["metricas_protegidas"], bloco


def test_fusao_de_fichas_sem_linha_nova_esconde_o_ano(db):
    """Os retratos da ficha inativa passam para uma criança da coorte (a fusão): nenhuma
    linha entra nem sai, e o maior id não muda — mas a folga de janeiro passa a ter UMA
    criança ativa."""
    m = _mundo(db)
    assert _ano(db, m["rede"])["rede"]["matific"]["estrelas_por_aluno"] is not None
    db.execute(update(SnapshotMatific).where(SnapshotMatific.aluno_id == m["sombra"].id)
               .values(aluno_id=m["alunos_alfa"][1].id))
    db.commit()
    depois = _ano(db, m["rede"])
    assert depois == _do_zero(db, m["rede"])
    assert depois["rede"]["matific"]["estrelas_por_aluno"] is None, depois["rede"]["matific"]


def test_crianca_inativada_muda_a_coorte_e_o_bloco(db):
    """Com uma criança a menos no 3º bimestre (4 ativas), o bimestre esconde as estrelas e o
    ano letivo tem de esconder também."""
    m = _mundo(db)
    rede = m["rede"]
    # Na BETA, só 5 das 6 crianças fazem atividade no 3º bimestre.
    quieta = m["alunos_beta"][5]
    db.execute(update(SnapshotMatific).where(SnapshotMatific.aluno_id == quieta.id,
                                             SnapshotMatific.data_referencia >= datetime(2026, 9, 1))
               .values(atividades=20, estrelas=60))
    db.commit()
    svc.limpar_cache_dos_blocos()
    assert _ano(db, rede)["escolas"][1]["matific"]["estrelas_por_aluno"] is not None
    db.get(Aluno, m["alunos_beta"][0].id).status = "inativo"
    db.commit()
    depois = _ano(db, rede)
    assert depois == _do_zero(db, rede)
    beta = depois["escolas"][1]
    assert beta["matific"]["estrelas_por_aluno"] is None, beta["matific"]
    assert "estrelas_por_aluno" in beta["matific"]["metricas_protegidas"]


def _blocos_medidos_de_novo(db, rede, medidas, mudar) -> set[int]:
    """Muda o banco e diz de que escolas os BLOCOS foram medidos de novo no pedido seguinte
    — e confere que a resposta é a da medida do zero."""
    _ano(db, rede)
    mudar()
    db.commit()
    medidas.clear()
    depois = _ano(db, rede)
    # Cada escola mede o período uma vez; a que mede mais vezes mediu os blocos de novo.
    vezes = Counter(e for e, _i, _f in medidas)
    assert depois == _do_zero(db, rede)
    return {e for e, n in vezes.items() if n > 1}


@pytest.mark.parametrize("vetor", ["coleta_nova", "importacao_sem_questoes", "importacao_apagada",
                                   "leitura_nova", "serie_da_turma", "ficha_inativada"])
def test_cada_mudanca_mede_de_novo_so_a_escola_dela(db, medidas, vetor):
    m = _mundo(db)
    alfa, alvo = m["alfa"], m["alunos_alfa"][2]

    def mudar():
        if vetor == "coleta_nova":
            db.add(SnapshotMatific(escola_id=alfa.id, aluno_id=alvo.id,
                                   importacao_id=_nova_importacao(db, alfa).id,
                                   data_referencia=datetime(2026, 4, 1, 3, 20), atividades=15,
                                   estrelas=45, pontuacao_media=0.0))
        elif vetor == "importacao_sem_questoes":
            imp = db.execute(select(Importacao).where(Importacao.escola_id == alfa.id,
                                                      Importacao.plataforma == "elefante")
                             .limit(1)).scalar_one()
            imp.status = IMPORTACAO_SEM_QUESTOES
        elif vetor == "importacao_apagada":
            imp_id = db.execute(select(SnapshotElefante.importacao_id).where(
                SnapshotElefante.aluno_id == alvo.id).limit(1)).scalar_one()
            db.execute(delete(SnapshotElefante).where(SnapshotElefante.importacao_id == imp_id))
            db.execute(delete(Importacao).where(Importacao.id == imp_id))
        elif vetor == "leitura_nova":
            ler(db, alfa, alvo, livros(db, alfa, 1, "M"), datetime(2026, 8, 10, 14, 0))
        elif vetor == "serie_da_turma":
            turma = db.execute(select(Turma).where(Turma.escola_id == alfa.id,
                                                   Turma.nome == "3º Ano A")).scalar_one()
            turma.ano_escolar = "4º Ano"
        else:
            db.get(Aluno, alvo.id).status = "inativo"
    assert _blocos_medidos_de_novo(db, m["rede"], medidas, mudar) == {alfa.id}


def test_crianca_que_muda_de_serie_entre_duas_series_visiveis(db, medidas):
    """A ALFA ganha um 4º ano com 6 crianças; uma criança do 3º passa para o 4º (5 e 7: as
    duas séries continuam visíveis, a lista de crianças da escola é a mesma) — só a série
    dela muda, e as células dos blocos têm de ser medidas de novo."""
    m = _mundo(db)
    alfa = m["alfa"]
    quarto = turma_com_alunos(db, alfa, "4º Ano", 6)
    for a in quarto:
        for quando, atividades in COLETAS:
            retrato_matific(db, alfa, a, quando, atividades=atividades, estrelas=atividades)
    db.commit()
    turma_4 = db.execute(select(Turma).where(Turma.escola_id == alfa.id,
                                             Turma.ano_escolar == "4º Ano")).scalar_one()
    muda = m["alunos_alfa"][0]

    def mudar():
        mat = db.execute(select(Matricula).where(Matricula.aluno_id == muda.id)).scalar_one()
        mat.turma_id = turma_4.id
    assert _blocos_medidos_de_novo(db, m["rede"], medidas, mudar) == {alfa.id}
    series = {c["serie"]: c["alunos"] for c in _ano(db, m["rede"])["escolas"][0]["series"]}
    assert series == {3: 5, 4: 7}, series


def test_modulos_e_dia_mudam_a_chave(db, medidas):
    m = _mundo(db)
    rede = m["rede"]
    _ano(db, rede)
    medidas.clear()
    _ano(db, rede, hoje=date(2026, 10, 6))           # outro dia: tudo medido de novo
    assert len(medidas) == 2 * MEDIDAS_DO_ANO, medidas
    db.add(ModuloRede(rede_id=rede.id, modulo="leitura", ativo=False))
    db.commit()
    medidas.clear()
    sem_leitura = _ano(db, rede)
    assert len(medidas) == 2 * MEDIDAS_DO_ANO, medidas
    assert sem_leitura == _do_zero(db, rede) and sem_leitura["rede"]["elefante"] is None


def test_guarda_vence_e_mede_de_novo(db, medidas, monkeypatch):
    m = _mundo(db)
    _ano(db, m["rede"])
    depois_da_validade = svc._relogio() + svc._GUARDA_DOS_BLOCOS_S + 1
    monkeypatch.setattr(svc, "_relogio", lambda: depois_da_validade)
    medidas.clear()
    _ano(db, m["rede"])
    assert len(medidas) == 2 * MEDIDAS_DO_ANO, medidas


def test_bancos_diferentes_nao_se_misturam(db):
    """Os mesmos ids, as mesmas linhas e os mesmos carimbos — só a coleta de janeiro de uma
    criança muda (0 × 5 atividades; o total do ano é o mesmo, então o resto da conta não
    acusa): cada banco tem a guarda dele."""
    m = _mundo(db)
    assert _ano(db, m["rede"])["rede"]["matific"]["estrelas_por_aluno"] is not None
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    Base.metadata.create_all(motor)
    outro = sessionmaker(bind=motor)()
    try:
        m2 = _mundo(outro)
        assert (m2["rede"].id, m2["alfa"].id, m2["alunos_alfa"][0].id) == (
            m["rede"].id, m["alfa"].id, m["alunos_alfa"][0].id)
        outro.execute(update(SnapshotMatific).where(
            SnapshotMatific.aluno_id == m2["alunos_alfa"][0].id,
            SnapshotMatific.data_referencia == datetime(2026, 1, 20, 3, 20))
            .values(atividades=5, estrelas=15))
        outro.commit()
        segundo = svc.plataformas_da_rede(outro, m2["rede"], hoje=HOJE)["rede"]["matific"]
        assert segundo["estrelas_por_aluno"] is None, segundo
    finally:
        outro.close()
        motor.dispose()


def test_cliente_da_rota_tambem_usa_a_guarda(db, escola_completa, medidas):
    """A rota da Secretaria (a mesma medida): o segundo pedido não mede os blocos."""
    m = _mundo(db)
    sec: TestClient = _login(db, "sec.guarda.rota@ficticio.local", cargo="coordenador",
                             rede_id=m["rede"].id)
    url = f"{API}/redes/{m['rede'].id}/analise/plataformas"
    assert sec.get(url, params={"periodo": "ano_letivo"}).status_code == 200
    medidas.clear()
    assert sec.get(url, params={"periodo": "ano_letivo"}).status_code == 200
    assert len(medidas) == 2, medidas
