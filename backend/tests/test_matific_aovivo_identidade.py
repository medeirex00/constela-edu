"""Placar AO VIVO do Matific: a linha liga à ficha pela CONTA, não pelo nome.

Regressão da auditoria e92 (``test_c10``) e do A2 §3.2: ``aovivo`` ligava cada
linha do Placar à ficha só pelo nome normalizado. Com o nome abreviado do Placar
("ANA BEATRIZ S", quando o student-leaderboard não traz o nome cheio) a linha
ficava sem link mesmo com a conta vinculada; com homônimo na escola, também; e
a conta duplicada que a escola APOSENTOU ganhava o link da criança pelo nome.

A regra agora é a da sincronização: a ``IdentidadeExterna`` EFETIVA desta escola
manda; conta conhecida que não leva a ficha ativa fica sem link; só a conta
desconhecida cai no nome, como reserva — e homônimos continuam sem link.

Dados 100% fictícios; sem rede (a coleta é substituída).
"""
from datetime import datetime

import pytest

from app.models import Aluno, IdentidadeExterna, Matricula
from app.sync import aovivo, connectors, vault
from app.sync.interfaces import Credenciais

K = "3 ANO A TARDE (300000001)"


@pytest.fixture(autouse=True)
def _limpar_cache_resultado():
    aovivo._cache.clear()
    yield
    aovivo._cache.clear()


def _agora():
    return datetime(2026, 9, 10, 12, 0, 0)


def _conta(db, escola_id, aluno_id, uuid, status="efetiva"):
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=aluno_id, plataforma="matific",
                             id_externo=uuid, status=status,
                             aposentada_em=_agora() if status == "aposentada" else None))
    db.commit()


def _linha(nome, uuid, estrelas=10, atividades=5):
    return {"nome": nome, "nome_abrev": nome, "uuid": uuid, "turma": K, "serie": "3",
            "estrelas": estrelas, "atividades": atividades}


def _abreviado(nome):
    partes = nome.split()
    return f"{partes[0]} {partes[1]} {partes[-1][0]}".upper()


def _ranking(db, escola_id, linhas):
    return aovivo._montar_ranking(linhas, aovivo._fichas_da_escola(db, escola_id, 2026))


def _aluno_extra(db, ec, nome, status="ativo"):
    al = Aluno(escola_id=ec["escola"].id, nome=nome, status=status)
    db.add(al)
    db.flush()
    db.add(Matricula(escola_id=ec["escola"].id, aluno_id=al.id, turma_id=ec["turma"].id,
                     ano_letivo=2026))
    db.commit()
    return al


def test_c10_nome_abreviado_liga_pela_conta_vinculada(db, escola_completa):
    """e92 c10 invertido: antes ``aluno_id=None`` com o uuid vinculado."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _conta(db, eid, a.id, "u-a")
    itens = _ranking(db, eid, [_linha(_abreviado(a.nome), "u-a")])
    assert itens[0]["aluno_id"] == a.id


def test_homonimos_ligam_pela_conta_e_sem_conta_ficam_sem_link(db, escola_completa):
    """Duas fichas ativas com o MESMO nome: a linha da conta vinculada abre a ficha
    certa; a linha de conta desconhecida com o mesmo nome continua sem link
    (não dá para desambiguar pelo nome)."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    gemea = _aluno_extra(db, escola_completa, a.nome)
    _conta(db, eid, gemea.id, "u-gemea")
    itens = _ranking(db, eid, [_linha(a.nome, "u-gemea", estrelas=30),
                               _linha(a.nome, "u-desconhecida", estrelas=20)])
    assert [i["aluno_id"] for i in itens] == [gemea.id, None]


def test_conta_aposentada_nao_ganha_o_link_da_crianca_pelo_nome(db, escola_completa):
    """A escola decidiu qual conta vale: a aposentada (mesmo nome da criança) não
    abre a ficha; a efetiva abre."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _conta(db, eid, a.id, "u-efetiva")
    _conta(db, eid, a.id, "u-aposentada", status="aposentada")
    itens = _ranking(db, eid, [_linha(a.nome, "u-aposentada", estrelas=40),
                               _linha(a.nome, "u-efetiva", estrelas=10)])
    assert [i["aluno_id"] for i in itens] == [None, a.id]


def test_conta_aposentada_sozinha_tambem_fica_sem_link(db, escola_completa):
    """Mesmo sem a efetiva no resultado, a conta aposentada não cai no nome."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _conta(db, eid, a.id, "u-aposentada", status="aposentada")
    itens = _ranking(db, eid, [_linha(a.nome, "u-aposentada")])
    assert itens[0]["aluno_id"] is None


