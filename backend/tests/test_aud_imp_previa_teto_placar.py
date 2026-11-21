"""O teto de linhas da prévia vale também para o Placar do Matific em JSON.

REV-IMP-4 (sobre UPLOADS-3): o teto ``LINHAS_MAXIMAS_TEXTO`` (20.000) ficava em
``_analisar_texto_com_teto``, que só envolve ``svc.analisar_texto``. O Placar do
Matific enviado como arquivo .json (até 10 MB, tipo "texto") ia por
``_payload_matific_placar`` → ``analisar_matific_api`` → ``casar_nomes`` sem teto
nenhum: ~17 ms por nome distinto novo com 600 ativos, e um .json de 10 MB (~100 mil
contas) prendia uma thread e a conexão por dezenas de minutos. Agora o Placar acima
do teto é recusado (413, a mesma mensagem do texto) antes da análise e do casamento.
Dados fictícios.
"""
import json

from app.services import importacao as svc

API = "/api/v1"


def _placar(n: int) -> bytes:
    return json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
        {"nome": f"Aluno Ficticio {i:05d} Souza", "uuid": f"uuid-fict-{i:05d}",
         "estrelas": 1, "atividades": 1} for i in range(n)]}).encode("utf-8")


def _enviar(cliente, escola_id, conteudo: bytes):
    return cliente.post(f"{API}/escolas/{escola_id}/importacoes/analisar",
                        files={"arquivo": ("placar.json", conteudo, "application/json")})


def test_placar_em_json_acima_do_teto_e_recusado_antes_de_analisar(cliente,
                                                                  escola_completa,
                                                                  monkeypatch):
    chamado = []
    original = svc.analisar_matific_api

    def analisar(*args, **kwargs):
        chamado.append("analisar_matific_api")
        return original(*args, **kwargs)

    monkeypatch.setattr(svc, "analisar_matific_api", analisar)
    monkeypatch.setattr(svc, "casar_nomes", lambda *a, **k: chamado.append("casar_nomes"))
    r = _enviar(cliente, escola_completa["escola"].id, _placar(20_001))
    assert r.status_code == 413, r.text[:300]
    assert r.json()["detail"] == ("O relatório tem mais de 20.000 linhas. Envie em "
                                  "partes (por exemplo, uma turma por vez).")
    assert chamado == []


def test_placar_em_json_no_teto_continua_aceito(cliente, escola_completa, monkeypatch):
    # O casamento das 20.000 contas novas não é o que se mede aqui.
    monkeypatch.setattr(svc, "casar_nomes", lambda *a, **k: None)
    r = _enviar(cliente, escola_completa["escola"].id, _placar(20_000))
    assert r.status_code == 200, r.text[:300]
    assert r.json()["total_linhas"] == 20_000


def test_placar_normal_continua_aceito(cliente, escola_completa):
    r = _enviar(cliente, escola_completa["escola"].id, _placar(3))
    assert r.status_code == 200, r.text[:300]
    corpo = r.json()
    assert (corpo["plataforma"], corpo["tipo"], corpo["total_linhas"]) == ("matific",
                                                                         "texto", 3)
