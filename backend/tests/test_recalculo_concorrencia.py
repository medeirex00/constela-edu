"""Concorrência do RECÁLCULO de notas (P0): ``scoring.recalcular_escola`` faz
SELECT-then-INSERT em ``notas`` e precisa de exclusão mútua por escola.

Sem trava, dois recálculos sobrepostos da MESMA escola (importação terminando +
mudança de peso, /recalcular clicado duas vezes, sync automática + gestor) leem
o mesmo estado e gravam por cima um do outro:

  * ``notas`` vazia → os dois INSERTem → ``uq_nota_aluno_ano`` estoura
    (UniqueViolation 23505 → HTTP 500) e, quando as ordens de ranking diferem,
    dá até DEADLOCK (40P01) — a ordem dos INSERTs é a ordem do ranking;
  * ``notas`` já existente → os dois UPDATEam → NENHUM erro, e vence quem
    gravar por último, que pode ser quem leu o estado mais VELHO. É a
    CORRUPÇÃO SILENCIOSA: o dano real, sem sintoma visível.

A defesa é ``bloquear_escola_para_recalculo`` (advisory lock transacional,
namespace 4713) adquirida ANTES de qualquer leitura que participe do cálculo.

Este módulo cobre o que dá para provar em SQLite (ordem, hierarquia de travas,
idempotência e a fórmula intacta). A corrida REAL entre transações é provada em
``test_recalculo_concorrencia_pg.py`` (Postgres, marcador ``postgres``).
"""
import pytest
from sqlalchemy import event, func, select

from app.core import database as core_db
from app.models import Configuracao, Nota, SnapshotElefante, SnapshotMatific
from app.services import scoring

# Tabelas cujo SELECT ALIMENTA o cálculo: se algum destes for lido antes da
# trava, a trava chegou tarde (o valor lido pode já estar obsoleto).
_TABELAS_DO_CALCULO = ("matriculas", "notas", "snapshots_matific",
                       "snapshots_elefante")


def _importacao(db, escola_id, usuario_id=None):
    from app.models import Importacao

    imp = Importacao(escola_id=escola_id, usuario_id=usuario_id,
                     plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _semear_snapshots(db, escola_completa):
    """Dados fixos (nada aleatório) — a mesma entrada tem de dar a mesma nota."""
    escola_id = escola_completa["escola"].id
    imp = _importacao(db, escola_id, escola_completa["admin"].id)
    valores = [
        (120, 300, 4.5, 30, 600, 100, 80, {"AA": 10, "D": 5}),
        (60, 150, 3.0, 15, 300, 50, 25, {"AA": 5, "D": 2}),
        (200, 500, 5.0, 45, 900, 150, 120, {"AA": 20, "D": 9}),
    ]
    for aluno, v in zip(escola_completa["alunos"], valores):
        db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno.id,
                               importacao_id=imp.id, atividades=v[0],
                               estrelas=v[1], pontuacao_media=v[2]))
        db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno.id,
                                importacao_id=imp.id, livros_unicos=v[3],
                                tempo_leitura_min=v[4], questoes_tentativas=v[5],
                                questoes_acertos=v[6], livros_por_nivel=v[7]))
    db.commit()
    return escola_id


def _notas(db, escola_id):
    return {
        n.aluno_id: (n.nota_matific, n.nota_elefante, n.nota_geral, n.posicao)
        for n in db.execute(
            select(Nota).where(Nota.escola_id == escola_id)).scalars()
    }


