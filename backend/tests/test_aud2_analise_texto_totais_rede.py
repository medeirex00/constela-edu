"""G_GRUPO-3 (auditoria, fase C): o aviso dos totais da rede diz exatamente o que fica de
fora quando uma escola tem a matéria escondida pelo grupo pequeno.

O texto (``grupo_pequeno.TEXTO_FORA_DOS_TOTAIS_DA_REDE``, o mesmo da API, da tela e do
boletim em PDF) dizia que essas escolas "ficam fora dos totais e das médias da rede nessa
matéria". Mas as CONTAGENS continuam no cartão de propósito (alunos com dados, ativos de cada
plataforma, adoção) e a rede as soma: "Alunos com dados: 24" incluía a criança da escola
escondida, logo acima de um aviso dizendo que ela estava fora. Agora o texto diz o que sai
(livros, tempo de leitura, atividades, estrelas e as médias) e o que continua (as contagens de
alunos com dados e a adoção).

Dados INVENTADOS. Nenhuma rede externa.
"""
import pytest

from app.models import Rede
from app.services import grupo_pequeno
from tests.test_grupo_pequeno_escola_secretaria import API, _escola, _usuarios


@pytest.fixture()
def rede_com_escola_escondida(db):
    rede = Rede(nome="REDE FICTÍCIA DO AVISO", status="ativa")
    db.add(rede)
    db.flush()
    escolas = {
        "pequena": _escola(db, rede.id, "Escola Fictícia Pequena", concorrem=1, livros_cada=9,
                           nota=80.0, inep="35000011"),
        "media": _escola(db, rede.id, "Escola Fictícia Média", concorrem=4, livros_cada=5,
                         nota=60.0, inep="35000012"),
        "grande": _escola(db, rede.id, "Escola Fictícia Grande", concorrem=6, livros_cada=3,
                          nota=50.0, inep="35000013"),
    }
    db.commit()
    return {"rede": rede, **escolas, **_usuarios(db, rede.id, sufixo=".aviso")}


def test_aviso_dos_totais_diz_que_as_contagens_continuam(rede_com_escola_escondida):
    cen = rede_com_escola_escondida
    r = cen["sec"].get(f"{API}/redes/{cen['rede'].id}/dashboard")
    assert r.status_code == 200, r.text
    painel = r.json()
    cartoes = {c["nome"]: c for c in painel["escolas"]}
    pequena = cartoes["Escola Fictícia Pequena"]
    assert pequena["livros"] is None and pequena["oculto"]["leitura"] is not None
    totais = painel["totais"]
    # O que o texto diz que fica de fora, fica: os livros somam só as escolas visíveis...
    visiveis = [c for c in cartoes.values() if c["livros"] is not None]
    assert totais["livros"] == sum(c["livros"] for c in visiveis)
    # ...e o que ele diz que continua, continua: as contagens somam TODAS as escolas.
    assert totais["ativos_elefante"] == sum(c["ativos_elefante"] for c in cartoes.values())
    assert totais["alunos_com_dados"] == sum(c["alunos_com_dados"] for c in cartoes.values())
    assert pequena["ativos_elefante"] == 1
    texto = totais["grupo_pequeno"]["texto"]
    assert texto == grupo_pequeno.TEXTO_FORA_DOS_TOTAIS_DA_REDE
    # O texto não afirma mais que a escola fica fora de TODOS os totais da matéria...
    assert "ficam fora dos totais e das médias" not in texto
    # ...diz quais números saem e que as contagens de alunos com dados continuam com ela.
    for palavra in ("livros", "tempo", "atividades", "estrelas", "médias"):
        assert palavra in texto, palavra
    assert "alunos com dados" in texto and "continuam" in texto
