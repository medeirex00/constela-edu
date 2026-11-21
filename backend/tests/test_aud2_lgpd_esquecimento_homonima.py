"""Exclusão permanente (LGPD) × a pendência de OUTRA criança, homônima (REV2-LGPD-1).

O DEFEITO. A marca de esquecimento (G_LGPD-1) gravava a conta de toda revisão que
``exclusao_aluno._revisao_dela`` considera "dela" só pelo nome (nenhuma ficha
escolhida, o nome igual, nenhum homônimo com ficha). Isso inclui a pendência de
OUTRA criança, de mesmo nome e ainda sem ficha, que o motor mandou para a fila
justamente por dúvida ("homonimo_em_outra_sala"). A conta dela passava a ser
ignorada para sempre na escola: a coleta seguinte não criava a ficha (política
"permitir"), nem a ficha cadastrada à mão recebia o dado, e não há ação para
levantar a marca.

O CONSERTO. Só entra na marca a conta da revisão que PROVA ser da criança: resolvida
para ela, da conta vinculada a ela ou, sem ficha escolhida, a pendência cujo motivo
aponta para a ficha dela como a única correspondência segura
("outra_identidade_na_plataforma", "ficha_inativa", "deixada_para_revisao"), sem
nenhuma ficha viva entre os candidatos. Pendência de dúvida de identidade continua
sendo apagada (tem o nome dela), mas a conta não é marcada.

Base: a variante do revisor (``test_rev2_lgpd_v1.py``). Dados 100% fictícios; sem
rede (o núcleo do /confirmar com os parâmetros da sync).
"""
import pytest
from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna, RevisaoIdentidade, Turma
from app.models.nota import LogAuditoria
from app.routers.importacoes import _confirmar_sem_commit
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import exclusao_aluno, politica_sync
from app.services import identidade_aluno as ida

API = "/api/v1"
NOME = "MARIA HOMONIMA FICTICIA"
CONTA_A = "uuid-ficticio-homonima-a-1"
CONTA_B = "uuid-ficticio-homonima-b-2"


def _linha(nome, conta, turma_nome):
    return LinhaConfirmacao(nome=nome, criar_em_turma_nome=turma_nome, dados={
        "matific_uuid": conta, "turma_relatorio": turma_nome,
        "atividades": 5, "estrelas": 12, "pontuacao_media": 80})


def _coleta(db, escola, admin, linhas):
    """A mesma chamada que ``sync/orchestrator`` faz ao /confirmar."""
    corpo = ImportacaoConfirm(
        plataforma="matific", formato="resumo", tipo="texto", linhas=linhas,
        recalcular=False, sincronizar_turma=True, permitir_criar_turma=False,
        permitir_criar_aluno=politica_sync.pode_criar_aluno(db, escola.id))
    r = _confirmar_sem_commit(dados=corpo, escola_id=escola.id, usuario=admin, db=db)
    db.commit()
    return r


