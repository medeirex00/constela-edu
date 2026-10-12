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
    divergência de qualquer um sai 3;
  * (iteração 2) CONTINUIDADE DA CONTA no lugar de "presença = duas contas":
    a oficial com o Matific ligado por nome até 31/07 e a sombra com a conta
    de 01/08 em diante, contadores do limite iguais ou crescentes, consolidam;
    sobreposição de datas, contador que regride, intervalo > 31 dias, dado sem
    snapshot, dado novo na ficha anterior, leitura repetida divergente e conta
    própria da oficial na plataforma são CONFLITO. O nome idêntico com dado só
    consolida continuando dado ANTERIOR da oficial. A forma do nome: sufixo da
    turma ("… 2B"), partícula a menos e vogal acentuada que virou minúscula
    não impedem o par; prenome diferente e gêmeos seguem na revisão mesmo com
    continuidade perfeita. E o risco que a regra não elimina (criança diferente
    cujos contadores começam acima dos da oficial) fica documentado em
    ``test_falsificacao_de_continuidade``.

Nomes FICTÍCIOS, montados para o teste (nenhum é de aluno real). As datas e os
contadores seguem o PADRÃO medido em produção (12/10), não dados de criança.
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
    EventoAluno,
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
    não pode ser fundida — o retrato vigente da criança viraria o da sombra.

    REGRA MUDOU (iteração 2, continuidade da conta): presença de dado nas duas
    fichas já não é, sozinha, "duas contas". Aqui a sombra começa com 5 livros
    depois de a oficial ter 30 — o contador acumulado REGRIDE, então não é a
    mesma conta continuando: segue CONFLITO, agora com o motivo exato."""
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
    assert (item.classe, item.motivo) == (cs.CONFLITO, "contador_regrediu")
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
    irreversível. Com leitura nas duas, as duas têm dado do Elefante: CONFLITO.

    REGRA MUDOU (iteração 2): o motivo agora diz POR QUE não há como provar que
    é a mesma conta — nenhuma das duas tem snapshot do Elefante (só leitura).
    Com snapshots e continuidade, a leitura repetida divergente continua
    CONFLITO (``test_continuidade_com_leitura_repetida_divergente_e_conflito``)."""
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
    assert (item.classe, item.motivo) == (cs.CONFLITO, "continuidade_sem_retrato")
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


# --- 3b. continuidade da conta (iteração 2) --------------------------------------
#
# O padrão medido em produção (12/10), com nomes e números sintéticos: a oficial
# tem o Matific ligado por NOME de 30/04 a 31/07; a sombra tem a conta e os
# snapshots de 01/08 a 01/10. Os contadores acumulados do ano no limite são
# iguais (ou crescem): é a MESMA conta dividida em duas fichas.

OFICIAL_W = "WALDIRENE SOFIA FAGUNDES SILVA"
SOMBRA_W = "WALDIRENE S"
HIST_OFICIAL_W = [("2026-04-30", 4, 12), ("2026-05-31", 9, 27), ("2026-06-30", 15, 48),
                  ("2026-07-31", 23, 70)]
HIST_SOMBRA_W = [("2026-08-01", 23, 70), ("2026-09-01", 31, 101), ("2026-10-01", 38, 126)]


def _snaps(db, escola, aluno, plataforma, serie):
    """Snapshots da ficha: ``serie`` = [(dia, contador1, contador2), …] — no
    Matific (atividades, estrelas), no Elefante (livros, minutos)."""
    imp = _importacao(db, escola, plataforma)
    for dia, c1, c2 in serie:
        quando = datetime.fromisoformat(dia)
        if plataforma == "matific":
            db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                                   importacao_id=imp.id, data_referencia=quando,
                                   atividades=c1, estrelas=c2, pontuacao_media=3.0))
        else:
            db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                    importacao_id=imp.id, data_referencia=quando,
                                    livros_unicos=c1, tempo_leitura_min=c2,
                                    livros_por_nivel={"D": c1}))
    db.flush()


