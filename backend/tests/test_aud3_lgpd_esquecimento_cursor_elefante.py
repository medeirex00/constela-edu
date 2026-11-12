"""Exclusão permanente (LGPD): o id da conta da criança no Elefante sai também do
cursor da sincronização incremental — e, com ele, do arquivo de backup (S_G_LGPD-2).

O DEFEITO. O cursor do incremental do Elefante fica em ``configuracoes`` (namespace
``sync_incremental``, chave ``elefante``) como ``{studentId: total de livros}``. A
exclusão apagava ``identidades_externas`` mas não tocava no cursor: o número da conta
da criança na plataforma (um pseudônimo, reidentificável por quem tem o painel do
Elefante da escola), com a quantidade de livros, ficava no banco para sempre e saía
em todo backup da escola. O RETENCAO-TECNICA §2.3 promete as identidades externas
apagadas, e o ``test_exclusao_alcance_total`` só procurava o nome e o id da ficha.

Dados 100% fictícios; sem rede (navegador falso do Elefante, conectores reais,
serviço real de sincronização).
"""
import inspect
import json

import pytest
from sqlalchemy import JSON, String, Text, select

from app.core.database import Base
from app.models import Aluno, Configuracao, Escola, IdentidadeExterna, Matricula
from app.services import backup as svc_backup
from app.services import exclusao_aluno
from app.sync import service
from tests._sync_nucleo_fakes import NavElefante, aluno_el, credencial, instalar, livro, rodar
# A coleta roda "agora": num dia de outro ano que o letivo da escola, ela não cria a
# ficha (coleta_fora_do_ano_letivo, S_G_VIRADA-1) e os testes perdiam o objeto.
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"
NOME = "LIVIA FICTICIA ESQUECIDA DO CURSOR"
SID = 7700001
CID = 600002
LIVROS = [livro("Livro Ficticio Cursor Um", data="2026-03-10T10:00:00"),
          livro("Livro Ficticio Cursor Dois", data="2026-04-11T10:00:00"),
          livro("Livro Ficticio Cursor Tres", data="2026-05-12T10:00:00")]


def _turmas(ec):
    a, b, c = ec["alunos"]
    return {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9200001, a.nome, [livro("Livro Ficticio A", data="2026-04-01T10:00:00")]),
        aluno_el(9200002, b.nome, []), aluno_el(9200003, c.nome, []),
        aluno_el(SID, NOME, LIVROS)]}}


def _varrer(db, alvo: str):
    """(tabela, coluna) de TODA coluna de texto/JSON que contém ``alvo``."""
    achados = []
    for tabela in Base.metadata.sorted_tables:
        colunas = [c for c in tabela.columns if isinstance(c.type, (String, Text, JSON))]
        if not colunas:
            continue
        for linha in db.execute(select(*colunas)).all():
            for col, valor in zip(colunas, linha):
                texto = valor if isinstance(valor, str) else json.dumps(
                    valor, ensure_ascii=False, default=str)
                if valor is not None and alvo in texto:
                    achados.append((tabela.name, col.name))
    return achados


def _cursor(db, eid):
    db.expire_all()
    linha = db.execute(select(Configuracao).where(
        Configuracao.escola_id == eid, Configuracao.namespace == service._NS_INCREMENTAL,
        Configuracao.chave == "elefante")).scalar_one_or_none()
    return dict(linha.valor) if linha is not None else None


def test_o_namespace_do_cursor_e_o_da_sincronizacao():
    assert exclusao_aluno.NAMESPACE_CURSOR_DA_SINCRONIZACAO == service._NS_INCREMENTAL


def test_exclusao_tira_o_studentId_do_cursor_e_do_backup(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turmas(ec)))
    rodar(db, eid, "elefante")
    ids = db.execute(select(Aluno.id).where(Aluno.escola_id == eid, Aluno.nome == NOME)
                     ).scalars().all()
    assert len(ids) == 1
    antes = _cursor(db, eid)
    assert antes is not None and str(SID) in antes
    assert ("configuracoes", "valor") in _varrer(db, str(SID))

    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": ids, "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    sobras = _varrer(db, str(SID))
    assert not sobras, (
        f"o id da conta da criança no Elefante ({SID}) sobrevive à exclusão: {sobras}")
    # O cursor das outras crianças fica como estava (o incremental delas segue).
    depois = _cursor(db, eid)
    assert depois == {k: v for k, v in antes.items() if k != str(SID)}
    backup = cliente.get(f"{API}/escolas/{eid}/backup")
    assert backup.status_code == 200, backup.text
    assert str(SID) not in json.dumps(backup.json()["tabelas"]["configuracoes"], default=str)


