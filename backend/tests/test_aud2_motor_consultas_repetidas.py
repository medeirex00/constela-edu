"""As telas principais da coordenação não repetem a mesma consulta dezenas de vezes.

Em produção cada ida ao banco custa ~0,2 s (a API e o banco ficam em regiões diferentes,
O-QUE-DEPENDE-DE-VOCE.md §11). O pacote ``/sincronizacao`` (Painel e Ranking do app), o
``/insights`` e o ``/gamificacao/mural`` (Dashboard da web) chamam o ranking de evolução
três a quatro vezes, e cada chamada relia do banco a MESMA configuração da escola (o
perfil de scoring e os pesos, quatro namespaces por chamada), o MESMO contrato da rede
(``modulos_rede``), as MESMAS turmas que concorrem e o MESMO elenco (matrículas e alunos,
quem tem leitura). Nada disso muda no meio de uma leitura: dentro de
``scoring.leituras_da_requisicao`` sai do banco uma vez só.

Dados 100% fictícios.
"""
import collections
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno, Configuracao, Escola, Importacao, Leitura, Livro, Matricula, ModuloRede,
    NivelDificuldade, Professor, Rede, ReferenciaNormalizacao, SnapshotElefante,
    SnapshotMatific, Turma, Usuario,
)
from app.services import elegibilidade, evolucao, modulos, scoring

API = "/api/v1"
SENHA = "s3nh4-ficticia"


def _login(email: str) -> TestClient:
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cli


@pytest.fixture()
def cenario(db):
    """Escola de uma rede com os dois módulos, duas turmas que concorrem e uma Fase
    (não concorre), crianças com dois retratos de cada plataforma e leituras datadas."""
    rede = Rede(nome="Rede Ficticia Consultas", status="ativa")
    db.add(rede)
    db.flush()
    escola = Escola(nome="EM FICTICIA DAS CONSULTAS", ano_letivo_ativo=2026,
                    status="ativa", rede_id=rede.id)
    db.add(escola)
    db.flush()
    for ns, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=ns, chave="valores",
                            valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="N2", codigo="n2", codigos=["D"],
                            pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
    prof = Professor(escola_id=escola.id, nome="Professora Ficticia",
                     email="prof@consultas.local")
    db.add(prof)
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    livros = [Livro(escola_id=escola.id, titulo=f"Livro Ficticio {i}", nivel_codigo="D")
              for i in range(3)]
    db.add_all(livros)
    db.flush()
    agora = datetime.now().replace(microsecond=0)
    turmas = [
        Turma(escola_id=escola.id, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=2026,
              status="ativa", professor_id=prof.id, turno="manha"),
        Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano", ano_letivo=2026,
              status="ativa", turno="tarde"),
        Turma(escola_id=escola.id, nome="1 FASE A", ano_escolar="1ª Fase", ano_letivo=2026,
              status="ativa", turno="tarde"),
    ]
    db.add_all(turmas)
    db.flush()
    k = 0
    for turma in turmas:
        for _ in range(4):
            k += 1
            aluno = Aluno(escola_id=escola.id, nome=f"Crianca Ficticia {k:02d}",
                          status="ativo")
            db.add(aluno)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                             ano_letivo=2026))
            # Uma criança por turma parou há mais de um mês: o pacote tem alertas.
            parada = k % 4 == 0
            for dias, fator in (((60, 1), (45, 2)) if parada else ((20, 1), (2, 2))):
                quando = agora - timedelta(days=dias)
                db.add(SnapshotElefante(
                    escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                    data_referencia=quando, livros_unicos=(k % 4 + 1) * fator,
                    tempo_leitura_min=10 * fator, questoes_tentativas=4 * fator,
                    questoes_acertos=2 * fator, livros_por_nivel={"D": (k % 4 + 1) * fator}))
                db.add(SnapshotMatific(
                    escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                    data_referencia=quando, atividades=(k % 5 + 1) * fator,
                    estrelas=2 * (k % 5 + 1) * fator, pontuacao_media=2.0))
            db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id,
                           livro_id=livros[k % 3].id,
                           data=agora - timedelta(days=50 if parada else 1),
                           tempo_leitura_min=15, nivel_codigo="D"))
    for email, cargo in (("coord@consultas.local", "coordenador"),
                         ("prof@consultas.local", "professor")):
        db.add(Usuario(escola_id=escola.id, nome=f"Usuaria {cargo}", email=email,
                       senha_hash=hash_senha(SENHA), cargo=cargo))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return {"escola": escola, "rede": rede,
            "coordenacao": _login("coord@consultas.local"),
            "professora": _login("prof@consultas.local")}