def _evento(db, escola, aluno, plataforma, quando, chave):
    db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id, plataforma=plataforma,
                       tipo_evento="atividade" if plataforma == "matific" else "leitura",
                       ocorrido_em=datetime.fromisoformat(quando), chave_natural=chave))
    db.flush()


def _livro(db, escola, titulo="LIVRO SINTETICO"):
    from app.models import Livro
    livro = Livro(escola_id=escola.id, titulo=titulo, nivel_codigo="D")
    db.add(livro)
    db.flush()
    return livro


def _par(db, esc, *, hist_oficial=HIST_OFICIAL_W, hist_sombra=HIST_SOMBRA_W,
         plataforma="matific", oficial_nome=OFICIAL_W, sombra_nome=SOMBRA_W,
         conta="u-waldirene", turma=None):
    """A oficial com o histórico ligado por nome (sem conta) e a sombra com a
    conta e o histórico dela, na mesma turma."""
    e = esc["escola"]
    turma = turma or esc["b"]
    oficial = _aluno(db, e, turma, oficial_nome, chamada=5)
    sombra = _aluno(db, e, turma, sombra_nome, lp=False)
    if conta:
        _conta(db, e, sombra, plataforma, conta)
    if hist_oficial:
        _snaps(db, e, oficial, plataforma, hist_oficial)
    if hist_sombra:
        _snaps(db, e, sombra, plataforma, hist_sombra)
    db.commit()
    return oficial, sombra


@pytest.mark.parametrize("limite_oficial, limite_sombra, contadores", [
    ((23, 70), (23, 70), "iguais"),           # 9 dos 10 pares medidos
    ((36, 150), (39, 164), "crescentes"),      # o par em que a conta seguiu ativa
])
def test_continuidade_da_conta_consolida_e_registra_o_limite(db, esc, limite_oficial,
                                                             limite_sombra, contadores):
    e = esc["escola"]
    oficial, sombra = _par(
        db, esc, hist_oficial=HIST_OFICIAL_W[:-1] + [("2026-07-31", *limite_oficial)],
        hist_sombra=[("2026-08-01", *limite_sombra)] + HIST_SOMBRA_W[1:])
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial.id)
    assert item.evidencias["relacao_nome"] == "abreviacao"
    continuidade = {
        "ficha_anterior": "oficial",
        "ultimo_retrato_anterior": "2026-07-31",
        "primeiro_retrato_posterior": "2026-08-01",
        "dias_entre": 1,
        "contadores": contadores,
        "contadores_anterior": dict(zip(("atividades", "estrelas"), limite_oficial)),
        "contadores_posterior": dict(zip(("atividades", "estrelas"), limite_sombra)),
    }
    assert item.evidencias["continuidade"] == {"matific": continuidade}

    res = _aplicar(db, e)
    assert [x["sombra_id"] for x in res["consolidados"]] == [sombra.id]
    assert not _existe(db, sombra.id)
    assert _dono(db, e, "matific", "u-waldirene") == oficial.id
    # O histórico inteiro, das duas fichas, fica na oficial — contínuo.
    assert len(db.execute(select(SnapshotMatific.id).where(
        SnapshotMatific.aluno_id == oficial.id)).scalars().all()) == 7
    nota = db.execute(select(Nota).where(Nota.aluno_id == oficial.id)).scalar_one()
    assert nota.aferido_matematica
    [log] = _logs(db, "aluno.consolidado_automatico")
    assert log.detalhes["evidencias"]["continuidade"] == {"matific": continuidade}
    texto = json.dumps(log.detalhes, ensure_ascii=False)
    assert OFICIAL_W not in texto and SOMBRA_W not in texto        # só datas e números