def _excluir(cliente_global, eid, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _marcas(db):
    db.expire_all()
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.excluido_permanente")).scalars().one()
    return {m["marca"] for m in log.detalhes.get("contas_esquecidas") or []}


@pytest.fixture
def homonimas(db, escola_completa):
    """A ficha A (3º Ano A, conta A) e a criança B, de mesmo nome, que chega pela
    coleta no 5º Ano B (conta B) e vai para a fila: "homonimo_em_outra_sala"."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    outra_turma = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano",
                        ano_letivo=2026)
    db.add(outra_turma)
    db.commit()
    _coleta(db, escola, admin, [_linha(NOME, CONTA_A, turma.nome)])
    a_id = db.execute(select(Aluno.id).where(Aluno.nome == NOME)).scalar_one()
    _coleta(db, escola, admin, [_linha(NOME, CONTA_B, outra_turma.nome)])
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.id_externo == CONTA_B)).scalars().one()
    assert (rev.motivo, rev.aluno_escolhido_id) == ("homonimo_em_outra_sala", None)
    assert [c["aluno_id"] for c in rev.candidatos] == [a_id]
    return {"escola": escola, "admin": admin, "a_id": a_id, "outra_turma": outra_turma}


def test_a_conta_da_homonima_na_fila_nao_e_esquecida_junto(db, homonimas, cliente_global):
    escola, admin, outra_turma = (homonimas["escola"], homonimas["admin"],
                                  homonimas["outra_turma"])
    _excluir(cliente_global, escola.id, homonimas["a_id"])

    marcas = _marcas(db)
    assert exclusao_aluno.marca_da_conta("matific", CONTA_A) in marcas
    assert exclusao_aluno.marca_da_conta("matific", CONTA_B) not in marcas, (
        "a conta de OUTRA criança (homônima, na fila) foi marcada como esquecida")
    # A pendência dela tinha o nome da excluída e sai, como antes.
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.id_externo == CONTA_B)).scalars().all() == []

    # A coleta seguinte traz a criança B de volta como qualquer criança nova
    # (política padrão "permitir").
    res = _coleta(db, escola, admin, [_linha(NOME, CONTA_B, outra_turma.nome)])
    db.expire_all()
    fichas = db.execute(select(Aluno.id).where(Aluno.nome == NOME)).scalars().all()
    assert len(fichas) == 1, (fichas, res.avisos, res.ignorados)
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.id_externo == CONTA_B)).scalar_one() == fichas[0]


def test_a_ficha_cadastrada_a_mao_recebe_a_conta_da_homonima(db, homonimas, cliente_global):
    """A escolha explícita de um humano (passo 0 de ``decidir``) associa a conta B à
    ficha nova da B — o passo 00 (conta esquecida) não a barra."""
    escola, outra_turma = homonimas["escola"], homonimas["outra_turma"]
    _excluir(cliente_global, escola.id, homonimas["a_id"])
    b = Aluno(escola_id=escola.id, nome=NOME)
    db.add(b)
    db.commit()
    ctx = ida.carregar_contexto(db, escola.id)
    dec = ida.decidir(ctx, ida.linha_de_dados(NOME, {"matific_uuid": CONTA_B},
                                              plataforma="matific",
                                              turma_nome=outra_turma.nome, aluno_id=b.id))
    assert (dec.acao, dec.aluno_id) == (ida.ASSOCIAR, b.id), (dec.acao, dec.motivo)
    # E a conta A, que era dela, continua esquecida.
    dec_a = ida.decidir(ctx, ida.linha_de_dados(NOME, {"matific_uuid": CONTA_A},
                                                plataforma="matific",
                                                turma_nome="3º Ano A"))
    assert (dec_a.acao, dec_a.motivo) == (ida.IGNORAR, ida.MOTIVO_CONTA_ESQUECIDA)


@pytest.mark.parametrize("motivo", ["candidatos_multiplos", "nome_casa_em_outra_sala",
                                    "criacao_bloqueada_por_politica",
                                    "contas_repetidas_no_relatorio", "sem_turma",
                                    "correspondencia_insegura"])
def test_pendencia_de_duvida_so_pelo_nome_nao_marca_a_conta(
        db, escola_completa, cliente_global, motivo):
    """Os motivos de dúvida de identidade não provam de quem é a conta — nem quando
    a excluída é a candidata. A pendência sai (tem o nome dela); a conta, não."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    _coleta(db, escola, admin, [_linha(NOME, CONTA_A, turma.nome)])
    a_id = db.execute(select(Aluno.id).where(Aluno.nome == NOME)).scalar_one()
    db.add(RevisaoIdentidade(
        escola_id=escola.id, chave=f"k-{motivo}", chave_identidade=f"ci-{motivo}",
        plataforma="matific", id_externo=CONTA_B, nome_recebido=NOME, motivo=motivo,
        status="pendente",
        candidatos=[{"aluno_id": a_id, "nome": NOME, "status": "ativo",
                     "turma": turma.nome}]))
    db.commit()
    _excluir(cliente_global, escola.id, a_id)
    marcas = _marcas(db)
    assert marcas == {exclusao_aluno.marca_da_conta("matific", CONTA_A)}, motivo
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.id_externo == CONTA_B)).scalars().all() == []


@pytest.mark.parametrize("motivo", ["outra_identidade_na_plataforma", "ficha_inativa",
                                    "deixada_para_revisao"])
def test_pendencia_que_aponta_so_para_ela_marca_a_conta(db, escola_completa,
                                                        cliente_global, motivo):
    """O motor achou a ficha dela como a única correspondência segura e só não
    associou pela trava (outra conta, ficha inativa, pedido de revisão): a conta é
    dela e fica esquecida."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    _coleta(db, escola, admin, [_linha(NOME, CONTA_A, turma.nome)])
    a_id = db.execute(select(Aluno.id).where(Aluno.nome == NOME)).scalar_one()
    db.add(RevisaoIdentidade(
        escola_id=escola.id, chave=f"k-{motivo}", chave_identidade=f"ci-{motivo}",
        plataforma="matific", id_externo=CONTA_B, nome_recebido=NOME, motivo=motivo,
        status="pendente",
        candidatos=[{"aluno_id": a_id, "nome": NOME, "status": "ativo",
                     "turma": turma.nome}]))
    db.commit()
    _excluir(cliente_global, escola.id, a_id)
    assert _marcas(db) == {exclusao_aluno.marca_da_conta("matific", CONTA_A),
                           exclusao_aluno.marca_da_conta("matific", CONTA_B)}, motivo


def test_pendencia_que_tambem_aponta_para_ficha_viva_nao_marca(db, escola_completa,
                                                               cliente_global):
    """Com uma ficha que CONTINUA na escola entre os candidatos, a pendência não diz
    de quem é a conta: não entra na marca."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    fica = escola_completa["alunos"][1]
    _coleta(db, escola, admin, [_linha(NOME, CONTA_A, turma.nome)])
    a_id = db.execute(select(Aluno.id).where(Aluno.nome == NOME)).scalar_one()
    db.add(RevisaoIdentidade(
        escola_id=escola.id, chave="k-viva", chave_identidade="ci-viva",
        plataforma="matific", id_externo=CONTA_B, nome_recebido=NOME,
        motivo="outra_identidade_na_plataforma", status="pendente",
        candidatos=[{"aluno_id": a_id, "nome": NOME, "status": "ativo",
                     "turma": turma.nome},
                    {"aluno_id": fica.id, "nome": fica.nome, "status": "ativo",
                     "turma": turma.nome}]))
    db.commit()
    _excluir(cliente_global, escola.id, a_id)
    assert _marcas(db) == {exclusao_aluno.marca_da_conta("matific", CONTA_A)}
