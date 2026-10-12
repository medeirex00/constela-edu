"""Consolidação automática e segura das FICHAS-SOMBRA (``services/consolidacao_sombras``).

O padrão real (escolas 1 e 11, jul/ago): a sincronização do Matific recebeu o
nome TRUNCADO ("ZULEICA R") e criou a ficha ao lado da ficha OFICIAL da Lista
Piloto da mesma criança, na mesma turma, com a conta do Matific. A criança virou
duas: Matemática numa ficha, Leitura na outra. O motor já desempatava a linha do
Elefante para a oficial, mas nada era fundido.

O que estes testes travam:
  * o padrão consolida — e, depois, a linha do Elefante com o nome completo
    (uma letra diferente num SOBRENOME do meio; a partícula "DE" faltando) vai
    para a oficial SEM revisão, e as pendências antigas dessa linha são
    encerradas pelo mecanismo que já existe;
  * NUNCA junta crianças diferentes: gêmeos, irmão de outra turma (com ou sem
    conta, se for da Lista Piloto), gêmea fora da lista na mesma turma, nome
    idêntico com conta ou dado, nomes em outra ordem, identificador divergente,
    decisão humana na sombra, a dona real escondida por partícula ou por uma
    letra no prenome, uma letra diferente no PRENOME (decisão 3 do dono: segue
    manual) e prenome que é prefixo do outro (GABRIEL × GABRIELA);
  * duas contas (ou dois retratos) na mesma plataforma é CONFLITO — também com
    o dado gravado por nome, sem conta, e com a 2ª conta pendente na fila; a
    sombra de OUTRA turma, fora da lista, com conta própria não bloqueia;
  * a aplicação reconfere o par (compare-and-set, relendo as fichas do banco),
    é idempotente, move tudo para a oficial sem dobrar a nota, audita os ids
    movidos sem pôr uma pessoa como autora, e é atômica com o recálculo;
  * a política da escola: "manual" (padrão) não funde nada na sincronização;
    "automatico" funde, numa transação própria, sem derrubar a sync se falhar;
    só o admin global a altera;
  * o script: simulação não grava; --aplicar exige --esperado e --assinatura;
    divergência de qualquer um sai 3.

Nomes FICTÍCIOS, montados para o teste (nenhum é de aluno real).
"""
import json
import sys
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Escola,
    IdentidadeExterna,
    Importacao,
    LogAuditoria,
    Matricula,
    Nota,
    Rede,
    RevisaoIdentidade,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.models.sincronizacao import SincronizacaoLog
from app.services import consolidacao_sombras as cs
from app.services import identidade_aluno as ida
from app.services import politica_sync, scoring
from app.sync import orchestrator, service, vault
from app.sync.interfaces import ArquivoObtido, Contexto, Credenciais

ANO = 2026
SALA = "2 ANO B TARDE ANUAL"            # como o Elefante escreve a turma
DATA_CONGELADA = "2025-09-22T10:00:00+00:00"

OFICIAL_Z = "ZULEICA RAMONA TEODORO DA CUNHA"
SOMBRA_Z = "ZULEICA R"
ELEFANTE_Z = "ZULEICA RAMONA TEODORA DA CUNHA"     # uma letra no sobrenome do meio
OFICIAL_O = "OSVALDINO BRAGANCA DE MELO"
SOMBRA_O = "OSVALDINO B"
ELEFANTE_O = "OSVALDINO BRAGANCA MELO"             # sem a partícula "DE"
SID_Z, SID_O = 4410001, 4410002


# --- montagem ------------------------------------------------------------------

def _turma(db, escola, nome, ano_escolar, codigo=None):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar, ano_letivo=ANO,
              codigo_externo=codigo)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, lp=True, status="ativo", chamada=None,
           nascimento=None, ra=None):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, numero_chamada=chamada,
              data_nascimento=nascimento, da_lista_piloto=lp,
              ficha={"ra": ra} if ra else {})
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ANO))
        db.flush()
    return a


def _conta(db, escola, aluno, plataforma, id_externo, status="efetiva"):
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id, plataforma=plataforma,
                             id_externo=id_externo, status=status))
    db.flush()


def _importacao(db, escola, plataforma="matific"):
    imp = Importacao(escola_id=escola.id, plataforma=plataforma, tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _item(plano, aluno):
    item = plano.item_da_sombra(aluno.id)
    assert item is not None, f"ficha {aluno.id} fora do plano"
    return item


def _logs(db, acao):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)
                      .order_by(LogAuditoria.id)).scalars().all()


def _existe(db, aluno_id):
    db.expire_all()
    return db.get(Aluno, aluno_id) is not None


def _dono(db, escola, plataforma, id_externo):
    db.expire_all()
    return db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == escola.id, IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == id_externo)).scalar_one_or_none()


def _aplicar(db, escola, plano=None, origem="teste"):
    plano = plano or cs.planejar(db, escola.id)
    return cs.aplicar(db, plano, usuario_id=None, origem=origem)


@pytest.fixture()
def esc(db, escola_completa):
    escola = escola_completa["escola"]
    b = _turma(db, escola, "2º Ano B", "2º Ano", codigo="300399001")
    a4 = _turma(db, escola, "4º Ano A", "4º Ano")
    db.commit()
    return {"escola": escola, "admin": escola_completa["admin"], "b": b, "a4": a4}


@pytest.fixture()
def padrao(db, esc):
    """Dois pares do padrão real: a oficial da Lista Piloto SEM conta Matific e,
    na mesma turma, a sombra de nome truncado COM a conta Matific."""
    e, b = esc["escola"], esc["b"]
    oficial_z = _aluno(db, e, b, OFICIAL_Z, chamada=7)
    sombra_z = _aluno(db, e, b, SOMBRA_Z, lp=False)
    _conta(db, e, sombra_z, "matific", "u-sombra-zuleica")
    oficial_o = _aluno(db, e, b, OFICIAL_O, chamada=12)
    sombra_o = _aluno(db, e, b, SOMBRA_O, lp=False)
    _conta(db, e, sombra_o, "matific", "u-sombra-osvaldino")
    _aluno(db, e, b, "PRISCILA NUNES TAVARES")            # colega sem relação
    db.commit()
    return {**esc, "oficial_z": oficial_z, "sombra_z": sombra_z,
            "oficial_o": oficial_o, "sombra_o": sombra_o}


# --- 1. o padrão: consolida, e o Elefante passa a cair na oficial sem revisão ----

def _pendencia_antiga(db, escola, sid, nome, candidatos):
    """A pendência que a sincronização antiga deixou para a linha do Elefante."""
    chave_ident = f"elefante|id:{sid}"
    rev = RevisaoIdentidade(
        escola_id=escola.id, chave=ida.chave_pendencia(chave_ident, "resumo"),
        chave_identidade=chave_ident, plataforma="elefante", formato="resumo",
        id_externo=str(sid), nome_recebido=nome, turma_informada=SALA,
        motivo="candidatos_multiplos",
        candidatos=[{"aluno_id": a.id, "nome": a.nome} for a in candidatos],
        linhas=[{"turma_relatorio": SALA, "livros_unicos": 3,
                 "elefante_student_id": str(sid)}],
        contexto={"tipo": "texto", "data_referencia": DATA_CONGELADA,
                  "periodo_inicio": "", "periodo_fim": ""},
        origem="sincronizacao", status="pendente")
    db.add(rev)
    db.commit()
    return rev


def _sincronizar_elefante(db, escola, monkeypatch, alunos):
    """O orquestrador REAL da sincronização (o caminho de produção)."""
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    payload = {"courseSchoolDescriptors": {"courseName": SALA},
               "students": [{"studentId": sid, "studentName": nome, "totalBooksRead": 9}
                            for sid, nome in alunos]}
    return orchestrator.aplicar_arquivo(
        db, escola, ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                                  nome_arquivo="e.json", plataforma="elefante",
                                  content_type=orchestrator.CT_ELEFANTE_API,
                                  formato_hint="resumo"),
        usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=escola.id, execucao_id=None, log=lambda *a: None))


