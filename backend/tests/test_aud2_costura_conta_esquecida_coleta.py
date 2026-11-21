"""Conta da criança excluída para sempre (G_LGPD-1): na coleta seguinte, a linha é
descarte já decidido, anônimo — não pendência.

``identidade_aluno.decidir`` já ignora a conta marcada pela exclusão permanente
(motivo ``conta_esquecida``), e nada com o nome é gravado. O defeito estava no que
vinha DEPOIS: no /confirmar a linha caía no ramo genérico do IGNORAR, que

  * devolvia, na resposta HTTP, o aviso "Linha “<nome>”: a ficha escolhida foi
    excluída e não recebe dados" — o NOME da criança esquecida, com texto errado;
  * entrava em ``ignorados`` e em 'sem_vinculo': a sincronização marcava
    "correspondência pendente" a cada coleta e mandava a escola a uma fila de
    Revisões vazia.

Agora a linha é contada em ``linhas_descartadas['conta_esquecida']`` (motivo já
decidido, fora de ``ignorados``, de 'sem_vinculo' e dos erros), a resposta leva UM
aviso anônimo, e o log da execução da sincronização diz que é conta de aluno
excluído permanentemente — não "conta que a escola aposentou". Dados fictícios;
conectores reais com navegador falso; sem rede.
"""
import json

from sqlalchemy import select

from app.models import RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoLog
from app.services import politica_sync
from app.sync import service
from tests._sync_nucleo_fakes import API, NavElefante, aluno_el, credencial, instalar, livro, rodar

K = "3 ANO A (300396804)"
CID = 511434
SIDS = (9200001, 9200002, 9200003)
AVISO_ANONIMO = ("1 linha(s) de conta(s) de aluno excluído permanentemente foram "
                 "ignoradas: a conta continua ativa na plataforma; peça o encerramento lá.")


def _turma(ec):
    return {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(sid, aluno.nome, [livro(f"Livro Ficticio {i}", "D",
                                         f"2026-09-0{i + 1}T10:00:00")])
        for i, (sid, aluno) in enumerate(zip(SIDS, ec["alunos"]))]}}


def _excluir_para_sempre(cliente_global, eid, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _alerta(db, eid, tipo):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == "elefante",
        SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def test_coleta_seguinte_conta_a_conta_esquecida_como_descarte_decidido(
        db, cliente_global, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    esquecida = escola_completa["alunos"][2]
    nome = esquecida.nome
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turma(escola_completa)))
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"

    _excluir_para_sempre(cliente_global, eid, esquecida.id)
    # A plataforma segue mandando a conta dela, com o nome, junto com as outras.
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou"), (
        ex2.status, ex2.motivo)
    assert ex2.qtd_em_revisao == 0 and ex2.qtd_erros == 0
    assert _alerta(db, eid, "correspondencia_pendente") is None
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().first() is None

    logs = [lg.mensagem for lg in db.execute(select(SincronizacaoLog).where(
        SincronizacaoLog.execucao_id == ex2.id)).scalars()]
    assert any("aluno excluído permanentemente" in m for m in logs), logs
    assert not any("aposentou" in m for m in logs), logs
    assert not any(nome in m for m in logs), logs
    # Nada com o nome no log permanente.
    assert nome not in json.dumps([lg.detalhes for lg in db.execute(
        select(LogAuditoria)).scalars()], ensure_ascii=False, default=str)


def test_upload_manual_da_conta_esquecida_nao_devolve_o_nome(
        db, cliente, cliente_global, escola_completa):
    eid = escola_completa["escola"].id
    esquecida = escola_completa["alunos"][2]
    nome = esquecida.nome

    def _enviar():
        r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
            "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
            "recalcular": False,
            "linhas": [{"nome": nome, "dados": {
                "elefante_student_id": str(SIDS[2]), "turma_relatorio": K,
                "livros_unicos": 3, "tempo_leitura_min": 10}}]})
        assert r.status_code == 200, r.text
        return r.json()

    assert _enviar()["qtd_alunos"] == 1         # a conta fica vinculada à ficha
    _excluir_para_sempre(cliente_global, eid, esquecida.id)

    corpo = _enviar()
    assert corpo["linhas_descartadas"] == {"conta_esquecida": 1}, corpo
    assert corpo["ignorados"] == []
    assert corpo["linhas_em_revisao"] == 0 and corpo["qtd_revisoes"] == 0
    assert corpo["qtd_erros"] == 0
    assert not any(nome in aviso for aviso in corpo["avisos"]), corpo["avisos"]
    assert AVISO_ANONIMO in corpo["avisos"], corpo["avisos"]


def test_log_da_execucao_separa_conta_esquecida_de_conta_aposentada(db, escola_completa):
    """O texto de cada descarte decidido segue o motivo dele."""
    assert "conta_esquecida" in service._MOTIVOS_DECIDIDOS
    ap = service._Apuracao(linhas=5, conferidos_sem_mudanca=2,
                           descartes={"identidade_aposentada": 1, "conta_esquecida": 2})
    assert ap.decididos == 3 and ap.defeitos == 0
    textos = service._textos_dos_decididos(ap)
    assert len(textos) == 2
    [aposentada] = [t for t in textos if "aposentou" in t]
    [esquecida] = [t for t in textos if "excluído permanentemente" in t]
    assert aposentada.startswith("1 linha(s) de conta(s) da plataforma que a escola aposentou")
    assert esquecida.startswith("2 linha(s) de conta(s) de aluno excluído permanentemente "
                                "foram ignoradas")
    assert service._rotulo_descarte("conta_esquecida") != "conta esquecida"