@pytest.mark.parametrize("hist_oficial", [
    # A oficial seguiu recebendo dado depois que a sombra começou.
    HIST_OFICIAL_W + [("2026-08-05", 25, 75)],
    # O mesmo dia nas duas fichas já é simultâneo.
    HIST_OFICIAL_W[:-1] + [("2026-08-01", 23, 70)],
])
def test_retratos_que_se_sobrepoem_sao_conflito(db, esc, hist_oficial):
    e = esc["escola"]
    _oficial, sombra = _par(db, esc, hist_oficial=hist_oficial)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "dados_simultaneos_mesma_plataforma")
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


@pytest.mark.parametrize("limite_sombra", [(23, 69), (22, 80), (0, 0)])
def test_contador_que_regride_no_limite_e_conflito(db, esc, limite_sombra):
    e = esc["escola"]
    _oficial, sombra = _par(db, esc, hist_sombra=[("2026-08-01", *limite_sombra)])
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "contador_regrediu")


@pytest.mark.parametrize("ultimo_da_oficial, classe, motivo", [
    ("2026-06-30", cs.CONFLITO, "intervalo_longo"),       # 32 dias até 01/08
    ("2026-07-01", cs.CONSOLIDAR, ""),                    # 31 dias: o limite aceito
])
def test_intervalo_maior_que_31_dias_e_conflito(db, esc, ultimo_da_oficial, classe, motivo):
    e = esc["escola"]
    _oficial, sombra = _par(db, esc, hist_oficial=[("2026-04-30", 4, 12),
                                                   (ultimo_da_oficial, 23, 70)])
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (classe, motivo)
    if classe == cs.CONSOLIDAR:
        assert item.evidencias["continuidade"]["matific"]["dias_entre"] == 31


@pytest.mark.parametrize("caso", ["oficial_so_com_evento", "oficial_so_com_leitura",
                                  "sombra_so_com_conta"])
def test_dado_sem_snapshot_nao_prova_continuidade(db, esc, caso):
    """Leitura e evento soltos (ou a conta sem retrato) não têm contador com que
    provar que é a mesma conta: CONFLITO, sem fundir nada."""
    e = esc["escola"]
    plataforma = "elefante" if caso == "oficial_so_com_leitura" else "matific"
    hist_elefante = [("2026-08-01", 12, 300), ("2026-09-01", 15, 360)]
    oficial, sombra = _par(
        db, esc, plataforma=plataforma, conta="4416001" if plataforma == "elefante"
        else "u-waldirene",
        hist_oficial=None if caso != "sombra_so_com_conta" else HIST_OFICIAL_W,
        hist_sombra=(None if caso == "sombra_so_com_conta"
                     else hist_elefante if plataforma == "elefante" else HIST_SOMBRA_W))
    if caso == "oficial_so_com_evento":
        _evento(db, e, oficial, "matific", "2026-07-10T10:00:00", "evt-oficial-1")
    elif caso == "oficial_so_com_leitura":
        _leitura(db, e, oficial, _livro(db, e), datetime(2026, 7, 10, 10, 0))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "continuidade_sem_retrato")
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


@pytest.mark.parametrize("plataforma, quando", [
    ("matific", "2026-08-15T10:00:00"),    # evento da oficial depois de a sombra começar
    ("matific", "2026-08-01T07:00:00"),    # no mesmo dia do 1º retrato da sombra
    ("elefante", "2026-08-10T09:00:00"),   # leitura da oficial depois de a sombra começar
])
def test_dado_novo_na_ficha_anterior_e_conflito(db, esc, plataforma, quando):
    """(v): os snapshots não se sobrepõem, mas a oficial ainda recebeu dado da
    plataforma depois de a sombra começar — duas fontes ao mesmo tempo."""
    e = esc["escola"]
    if plataforma == "matific":
        oficial, sombra = _par(db, esc)
        _evento(db, e, oficial, "matific", quando, "evt-oficial-tardio")
    else:
        oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416002",
                               hist_oficial=[("2026-07-13", 120, 180), ("2026-07-31", 129, 200)],
                               hist_sombra=[("2026-08-01", 135, 220)])
        _leitura(db, e, oficial, _livro(db, e), datetime.fromisoformat(quando))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "dados_simultaneos_mesma_plataforma")


