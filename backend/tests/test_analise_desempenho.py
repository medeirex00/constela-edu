"""Análise educacional — CUSTO em consultas ao banco. Em produção a API e o banco ficam em
regiões diferentes (~195 ms por ida e volta): o tempo de uma rota é o NÚMERO de consultas. A
validação com os dados reais mediu 11,9 s em ``/plataformas``; numa rede fictícia de 28
escolas com essa latência, a rota fazia 205 consultas (44 s) e a evolução por bimestre, ~175 s
(o web desiste em 15 s e em 60 s).

O que estes testes sustentam, contando as consultas (``before_cursor_execute``):

* escola SEM nenhuma coleta não custa consulta nenhuma a mais na rota da rede: a supressão
  sai de UMA contagem por escola × série (que não depende do período) e as coletas e o
  primeiro evento de UMA consulta agrupada;
* escola COM coleta também não: as leituras são UMA consulta por fonte para todas as escolas
  (não crescem com o número de escolas, de séries, nem com o histórico de retratos: só os
  retratos que a regra usa são lidos);
* a evolução por bimestre custa o mesmo que UM período da rota de plataformas (os bimestres
  são lidos juntos), e a da ficha (``so_escola``) mede só a escola;
* a rota da escola mede SÓ a escola — o custo não cresce com as outras escolas da rede — e
  devolve o MESMO bloco que a rota da rede mostra para ela.

Dados INVENTADOS (decisão D13).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app.models import SnapshotElefante, SnapshotMatific
from app.services.analise import AnaliseInvalida
from app.services.analise import escola as svc_escola
from app.services.analise import evolucao as svc_evolucao
from app.services.analise import plataformas as svc
from app.services.analise import relacao as svc_relacao
from tests.test_analise_base import (HOJE, _importacao, ler, livros, nova_escola, nova_rede,
                                     turma_com_alunos)

SERIES = ("1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano")
# Consultas da rota da rede inteira, para QUALQUER número de escolas e de bimestres: escolas
# com os módulos, coorte com as coletas, Elefante (livros, tempo, eventos e nível), questões e
# Matific = 5 (eram 7: escolas e módulos, coorte e coletas iam separados), mais 1 aqui: a
# recarga da rede, que o ``commit`` do próprio teste expira (``rede.id``).
CONSULTAS_DA_ROTA = 6


class _Contador:
    def __init__(self, db):
        self.engine, self.n = db.get_bind(), 0

    def _conta(self, *_a, **_k):
        self.n += 1

    def __enter__(self):
        self.n = 0
        event.listen(self.engine, "before_cursor_execute", self._conta)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._conta)


def _escola_com_dado(db, rede, nome, inep, dias=10):
    """5 séries × 6 crianças, com leitura e um retrato DIÁRIO de cada plataforma (o
    histórico longo que a versão antiga carregava inteiro, série por série)."""
    e = nova_escola(db, rede, nome, inep)
    lv = livros(db, e, 2, "K")
    imp_e, imp_m = _importacao(db, e, "elefante"), _importacao(db, e, "matific")
    retratos = []
    for serie in SERIES:
        for a in turma_com_alunos(db, e, serie, 6):
            ler(db, e, a, lv[:1], datetime(2026, 5, 4, 10, 0))
            for d in range(dias):
                quando = datetime(2026, 10, 4, 3, 10) - timedelta(days=d)
                retratos.append(SnapshotElefante(
                    escola_id=e.id, aluno_id=a.id, importacao_id=imp_e.id,
                    data_referencia=quando, livros_unicos=0, tempo_leitura_min=0,
                    questoes_tentativas=10 * (dias - d), questoes_acertos=7 * (dias - d),
                    livros_por_nivel={}))
                retratos.append(SnapshotMatific(
                    escola_id=e.id, aluno_id=a.id, importacao_id=imp_m.id,
                    data_referencia=quando, atividades=dias - d, estrelas=3 * (dias - d),
                    pontuacao_media=0.0))
    db.add_all(retratos)
    db.flush()
    return e


def _escola_sem_dado(db, rede, nome, inep):
    e = nova_escola(db, rede, nome, inep)
    for serie in SERIES:
        turma_com_alunos(db, e, serie, 6)
    return e


def _rede(db, *, com: int, sem: int, sufixo: str):
    rede = nova_rede(db, nome=f"Rede Fictícia Custosa {sufixo}", codigo=f"35997{sufixo}")
    escolas = [_escola_com_dado(db, rede, f"EMEF Custosa {sufixo}-{i}", f"3599{sufixo}{i:02d}")
               for i in range(com)]
    escolas += [_escola_sem_dado(db, rede, f"EMEF Parada {sufixo}-{i}", f"3599{sufixo}{50 + i}")
                for i in range(sem)]
    db.commit()
    return rede, escolas


def _consultas(db, funcao) -> tuple[int, dict]:
    with _Contador(db) as c:
        saida = funcao()
    return c.n, saida


def test_escola_sem_coleta_nao_custa_consulta_na_rota_da_rede(db):
    rede_a, _ = _rede(db, com=2, sem=0, sufixo="11")
    rede_b, _ = _rede(db, com=2, sem=6, sufixo="12")
    n_a, _ = _consultas(db, lambda: svc.plataformas_da_rede(db, rede_a, hoje=HOJE))
    n_b, dados = _consultas(db, lambda: svc.plataformas_da_rede(db, rede_b, hoje=HOJE))
    print(f"\n/plataformas: 2 escolas com dado = {n_a} consultas; + 6 sem coleta = {n_b}")
    assert n_b == n_a                                    # O(1): escola sem dado não custa nada
    paradas = [e for e in dados["escolas"] if e["nome"].startswith("EMEF Parada")]
    assert len(paradas) == 6 and all(e["cobertura"]["elefante"] == svc.SEM_COLETA
                                     for e in paradas)
    assert all(e["elefante"]["livros_por_aluno"] is None for e in paradas)   # nunca 0


def test_escola_com_coleta_custa_um_numero_fixo_de_consultas(db):
    rede_a, _ = _rede(db, com=2, sem=0, sufixo="21")
    rede_b, _ = _rede(db, com=5, sem=0, sufixo="22")
    n_a, _ = _consultas(db, lambda: svc.plataformas_da_rede(db, rede_a, hoje=HOJE))
    n_b, dados = _consultas(db, lambda: svc.plataformas_da_rede(db, rede_b, hoje=HOJE))
    print(f"\n/plataformas: 2 escolas = {n_a}; 5 escolas = {n_b}")
    assert n_b == n_a == CONSULTAS_DA_ROTA        # nem uma consulta a mais por escola
    # O histórico diário NÃO muda a conta: o ganho é o do último retrato menos a base.
    alfa = dados["escolas"][0]
    assert alfa["elefante"]["taxa_acerto_pct"] == 70.0
    assert alfa["matific"]["atividades_por_aluno"] == 10.0


def test_relacao_custa_o_mesmo_que_as_plataformas_mais_os_indicadores(db):
    rede_a, _ = _rede(db, com=2, sem=0, sufixo="31")
    rede_b, _ = _rede(db, com=2, sem=6, sufixo="32")
    n_a, _ = _consultas(db, lambda: svc_relacao.relacao(db, rede_a, indicador="saresp",
                                                        hoje=HOJE))
    n_b, _ = _consultas(db, lambda: svc_relacao.relacao(db, rede_b, indicador="saresp",
                                                        hoje=HOJE))
    print(f"\n/relacao: 2 escolas com dado = {n_a}; + 6 sem coleta = {n_b}")
    assert n_b == n_a


def test_rota_da_escola_mede_so_a_escola(db):
    rede_a, esc_a = _rede(db, com=2, sem=0, sufixo="41")
    rede_b, esc_b = _rede(db, com=6, sem=6, sufixo="42")
    n_a, a = _consultas(db, lambda: svc_escola.analise_da_escola(db, esc_a[0], hoje=HOJE))
    n_b, b = _consultas(db, lambda: svc_escola.analise_da_escola(db, esc_b[0], hoje=HOJE))
    print(f"\n/escolas/{{id}}/analise: rede de 2 escolas = {n_a}; rede de 12 = {n_b}")
    assert n_b == n_a                    # as outras 11 escolas não são medidas
    # E o bloco é o MESMO que a rota da rede mostra para a escola.
    da_rede = next(e for e in svc.plataformas_da_rede(db, rede_b, hoje=HOJE)["escolas"]
                   if e["escola_id"] == esc_b[0].id)
    p = b["plataformas"]
    assert p["alunos"] == da_rede["alunos"] and p["series"] == da_rede["series"]
    assert p["elefante"] == da_rede["elefante"] and p["matific"] == da_rede["matific"]
    assert a["plataformas"]["suprimido"] is False


@pytest.mark.parametrize("dias", [3, 40])
def test_historico_longo_nao_muda_o_numero_de_consultas(db, dias):
    rede = nova_rede(db, nome=f"Rede Fictícia Histórico {dias}", codigo=f"35996{dias:02d}")
    _escola_com_dado(db, rede, "EMEF Histórica", f"359976{dias:02d}", dias=dias)
    db.commit()
    n, dados = _consultas(db, lambda: svc.plataformas_da_rede(db, rede, hoje=HOJE))
    print(f"\n/plataformas com {dias} retratos por criança: {n} consultas")
    (e,) = dados["escolas"]
    # 7 retratos por semana: ganho = último − base (o primeiro do ano parte do zero).
    assert e["matific"]["atividades_por_aluno"] == float(dias)
    assert n == CONSULTAS_DA_ROTA


def test_evolucao_le_os_bimestres_juntos(db):
    """Os 4 bimestres custam o mesmo que UM período, para 2 ou 7 escolas; e a evolução da
    ficha (só a escola) devolve, da escola, os MESMOS números da evolução da rede."""
    rede_a, _ = _rede(db, com=2, sem=0, sufixo="51")
    rede_b, esc_b = _rede(db, com=5, sem=2, sufixo="52")
    fim_do_ano = HOJE.replace(month=12, day=20)           # os 4 bimestres já começaram
    n_a, _ = _consultas(db, lambda: svc_evolucao.evolucao(db, rede_a, hoje=fim_do_ano))
    n_b, rede = _consultas(db, lambda: svc_evolucao.evolucao(db, rede_b, hoje=fim_do_ano))
    print(f"\n/evolucao: 2 escolas = {n_a}; 7 escolas = {n_b} consultas")
    assert len(rede["bimestres"]) == 4
    assert n_b == n_a == CONSULTAS_DA_ROTA
    alvo = esc_b[1].id
    n_e, so = _consultas(db, lambda: svc_evolucao.evolucao(db, rede_b, escola_id=alvo,
                                                           so_escola=True, hoje=fim_do_ano))
    assert n_e <= CONSULTAS_DA_ROTA
    assert so["filtros"]["so_escola"] is True
    for b_rede, b_so in zip(rede["bimestres"], so["bimestres"]):
        assert b_so["rede"] is None                     # a rede não foi medida
        (da_escola,) = b_so["escolas"]
        assert da_escola == next(e for e in b_rede["escolas"] if e["id"] == alvo)
    with pytest.raises(AnaliseInvalida):                   # só a escola pede a escola
        svc_evolucao.evolucao(db, rede_b, so_escola=True, hoje=fim_do_ano)


def test_rotas_de_medicao_da_secretaria_nao_releem_a_rede(db):
    """A rota das plataformas e a da evolução (as da Secretaria no Panorama, na lista e na
    ficha) não leem a linha da rede: ``exigir_rede`` já a conferiu e as medições usam só o
    id. A conta: o usuário e as 5 consultas da medição."""
    from fastapi.testclient import TestClient

    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario

    rede, escolas = _rede(db, com=2, sem=1, sufixo="61")
    db.add(Usuario(nome="Sec Medição", email="sec@medicao.local", senha_hash=hash_senha("s3nh4m"),
                   cargo="coordenador", rede_id=rede.id))
    db.commit()
    rid, alvo = rede.id, escolas[0].id
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": "sec@medicao.local", "password": "s3nh4m"})
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    sqls: list[str] = []

    def _anota(_c, _cur, sql, *_a):
        sqls.append(" ".join(sql.lower().replace('"', " ").split()))

    motor = db.get_bind()
    for url in (f"/api/v1/redes/{rid}/analise/plataformas",
                f"/api/v1/redes/{rid}/analise/plataformas/evolucao",
                f"/api/v1/redes/{rid}/analise/plataformas/evolucao?escola_id={alvo}&so_escola=true"):
        sqls.clear()
        event.listen(motor, "before_cursor_execute", _anota)
        try:
            resposta = c.get(url)
        finally:
            event.remove(motor, "before_cursor_execute", _anota)
        assert resposta.status_code == 200, (url, resposta.text[:300])
        assert not [s for s in sqls if " from redes" in s], url
        assert len(sqls) == 1 + CONSULTAS_DA_ROTA - 1, (url, len(sqls))
