"""G_GRUPO-1 (auditoria, fase C): a SECRETARIA não lê a régua de normalização de uma
escola (``GET /escolas/{id}/configuracoes/referencias``).

Os ``valores_em_uso`` da régua são o MÁXIMO de cada indicador entre as crianças da escola
(menos de ``scoring.MIN_ALUNOS_ROBUSTO`` crianças com dado) ou o P90 delas — que, com 11,
21, 31… crianças, é exatamente o número de UMA criança. Na escola de 1 criança, a rota
devolvia todos os números dela, os mesmos que o cartão da rede (``/redes/{id}/dashboard``)
esconde pela regra do grupo pequeno. A Secretaria não edita a régua e nenhuma tela dela
chama a rota (a web só desenha as referências para o Admin Global): a rota passa a negar a
Secretaria. A gestão da escola e o Admin Global seguem lendo como antes.

Dados INVENTADOS. Nenhuma rede externa.
"""
from datetime import datetime

from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Importacao, SnapshotElefante, SnapshotMatific, Usuario
from app.services import scoring
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

API = "/api/v1"
# Os números da ÚNICA criança da escola de 1 (canários: nenhum outro número do mundo
# coincide com eles).
CRIANCA_UNICA = {"max_livros": 37, "max_tempo": 1913, "max_tentativas": 61,
                 "max_acertos": 53, "max_atividades": 733, "max_estrelas": 2419,
                 "max_media": 3.37}


def _imp(db, escola, plataforma):
    imp = Importacao(escola_id=escola.id, plataforma=plataforma, tipo="seed",
                     status="concluida", qtd_alunos=0, qtd_erros=0, tempo_ms=0)
    db.add(imp)
    db.flush()
    return imp


def _retratos(db, escola, aluno, *, livros, tempo, tent, acer, ativ, estr, pmedia):
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=_imp(db, escola, "elefante").id,
                            data_referencia=datetime(2026, 10, 1, 3, 10), livros_unicos=livros,
                            tempo_leitura_min=tempo, questoes_tentativas=tent,
                            questoes_acertos=acer, livros_por_nivel={"K": livros}))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=_imp(db, escola, "matific").id,
                           data_referencia=datetime(2026, 10, 1, 3, 20), atividades=ativ,
                           estrelas=estr, pontuacao_media=pmedia))
    db.flush()


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _mundo(db):
    rede = nova_rede(db, nome="Rede Fictícia da Régua", codigo="3599955", codmun="9955")
    uma = nova_escola(db, rede, "EMEF Fictícia Uma", "35995501")
    cinco = nova_escola(db, rede, "EMEF Fictícia Cinco", "35995502")
    onze = nova_escola(db, rede, "EMEF Fictícia Onze", "35995503")
    [so] = turma_com_alunos(db, uma, "3º Ano", 1)
    _retratos(db, uma, so, livros=37, tempo=1913, tent=61, acer=53, ativ=733, estr=2419,
              pmedia=3.37)
    # Escola de 5: o cartão é visível; a criança do topo leu 23 livros.
    for i, a in enumerate(turma_com_alunos(db, cinco, "4º Ano", 5)):
        _retratos(db, cinco, a, livros=[4, 6, 9, 11, 23][i], tempo=50 + i, tent=10, acer=5,
                  ativ=20 + i, estr=40 + i, pmedia=2.0)
    # Escola de 11 (régua robusta, P90): (11-1)*0,9 = 9 -> o 10º valor ordenado EXATO (31).
    for i, a in enumerate(turma_com_alunos(db, onze, "5º Ano", 11)):
        _retratos(db, onze, a, livros=[2, 3, 5, 7, 8, 12, 13, 15, 16, 31, 40][i],
                  tempo=60 + i, tent=10, acer=5, ativ=30 + i, estr=70 + i, pmedia=2.5)
    db.commit()
    for e in (uma, cinco, onze):
        scoring.recalcular_escola(db, e.id)
    return rede, uma, cinco, onze


def test_secretaria_nao_le_os_numeros_da_crianca_na_regua(db, escola_completa):
    rede, uma, cinco, onze = _mundo(db)
    # Secretaria (cargo coordenador + rede) e a conta PROMOVIDA a Secretaria (cargo admin,
    # guarda o escola_id de origem).
    db.add(Usuario(escola_id=None, nome="Secretaria Fictícia", email="sec.regua@ficticio.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.add(Usuario(escola_id=uma.id, nome="Secretaria Promovida", email="prom.regua@ficticio.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin", rede_id=rede.id))
    db.commit()
    for email in ("sec.regua@ficticio.local", "prom.regua@ficticio.local"):
        sec = _login(email)
        # O cartão da rede esconde a criança da escola de 1 (grupo pequeno)...
        painel = sec.get(f"{API}/redes/{rede.id}/dashboard").json()
        cartao = {c["escola_id"]: c for c in painel["escolas"]}[uma.id]
        assert cartao["livros"] is None and cartao["grupo_pequeno"] is True
        # ...e a régua também não entrega os números dela (nem o topo da de 5, nem o
        # P90 = criança exata da de 11).
        for escola in (uma, cinco, onze):
            r = sec.get(f"{API}/escolas/{escola.id}/configuracoes/referencias")
            assert r.status_code == 403, (email, escola.nome, r.status_code, r.text)
            corpo = r.text
            for valor in ("1913", "2419", "733", "3.37"):
                assert valor not in corpo, (email, escola.nome, corpo)
            assert "valores_em_uso" not in corpo


def test_gestao_da_escola_e_admin_global_seguem_lendo_a_regua(db, escola_completa,
                                                              cliente_global):
    rede, uma, cinco, onze = _mundo(db)
    # Coordenador DA escola (sem rede): vê as crianças da própria escola, vê a régua.
    db.add(Usuario(escola_id=uma.id, nome="Coordenação Fictícia", email="coord.uma@ficticio.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.add(Usuario(escola_id=cinco.id, nome="Direção Fictícia", email="admin.cinco@ficticio.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin"))
    db.commit()
    coord = _login("coord.uma@ficticio.local")
    r = coord.get(f"{API}/escolas/{uma.id}/configuracoes/referencias")
    assert r.status_code == 200, r.text
    em_uso = r.json()["valores_em_uso"]
    assert {k: em_uso[k] for k in CRIANCA_UNICA} == CRIANCA_UNICA

    admin = _login("admin.cinco@ficticio.local")
    r = admin.get(f"{API}/escolas/{cinco.id}/configuracoes/referencias")
    assert r.status_code == 200 and r.json()["valores_em_uso"]["max_livros"] == 23

    r = cliente_global.get(f"{API}/escolas/{onze.id}/configuracoes/referencias")
    assert r.status_code == 200 and r.json()["valores_em_uso"]["max_livros"] == 31