# --------------------------------------------------------------------------
# 1. A ORDEM: travar depois de ler não protege nada.
# --------------------------------------------------------------------------
def test_trava_adquirida_antes_de_qualquer_leitura_do_calculo(
        db, escola_completa, monkeypatch):
    """A trava tem de ser a PRIMEIRA coisa: um SELECT anterior a ela já traz um
    estado que pode envelhecer antes da gravação — foi exatamente assim que a
    corrida nasceu."""
    escola_id = _semear_snapshots(db, escola_completa)

    lidas_antes: list[str] = []
    leituras: list[str] = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _espiar(conn, cursor, sql, params, contexto, executemany):
        texto = " ".join(str(sql).lower().split())
        if texto.startswith("select"):
            for tabela in _TABELAS_DO_CALCULO:
                if f" {tabela}" in texto:
                    leituras.append(tabela)

    trava_real = scoring.bloquear_escola_para_recalculo

    def _spy(sessao, eid):
        lidas_antes.extend(leituras)          # fotografia no momento da trava
        return trava_real(sessao, eid)

    monkeypatch.setattr(scoring, "bloquear_escola_para_recalculo", _spy)
    try:
        scoring.recalcular_escola(db, escola_id)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", _espiar)

    assert lidas_antes == [], (
        "a trava foi adquirida DEPOIS de ler "
        f"{sorted(set(lidas_antes))} — leitura obsoleta entra no cálculo")
    assert leituras, "o espião não viu leitura nenhuma — teste inócuo"


def test_trava_do_recalculo_e_advisory_lock_so_no_postgres():
    """A trava existe de verdade (e é no-op no SQLite de dev/testes)."""
    executados: list[str] = []

    class _Sessao:
        def __init__(self, dialeto):
            self._dialeto = dialeto

        def get_bind(self):
            return type("B", (), {"dialect": type("D", (), {"name": self._dialeto})()})()

        def execute(self, sql, params=None):
            executados.append(str(sql))

    core_db.bloquear_escola_para_recalculo(_Sessao("postgresql"), 7)
    assert len([s for s in executados if "pg_advisory_xact_lock" in s]) == 1

    executados.clear()
    core_db.bloquear_escola_para_recalculo(_Sessao("sqlite"), 7)
    assert executados == []


def test_namespaces_das_travas_nao_colidem():
    """Importação (4711), coleta (4712) e recálculo (4713) são namespaces
    distintos — travas diferentes não podem se bloquear entre si por acidente."""
    assert len({core_db._NS_IMPORTACAO, core_db._NS_COLETA_AVALIACAO,
                core_db._NS_RECALCULO}) == 3
    assert core_db._NS_RECALCULO == 4713


# --------------------------------------------------------------------------
# 2. HIERARQUIA: a ordem é importação (4711) → recálculo (4713). Os endpoints de
# importação comitam ANTES de recalcular (não seguram 4711 no recálculo); a
# consolidação de sombras e o /resolver recalculam DENTRO da trava de
# importação (fusão/dado e nota caem juntos) — permitido. O inverso, pedir 4711
# segurando 4713, é o que fecharia o ciclo: proibido.
# --------------------------------------------------------------------------
@pytest.fixture()
def vigia_hierarquia(monkeypatch):
    """Marca a trava de IMPORTAÇÃO como 'segura' até o commit/rollback e falha
    se o recálculo for chamado dentro dessa janela."""
    from app.routers import importacoes as imp
    from app.routers import academico as acad
    from sqlalchemy.orm import Session

    estado = {"importacao_ativa": False, "violacoes": [], "recalculos": 0}

    trava_real = core_db.bloquear_escola_para_importacao

    def _travar(sessao, eid):
        estado["importacao_ativa"] = True
        return trava_real(sessao, eid)

    for modulo in (imp, acad):
        monkeypatch.setattr(modulo, "bloquear_escola_para_importacao", _travar)

    commit_real, rollback_real = Session.commit, Session.rollback

    def _commit(self):
        r = commit_real(self)
        estado["importacao_ativa"] = False   # lock transacional cai no commit
        return r

    def _rollback(self):
        r = rollback_real(self)
        estado["importacao_ativa"] = False
        return r

    monkeypatch.setattr(Session, "commit", _commit)
    monkeypatch.setattr(Session, "rollback", _rollback)

    recalcular_real = scoring.recalcular_escola

    def _recalcular(sessao, eid):
        estado["recalculos"] += 1
        if estado["importacao_ativa"]:
            estado["violacoes"].append(eid)
        return recalcular_real(sessao, eid)

    monkeypatch.setattr(scoring, "recalcular_escola", _recalcular)
    return estado