class Idas:
    """Conta as idas ao banco e as repetições EXATAS (mesmo SQL, mesmos parâmetros)."""

    def __init__(self, engine):
        self.engine, self.comandos = engine, []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._antes)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._antes)

    def _antes(self, _conn, _cursor, comando, parametros, *_a):
        self.comandos.append((" ".join(comando.split()), repr(parametros)))

    @property
    def total(self) -> int:
        return len(self.comandos)

    @property
    def repeticoes(self) -> int:
        return self.total - len(set(self.comandos))

    def resumo(self) -> str:
        repetidas = [(n, sql[:110]) for (sql, _p), n in
                     collections.Counter(self.comandos).most_common() if n > 1]
        return (f"{self.total} idas, {self.repeticoes} repetições exatas: "
                + "; ".join(f"{n}x {sql}" for n, sql in repetidas[:8]))


def _medir(db, cliente: TestClient, rota: str) -> Idas:
    with Idas(db.get_bind()) as idas:
        r = cliente.get(f"{API}{rota}")
    assert r.status_code == 200, r.text[:300]
    return idas


# Tetos: a meta de 5 s das telas (§11) a ~0,2 s por ida = 25 idas para a tela principal do
# app. As leituras que sobram são as do próprio conteúdo (séries, leituras por janela,
# notas, conquistas) e as de login/escopo, que já não se repetem.
@pytest.mark.parametrize("perfil,rota,teto", [
    ("coordenacao", "/escolas/{id}/sincronizacao", 25),
    ("professora", "/escolas/{id}/sincronizacao", 25),
    ("coordenacao", "/escolas/{id}/gamificacao/mural", 20),
    ("coordenacao", "/escolas/{id}/ranking-evolucao", 15),
])
def test_tela_principal_cabe_no_teto_de_idas(db, cenario, perfil, rota, teto):
    idas = _medir(db, cenario[perfil], rota.format(id=cenario["escola"].id))
    print(f"\n[{perfil}] {rota}: {idas.resumo()}")
    assert idas.total <= teto, idas.resumo()


@pytest.mark.parametrize("perfil,rota", [
    ("coordenacao", "/escolas/{id}/sincronizacao"),
    ("professora", "/escolas/{id}/sincronizacao"),
    ("coordenacao", "/escolas/{id}/gamificacao/mural"),
    ("coordenacao", "/escolas/{id}/ranking-evolucao"),
    ("coordenacao", "/escolas/{id}/dashboard"),
])
def test_nenhuma_leitura_do_motor_se_repete(db, cenario, perfil, rota):
    """Nenhuma consulta sai duas vezes iguais (mesmo SQL, mesmos parâmetros) na mesma
    requisição: configuração, contrato, turmas que concorrem, coorte, quem tem
    leitura, leituras da janela, ranking. (A ficha da escola fica de fora: quem a relê
    é o login, que não é do motor.)"""
    idas = _medir(db, cenario[perfil], rota.format(id=cenario["escola"].id))
    repetidas = {sql[:120]: n for (sql, _p), n in collections.Counter(idas.comandos).items()
                 if n > 1 and "FROM escolas" not in sql}
    assert not repetidas, repetidas


