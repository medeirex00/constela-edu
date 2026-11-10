"""Upload MANUAL de relatório de plataforma segue a política 'bloquear' (D5).

A2 §3.3 / S14: a sincronização respeitava a política de criação de aluno da
escola, mas o upload manual pela tela de Importações não — o ``/confirmar`` tinha
``permitir_criar_aluno=True`` por padrão e a tela não mandava o campo. Numa
escola cuja matrícula vem da Lista Piloto, o relatório do Elefante/Matific
enviado à mão criava ficha ativa, sem RA e sem nascimento.

Agora o padrão do ``/confirmar`` é a política da escola: com 'bloquear' a linha
sem candidato seguro vai para a Revisão de identidade com o motivo
'criacao_bloqueada_por_politica', a resposta conta quantas foram barradas e diz
o motivo, e a prévia (``/analisar``) avisa antes. A Lista Piloto não muda.

Dados 100% fictícios; sem rede.
"""
from sqlalchemy import func, select

from app.models import Aluno, IdentidadeExterna, Matricula, RevisaoIdentidade, Turma
from app.services import politica_sync
from tests.test_aluno_transferido import _confirmar as _confirmar_lista
from tests.test_aluno_transferido import _linha as _linha_lista
from tests.test_aluno_transferido import _planilha

API = "/api/v1"
TEXTO_MATIFIC = """Relatório Matific — Turma 3º Ano A
Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas
Ana Beatriz Souza\t42\t85,5\t120
Crianca Ficticia Sem Ficha\t10\t70\t35
Total\t52\t\t155
"""


def _bloquear(db, escola_id):
    politica_sync.definir(db, escola_id, "bloquear")
    db.commit()


def _conta(db, modelo, escola_id):
    return db.scalar(select(func.count()).select_from(modelo)
                     .where(modelo.escola_id == escola_id)) or 0


def _linha_elefante(nome, *, sid, **extra):
    return {"nome": nome, "dados": {"elefante_student_id": sid,
                                    "turma_relatorio": "3º Ano A",
                                    "livros_unicos": 3, "tempo_leitura_min": 10},
            **extra}


def _confirmar(cliente, escola_id, linhas, **corpo):
    r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "recalcular": False, "linhas": linhas, **corpo})
    assert r.status_code == 200, r.text
    return r.json()


def test_confirmar_pela_tela_com_bloquear_nao_cria_e_diz_o_motivo(cliente, db,
                                                                 escola_completa):
    """O corpo que a tela envia (sem a flag) numa escola 'bloquear': nenhuma ficha,
    matrícula ou identidade nasce; a linha vai para a revisão com o motivo; a
    resposta conta a criação barrada e a mensagem explica a política."""
    eid = escola_completa["escola"].id
    _bloquear(db, eid)
    antes = (_conta(db, Aluno, eid), _conta(db, Matricula, eid),
             _conta(db, IdentidadeExterna, eid))
    corpo = _confirmar(cliente, eid, [
        _linha_elefante("Crianca Ficticia Sem Ficha Nenhuma", sid="70001",
                        criar_em_turma_id=escola_completa["turma"].id)])
    db.expire_all()
    assert (_conta(db, Aluno, eid), _conta(db, Matricula, eid),
            _conta(db, IdentidadeExterna, eid)) == antes
    assert corpo["criacao_bloqueada"] == 1
    assert corpo["qtd_revisoes"] == 1
    assert "política desta escola" in corpo["mensagem"]
    assert "Lista Piloto" in corpo["mensagem"]
    assert any("política desta escola não deixa a plataforma criar ficha" in a
               for a in corpo["avisos"])
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().one()
    assert (rev.motivo, rev.origem, rev.id_externo) == (
        "criacao_bloqueada_por_politica", "importacao", "70001")


def test_bloquear_nao_cria_turma_vazia_pelo_nome_do_relatorio(cliente, db, escola_completa):
    """'Criar em turma nova' (nome do relatório) numa escola 'bloquear': sem ficha
    nova não nasce turma — nem vazia. A linha fica 'turma_nao_cadastrada'."""
    eid = escola_completa["escola"].id
    _bloquear(db, eid)
    turmas = _conta(db, Turma, eid)
    corpo = _confirmar(cliente, eid, [
        _linha_elefante("Crianca Ficticia De Turma Nova", sid="70002",
                        criar_em_turma_nome="5 ANO Z NOTURNO")])
    db.expire_all()
    assert _conta(db, Turma, eid) == turmas
    assert db.execute(select(Aluno).where(
        Aluno.nome == "Crianca Ficticia De Turma Nova")).scalars().first() is None
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().one()
    assert rev.motivo == "turma_nao_cadastrada"
    assert corpo["criacao_bloqueada"] == 0


