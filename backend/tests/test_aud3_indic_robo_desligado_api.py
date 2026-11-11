"""A API das fontes do robô de avaliações diz se o robô está ligado (auditoria
S_G_INDICADORES-5). O robô AUTOMÁTICO fica desligado por padrão
(``AVALIACOES_ROBO_HABILITADO``, decisão registrada) e a fonte mensal não é coletada
sozinha; a tela prometia "O robô passa a baixar e importar sozinho" e mostrava "próxima:
<data>" sem ter como saber disso. Agora cada fonte, na lista e na resposta do cadastro,
traz ``robo_habilitado``. Nada aqui liga o robô de verdade. Dados fictícios."""
from app.core.config import settings
from app.services import avaliacoes as svc

CORPO = {"avaliacao": "ideb", "nome": "IDEB inventado 2023",
         "url": "https://exemplo.invalido/ideb.csv", "edicao": 2023, "indicador": "ideb",
         "unidade": "indice", "cadencia": "mensal",
         "mapeamento": {"linha_dados": 1, "col_inep": 0, "col_valor": 1}}


def test_com_o_padrao_a_api_diz_que_o_robo_esta_desligado(db, cliente_global):
    assert svc.robo_habilitado() is False
    criada = cliente_global.post("/api/v1/avaliacoes/fontes", json=CORPO)
    assert criada.status_code == 201, criada.text
    assert criada.json()["robo_habilitado"] is False
    lista = cliente_global.get("/api/v1/avaliacoes/fontes").json()
    assert [f["robo_habilitado"] for f in lista] == [False]
    # E, de fato, a fonte mensal vencida não é coletada com o robô desligado.
    assert svc.coletar_pendentes(db, baixador=lambda _url: b"") == 0


def test_com_o_robo_ligado_a_api_diz_que_esta_ligado(db, cliente_global, monkeypatch):
    monkeypatch.setattr(settings, "AVALIACOES_ROBO_HABILITADO", "true")
    cliente_global.post("/api/v1/avaliacoes/fontes", json=CORPO)
    lista = cliente_global.get("/api/v1/avaliacoes/fontes").json()
    assert [f["robo_habilitado"] for f in lista] == [True]