def test_exclusao_de_turma_com_alunos_tambem_tira_do_cursor(
        db, escola_completa, cliente_global, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turmas(ec)))
    rodar(db, eid, "elefante")
    turma_id = ec["turma"].id
    contas = dict(db.execute(
        select(IdentidadeExterna.aluno_id, IdentidadeExterna.id_externo)
        .join(Matricula, Matricula.aluno_id == IdentidadeExterna.aluno_id)
        .where(Matricula.turma_id == turma_id,
               IdentidadeExterna.plataforma == "elefante")).all())
    assert contas and set(contas.values()) <= set(_cursor(db, eid))
    r = cliente_global.delete(f"{API}/escolas/{eid}/turmas/{turma_id}?com_alunos=true")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert not any(db.get(Aluno, aid) for aid in contas)
    assert not set(_cursor(db, eid) or {}) & set(contas.values())


# ---------------------------------------------------------------------------
# REV3-LGPD-1: a conta esquecida VOLTAVA ao cursor por dois caminhos
# ---------------------------------------------------------------------------
# (1) a coleta seguinte: o Elefante continua mandando a conta (a ficha não volta: a
#     porta de identidade a ignora pela marca), o conector a conta em
#     ``contadores_novos`` e ``_salvar_contadores`` faz MERGE com o cursor gravado;
# (2) a restauração de um backup gerado ANTES da exclusão: o namespace
#     ``sync_incremental`` volta do arquivo (não está em PRESERVADAS_NA_RESTAURACAO).
# A ficha não volta em nenhum dos dois, mas o id da conta da criança voltava ao banco
# e a todo backup seguinte. Tirar a conta só de ``contadores_novos`` não basta: o
# merge mantém o id que a restauração devolveu. O remédio é
# ``exclusao_aluno.tirar_contas_esquecidas_do_cursor``, que lê as marcas de
# esquecimento do log e limpa o cursor JÁ gravado — chamado pela sincronização
# depois de ``_salvar_contadores`` e pela restauração depois de recriar as
# configurações.
_CHAMADA = "tirar_contas_esquecidas_do_cursor"
# As duas chamadas ficam em módulos de outras frentes (sincronização e restauração).
# Enquanto não entram, os testes de ponta a ponta abaixo PRECISAM falhar (xfail
# estrito); quando entram, passam a valer como teste comum.
_SYNC_CHAMA = _CHAMADA in inspect.getsource(service)
_RESTAURACAO_CHAMA = _CHAMADA in inspect.getsource(svc_backup)
_pendente_na_sync = pytest.mark.xfail(
    not _SYNC_CHAMA, strict=True,
    reason="a sincronização (app/sync/service.py, bloco CURSOR) ainda não chama "
           "exclusao_aluno.tirar_contas_esquecidas_do_cursor depois de _salvar_contadores")
_pendente_na_restauracao = pytest.mark.xfail(
    not _RESTAURACAO_CHAMA, strict=True,
    reason="a restauração (services/backup.restaurar) ainda não chama "
           "exclusao_aluno.tirar_contas_esquecidas_do_cursor depois de recriar as "
           "configurações")


def _coletar_e_achar(db, ec, monkeypatch):
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turmas(ec)))
    rodar(db, eid, "elefante")
    [aid] = db.execute(select(Aluno.id).where(Aluno.escola_id == eid, Aluno.nome == NOME)
                       ).scalars().all()
    return eid, aid


