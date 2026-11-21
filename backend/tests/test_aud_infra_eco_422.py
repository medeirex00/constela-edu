"""O 422 de validação não devolve o que o cliente mandou quando o valor é um contêiner.

O tratador global (``main._erro_de_validacao``) tirava do erro o ``input`` só quando era
bytes ou texto longo. Uma LISTA ou um DICT voltavam inteiros — no erro "campo ausente"
o ``input`` é o CORPO INTEIRO — e eram codificados (``jsonable_encoder``) e serializados
dentro do event loop: um anônimo com 30 MB de lista parava o worker por segundos
(auditoria, achado API_SEGURANCA-1). Agora só fica o ``input`` escalar curto, e a
resposta leva no máximo ``_ERROS_MAXIMOS_NO_422`` erros. Dados fictícios.
"""
import asyncio
import json

from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.main import app

API = "/api/v1"


def test_lista_longa_num_campo_de_texto_nao_volta_no_422(db):
    marca = "ECO-ANINHADO-" * 50                       # 650 caracteres por item
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": "abcdefghij", "nova_senha": [marca] * 200})
    assert r.status_code == 422
    assert "ECO-ANINHADO" not in r.text, f"422 devolveu {len(r.content)} bytes com o corpo"
    assert r.json()["detail"]                           # o erro continua explicado


def test_campo_ausente_nao_devolve_o_corpo_inteiro(db):
    """No erro 'missing', o ``input`` do Pydantic é o corpo inteiro (um dict)."""
    marca = "CAMPO-EXTRA-" * 100
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": "abcdefghij", "lixo": marca})
    assert r.status_code == 422
    assert "CAMPO-EXTRA" not in r.text, f"422 devolveu {len(r.content)} bytes com o corpo"
    erro = r.json()["detail"][0]
    assert erro["type"] == "missing" and erro["loc"] == ["body", "nova_senha"]


def test_rota_anonima_do_quest_nao_ecoa_a_lista(db):
    marca = "ECO-QUEST-" * 30
    r = TestClient(app).post(f"{API}/quest/auth/quem", json={"codigo": [marca] * 100})
    assert r.status_code == 422
    assert "ECO-QUEST" not in r.text, f"422 devolveu {len(r.content)} bytes com o corpo"


def test_lista_enorme_gera_resposta_pequena(db):
    """O tamanho da resposta não acompanha o do corpo enviado."""
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": "abcdefghij", "nova_senha": ["x"] * 200_000})
    assert r.status_code == 422
    assert len(r.content) < 2_000, f"422 de {len(r.content)} bytes"


def test_valor_escalar_curto_continua_no_erro(cliente, escola_completa):
    """O ``input`` curto e escalar ainda ajuda a entender o erro (ex.: número no lugar de
    texto). Num campo que não é segredo: o de senha, código ou token não devolve nem o
    valor curto (REG_SEGURANCA-4, test_aud3_seg_422_sem_segredo.py)."""
    admin = escola_completa["admin"]
    r = cliente.patch(f"{API}/escolas/{escola_completa['escola'].id}/usuarios/{admin.id}",
                      json={"nome": 1})
    assert r.status_code == 422
    por_campo = {tuple(e["loc"]): e for e in r.json()["detail"]}
    assert por_campo[("body", "nome")]["input"] == 1


def _responder(erros: list[dict]) -> dict:
    pedido = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
    resposta = asyncio.run(main._erro_de_validacao(pedido, RequestValidationError(erros)))
    assert resposta.status_code == 422
    return json.loads(resposta.body)


def test_input_so_fica_quando_e_escalar_curto():
    erros = [
        {"type": "t", "loc": ("body", "a"), "msg": "m", "input": None},
        {"type": "t", "loc": ("body", "b"), "msg": "m", "input": True},
        {"type": "t", "loc": ("body", "c"), "msg": "m", "input": 7},
        {"type": "t", "loc": ("body", "d"), "msg": "m", "input": 1.5},
        {"type": "t", "loc": ("body", "e"), "msg": "m", "input": "curto"},
        {"type": "t", "loc": ("body", "f"), "msg": "m", "input": "x" * 257},
        {"type": "t", "loc": ("body", "g"), "msg": "m", "input": b"bytes"},
        {"type": "t", "loc": ("body", "h"), "msg": "m", "input": ["lista"]},
        {"type": "t", "loc": ("body", "i"), "msg": "m", "input": ("tupla",)},
        {"type": "t", "loc": ("body", "j"), "msg": "m", "input": {"dict": 1}},
        {"type": "t", "loc": ("body", "k"), "msg": "m", "input": {"conjunto"}},
    ]
    detalhe = _responder(erros)["detail"]
    com_input = {e["loc"][1]: e["input"] for e in detalhe if "input" in e}
    assert com_input == {"a": None, "b": True, "c": 7, "d": 1.5, "e": "curto"}
    assert len(detalhe) == len(erros)                   # nenhum erro some