def test_confirmar_solta_a_trava_de_importacao_antes_de_recalcular(
        cliente, db, escola_completa, vigia_hierarquia):
    """/importacoes/confirmar pega 4711, COMITA e só então recalcula."""
    escola_id = escola_completa["escola"].id
    r = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
              "recalcular": True,
              "linhas": [{"nome": escola_completa["alunos"][0].nome,
                          "dados": {"livros_unicos": 4}}]})
    assert r.status_code == 200, r.text
    assert vigia_hierarquia["recalculos"] == 1, "o recálculo nem rodou"
    assert vigia_hierarquia["violacoes"] == [], (
        "recálculo (4713) pedido ainda segurando a trava de importação (4711)")


def test_matriculas_confirmar_solta_a_trava_antes_de_recalcular(
        cliente, db, escola_completa, vigia_hierarquia):
    """/importacoes/matriculas/confirmar (Lista Piloto): mesma hierarquia."""
    import io
    from datetime import date

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1º Ano A"
    ws.append([None, None, None, "PREFEITURA MUNICIPAL DE CARAGUATATUBA"])
    ws.append(["Escola:", None, "EMEF TESTE", None, None, None, None,
               "Lista Piloto:", 2026])
    ws.append([])
    ws.append(["Professor:", None, "PAULA", None, "Ano:", "1º Ano A",
               "Turno:       TARDE", None, "N.º da Classe (SED):", 300396614])
    ws.append([])
    ws.append(["N.º", "RM", "RA", "Nome", "Data de Nasc."])
    ws.append([1, 4446, "123.100.026-0", "CRIANCA DA LISTA PILOTO",
               date(2019, 9, 18)])
    buffer = io.BytesIO()
    wb.save(buffer)

    escola_id = escola_completa["escola"].id
    r = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/matriculas/confirmar",
        files={"arquivo": ("Lista Piloto 2026.xlsx", buffer.getvalue(),
                           "application/vnd.openxmlformats-officedocument"
                           ".spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert vigia_hierarquia["recalculos"] == 1, "o recálculo nem rodou"
    assert vigia_hierarquia["violacoes"] == []


@pytest.fixture()
def vigia_ordem_das_travas(monkeypatch):
    """Registra a ORDEM em que as travas da escola são pedidas (``importacao`` =
    4711, ``recalculo`` = 4713) e conta como violação pedir 4711 com 4713 já
    segura — o sentido proibido. As travas são transacionais: caem no
    commit/rollback."""
    from sqlalchemy.orm import Session

    from app.routers import importacoes as imp

    estado = {"seguras": set(), "ordem": [], "violacoes": []}
    trava_importacao_real = core_db.bloquear_escola_para_importacao
    trava_recalculo_real = scoring.bloquear_escola_para_recalculo

    def _importacao(sessao, eid):
        if "recalculo" in estado["seguras"]:
            estado["violacoes"].append(eid)
        estado["seguras"].add("importacao")
        estado["ordem"].append("importacao")
        return trava_importacao_real(sessao, eid)

    def _recalculo(sessao, eid):
        estado["seguras"].add("recalculo")
        estado["ordem"].append(("recalculo", "importacao" in estado["seguras"]))
        return trava_recalculo_real(sessao, eid)

    # A consolidação importa a trava de importação na hora da chamada (de
    # core_db); o router a importou pelo nome; o scoring, a do recálculo.
    monkeypatch.setattr(core_db, "bloquear_escola_para_importacao", _importacao)
    monkeypatch.setattr(imp, "bloquear_escola_para_importacao", _importacao)
    monkeypatch.setattr(scoring, "bloquear_escola_para_recalculo", _recalculo)
    commit_real, rollback_real = Session.commit, Session.rollback

    def _commit(self):
        r = commit_real(self)
        estado["seguras"].clear()
        return r

    def _rollback(self):
        r = rollback_real(self)
        estado["seguras"].clear()
        return r

    monkeypatch.setattr(Session, "commit", _commit)
    monkeypatch.setattr(Session, "rollback", _rollback)
    return estado


def test_consolidacao_de_sombras_recalcula_dentro_da_trava_de_importacao(
        db, escola_completa, vigia_ordem_das_travas):
    """``consolidacao_sombras.aplicar`` pega 4711 e recalcula na MESMA transação
    (fusão e nota caem juntas): a ordem permitida, 4711 → 4713, sem nunca pedir
    4711 com 4713 segura."""
    from app.models import Aluno, IdentidadeExterna, Matricula
    from app.services import consolidacao_sombras as cs

    escola, turma = escola_completa["escola"], escola_completa["turma"]
    oficial = Aluno(escola_id=escola.id, nome="ZULEICA RAMONA TEODORO DA CUNHA",
                    da_lista_piloto=True)
    sombra = Aluno(escola_id=escola.id, nome="ZULEICA R", da_lista_piloto=False)
    db.add_all([oficial, sombra])
    db.flush()
    for aluno in (oficial, sombra):
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=sombra.id,
                             plataforma="matific", id_externo="u-sombra"))
    db.commit()
    plano = cs.planejar(db, escola.id)
    vigia_ordem_das_travas["ordem"].clear()
    res = cs.aplicar(db, plano, usuario_id=None, origem="teste")
    assert [x["sombra_id"] for x in res["consolidados"]] == [sombra.id]
    # O recálculo foi pedido COM a trava de importação segura (o aninhamento
    # documentado), e nunca o inverso.
    assert vigia_ordem_das_travas["ordem"] == ["importacao", ("recalculo", True)]
    assert vigia_ordem_das_travas["violacoes"] == []