def test_padrao_consolida_e_o_elefante_cai_na_oficial_sem_revisao(db, padrao, monkeypatch):
    c = padrao
    e = c["escola"]
    plano = cs.planejar(db, e.id)
    for sombra, oficial in ((c["sombra_z"], c["oficial_z"]), (c["sombra_o"], c["oficial_o"])):
        item = _item(plano, sombra)
        assert (item.classe, item.oficial_id, item.turma_id) == (
            cs.CONSOLIDAR, oficial.id, c["b"].id)
        assert item.evidencias["relacao_nome"] == "abreviacao"
        assert item.evidencias["plataformas_da_sombra"] == ["matific"]
    # As oficiais e as fichas de outras turmas não são alvo (só fora da Lista Piloto).
    assert plano.item_da_sombra(c["oficial_z"].id) is None

    revs = [_pendencia_antiga(db, e, SID_Z, ELEFANTE_Z, (c["oficial_z"], c["sombra_z"])),
            _pendencia_antiga(db, e, SID_O, ELEFANTE_O, (c["oficial_o"], c["sombra_o"]))]

    res = _aplicar(db, e, plano)
    assert sorted(x["sombra_id"] for x in res["consolidados"]) == sorted(
        [c["sombra_z"].id, c["sombra_o"].id])
    assert res["pulados"] == []
    assert not _existe(db, c["sombra_z"].id) and not _existe(db, c["sombra_o"].id)
    assert _dono(db, e, "matific", "u-sombra-zuleica") == c["oficial_z"].id
    assert _dono(db, e, "matific", "u-sombra-osvaldino") == c["oficial_o"].id

    # A linha do Elefante com o nome completo: o motor decide pela oficial, sem
    # revisão — pela grafia SEGURA (sobrenome do meio) e pelo nome sem "DE".
    ctx = ida.carregar_contexto(db, e.id)
    for nome, sid, oficial, via in ((ELEFANTE_Z, SID_Z, c["oficial_z"], "variante"),
                                    (ELEFANTE_O, SID_O, c["oficial_o"], "parcial")):
        d = ida.decidir(ctx, ida.LinhaIdentidade(nome=nome, plataforma="elefante",
                                                 id_externo=str(sid), turma_nome=SALA))
        assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, oficial.id, via)

    n_alunos = db.execute(select(func.count()).select_from(Aluno)).scalar_one()
    _sincronizar_elefante(db, e, monkeypatch, [(SID_Z, ELEFANTE_Z), (SID_O, ELEFANTE_O)])
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Aluno)).scalar_one() == n_alunos
    assert _dono(db, e, "elefante", str(SID_Z)) == c["oficial_z"].id
    assert _dono(db, e, "elefante", str(SID_O)) == c["oficial_o"].id
    # As pendências antigas foram encerradas pelo encerramento automático que já
    # existe — e nenhuma pendência nova nasceu.
    todas = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert {r.id for r in todas} == {r.id for r in revs}
    for rev, oficial in zip(revs, (c["oficial_z"], c["oficial_o"])):
        r = db.get(RevisaoIdentidade, rev.id)
        assert (r.status, r.aluno_escolhido_id, r.resolvida_por_id) == (
            "resolvida", oficial.id, None)
        assert r.resolucao["automatica"] is True
    assert len(_logs(db, "revisao.encerrada_automaticamente")) == 2


def test_auditoria_e_dados_movidos_sem_dobrar_a_nota(db, padrao):
    """Snapshots e conta vão para a oficial, a sombra é apagada, a auditoria tem
    as evidências (sem nome de criança) e a nota é recalculada sem dobrar."""
    c = padrao
    e, sombra, oficial = c["escola"], c["sombra_z"], c["oficial_z"]
    imp_m, imp_e = _importacao(db, e, "matific"), _importacao(db, e, "elefante")
    snap_m = SnapshotMatific(escola_id=e.id, aluno_id=sombra.id, importacao_id=imp_m.id,
                             atividades=40, estrelas=150, pontuacao_media=3.75)
    db.add(snap_m)
    db.add(SnapshotElefante(escola_id=e.id, aluno_id=oficial.id, importacao_id=imp_e.id,
                            livros_unicos=12, tempo_leitura_min=300,
                            livros_por_nivel={"D": 2}))
    db.commit()
    snap_m_id = snap_m.id
    [conta_id] = db.execute(select(IdentidadeExterna.id).where(
        IdentidadeExterna.aluno_id == sombra.id)).scalars().all()
    scoring.recalcular_escola(db, e.id)
    nota_sombra = db.execute(select(Nota).where(Nota.aluno_id == sombra.id)).scalar_one()
    matematica_antes = nota_sombra.nota_matific
    assert matematica_antes > 0
    ativos_antes = db.execute(select(func.count()).select_from(Matricula).where(
        Matricula.turma_id == c["b"].id)).scalar_one()

    res = _aplicar(db, e)
    assert len(res["consolidados"]) == 2             # as duas sombras do padrão

    db.expire_all()
    assert not _existe(db, sombra.id)
    assert db.execute(select(SnapshotMatific.aluno_id)).scalars().all() == [oficial.id]
    assert db.execute(select(SnapshotElefante.aluno_id)).scalars().all() == [oficial.id]
    # A turma conta a criança UMA vez.
    assert db.execute(select(func.count()).select_from(Matricula).where(
        Matricula.turma_id == c["b"].id)).scalar_one() == ativos_antes - 2
    # Nota: uma por criança, a oficial com as DUAS matérias e a Matemática igual à
    # que a sombra tinha (o snapshot foi movido, não somado).
    notas = db.execute(select(Nota).where(Nota.escola_id == e.id)).scalars().all()
    assert len({n.aluno_id for n in notas}) == len(notas)
    assert sombra.id not in {n.aluno_id for n in notas}
    nota = next(n for n in notas if n.aluno_id == oficial.id)
    assert nota.aferido_matematica and nota.aferido_leitura
    assert nota.nota_matific == pytest.approx(matematica_antes)

    [log] = [l for l in _logs(db, "aluno.consolidado_automatico")
             if l.detalhes["sombra_id"] == sombra.id]
    d = log.detalhes
    assert (log.entidade, log.entidade_id) == ("aluno", oficial.id)
    assert (d["oficial_id"], d["turma_id"], d["motivo"], d["origem"]) == (
        oficial.id, c["b"].id, cs.REGRA, "teste")
    assert d["plataformas_movidas"] == ["matific"]
    assert (d["identidades_movidas"], d["snapshots_matific"]) == (1, 1)
    # QUAIS linhas vieram da sombra (para desfazer pelo log, se preciso).
    assert d["linhas_movidas"] == {"snapshots_matific": [snap_m_id],
                                   "snapshots_elefante": [], "leituras": [],
                                   "eventos": [], "identidades_externas": [conta_id]}
    assert all(v == [] for v in d["linhas_descartadas"].values())
    assert d["evidencias"]["relacao_nome"] == "abreviacao"
    texto = json.dumps(d, ensure_ascii=False)
    assert SOMBRA_Z not in texto and OFICIAL_Z not in texto       # sem PII nova
    # A fusão em si é a da tela: "aluno.fundido" com a foto pré-fusão — e marcada
    # como automática, sem pessoa como autora.
    fundido = [l for l in _logs(db, "aluno.fundido")
               if l.detalhes["removido"]["id"] == sombra.id]
    assert len(fundido) == 1 and fundido[0].detalhes["foto_pre_fusao"]["id"] == sombra.id
    assert fundido[0].detalhes["origem"] == "consolidacao_automatica:teste"
    assert fundido[0].usuario_id is None


def test_idempotente_a_segunda_execucao_nao_acha_nada(db, padrao):
    e = padrao["escola"]
    assert len(_aplicar(db, e)["consolidados"]) == 2
    n_logs = len(_logs(db, "aluno.consolidado_automatico"))
    plano = cs.planejar(db, e.id)
    assert plano.consolidar == []
    res = _aplicar(db, e, plano)
    assert res == {"escola_id": e.id, "consolidados": [], "pulados": []}
    assert len(_logs(db, "aluno.consolidado_automatico")) == n_logs


# --- 2. nunca junta crianças diferentes ----------------------------------------

def test_gemeos_duas_oficiais_compativeis_vao_para_revisao(db, esc):
    e, b = esc["escola"], esc["b"]
    alice = _aluno(db, e, b, "MARIA ALICE ALVES PEREIRA")
    aline = _aluno(db, e, b, "MARIA ALINE ALVES PEREIRA")
    sombra = _aluno(db, e, b, "MARIA A", lp=False)
    _conta(db, e, sombra, "matific", "u-maria-a")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.REVISAR, "varias_oficiais")
    assert set(item.relacionados) == {alice.id, aline.id}
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


def test_irmao_em_outra_turma_sem_conta_vai_para_revisao(db, padrao):
    """O irmão da 4ºA tem o mesmo prenome e sobrenome: "ZULEICA R" pode ser dele."""
    c = padrao
    irmao = _aluno(db, c["escola"], c["a4"], "ZULEICA REBECA TEODORO DA CUNHA")
    db.commit()
    item = _item(cs.planejar(db, c["escola"].id), c["sombra_z"])
    assert (item.classe, item.motivo) == (cs.REVISAR, "compativel_em_outra_ficha")
    assert item.relacionados == (irmao.id,)
    assert c["sombra_z"].id not in [x["sombra_id"]
                                    for x in _aplicar(db, c["escola"])["consolidados"]]
    assert _existe(db, c["sombra_z"].id)