@pytest.mark.parametrize("status", ["efetiva", "aposentada"])
def test_oficial_com_conta_propria_na_plataforma_e_conflito_mesmo_continuo(db, esc, status):
    """Continuidade perfeita nos snapshots, mas a OFICIAL tem conta própria no
    Matific: são duas contas reais — qual é a da criança, gente decide."""
    e = esc["escola"]
    oficial, sombra = _par(db, esc)
    _conta(db, e, oficial, "matific", "u-conta-da-oficial", status=status)
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.CONFLITO, "duas_contas_mesma_plataforma")


@pytest.mark.parametrize("copia_identica", [True, False])
def test_continuidade_com_leitura_repetida_divergente_e_conflito(db, esc, copia_identica):
    """Mesmo com a conta continuando, o MESMO livro nas duas fichas com data ou
    tempo diferentes seria descartado na fusão (uma leitura por livro): CONFLITO.
    A cópia idêntica da mesma leitura (a plataforma reenviou o histórico da
    conta) não perde nada e consolida."""
    from app.models import Leitura
    e = esc["escola"]
    oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416003",
                           hist_oficial=[("2026-07-13", 120, 180), ("2026-07-31", 129, 200)],
                           hist_sombra=[("2026-08-01", 135, 220), ("2026-09-17", 140, 250)])
    livro = _livro(db, e)
    db.add(Leitura(escola_id=e.id, aluno_id=oficial.id, livro_id=livro.id,
                   data=datetime(2026, 7, 20, 10, 0), tempo_leitura_min=12))
    db.add(Leitura(escola_id=e.id, aluno_id=sombra.id, livro_id=livro.id,
                   data=datetime(2026, 7, 20, 10, 0) if copia_identica
                   else datetime(2026, 8, 6, 10, 0), tempo_leitura_min=12))
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    if not copia_identica:
        assert (item.classe, item.motivo) == (cs.CONFLITO, "leitura_repetida_nas_duas_fichas")
        assert _aplicar(db, e)["consolidados"] == []
        db.expire_all()
        assert len(db.execute(select(Leitura.id)).scalars().all()) == 2
        return
    assert item.classe == cs.CONSOLIDAR
    assert item.evidencias["continuidade"]["elefante"]["contadores"] == "crescentes"
    assert len(_aplicar(db, e)["consolidados"]) == 1
    db.expire_all()
    assert db.execute(select(Leitura.aluno_id, Leitura.data)).all() == [
        (oficial.id, datetime(2026, 7, 20, 10, 0))]


