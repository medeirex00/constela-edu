"""N6: escola sem admin/coordenador ATIVO falha ANTES de coletar.

A importação automática é assinada por um usuário da escola
(``orchestrator._resolver_ator``). Sem nenhum ativo, a aplicação levantava
RuntimeError depois da coleta inteira: "Falha inesperada: RuntimeError"
recuperável, e cada nova tentativa coletava tudo de novo para falhar igual. Afeta
sobretudo a escola nova, com a coleta pedida pelo Admin Global ou pelo agendador.

Agora a execução termina 'erro' com o código próprio ``escola_sem_responsavel``,
não recuperável, sem chamar o conector. Dados FICTÍCIOS, sem rede.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoExecucao
from app.sync import connectors, service, vault
from app.sync.interfaces import Conector, Credenciais, Estrategia, ResultadoValidacao


class _ConectorContado(Conector):
    plataforma = "matific"
    versao = "9.9.9"
    estrategia = Estrategia.NAVEGADOR

    def __init__(self):
        self.chamadas = 0

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    async def localizar_relatorios(self, cred, ctx):
        return []

    async def obter(self, cred, rel, ctx):
        raise NotImplementedError

    async def sincronizar(self, cred, ctx):
        self.chamadas += 1
        return []


@pytest.fixture()
def sem_responsavel(db, escola_completa, monkeypatch):
    """Escola cujo único admin está inativo, com credencial e conector contado."""
    escola = escola_completa["escola"]
    escola_completa["admin"].status = "inativo"
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    conector = _ConectorContado()
    monkeypatch.setitem(connectors._REGISTRO, "matific", conector)
    # Com o agendador LIGADO, uma falha recuperável ganharia nova tentativa na fila.
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    return escola, conector


def test_escola_sem_responsavel_falha_antes_de_coletar_e_sem_nova_tentativa(
        db, sem_responsavel):
    escola, conector = sem_responsavel
    ex = service.enfileirar(db, escola.id, "matific", origem="scheduler")
    db.commit()

    service.executar(db, ex)

    db.expire_all()
    ex = db.get(SincronizacaoExecucao, ex.id)
    assert conector.chamadas == 0                       # nada foi coletado
    assert ex.status == "erro"
    assert ex.motivo == service.CODIGO_SEM_RESPONSAVEL
    assert "coordenador" in ex.erro_resumo and "Falha inesperada" not in ex.erro_resumo
    alerta = db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == escola.id,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().one()
    assert (alerta.tipo, alerta.severidade) == (service.CODIGO_SEM_RESPONSAVEL, "critico")
    assert service.categoria_do_tipo(alerta.tipo) == "configuracao"
    # Não recuperável: nenhuma nova tentativa na fila.
    assert db.scalar(select(SincronizacaoExecucao.id).where(
        SincronizacaoExecucao.escola_id == escola.id,
        SincronizacaoExecucao.status == "fila")) is None
    # A credencial não é marcada inválida: a plataforma não recusou nada.
    assert vault.obter_linha(db, escola.id, "matific").status != "invalida"


def test_pedido_do_admin_global_em_escola_sem_responsavel_tambem_falha_antes(
        db, sem_responsavel):
    """O Admin Global não é da escola: o ator cai no admin/coordenador da escola."""
    from app.core.security import hash_senha
    from app.models import Usuario

    escola, conector = sem_responsavel
    glob = Usuario(escola_id=None, nome="Global Ficticio", email="global@teste.local",
                   senha_hash=hash_senha("x"), cargo="admin")
    db.add(glob)
    db.commit()
    ex = service.enfileirar(db, escola.id, "matific", origem="manual", usuario_id=glob.id)
    db.commit()

    service.executar(db, ex)

    db.expire_all()
    assert conector.chamadas == 0
    assert db.get(SincronizacaoExecucao, ex.id).motivo == service.CODIGO_SEM_RESPONSAVEL


def test_com_coordenador_ativo_a_coleta_segue(db, escola_completa, sem_responsavel):
    from app.core.security import hash_senha
    from app.models import Usuario

    escola, conector = sem_responsavel
    db.add(Usuario(escola_id=escola.id, nome="Coord Ficticio", email="coord@teste.local",
                   senha_hash=hash_senha("x"), cargo="coordenador"))
    db.commit()
    ex = service.enfileirar(db, escola.id, "matific", origem="scheduler")
    db.commit()

    service.executar(db, ex)

    db.expire_all()
    assert conector.chamadas == 1
    assert db.get(SincronizacaoExecucao, ex.id).motivo != service.CODIGO_SEM_RESPONSAVEL