@pytest.mark.parametrize("da_lista, classe", [
    # A ficha da Lista Piloto de outra turma, mesmo com conta própria, pode ser a
    # dona da conta antiga da sombra: a criança mudou de turma e ganhou conta nova.
    (True, cs.REVISAR),
    # A ficha FORA da lista, em outra turma, com a conta dela é a sombra de outra
    # criança — não disputa a conta desta.
    (False, cs.CONSOLIDAR),
])
def test_homonimo_de_outra_turma_com_conta_propria(db, padrao, da_lista, classe):
    """REGRA MUDOU (revisão adversarial, 12/10): conta própria só isenta a ficha
    FORA da Lista Piloto de OUTRA turma."""
    c = padrao
    e = c["escola"]
    irmao = _aluno(db, e, c["a4"], "ZULEICA REBECA TEODORO DA CUNHA", lp=da_lista)
    _conta(db, e, irmao, "matific", "u-zuleica-rebeca")
    db.commit()
    item = _item(cs.planejar(db, e.id), c["sombra_z"])
    assert (item.classe, item.oficial_id) == (classe, c["oficial_z"].id)
    if classe == cs.REVISAR:
        assert (item.motivo, item.relacionados) == ("compativel_em_outra_ficha", (irmao.id,))
    else:
        assert item.evidencias["outras_compativeis_com_conta_propria"] == [irmao.id]


@pytest.mark.parametrize("cenario", ["transferida_de_turma", "saiu_da_escola",
                                     "gemea_fora_da_lista"])
def test_conta_propria_nao_isenta_quem_pode_ter_ganho_segunda_conta(db, esc, cenario):
    """A criança que pode ter ganhado uma SEGUNDA conta no Matific: a conta da
    sombra pode ser a antiga dela. Conta própria não prova nada."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, "IRACEMA SOFIA LIMA", chamada=10)
    if cenario == "transferida_de_turma":
        outra = _aluno(db, e, esc["a4"], "IRACEMA SILVA COSTA", chamada=11)
    elif cenario == "saiu_da_escola":
        outra = _aluno(db, e, b, "IRACEMA SILVA COSTA", chamada=11, status="transferido")
    else:
        outra = _aluno(db, e, b, "IRACEMA SILVIA COSTA", lp=False)
    _conta(db, e, outra, "matific", "u-iracema-nova")
    sombra = _aluno(db, e, b, "IRACEMA S", lp=False)
    _conta(db, e, sombra, "matific", "u-iracema-antiga")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.oficial_id, item.relacionados) == (
        cs.REVISAR, "compativel_em_outra_ficha", oficial.id, (outra.id,))
    assert _aplicar(db, e)["consolidados"] == []
    assert _dono(db, e, "matific", "u-iracema-antiga") == sombra.id


def test_homonimo_so_com_conta_aposentada_continua_bloqueando(db, padrao):
    """Conta aposentada não é conta PRÓPRIA em uso: não prova que a conta da
    sombra não é a dele."""
    c = padrao
    e = c["escola"]
    irmao = _aluno(db, e, c["a4"], "ZULEICA REBECA TEODORO DA CUNHA")
    _conta(db, e, irmao, "matific", "u-zuleica-rebeca", status="aposentada")
    db.commit()
    item = _item(cs.planejar(db, e.id), c["sombra_z"])
    assert (item.classe, item.motivo) == (cs.REVISAR, "compativel_em_outra_ficha")


def test_oficial_so_em_outra_turma_vai_para_revisao(db, esc):
    e = esc["escola"]
    oficial = _aluno(db, e, esc["a4"], OFICIAL_Z)
    sombra = _aluno(db, e, esc["b"], SOMBRA_Z, lp=False)
    _conta(db, e, sombra, "matific", "u-z")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.relacionados) == (
        cs.REVISAR, "oficial_em_outra_turma", (oficial.id,))


def test_outra_crianca_fora_da_lista_fica_sem_par(db, padrao):
    c = padrao
    outra = _aluno(db, c["escola"], c["b"], "JOSEFA QUITERIA MOREIRA", lp=False)
    _conta(db, c["escola"], outra, "matific", "u-josefa")
    db.commit()
    plano = cs.planejar(db, c["escola"].id)
    assert _item(plano, outra).classe == cs.SEM_PAR
    # As fichas da turma-base da fixture também são outras crianças sem par.
    assert plano.contagens()[cs.SEM_PAR] >= 1
    _aplicar(db, c["escola"], plano)
    assert _existe(db, outra.id)


def test_conta_na_mesma_plataforma_da_oficial_e_conflito(db, padrao):
    c = padrao
    e = c["escola"]
    _conta(db, e, c["oficial_z"], "matific", "u-oficial-zuleica")
    _conta(db, e, c["oficial_o"], "matific", "u-oficial-osvaldino", status="aposentada")
    db.commit()
    plano = cs.planejar(db, e.id)
    for sombra in (c["sombra_z"], c["sombra_o"]):
        item = _item(plano, sombra)
        assert (item.classe, item.motivo) == (cs.CONFLITO, "duas_contas_mesma_plataforma")
    assert _aplicar(db, e, plano)["consolidados"] == []
    assert _existe(db, c["sombra_z"].id) and _existe(db, c["sombra_o"].id)


def test_conta_em_outra_plataforma_da_oficial_nao_e_conflito(db, padrao):
    c = padrao
    _conta(db, c["escola"], c["oficial_z"], "elefante", "4419999")
    db.commit()
    assert _item(cs.planejar(db, c["escola"].id), c["sombra_z"]).classe == cs.CONSOLIDAR


def test_sombra_com_duas_contas_na_mesma_plataforma_e_conflito(db, padrao):
    """O outro padrão real: a ficha fora da lista recebeu uma SEGUNDA conta Matific
    de nome compatível — pode ser outra criança. Gente decide."""
    c = padrao
    _conta(db, c["escola"], c["sombra_z"], "matific", "u-segunda-conta")
    db.commit()
    item = _item(cs.planejar(db, c["escola"].id), c["sombra_z"])
    assert (item.classe, item.motivo) == (cs.CONFLITO, "duas_contas_mesma_plataforma")


def test_conta_contestada_na_fila_e_conflito(db, padrao):
    c = padrao
    e = c["escola"]
    db.add(RevisaoIdentidade(
        escola_id=e.id, chave="matific|id:u-outra|resumo||", chave_identidade="matific|id:u-outra",
        plataforma="matific", formato="resumo", id_externo="u-outra", nome_recebido=SOMBRA_Z,
        motivo="outra_identidade_na_plataforma",
        candidatos=[{"aluno_id": c["sombra_z"].id, "nome": SOMBRA_Z}], linhas=[],
        origem="sincronizacao", status="pendente"))
    db.commit()
    item = _item(cs.planejar(db, e.id), c["sombra_z"])
    assert (item.classe, item.motivo) == (cs.CONFLITO, "conta_contestada")


@pytest.mark.parametrize("com_conta, classe, motivo", [
    (True, cs.REVISAR, "nome_identico_com_conta"),
    (False, cs.CONSOLIDAR, ""),
])
def test_nome_identico_so_consolida_sem_conta(db, esc, com_conta, classe, motivo):
    """Nome idêntico ao da oficial pode ser OUTRA criança real de mesmo nome: só
    é sombra sem conta em nenhuma plataforma. O asterisco da Lista Piloto não
    muda o nome."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, "LAURINDA GOMES DA SILVA*")
    sombra = _aluno(db, e, b, "LAURINDA GOMES DA SILVA", lp=False)
    if com_conta:
        _conta(db, e, sombra, "elefante", "4415555")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.oficial_id) == (classe, motivo, oficial.id)
    if classe == cs.CONSOLIDAR:
        assert item.evidencias["relacao_nome"] == "nome_identico"
        assert len(_aplicar(db, e)["consolidados"]) == 1
        assert not _existe(db, sombra.id)
    else:
        assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


@pytest.mark.parametrize("campo_sombra, campo_oficial", [
    ({"chamada": 3}, {}),                                   # oficial tem chamada 7
    ({"nascimento": date(2018, 3, 1)}, {"nascimento": date(2018, 9, 9)}),
    ({"ra": "111222333"}, {"ra": "999888777"}),
])
def test_identificador_divergente_vai_para_revisao(db, esc, campo_sombra, campo_oficial):
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, OFICIAL_Z, chamada=7, **campo_oficial)
    sombra = _aluno(db, e, b, SOMBRA_Z, lp=False, **campo_sombra)
    _conta(db, e, sombra, "matific", "u-z")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.oficial_id) == (
        cs.REVISAR, "identificador_divergente", oficial.id)


def _revisao_resolvida(db, escola, escolhido, *, automatica):
    resolucao = {"acao": "associar", "aluno_id": escolhido.id}
    if automatica:
        resolucao["automatica"] = True
    db.add(RevisaoIdentidade(
        escola_id=escola.id, chave="matific|id:u-sombra-zuleica|resumo||",
        chave_identidade="matific|id:u-sombra-zuleica", plataforma="matific",
        formato="resumo", id_externo="u-sombra-zuleica", nome_recebido=SOMBRA_Z,
        motivo="correspondencia_insegura", candidatos=[], linhas=[],
        origem="sincronizacao", status="resolvida", aluno_escolhido_id=escolhido.id,
        resolucao=resolucao, resolvida_em=datetime.now(timezone.utc)))
    db.commit()