def test_sombra_de_nome_identico_do_elefante_com_continuidade_consolida(db, esc):
    """O caso real: a MESMA oficial tem a sombra truncada do Matific e uma sombra
    de nome IDÊNTICO criada pelo Elefante. A oficial tinha o Elefante por nome
    (13/07–31/07) e o Matific por nome (abr–jul); cada sombra continua uma das
    contas a partir de 01/08. As duas consolidam."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, "HELOIZA BEATRIZ NOGUEIRA PRATES", chamada=8)
    truncada = _aluno(db, e, b, "HELOIZA B", lp=False)
    identica = _aluno(db, e, b, "HELOIZA BEATRIZ NOGUEIRA PRATES", lp=False)
    _conta(db, e, truncada, "matific", "u-heloiza")
    _conta(db, e, identica, "elefante", "4416004")
    _snaps(db, e, oficial, "matific", HIST_OFICIAL_W)
    _snaps(db, e, oficial, "elefante", [("2026-07-13", 120, 180), ("2026-07-31", 129, 200)])
    _snaps(db, e, truncada, "matific", HIST_SOMBRA_W)
    _snaps(db, e, identica, "elefante", [("2026-08-01", 135, 220), ("2026-09-17", 150, 270)])
    db.commit()
    plano = cs.planejar(db, e.id)
    item = _item(plano, identica)
    assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial.id)
    assert item.evidencias["relacao_nome"] == "nome_identico"
    ev = item.evidencias["continuidade"]["elefante"]
    assert (ev["ficha_anterior"], ev["contadores"], ev["contadores_anterior"]["livros_unicos"],
            ev["contadores_posterior"]["livros_unicos"]) == ("oficial", "crescentes", 129, 135)
    assert _item(plano, truncada).classe == cs.CONSOLIDAR
    res = _aplicar(db, e, plano)
    assert sorted(x["sombra_id"] for x in res["consolidados"]) == sorted(
        [truncada.id, identica.id])
    assert res["pulados"] == []
    assert _dono(db, e, "matific", "u-heloiza") == oficial.id
    assert _dono(db, e, "elefante", "4416004") == oficial.id
    assert set(db.execute(select(SnapshotElefante.aluno_id)).scalars()) == {oficial.id}


@pytest.mark.parametrize("caso", ["oficial_sem_dado_na_plataforma", "sombra_veio_antes"])
def test_nome_identico_sem_dado_anterior_da_oficial_continua_revisao(db, esc, caso):
    """Regra (e): o nome idêntico com dado só é a sombra se continua dado
    ANTERIOR da oficial na mesma plataforma. A oficial só com Matific (e a
    sombra com o Elefante), ou a sombra com o Elefante ANTES da oficial: pode
    ser outra criança de mesmo nome → revisão."""
    e = esc["escola"]
    nome = "LAURINDA GOMES DA SILVA"
    if caso == "oficial_sem_dado_na_plataforma":
        oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416005",
                               oficial_nome=nome + "*", sombra_nome=nome, hist_oficial=None,
                               hist_sombra=[("2026-08-01", 10, 60)])
        _snaps(db, e, oficial, "matific", HIST_OFICIAL_W)
    else:
        oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416005",
                               oficial_nome=nome + "*", sombra_nome=nome,
                               hist_oficial=[("2026-08-01", 12, 80)],
                               hist_sombra=[("2026-06-30", 8, 40), ("2026-07-31", 10, 60)])
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo, item.oficial_id) == (
        cs.REVISAR, "nome_identico_com_conta", oficial.id)
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


def test_duas_sombras_que_dividem_plataforma_so_passam_com_continuidade(db, esc):
    """A mesma lógica entre duas SOMBRAS da mesma oficial: uma tem o Matific por
    nome (jun–jul, sem conta), a outra a conta a partir de 01/08. Continuidade
    entre elas → as duas consolidam, uma depois da outra."""
    e, b = esc["escola"], esc["b"]
    oficial = _aluno(db, e, b, "QUITERIA HELENA BARROS", chamada=14)
    por_nome = _aluno(db, e, b, "QUITERIA H", lp=False)
    com_conta = _aluno(db, e, b, "QUITERIA HELENA B", lp=False)
    _conta(db, e, com_conta, "matific", "u-quiteria")
    _snaps(db, e, por_nome, "matific", HIST_OFICIAL_W[2:])
    _snaps(db, e, com_conta, "matific", HIST_SOMBRA_W)
    db.commit()
    plano = cs.planejar(db, e.id)
    for s, outra in ((por_nome, com_conta), (com_conta, por_nome)):
        item = _item(plano, s)
        assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial.id)
        [ev] = item.evidencias["continuidade_entre_sombras"]
        assert (ev["sombra_id"], ev["plataforma"], ev["contadores"]) == (
            outra.id, "matific", "iguais")
    res = _aplicar(db, e, plano)
    assert {x["sombra_id"] for x in res["consolidados"]} == {por_nome.id, com_conta.id}
    assert res["pulados"] == []
    assert _dono(db, e, "matific", "u-quiteria") == oficial.id


def test_duas_sombras_que_dividem_plataforma_sem_continuidade_sao_conflito(db, esc):
    e, b = esc["escola"], esc["b"]
    _aluno(db, e, b, "QUITERIA HELENA BARROS", chamada=14)
    por_nome = _aluno(db, e, b, "QUITERIA H", lp=False)
    com_conta = _aluno(db, e, b, "QUITERIA HELENA B", lp=False)
    _conta(db, e, com_conta, "matific", "u-quiteria")
    _snaps(db, e, por_nome, "matific", HIST_OFICIAL_W + [("2026-08-20", 30, 90)])
    _snaps(db, e, com_conta, "matific", HIST_SOMBRA_W)
    db.commit()
    plano = cs.planejar(db, e.id)
    for s, outra in ((por_nome, com_conta), (com_conta, por_nome)):
        assert (_item(plano, s).classe, _item(plano, s).motivo,
                _item(plano, s).relacionados) == (
            cs.CONFLITO, "dados_simultaneos_mesma_plataforma", (outra.id,))
    assert _aplicar(db, e, plano)["consolidados"] == []


# --- 3c. a forma do nome (iteração 2) ---------------------------------------------

ARTEMISIA = "ARTEMISIA ELIZA FERNANDES ROSA"
HIST_ELEFANTE_OFICIAL = [("2026-07-13", 40, 90), ("2026-07-31", 44, 101)]
HIST_ELEFANTE_SOMBRA = [("2026-08-01", 44, 101), ("2026-09-17", 51, 130)]


@pytest.mark.parametrize("turma_nome, ano_escolar, nome_sombra", [
    ("2º Ano B", "2º Ano", ARTEMISIA + " 2B"),
    ("2º Ano A", "2º Ano", ARTEMISIA + " 2a"),
    ("5º Ano A", "5º Ano", ARTEMISIA + " 5A"),
    ("4º Ano A", "4º Ano", ARTEMISIA + "4A"),            # grudado no último nome
])
def test_sufixo_da_turma_no_nome_da_sombra_nao_impede_o_par(db, esc, turma_nome,
                                                            ano_escolar, nome_sombra):
    """A sombra criada pelo Elefante com a turma digitada junto do nome: sem o
    sufixo da PRÓPRIA sala, é o nome idêntico ao da oficial — e consolida com a
    continuidade do Elefante (regra (e))."""
    e = esc["escola"]
    turma = {"2º Ano B": esc["b"], "4º Ano A": esc["a4"]}.get(turma_nome) or _turma(
        db, e, turma_nome, ano_escolar)
    oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416006",
                           oficial_nome=ARTEMISIA, sombra_nome=nome_sombra, turma=turma,
                           hist_oficial=HIST_ELEFANTE_OFICIAL,
                           hist_sombra=HIST_ELEFANTE_SOMBRA)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial.id)
    assert item.evidencias["relacao_nome"] == "nome_identico"
    assert item.evidencias["nome_normalizado"] == ["sufixo_da_turma"]
    assert len(_aplicar(db, e)["consolidados"]) == 1 and not _existe(db, sombra.id)
    db.expire_all()
    assert db.get(Aluno, oficial.id).nome == ARTEMISIA       # o nome oficial não muda


def test_sufixo_de_outra_sala_fica_no_nome(db, esc):
    """"… 3A" na 2ºB não é a turma da sombra: o token fica (como no motor) e o par
    segue para a revisão de sempre."""
    e = esc["escola"]
    _oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416007",
                            oficial_nome=ARTEMISIA, sombra_nome=ARTEMISIA + " 3A",
                            hist_oficial=HIST_ELEFANTE_OFICIAL,
                            hist_sombra=HIST_ELEFANTE_SOMBRA)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.REVISAR, "nome_parecido_na_turma")


@pytest.mark.parametrize("com_dado", [False, True])
def test_particula_a_menos_e_o_mesmo_nome(db, esc, com_dado):
    """"… SOARES SANTOS" × "… SOARES DOS SANTOS*": a partícula não distingue
    ninguém. Sem dado, consolida como nome idêntico; com dado, consolida com a
    continuidade da oficial (regra (e))."""
    e = esc["escola"]
    oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416008" if com_dado else None,
                           oficial_nome="TELMO LUCAS SOARES DOS SANTOS*",
                           sombra_nome="TELMO LUCAS SOARES SANTOS",
                           hist_oficial=HIST_ELEFANTE_OFICIAL if com_dado else None,
                           hist_sombra=HIST_ELEFANTE_SOMBRA if com_dado else None)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial.id)
    assert item.evidencias["relacao_nome"] == "nome_identico"
    assert item.evidencias["nome_normalizado"] == ["particulas"]
    assert len(_aplicar(db, e)["consolidados"]) == 1


def test_particula_a_menos_com_conta_e_sem_dado_da_oficial_vai_para_revisao(db, esc):
    e = esc["escola"]
    _oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416009",
                            oficial_nome="TELMO LUCAS SOARES DOS SANTOS*",
                            sombra_nome="TELMO LUCAS SOARES SANTOS", hist_oficial=None,
                            hist_sombra=HIST_ELEFANTE_SOMBRA)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.REVISAR, "nome_identico_com_conta")


@pytest.mark.parametrize("nome_sombra", [
    "SAMANTA INOCeNCIO MAGALHaES",            # a vogal acentuada virou minúscula
    "SAMANTA INOCeNCIO MAGALHaES 2B",         # … e com o sufixo da turma
])
def test_vogal_acentuada_que_virou_minuscula_e_o_mesmo_nome(db, esc, nome_sombra):
    e = esc["escola"]
    oficial, sombra = _par(db, esc, plataforma="elefante", conta="4416010",
                           oficial_nome="SAMANTA INOCÊNCIO MAGALHÃES", sombra_nome=nome_sombra,
                           hist_oficial=HIST_ELEFANTE_OFICIAL,
                           hist_sombra=HIST_ELEFANTE_SOMBRA)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.oficial_id, item.evidencias["relacao_nome"]) == (
        cs.CONSOLIDAR, oficial.id, "nome_identico")


@pytest.mark.parametrize("oficial_nome, sombra_nome, motivo", [
    ("GABRIELA TEODORO MASCARENHAS", "GABRIEL TEODORO MASCARENHAS", "prenome_diferente"),
    ("OTAVIANO RICARDO BRAGANCA MELO", "OTAVIANA R", "nome_parecido_na_turma"),
    ("KETLIN SOFIA FALCAO", "KETLYN SOFIA FALCAO", "nome_parecido_na_turma"),
    ("KETLIN SOFIA FALCAO", "KETLYN S", "nome_parecido_na_turma"),
])
def test_prenome_diferente_continua_revisao_mesmo_com_continuidade_perfeita(
        db, esc, oficial_nome, sombra_nome, motivo):
    """Decisão 3 do dono: o PRENOME diferente é revisão manual — e a
    continuidade dos dados não muda isso (irmãos dividem tablet e turma)."""
    e = esc["escola"]
    oficial, sombra = _par(db, esc, oficial_nome=oficial_nome, sombra_nome=sombra_nome)
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.REVISAR, motivo)
    assert oficial.id in ((item.oficial_id,) + item.relacionados)
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


def test_gemeos_com_continuidade_perfeita_continuam_revisao(db, esc):
    e, b = esc["escola"], esc["b"]
    alice = _aluno(db, e, b, "MARIA ALICE ALVES PEREIRA", chamada=1)
    aline = _aluno(db, e, b, "MARIA ALINE ALVES PEREIRA", chamada=2)
    sombra = _aluno(db, e, b, "MARIA A", lp=False)
    _conta(db, e, sombra, "matific", "u-maria-a")
    _snaps(db, e, alice, "matific", HIST_OFICIAL_W)
    _snaps(db, e, sombra, "matific", HIST_SOMBRA_W)
    db.commit()
    item = _item(cs.planejar(db, e.id), sombra)
    assert (item.classe, item.motivo) == (cs.REVISAR, "varias_oficiais")
    assert set(item.relacionados) == {alice.id, aline.id}
    assert _aplicar(db, e)["consolidados"] == [] and _existe(db, sombra.id)


# --- 3d. o risco que a continuidade não elimina -----------------------------------

@pytest.mark.parametrize("inicio_da_outra, classe, motivo", [
    # A conta NOVA de outra criança começa do zero, abaixo da oficial: protegido.
    ((2, 5), cs.CONFLITO, "contador_regrediu"),
    # A outra criança já usava o Matific (outra escola, conta antiga) e começa
    # ACIMA da oficial: os dados não a distinguem da mesma conta continuando.
    ((40, 130), cs.CONSOLIDAR, ""),
])
def test_falsificacao_de_continuidade(db, esc, inicio_da_outra, classe, motivo):
    """FALSIFICAÇÃO: uma criança DIFERENTE — fora da Lista Piloto, na mesma
    turma, com nome que é a forma do relatório do nome da oficial — cuja conta
    passa a mandar dados depois que a oficial parou (05/08, quatro dias depois
    do último retrato da oficial).

    O que a regra faz: com contadores ABAIXO dos da oficial (a conta nova de
    outra criança), o contador regride → CONFLITO. Com contadores IGUAIS ou
    MAIORES, a continuidade é aceita e o par CONSOLIDA: datas e contadores
    acumulados não distinguem a mesma conta continuando de outra conta que, por
    acaso, já estava acima. É um RISCO ACEITO, não escondido: o que segura esse
    caso é o resto da regra — o nome tem de ser a forma do relatório do nome da
    oficial NA MESMA TURMA, nenhuma outra ficha da escola pode ser a dona, a
    criança de verdade não está na Lista Piloto (senão seriam duas oficiais) —
    e a política da escola começa em "manual". A auditoria guarda os
    contadores dos dois lados do limite para quem precisar desfazer."""
    e = esc["escola"]
    oficial, outra = _par(db, esc, oficial_nome="CLEMENTINA ROSA VASCONCELOS",
                          sombra_nome="CLEMENTINA R", conta="u-outra-crianca",
                          hist_oficial=[("2026-05-31", 6, 20), ("2026-07-31", 12, 39)],
                          hist_sombra=[("2026-08-05", *inicio_da_outra),
                                       ("2026-09-05", inicio_da_outra[0] + 9,
                                        inicio_da_outra[1] + 30)])
    item = _item(cs.planejar(db, e.id), outra)
    assert (item.classe, item.motivo, item.oficial_id) == (classe, motivo, oficial.id)
    if classe == cs.CONSOLIDAR:
        ev = item.evidencias["continuidade"]["matific"]
        assert (ev["dias_entre"], ev["contadores"]) == (5, "crescentes")
        assert ev["contadores_anterior"] == {"atividades": 12, "estrelas": 39}
        assert ev["contadores_posterior"] == {"atividades": 40, "estrelas": 130}


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


def test_script_linha_do_consolidar_mostra_a_continuidade(db, esc):
    """A conferência antes de --aplicar vê a continuidade de cada par (dias do
    limite, intervalo, iguais/crescentes) — sem nome e só com ASCII na seta."""
    import scripts.consolidar_sombras as etapa
    _oficial, sombra = _par(db, esc)
    item = _item(cs.planejar(db, esc["escola"].id), sombra)
    linha = etapa._linha(db, item, False)
    assert "continuidade: matific oficial 2026-07-31->2026-08-01 (1d) iguais" in linha
    assert SOMBRA_W not in linha and OFICIAL_W not in linha
    linha.encode("ascii")


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