def test_quantidade_de_erros_tem_teto():
    """Uma lista de 100 mil itens inválidos gera 100 mil erros no Pydantic: a resposta
    leva só os primeiros (cada tela mostra as mensagens, sem repetir)."""
    erros = [{"type": "int_parsing", "loc": ("body", "ids", i), "msg": "m", "input": "x"}
             for i in range(100_000)]
    detalhe = _responder(erros)["detail"]
    assert len(detalhe) == main._ERROS_MAXIMOS_NO_422
    assert [e["loc"][2] for e in detalhe] == list(range(main._ERROS_MAXIMOS_NO_422))


def test_numero_nao_finito_no_lugar_de_texto_e_422_e_nao_500(db):
    """O JSON do Python aceita NaN/Infinity; a resposta JSON do Starlette os recusa
    (``allow_nan=False``). Com o ``input`` NaN no erro, montar o 422 virava um 500."""
    for literal in ("NaN", "Infinity", "-Infinity"):
        r = TestClient(app, raise_server_exceptions=False).post(
            f"{API}/auth/redefinir-senha",
            content=f'{{"token": {literal}, "nova_senha": "x"}}',
            headers={"content-type": "application/json"})
        assert r.status_code == 422, f"{literal}: {r.status_code} {r.text[:120]}"


# --- REV-INFRA-3: o eco pelo ``loc`` -------------------------------------------------------
# Num campo dict[str, ...] com valor inválido, a CHAVE que o cliente mandou entra no ``loc``
# do erro. Sem teto, uma chave de 500 mil caracteres voltava inteira no 422 (e uma de 30 MB,
# 31,5 MB de resposta). Só as rotas com login têm campo assim (AlunoCreate.ficha,
# PesosUpdate.valores, valores_manuais, nome_ficha_nova_por_turma).


def test_chave_longa_de_dict_nao_volta_inteira_pelo_loc(cliente, escola_completa):
    chave = "CHAVE-ECO-" * 50_000                       # 500 mil caracteres
    r = cliente.post(f"{API}/escolas/{escola_completa['escola'].id}/alunos",
                     json={"nome": "Aluno Ficticio", "turma_id": escola_completa["turma"].id,
                           "ficha": {chave: 1}})
    assert r.status_code == 422, r.text[:200]
    assert len(r.content) < 2_000, f"422 de {len(r.content)} bytes ecoa a chave pelo loc"
    assert chave not in r.text
    erro = r.json()["detail"][0]
    # Continua dizendo ONDE está o erro: o campo e o começo da chave.
    assert erro["loc"][:2] == ["body", "ficha"]
    assert erro["loc"][2] == chave[:main._LOC_MAXIMO_NO_422] + "…"


def test_loc_encurta_so_o_texto_longo():
    longo = "K" * 100_000
    no_limite = "c" * main._LOC_MAXIMO_NO_422
    detalhe = _responder([
        {"type": "t", "loc": ("body", "ficha", longo), "msg": "m", "input": 1},
        {"type": "t", "loc": ("body", "ids", 3), "msg": "m", "input": "x"},
        {"type": "t", "loc": ("body", "valores", no_limite), "msg": "m", "input": "x"},
    ])["detail"]
    assert [e["loc"] for e in detalhe] == [
        ["body", "ficha", "K" * main._LOC_MAXIMO_NO_422 + "…"],
        ["body", "ids", 3],
        ["body", "valores", no_limite],
    ]


def test_mensagem_do_validador_nao_ecoa_a_chave_longa(cliente_global, escola_completa):
    """Os validadores de PesosUpdate.valores e ReferenciasUpdate.valores_manuais citam as
    chaves inválidas na mensagem (o ``msg``): a chave enviada voltava inteira por ali."""
    chave = "CHAVE-MSG-" * 50_000                       # 500 mil caracteres
    r = cliente_global.put(
        f"{API}/escolas/{escola_completa['escola'].id}/configuracoes/referencias",
        json={"modo": "manual", "valores_manuais": {chave: -1}})
    assert r.status_code == 422, r.text[:200]
    assert len(r.content) < 2_000, f"422 de {len(r.content)} bytes ecoa a chave pelo msg"
    assert chave not in r.text
    # A mensagem continua explicando o erro.
    assert r.json()["detail"][0]["msg"].startswith(
        "Value error, Valor de referência manual não pode ser negativo")


def test_mensagem_curta_fica_inteira(cliente_global, escola_completa):
    r = cliente_global.put(
        f"{API}/escolas/{escola_completa['escola'].id}/configuracoes/referencias",
        json={"modo": "manual", "valores_manuais": {"max_tempo": -1}})
    assert r.status_code == 422, r.text[:200]
    assert r.json()["detail"][0]["msg"].endswith(": max_tempo.")