def test_revisao_humana_que_escolheu_a_sombra_vai_para_revisao(db, padrao):
    c = padrao
    _revisao_resolvida(db, c["escola"], c["sombra_z"], automatica=False)
    item = _item(cs.planejar(db, c["escola"].id), c["sombra_z"])
    assert (item.classe, item.motivo) == (cs.REVISAR, "decisao_humana_na_sombra")


def test_escolha_automatica_do_sistema_na_sombra_nao_bloqueia(db, padrao):
    """Encerramento automático só repete a regra: não é decisão de gente."""
    c = padrao
    _revisao_resolvida(db, c["escola"], c["sombra_z"], automatica=True)
    assert _item(cs.planejar(db, c["escola"].id), c["sombra_z"]).classe == cs.CONSOLIDAR


def test_conta_aposentada_na_sombra_vai_para_revisao(db, esc):
    e, b = esc["escola"], esc["b"]
    _aluno(db, e, b, OFICIAL_Z)
    sombra = _aluno(db, e, b, SOMBRA_Z, lp=False)
    _conta(db, e, sombra, "matific", "u-z", status="aposentada")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.REVISAR, "conta_aposentada_na_sombra")


@pytest.mark.parametrize("nome_sombra", [
    "OTAVIANO RICADO BRAGANCA MELO",    # 2º prenome com uma letra a menos
    "OTAVIANO RICADO B",                # o mesmo, truncado pelo relatório
    "OTAVIANO RICARDA BRAGANCA MELO",   # 2º prenome com uma letra trocada
    "OTAVIANA R",                       # 1º prenome com uma letra trocada
])
def test_prenome_com_uma_letra_diferente_nunca_consolida(db, esc, nome_sombra):
    """Decisão 3 do dono (12/10): uma letra diferente no PRENOME segue na revisão
    manual — irmãos e gêmeos se distinguem pelo prenome."""
    e, b = esc["escola"], esc["b"]
    _aluno(db, e, b, "OTAVIANO RICARDO BRAGANCA MELO")
    sombra = _aluno(db, e, b, nome_sombra, lp=False)
    _conta(db, e, sombra, "matific", "u-otaviano")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert item.classe != cs.CONSOLIDAR
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


@pytest.mark.parametrize("oficial_nome, outra_nome, com_conta, motivo", [
    # Prenome com uma letra a mais/a menos NO FIM: "forte" para o motor (prefixo
    # = truncamento), mas na sala são irmãos de sexo diferente — nos dois sentidos.
    ("GABRIELA TEODORO MASCARENHAS", "GABRIEL TEODORO MASCARENHAS", True,
     "prenome_diferente"),
    ("GABRIEL TEODORO MASCARENHAS", "GABRIELA TEODORO MASCARENHAS", True,
     "prenome_diferente"),
    ("LUISA TEODORO MASCARENHAS", "LUIS TEODORO MASCARENHAS", False, "prenome_diferente"),
    ("LUIS TEODORO MASCARENHAS", "LUISA TEODORO MASCARENHAS", False, "prenome_diferente"),
    ("VICTORIA TEODORO MASCARENHAS", "VICTOR TEODORO MASCARENHAS", True,
     "prenome_diferente"),
    ("VICTOR TEODORO MASCARENHAS", "VICTORIA TEODORO MASCARENHAS", True,
     "prenome_diferente"),
    # 2º prenome com uma letra a menos no fim (o irmão do RICADO × RICARDO).
    ("OTAVIANO RICARDO BRAGANCA MELO", "OTAVIANO RICARD BRAGANCA MELO", True,
     "truncamento_fora_do_padrao"),
    ("OTAVIANO RICARD BRAGANCA MELO", "OTAVIANO RICARDO BRAGANCA MELO", True,
     "oficial_abreviada"),
])
def test_decisao3_prenome_que_e_prefixo_do_outro_nunca_consolida(
        db, esc, oficial_nome, outra_nome, com_conta, motivo):
    """Decisão 3 do dono: a diferença no PRENOME (ou um nome cortado no meio) é
    revisão manual. Só a forma do relatório — prenome igual e a última palavra
    reduzida à inicial — consolida."""
    from app.services import matching
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, oficial_nome, chamada=9)
    outra = _aluno(db, e, b, outra_nome, lp=False)
    if com_conta:
        _conta(db, e, outra, "matific", "u-outra")
    db.commit()
    assert matching.plausivel(outra_nome, oficial_nome) == "forte"   # o motor casaria
    item = _item(cs.planejar(db, e.id), outra)
    assert (item.classe, item.motivo, item.oficial_id) == (cs.REVISAR, motivo, oficial.id)
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, outra.id)


def test_nomes_em_outra_ordem_nao_sao_nome_identico(db, esc):
    """MARIA CLARA × CLARA MARIA: os mesmos nomes, outra criança."""
    e, b = esc["escola"], esc["b"]
    _aluno(db, e, b, "MARIA CLARA VIEIRA", chamada=17)
    outra = _aluno(db, e, b, "CLARA MARIA VIEIRA", lp=False)          # sem conta
    db.commit()
    item = _item(cs.planejar(db, e.id), outra)
    assert (item.classe, item.motivo) == (cs.REVISAR, "nome_em_outra_ordem")
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, outra.id)


def test_oficial_abreviada_com_ficha_completa_nao_consolida(db, esc):
    """A Lista Piloto tem o 2º prenome abreviado; a ficha fora da lista tem o nome
    COMPLETO e a conta do Elefante. Não é sombra de relatório — pode ser a gêmea
    que não está na lista."""
    e, b = esc["escola"], esc["b"]
    _aluno(db, e, b, "ZILDA E MOTTA", chamada=21)
    completa = _aluno(db, e, b, "ZILDA ESTER MOTTA", lp=False)
    _conta(db, e, completa, "elefante", "77001")
    db.commit()
    item = _item(cs.planejar(db, e.id), completa)
    assert (item.classe, item.motivo) == (cs.REVISAR, "oficial_abreviada")


@pytest.mark.parametrize("dona_nome, colega_nome, sombra_nome", [
    # A partícula ocupa a posição da inicial: "TEOBALDO O" não é "forte" com a
    # dona real, só com o colega de mesmo prenome.
    ("TEOBALDO DE OLIVEIRA SOUSA", "TEOBALDO OTAVIO LIMA", "TEOBALDO O"),
    ("GERVASIO HENRIQUE DOS SANTOS", "GERVASIO HENRIQUE SOARES LIMA", "GERVASIO HENRIQUE S"),
    # Decisão 3: a dona real tem UMA letra diferente no prenome (KETLIN × KETLYN)
    # — o caso que segue manual não pode ser resolvido sozinho para outra criança.
    ("KETLIN SOFIA FALCAO", "KETLYN SAMARA COSTA", "KETLYN S"),
])
def test_dona_real_invisivel_ao_forte_segura_a_sombra(db, esc, dona_nome, colega_nome,
                                                      sombra_nome):
    e, b = esc["escola"], esc["b"]
    dona = _aluno(db, e, b, dona_nome, chamada=3)
    colega = _aluno(db, e, b, colega_nome, chamada=4)
    sombra = _aluno(db, e, b, sombra_nome, lp=False)
    _conta(db, e, sombra, "matific", "u-sombra")
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.oficial_id) == (
        cs.REVISAR, "nome_parecido_na_turma", colega.id)
    assert set(item.relacionados) == {colega.id, dona.id}
    assert _aplicar(db, e)["consolidados"] == []
    assert _dono(db, e, "matific", "u-sombra") == sombra.id      # a conta não andou