def test_bloquear_continua_associando_quem_tem_ficha(cliente, db, escola_completa):
    """A política barra só a ficha NOVA: o nome idêntico na sala continua casando
    e o dado entra."""
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _bloquear(db, eid)
    corpo = _confirmar(cliente, eid, [_linha_elefante(ana.nome, sid="70003")])
    assert corpo["criacao_bloqueada"] == 0 and corpo["qtd_revisoes"] == 0
    assert corpo["alunos_aplicados_ids"] == [ana.id]
    db.expire_all()
    ident = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "70003")).scalars().first()
    assert ident is not None and ident.aluno_id == ana.id


def test_sem_politica_o_upload_manual_cria_como_sempre(cliente, db, escola_completa):
    """Escola sem política ('permitir'): nada muda."""
    eid = escola_completa["escola"].id
    antes = _conta(db, Aluno, eid)
    corpo = _confirmar(cliente, eid, [
        _linha_elefante("Crianca Ficticia Nova Permitida", sid="70004",
                        criar_em_turma_id=escola_completa["turma"].id)])
    db.expire_all()
    assert _conta(db, Aluno, eid) == antes + 1
    assert corpo["criacao_bloqueada"] == 0
    assert "política" not in corpo["mensagem"]


def test_permitir_so_quem_nao_tem_ficha_parecida_vira_ficha(cliente, db, escola_completa):
    """O que a confirmação da política 'Permitida' (Sincronizacao.tsx) promete: o aluno
    sem NENHUMA ficha parecida vira ficha; com ficha parecida (aqui, 'Sousa' × a ficha
    'Ana Beatriz Souza' da sala) a linha vai para Revisões de identidade e nada nasce —
    não basta "não ser reconhecido com segurança" para virar ficha."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    antes = _conta(db, Aluno, eid)
    corpo = _confirmar(cliente, eid, [
        _linha_elefante("Ana Beatriz Sousa", sid="70006", criar_em_turma_id=turma),
        _linha_elefante("Crianca Ficticia Sem Nenhuma Parecida", sid="70007",
                        criar_em_turma_id=turma)])
    db.expire_all()
    assert _conta(db, Aluno, eid) == antes + 1
    assert db.execute(select(Aluno).where(
        Aluno.nome == "Ana Beatriz Sousa")).scalars().first() is None
    assert corpo["qtd_revisoes"] == 1 and corpo["criacao_bloqueada"] == 0
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().one()
    assert (rev.motivo, rev.nome_recebido) == ("correspondencia_insegura", "Ana Beatriz Sousa")


def test_previa_avisa_a_politica_antes_de_confirmar(cliente, db, escola_completa):
    """O /analisar diz à tela que a escola não deixa criar ficha — o aviso vem
    ANTES de o gestor escolher "criar"."""
    eid = escola_completa["escola"].id
    url = f"{API}/escolas/{eid}/importacoes/analisar"
    r = cliente.post(url, data={"texto": TEXTO_MATIFIC})
    assert r.status_code == 200, r.text
    assert r.json()["criacao_bloqueada_por_politica"] is False
    _bloquear(db, eid)
    r = cliente.post(url, data={"texto": TEXTO_MATIFIC})
    assert r.status_code == 200, r.text
    assert r.json()["criacao_bloqueada_por_politica"] is True


def test_lista_piloto_continua_criando_com_bloquear(cliente, db, escola_completa):
    """A Lista Piloto É a fonte da matrícula: a política não a afeta."""
    eid = escola_completa["escola"].id
    _bloquear(db, eid)
    antes = _conta(db, Aluno, eid)
    _confirmar_lista(cliente, eid, _planilha(("3º Ano B", [
        _linha_lista("CRIANCA FICTICIA DA LISTA PILOTO", numero=1, ra="123.400.001-0")])))
    db.expire_all()
    assert _conta(db, Aluno, eid) == antes + 1
    assert db.execute(select(Aluno).where(
        Aluno.nome == "CRIANCA FICTICIA DA LISTA PILOTO")).scalars().first() is not None


def test_revisao_continua_criando_a_ficha_deliberada(cliente, db, escola_completa):
    """A ficha nova continua possível — deliberadamente, pela tela de revisão
    (``criar_em_turma_id``), também numa escola 'bloquear'."""
    eid = escola_completa["escola"].id
    _bloquear(db, eid)
    _confirmar(cliente, eid, [
        _linha_elefante("Crianca Ficticia Decidida Na Revisao", sid="70005",
                        criar_em_turma_id=escola_completa["turma"].id)])
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().one()
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rev.id}/resolver",
                     json={"criar_em_turma_id": escola_completa["turma"].id})
    assert r.status_code == 200, r.text
    db.expire_all()
    nova = db.execute(select(Aluno).where(
        Aluno.nome == "Crianca Ficticia Decidida Na Revisao")).scalars().one()
    ident = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "70005")).scalars().one()
    assert ident.aluno_id == nova.id
