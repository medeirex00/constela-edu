"""PONTA A PONTA da sincronização com as duas plataformas FALSAS, numa escola
fictícia: o caminho real inteiro (``enfileirar`` → ``executar`` → conector real
com navegador falso → orquestrador → ``confirmar`` → ``scoring`` → rotas).

Cobre, num mesmo cenário:
  * a coleta COMPLETA do Elefante e do Matific — alunos casados pelo nome e com a
    conta vinculada, leituras, retratos (livros, tempo, questões, estrelas,
    atividades), notas, ranking, status da credencial, nenhum alerta e nenhuma
    ficha nova;
  * REPETIR as duas coletas não duplica nada ('nada mudou');
  * o "Sincronizar agora" DUPLO reaproveita a mesma execução (uma thread só), e
    depois de ela terminar um novo clique cria outra;
  * a CREDENCIAL nunca aparece em log técnico, log da coleta, alerta, execução,
    auditoria nem nas respostas da API (e fica cifrada no banco);
  * o AGENDADOR continua desligado no boot (decisão do dono: a coleta automática
    está desligada de propósito).

A variante no PostgreSQL real está em ``test_aud_sync_ponta_a_ponta_pg.py``.
Dados 100% fictícios; nada sai da máquina (o plugin ``sem_rede_e1`` bloqueia rede).
"""
import json
import logging

from sqlalchemy import func, select

from app.models import Aluno, LogAuditoria, Nota, Turma
from app.models.plataformas import Leitura, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import (PlataformaCredencial, SincronizacaoAlerta,
                                      SincronizacaoExecucao, SincronizacaoLog)
from app.sync import scheduler, service, vault
from tests._infra_comum import BOOT, ambiente, sqlite_url  # noqa: F401 — fixture
from tests._infra_comum import rodar as rodar_processo
from tests._sync_nucleo_fakes import (
    API, NavElefante, PlacarFake, aluno_el, alertas_abertos, contagens, credencial,
    ident, instalar, livro, novo_aluno, rodar, snap_atual)

# Os mesmos valores que ``_sync_nucleo_fakes.credencial`` grava (fictícios).
USUARIO, SENHA = "robo-ficticio", "valor-ficticio-local"
CID_A, CID_B = 511434, 600001
K_A, K_B = "3 ANO A (300396804)", "4 ANO B (300397061)"


def escola_ficticia(db, ec):
    """A escola do conftest (3º Ano A, três crianças) mais uma turma do 4º ano com
    uma criança: duas turmas em cada plataforma."""
    eid = ec["escola"].id
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.commit()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    return eid, (*ec["alunos"], d)


def origem_elefante(alunos):
    a, b, c, d = alunos
    return {
        CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
            aluno_el(9100001, a.nome, [livro("Livro Ficticio Um", "D", "2026-09-02T10:00:00"),
                                       livro("Livro Ficticio Dois", "E", "2026-09-03T10:00:00")],
                     tempo=1200, resp=10, ok=7),
            aluno_el(9100002, b.nome, [livro("Livro Ficticio Tres", "E", "2026-09-05T10:00:00")],
                     tempo=600, resp=4, ok=2),
            aluno_el(9100003, c.nome, [livro("Livro Ficticio Quatro", "D", "2026-09-06T10:00:00")],
                     tempo=300, resp=6, ok=6)]},
        CID_B: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
            aluno_el(9200001, d.nome, [livro("Livro Ficticio Cinco", "E", "2026-09-07T10:00:00")],
                     tempo=900, resp=8, ok=5)]},
    }


def placar_matific(alunos):
    a, b, c, d = alunos
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 40, 10), ("u-b", b.nome, K_A, 30, 8),
                     ("u-c", c.nome, K_A, 20, 5), ("u-d", d.nome, K_B, 50, 12)]
    return placar


def _segredo_em(texto) -> bool:
    t = str(texto or "")
    return SENHA in t or USUARIO in t