@pytest.mark.parametrize("nome_da_segunda_conta", ["ODILA SO", "ODILA SOFIA L"])
def test_segunda_conta_pendente_na_fila_e_conflito(db, esc, nome_da_segunda_conta):
    """A sombra tem a conta X; chega a conta Y com outro recorte do nome e o motor
    grava "candidatos_multiplos" (oficial, sombra). É a mesma dúvida das duas
    contas: gente decide antes de a conta X ir para a oficial."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, "ODILA SOFIA LIMA", chamada=18)
    sombra = _aluno(db, e, b, "ODILA S", lp=False)
    _conta(db, e, sombra, "matific", "u-odila-x")
    db.commit()
    ctx = ida.carregar_contexto(db, e.id)
    dec = ida.decidir(ctx, ida.LinhaIdentidade(
        nome=nome_da_segunda_conta, plataforma="matific", id_externo="u-odila-y",
        turma_nome="2º Ano B"))
    assert (dec.acao, dec.motivo) == (ida.REVISAR, "candidatos_multiplos")
    assert set(dec.candidatos) == {oficial.id, sombra.id}
    db.add(RevisaoIdentidade(
        escola_id=e.id, chave="matific|id:u-odila-y|resumo||",
        chave_identidade="matific|id:u-odila-y", plataforma="matific", formato="resumo",
        id_externo="u-odila-y", nome_recebido=nome_da_segunda_conta,
        turma_informada="2º Ano B", motivo=dec.motivo,
        candidatos=[{"aluno_id": i} for i in dec.candidatos], linhas=[],
        origem="sincronizacao", status="pendente"))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "conta_contestada")


def test_pendencia_da_propria_conta_ou_de_outra_plataforma_nao_contesta(db, padrao):
    """A pendência do Elefante com (oficial, sombra) é o estado normal do padrão
    — a sombra não tem conta do Elefante; e a pendência com o MESMO id da conta
    da sombra não é outra conta."""
    c = padrao
    e = c["escola"]
    for plataforma, id_externo in (("elefante", "4410099"), ("matific", "u-sombra-zuleica")):
        db.add(RevisaoIdentidade(
            escola_id=e.id, chave=f"{plataforma}|id:{id_externo}|resumo||",
            chave_identidade=f"{plataforma}|id:{id_externo}", plataforma=plataforma,
            formato="resumo", id_externo=id_externo, nome_recebido=OFICIAL_Z,
            motivo="candidatos_multiplos",
            candidatos=[{"aluno_id": c["oficial_z"].id}, {"aluno_id": c["sombra_z"].id}],
            linhas=[], origem="sincronizacao", status="pendente"))
    db.commit()
    assert _item(cs.planejar(db, e.id), c["sombra_z"]).classe == cs.CONSOLIDAR


def test_oficial_com_dado_legado_na_plataforma_da_sombra_e_conflito(db, esc):
    """O histórico do Elefante foi gravado por NOME, antes do studentId: a oficial
    tem o retrato sem conta registrada. Uma sombra com OUTRA conta do Elefante
    não pode ser fundida — o retrato vigente da criança viraria o da sombra."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, OFICIAL_Z, chamada=7)
    sombra = _aluno(db, e, b, SOMBRA_Z, lp=False)
    _conta(db, e, sombra, "elefante", "4419001")
    imp = _importacao(db, e, "elefante")
    db.add(SnapshotElefante(escola_id=e.id, aluno_id=oficial.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 9, 1), livros_unicos=30,
                            tempo_leitura_min=900, livros_por_nivel={"D": 30}))
    db.add(SnapshotElefante(escola_id=e.id, aluno_id=sombra.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 9, 10), livros_unicos=5,
                            tempo_leitura_min=100, livros_por_nivel={"D": 5}))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "duas_contas_mesma_plataforma")
    assert _aplicar(db, e)["consolidados"] == []
    db.expire_all()
    assert db.execute(select(SnapshotElefante.livros_unicos).where(
        SnapshotElefante.aluno_id == oficial.id)).scalars().all() == [30]


def _leitura(db, escola, aluno, livro, quando):
    from app.models import Leitura
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id, data=quando))


def test_nome_identico_com_dado_sem_conta_nao_consolida(db, esc):
    """Nome idêntico e SEM conta registrada, mas com dado de plataforma (gravado
    por nome): pode ser outra criança real de mesmo nome — revisão."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, "LAURINDA GOMES DA SILVA*", chamada=4)
    sombra = _aluno(db, e, b, "LAURINDA GOMES DA SILVA", lp=False)
    imp = _importacao(db, e, "matific")
    db.add(SnapshotMatific(escola_id=e.id, aluno_id=sombra.id, importacao_id=imp.id,
                           atividades=10, estrelas=20, pontuacao_media=2.0))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.oficial_id) == (
        cs.REVISAR, "nome_identico_com_conta", oficial.id)


def test_leitura_do_mesmo_livro_nas_duas_fichas_nao_e_descartada(db, esc):
    """A fusão descartaria a leitura repetida da sombra, com data e tempo — perda
    irreversível. Com leitura nas duas, as duas têm dado do Elefante: CONFLITO."""
    from app.models import Leitura, Livro
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, OFICIAL_Z, chamada=7)
    sombra = _aluno(db, e, b, SOMBRA_Z, lp=False)
    _conta(db, e, sombra, "matific", "u-z")
    livro = Livro(escola_id=e.id, titulo="LIVRO SINTETICO", nivel_codigo="D")
    db.add(livro)
    db.flush()
    _leitura(db, e, oficial, livro, datetime(2026, 3, 25, 10, 0))
    _leitura(db, e, sombra, livro, datetime(2026, 8, 6, 10, 0))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "duas_contas_mesma_plataforma")
    assert _aplicar(db, e)["consolidados"] == []
    db.expire_all()
    assert sorted(d.month for d in db.execute(
        select(Leitura.data).where(Leitura.livro_id == livro.id)).scalars()) == [3, 8]


def test_duas_sombras_provadamente_diferentes_vao_para_revisao(db, esc):
    """Duas fichas fora da lista, as duas na forma do relatório da MESMA oficial
    (sem nascimento), com nascimentos diferentes entre si: são duas crianças. No
    máximo uma é a oficial — a ordem dos ids não pode escolher."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, OFICIAL_Z)
    s1 = _aluno(db, e, b, SOMBRA_Z, lp=False, nascimento=date(2018, 1, 1))
    _conta(db, e, s1, "matific", "u-s1")
    s2 = _aluno(db, e, b, "ZULEICA RAMONA T", lp=False, nascimento=date(2018, 6, 6))
    _conta(db, e, s2, "elefante", "4418002")
    db.commit()
    plano = cs.planejar(db, e.id)
    for s, outra in ((s1, s2), (s2, s1)):
        item = _item(plano, s)
        assert (item.classe, item.motivo, item.relacionados) == (
            cs.REVISAR, "sombras_distintas", (outra.id,))
    assert _aplicar(db, e, plano)["consolidados"] == []
    db.expire_all()
    assert db.get(Aluno, oficial.id).data_nascimento is None


def test_quest_nos_dois_lados_vai_para_revisao(db, padrao):
    from app.quest.models import QuestPerfil
    c = padrao
    e = c["escola"]
    for i, a in enumerate((c["sombra_z"], c["oficial_z"])):
        db.add(QuestPerfil(escola_id=e.id, aluno_id=a.id, apelido=f"Sint{i}",
                           codigo_amigo=f"SINT-{i:04d}"))
    db.commit()
    item = _item(cs.planejar(db, e.id), c["sombra_z"])
    assert (item.classe, item.motivo) == (cs.REVISAR, "quest_nos_dois")


# --- 3. várias sombras da mesma oficial ------------------------------------------

def test_duas_sombras_sem_conflito_de_conta_vao_as_duas(db, padrao):
    """Duas formas abreviadas da MESMA oficial, só uma com conta: as duas são
    sombras dela, e a segunda é planejada de novo depois da primeira fusão."""
    c = padrao
    e = c["escola"]
    segunda = _aluno(db, e, c["b"], "ZULEICA RAMONA T", lp=False)    # sem conta
    db.commit()
    plano = cs.planejar(db, e.id)
    primeira = _item(plano, c["sombra_z"])
    assert (primeira.classe, primeira.relacionados) == (cs.CONSOLIDAR, (segunda.id,))
    assert primeira.evidencias["outras_sombras_da_mesma_oficial"] == [segunda.id]
    assert (_item(plano, segunda).classe, _item(plano, segunda).oficial_id) == (
        cs.CONSOLIDAR, c["oficial_z"].id)
    res = _aplicar(db, e, plano)
    assert {x["sombra_id"] for x in res["consolidados"]} >= {c["sombra_z"].id, segunda.id}
    assert res["pulados"] == []
    assert not _existe(db, segunda.id) and not _existe(db, c["sombra_z"].id)


def test_ficha_de_nome_parcial_na_turma_segura_a_sombra(db, padrao):
    """"ZULEICA RAMONA" (sem os sobrenomes) não é forma "forte" da oficial — pode
    ser outra criança — e "ZULEICA R" casa com ela: revisão para as duas."""
    c = padrao
    e = c["escola"]
    parcial = _aluno(db, e, c["b"], "ZULEICA RAMONA", lp=False)
    db.commit()
    plano = cs.planejar(db, e.id)
    item = _item(plano, c["sombra_z"])
    assert (item.classe, item.motivo, item.relacionados) == (
        cs.REVISAR, "compativel_em_outra_ficha", (parcial.id,))
    assert (_item(plano, parcial).classe, _item(plano, parcial).motivo) == (
        cs.REVISAR, "nome_parecido_na_turma")


@pytest.mark.parametrize("nome_segunda", ["ZULEICA RA", "ZULEICA RAMONA T"])
def test_duas_sombras_com_conta_na_mesma_plataforma_sao_conflito(db, padrao, nome_segunda):
    c = padrao
    e = c["escola"]
    segunda = _aluno(db, e, c["b"], nome_segunda, lp=False)
    _conta(db, e, segunda, "matific", "u-outra-zuleica")
    db.commit()
    plano = cs.planejar(db, e.id)
    for s, outra in ((c["sombra_z"], segunda), (segunda, c["sombra_z"])):
        assert (_item(plano, s).classe, _item(plano, s).motivo,
                _item(plano, s).relacionados) == (
            cs.CONFLITO, "duas_contas_mesma_plataforma", (outra.id,))


