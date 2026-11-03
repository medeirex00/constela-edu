"""D10 (risco V) pela FICHA — revisão de integração do e97 (auth-escopo, provas 1 e
3, invertidas como regressão).

A regra única do D10 (``identidade_aluno.efetivas_em_outra_escola``) descarta de
propósito a identidade presa a uma ficha EXCLUÍDA: excluída a ficha na escola A, a
escola B vincula a mesma conta sem trava, e isso está certo. Mas QUALQUER saída de
"excluido" faz a conta voltar a valer em A — ela ficava efetiva nas duas escolas,
sem Admin Global, sem aviso e sem auditoria, e a criança de B parava de ser
atualizada (revisão ``identidade_de_outra_escola`` na coleta seguinte de B).

Agora (``identidade_efetiva.trava_ficha_sai_de_excluido`` e
``contas_de_outra_escola_da_ficha``):
  * ``/alunos/acoes`` (reativar, arquivar, marcar_transferido de ficha excluída):
    403 para a gestão da escola (admin ou coordenação), nada muda; o Admin Global
    segue, com ``avisos`` e a auditoria ``aluno.reativacao_outra_escola_confirmada``;
  * Lista Piloto (reativação AUTOMÁTICA pelo RA): a ficha NÃO é reativada e a linha
    não altera nada, com aviso e a auditoria
    ``aluno.reativacao_retida_conta_de_outra_escola`` — para qualquer usuário; as
    outras linhas seguem, e a reativação acontece no envio seguinte quando a conta
    deixa de valer na outra escola.

Dados 100% fictícios (nomes de escola e de criança inventados); sem rede.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.core.security import hash_senha
from app.models import Aluno, IdentidadeExterna, Usuario
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotMatific
from app.services import identidade_aluno as ida

API = "/api/v1"
U = "u-ficticia-d10-ficha-excluida"
K = "3 ANO A (300396804)"
AVISO = "continua vinculada a um aluno de outra escola"
AUD_CONFIRMADA = "aluno.reativacao_outra_escola_confirmada"
AUD_RETIDA = "aluno.reativacao_retida_conta_de_outra_escola"
NOME_B = "Crianca Ficticia Da Escola B"


def _nova_escola(db):
    from tests.test_sync_escola_cruzada import _nova_escola as nova

    return nova(db, nome="ESCOLA FICTICIA B DO D10", com_alunos=(NOME_B,))


def _cliente_de(email):
    from tests.test_sync_escola_externa_decisoes import _cliente_de as cliente

    return cliente(email)


def _efetivas(db, eid):
    db.expire_all()
    return ida.efetivas_em_outra_escola(db, eid, "matific", [U])


def _auditoria(db, *, contendo=None, acao=None):
    db.expire_all()
    linhas = db.execute(select(LogAuditoria).order_by(LogAuditoria.id)).scalars().all()
    if acao is not None:
        return [a for a in linhas if a.acao == acao]
    return [a for a in linhas if contendo in a.acao]


def _acao(cliente, eid, ids, acao):
    return cliente.post(f"{API}/escolas/{eid}/alunos/acoes",
                        json={"aluno_ids": list(ids), "acao": acao})


def _status(db, aluno_id):
    db.expire_all()
    return db.get(Aluno, aluno_id).status


def _cena(db, escola_completa, cliente, idx=0):
    """A escola A (escola_completa) tem a conta U efetiva na ficha X; a gestão de A
    exclui X (a criança saiu); a escola B vincula U à ficha Y dela (legítimo: U
    deixou de ser "de outra escola"). Devolve (e1, x, e2, y)."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][idx]
    db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    assert _acao(cliente, e1, [x.id], "excluir").status_code == 200
    escola_b, _t, (y,) = _nova_escola(db)
    e2 = escola_b.id
    assert _efetivas(db, e2) == {}
    db.add(IdentidadeExterna(escola_id=e2, aluno_id=y.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    assert _efetivas(db, e1) == {U: e2} and _efetivas(db, e2) == {}
    return e1, x, e2, y


def _importar_b_sem_ficha(cliente_b, e2, estrelas):
    """Coleta/importação de B sem ficha escolhida (como a sincronização)."""
    linha = {"nome": NOME_B,
             "dados": {"matific_uuid": U, "estrelas": estrelas, "atividades": 10,
                       "pontuacao_media": 80, "turma_relatorio": K}}
    return cliente_b.post(f"{API}/escolas/{e2}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "recalcular": False, "linhas": [linha]})


# ===========================================================================
# /alunos/acoes — ações explícitas da gestão
# ===========================================================================
@pytest.mark.parametrize("acao", ["reativar", "arquivar", "marcar_transferido"])
def test_gestao_nao_tira_de_excluido_ficha_com_conta_efetiva_em_outra_escola(
        db, escola_completa, cliente, acao):
    """Prova auth-escopo 1 e 3c invertidas: o admin da escola A (não global) não
    tira a ficha de "excluido" por nenhum ramo de status — 403, nada muda, a conta
    continua valendo só em B e a criança de B continua sendo atualizada."""
    e1, x, e2, y = _cena(db, escola_completa, cliente)
    r = _acao(cliente, e1, [x.id], acao)
    assert r.status_code == 403, r.text
    detalhe = r.json()["detail"]
    assert "Admin Global" in detalhe and "Nenhum aluno foi alterado" in detalhe
    assert x.nome in detalhe and NOME_B not in detalhe       # nada da outra escola
    assert _status(db, x.id) == "excluido"
    assert _efetivas(db, e2) == {} and _efetivas(db, e1) == {U: e2}
    assert _auditoria(db, contendo="outra_escola") == []
    assert _auditoria(db, acao=f"aluno.{acao}") == []

    # Efeito invertido (risco V): a coleta seguinte de B continua aplicando.
    r = _importar_b_sem_ficha(_cliente_de(f"admin{e2}@teste.local"), e2, 60)
    assert r.status_code == 200, r.text
    assert r.json()["ids_de_outra_escola"] == []
    db.expire_all()
    assert max(s.estrelas for s in db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == y.id)).scalars()) == 60


def test_coordenacao_tambem_recebe_403(db, escola_completa, cliente):
    """Prova auth-escopo 3a invertida: a coordenadora de A (nem admin, nem
    global) também é barrada."""
    e1, x, e2, _y = _cena(db, escola_completa, cliente, idx=1)
    db.add(Usuario(escola_id=e1, nome="Coordenadora Ficticia", email="coord.d10@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    r = _acao(_cliente_de("coord.d10@teste.local"), e1, [x.id], "reativar")
    assert r.status_code == 403, r.text
    assert _status(db, x.id) == "excluido"
    assert _efetivas(db, e2) == {}


def test_acao_em_massa_com_uma_ficha_travada_e_recusada_inteira(db, escola_completa,
                                                               cliente):
    """Nada muda quando a trava acusa: nem a ficha travada, nem as outras da
    seleção (a resposta não é parcial)."""
    e1, x, e2, _y = _cena(db, escola_completa, cliente)
    z = escola_completa["alunos"][2]
    assert _acao(cliente, e1, [z.id], "excluir").status_code == 200
    r = _acao(cliente, e1, [x.id, z.id], "reativar")
    assert r.status_code == 403, r.text
    assert (_status(db, x.id), _status(db, z.id)) == ("excluido", "excluido")
    assert _efetivas(db, e2) == {}


def test_admin_global_tira_de_excluido_com_aviso_e_auditoria(db, escola_completa, cliente,
                                                            cliente_global):
    """Controle do D10: o Admin Global decide — segue, com o aviso na resposta e a
    auditoria própria (sem nome); a outra escola não é alterada."""
    e1, x, e2, y = _cena(db, escola_completa, cliente)
    r = _acao(cliente_global, e1, [x.id], "reativar")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert sum(AVISO in a for a in corpo["avisos"]) == 1, corpo
    assert corpo["afetados"] == 1
    assert _status(db, x.id) == "ativo"
    assert _efetivas(db, e2) == {U: e1}                 # a decisão consciente do global
    [aud] = _auditoria(db, acao=AUD_CONFIRMADA)
    assert (aud.escola_id, aud.entidade, aud.entidade_id) == (e1, "aluno", x.id)
    assert aud.usuario_id is not None
    assert aud.detalhes["plataforma"] == "matific" and aud.detalhes["id_externo"] == U
    assert aud.detalhes["outra_escola_id"] == e2
    assert (aud.detalhes["acao"], aud.detalhes["status_novo"]) == ("reativar", "ativo")
    assert x.nome not in str(aud.detalhes) and NOME_B not in str(aud.detalhes)
    assert len(_auditoria(db, acao="aluno.reativar")) == 1
    db.expire_all()
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == e2,
        IdentidadeExterna.id_externo == U)).scalar_one() == y.id


@pytest.mark.parametrize("caso", ["conta_so_daqui", "conta_aposentada_aqui"])
def test_ficha_excluida_sem_conta_valendo_em_outra_escola_reativa_com_a_gestao(
        db, escola_completa, cliente, caso):
    """Controles: sem conta da ficha efetiva em outra escola, a gestão reativa como
    antes (200, avisos vazio, sem auditoria do D10). A conta APOSENTADA aqui não
    volta a valer com a ficha (tem trava própria), então não trava a ficha."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][0]
    if caso == "conta_so_daqui":
        db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                                 id_externo="u-ficticia-so-daqui"))
    else:
        db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                                 id_externo=U, status="aposentada"))
        db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                                 id_externo="u-ficticia-efetiva-daqui"))
        _b, _t, (y,) = _nova_escola(db)
        db.add(IdentidadeExterna(escola_id=_b.id, aluno_id=y.id, plataforma="matific",
                                 id_externo=U))
    db.commit()
    assert _acao(cliente, e1, [x.id], "excluir").status_code == 200
    r = _acao(cliente, e1, [x.id], "reativar")
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _status(db, x.id) == "ativo"
    assert _auditoria(db, contendo="outra_escola") == []


def test_ficha_que_nao_esta_excluida_nao_passa_pela_trava(db, escola_completa, cliente):
    """Só a saída de "excluido" muda a efetividade: a ficha ARQUIVADA já conta como
    efetiva (a regra única só descarta a excluída), então reativá-la não faz conta
    nenhuma passar a valer — segue com a gestão, sem aviso."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][0]
    _b, _t, (y,) = _nova_escola(db)
    db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                             id_externo=U))
    db.add(IdentidadeExterna(escola_id=_b.id, aluno_id=y.id, plataforma="matific",
                             id_externo=U))                  # legado: já vale nas duas
    db.commit()
    assert _acao(cliente, e1, [x.id], "arquivar").status_code == 200
    r = _acao(cliente, e1, [x.id], "reativar")
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _status(db, x.id) == "ativo"