def test_resolver_de_revisao_recalcula_dentro_da_trava_de_importacao(
        cliente, db, escola_completa, vigia_ordem_das_travas):
    """O /resolver de revisão de identidade aplica o dado da pendência e
    recalcula na MESMA transação (``commit=False``): 4711 → 4713, nunca o
    inverso."""
    from app.models import RevisaoIdentidade

    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    rev = RevisaoIdentidade(
        escola_id=escola.id, chave="elefante|id:8888|resumo||",
        chave_identidade="elefante|id:8888", plataforma="elefante", formato="resumo",
        id_externo="8888", nome_recebido="ANA BEATRIZ SOUZA", turma_informada="3ºA",
        motivo="nome_casa_em_outra_sala", candidatos=[],
        linhas=[{"turma_relatorio": "3ºA", "elefante_student_id": "8888",
                 "livros_unicos": 9, "tempo_leitura_min": 45,
                 "questoes_tentativas": 6, "questoes_acertos": 5}],
        contexto={"tipo": "texto", "periodo_inicio": "", "periodo_fim": "",
                  "data_referencia": "2026-09-22T16:51:00+00:00"},
        origem="sincronizacao", status="pendente")
    db.add(rev)
    db.commit()
    vigia_ordem_das_travas["ordem"].clear()
    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": ana.id})
    assert r.status_code == 200, r.text
    assert r.json()["importacoes"], "o /resolver não aplicou dado — teste inócuo"
    ordem = vigia_ordem_das_travas["ordem"]
    assert ordem[-1] == ("recalculo", True) and set(ordem[:-1]) == {"importacao"}
    assert vigia_ordem_das_travas["violacoes"] == []


