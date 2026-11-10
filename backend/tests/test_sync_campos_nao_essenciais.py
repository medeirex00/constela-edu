"""S9 (parcial na auditoria): campo NÃO essencial do Elefante renomeado na API.

``CAMPOS_ESSENCIAIS_SYNC`` protegia só os campos-título (livros): com
``responses``, ``approvedResponses`` ou ``totalReadTime`` renomeados, a execução
saía 'concluida', sem alerta, e o retrato de hoje repetia tempo e questões de antes
— as Questões do período, que medem a diferença entre retratos, liam "0 no
período" com cobertura completa.

Comportamento escolhido (visível e não destrutivo):
* os livros entram como sempre (nada é zerado nem recusado);
* a execução termina 'parcial' (com dado aplicado) ou 'sem_atualizacao' (sem),
  motivo ``campos_nao_atualizados``, com o alerta crítico 'parser_incompativel'
  dizendo o que não veio; não conta como "em dia" nem como verificação;
* quem não mudou não ganha retrato repetido com a data de hoje: a última medida de
  tempo e questões continua a de antes, e o relatório declara a cobertura.

Valor NULO explícito (o aluno sem dado) não é campo sumido: segue como antes.
Dados FICTÍCIOS, sem rede.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.plataformas import SnapshotElefante
from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import service
from tests._sync_nucleo_fakes import (
    NavElefante,
    aluno_el,
    alertas_abertos,
    credencial,
    instalar,
    livro,
    rodar,
    snap_atual,
)

CID = 733001
NAO_ESSENCIAIS = ("totalReadTime", "responses", "approvedResponses")


def _origem(a, b, livros_a=1):
    return {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9300001, a.nome, [livro(f"Livro Ficticio A{i}") for i in range(livros_a)],
                 tempo=12000, resp=30, ok=25),
        aluno_el(9300002, b.nome, [livro("Livro Ficticio B1")], tempo=6000, resp=10, ok=8)]}}


def _sem(nav, chaves, *, nulo=False, livros_de=None):
    """A resposta do relatório de turma perde ``chaves`` (ou as manda nulas)."""
    original = nav.avaliar

    async def avaliar(expressao):
        res = await original(expressao)
        if isinstance(res, dict) and isinstance(res.get("body"), dict) \
                and "students" in res["body"]:
            for s in res["body"]["students"]:
                for chave in chaves:
                    if nulo:
                        s[chave] = None
                    else:
                        s.pop(chave, None)
                if livros_de and s["studentId"] in livros_de:
                    s["totalBooksRead"] = livros_de[s["studentId"]]
        return res
    nav.avaliar = avaliar


def _coleta_de_dois_dias_atras(db):
    """A 1ª coleta passa a ser de dois dias atrás: a de hoje não atualiza o retrato
    do mesmo dia no lugar — grava (ou não) um retrato novo."""
    for snap in db.execute(select(SnapshotElefante)).scalars():
        snap.data_referencia = snap.data_referencia - timedelta(days=2)
    db.commit()


MOTIVO = "campos_nao_atualizados"


def _retratos(db, aluno_id):
    return db.scalar(select(func.count()).select_from(SnapshotElefante).where(
        SnapshotElefante.aluno_id == aluno_id))


def _alerta(db, eid):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.tipo == "parser_incompativel",
        SincronizacaoAlerta.resolvido.is_(False))).scalars().one()


def test_tempo_e_questoes_renomeados_com_livro_novo_sai_parcial_com_alerta(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)
    retratos_b = _retratos(db, b.id)

    _sem(nav, NAO_ESSENCIAIS, livros_de={9300001: 7})
    ex, _ = rodar(db, eid, "elefante")

    assert ex.status == "parcial"                       # nunca 'concluida' calada
    assert ex.motivo == MOTIVO
    alerta = _alerta(db, eid)
    assert alerta.severidade == "critico"
    assert "questões respondidas" in alerta.mensagem and "tempo de leitura" in alerta.mensagem
    assert "coleta_parcial" in alertas_abertos(db, eid, "elefante")
    # Não destrutivo: os livros novos de A entraram; tempo/questões ficaram os de antes.
    s = snap_atual(db, SnapshotElefante, a.id)
    assert (s.livros_unicos, s.tempo_leitura_min, s.questoes_tentativas,
            s.questoes_acertos) == (7, 200, 30, 25)
    # B não mudou: nenhum retrato repetido com a data de hoje (A ganhou um, com os
    # livros novos).
    assert _retratos(db, b.id) == retratos_b
    # Não conta como "em dia".
    assert service.ultimo_em_dia_em(db, eid, "elefante") < ex.finalizada_em


def test_tempo_e_questoes_renomeados_sem_mudanca_nao_e_nada_mudou(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)
    antes = (_retratos(db, a.id), _retratos(db, b.id))
    verificada = service.ultima_verificacao_em(db, eid, "elefante")

    _sem(nav, ("responses", "approvedResponses"))
    ex, _ = rodar(db, eid, "elefante")

    assert ex.status == "sem_atualizacao"
    assert ex.motivo == MOTIVO                                   # não 'nada_mudou'
    assert "questões aprovadas" in _alerta(db, eid).mensagem
    assert (_retratos(db, a.id), _retratos(db, b.id)) == antes
    assert service.ultima_verificacao_em(db, eid, "elefante") == verificada


def test_valor_nulo_explicito_nao_e_campo_renomeado(db, escola_completa, monkeypatch):
    """``responses: null`` em todo mundo (turma sem questões) é "sem dado", não API
    que mudou: segue como antes, sem alerta."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")

    _sem(nav, ("responses", "approvedResponses"), nulo=True, livros_de={9300001: 7})
    ex, _ = rodar(db, eid, "elefante")

    assert ex.status == "concluida"
    assert "parser_incompativel" not in alertas_abertos(db, eid, "elefante")