def test_coleta_completa_das_duas_plataformas_e_repetir_nao_duplica(
        db, cliente, escola_completa, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    eid, alunos = escola_ficticia(db, escola_completa)
    a, b, c, d = alunos
    credencial(db, eid, "elefante")
    credencial(db, eid, "matific")
    instalar(monkeypatch, nav_elefante=NavElefante(origem_elefante(alunos)),
             placar=placar_matific(alunos))
    fichas_antes = db.scalar(select(func.count()).select_from(Aluno).where(
        Aluno.escola_id == eid))

    # ---------------- Elefante: coleta completa
    ex, err = rodar(db, eid, "elefante")
    assert err is None and (ex.status, ex.motivo) == ("concluida", None), (
        ex.status, ex.motivo, ex.erro_resumo)
    assert (ex.qtd_alunos, ex.qtd_turmas, ex.qtd_em_revisao, ex.qtd_falhas) == (4, 2, 0, 0)
    for al, sid in zip(alunos, (9100001, 9100002, 9100003, 9200001)):
        assert ident(db, eid, "elefante", sid) == al.id, al.nome
    lidos = {al.id: db.scalar(select(func.count()).select_from(Leitura).where(
        Leitura.aluno_id == al.id)) for al in alunos}
    assert lidos == {a.id: 2, b.id: 1, c.id: 1, d.id: 1}
    s = snap_atual(db, SnapshotElefante, a.id)
    assert (s.livros_unicos, s.tempo_leitura_min, s.questoes_tentativas,
            s.questoes_acertos) == (2, 20, 10, 7)
    s = snap_atual(db, SnapshotElefante, d.id)
    assert (s.livros_unicos, s.questoes_tentativas, s.questoes_acertos) == (1, 8, 5)
    assert vault.obter_linha(db, eid, "elefante").status == "valida"
    assert alertas_abertos(db, eid, "elefante") == []
    assert service.ultimo_em_dia_em(db, eid, "elefante") == ex.finalizada_em

    # ---------------- Matific: coleta completa
    ex, err = rodar(db, eid, "matific")
    assert err is None and (ex.status, ex.motivo) == ("concluida", None), (
        ex.status, ex.motivo, ex.erro_resumo)
    assert (ex.qtd_alunos, ex.qtd_turmas) == (4, 2)
    for al, uuid in zip(alunos, ("u-a", "u-b", "u-c", "u-d")):
        assert ident(db, eid, "matific", uuid) == al.id, al.nome
    s = snap_atual(db, SnapshotMatific, d.id)
    assert (s.estrelas, s.atividades) == (50, 12)
    assert vault.obter_linha(db, eid, "matific").status == "valida"
    assert alertas_abertos(db, eid) == []

    # Nenhuma ficha nova (todos casaram), notas para os 4 e o ranking com os 4.
    assert db.scalar(select(func.count()).select_from(Aluno).where(
        Aluno.escola_id == eid)) == fichas_antes
    assert db.scalar(select(func.count()).select_from(Nota).where(Nota.escola_id == eid)) == 4
    r = cliente.get(f"{API}/escolas/{eid}/ranking")
    assert r.status_code == 200 and {i["aluno_id"] for i in r.json()} >= {x.id for x in alunos}

    # ---------------- repetir as duas coletas não duplica nada
    antes = contagens(db, eid)
    for plat in ("elefante", "matific"):
        ex, err = rodar(db, eid, plat)
        assert err is None and (ex.status, ex.motivo) == ("sem_atualizacao", "nada_mudou"), (
            plat, ex.status, ex.motivo)
    depois = contagens(db, eid)
    antes.pop("importacoes"), depois.pop("importacoes")     # uma por arquivo, por desenho
    assert depois == antes
    assert alertas_abertos(db, eid) == []

    # ---------------- a credencial nunca aparece fora do cofre
    textos = [m for (m,) in db.execute(select(SincronizacaoLog.mensagem))]
    textos += [m for (m,) in db.execute(select(SincronizacaoAlerta.mensagem))]
    textos += [m for (m,) in db.execute(select(SincronizacaoExecucao.erro_resumo))]
    textos += [str(p) for (p,) in db.execute(select(SincronizacaoExecucao.parametros))]
    textos += [m for (m,) in db.execute(select(PlataformaCredencial.ultimo_erro))]
    textos += [str(x) for (x,) in db.execute(select(LogAuditoria.detalhes))]
    for rota in ("status", "logs?limite=1000", "alertas", "historico"):
        resp = cliente.get(f"{API}/escolas/{eid}/sync/{rota}")
        assert resp.status_code == 200, (rota, resp.text[:200])
        textos.append(resp.text)
    textos += [rec.getMessage() for rec in caplog.records]
    textos.append(caplog.text)
    assert len(textos) > 20
    assert not [t for t in textos if _segredo_em(t)], "a credencial apareceu fora do cofre"
    # No banco ela fica cifrada (e a cifra abre com as chaves deste servidor).
    for (cifrado,) in db.execute(select(PlataformaCredencial.segredo_cifrado)):
        assert not _segredo_em(cifrado)
    assert vault.obter_credencial(db, eid, "elefante").senha == SENHA


def test_sincronizar_agora_duplo_reaproveita_a_execucao(db, cliente, escola_completa,
                                                        monkeypatch):
    eid, alunos = escola_ficticia(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(origem_elefante(alunos)))
    disparos: list[int] = []
    vivas: set[int] = set()

    def _disparar(execucao_id):
        # Como o de verdade: a thread fica registrada como viva neste processo
        # enquanto espera a vez (aqui ela não roda; o teste a executa abaixo).
        disparos.append(execucao_id)
        vivas.add(execucao_id)
    monkeypatch.setattr(service, "disparar_em_thread", _disparar)
    monkeypatch.setattr(service, "_vivas_neste_processo", vivas)

    r1 = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=elefante")
    r2 = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=elefante")
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    exid = r1.json()[0]["id"]
    assert r2.json()[0]["id"] == exid and r2.json()[0]["reaproveitada"] is True
    assert r1.json()[0]["reaproveitada"] is False
    assert disparos == [exid], "o segundo clique disparou outra thread"
    assert db.scalar(select(func.count()).select_from(SincronizacaoExecucao).where(
        SincronizacaoExecucao.escola_id == eid)) == 1

    # A execução roda UMA vez; depois dela, um novo clique é uma coleta nova.
    vivas.discard(exid)
    service.executar(db, db.get(SincronizacaoExecucao, exid))
    db.expire_all()
    assert db.get(SincronizacaoExecucao, exid).status == "concluida"
    r3 = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=elefante")
    assert r3.status_code == 200 and r3.json()[0]["id"] != exid
    assert r3.json()[0]["reaproveitada"] is False


_BOOT_E_VER_AGENDADOR = BOOT + (
    "import json\n"
    "import app.sync.scheduler as _s\n"
    "import app.main\n"
    "from app.sync import service as _sv\n"
    "print('RESULTADO=' + json.dumps({'ativo': _s.ativo(), 'decisao': _s.decisao(),\n"
    "                                 'ligado': _sv.agendador_ligado()}))\n"
    "_s.parar()\n"
)


def test_agendador_continua_desligado_no_boot(sqlite_url):
    """O boot de verdade (import do ``app.main`` num processo novo, como o uvicorn
    faria), com a configuração PADRÃO — sem ``SYNC_SCHEDULER_ENABLED`` no ambiente:
    a thread do agendador não sobe e a decisão registrada é 'desligado'."""
    env = ambiente(sqlite_url, False)
    env.pop("SYNC_SCHEDULER_ENABLED", None)
    env.pop("SYNC_SCHEDULER_FORCAR", None)
    p = rodar_processo(_BOOT_E_VER_AGENDADOR, env)
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, f"{p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}"
    assert json.loads(linhas[-1][len("RESULTADO="):]) == {
        "ativo": False, "decisao": "desligado", "ligado": False}
    # E neste processo (o import do conftest também foi um boot): nada ligado.
    assert scheduler.ativo() is False and service.agendador_ligado() is False