def test_conta_desconhecida_nao_liga_a_ficha_que_ja_tem_outra_conta(db, escola_completa):
    """Conta nova com o nome de quem já tem conta efetiva: pode ser outra criança
    (a sincronização manda para 'outra_identidade_na_plataforma') — sem link."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _conta(db, eid, a.id, "u-a")
    itens = _ranking(db, eid, [_linha(a.nome, "u-nova")])
    assert itens[0]["aluno_id"] is None


def test_nome_continua_reserva_para_quem_ainda_nao_tem_conta(db, escola_completa):
    """Sem conta vinculada (1ª coleta da escola), o nome segue ligando — e a
    linha sem uuid também."""
    eid = escola_completa["escola"].id
    b, c = escola_completa["alunos"][1], escola_completa["alunos"][2]
    itens = _ranking(db, eid, [_linha(b.nome, "u-b", estrelas=20), _linha(c.nome, "")])
    assert [i["aluno_id"] for i in itens] == [b.id, c.id]


def test_conta_de_ficha_transferida_fica_sem_link_mesmo_com_homonimo_ativo(
        db, escola_completa):
    """A conta é de uma criança transferida (ficha fora do ranking): a linha não
    abre ficha nenhuma — nem a do homônimo ativo, que é OUTRA criança."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    transferida = _aluno_extra(db, escola_completa, "Crianca Ficticia Transferida",
                               status="transferido")
    _conta(db, eid, transferida.id, "u-transf")
    a.nome = "Crianca Ficticia Transferida"
    db.commit()
    itens = _ranking(db, eid, [_linha("Crianca Ficticia Transferida", "u-transf")])
    assert itens[0]["aluno_id"] is None


def test_conta_de_ficha_excluida_nao_segura_a_identidade(db, escola_completa):
    """Ficha EXCLUÍDA não segura a conta (regra da sincronização): a linha cai no
    nome, como uma conta desconhecida."""
    eid = escola_completa["escola"].id
    b = escola_completa["alunos"][1]
    excluida = _aluno_extra(db, escola_completa, "Ficha Ficticia Excluida", status="excluido")
    _conta(db, eid, excluida.id, "u-livre")
    itens = _ranking(db, eid, [_linha(b.nome, "u-livre")])
    assert itens[0]["aluno_id"] == b.id


def test_conta_de_outra_escola_nao_e_conhecida_aqui(db, escola_completa):
    """O índice é POR ESCOLA: a conta vinculada a um aluno de outra escola não
    abre a ficha de lá a partir do placar daqui."""
    from app.models import Escola
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    de_la = Aluno(escola_id=outra.id, nome="Crianca De La Ficticia")
    db.add(de_la)
    db.flush()
    _conta(db, outra.id, de_la.id, "u-de-la")
    eid = escola_completa["escola"].id
    itens = _ranking(db, eid, [_linha("Crianca De La Ficticia", "u-de-la")])
    assert itens[0]["aluno_id"] is None


def test_placar_ao_vivo_ponta_a_ponta_liga_pela_conta(db, escola_completa, monkeypatch):
    """Pela entrada única do serviço: o nome abreviado com a conta vinculada ganha
    o link e conta em ``com_link``; o homônimo sem conta não."""
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    _conta(db, escola.id, a.id, "u-a")
    linhas = [_linha(_abreviado(a.nome), "u-a", estrelas=50, atividades=10),
              _linha(a.nome, "u-outra", estrelas=5, atividades=1)]

    class _Conector:
        def coletar_via_http(self, *a, **k):  # pragma: no cover - substituído abaixo
            raise AssertionError("não deve ser chamado")

    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _Conector() if plat == "matific" else None)
    monkeypatch.setattr(aovivo, "_coletar_http_first",
                        lambda *a, **k: ([dict(x) for x in linhas], None))
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()

    r = aovivo.placar_matific(db, escola.id, periodo="mes", inicio=None, fim=None,
                              agora=_agora())
    assert [i["aluno_id"] for i in r["itens"]] == [a.id, None]
    assert r["com_link"] == 1