def test_insights_le_configuracao_e_contrato_uma_vez_por_servico(db, cenario):
    """O /insights (rota da frente do assistente) chama os índices e os alertas: cada
    serviço lê configuração, contrato e elenco uma vez só."""
    escola_id = cenario["escola"].id
    idas = _medir(db, cenario["coordenacao"], f"/escolas/{escola_id}/insights")
    print(f"\n[coordenacao] /insights: {idas.resumo()}")
    configuracoes = collections.Counter(
        (sql, p) for sql, p in idas.comandos if "FROM configuracoes" in sql)
    # Os índices e os alertas são dois serviços chamados em separado pela rota: no
    # máximo uma leitura de cada configuração por serviço (eram 17 do perfil).
    assert max(configuracoes.values(), default=0) <= 2, idas.resumo()
    assert idas.total <= 22, idas.resumo()


def test_o_pacote_do_app_e_o_mesmo_com_e_sem_memoria(db, cenario, monkeypatch):
    """A memória só tira idas repetidas: o pacote inteiro (painel, ranking, evolução,
    alertas e mural) sai igual ao montado consultando o banco a cada leitura."""
    cli, escola_id = cenario["coordenacao"], cenario["escola"].id

    def _pacote():
        r = cli.get(f"{API}/escolas/{escola_id}/sincronizacao")
        assert r.status_code == 200, r.text[:300]
        corpo = r.json()
        corpo.pop("gerado_em")
        return corpo

    com_memoria = _pacote()
    monkeypatch.setattr(scoring, "memoria_da_requisicao", lambda *_a, **_k: None)
    sem_memoria = _pacote()
    assert com_memoria == sem_memoria
    assert com_memoria["evolucao"] and com_memoria["ranking"] and com_memoria["alertas"]
    assert com_memoria["dashboard"]["top10"]


# ---------------------------------------------------------------------------
# A memória vale só dentro do bloco e não muda resultado
# ---------------------------------------------------------------------------
def test_memoria_so_vale_dentro_do_bloco(db, cenario):
    """Fora do bloco nada fica velho: a gravação seguinte é lida do banco."""
    escola = cenario["escola"]
    with scoring.leituras_da_requisicao(db):
        assert scoring._scoring_personalizado(db, escola.id) is False
        assert modulos.modulos_da_escola(db, escola) == {"leitura", "matematica"}
        with Idas(db.get_bind()) as idas:
            # Dentro do bloco, a segunda leitura não vai ao banco.
            scoring._scoring_personalizado(db, escola.id)
            modulos.modulos_da_escola(db, escola)
            scoring.pesos_efetivos(db, escola.id, "pesos.geral")
            elegibilidade.turmas_premiaveis(db, escola.id, 2026)
            elegibilidade.turmas_premiaveis(db, escola.id, 2026)
        assert idas.total <= 1, idas.resumo()   # a primeira turmas_premiaveis
    db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.add(ModuloRede(rede_id=cenario["rede"].id, modulo="matematica", ativo=False))
    db.commit()
    assert scoring._scoring_personalizado(db, escola.id) is True
    assert modulos.modulos_da_escola(db, escola) == {"leitura"}


def test_bloco_aninhado_nao_desliga_a_memoria_de_quem_abriu(db, cenario):
    escola = cenario["escola"]
    with scoring.leituras_da_requisicao(db):
        with scoring.leituras_da_requisicao(db):
            modulos.modulos_da_escola(db, escola)
        with Idas(db.get_bind()) as idas:
            modulos.modulos_da_escola(db, escola)
        assert idas.total == 0, idas.resumo()


def test_ranking_de_evolucao_e_o_mesmo_com_e_sem_memoria(db, cenario):
    escola_id = cenario["escola"].id

    def _retrato():
        return [(i.aluno_id, i.posicao, i.nota_evolucao, i.notas, i.aferido)
                for i in evolucao.ranking_evolucao(db, escola_id, dias=30,
                                                   base_no_periodo=True)]

    sem = _retrato()
    with scoring.leituras_da_requisicao(db):
        com = [_retrato(), _retrato()]
    assert com == [sem, sem]
    assert sem, "o cenário tem de produzir itens"