# ===========================================================================
# Lista Piloto — reativação AUTOMÁTICA pelo RA
# ===========================================================================
def _lista():
    from tests.test_aluno_transferido import _linha, _planilha

    return _planilha(("3º Ano B", [
        _linha("HELENA FICTICIA RAMOS", numero=1, ra="222.200.001-0",
               nasc=date(2017, 5, 1)),
        _linha("OTAVIO FICTICIO LIMA", numero=2, ra="222.200.002-0",
               nasc=date(2017, 6, 2)),
    ]))


def _cena_lista(db, escola_completa, cliente):
    """A importa a Lista Piloto; a ficha da Helena tem a conta U; A exclui a Helena
    e o Otávio (este sem conta); B vincula U à ficha dela. Devolve (e1, h, o, e2, y)."""
    from tests.test_aluno_transferido import _confirmar, _por_nome

    e1 = escola_completa["escola"].id
    _confirmar(cliente, e1, _lista())
    h = _por_nome(db, e1, "HELENA FICTICIA RAMOS")
    o = _por_nome(db, e1, "OTAVIO FICTICIO LIMA")
    db.add(IdentidadeExterna(escola_id=e1, aluno_id=h.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    assert _acao(cliente, e1, [h.id, o.id], "excluir").status_code == 200
    # A ficha fica com um nº de chamada diferente do da planilha: se a linha fosse
    # aplicada, ele voltaria a 1.
    db.get(Aluno, h.id).numero_chamada = 9
    db.commit()
    escola_b, _t, (y,) = _nova_escola(db)
    e2 = escola_b.id
    db.add(IdentidadeExterna(escola_id=e2, aluno_id=y.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    assert _efetivas(db, e2) == {}
    return e1, h, o, e2, y


@pytest.mark.parametrize("quem", ["gestao", "admin_global"])
def test_lista_piloto_nao_reativa_ficha_excluida_com_conta_efetiva_em_outra_escola(
        db, escola_completa, cliente, cliente_global, quem):
    """Prova auth-escopo 3b invertida: reenviar a MESMA Lista Piloto não reativa a
    Helena (a conta U vale em B) nem altera nada na ficha dela — com aviso e
    auditoria; o Otávio, excluído sem conta, é reativado normalmente. Vale também
    para o Admin Global: a planilha não é uma decisão sobre a conta."""
    from tests.test_aluno_transferido import _confirmar

    e1, h, o, e2, _y = _cena_lista(db, escola_completa, cliente)
    quem_envia = cliente if quem == "gestao" else cliente_global
    corpo = _confirmar(quem_envia, e1, _lista())
    db.expire_all()
    helena, otavio = db.get(Aluno, h.id), db.get(Aluno, o.id)
    assert helena.status == "excluido" and helena.numero_chamada == 9   # nada alterado
    assert otavio.status == "ativo"                                       # reativação legítima
    assert _efetivas(db, e2) == {} and _efetivas(db, e1) == {U: e2}
    retidos = [a for a in corpo["avisos"] if "HELENA FICTICIA RAMOS" in a]
    assert len(retidos) == 1 and "NÃO o reativou" in retidos[0], corpo["avisos"]
    assert "1 ficha(s) excluída(s) NÃO foram reativadas" in corpo["mensagem"]
    assert corpo["alunos_em_revisao"] == 0
    [aud] = _auditoria(db, acao=AUD_RETIDA)
    assert (aud.escola_id, aud.entidade_id) == (e1, h.id)
    assert aud.detalhes["outra_escola_id"] == e2 and aud.detalhes["id_externo"] == U
    assert "HELENA" not in str(aud.detalhes)
    assert _auditoria(db, acao=AUD_CONFIRMADA) == []
    [resumo] = _auditoria(db, acao="matriculas.importadas")[-1:]
    assert resumo.detalhes["alunos_reativacao_retida_conta_de_outra_escola"] == 1


def test_lista_piloto_reativa_quando_a_conta_deixa_de_valer_na_outra_escola(
        db, escola_completa, cliente):
    """A reativação legítima não se perde: quando B exclui a ficha dela (a conta
    deixa de valer lá), o envio seguinte da planilha reativa a Helena e aplica a
    linha, sem aviso do D10."""
    from tests.test_aluno_transferido import _confirmar

    e1, h, _o, e2, y = _cena_lista(db, escola_completa, cliente)
    _confirmar(cliente, e1, _lista())
    assert _status(db, h.id) == "excluido"
    assert _acao(_cliente_de(f"admin{e2}@teste.local"), e2, [y.id], "excluir").status_code == 200
    corpo = _confirmar(cliente, e1, _lista())
    db.expire_all()
    helena = db.get(Aluno, h.id)
    assert helena.status == "ativo" and helena.numero_chamada == 1
    assert not any("NÃO o reativou" in a for a in corpo["avisos"])
    assert _efetivas(db, e2) == {U: e1} and _efetivas(db, e1) == {}