@pytest.mark.parametrize("rebaixa", ["decisao_humana", "conta_aposentada", "nome_fora_do_padrao"])
def test_irma_com_conta_na_mesma_plataforma_segura_mesmo_rebaixada(db, padrao, rebaixa):
    """A outra ficha-sombra da mesma oficial tem OUTRA conta Matific e vai para a
    revisão por um motivo que nada tem a ver com a conta. A primeira continua
    CONFLITO: fundi-la daria a conta X à oficial sem ninguém escolher entre X e
    Y (gêmeas em que só uma está na Lista Piloto)."""
    c = padrao
    e = c["escola"]
    segunda = _aluno(db, e, c["b"],
                     "ZULEICA RA" if rebaixa == "nome_fora_do_padrao" else "ZULEICA RAMONA T",
                     lp=False)
    _conta(db, e, segunda, "matific", "u-outra-zuleica",
           status="aposentada" if rebaixa == "conta_aposentada" else "efetiva")
    if rebaixa == "decisao_humana":
        db.add(RevisaoIdentidade(
            escola_id=e.id, chave="elefante|nome:x|sala:2|B|resumo||",
            chave_identidade="elefante|nome:x|sala:2|B", plataforma="elefante",
            formato="resumo", id_externo=None, nome_recebido="ZULEICA RAMONA T",
            motivo="correspondencia_insegura", candidatos=[], linhas=[],
            origem="sincronizacao", status="resolvida", aluno_escolhido_id=segunda.id,
            resolucao={"acao": "associar", "aluno_id": segunda.id}))
    db.commit()
    plano = cs.planejar(db, e.id)
    assert _item(plano, segunda).classe != cs.CONSOLIDAR
    item = _item(plano, c["sombra_z"])
    assert (item.classe, item.motivo, item.relacionados) == (
        cs.CONFLITO, "duas_contas_mesma_plataforma", (segunda.id,))
    assert c["sombra_z"].id not in [x["sombra_id"]
                                    for x in _aplicar(db, e, plano)["consolidados"]]
    assert _dono(db, e, "matific", "u-sombra-zuleica") == c["sombra_z"].id


def test_sombra_irma_que_nao_consolida_segura_a_outra(db, padrao):
    """A irmã de nome idêntico à oficial e com conta pode ser OUTRA criança — e
    "ZULEICA R" pode ser dela."""
    c = padrao
    e = c["escola"]
    identica = _aluno(db, e, c["b"], OFICIAL_Z, lp=False)
    _conta(db, e, identica, "elefante", "4417777")
    db.commit()
    plano = cs.planejar(db, e.id)
    assert _item(plano, identica).motivo == "nome_identico_com_conta"
    item = _item(plano, c["sombra_z"])
    assert (item.classe, item.motivo, item.relacionados) == (
        cs.REVISAR, "sombra_irma_em_revisao", (identica.id,))


# --- 4. compare-and-set ----------------------------------------------------------

def test_estado_muda_entre_planejar_e_aplicar_o_par_e_pulado(db, padrao):
    c = padrao
    e = c["escola"]
    plano = cs.planejar(db, e.id)
    # Depois do plano: a sombra ganha nº de chamada divergente (outra criança?) e
    # a outra sombra é fundida à mão por alguém.
    db.get(Aluno, c["sombra_z"].id).numero_chamada = 3
    db.delete(db.get(Aluno, c["sombra_o"].id))
    db.commit()
    res = _aplicar(db, e, plano)
    assert res["consolidados"] == []
    pulados = {p["sombra_id"]: p for p in res["pulados"]}
    assert pulados[c["sombra_z"].id]["classe_atual"] == cs.REVISAR
    assert pulados[c["sombra_z"].id]["motivo_atual"] == "identificador_divergente"
    assert pulados[c["sombra_o"].id]["motivo_atual"] == "ficha_inexistente"
    assert _existe(db, c["sombra_z"].id)
    assert {l.entidade_id for l in _logs(db, "aluno.consolidacao_pulada")} == {
        c["sombra_z"].id, c["sombra_o"].id}
    assert _logs(db, "aluno.consolidado_automatico") == []


@pytest.mark.parametrize("mudanca", ["chamada_da_sombra", "oficial_transferida",
                                     "sombra_entra_na_lista"])
def test_mudanca_de_outra_sessao_com_fichas_vivas_na_memoria_pula(db, padrao, mudanca):
    """Quem aplica ainda SEGURA as fichas desta sessão (o plano acabou de lê-las)
    e OUTRA transação muda o cadastro e grava. O compare-and-set relê do banco,
    não do identity map: pula o par."""
    c = padrao
    e = c["escola"]
    plano = cs.planejar(db, e.id)
    vivas = (db.get(Aluno, c["sombra_z"].id), db.get(Aluno, c["oficial_z"].id))
    with sessionmaker(bind=db.get_bind())() as outra:
        if mudanca == "chamada_da_sombra":
            outra.get(Aluno, c["sombra_z"].id).numero_chamada = 3     # oficial tem 7
        elif mudanca == "oficial_transferida":
            outra.get(Aluno, c["oficial_z"].id).status = "transferido"
        else:
            outra.get(Aluno, c["sombra_z"].id).da_lista_piloto = True
        outra.commit()
    res = _aplicar(db, e, plano)
    assert [p["sombra_id"] for p in res["pulados"]] == [c["sombra_z"].id]
    assert c["sombra_z"].id not in [x["sombra_id"] for x in res["consolidados"]]
    assert _existe(db, c["sombra_z"].id) and len(vivas) == 2


def test_conta_nova_da_oficial_entre_planejar_e_aplicar_pula(db, padrao):
    c = padrao
    e = c["escola"]
    plano = cs.planejar(db, e.id)
    _conta(db, e, c["oficial_z"], "matific", "u-nova-da-oficial")
    db.commit()
    res = _aplicar(db, e, plano)
    assert [p["sombra_id"] for p in res["pulados"]] == [c["sombra_z"].id]
    assert [x["sombra_id"] for x in res["consolidados"]] == [c["sombra_o"].id]


# --- 5. a política e a sincronização --------------------------------------------

def test_politica_padrao_e_manual_e_so_aceita_os_dois_modos(db, escola_completa):
    eid = escola_completa["escola"].id
    assert politica_sync.obter(db, eid)["consolidar_sombras"] == "manual"
    assert politica_sync.consolidar_sombras_automatico(db, eid) is False
    assert politica_sync.definir(db, eid, consolidar_sombras="automatico") == {
        "criar_aluno": "permitir", "consolidar_sombras": "automatico"}
    db.commit()
    assert politica_sync.consolidar_sombras_automatico(db, eid) is True
    # Mudar uma chave não mexe na outra.
    assert politica_sync.definir(db, eid, "bloquear") == {
        "criar_aluno": "bloquear", "consolidar_sombras": "automatico"}
    with pytest.raises(ValueError, match="consolidar_sombras"):
        politica_sync.definir(db, eid, consolidar_sombras="sempre")
    with pytest.raises(ValueError, match="Nada a alterar"):
        politica_sync.definir(db, eid)


def test_politica_corrompida_cai_no_manual(db, escola_completa):
    from app.models import Configuracao
    eid = escola_completa["escola"].id
    db.add(Configuracao(escola_id=eid, namespace=politica_sync.NAMESPACE,
                        chave=politica_sync.CHAVE,
                        valor={"criar_aluno": "bloquear", "consolidar_sombras": "SIM!"}))
    db.commit()
    assert politica_sync.obter(db, eid) == {"criar_aluno": "bloquear",
                                            "consolidar_sombras": "manual"}
    assert politica_sync.consolidar_sombras_automatico(db, eid) is False


def _executar_sync(db, escola, monkeypatch, usuario_id=None):
    """Uma execução de sincronização inteira (``service.executar``) com um conector
    falso de um arquivo; a aplicação do arquivo é simulada — o que se testa é o
    que acontece DEPOIS dela."""
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    ex = service.enfileirar(db, escola.id, "matific", origem="teste", usuario_id=usuario_id)
    db.commit()

    class ConectorFake:
        plataforma = "matific"
        versao = "test"

        async def sincronizar(self, cred, contexto):
            return [ArquivoObtido(conteudo=b"{}", nome_arquivo="t.json",
                                  plataforma="matific")]

    def fake_aplicar(db_, escola_, arquivo, *, usuario_id, recalcular, contexto):
        return {"qtd_alunos": 1, "qtd_erros": 0, "qtd_turmas": 0, "importacao_id": None,
                "avisos": [], "ignorados": [], "sem_dados": False}

    monkeypatch.setattr(service.connectors, "obter", lambda _p: ConectorFake())
    monkeypatch.setattr(service.orchestrator, "aplicar_arquivo", fake_aplicar)
    monkeypatch.setattr(service, "_recalcular_ao_final", lambda *a, **k: None)
    return service.executar(db, ex)