def _excluir(cliente_global, eid, aid):
    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": [aid], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _restaurar(cliente_global, eid, conteudo):
    r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                            files={"arquivo": ("backup.json", conteudo, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()


def _ficha_de_volta(db, eid):
    db.expire_all()
    return db.execute(select(Aluno.id).where(Aluno.escola_id == eid, Aluno.nome == NOME)
                      ).scalars().all()


def _linha_da_completa(db, eid):
    db.expire_all()
    linha = db.execute(select(Configuracao).where(
        Configuracao.escola_id == eid, Configuracao.namespace == service._NS_INCREMENTAL,
        Configuracao.chave == "elefante" + service._SUFIXO_COMPLETA)).scalar_one_or_none()
    return dict(linha.valor) if linha is not None else None


def test_cursor_ja_mesclado_pela_coleta_perde_a_conta_esquecida(
        db, escola_completa, cliente_global, monkeypatch):
    """O que a coleta faz depois da exclusão (MERGE da conta no cursor gravado) e o
    que o remédio desfaz: só a conta esquecida sai; as outras ficam com os totais."""
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    antes = _cursor(db, eid)
    _excluir(cliente_global, eid, aid)
    assert str(SID) not in _cursor(db, eid)
    completa = _linha_da_completa(db, eid)
    # A coleta seguinte vê a conta de novo e a MESCLA no cursor (é o que
    # ``_salvar_contadores`` faz com ``contadores_novos``).
    service._salvar_contadores(db, eid, "elefante", {str(SID): len(LIVROS)})
    db.commit()
    assert str(SID) in _cursor(db, eid)

    tiradas = exclusao_aluno.tirar_contas_esquecidas_do_cursor(db, eid)
    db.commit()
    assert tiradas == 1
    assert _cursor(db, eid) == {k: v for k, v in antes.items() if k != str(SID)}
    # A marca da recoleta completa (mesmo namespace) não é conta: fica.
    assert _linha_da_completa(db, eid) == completa
    # Sem conta esquecida no cursor, nada sai.
    assert exclusao_aluno.tirar_contas_esquecidas_do_cursor(db, eid) == 0


def test_cursor_devolvido_pela_restauracao_perde_a_conta_esquecida(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    antes = _cursor(db, eid)
    baixado = cliente.get(f"{API}/escolas/{eid}/backup")
    assert baixado.status_code == 200, baixado.text
    assert str(SID) in json.dumps(baixado.json()["tabelas"]["configuracoes"])
    _excluir(cliente_global, eid, aid)
    _restaurar(cliente_global, eid, baixado.content)
    assert _ficha_de_volta(db, eid) == []

    exclusao_aluno.tirar_contas_esquecidas_do_cursor(db, eid, todas_as_escolas=True)
    db.commit()
    assert _cursor(db, eid) == {k: v for k, v in antes.items() if k != str(SID)}
    assert not _varrer(db, str(SID))


def test_cursor_de_outra_escola_so_perde_a_conta_com_todas_as_escolas(
        db, escola_completa, cliente_global, monkeypatch):
    """O arquivo de uma escola restaurado em OUTRA leva o cursor da primeira, e a marca
    está no log da escola que excluiu. A sincronização confere só as marcas da própria
    escola (a conta pode ser de uma criança que continua estudando na outra); a
    restauração, as de todas (tirar uma conta do cursor nunca perde dado: a coleta
    seguinte só a busca inteira)."""
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    _excluir(cliente_global, eid, aid)
    outra = Escola(nome="ESCOLA FICTICIA DESTINO DO ARQUIVO", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add(Configuracao(escola_id=outra.id, namespace=service._NS_INCREMENTAL,
                        chave="elefante", valor={str(SID): 3, "9300001": 1}))
    db.commit()

    assert exclusao_aluno.tirar_contas_esquecidas_do_cursor(db, outra.id) == 0
    db.commit()
    assert _cursor(db, outra.id) == {str(SID): 3, "9300001": 1}
    assert exclusao_aluno.tirar_contas_esquecidas_do_cursor(
        db, outra.id, todas_as_escolas=True) == 1
    db.commit()
    assert _cursor(db, outra.id) == {"9300001": 1}


@_pendente_na_sync
def test_coleta_seguinte_nao_regrava_a_conta_esquecida_no_cursor(
        db, escola_completa, cliente_global, monkeypatch):
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    _excluir(cliente_global, eid, aid)
    assert str(SID) not in _cursor(db, eid)
    rodar(db, eid, "elefante")
    assert _ficha_de_volta(db, eid) == []
    assert str(SID) not in _cursor(db, eid)


@_pendente_na_sync
def test_coleta_tira_a_conta_esquecida_que_ja_estava_no_cursor(
        db, escola_completa, cliente_global, monkeypatch):
    """A conta esquecida JÁ gravada no cursor (por uma restauração sem a limpeza, ou
    pela exclusão de uma versão que não tirava a conta do cursor) sai na coleta
    seguinte. Tirá-la só de ``contadores_novos`` não basta: o MERGE de
    ``_salvar_contadores`` mantém o que já estava gravado."""
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    _excluir(cliente_global, eid, aid)
    service._salvar_contadores(db, eid, "elefante", {str(SID): len(LIVROS)})
    db.commit()
    assert str(SID) in _cursor(db, eid)
    rodar(db, eid, "elefante")
    assert _ficha_de_volta(db, eid) == []
    assert str(SID) not in _cursor(db, eid)


@_pendente_na_restauracao
def test_restauracao_de_backup_anterior_nao_devolve_a_conta_ao_cursor(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    baixado = cliente.get(f"{API}/escolas/{eid}/backup")
    assert baixado.status_code == 200, baixado.text
    _excluir(cliente_global, eid, aid)
    _restaurar(cliente_global, eid, baixado.content)
    assert _ficha_de_volta(db, eid) == []
    assert str(SID) not in (_cursor(db, eid) or {})
    assert not _varrer(db, str(SID))


@_pendente_na_sync
def test_restauracao_seguida_de_coleta_nao_deixa_a_conta_no_cursor(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    """A restauração devolve a conta ao cursor e a coleta seguinte a MESCLA: tirar a
    conta só de ``contadores_novos`` deixaria o id restaurado para sempre."""
    eid, aid = _coletar_e_achar(db, escola_completa, monkeypatch)
    baixado = cliente.get(f"{API}/escolas/{eid}/backup")
    assert baixado.status_code == 200, baixado.text
    _excluir(cliente_global, eid, aid)
    rodar(db, eid, "elefante")
    assert str(SID) not in _cursor(db, eid)
    _restaurar(cliente_global, eid, baixado.content)
    rodar(db, eid, "elefante")
    assert _ficha_de_volta(db, eid) == []
    assert str(SID) not in _cursor(db, eid)
