"""Placar AO VIVO: a linha cuja conta é a identidade efetiva de um aluno de OUTRA
escola fica SEM link, como na sincronização — 2ª revisão de integração do e97
(identidade-sync, prova 4, teste 1 invertido).

``_FichasDaEscola.aluno_da_linha`` só conhecia as contas DESTA escola: a conta
efetiva noutra escola era "desconhecida" e caía no NOME, ganhando o link do
homônimo daqui. A sincronização, com a mesma linha, manda a conta para a revisão
``identidade_de_outra_escola`` (``decidir``, passo 0d) e nunca a liga pelo nome. O
link decide o recorte do professor (``/matific/placar-ao-vivo`` filtra por
``aluno_id``) e é a base do "premiar por período". Agora ``_fichas_da_escola``
soma às contas conhecidas as de ``efetivas_em_outra_escola`` (uma consulta por
placar).

Dados 100% fictícios (nomes de escola e de criança inventados); sem rede (a coleta
é substituída).
"""
from datetime import datetime

import pytest

from app.models import Aluno, Escola, IdentidadeExterna, Matricula, Turma
from app.services import identidade_aluno as ida
from app.sync import aovivo, connectors, vault
from app.sync.interfaces import Credenciais

K = "3 ANO A TARDE (300000001)"


@pytest.fixture(autouse=True)
def _limpar_cache():
    aovivo._cache.clear()
    yield
    aovivo._cache.clear()


def _linha(nome, uuid, estrelas=10):
    return {"nome": nome, "nome_abrev": nome, "uuid": uuid, "turma": K, "serie": "3",
            "estrelas": estrelas, "atividades": 5}


def _escola_b(db, nomes):
    """Escola B com um aluno por nome, cada um com a sua conta efetiva."""
    b = Escola(nome="ESCOLA FICTICIA B DO PLACAR", ano_letivo_ativo=2026)
    db.add(b)
    db.flush()
    t = Turma(escola_id=b.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(t)
    db.flush()
    contas = []
    for i, nome in enumerate(nomes):
        al = Aluno(escola_id=b.id, nome=nome)
        db.add(al)
        db.flush()
        db.add(Matricula(escola_id=b.id, aluno_id=al.id, turma_id=t.id, ano_letivo=2026))
        conta = f"u-ficticia-placar-b{i}"
        db.add(IdentidadeExterna(escola_id=b.id, aluno_id=al.id, plataforma="matific",
                                 id_externo=conta))
        contas.append(conta)
    db.commit()
    return b, contas


def _placar(db, escola_id, linhas, monkeypatch):
    class _Conector:  # placar_matific confere que o conector tem coletar_via_http
        def coletar_via_http(self, *a, **k):  # pragma: no cover - substituído
            raise AssertionError("substituído")

    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _Conector() if plat == "matific" else None)
    monkeypatch.setattr(aovivo, "_coletar_http_first",
                        lambda *a, **k: ([dict(x) for x in linhas], None))
    vault.salvar_credencial(db, escola_id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    return aovivo.placar_matific(db, escola_id, periodo="mes", inicio=None, fim=None,
                                 agora=datetime(2026, 9, 10, 12, 0, 0))


def test_conta_de_outra_escola_nao_ganha_o_link_do_homonimo_daqui(db, escola_completa):
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]                     # homônimo ATIVO em A, sem conta
    _b, (u,) = _escola_b(db, [a.nome])
    linha = _linha(a.nome, u)
    fichas = aovivo._fichas_da_escola(db, eid, 2026, uuids=[u])
    [item] = aovivo._montar_ranking([linha], fichas)
    assert item["aluno_id"] is None

    # Coerente com a sincronização: a mesma linha vai para a revisão própria.
    ctx = ida.carregar_contexto(db, eid, 2026)

    class _L:
        nome = a.nome
        dados = {"matific_uuid": u, "turma_relatorio": K}
    ida.marcar_ids_de_outra_escola(db, ctx, [_L()], "matific")
    dec = ida.decidir(ctx, ida.linha_de_dados(a.nome, _L.dados, plataforma="matific",
                                              turma_nome=K))
    assert (dec.acao, dec.motivo) == (ida.REVISAR, "identidade_de_outra_escola")


def test_placar_ponta_a_ponta_nao_liga_pelo_nome_a_conta_de_outra_escola(
        db, escola_completa, monkeypatch):
    """Pela entrada única do serviço (a do router do premiar por período): a linha
    da criança de B fica sem link; a conta desconhecida continua caindo no nome."""
    escola = escola_completa["escola"]
    a, outro = escola_completa["alunos"][0], escola_completa["alunos"][1]
    _b, (u,) = _escola_b(db, [a.nome])
    r = _placar(db, escola.id, [_linha(a.nome, u, estrelas=50),
                                _linha(outro.nome, "u-ficticia-desconhecida", estrelas=5)],
                monkeypatch)
    por_nome = {i["nome"]: i["aluno_id"] for i in r["itens"]}
    assert por_nome[a.nome] is None
    assert por_nome[outro.nome] == outro.id                  # reserva pelo nome intacta
    assert r["com_link"] == 1


def test_conta_que_tambem_vale_aqui_continua_ligando_pela_conta(db, escola_completa):
    """A conta vinculada a uma ficha ativa DESTA escola segue pela regra 1 (a conta
    casa antes do nome), mesmo que também seja efetiva noutra escola."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _b, (u,) = _escola_b(db, ["Crianca Ficticia Do Placar B"])
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="matific",
                             id_externo=u))
    db.commit()
    fichas = aovivo._fichas_da_escola(db, eid, 2026, uuids=[u])
    [item] = aovivo._montar_ranking([_linha("ANA B S", u)], fichas)
    assert item["aluno_id"] == a.id


def test_uma_consulta_da_regra_unica_por_placar(db, escola_completa, monkeypatch):
    """A conferência é feita UMA vez por placar, com todas as contas das linhas —
    não por linha."""
    escola = escola_completa["escola"]
    nomes = ["Crianca Ficticia Placar Um", "Crianca Ficticia Placar Dois",
             "Crianca Ficticia Placar Tres"]
    _b, contas = _escola_b(db, nomes)
    chamadas = []
    original = ida.efetivas_em_outra_escola

    def _contando(db_, escola_id, plataforma, ids):
        chamadas.append((escola_id, plataforma, sorted(ids)))
        return original(db_, escola_id, plataforma, ids)

    monkeypatch.setattr(ida, "efetivas_em_outra_escola", _contando)
    r = _placar(db, escola.id, [_linha(n, c) for n, c in zip(nomes, contas)], monkeypatch)
    assert [i["aluno_id"] for i in r["itens"]] == [None, None, None]
    assert chamadas == [(escola.id, "matific", sorted(contas))]