def _logs_da_execucao(db, ex, etapa):
    return db.execute(select(SincronizacaoLog).where(
        SincronizacaoLog.execucao_id == ex.id, SincronizacaoLog.etapa == etapa)
        .order_by(SincronizacaoLog.id)).scalars().all()


@pytest.mark.parametrize("gravar_manual", [False, True])
def test_politica_manual_nao_funde_nada_na_sync(db, padrao, monkeypatch, gravar_manual):
    c = padrao
    if gravar_manual:
        politica_sync.definir(db, c["escola"].id, consolidar_sombras="manual")
        db.commit()
    planejados = []
    monkeypatch.setattr(cs, "planejar", lambda *a, **k: planejados.append(a))
    ex = _executar_sync(db, c["escola"], monkeypatch)
    assert ex.status == "concluida"
    assert planejados == []                  # no "manual" nem se planeja nada
    assert _existe(db, c["sombra_z"].id) and _existe(db, c["sombra_o"].id)
    assert _logs(db, "aluno.consolidado_automatico") == []
    assert _logs(db, "aluno.consolidacao_automatica_falhou") == []
    assert _logs_da_execucao(db, ex, "identidade") == []


def test_politica_automatico_funde_na_sync(db, padrao, monkeypatch):
    """REGRA MUDOU (revisão adversarial, 12/10): a sync do AGENDADOR não tem
    autor — a fusão automática fica com ``usuario_id`` vazio e a origem em
    ``aluno.fundido``, em vez de ser atribuída ao primeiro admin da escola."""
    c = padrao
    e = c["escola"]
    politica_sync.definir(db, e.id, consolidar_sombras="automatico")
    db.commit()
    ex = _executar_sync(db, e, monkeypatch)
    assert ex.status == "concluida" and ex.usuario_id is None
    assert not _existe(db, c["sombra_z"].id) and not _existe(db, c["sombra_o"].id)
    assert _dono(db, e, "matific", "u-sombra-zuleica") == c["oficial_z"].id
    logs = _logs(db, "aluno.consolidado_automatico")
    assert len(logs) == 2
    assert {l.detalhes["origem"] for l in logs} == {"sincronizacao"}
    assert {l.usuario_id for l in logs} == {None}               # ninguém fundiu à mão
    fundidos = _logs(db, "aluno.fundido")
    assert len(fundidos) == 2 and {l.usuario_id for l in fundidos} == {None}
    assert {l.detalhes["origem"] for l in fundidos} == {
        "consolidacao_automatica:sincronizacao"}
    [log] = _logs_da_execucao(db, ex, "identidade")
    assert log.nivel == "info" and "2 ficha(s)-sombra consolidada(s)" in log.mensagem
    assert SOMBRA_Z not in log.mensagem
    # A próxima sincronização não acha mais nada (e não loga nada).
    ex2 = _executar_sync(db, e, monkeypatch)
    assert ex2.status == "concluida" and _logs_da_execucao(db, ex2, "identidade") == []
    assert len(_logs(db, "aluno.consolidado_automatico")) == 2


def test_sync_pedida_por_uma_pessoa_registra_quem_pediu(db, padrao, monkeypatch):
    c = padrao
    e = c["escola"]
    politica_sync.definir(db, e.id, consolidar_sombras="automatico")
    db.commit()
    ex = _executar_sync(db, e, monkeypatch, usuario_id=c["admin"].id)
    assert ex.status == "concluida"
    for acao in ("aluno.consolidado_automatico", "aluno.fundido"):
        assert {l.usuario_id for l in _logs(db, acao)} == {c["admin"].id}
    assert {l.detalhes["origem"] for l in _logs(db, "aluno.fundido")} == {
        "consolidacao_automatica:sincronizacao"}


def test_falha_no_recalculo_desfaz_as_fusoes(db, padrao, monkeypatch):
    """O recálculo roda na MESMA transação das fusões: se ele cai, nada fica
    fundido — a criança não fica com a nota velha (a da sombra, com a
    Matemática, apagada) e o log diz a verdade."""
    c = padrao
    e = c["escola"]
    imp_m = _importacao(db, e, "matific")
    db.add(SnapshotMatific(escola_id=e.id, aluno_id=c["sombra_z"].id,
                           importacao_id=imp_m.id, atividades=40, estrelas=150,
                           pontuacao_media=3.75))
    db.commit()
    scoring.recalcular_escola(db, e.id)
    politica_sync.definir(db, e.id, consolidar_sombras="automatico")
    db.commit()

    def explode(*a, **k):
        raise RuntimeError("recálculo caiu")

    monkeypatch.setattr(cs, "_recalcular", explode)
    ex = _executar_sync(db, e, monkeypatch)
    assert ex.status == "concluida"
    assert _existe(db, c["sombra_z"].id) and _existe(db, c["sombra_o"].id)
    assert _dono(db, e, "matific", "u-sombra-zuleica") == c["sombra_z"].id
    assert _logs(db, "aluno.fundido") == []
    assert _logs(db, "aluno.consolidado_automatico") == []
    [falha] = _logs(db, "aluno.consolidacao_automatica_falhou")
    assert falha.detalhes == {"origem": "sincronizacao", "erro": "RuntimeError"}
    nota = db.execute(select(Nota).where(Nota.aluno_id == c["sombra_z"].id)).scalar_one()
    assert nota.aferido_matematica                       # a nota da sombra segue viva
    [log] = _logs_da_execucao(db, ex, "identidade")
    assert log.nivel == "warn" and "nenhuma ficha foi fundida" in log.mensagem


def test_falha_na_consolidacao_nao_derruba_a_sync(db, padrao, monkeypatch):
    c = padrao
    e = c["escola"]
    politica_sync.definir(db, e.id, consolidar_sombras="automatico")
    db.commit()

    def explode(*a, **k):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(cs, "aplicar", explode)
    ex = _executar_sync(db, e, monkeypatch)
    assert ex.status == "concluida"
    assert _existe(db, c["sombra_z"].id) and _existe(db, c["sombra_o"].id)
    [falha] = _logs(db, "aluno.consolidacao_automatica_falhou")
    assert falha.detalhes == {"origem": "sincronizacao", "erro": "RuntimeError"}
    [log] = _logs_da_execucao(db, ex, "identidade")
    assert log.nivel == "warn"


# --- 6. a rota da política ------------------------------------------------------

SENHA = "s3nh4"


