"""Cenários do GET /escolas/{id}/sync/status para o teste de ORÇAMENTO de consultas
(``test_sync_status_orcamento.py``) e o teste DOURADO da resposta
(``test_sync_status_dourado.py``).

Cada cenário monta um estado fictício e DETERMINÍSTICO da escola (instantes fixos
em relação a ``AGORA``, que o teste congela em ``service._agora``) e devolve o id
da escola. Os estados cobrem o que o /status sabe dizer: escola recém-criada,
ano letivo virado, escola configurada e em dia (com rede), dados velhos (o
/status ABRE e atualiza alertas de frescor), execução em andamento e manual viva
na fila, fila parada (o /status CANCELA o que só o agendador rodaria), credencial
ilegível ou recusada, módulo fora do plano (o /status FECHA o alerta) e
agendador ligado.

Nomes, contas e senhas são fictícios; nenhuma senha aparece na resposta.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.security import cifrar_segredo
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    LogAuditoria,
    Matricula,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.models.rede import ModuloRede, Rede
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.sync import escola_externa, service

# O "agora" congelado dos cenários (UTC naive, o referencial do serviço).
AGORA = datetime(2026, 10, 20, 15, 0, 0)


def _h(horas: float) -> datetime:
    return AGORA - timedelta(hours=horas)


# ---------------------------------------------------------------------------
# Peças
# ---------------------------------------------------------------------------
def _cred(db, eid, plataforma, *, status="valida", legivel=True, erro=None):
    segredo = (cifrar_segredo(json.dumps({"usuario": f"robo.{plataforma}@escola.invalid",
                                          "senha": "senha-ficticia", "extra": {}}))
               if legivel else "cifra-que-nao-abre-com-chave-nenhuma")
    db.add(PlataformaCredencial(escola_id=eid, plataforma=plataforma,
                                segredo_cifrado=segredo, status=status,
                                validada_em=_h(30) if status == "valida" else None,
                                ultimo_erro=erro, created_at=_h(24 * 40),
                                updated_at=_h(30)))


def _agenda(db, eid, plataforma, *, ativo=True, cadencia="diaria", desde_horas=24 * 20):
    db.add(SincronizacaoConfig(escola_id=eid, plataforma=plataforma, ativo=ativo,
                               cadencia=cadencia, hora_local="06:30",
                               proxima_execucao=AGORA + timedelta(hours=15, minutes=30),
                               created_at=_h(24 * 40), updated_at=_h(desde_horas)))


def _execucao(db, eid, plataforma, status, *, horas, origem="manual", motivo=None,
              parametros=None, recalculo=False, erro=None, qtd_alunos=0,
              disponivel_em=None, tentativa=1):
    terminou = status in service.STATUS_TERMINAIS
    ex = SincronizacaoExecucao(
        escola_id=eid, plataforma=plataforma, origem=origem, status=status,
        created_at=_h(horas + 0.1),
        iniciada_em=_h(horas + 0.05) if status != "fila" else None,
        finalizada_em=_h(horas) if terminou else None,
        duracao_ms=180_000 if terminou else 0, qtd_alunos=qtd_alunos,
        motivo=motivo, parametros=parametros or {}, recalculo_pendente=recalculo,
        erro_resumo=erro, disponivel_em=disponivel_em, tentativa=tentativa)
    db.add(ex)
    db.flush()
    return ex


def _alerta(db, eid, plataforma, tipo, *, execucao_id=None, mensagem="Alerta fictício.",
            severidade="warn"):
    db.add(SincronizacaoAlerta(escola_id=eid, plataforma=plataforma, tipo=tipo,
                               severidade=severidade, mensagem=mensagem,
                               execucao_id=execucao_id, created_at=_h(48)))


def _vinculo(db, eid, plataforma, id_externo, nome):
    db.add(Configuracao(escola_id=eid, namespace=escola_externa.NAMESPACE, chave=plataforma,
                        valor={"id": id_externo, "nome": nome, "origem": "aprendido",
                               "definido_em": "2026-10-01T10:00:00", "definido_por": None}))


def _rede(db, escola, *, desligados=()):
    rede = Rede(nome="Rede Fictícia de Testes", uf="SP")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in desligados:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=False))


def _cobertura(db, base):
    """Snapshots dos alunos do fixture (Elefante: um com livros, um zerado;
    Matific: um) e pendências de correspondência (2 dentro dos 30 dias)."""
    eid = base["escola"].id
    ana, joao, _sofia = base["alunos"]
    imp = Importacao(escola_id=eid, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=eid, aluno_id=ana.id, importacao_id=imp.id,
                            data_referencia=_h(30), livros_unicos=4,
                            livros_por_nivel={"D": 4}))
    db.add(SnapshotElefante(escola_id=eid, aluno_id=joao.id, importacao_id=imp.id,
                            data_referencia=_h(54), livros_unicos=0))
    db.add(SnapshotMatific(escola_id=eid, aluno_id=ana.id, importacao_id=imp.id,
                           data_referencia=_h(30), atividades=12, estrelas=30,
                           pontuacao_media=2.5))
    for acao, horas in (("aluno.revisao_necessaria", 24 * 3),
                        ("importacao.linha_ignorada", 24 * 29),
                        ("aluno.revisao_necessaria", 24 * 31),     # fora da janela
                        ("aluno.criado", 24)):                     # outra ação
        db.add(LogAuditoria(escola_id=eid, acao=acao, entidade="aluno",
                            detalhes={}, created_at=_h(horas)))


def _volume(db, base, fator: int):
    """Massa extra que NÃO muda o número de consultas: alunos matriculados com
    snapshots, execuções antigas com logs."""
    if fator <= 1:
        return
    eid = base["escola"].id
    turma = base["turma"]
    imp = Importacao(escola_id=eid, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for i in range(20 * fator):
        aluno = Aluno(escola_id=eid, nome=f"Aluno Ficticio {fator}-{i:03d}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=eid, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=2026))
        db.add(SnapshotElefante(escola_id=eid, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=_h(30 + i % 7), livros_unicos=i % 3))
        db.add(SnapshotMatific(escola_id=eid, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=_h(30 + i % 5), atividades=i % 4))
    for i in range(30 * fator):
        plataforma = ("elefante", "matific")[i % 2]
        ex = _execucao(db, eid, plataforma, ("concluida", "erro", "sem_atualizacao")[i % 3],
                       horas=24 * 60 + i, motivo="nada_mudou" if i % 3 == 2 else None)
        for j in range(3):
            db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=eid, etapa="coleta",
                                    nivel="info", mensagem=f"linha fictícia {j}",
                                    created_at=_h(24 * 60 + i)))


# ---------------------------------------------------------------------------
# Cenários: cada um recebe (db, base, monkeypatch, fator) e devolve o id da escola.
# ---------------------------------------------------------------------------
def escola_nova(db, base, monkeypatch, fator=1):
    """Recém-criada: sem turma, sem aluno, sem integração."""
    escola = Escola(nome="Escola Nova Ficticia", ano_letivo_ativo=2026)
    db.add(escola)
    db.commit()
    return escola.id


def virada_do_ano(db, base, monkeypatch, fator=1):
    """Ano letivo ativo já virou (2027) e a escola só tem turma, matrícula e dado
    de 2026: tem Lista Piloto, mas o universo pontuado está vazio (zeros)."""
    escola = Escola(nome="Escola Virada Ficticia", ano_letivo_ativo=2027)
    db.add(escola)
    db.flush()
    turma = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano", ano_letivo=2026)
    aluno = Aluno(escola_id=escola.id, nome="Aluna Ficticia Da Virada")
    db.add_all([turma, aluno])
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=_h(24 * 40), atividades=3))
    db.commit()
    return escola.id


def configurada_em_dia(db, base, monkeypatch, fator=1):
    """Integrações conectadas, agendadas e em dia, com rede (plano consultado):
    a leitura NÃO grava nada."""
    escola = base["escola"]
    eid = escola.id
    _rede(db, escola)
    for p in ("elefante", "matific"):
        _cred(db, eid, p)
        _agenda(db, eid, p)
    _execucao(db, eid, "elefante", "concluida", horas=6, qtd_alunos=3)
    _execucao(db, eid, "elefante", "sem_atualizacao", horas=2, motivo="nada_mudou")
    _execucao(db, eid, "matific", "concluida", horas=10, qtd_alunos=2)
    # Coleta POR PERÍODO: é a última execução e a última tentativa, mas não é
    # "último sucesso" nem "em dia" (não renova o acumulado).
    _execucao(db, eid, "matific", "concluida", horas=1, qtd_alunos=2,
              parametros={"matific_start_date": "2026-10-01",
                          "matific_end_date": "2026-10-07"})
    _alerta(db, eid, "matific", "correspondencia_pendente")
    _vinculo(db, eid, "elefante", "4321", "EMEF Ficticia")
    _cobertura(db, base)
    _volume(db, base, fator)
    db.commit()
    return eid


def dados_velhos(db, base, monkeypatch, fator=1):
    """Agenda diária sem coleta em dia: a 1ª leitura ABRE o 'desatualizada' do
    Matific e ATUALIZA o texto do aberto do Elefante; a 2ª não grava nada.
    Também: parcial com unidade que falhou (sucesso, mas não 'em dia'), erro com
    alerta da própria tentativa, recálculo pendente (marca e alerta)."""
    eid = base["escola"].id
    _cred(db, eid, "elefante")
    _cred(db, eid, "matific", status="nao_validada")
    _agenda(db, eid, "elefante")
    _agenda(db, eid, "matific", desde_horas=24 * 10)
    _execucao(db, eid, "elefante", "concluida", horas=24 * 5, qtd_alunos=3)
    _execucao(db, eid, "elefante", "parcial", horas=20, motivo="coleta_parcial",
              qtd_alunos=2, recalculo=True)
    _alerta(db, eid, "elefante", "desatualizada", severidade="critico",
            mensagem="Sem sincronização bem-sucedida há 2 dia(s) — texto antigo.")
    antiga = _execucao(db, eid, "matific", "erro", horas=50, erro="Erro fictício antigo.",
                       motivo="erro_inesperado")
    erro = _execucao(db, eid, "matific", "erro", horas=3, erro="A plataforma não respondeu.",
                     motivo="falha_download")
    # O alerta da ÚLTIMA tentativa explica a falha, mesmo sendo mais antigo que
    # outro aberto (de outra execução).
    _alerta(db, eid, "matific", "falha_download", execucao_id=erro.id)
    _alerta(db, eid, "matific", "erro_inesperado", execucao_id=antiga.id)
    _alerta(db, eid, "matific", "recalculo_pendente")
    _cobertura(db, base)
    db.commit()
    return eid


def execucao_ativa(db, base, monkeypatch, fator=1):
    """Elefante coletando agora; Matific com uma manual na fila há 2 h cuja thread
    dá sinal de vida (outro worker): nada é liberado nem gravado."""
    eid = base["escola"].id
    for p in ("elefante", "matific"):
        _cred(db, eid, p)
    _execucao(db, eid, "elefante", "concluida", horas=26, qtd_alunos=3)
    _execucao(db, eid, "elefante", "executando", horas=0.02)
    _execucao(db, eid, "matific", "concluida", horas=30, qtd_alunos=3)
    viva = _execucao(db, eid, "matific", "fila", horas=2)
    db.add(SincronizacaoLog(execucao_id=viva.id, escola_id=eid, etapa="fila", nivel="info",
                            mensagem="Esperando a vez (sinal de vida fictício).",
                            created_at=_h(0.05)))
    db.commit()
    return eid


def fila_parada(db, base, monkeypatch, fator=1):
    """Agendador desligado: a agendada e a manual órfã (sem sinal de vida há mais
    que SYNC_TRAVADA_S) só ele rodaria — a 1ª leitura as CANCELA (com registro)."""
    eid = base["escola"].id
    for p in ("elefante", "matific"):
        _cred(db, eid, p)
        _agenda(db, eid, p, ativo=False, cadencia="manual")
    _execucao(db, eid, "elefante", "concluida", horas=26, qtd_alunos=3)
    _execucao(db, eid, "elefante", "fila", horas=1, origem="scheduler")
    _execucao(db, eid, "matific", "erro", horas=5, erro="Falha fictícia.", motivo="falha_download")
    _execucao(db, eid, "matific", "fila", horas=settings.SYNC_TRAVADA_S / 3600 + 1)
    db.commit()
    return eid


def credencial_ilegivel(db, base, monkeypatch, fator=1):
    """Elefante 'valida' cuja cifra não abre (rotação sem recifrar) → 'ilegivel';
    Matific recusada pela plataforma → falha de 'autenticacao'."""
    eid = base["escola"].id
    _cred(db, eid, "elefante", legivel=False)
    _cred(db, eid, "matific", status="invalida", erro="Usuário ou senha recusados (fictício).")
    _execucao(db, eid, "elefante", "concluida", horas=12, qtd_alunos=3)
    _execucao(db, eid, "matific", "erro", horas=4, erro="Login recusado.", motivo="falha_auth")
    db.commit()
    return eid


def fora_do_plano(db, base, monkeypatch, fator=1):
    """A rede não contratou Matemática: o 'desatualizada' que ficou do Matific é
    FECHADO na 1ª leitura; o Elefante segue em dia."""
    escola = base["escola"]
    eid = escola.id
    _rede(db, escola, desligados=("matematica",))
    for p in ("elefante", "matific"):
        _cred(db, eid, p)
        _agenda(db, eid, p)
    _execucao(db, eid, "elefante", "concluida", horas=8, qtd_alunos=3)
    _execucao(db, eid, "matific", "concluida", horas=24 * 9, qtd_alunos=3)
    _alerta(db, eid, "matific", "desatualizada", severidade="critico",
            mensagem="Sem sincronização bem-sucedida há 9 dia(s) (fictício).")
    db.commit()
    return eid


def agendador_ligado(db, base, monkeypatch, fator=1):
    """Agendador ligado: a agendada na fila é dele (não é liberada) e o card não
    diz 'fila parada'."""
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    eid = base["escola"].id
    for p in ("elefante", "matific"):
        _cred(db, eid, p)
        _agenda(db, eid, p)
    _execucao(db, eid, "elefante", "concluida", horas=20, qtd_alunos=3)
    _execucao(db, eid, "elefante", "fila", horas=0.5, origem="scheduler")
    _execucao(db, eid, "matific", "sem_atualizacao", horas=7, motivo="nada_mudou")
    db.commit()
    return eid


CENARIOS = {
    "escola_nova": escola_nova,
    "virada_do_ano": virada_do_ano,
    "configurada_em_dia": configurada_em_dia,
    "dados_velhos": dados_velhos,
    "execucao_ativa": execucao_ativa,
    "fila_parada": fila_parada,
    "credencial_ilegivel": credencial_ilegivel,
    "fora_do_plano": fora_do_plano,
    "agendador_ligado": agendador_ligado,
}


def congelar(monkeypatch):
    """``service._agora`` fixo em ``AGORA`` e o agendador desligado (o padrão dos
    testes; o cenário ``agendador_ligado`` liga). Nenhuma thread de espera de
    outro teste conta como viva aqui."""
    monkeypatch.setattr(service, "_agora", lambda: AGORA)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", False)
    monkeypatch.setattr(service, "_vivas_neste_processo", set())