def test_recalcular_recebe_transacao_limpa(cliente, cliente_global, db,
                                           escola_completa, monkeypatch):
    """Todo chamador que não precisa recalcular na mesma transação comita ANTES
    de recalcular: a sessão que entra em ``recalcular_escola`` não tem escrita
    pendente. Importa porque a trava é transacional — pendências arrastariam a
    transação (e o lock) para fora do escopo do recálculo. (A consolidação de
    sombras e o /resolver recalculam com ``commit=False`` dentro da própria
    transação, de propósito: seção 2.)"""
    pendencias: list[tuple] = []
    recalcular_real = scoring.recalcular_escola

    def _recalcular(sessao, eid):
        pendencias.append((len(sessao.new), len(sessao.dirty), len(sessao.deleted)))
        return recalcular_real(sessao, eid)

    monkeypatch.setattr(scoring, "recalcular_escola", _recalcular)

    escola_id = escola_completa["escola"].id
    base = f"/api/v1/escolas/{escola_id}"
    # Uma amostra dos caminhos reais que disparam recálculo: o botão explícito,
    # o fim de uma importação, uma mudança de pesos (parâmetro oficial — só o
    # Admin Global grava) e uma ação em massa.
    assert cliente.post(f"{base}/recalcular").status_code == 200
    assert cliente.post(
        f"{base}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
              "recalcular": True,
              "linhas": [{"nome": escola_completa["alunos"][0].nome,
                          "dados": {"livros_unicos": 7}}]}).status_code == 200
    assert cliente_global.put(
        f"{base}/configuracoes/pesos/geral",
        json={"valores": {"matific": 40.0, "elefante": 60.0}}).status_code == 200
    assert cliente.post(
        f"{base}/alunos/acoes",
        json={"acao": "arquivar",
              "aluno_ids": [escola_completa["alunos"][1].id]}).status_code == 200

    assert len(pendencias) == 4, pendencias
    assert all(p == (0, 0, 0) for p in pendencias), pendencias


# --------------------------------------------------------------------------
# 3. A trava não muda o RESULTADO: idempotência e fórmula intactas.
# --------------------------------------------------------------------------
def test_recalculo_e_idempotente(db, escola_completa):
    """Rodar duas vezes seguidas dá exatamente o mesmo resultado."""
    escola_id = _semear_snapshots(db, escola_completa)

    assert scoring.recalcular_escola(db, escola_id) == 3
    primeira = _notas(db, escola_id)
    assert scoring.recalcular_escola(db, escola_id) == 3
    db.expire_all()
    assert _notas(db, escola_id) == primeira

    total = db.execute(
        select(func.count()).select_from(Nota)
        .where(Nota.escola_id == escola_id)).scalar_one()
    assert total == 3, "1 nota por aluno/ano — nada duplicado"


def test_formula_inalterada(db, escola_completa):
    """Valores CONGELADOS antes da introdução da trava. A trava é exclusão
    mútua: não pode mexer em peso, normalização, nota nem desempate. Se este
    teste ficar vermelho, a fórmula mudou — não é regressão de concorrência."""
    escola_id = _semear_snapshots(db, escola_completa)
    # A escola de teste usa uma régua CUSTOM (NivelDificuldade próprio no fixture:
    # AA=1.0, D=4.0) e estes valores foram CONGELADOS com essa régua. No padrão
    # Constela a nota LOCAL passou a ser a institucional (dificuldade A3), que
    # ignora o NivelDificuldade custom. Marcar a escola como PERSONALIZADA faz o
    # cálculo local seguir idêntico ao congelado — é o guard da FÓRMULA (não da
    # separação institucional×escola), então preserva-se a config original.
    db.add(Configuracao(escola_id=escola_id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.commit()
    scoring.recalcular_escola(db, escola_id)

    por_nome = {
        aluno.nome: _notas(db, escola_id)[aluno.id]
        for aluno in escola_completa["alunos"]
    }
    assert por_nome == {
        "Ana Beatriz Souza": (70.5, 62.74, 66.62, 2),
        "João Pedro Barbosa": (40.5, 27.67, 34.09, 3),
        "Sofia Almeida Duarte": (100.0, 100.0, 100.0, 1),
    }