def _login(email: str) -> TestClient:
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def test_rota_da_politica_so_admin_global_altera_a_consolidacao(cliente, cliente_global,
                                                                db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Sintética", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add_all([
        Usuario(escola_id=escola.id, nome="Coord", email="coord@sombra.local",
                senha_hash=hash_senha(SENHA), cargo="coordenador"),
        Usuario(escola_id=escola.id, nome="Secretaria", email="sec@sombra.local",
                senha_hash=hash_senha(SENHA), cargo="admin", rede_id=rede.id),
    ])
    db.commit()
    url = f"/api/v1/escolas/{escola.id}/configuracoes/sincronizacao"
    corpo = {"consolidar_sombras": "automatico"}

    assert cliente.get(url).json() == {"criar_aluno": "permitir",
                                       "consolidar_sombras": "manual"}
    assert cliente.put(url, json=corpo).status_code == 403                  # admin da escola
    assert _login("coord@sombra.local").put(url, json=corpo).status_code == 403
    assert _login("sec@sombra.local").put(url, json=corpo).status_code == 403
    assert politica_sync.consolidar_sombras_automatico(db, escola.id) is False

    ok = cliente_global.put(url, json={**corpo, "motivo": "evidência suficiente"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"criar_aluno": "permitir", "consolidar_sombras": "automatico"}
    assert cliente.get(url).json()["consolidar_sombras"] == "automatico"
    assert cliente_global.put(url, json={"consolidar_sombras": "sempre"}).status_code == 422
    assert cliente_global.put(url, json={"motivo": "nada"}).status_code == 422

    log = _logs(db, "sincronizacao.politica_alterada")[-1]
    assert log.detalhes["de"] == {"criar_aluno": "permitir", "consolidar_sombras": "manual"}
    assert log.detalhes["para"] == {"criar_aluno": "permitir",
                                    "consolidar_sombras": "automatico"}


def test_mudar_a_politica_nao_funde_nada_sozinho(cliente_global, db, padrao):
    """Ligar a consolidação vale da PRÓXIMA sincronização em diante."""
    c = padrao
    r = cliente_global.put(
        f"/api/v1/escolas/{c['escola'].id}/configuracoes/sincronizacao",
        json={"consolidar_sombras": "automatico"})
    assert r.status_code == 200
    assert _existe(db, c["sombra_z"].id) and _existe(db, c["sombra_o"].id)


# --- 7. o script ----------------------------------------------------------------

@pytest.fixture()
def banco(tmp_path):
    """SQLite em arquivo DESCARTÁVEL (nunca o banco de desenvolvimento)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'sombras.db'}")
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    db = Sessao()
    escola = Escola(nome="ESCOLA SOMBRAS SINT", ano_letivo_ativo=ANO)
    db.add(escola)
    db.flush()
    for ns, valores in scoring.PESOS_PADRAO.items():
        from app.models import Configuracao
        db.add(Configuracao(escola_id=escola.id, namespace=ns, chave="valores",
                            valor=valores))
    b = _turma(db, escola, "2º Ano B", "2º Ano")
    oficial = _aluno(db, escola, b, OFICIAL_Z)
    sombra = _aluno(db, escola, b, SOMBRA_Z, lp=False)
    _conta(db, escola, sombra, "matific", "u-script")
    _aluno(db, escola, b, "MARIA ALICE ALVES PEREIRA")
    _aluno(db, escola, b, "MARIA ALINE ALVES PEREIRA")
    gemea = _aluno(db, escola, b, "MARIA A", lp=False)
    ids = {"escola": escola.id, "oficial": oficial.id, "sombra": sombra.id,
           "gemea": gemea.id}
    db.commit()
    db.close()
    yield Sessao, ids
    engine.dispose()


def _rodar(monkeypatch, capsys, Sessao, *args):
    import scripts.consolidar_sombras as etapa
    monkeypatch.setattr(etapa, "SessionLocal", Sessao)
    monkeypatch.setattr(sys, "argv", ["consolidar_sombras", *args])
    codigo = etapa.main()
    return codigo, capsys.readouterr().out


def _retrato(Sessao):
    with Sessao() as db:
        return (sorted(db.execute(select(Aluno.id)).scalars()),
                db.execute(select(func.count()).select_from(LogAuditoria)).scalar_one())


def _assinatura_da_simulacao(saida: str) -> str:
    [linha] = [l for l in saida.splitlines()
               if l.startswith("assinatura dos pares CONSOLIDAR: ")]
    return linha.split(": ", 1)[1].strip()


def test_script_simulacao_nao_grava_e_so_mostra_ids(banco, monkeypatch, capsys):
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]))
    assert codigo == 0
    assert "CONSOLIDAR 1 · REVISAR 1 · CONFLITO 0" in saida
    assert f"sombra={ids['sombra']} -> oficial={ids['oficial']}" in saida
    assert f"sombra={ids['gemea']}" in saida and "varias_oficiais" in saida
    assert "total de pares CONSOLIDAR: 1" in saida and "nada foi gravado" in saida
    assert len(_assinatura_da_simulacao(saida)) == 12
    assert SOMBRA_Z not in saida and OFICIAL_Z not in saida      # nomes só com --nomes
    assert _retrato(Sessao) == antes

    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--todas", "--nomes")
    assert codigo == 0 and f"«{SOMBRA_Z}» × «{OFICIAL_Z}»" in saida
    assert _retrato(Sessao) == antes


def test_script_esperado_divergente_sai_3_sem_gravar(banco, monkeypatch, capsys):
    Sessao, ids = banco
    import scripts.consolidar_sombras as etapa
    antes = _retrato(Sessao)
    _, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]))
    assinatura = _assinatura_da_simulacao(saida)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]),
                           "--aplicar", "--esperado", "2", "--assinatura", assinatura)
    assert codigo == etapa.SAIDA_ESPERADO_DIVERGENTE == 3
    assert "ABORTADO" in saida and "Nada foi gravado" in saida
    assert _retrato(Sessao) == antes


def test_script_outros_pares_com_o_mesmo_total_sai_3_sem_gravar(banco, monkeypatch, capsys):
    """Entre a conferência e a aplicação um par sai e outro entra — o TOTAL é o
    mesmo, os pares não. A assinatura pega: nada é gravado."""
    Sessao, ids = banco
    import scripts.consolidar_sombras as etapa
    _, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]))
    conferida = _assinatura_da_simulacao(saida)
    with Sessao() as db:                      # o par conferido some, outro aparece
        escola = db.get(Escola, ids["escola"])
        db.get(Aluno, ids["sombra"]).numero_chamada = 3
        db.get(Aluno, ids["oficial"]).numero_chamada = 7
        turma = db.execute(select(Turma).where(Turma.escola_id == escola.id)).scalars().first()
        _aluno(db, escola, turma, "OSVALDINO BRAGANCA DE MELO")
        _aluno(db, escola, turma, "OSVALDINO B", lp=False)
        db.commit()
    antes = _retrato(Sessao)
    _, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]))
    assert "total de pares CONSOLIDAR: 1" in saida
    assert _assinatura_da_simulacao(saida) != conferida
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]),
                           "--aplicar", "--esperado", "1", "--assinatura", conferida)
    assert codigo == etapa.SAIDA_ESPERADO_DIVERGENTE
    assert "ABORTADO" in saida and "os pares mudaram" in saida
    assert _retrato(Sessao) == antes


def test_script_aplicar_com_o_esperado_certo_consolida(banco, monkeypatch, capsys):
    Sessao, ids = banco
    _, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]))
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]),
                           "--aplicar", "--esperado", "1",
                           "--assinatura", _assinatura_da_simulacao(saida))
    assert codigo == 0 and "consolidadas: 1 de 1" in saida
    with Sessao() as db:
        assert db.get(Aluno, ids["sombra"]) is None
        assert db.get(Aluno, ids["gemea"]) is not None             # gêmea: revisão
        [log] = db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "aluno.consolidado_automatico")).scalars().all()
        assert log.detalhes["origem"] == "script" and log.usuario_id is None
    # De novo: nada mais a consolidar.
    _, saida = _rodar(monkeypatch, capsys, Sessao, "--todas")
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--todas",
                           "--aplicar", "--esperado", "0",
                           "--assinatura", _assinatura_da_simulacao(saida))
    assert codigo == 0 and "consolidadas: 0 de 0" in saida


@pytest.mark.parametrize("args, trecho", [
    (["--escola", "1", "--aplicar"], "--aplicar exige --esperado N"),
    (["--escola", "1", "--aplicar", "--esperado", "1"], "--aplicar exige --assinatura A"),
    (["--escola", "1", "--esperado", "3"], "--esperado só vale junto com --aplicar"),
    (["--escola", "1", "--assinatura", "abc"], "--assinatura só vale junto com --aplicar"),
    (["--escola", "1", "--aplicar", "--esperado", "-1", "--assinatura", "abc"],
     "--esperado não pode ser negativo"),
    (["--aplicar", "--esperado", "1"], "one of the arguments --escola --todas is required"),
    (["--escola", "1", "--todas"], "not allowed with argument"),
])
def test_script_recusa_combinacoes_invalidas_sem_abrir_o_banco(args, trecho, capsys,
                                                                monkeypatch):
    import scripts.consolidar_sombras as etapa

    def sem_banco():
        raise AssertionError("não deveria abrir o banco")

    monkeypatch.setattr(etapa, "SessionLocal", sem_banco)
    with pytest.raises(SystemExit) as saida:
        etapa.main(args)
    assert saida.value.code == 2
    assert trecho in capsys.readouterr().err


def test_script_simulacao_no_postgres_exige_transacao_somente_leitura():
    """No Postgres a simulação abre READ ONLY e o banco CONFIRMA; se não
    confirmar, o script não segue. Nos outros dialetos nada é enviado."""
    import scripts.consolidar_sombras as etapa

    class _Sessao:
        def __init__(self, dialeto, resposta="on"):
            self.dialeto, self.resposta, self.executadas = dialeto, resposta, []

        def get_bind(self):
            return type("B", (), {"dialect": type("D", (), {"name": self.dialeto})()})()

        def execute(self, instrucao):
            self.executadas.append(str(instrucao))
            return type("R", (), {"scalar": lambda _s: self.resposta})()

    pg = _Sessao("postgresql")
    assert etapa._abrir_somente_leitura(pg) is True
    assert pg.executadas == ["SET TRANSACTION READ ONLY", "SHOW transaction_read_only"]
    assert etapa._abrir_somente_leitura(_Sessao("postgresql", "off")) is False
    lite = _Sessao("sqlite")
    assert etapa._abrir_somente_leitura(lite) is True and lite.executadas == []


def test_script_aborta_se_a_simulacao_nao_ficou_somente_leitura(banco, monkeypatch, capsys):
    Sessao, ids = banco
    import scripts.consolidar_sombras as etapa
    monkeypatch.setattr(etapa, "_abrir_somente_leitura", lambda db: False)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--escola", str(ids["escola"]))
    assert codigo == etapa.SAIDA_SEM_SOMENTE_LEITURA
    assert "ABORTADO" in saida and "CONSOLIDAR" not in saida