@pytest.mark.parametrize("com_livro_novo", [False, True])
def test_campos_sumidos_com_linha_com_defeito_nao_contam_como_em_dia(
        db, escola_completa, monkeypatch, com_livro_novo):
    """Revisão independente: uma linha sem nome (defeito) ao lado dos campos sumidos
    fazia o motivo virar 'linhas_descartadas', que conta como "em dia" — o
    'desatualizada' não abria e o card não citava os campos que faltaram."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)
    em_dia_antes = service.ultimo_em_dia_em(db, eid, "elefante")

    nav.turmas[CID]["alunos"].append(aluno_el(9300003, "", [], tempo=1, resp=1, ok=1))
    _sem(nav, NAO_ESSENCIAIS, livros_de={9300001: 7} if com_livro_novo else None)
    ex, _ = rodar(db, eid, "elefante")

    assert ex.status == ("parcial" if com_livro_novo else "sem_atualizacao")
    assert ex.motivo == MOTIVO
    assert service.ultimo_em_dia_em(db, eid, "elefante") == em_dia_antes
    # O defeito continua dito no alerta da coleta parcial.
    abertos = alertas_abertos(db, eid, "elefante")
    assert "parser_incompativel" in abertos and "coleta_parcial" in abertos
    msg = db.execute(select(SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.tipo == "coleta_parcial",
        SincronizacaoAlerta.resolvido.is_(False))).scalar_one()
    assert "descartada" in msg


def _mensagem_coleta_parcial(db, eid):
    return db.execute(select(SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.tipo == "coleta_parcial",
        SincronizacaoAlerta.resolvido.is_(False))).scalar_one()


def test_so_campo_sumido_nao_manda_sincronizar_de_novo(db, escola_completa, monkeypatch):
    """Revisão independente: o 'coleta_parcial' da S9 dizia "Sincronize de novo para
    completar", mas um campo renomeado não volta com outra coleta (o crítico ao lado
    diz que o conector precisa ser revisto)."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)

    _sem(nav, ("responses",), livros_de={9300001: 7})
    ex, _ = rodar(db, eid, "elefante")

    assert (ex.status, ex.motivo) == ("parcial", MOTIVO)
    msg = _mensagem_coleta_parcial(db, eid)
    assert "questões respondidas não vieram" in msg
    assert "Sincronize de novo" not in msg
    assert "não voltam com outra coleta" in msg


def test_campo_sumido_com_defeito_ainda_manda_sincronizar_de_novo(
        db, escola_completa, monkeypatch):
    """Com linha com defeito ao lado, repetir a coleta continua valendo para ela."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)

    nav.turmas[CID]["alunos"].append(aluno_el(9300003, "", [], tempo=1, resp=1, ok=1))
    _sem(nav, ("responses",), livros_de={9300001: 7})
    rodar(db, eid, "elefante")

    msg = _mensagem_coleta_parcial(db, eid)
    assert "Sincronize de novo para completar." in msg
    assert "não voltam com outra coleta" in msg


def test_campos_sumidos_com_pendencia_de_revisao_nao_contam_como_em_dia(
        db, escola_completa, monkeypatch):
    """A mesma coisa com uma conta que vai para a revisão (nome de uma palavra): o
    motivo virava 'correspondencia_pendente', que conta como "em dia". A pendência
    continua com o alerta próprio."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)
    em_dia_antes = service.ultimo_em_dia_em(db, eid, "elefante")

    nav.turmas[CID]["alunos"].append(
        aluno_el(9300004, "Ficticio", [livro("Livro Ficticio X")]))
    _sem(nav, NAO_ESSENCIAIS)
    ex, _ = rodar(db, eid, "elefante")

    assert (ex.status, ex.motivo) == ("sem_atualizacao", MOTIVO)
    assert service.ultimo_em_dia_em(db, eid, "elefante") == em_dia_antes
    abertos = alertas_abertos(db, eid, "elefante")
    assert "parser_incompativel" in abertos and "correspondencia_pendente" in abertos


def _status_das_importacoes_dos_retratos(db, desde):
    """{status da importação} dos retratos gravados a partir de ``desde``."""
    from app.models import Importacao
    return set(db.execute(
        select(Importacao.status).join(
            SnapshotElefante, SnapshotElefante.importacao_id == Importacao.id)
        .where(SnapshotElefante.data_referencia >= desde)).scalars())


def test_questoes_do_periodo_nao_saem_completas_quando_todos_mudaram(
        db, escola_completa, monkeypatch):
    """Revisão independente (o dano que a S9 devia evitar): todos da turma leram um
    livro novo e responderam questões, mas a API deixou de mandar tempo e questões.
    Cada um ganhava um retrato de hoje com as questões HERDADAS, e o Relatório por
    Período dizia 0 questões com cobertura "completa". Agora a importação é marcada,
    esse retrato não é borda das questões e o relatório não afirma o que não mediu."""
    from datetime import datetime

    from app.models import Importacao
    from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
    from app.services import relatorios_periodo as rp
    from app.sync import fuso

    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    hoje = fuso.hoje_local()
    d0 = datetime.combine(hoje - timedelta(days=5), datetime.min.time()).replace(
        hour=3, minute=10)                         # 00:10 em Brasília: mede o início
    for snap in db.execute(select(SnapshotElefante)).scalars():
        snap.data_referencia = d0
        db.get(Importacao, snap.importacao_id).created_at = d0
    db.commit()
    for al in nav.turmas[CID]["alunos"]:          # na plataforma: livro novo e +20 questões
        al["livros"].append(livro(f"Livro Ficticio Novo {al['sid']}",
                                  data=(hoje - timedelta(days=1)).isoformat() + "T10:00:00"))
        al["total"] = len(al["livros"])
        al["resp"] += 20
        al["ok"] += 15
    _sem(nav, NAO_ESSENCIAIS)

    ex, _ = rodar(db, eid, "elefante")

    assert (ex.status, ex.motivo) == ("parcial", MOTIVO)
    # Os livros entraram (nada destruído): retrato novo de hoje para os dois…
    assert _retratos(db, a.id) == 2 and _retratos(db, b.id) == 2
    # …gravado por importações marcadas: as questões dele não são medida de hoje.
    assert _status_das_importacoes_dos_retratos(db, d0 + timedelta(days=1)) == {
        IMPORTACAO_SEM_QUESTOES}
    assert _status_das_importacoes_dos_retratos(db, d0) >= {"concluida"}
    rel = rp.gerar(db, eid, preset="personalizado", plataformas=("elefante",),
                   inicio=d0.date(), fim=hoje, hoje=hoje)["elefante"]
    cob = rel["cobertura_questoes"]
    assert cob["completa"] is False and cob["status"] != "completa"
    assert rel["questoes_tentativas"] is None          # sem número, não "0"
    assert cob["alunos_questoes_nao_vieram"] == 2


def test_so_o_tempo_sumido_nao_marca_a_importacao(db, escola_completa, monkeypatch):
    """Sem o tempo, as questões vieram: o retrato novo mede as questões e a
    importação não é marcada."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)
    desde = service._agora() - timedelta(hours=1)

    _sem(nav, ("totalReadTime",), livros_de={9300001: 7})
    ex, _ = rodar(db, eid, "elefante")

    assert (ex.status, ex.motivo) == ("parcial", MOTIVO)
    assert _status_das_importacoes_dos_retratos(db, desde) == {"concluida"}


def test_campo_ausente_so_em_parte_das_linhas_segue_herdando_como_antes(
        db, escola_completa, monkeypatch):
    """Só a rename (todas as linhas) é tratada: a linha isolada sem tempo continua
    herdando (a API nem sempre manda) — o comportamento de antes, sem alerta."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    original = nav.avaliar

    async def so_de_b(expressao):
        res = await original(expressao)
        if isinstance(res, dict) and isinstance(res.get("body"), dict) \
                and "students" in res["body"]:
            for s in res["body"]["students"]:
                if s["studentId"] == 9300002:
                    s.pop("totalReadTime", None)
                else:
                    s["totalBooksRead"] = 9
        return res
    nav.avaliar = so_de_b
    ex, _ = rodar(db, eid, "elefante")

    assert ex.status == "concluida"
    assert "parser_incompativel" not in alertas_abertos(db, eid, "elefante")
