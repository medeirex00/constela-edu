"""Motor de execução da sincronização — fila, ciclo de vida, retries, alertas.

Uma EXECUÇÃO (``SincronizacaoExecucao``) é a unidade de trabalho: enfileirada
(``fila``) → o worker a pega (``executando``) → conclui (``concluida`` /
``sem_dados`` / ``erro``). Idempotência/duplicidade: nunca há duas execuções
ativas para o mesmo (escola, plataforma). Erros recuperáveis re-enfileiram com
backoff exponencial até ``SYNC_MAX_TENTATIVAS`` — só com o agendador LIGADO (é
ele quem roda a nova tentativa; desligado, a falha fica visível e a escola tenta
de novo pelo "Sincronizar agora").

Fuso: instantes gravados em UTC naive; regras de negócio (horário da agenda,
dia da semana) no fuso de Brasília — ver ``app/sync/fuso.py``.

O conector (I/O de rede/navegador) é assíncrono; a aplicação no banco é
síncrona (reusa o pipeline). Rodamos o fetch com ``asyncio.run`` na mesma
thread do worker — o conector não toca o banco; só o ``log`` toca, sequencial.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, case, cast, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import settings
from app.models.escola import Escola
from app.models.plataformas import Importacao
from app.services import modulos as svc_modulos
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.services.identidade_aluno import MOTIVOS_DESCARTE_DECIDIDO
from app.sync import connectors, escola_externa, fuso, vault
from app.sync import orchestrator
from app.sync.interfaces import Contexto, ErroConector

logger = logging.getLogger("constela.sync")


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(valor: datetime | None) -> datetime | None:
    """Normaliza para UTC naive (o referencial de ``_agora``). Objeto recém-
    flushado ainda traz o default tz-aware do modelo; lido do banco, vem naive."""
    if valor is not None and valor.tzinfo is not None:
        return valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def agendador_ligado() -> bool:
    """O agendador automático roda neste ambiente? É a CONFIGURAÇÃO (vale para
    todos os workers do mesmo deploy), não a thread deste processo — quem decide
    se uma execução deixada na fila vai rodar sozinha é ela."""
    return bool(settings.SYNC_SCHEDULER_ENABLED)


# --------------------------------------------------------------------------
# Logs e alertas (nunca com segredo)
# --------------------------------------------------------------------------
def registrar_log(db: Session, execucao: SincronizacaoExecucao, etapa: str,
                  nivel: str, mensagem: str) -> None:
    db.add(SincronizacaoLog(execucao_id=execucao.id, escola_id=execucao.escola_id,
                            etapa=etapa, nivel=nivel, mensagem=mensagem[:1000]))
    db.flush()


def abrir_alerta(db: Session, escola_id: int, plataforma: str | None, tipo: str,
                 mensagem: str, *, severidade: str = "warn",
                 execucao_id: int | None = None) -> None:
    """Abre um alerta se ainda não houver um IGUAL em aberto (evita spam).

    Se já há um igual aberto e a ocorrência nova vem de uma execução, o aberto
    passa a apontar para ELA (e leva a mensagem dela): a data de abertura continua
    a da primeira vez, mas "qual execução falhou por último, e por quê" é o que o
    /status usa para dizer o tipo da falha — apontar para a de semanas atrás
    explicaria a falha de hoje com o texto antigo."""
    existe = db.execute(
        select(SincronizacaoAlerta).where(
            SincronizacaoAlerta.escola_id == escola_id,
            SincronizacaoAlerta.plataforma == plataforma,
            SincronizacaoAlerta.tipo == tipo,
            SincronizacaoAlerta.resolvido.is_(False),
        )
    ).scalars().first()
    if existe is not None:
        if execucao_id is not None and existe.execucao_id != execucao_id:
            existe.execucao_id = execucao_id
            existe.mensagem = mensagem[:500]
            db.flush()
        return
    db.add(SincronizacaoAlerta(
        escola_id=escola_id, plataforma=plataforma, tipo=tipo,
        severidade=severidade, mensagem=mensagem[:500], execucao_id=execucao_id))
    db.flush()


def resolver_alertas(db: Session, escola_id: int, plataforma: str,
                     tipos: tuple[str, ...]) -> int:
    """Fecha alertas de dado tipo (ex.: após uma sync bem-sucedida). Devolve
    quantos fechou."""
    return _marcar_resolvidos(db, db.execute(
        select(SincronizacaoAlerta).where(
            SincronizacaoAlerta.escola_id == escola_id,
            SincronizacaoAlerta.plataforma == plataforma,
            SincronizacaoAlerta.tipo.in_(tipos),
            SincronizacaoAlerta.resolvido.is_(False),
        )
    ).scalars())


def _marcar_resolvidos(db: Session, alertas) -> int:
    """Fecha (com a data) os alertas ABERTOS em ``alertas`` (o chamador os leu com
    ``resolvido`` falso). Devolve quantos fechou — 0: nada foi gravado."""
    n = 0
    for al in alertas:
        al.resolvido = True
        al.resolvido_em = _agora()
        n += 1
    db.flush()
    return n


# --------------------------------------------------------------------------
# Taxonomia dos alertas — MAPA ÚNICO código do conector → (tipo, severidade)
#
# Antes havia dois caminhos que não conversavam: a execução traduzia
# ``falha_auth`` para o tipo ``falha_autenticacao``; o salvar credencial gravava
# o código CRU como tipo (``erro_navegador``, ``pagina_login``, ``captcha``…,
# sempre como crítico e marcando a senha como inválida); e o sucesso fechava uma
# lista fixa que não tinha nem ``falha_autenticacao`` nem os códigos crus. Em
# produção, alertas de julho/agosto seguiam abertos. Agora os dois caminhos usam
# este mapa, e o sucesso fecha TODA falha da integração (ver
# ``resolver_falhas_da_integracao``).
# --------------------------------------------------------------------------
CODIGO_SEM_RESPONSAVEL = "escola_sem_responsavel"
ALERTA_POR_CODIGO: dict[str, tuple[str, str]] = {
    # A plataforma RECUSOU usuário/senha (o único caso que prova senha errada).
    "senha_invalida": ("senha_invalida", "critico"),
    "senha_expirada": ("senha_expirada", "critico"),
    # A senha SALVA não abre com as chaves deste servidor (DEK/SECRET_KEY trocadas
    # sem recifrar, valor corrompido): a plataforma NÃO recusou nada — a
    # credencial não é marcada 'invalida' (o /status já deriva 'ilegivel'), mas
    # nada volta sozinho: só o recadastro resolve.
    vault.CODIGO_CREDENCIAL_ILEGIVEL: ("credencial_ilegivel", "critico"),
    # Acesso não confirmado: SSO, 2FA, tela que mudou, desafio anti-robô.
    "falha_auth": ("falha_autenticacao", "warn"),
    "mfa": ("mfa", "warn"),
    "pagina_login": ("pagina_login", "warn"),
    "captcha": ("captcha", "warn"),
    "erro_navegador": ("erro_navegador", "warn"),
    # Coleta (a plataforma não respondeu como esperado).
    "sem_escola": ("sem_escola", "warn"),
    "falha_download": ("falha_download", "warn"),
    "timeout": ("timeout", "warn"),
    "http_indisponivel": ("falha_download", "warn"),
    "sessao_invalida": ("falha_autenticacao", "warn"),
    # Processamento do lado do Constela.
    "erro_inesperado": ("erro_inesperado", "warn"),
    "parser_incompativel": ("parser_incompativel", "critico"),
    # Este servidor não consegue coletar (o navegador não abriu): a falha ao subir o
    # Chromium pode passar e tem nova tentativa; o pacote ausente não.
    "navegador_indisponivel": ("plataforma_indisponivel", "critico"),
    # O login funcionou, mas o endpoint de DADOS respondeu 401/403: a conta não
    # tem (mais) acesso ao relatório. Não é senha errada — a credencial não é
    # marcada inválida —, mas nada volta sozinho.
    "sem_acesso_ao_dado": ("sem_acesso_ao_dado", "critico"),
    "periodo_invalido": ("periodo_invalido", "warn"),
    # ESCOLA EXTERNA (``sync/escola_externa.py``): a coleta não sabe, com
    # segurança, de qual escola da plataforma são os dados — nada foi aplicado e
    # nada volta sozinho (alguém confere a credencial ou escolhe a escola).
    "conta_multiescola": ("conta_multiescola", "critico"),
    "escola_externa_trocada": ("escola_externa_trocada", "critico"),
    "escola_externa_em_outra_escola": ("escola_externa_em_outra_escola", "critico"),
    "escola_nao_identificada": ("escola_nao_identificada", "critico"),
    # D8 (LGPD): sem vínculo, TODAS as contas da coleta já são de alunos de OUTRA
    # escola do Constela — credencial da outra escola; nada foi gravado.
    "contas_de_outra_escola": ("contas_de_outra_escola", "critico"),
    # A escola não tem admin/coordenador ATIVO para assinar a importação
    # automática: nada é coletado e nada volta sozinho (alguém cadastra ou reativa).
    CODIGO_SEM_RESPONSAVEL: (CODIGO_SEM_RESPONSAVEL, "critico"),
}
_ALERTA_PADRAO = ("falha_download", "warn")   # código desconhecido: como antes


def alerta_do_codigo(codigo: str | None) -> tuple[str, str]:
    """(tipo do alerta, severidade) de um código de erro de conector."""
    return ALERTA_POR_CODIGO.get(codigo or "", _ALERTA_PADRAO)


# Só estes códigos PROVAM que a plataforma recusou a credencial — os únicos que
# marcam a credencial como 'invalida'. Página que não abriu, navegador, CAPTCHA,
# timeout… são do caminho, não da senha.
CODIGOS_CREDENCIAL_RECUSADA = frozenset({"senha_invalida", "senha_expirada"})

# Vindos do conector, estes códigos só saem com o navegador deste servidor ABERTO — o
# conector abre o navegador (``_sessao``) antes do login — e quase sempre são a
# resposta da página de login da plataforma: recusou a senha, pediu CAPTCHA ou 2FA,
# mudou, não confirmou o login, não mostrou a escola. Provam que o alerta de quando o
# Chromium não subia (``navegador_indisponivel`` → 'plataforma_indisponivel') perdeu a
# causa: o teste de conexão (``router._registrar_validacao``) e a execução
# (``_tratar_falha``) o fecham antes de abrir o da recusa. NÃO entram o
# ``erro_navegador`` (pode ser o navegador que caiu no meio), o próprio
# ``navegador_indisponivel`` nem o ``timeout``. Na EXECUÇÃO há ainda a marca
# ``coleta['navegador_abriu']`` (a página de login respondeu; ``_encerrar_com_falha``)
# e a coleta que voltou (``_concluir``): as duas também o fecham. O navegador que cai
# no meio da execução é ``navegador_indisponivel`` (``_navegador_que_caiu``) e não fecha.
CODIGOS_RESPOSTA_DO_LOGIN = frozenset({
    "senha_invalida", "senha_expirada", "captcha", "pagina_login", "mfa",
    "falha_auth", "sem_escola"})

# Alertas de ACESSO: um login que funcionou prova que deixaram de valer.
# ``falha_auth`` é o tipo antigo, gravado cru pelo salvar credencial. A senha
# salva ilegível também: o login só roda com a cifra aberta.
TIPOS_ACESSO = ("senha_invalida", "senha_expirada", "falha_autenticacao", "falha_auth",
                "mfa", "pagina_login", "captcha", "erro_navegador", "credencial_ilegivel")

# Alertas com regra PRÓPRIA de abrir/fechar — não são "a última execução
# falhou", então um sucesso qualquer não os fecha: 'lento' fecha quando uma
# execução termina dentro do normal; 'desatualizada' quando o dado volta a estar
# em dia (ou a agenda é desligada); 'queda_matific' quando uma coleta deixa de
# trazer total menor que o gravado; 'contas_ausentes' quando a coleta que o
# confere (acumulado do Matific; coleta completa do Elefante) volta a trazer
# todas as contas vinculadas.
TIPOS_REGRA_PROPRIA = ("lento", "desatualizada", "queda_matific", "contas_ausentes")

# CATEGORIA da falha (o que a escola faz a respeito): a tela diferencia acesso
# recusado × plataforma fora do ar/bloqueando × erro do nosso lado × este
# servidor sem como coletar × pedido com configuração que não é aceita.
CATEGORIA_POR_TIPO: dict[str, str] = {
    "senha_invalida": "autenticacao", "senha_expirada": "autenticacao",
    "falha_autenticacao": "autenticacao", "falha_auth": "autenticacao", "mfa": "autenticacao",
    "pagina_login": "indisponibilidade_externa", "captcha": "indisponibilidade_externa",
    "erro_navegador": "indisponibilidade_externa", "sem_escola": "indisponibilidade_externa",
    "falha_download": "indisponibilidade_externa", "timeout": "indisponibilidade_externa",
    "interrompida": "processamento", "erro_inesperado": "processamento",
    "parser_incompativel": "processamento", "recalculo_pendente": "processamento",
    # Período pedido inválido (datas, fim antes do início, um dia só sem a
    # confirmação da plataforma): não é erro do nosso lado — quem pediu ajusta.
    "periodo_invalido": "configuracao",
    # A senha salva não abre com as chaves deste servidor: a plataforma não
    # recusou nada (não é 'autenticacao'); a configuração guardada é que não serve
    # mais e só o recadastro resolve.
    "credencial_ilegivel": "configuracao",
    "sem_acesso_ao_dado": "autenticacao",
    "coleta_parcial": "indisponibilidade_externa",
    "contas_ausentes": "indisponibilidade_externa",
    "plataforma_indisponivel": "indisponivel",
    # A conta cadastrada não é (só) desta escola: é o acesso que precisa de
    # conferência — a tela usa a frase própria de cada código.
    "conta_multiescola": "autenticacao", "escola_externa_trocada": "autenticacao",
    "escola_externa_em_outra_escola": "autenticacao", "contas_de_outra_escola": "autenticacao",
    "escola_nao_identificada": "processamento",
    # Falta um usuário ativo da escola que assine a importação: é cadastro, não
    # falha da plataforma nem do processamento.
    CODIGO_SEM_RESPONSAVEL: "configuracao",
}

# --------------------------------------------------------------------------
# ESTADOS FINAIS de uma execução (contrato da Etapa 2)
#   concluida       nenhuma unidade esperada falhou e ≥1 aluno teve dado novo/alterado
#   parcial         ≥1 aluno com dado aplicado, mas parte falhou (turma/lote/aluno,
#                   arquivo, falha depois de gravar, linha com defeito) — alerta
#                   'coleta_parcial'. Exceção D2(6): falhou SÓ o endpoint dos nomes
#                   do Matific, com conta vinculada conferida, também é 'parcial'
#                   com 0 aluno — essa não aplicou dado (``_filtro_aplicou_dado``)
#   sem_atualizacao coleta completa, sem erro, com linhas, e 0 aluno com dado novo:
#                   motivo 'nada_mudou' (legítimo), 'correspondencia_pendente'
#                   (parte das linhas ficou em revisão/sem vínculo e ≥1 conta já
#                   vinculada da escola foi conferida — alerta próprio),
#                   'tudo_em_revisao' (as linhas ficaram em revisão/sem vínculo e
#                   NENHUMA conta da escola foi conferida — mesmo alerta, texto
#                   próprio, e NÃO conta como "em dia"), 'queda_retida' (total
#                   menor do Matific retido — 'queda_matific') ou
#                   'linhas_descartadas' (defeito — 'coleta_parcial')
#   sem_dados       a plataforma respondeu 2xx e trouxe 0 turma/0 linha
#   erro            login, HTTP de erro, tempo esgotado, resposta incompatível,
#                   exceção ou nenhuma unidade coletada; motivo = o código
#
# "Em dia" (fecha 'desatualizada') e "verificado" (ultima_verificacao_em): ver
# ``_filtro_em_dia`` e ``_filtro_verificacao``. A coleta POR PERÍODO do Matific
# não conta em nenhum dos dois nem no último sucesso (``_filtro_do_acumulado``).
# --------------------------------------------------------------------------
# Os estados que PODEM ter aplicado dado. O "último sucesso" exige mais: a
# 'parcial' só conta com ≥1 aluno aplicado (``_filtro_aplicou_dado``).
STATUS_COM_DADO = ("concluida", "parcial")
STATUS_TERMINAIS = ("concluida", "parcial", "sem_atualizacao", "sem_dados", "erro")
# O nome que ``sync/prerequisitos.py`` (status_honesto) procura: os mesmos estados.
ESTADOS_FINAIS = STATUS_TERMINAIS
MOTIVO_NADA_MUDOU = "nada_mudou"
# 'sem_atualizacao' em que TODAS as linhas ficaram em revisão/sem vínculo e a
# coleta não conferiu nenhuma conta já vinculada a um aluno da escola (nem
# aplicou, nem comparou e achou igual, nem reteve uma queda). É a assinatura de
# credencial de OUTRA escola ou de casamento quebrado — e também a 1ª coleta de
# uma escola sem nenhum vínculo. Não fecha 'desatualizada' (``_filtro_em_dia``).
MOTIVO_TUDO_EM_REVISAO = "tudo_em_revisao"
# 'sem_atualizacao' que conta como VERIFICAÇÃO (``ultima_verificacao_em``).
MOTIVOS_VERIFICADOS = (MOTIVO_NADA_MUDOU, "queda_retida")
# A resposta perdeu campos que o Constela usa fora dos essenciais (tempo e questões
# do Elefante, S9): os livros entram, esses números ficam os de antes. 'parcial'
# com dado aplicado; 'sem_atualizacao' sem. Não é "em dia" nem verificação.
MOTIVO_CAMPOS_NAO_ATUALIZADOS = "campos_nao_atualizados"
# 'sem_atualizacao' que NÃO conta como "em dia" (``_filtro_em_dia``).
MOTIVOS_SEM_EM_DIA = (MOTIVO_TUDO_EM_REVISAO, MOTIVO_CAMPOS_NAO_ATUALIZADOS)
# Só estes provam que a plataforma respondeu 2xx e a coleta chegou ao fim: são
# os que podem carimbar a credencial como 'valida'.
STATUS_CREDENCIAL_VALIDA = ("concluida", "parcial", "sem_atualizacao", "sem_dados")


def _filtro_do_acumulado():
    """A execução é a coleta REGULAR (o acumulado, que é o que os rankings usam),
    não uma coleta POR PERÍODO do Matific (``parametros`` com as datas: backfill de
    agosto, premiação da semana). Uma coleta de período passado não renova o
    acumulado — contá-la como "último sucesso"/"em dia" fechava o alerta
    'desatualizada' e zerava a idade do frescor com o ranking ainda de dias atrás."""
    texto = func.coalesce(cast(SincronizacaoExecucao.parametros, String), "")
    return ~texto.like("%matific_start_date%")


def _filtro_aplicou_dado():
    """A execução APLICOU dado: 'concluida' (sem condição, como sempre — também a
    linha antiga com 0 aluno) ou 'parcial' com ≥1 aluno aplicado. A 'parcial' com
    0 aluno (D2(6): falhou só o endpoint dos nomes do Matific e nada mudou) não
    trouxe dado: não é o último sucesso, o frescor nem o selo do ranking (P18),
    nem a referência do 'plataforma_sem_dados' (b9f4a4b). Sem o filtro do
    acumulado: cada uso decide se a coleta por período conta."""
    E = SincronizacaoExecucao
    return E.status.in_(STATUS_COM_DADO) & ((E.status == "concluida") | (E.qtd_alunos > 0))


def execucao_por_periodo(execucao: SincronizacaoExecucao) -> bool:
    """A mesma regra de ``_filtro_do_acumulado``, para uma execução em mãos."""
    return bool((execucao.parametros or {}).get("matific_start_date"))


def _filtro_verificacao():
    """Execuções que provam que o dado foi VERIFICADO (o novo
    ``ultima_verificacao_em``): dado aplicado, plataforma vazia de verdade ou
    coleta completa em que nada mudou — 'nada_mudou' ou 'queda_retida' (o total
    menor ficou retido; o resto foi conferido e nada mudou, e antes isso não
    contava). Linha em revisão ou com defeito não é dado conferido. Só a coleta
    do acumulado conta."""
    return ((SincronizacaoExecucao.status.in_(("concluida", "parcial", "sem_dados"))
             | ((SincronizacaoExecucao.status == "sem_atualizacao")
                & SincronizacaoExecucao.motivo.in_(MOTIVOS_VERIFICADOS)))
            & _filtro_do_acumulado())


def _filtro_em_dia():
    """Execuções que FECHAM o alerta 'desatualizada' (e são a referência da regra
    única de obsolescência): coleta completa e sem falha de unidade que conferiu
    a escola — 'concluida', 'sem_atualizacao' (nada mudou, correspondência
    pendente com ≥1 conta vinculada conferida, total retido, linhas descartadas)
    ou 'parcial' só por linhas descartadas. A 'parcial' com turma/lote/aluno que
    falhou não fecha: parte da escola continua sem dado novo. Pendência de
    revisão e linha com defeito permanente não deixam a escola "desatualizada" —
    têm os alertas próprios ('correspondencia_pendente', 'coleta_parcial'). Só a
    coleta do acumulado conta.

    Decisão registrada na correção da revisão e93 (antes: só 'concluida' e
    'sem_atualizacao/nada_mudou'): uma criança fora da Lista Piloto ou um livro
    sem data abriam o crítico "Sem sincronização bem-sucedida há N dias" num fim
    de semana com a coleta funcionando — e o 34f1a23 não abria.

    Forma C (aceita pelo dono, Etapa 3): 'sem_atualizacao/tudo_em_revisao' NÃO
    conta. Com tudo em revisão e nenhuma conta já vinculada conferida, a coleta
    não provou que o dado DESTA escola está em dia — é a assinatura de credencial
    de outra escola ou de casamento quebrado; o 'desatualizada' abre depois da
    cadência, ao lado do 'correspondencia_pendente'. ``coalesce``: motivo NULL
    (execução anterior à 0039) não é 'tudo_em_revisao'."""
    return (((SincronizacaoExecucao.status == "concluida")
             | ((SincronizacaoExecucao.status == "sem_atualizacao")
                & func.coalesce(SincronizacaoExecucao.motivo, "").notin_(MOTIVOS_SEM_EM_DIA))
             | ((SincronizacaoExecucao.status == "parcial")
                & (SincronizacaoExecucao.motivo == "linhas_descartadas")))
            & _filtro_do_acumulado())


def categoria_do_tipo(tipo: str | None) -> str | None:
    return CATEGORIA_POR_TIPO.get(tipo or "")


def resolver_falhas_da_integracao(db: Session, escola_id: int, plataforma: str, *,
                                  manter: tuple[str, ...] = TIPOS_REGRA_PROPRIA) -> int:
    """Fecha TODOS os alertas abertos de (escola, plataforma), menos os de
    ``manter``. É o fechamento por SUCESSO: uma execução que terminou bem prova
    que as falhas anteriores daquela integração deixaram de valer, qualquer que
    seja o nome do tipo (antes, uma lista fixa se desencontrava dos nomes gravados
    e deixava alertas abertos para sempre). O histórico não some: o alerta fica
    ``resolvido`` com a data. Alerta sem plataforma não é tocado."""
    consulta = select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == escola_id,
        SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.resolvido.is_(False))
    if manter:
        consulta = consulta.where(SincronizacaoAlerta.tipo.notin_(manter))
    n = 0
    for al in db.execute(consulta).scalars():
        al.resolvido = True
        al.resolvido_em = _agora()
        n += 1
    db.flush()
    return n


# --------------------------------------------------------------------------
# Blindagem: OBSOLESCÊNCIA ("os dados estão envelhecendo em silêncio?")
#
# O sistema já alerta quando uma EXECUÇÃO falha. Mas o risco pior é o silencioso:
# a agenda parou, a credencial expirou ou toda tentativa vem falhando — e o dado
# vai ficando velho sem ninguém notar ("por que esse dado é da semana passada?").
# Aqui a gente detecta isso: uma integração AGENDADA sem sincronização BEM-
# SUCEDIDA além do limite da cadência abre um alerta 'desatualizada' (deduplicado)
# que se resolve sozinho quando uma sync conclui com dados.
# --------------------------------------------------------------------------

# Tempo sem sucesso (status "concluida") até considerar a integração desatualizada.
# Folga sobre a cadência: uma janela perdida + margem. Cadências sem agenda (manual)
# não disparam alerta automático.
OBSOLETO_POR_CADENCIA = {
    "diaria": timedelta(days=2),
    "semanal": timedelta(days=10),
}


def limite_obsolescencia(cadencia: str) -> timedelta | None:
    return OBSOLETO_POR_CADENCIA.get(cadencia)


def ultimo_sucesso_em(db: Session, escola_id: int, plataforma: str) -> datetime | None:
    """Quando foi a última sincronização que APLICOU dado ('concluida', ou
    'parcial' com ≥1 aluno aplicado — ``_filtro_aplicou_dado``) desta integração
    — o marco de 'frescor' do dado. Falhas, 'sem_dados', 'sem_atualizacao' e a
    'parcial' sem aluno aplicado não contam (nada novo entrou), nem a coleta por
    período do Matific (não renova o acumulado dos rankings)."""
    return db.scalar(
        select(func.max(SincronizacaoExecucao.finalizada_em)).where(
            SincronizacaoExecucao.escola_id == escola_id,
            SincronizacaoExecucao.plataforma == plataforma,
            _filtro_sucesso(),
        ))


def _filtro_sucesso():
    """Execuções que contam como "último sucesso" (``ultimo_sucesso_em``)."""
    return _filtro_aplicou_dado() & _filtro_do_acumulado()


@dataclass(frozen=True)
class MarcosDaIntegracao:
    """Os marcos de UMA integração que o /status mostra, lidos de uma vez
    (``marcos_por_plataforma``)."""
    ultimo_sucesso_em: datetime | None = None
    ultimo_em_dia_em: datetime | None = None
    ultima_verificacao_em: datetime | None = None
    # Alguma execução da integração tem a marca ``recalculo_pendente``
    # (a metade "marca" de ``recalculo_pendente_aberto``).
    recalculo_marcado: bool = False


def marcos_por_plataforma(db: Session, escola_id: int) -> dict[str, MarcosDaIntegracao]:
    """``ultimo_sucesso_em``, ``ultimo_em_dia_em``, ``ultima_verificacao_em`` e a
    marca de recálculo pendente de TODAS as integrações da escola numa consulta
    agrupada por plataforma — os mesmos filtros das funções de uma plataforma só
    (cada MAX filtrado é o MAX daquela função). O /status pagava quatro idas ao
    banco por plataforma para isto. Plataforma sem execução não aparece."""
    E = SincronizacaoExecucao

    def _max_onde(filtro):
        return func.max(case((filtro, E.finalizada_em), else_=None))

    linhas = db.execute(
        select(E.plataforma,
               _max_onde(_filtro_sucesso()),
               _max_onde(_filtro_em_dia()),
               _max_onde(_filtro_verificacao()),
               func.max(case((E.recalculo_pendente.is_(True), 1), else_=0)))
        .where(E.escola_id == escola_id)
        .group_by(E.plataforma)
    ).all()
    return {plataforma: MarcosDaIntegracao(sucesso, em_dia, verificacao, bool(marca))
            for plataforma, sucesso, em_dia, verificacao, marca in linhas}


def ultima_verificacao_em(db: Session, escola_id: int, plataforma: str) -> datetime | None:
    """Quando a integração foi VERIFICADA por último: dado aplicado, plataforma
    vazia de verdade ou coleta completa em que nada mudou ('sem_atualizacao' com
    motivo 'nada_mudou' ou 'queda_retida'). Diferente do último sucesso:
    verificar não é atualizar."""
    return db.scalar(
        select(func.max(SincronizacaoExecucao.finalizada_em)).where(
            SincronizacaoExecucao.escola_id == escola_id,
            SincronizacaoExecucao.plataforma == plataforma,
            _filtro_verificacao()))


def ultimo_em_dia_em(db: Session, escola_id: int, plataforma: str) -> datetime | None:
    """Referência da regra ÚNICA de obsolescência ('desatualizada'): a última
    coleta completa e sem falha de unidade (``_filtro_em_dia``). A 'parcial' com
    unidade que falhou não fecha o alerta."""
    return db.scalar(
        select(func.max(SincronizacaoExecucao.finalizada_em)).where(
            SincronizacaoExecucao.escola_id == escola_id,
            SincronizacaoExecucao.plataforma == plataforma,
            _filtro_em_dia()))


def _referencia_frescor(cfg: SincronizacaoConfig, ultimo: datetime | None) -> datetime | None:
    """Marco a partir do qual medir a obsolescência: o último sucesso ou, se nunca
    houve, quando a AGENDA passou a valer (``updated_at``, bumpado ao ativar/trocar
    cadência) — NÃO a criação da linha. Assim uma agenda ANTIGA reativada hoje ganha
    a folga da cadência a partir de agora, em vez de alertar na hora ("cry-wolf")."""
    # NORMALIZA para naive: created_at/updated_at vêm do default do modelo
    # (base.agora() é tz-AWARE) e num objeto recém-flushado ainda estão aware;
    # _agora() e os datetimes do sync são naive. Sem isto, subtrair aware de naive
    # levanta TypeError. Lido do banco já volta naive — a normalização é a rede.
    return _naive_utc(ultimo or cfg.updated_at)


def _desatualizada(cfg: SincronizacaoConfig, ultimo: datetime | None,
                   agora: datetime) -> bool:
    """A regra ÚNICA de obsolescência: integração AGENDADA (ativa, cadência com
    limite) sem sucesso há mais que o limite. O /status, a varredura do agendador,
    o fim de cada execução e o painel global usam ESTA função."""
    limite = limite_obsolescencia(cfg.cadencia)
    if limite is None or not cfg.ativo:
        return False
    referencia = _referencia_frescor(cfg, ultimo)
    return referencia is not None and (agora - referencia) > limite


def esta_desatualizada(db: Session, cfg: SincronizacaoConfig,
                       agora: datetime | None = None) -> bool:
    """True se a integração AGENDADA está sem coleta em dia (``ultimo_em_dia_em``)
    há mais que o limite da cadência — para uma escola só, ex.: /status."""
    return _desatualizada(cfg, ultimo_em_dia_em(db, cfg.escola_id, cfg.plataforma),
                          agora or _agora())


# Sem agenda (cadência manual) não existe alerta automático — mas a TELA ainda
# tem de dizer se o dado está em dia, em vez de "Funcionando" para um dado de
# semanas atrás. Vale a mesma folga da cadência diária.
LIMITE_FRESCOR_SEM_AGENDA = timedelta(days=2)


def limite_frescor(cfg: SincronizacaoConfig | None) -> timedelta:
    """Idade máxima do último sucesso para o dado contar como "atualizado"."""
    limite = limite_obsolescencia(cfg.cadencia) if (cfg is not None and cfg.ativo) else None
    return limite or LIMITE_FRESCOR_SEM_AGENDA


def frescor(cfg: SincronizacaoConfig | None, ultimo: datetime | None,
            agora: datetime | None = None) -> dict:
    """Estado de frescor do DADO (não da última tentativa): 'atualizado' (último
    sucesso dentro do limite), 'desatualizado' (fora dele) ou 'sem_sucesso'
    (nunca houve). Com a idade em horas — a tela diz "há N dias"."""
    agora = agora or _agora()
    limite = limite_frescor(cfg)
    ultimo = _naive_utc(ultimo)
    if ultimo is None:
        return {"frescor": "sem_sucesso", "idade_horas": None,
                "limite_horas": int(limite.total_seconds() // 3600)}
    idade = max(timedelta(0), agora - ultimo)
    return {"frescor": "atualizado" if idade <= limite else "desatualizado",
            "idade_horas": int(idade.total_seconds() // 3600),
            "limite_horas": int(limite.total_seconds() // 3600)}


def _mensagem_desatualizada(dias: int) -> str:
    texto = (f"Sem sincronização bem-sucedida há {dias} dia(s) — os dados desta "
             "plataforma podem estar desatualizados.")
    if not agendador_ligado():
        # A causa mais comum hoje: a agenda da escola está ativa, mas o agendador
        # do servidor está desligado — dizer "confira a agenda" mandaria a escola
        # procurar um problema que não é dela.
        texto += (" A atualização automática está pausada neste servidor: os dados "
                  "só mudam quando alguém clica em “Sincronizar agora”.")
    return texto


def atualizar_alerta_desatualizada(db: Session, cfg: SincronizacaoConfig | None, *,
                                   agora: datetime | None = None,
                                   ultimo: datetime | None = None,
                                   ultimo_informado: bool = False) -> bool:
    """Abre (ou atualiza a idade d)o alerta 'desatualizada' se a integração está
    obsoleta pela regra ÚNICA; fecha-o se não está. Devolve se está desatualizada.

    Por que fora do agendador: a verificação só rodava DENTRO dele — desligado
    (como em produção desde 17/09), o alerta nunca abria, e o painel global dizia
    "0 desatualizadas" enquanto os dados tinham semanas. Agora roda também na
    leitura do /status e ao fim de cada execução (manual ou automática)."""
    return revisar_alerta_desatualizada(db, cfg, agora=agora, ultimo=ultimo,
                                        ultimo_informado=ultimo_informado)[0]


def revisar_alerta_desatualizada(db: Session, cfg: SincronizacaoConfig | None, *,
                                 agora: datetime | None = None,
                                 ultimo: datetime | None = None,
                                 ultimo_informado: bool = False,
                                 abertos: list[SincronizacaoAlerta] | None = None,
                                 no_plano: bool | None = None,
                                 ) -> tuple[bool, bool]:
    """O ciclo de vida de ``atualizar_alerta_desatualizada`` (a mesma regra),
    devolvendo ``(desatualizada, gravou)``: ``gravou`` diz se algum alerta foi
    aberto, fechado ou teve o texto trocado — o GET /status só commita quando
    gravou (antes commitava toda leitura, um COMMIT e uma nova conexão a cada
    consulta da tela).

    ``abertos``: os alertas 'desatualizada' ABERTOS desta integração, já lidos
    pelo chamador na mesma transação (o /status lê todos os abertos da escola
    numa consulta). Sem eles, a função consulta o banco como sempre. O caminho
    que INSERE (com o lock da config) é o mesmo nos dois casos.

    ``no_plano``: se a plataforma está no plano da rede da escola
    (``plataforma_no_plano``), já lido pelo chamador — o /status lê o contrato na
    mesma consulta da escola; sem isso, a escola de rede pagava uma ida a
    ``modulos_rede`` por plataforma. Sem ele (None), a função consulta como sempre."""
    if cfg is None:
        return False, False
    if no_plano is None:
        no_plano = plataforma_no_plano(db, cfg.escola_id, cfg.plataforma)
    if not no_plano:
        # Módulo fora do plano: a plataforma não é coletada (``executar``,
        # ``enfileirar_agendados``), então não "envelhece" — mesma régua da agenda
        # desligada. Fecha o alerta que tenha ficado do tempo do contrato.
        return False, _fechar_desatualizada(db, cfg, abertos) > 0
    agora = agora or _agora()
    if not ultimo_informado:
        ultimo = ultimo_em_dia_em(db, cfg.escola_id, cfg.plataforma)
    if not _desatualizada(cfg, ultimo, agora):
        return False, _fechar_desatualizada(db, cfg, abertos) > 0
    referencia = _referencia_frescor(cfg, ultimo)
    mensagem = _mensagem_desatualizada(max(1, (agora - referencia).days))
    consulta_aberto = select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == cfg.escola_id,
        SincronizacaoAlerta.plataforma == cfg.plataforma,
        SincronizacaoAlerta.tipo == "desatualizada",
        SincronizacaoAlerta.resolvido.is_(False))
    if abertos is None:
        aberto = db.execute(consulta_aberto).scalars().first()
    else:
        aberto = next((al for al in sorted(abertos, key=lambda al: al.id)
                       if not al.resolvido), None)
    if aberto is None and cfg.id is not None:
        # SERIALIZA a abertura por integração: a tela pede o /status duas vezes
        # ao mesmo tempo (Layout + página Integrações) e duas transações que não
        # se viam passavam juntas pelo "não há aberto" e inseriam dois alertas —
        # não há índice único que impeça. O lock da linha da config (PostgreSQL;
        # o SQLite ignora o FOR UPDATE) só é pedido quando vai INSERIR, então a
        # leitura de sempre não espera ninguém; a 2ª transação, liberada pelo
        # commit da 1ª, relê (nova leitura no READ COMMITTED) e acha o alerta.
        db.execute(select(SincronizacaoConfig.id).where(
            SincronizacaoConfig.id == cfg.id).with_for_update())
        aberto = db.execute(consulta_aberto).scalars().first()
    if aberto is None:
        abrir_alerta(db, cfg.escola_id, cfg.plataforma, "desatualizada", mensagem,
                     severidade="critico")
        return True, True
    if aberto.mensagem != mensagem:
        aberto.mensagem = mensagem[:500]   # a idade do dado anda; o texto acompanha
        db.flush()
        return True, True
    return True, False


def _fechar_desatualizada(db: Session, cfg: SincronizacaoConfig,
                          abertos: list[SincronizacaoAlerta] | None) -> int:
    """Fecha o 'desatualizada' aberto da integração: o já lido (``abertos``) ou,
    sem ele, o que a consulta de sempre achar. Devolve quantos fechou."""
    if abertos is None:
        return resolver_alertas(db, cfg.escola_id, cfg.plataforma, ("desatualizada",))
    return _marcar_resolvidos(db, abertos)


def _mapa_ultimo_sucesso(db: Session) -> dict[tuple[int, str], datetime]:
    """{(escola_id, plataforma): última coleta EM DIA (``ultimo_em_dia_em``)} em
    UMA consulta agregada — evita um MAX por config na varredura (N+1). É a
    referência da regra de obsolescência, a mesma do /status."""
    linhas = db.execute(
        select(SincronizacaoExecucao.escola_id, SincronizacaoExecucao.plataforma,
               func.max(SincronizacaoExecucao.finalizada_em))
        .where(_filtro_em_dia())
        .group_by(SincronizacaoExecucao.escola_id, SincronizacaoExecucao.plataforma)
    ).all()
    return {(eid, plat): ultimo for eid, plat, ultimo in linhas}


def verificar_obsolescencia(db: Session) -> int:
    """Varre as integrações AGENDADAS e abre um alerta 'desatualizada' para as que
    envelheceram em silêncio. Idempotente (abrir_alerta deduplica). Devolve quantas
    estão desatualizadas. Escala: uma consulta agregada do último sucesso (não N)."""
    agora = _agora()
    configs = db.execute(
        select(SincronizacaoConfig).where(
            SincronizacaoConfig.ativo.is_(True),
            SincronizacaoConfig.cadencia.in_(tuple(OBSOLETO_POR_CADENCIA)),
        )
    ).scalars().all()
    if not configs:
        return 0
    ultimos = _mapa_ultimo_sucesso(db)  # 1 consulta, não N
    n = 0
    for cfg in configs:
        if atualizar_alerta_desatualizada(
                db, cfg, agora=agora, ultimo=ultimos.get((cfg.escola_id, cfg.plataforma)),
                ultimo_informado=True):
            n += 1
        # Commit POR integração: a abertura do alerta trava a linha da config, e
        # segurar várias até o fim da varredura cruzaria a ordem de locks com um
        # /status que abre os alertas da mesma escola (deadlock). Custo: a
        # próxima config é relida pela chave primária depois do commit.
        db.commit()
    return n


def escolas_desatualizadas(db: Session, agora: datetime | None = None) -> set[int]:
    """Escolas com ≥1 integração AGENDADA desatualizada, pela MESMA regra do
    /status. O painel global contava pelos alertas 'desatualizada' — que só
    nasciam com o agendador ligado: desligado, o painel dizia 0 enquanto os
    cards das escolas diziam o contrário.

    Idas ao banco FIXAS, qualquer que seja o número de agendas (o painel é relido
    pelo polling da tela e cada ida custa ~195 ms em produção): numa consulta, as
    agendas com a última coleta em dia de cada uma (a referência de
    ``_mapa_ultimo_sucesso``, numa subconsulta correlacionada); noutra, o contrato
    das escolas vencidas (``modulos.modulos_por_escola``). Antes, uma ida por
    agenda vencida para a escola e outra para ``modulos_rede`` — com os
    pré-requisitos, o painel ia de 25 a 194 instruções com 0 a 28 escolas vencidas."""
    agora = agora or _agora()
    E = SincronizacaoExecucao
    ultimo_em_dia = (select(func.max(E.finalizada_em))
                     .where(E.escola_id == SincronizacaoConfig.escola_id,
                            E.plataforma == SincronizacaoConfig.plataforma, _filtro_em_dia())
                     .scalar_subquery())
    linhas = db.execute(
        select(SincronizacaoConfig, ultimo_em_dia).where(
            SincronizacaoConfig.ativo.is_(True),
            SincronizacaoConfig.cadencia.in_(tuple(OBSOLETO_POR_CADENCIA)))
    ).all()
    vencidas = [cfg for cfg, ultimo in linhas if _desatualizada(cfg, ultimo, agora)]
    if not vencidas:
        return set()
    # O contrato só é consultado para quem já está desatualizado: a plataforma
    # fora do plano não é coletada e não conta (ver ``atualizar_alerta_desatualizada``).
    modulos = svc_modulos.modulos_por_escola(db, {cfg.escola_id for cfg in vencidas})
    return {cfg.escola_id for cfg in vencidas
            if svc_modulos.plataforma_contratada(modulos[cfg.escola_id], cfg.plataforma)}


# --------------------------------------------------------------------------
# Fila
# --------------------------------------------------------------------------
def _execucao_ativa(db: Session, escola_id: int, plataforma: str):
    return db.execute(
        select(SincronizacaoExecucao).where(
            SincronizacaoExecucao.escola_id == escola_id,
            SincronizacaoExecucao.plataforma == plataforma,
            SincronizacaoExecucao.status.in_(("fila", "executando")),
        )
    ).scalars().first()


def _esta_travada(execucao: SincronizacaoExecucao) -> bool:
    """True se a execução em 'executando' está sem SINAL DE VIDA há mais de
    ``SYNC_SEM_SINAL_S`` (worker morto, redeploy no meio) — órfã, precisa ser
    recuperada. O critério é o último registro no log dela, não a idade: quem está
    vivo escreve nele (``_sinal_de_vida_enquanto_roda``), então uma coleta longa não
    é reivindicada, e a que morreu é liberada em minutos, não em 60."""
    if execucao.status != "executando" or execucao.iniciada_em is None:
        return False
    limite = _agora() - timedelta(seconds=settings.SYNC_SEM_SINAL_S)
    if _naive_utc(execucao.iniciada_em) >= limite:
        return False          # recente: o 1º sinal de vida ainda nem era devido
    db = object_session(execucao)
    if db is None:
        return False          # sem como conferir o sinal: na dúvida, está viva
    sinal = ultimo_sinal_de_vida(db, execucao)
    return sinal is None or sinal < limite


def _orfas_em_execucao(db: Session) -> list[SincronizacaoExecucao]:
    """As execuções que ``_esta_travada`` reivindicaria, numa consulta só."""
    limite = _agora() - timedelta(seconds=settings.SYNC_SEM_SINAL_S)
    linhas = db.execute(
        select(SincronizacaoExecucao, consulta_ultimo_log()).where(
            SincronizacaoExecucao.status == "executando",
            SincronizacaoExecucao.iniciada_em.isnot(None),
            SincronizacaoExecucao.iniciada_em < limite)
    ).all()
    return [ex for ex, ultimo_log in linhas
            if (sinal := sinal_de_vida(ex, ultimo_log)) is None or sinal < limite]


def _gravou_arquivo(db: Session, execucao_id: int) -> bool:
    """A execução chegou a GRAVAR algum arquivo da aplicação? O log 'parser' que
    abre cada arquivo (``orchestrator.aplicar_arquivo``) é do contexto NÃO
    autônomo da execução: só fica no banco junto com um commit da fase de
    aplicação (o /confirmar de cada arquivo commita o seu dado). Órfã sem ele
    morreu antes de gravar qualquer arquivo — quase sempre na coleta."""
    return db.execute(select(SincronizacaoLog.id).where(
        SincronizacaoLog.execucao_id == execucao_id,
        SincronizacaoLog.etapa == "parser").limit(1)).first() is not None


def _finalizar_travada(db: Session, execucao: SincronizacaoExecucao, *,
                       origem: str = "travada_no_pedido") -> bool:
    """Marca (atomicamente) uma execução órfã como 'erro'. Devolve True se ESTE
    chamador a reivindicou (para então re-enfileirar/limpar a exclusão mútua).

    Se ela morreu DEPOIS de gravar um arquivo, ganha a marca ``recalculo_pendente``:
    o recálculo do fim (que é quem grava a marca) não chegou a rodar, e sem ela as
    notas ficavam atrás dos retratos — a coleta seguinte, com os mesmos números
    ('nada mudou'), não recalculava. Com a marca, o /status avisa e a próxima coleta
    (ou o /recalcular) recalcula e a zera (``resolver_recalculo_pendente``). A órfã
    que morreu na coleta não ganha a marca: nada foi gravado.

    Quem reivindicou anota a linha do fim (``origem``: quem achou a órfã), que sai
    no log no commit do chamador; quem perdeu a corrida não encerrou nada."""
    execucao_id, escola_id, plataforma = (execucao.id, execucao.escola_id,
                                          execucao.plataforma)
    valores = {"status": "erro", "finalizada_em": _agora(),
               "erro_resumo": "Interrompida (reinício do serviço ou timeout)."}
    if _gravou_arquivo(db, execucao_id):
        valores["recalculo_pendente"] = True
    reivindicou = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao_id,
               SincronizacaoExecucao.status == "executando")
        .values(**valores)
    ).rowcount
    if reivindicou == 1:
        _anotar_fim(db, execucao_id, escola_id, plataforma, "erro", origem=origem)
    return reivindicou == 1


def _fechar_se_ainda_executando(db: Session, execucao: SincronizacaoExecucao,
                                status: str) -> bool:
    """Grava o status final SÓ se a execução ainda está 'executando' (UPDATE
    condicional, o par do ``_finalizar_travada``). False: outro caminho já a
    encerrou enquanto esta thread trabalhava — antes o status era sobrescrito e uma
    'erro' ("Interrompida") voltava a ser 'concluida', com a nova tentativa já na
    fila. ``synchronize_session=False`` e o valor em memória só depois de vencer: o
    objeto desta thread pode estar velho, e a sincronização avaliada em Python o
    daria por fechado mesmo sem a linha ter mudado."""
    fechou = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao.id,
               SincronizacaoExecucao.status == "executando")
        .values(status=status)
        .execution_options(synchronize_session=False)).rowcount == 1
    if fechou:
        set_committed_value(execucao, "status", status)
    return fechou


def _perdeu_o_fechamento(db: Session, execucao: SincronizacaoExecucao, ap: _Apuracao) -> None:
    """Outro caminho encerrou esta execução e o estado dele vale. O que esta thread
    gravou fica (cada arquivo commita o seu) e as notas ficam para a marca de
    recálculo pendente. Cursor, credencial e alertas não são tocados: uma execução
    nova pode estar rodando, e ela é quem responde pela integração agora."""
    ap.perdeu_o_fechamento = True
    if ap.aplicados:
        execucao.recalculo_pendente = True
    registrar_log(db, execucao, "scheduler", "warn",
                  "A execução já tinha sido encerrada como interrompida enquanto esta "
                  "coleta ainda rodava: o resultado dela não muda esse estado. O que já "
                  "foi gravado fica, e as notas serão recalculadas na próxima coleta.")


# --------------------------------------------------------------------------
# Sinal de vida das execuções MANUAIS na fila
#
# Uma manual fica em 'fila' enquanto a thread dela espera ``_semaforo_manual`` —
# SEM prazo: atrás de uma coleta completa do Elefante, ou de 16 cliques numa
# manhã de coletas manuais, a espera passa fácil de 30 min. Antes, "criada há
# mais de SYNC_TRAVADA_S" bastava para concluir que a thread tinha morrido: o
# GET /status (a tela o chama a cada 4 s) e o boot de outro worker cancelavam o
# pedido VIVO, com uma mensagem culpando o agendador, e a thread, ao ganhar a
# vez, perdia o claim e saía sem coletar nada. Agora quem espera dá sinal de
# vida: neste processo, pelo registro em memória; para os outros workers e
# réplicas (``WEB_CONCURRENCY`` > 1), por uma linha no log da execução a cada
# ``batimento_fila_s()``. Órfã = nenhuma thread aqui E nenhum sinal há mais de
# SYNC_TRAVADA_S — o processo que a esperava morreu.
# --------------------------------------------------------------------------
_vivas_neste_processo: set[int] = set()   # ids com thread viva (esperando/rodando)
_vivas_lock = threading.Lock()


def batimento_fila_s() -> float:
    """Intervalo do sinal de vida de quem espera: 6 sinais por janela de
    SYNC_TRAVADA_S, para um atraso ou uma falha de banco não bastarem para a
    execução parecer órfã."""
    return max(1.0, settings.SYNC_TRAVADA_S / 6)


def ultimo_sinal_de_vida(db: Session, execucao: SincronizacaoExecucao) -> datetime | None:
    """O mais novo entre o marco da execução e o último registro no log dela. Na
    fila, o marco é a criação, e só quem espera a vez escreve no log; em
    'executando', é o início, e escrevem a própria coleta e o
    ``_sinal_de_vida_enquanto_roda``."""
    ultimo_log = db.scalar(select(func.max(SincronizacaoLog.created_at)).where(
        SincronizacaoLog.execucao_id == execucao.id))
    return sinal_de_vida(execucao, ultimo_log)


def consulta_ultimo_log():
    """O último registro no log de CADA execução, como coluna correlacionada de
    uma consulta de ``SincronizacaoExecucao`` — para ler o sinal de vida de várias
    execuções na mesma ida (``sinal_de_vida``), não uma ida por execução."""
    return (select(func.max(SincronizacaoLog.created_at))
            .where(SincronizacaoLog.execucao_id == SincronizacaoExecucao.id)
            .scalar_subquery())


def sinal_de_vida(execucao: SincronizacaoExecucao, ultimo_log: datetime | None,
                  ) -> datetime | None:
    """A regra de ``ultimo_sinal_de_vida`` com o último log já lido."""
    marco = execucao.iniciada_em if execucao.status == "executando" else execucao.created_at
    marcos = [m for m in (_naive_utc(marco), _naive_utc(ultimo_log)) if m]
    return max(marcos) if marcos else None


def _manual_orfa(execucao: SincronizacaoExecucao, agora: datetime) -> bool:
    """Manual na fila sem ninguém esperando por ela (ver o bloco acima)."""
    if execucao.id in _vivas_neste_processo:
        return False
    limite = agora - timedelta(seconds=settings.SYNC_TRAVADA_S)
    criada = _naive_utc(execucao.created_at)
    if criada is None or criada >= limite:
        return False          # recente: o 1º sinal de vida ainda nem era devido
    db = object_session(execucao)
    if db is None:
        return False          # sem como conferir o sinal: na dúvida, está viva
    sinal = ultimo_sinal_de_vida(db, execucao)
    return sinal is None or sinal < limite


def so_o_agendador_roda(execucao: SincronizacaoExecucao, *,
                        agora: datetime | None = None) -> bool:
    """A execução está na fila e SÓ o agendador a roda — nenhuma thread espera
    por ela: é agendada (``origem='scheduler'``), é uma NOVA TENTATIVA com backoff
    (``disponivel_em`` — a thread que a criou já terminou) ou é uma manual ÓRFÃ
    (``_manual_orfa``: sem thread neste processo e sem sinal de vida há mais de
    ``SYNC_TRAVADA_S`` — o processo que a esperava morreu). A IDADE de uma manual
    sozinha não prova nada: ela pode estar esperando a vez no semáforo.
    Com o agendador desligado, uma execução assim não roda nunca."""
    if execucao.status != "fila":
        return False
    if execucao.origem == "scheduler" or execucao.disponivel_em is not None:
        return True
    return _manual_orfa(execucao, agora or _agora())


def _cancelar_na_fila(db: Session, execucao: SincronizacaoExecucao, motivo: str, *,
                      origem: str = "cancelada_na_fila") -> bool:
    """Cancela (atomicamente) uma execução AINDA na fila, com registro no log
    dela. Devolve False se ela saiu da fila no meio do caminho (alguém a
    reivindicou) — aí não é cancelada, e não há linha do fim para este chamador.
    Nunca apaga: o histórico é permanente. ``origem``: o caminho que cancelou
    (vai na linha do fim, que sai no log no commit do chamador)."""
    execucao_id, escola_id, plataforma = (execucao.id, execucao.escola_id,
                                          execucao.plataforma)
    cancelou = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao_id,
               SincronizacaoExecucao.status == "fila")
        .values(status="cancelada", finalizada_em=_agora(), erro_resumo=motivo[:300])
    ).rowcount == 1
    if cancelou:
        db.add(SincronizacaoLog(execucao_id=execucao_id, escola_id=escola_id,
                                etapa="scheduler", nivel="warn", mensagem=motivo[:1000]))
        db.flush()
        db.expire(execucao)
        # Nunca rodou: nenhum aluno aplicado.
        _anotar_fim(db, execucao_id, escola_id, plataforma, "cancelada", origem=origem,
                    alunos_aplicados=0)
    return cancelou


_MSG_FORA_DO_PLANO = ("Cancelada antes de coletar: o módulo da plataforma {plataforma} "
                      "não faz parte do plano desta rede.")


def plataforma_no_plano(db: Session, escola_id: int, plataforma: str) -> bool:
    """O módulo da plataforma está no plano da rede da escola? (cascata do
    contrato: ``services/modulos``). Plataforma fora do catálogo → True."""
    return svc_modulos.plataforma_contratada(
        svc_modulos.modulos_da_escola(db, db.get(Escola, escola_id)), plataforma)


def enfileirar_ou_reaproveitar(
        db: Session, escola_id: int, plataforma: str, *, origem: str,
        usuario_id: int | None = None, tentativa: int = 1,
        disponivel_em: datetime | None = None,
        parametros: dict | None = None) -> tuple[SincronizacaoExecucao, bool]:
    """Cria uma execução na fila. IDEMPOTENTE / anti-duplicidade em DUAS camadas:
    (1) fast-path: se já houver uma ativa (fila/executando) para (escola,
    plataforma), devolve-a; (2) garantia forte: o índice único parcial
    ``uq_sync_exec_ativa`` no banco impede que dois enfileiramentos concorrentes
    (clique duplo, scheduler + manual, múltiplas réplicas) criem duas ativas —
    a corrida perdida cai no ``IntegrityError`` e devolve a existente.

    PEDIDO MANUAL × FILA: o manual não fica refém de uma execução que está na
    fila esperando o agendador (nova tentativa com backoff, agendada, manual
    esquecida) nem herda os parâmetros dela — antes, "Coletar o período" devolvia
    a nova tentativa SEM as datas e coletava o ano inteiro. O manual a CANCELA
    (com registro) e entra no lugar. Só o clique repetido do mesmo pedido (manual
    recente, mesmos parâmetros) é deduplicado.

    Devolve ``(execucao, reaproveitada)``: ``reaproveitada`` é True quando a
    execução JÁ EXISTIA (a ativa de antes, ou a que um pedido concorrente criou)
    e False quando foi criada agora. O "Sincronizar agora" usa isso para não
    disparar outra thread para uma coleta que já está rodando e para dizer, na
    resposta, que o pedido se juntou a ela."""
    ativa = _execucao_ativa(db, escola_id, plataforma)
    if (ativa is not None and origem == "manual" and ativa.status == "fila"
            and (so_o_agendador_roda(ativa)
                 or (ativa.parametros or {}) != (parametros or {}))):
        if _cancelar_na_fila(
                db, ativa, "Substituída por um pedido manual de sincronização "
                           f"(tentativa {ativa.tentativa}, origem {ativa.origem}).",
                origem="cancelada_por_pedido_manual"):
            ativa = None
        else:
            ativa = _execucao_ativa(db, escola_id, plataforma)   # foi reivindicada
    if ativa is not None:
        if not _esta_travada(ativa):
            return ativa, True
        # Órfã presa em 'executando' (worker morto/redeploy). Auto-cura: tenta
        # reivindicá-la e liberá-la para criar a nova — senão a exclusão mútua
        # (uq_sync_exec_ativa) travaria a escola até um reinício. (Linha do fim com
        # a origem padrão, 'travada_no_pedido', no commit de quem pediu.)
        if _finalizar_travada(db, ativa):
            abrir_alerta(db, escola_id, plataforma, "interrompida",
                         "Sincronização anterior foi interrompida e reprogramada.",
                         severidade="warn", execucao_id=ativa.id)
            db.flush()
        else:
            # Perdemos a corrida para o reaper concorrente: NÃO devolver a órfã
            # já morta (o pedido deste chamador se perderia). Re-checa o estado —
            # se o reaper re-enfileirou uma nova ativa, devolve-a; senão (ex.:
            # última tentativa, sem retry) cai adiante e cria a que foi pedida.
            ativa = _execucao_ativa(db, escola_id, plataforma)
            if ativa is not None:
                return ativa, True
    execucao = SincronizacaoExecucao(
        escola_id=escola_id, plataforma=plataforma, origem=origem,
        usuario_id=usuario_id, status="fila", tentativa=tentativa,
        disponivel_em=disponivel_em, parametros=parametros or {},
        conector_versao=getattr(connectors.obter(plataforma), "versao", None))
    try:
        with db.begin_nested():          # savepoint: só o INSERT rola em conflito
            db.add(execucao)
            db.flush()
    except IntegrityError:
        # Outro worker/clique criou a ativa entre o SELECT e o INSERT.
        existente = _execucao_ativa(db, escola_id, plataforma)
        if existente is not None:
            return existente, True
        raise
    return execucao, False


def enfileirar(db: Session, escola_id: int, plataforma: str, *, origem: str,
               usuario_id: int | None = None, tentativa: int = 1,
               disponivel_em: datetime | None = None,
               parametros: dict | None = None) -> SincronizacaoExecucao:
    """``enfileirar_ou_reaproveitar`` para quem só precisa da execução (a nova
    ou a ativa reaproveitada) — agendador, novas tentativas, scripts."""
    execucao, _reaproveitada = enfileirar_ou_reaproveitar(
        db, escola_id, plataforma, origem=origem, usuario_id=usuario_id,
        tentativa=tentativa, disponivel_em=disponivel_em, parametros=parametros)
    return execucao


def proximas_da_fila(db: Session, limite: int = 10) -> list[SincronizacaoExecucao]:
    agora = _agora()
    return list(db.execute(
        select(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.status == "fila",
               (SincronizacaoExecucao.disponivel_em.is_(None))
               | (SincronizacaoExecucao.disponivel_em <= agora))
        .order_by(SincronizacaoExecucao.id)
        .limit(limite)
    ).scalars())


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------
def _contexto(db: Session, execucao: SincronizacaoExecucao, *,
              autonomo: bool = False) -> Contexto:
    """autonomo=True: cada log COMMITA — usado na fase de FETCH externo, para
    não segurar uma transação aberta durante a I/O de rede/navegador
    (idle-in-transaction derrubaria a conexão em Postgres gerenciado).
    autonomo=False (padrão): o log participa da transação da execução
    (persistência atômica, com um único commit no fim)."""
    def log(etapa: str, nivel: str, mensagem: str) -> None:
        registrar_log(db, execucao, etapa, nivel, mensagem)
        if autonomo:
            db.commit()
    return Contexto(escola_id=execucao.escola_id, execucao_id=execucao.id,
                    log=log, timeout_s=settings.SYNC_TIMEOUT_S)


_NS_INCREMENTAL = "sync_incremental"   # namespace da Configuracao (KV) por escola


def _carregar_contadores(db: Session, escola_id: int, plataforma: str) -> dict:
    """{studentId: total_de_livros} da última sync bem-sucedida (por escola/
    plataforma). Base do incremental SEGURO por aluno: quem não mudou, o conector
    pula. Guardado na tabela Configuracao (KV genérico — sem migração)."""
    from app.models.configuracao import Configuracao

    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == _NS_INCREMENTAL,
            Configuracao.chave == plataforma)
    ).scalar_one_or_none()
    return dict(row.valor) if row and isinstance(row.valor, dict) else {}


def _salvar_contadores(db: Session, escola_id: int, plataforma: str,
                       contadores: dict, *, substituir: bool = False) -> None:
    """Persiste (fazendo MERGE) as contagens por aluno vistas nesta sync. O merge
    preserva as contagens de turmas que falharam nesta rodada (não vieram em
    ``contadores``) — assim uma falha parcial nunca zera o cursor de um aluno.

    ``substituir`` (recoleta COMPLETA com unidade que falhou): o cursor passa a ser
    só o desta rodada. Quem falhou perde o cursor e a próxima coleta incremental o
    busca inteiro — o merge mantinha o antigo e, com o agregado da turma parado, o
    aluno era pulado até a recoleta seguinte, 7 dias depois."""
    if not contadores and not substituir:
        return
    from app.models.configuracao import Configuracao

    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == _NS_INCREMENTAL,
            Configuracao.chave == plataforma)
    ).scalar_one_or_none()
    if row is None:
        if not contadores:
            return
        row = Configuracao(escola_id=escola_id, namespace=_NS_INCREMENTAL,
                           chave=plataforma, valor={})
        db.add(row)
    atual = {} if substituir else (dict(row.valor) if isinstance(row.valor, dict) else {})
    for sid, total in contadores.items():
        try:
            atual[str(sid)] = int(total)
        except (TypeError, ValueError):
            continue
    row.valor = atual


# RECONCILIAÇÃO PERIÓDICA (ver `_coleta_completa_devida`): de quantos em
# quantos dias a sincronização ignora o cursor e recoleta TUDO.
DIAS_ENTRE_COLETAS_COMPLETAS = 7
_SUFIXO_COMPLETA = ":ultima_coleta_completa"


def _linha_coleta_completa(db: Session, escola_id: int, plataforma: str):
    from app.models.configuracao import Configuracao

    return db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == _NS_INCREMENTAL,
            Configuracao.chave == plataforma + _SUFIXO_COMPLETA)
    ).scalar_one_or_none()


def _coleta_completa_devida(db: Session, escola_id: int, plataforma: str,
                            agora: datetime | None = None) -> tuple[bool, str]:
    """A próxima coleta desta escola deve IGNORAR o cursor e trazer tudo?

    POR QUE ISTO EXISTE. O cursor é ``{studentId: totalBooksRead}`` e o
    ``totalBooksRead`` vem do relatório de TURMA do Elefante. Medimos (escola 1,
    03/10/2026) que esse agregado pode ficar PARADO enquanto o endpoint por
    aluno já devolve livro novo: duas crianças tinham, no relatório de turma,
    exatamente os mesmos livros, tempo, tentativas e acertos do último retrato
    gravado — e, no detalhe, livros lidos em 01–09/09 e 21/09 que nunca
    entraram. Nenhum dos quatro campos do relatório mudou, então NENHUM sinal
    derivado dele detectaria a novidade: o aluno fica congelado para sempre.

    A correção não tenta adivinhar um sinal melhor (não existe nesse relatório):
    ela aceita que o incremental é uma OTIMIZAÇÃO e não uma verdade, e garante
    uma recoleta completa a cada ``DIAS_ENTRE_COLETAS_COMPLETAS`` dias. Assim
    toda perda — por agregado defasado, por linha descartada no import, por
    falha que o cursor não soube desfazer — tem teto de tempo em vez de ser
    permanente. O custo é uma sincronização pesada por semana, que é
    exatamente o que acontecia antes do incremental existir.

    Devolve ``(devida, motivo)``; o motivo entra no log da execução.
    """
    agora = agora or _agora()
    if not _carregar_contadores(db, escola_id, plataforma):
        # Sem cursor não há o que ignorar: a coleta já é completa por natureza.
        return False, "sem cursor"
    linha = _linha_coleta_completa(db, escola_id, plataforma)
    bruto = (linha.valor or {}).get("em") if linha is not None else None
    if not bruto:
        return True, "nunca houve recoleta completa registrada"
    try:
        ultima = datetime.fromisoformat(str(bruto))
    except ValueError:
        return True, "marca de recoleta completa ilegível"
    # ``_agora`` deste módulo é UTC NAIVE (ver topo do arquivo). A marca normal
    # nasce dele, então já é naive; uma marca com fuso (editada à mão, ou de
    # outra convenção) é convertida para o mesmo referencial antes de subtrair.
    if ultima.tzinfo is not None:
        ultima = ultima.astimezone(timezone.utc).replace(tzinfo=None)
    dias = (agora - ultima).days
    if dias >= DIAS_ENTRE_COLETAS_COMPLETAS:
        return True, f"última recoleta completa há {dias} dia(s)"
    return False, f"recoleta completa há {dias} dia(s)"


def _marcar_coleta_completa(db: Session, escola_id: int, plataforma: str,
                            agora: datetime | None = None) -> None:
    """Registra que a recoleta completa desta escola/plataforma foi concluída.

    Só é chamada quando a execução gravou dados — uma recoleta que falhou no
    meio NÃO reinicia o relógio, senão a janela de reconciliação pularia."""
    from app.models.configuracao import Configuracao

    linha = _linha_coleta_completa(db, escola_id, plataforma)
    valor = {"em": (agora or _agora()).isoformat()}
    if linha is None:
        db.add(Configuracao(escola_id=escola_id, namespace=_NS_INCREMENTAL,
                            chave=plataforma + _SUFIXO_COMPLETA, valor=valor))
    else:
        linha.valor = valor


def _desfazer_cursor_ignorados(contexto: Contexto, ignorados: set[str]) -> None:
    """Remove de ``contadores_novos`` os alunos cujas linhas ficaram sem vínculo
    nesta sync (nomes normalizados em ``ignorados``): o merge de
    ``_salvar_contadores`` mantém o cursor anterior e a próxima sync retenta."""
    if not ignorados:
        return
    from app.services.importacao import chave_nome

    nomes = getattr(contexto, "nome_por_sid", None) or {}
    novos = getattr(contexto, "contadores_novos", None) or {}
    for sid in [s for s, nome in nomes.items()
                if chave_nome(nome) in ignorados and s in novos]:
        novos.pop(sid, None)


def _recalcular_ao_final(db: Session, escola_id: int, plataforma: str, n_alunos: int) -> None:
    """Ponto ÚNICO de finalização (o mesmo do /confirmar e do /recalcular).

    ``n_alunos`` 0: a coleta não aplicou aluno nenhum e recalcula só pela marca de
    recálculo pendente (órfã que gravou um arquivo, recálculo anterior que falhou).
    O push não diz "0 alunos atualizados" — diz que as notas foram recalculadas com
    o que já estava gravado. A finalização segue igual (cache do painel, pendência)."""
    from app.routers import importacoes as imp

    nome = "Matific" if plataforma == "matific" else "Elefante Letrado"
    if n_alunos:
        corpo = (f"{n_alunos} alunos atualizados na {nome} pela sincronização automática. "
                 "As notas já foram recalculadas.")
    else:
        corpo = (f"Notas recalculadas com os dados já gravados da {nome} "
                 "pela sincronização automática.")
    imp._finalizar_importacao(db, escola_id, corpo=corpo)


def _consulta_recalculo_pendente(escola_id: int):
    return select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == escola_id,
        SincronizacaoAlerta.tipo == "recalculo_pendente",
        SincronizacaoAlerta.resolvido.is_(False))


def recalculo_pendente_aberto(db: Session, escola_id: int,
                              plataforma: str | None = None) -> bool:
    """Há dado gravado esperando um recálculo de notas que falhou? O alerta aberto
    OU a marca de uma execução: fechar o alerta à mão não recalcula nada, e a
    marca (a mesma que o histórico mostra e que o pré-requisito
    ``recalculo_sem_pendencia`` do agendador lê) só cai com um recálculo que dá
    certo (``resolver_recalculo_pendente``)."""
    consulta = _consulta_recalculo_pendente(escola_id)
    if plataforma is not None:
        consulta = consulta.where(SincronizacaoAlerta.plataforma == plataforma)
    if db.execute(consulta.limit(1)).scalars().first() is not None:
        return True
    marca = select(SincronizacaoExecucao.id).where(
        SincronizacaoExecucao.escola_id == escola_id,
        SincronizacaoExecucao.recalculo_pendente.is_(True))
    if plataforma is not None:
        marca = marca.where(SincronizacaoExecucao.plataforma == plataforma)
    return db.execute(marca.limit(1)).first() is not None


def recalculo_pendente_lido(alertas_abertos, plataforma: str, *, marcado: bool) -> bool:
    """A regra de ``recalculo_pendente_aberto`` (de UMA plataforma) sobre o que o
    chamador já leu: os alertas ABERTOS da escola e a marca das execuções da
    plataforma (``MarcosDaIntegracao.recalculo_marcado``)."""
    return marcado or any(al.tipo == "recalculo_pendente" and al.plataforma == plataforma
                          and not al.resolvido for al in alertas_abertos)


def resolver_recalculo_pendente(db: Session, escola_id: int) -> int:
    """Um recálculo que deu certo fecha a pendência de TODAS as plataformas da
    escola (o recálculo é da escola inteira). Chamado pelo ponto único de
    finalização (``importacoes._finalizar_importacao``): vale para a sync, o
    /confirmar e o /recalcular manual.

    Devolve quantas pendências desfez (alertas fechados + execuções desmarcadas):
    o chamador commita quando é > 0. Contar só os alertas perdia o zeramento da
    marca quando o alerta já tinha sido fechado à mão — nada commitava a mudança
    e ela sumia com a sessão da requisição."""
    n = 0
    for al in db.execute(_consulta_recalculo_pendente(escola_id)).scalars():
        al.resolvido = True
        al.resolvido_em = _agora()
        n += 1
    # A marca nas execuções também deixa de valer: "pendente" é o que ainda falta
    # recalcular, não o histórico (que fica no log e no alerta resolvido). Sem
    # isso o histórico da tela seguia "recálculo pendente" e o pré-requisito
    # ``recalculo_sem_pendencia`` do agendador só soltava com uma nova coleta que
    # APLICASSE dado — nunca depois de um /recalcular ou de um "nada mudou".
    marcadas = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.escola_id == escola_id,
               SincronizacaoExecucao.recalculo_pendente.is_(True))
        .values(recalculo_pendente=False)
        .execution_options(synchronize_session="fetch")).rowcount or 0
    if n or marcadas:
        db.flush()
    return n + marcadas


# --------------------------------------------------------------------------
# Contabilidade da execução e decisão do status (contrato da Etapa 2)
# --------------------------------------------------------------------------
_MOTIVOS_DE_VINCULO = ("sem_vinculo",)   # pendência de correspondência, não defeito
# Descarte que a ESCOLA já decidiu (conta aposentada): nem pendência nem defeito.
# A linha não confere a escola, não desfaz cursor e não abre alerta — só fica
# contada no motivo próprio e citada no log da execução.
_MOTIVOS_DECIDIDOS = tuple(sorted(MOTIVOS_DESCARTE_DECIDIDO))
_MOTIVOS_FORA_DE_DEFEITO = _MOTIVOS_DE_VINCULO + _MOTIVOS_DECIDIDOS
# O motivo de cada linha com defeito (o código que conectores, parser e importação
# anotam) como a tela o diz nos alertas "Nenhuma linha aproveitável" e "Coleta parcial".
_ROTULO_DESCARTE = {
    "sem_nome": "sem o nome do aluno",
    "sem_nome_ou_turma": "sem o nome ou a turma do aluno",
    "sem_nome_ou_titulo": "sem o nome do aluno ou o título do livro",
    "sem_data": "leitura sem data",
    "livro_sem_titulo": "livro sem título",
    "id_em_varias_turmas": "a mesma conta em mais de uma turma, com números diferentes",
    "campos_ausentes": "sem campos que o Constela usa",
}


def _rotulo_descarte(motivo: str) -> str:
    """Rótulo do motivo; um código novo sem rótulo sai sem o "_" de código."""
    return _ROTULO_DESCARTE.get(motivo) or str(motivo).replace("_", " ")


# A UNIDADE da coleta que falhou (o código que conectores e serviço anotam em
# ``registrar_falha_coleta``) como a tela a diz nos alertas "Coleta parcial" e
# "Nenhum dado aplicado" — nunca o código interno ("endpoint", "lote").
_ROTULO_UNIDADE = {
    "turma": "turma",
    "lote": "livros lidos de uma turma",
    "aluno": "livros lidos de um aluno",
    "endpoint": "lista de nomes completos do Matific",
    "arquivo": "relatório de turma",
}


def _rotulo_unidade(unidade: str) -> str:
    """Rótulo da unidade; um código novo sem rótulo sai sem o "_" de código."""
    return _ROTULO_UNIDADE.get(unidade) or str(unidade).replace("_", " ")


# Linhas de LIVRO (leituras do Elefante) descartadas. O cursor do aluno avança mesmo
# assim (decisão: um livro com defeito permanente não faz toda coleta pedir os livros
# de novo — ``test_sync_revisao_regressao``), então outra coleta logo em seguida NÃO
# as pede: só a recoleta completa semanal (``_coleta_completa_devida``) o faz.
_MOTIVOS_DE_LIVRO = ("sem_data", "sem_nome_ou_titulo", "livro_sem_titulo")


@dataclass
class _Apuracao:
    """O que a execução de fato recebeu, aplicou e perdeu — sem PII."""
    arquivos: int = 0
    com_linhas: int = 0
    aplicados: set = field(default_factory=set)      # aluno_id com dado novo/alterado
    turmas: set = field(default_factory=set)
    turmas_sem_rotulo: int = 0                       # resultado no formato anterior
    linhas: int = 0
    em_revisao: int = 0
    ignorados: set = field(default_factory=set)      # chave de nome sem vínculo
    descartes: dict = field(default_factory=dict)    # motivo → linhas
    falhas: list = field(default_factory=list)       # [{unidade, id, codigo, http}]
    avisos_criticos: list = field(default_factory=list)
    retidos_queda: int = 0
    verificou_queda: bool = False
    importacoes: list = field(default_factory=list)
    # Contas que vieram: o Placar do ano (Matific) ou os relatórios de TODAS as
    # turmas (Elefante). None = o conector não garante a lista inteira.
    ids_recebidos: list | None = None
    # Alunos COM FICHA que a importação resolveu e cujo dado veio IGUAL ao gravado
    # (``qtd_alunos − alunos_aplicados_ids`` do arquivo: a mesma conta que a
    # importação manual mostra como "N conferido(s) sem mudança"). Somado por
    # arquivo: o mesmo aluno no resumo e nas leituras do Elefante conta duas vezes
    # — só o "houve ao menos um" decide (``conferiu_a_escola``).
    conferidos_sem_mudanca: int = 0
    # Contas (id externo) desta coleta que já são EFETIVAS em OUTRA escola do
    # Constela: foram para a revisão 'identidade_de_outra_escola' (nada aplicado).
    ids_outra_escola: set = field(default_factory=set)
    # A linha do fim no log (``_escrever_fim``): ``fim_gravado`` = (status, motivo)
    # depois do commit que gravou o estado final; ``fim_logado`` depois da linha.
    # Fora do banco, como o resto: é o que ``executar`` consulta ao sair por exceção.
    fim_gravado: tuple | None = None
    fim_logado: bool = False
    # Outro caminho encerrou a execução primeiro (``_perdeu_o_fechamento``).
    perdeu_o_fechamento: bool = False

    def incorporar_coleta(self, coleta: dict | None) -> None:
        """O que o CONECTOR anotou (unidades que não chegaram, linhas com defeito)."""
        coleta = coleta or {}
        self.falhas.extend(dict(f) for f in coleta.get("falhas") or [])
        if coleta.get("ids_recebidos") is not None:
            self.ids_recebidos = list(coleta["ids_recebidos"])
        for motivo, n in (coleta.get("descartes") or {}).items():
            self.descartes[motivo] = self.descartes.get(motivo, 0) + int(n or 0)
            self.linhas += int(n or 0)

    def somar(self, res: dict) -> None:
        """Soma o resultado de UM arquivo (``orchestrator.aplicar_arquivo``)."""
        self.arquivos += 1
        sem_dados = bool(res.get("sem_dados"))
        self.retidos_queda += int(res.get("retidos_queda") or 0)
        self.verificou_queda = self.verificou_queda or bool(res.get("verificou_queda"))
        ids = res.get("alunos_aplicados_ids")
        if ids is not None and not sem_dados:
            conferidos = res.get("conferidos_sem_mudanca")
            if conferidos is None:   # resultado sem a chave: a mesma conta, aqui
                conferidos = int(res.get("qtd_alunos") or 0) - len(ids)
            self.conferidos_sem_mudanca += max(0, int(conferidos or 0))
        if ids is None and not sem_dados:
            # Resultado no formato ANTERIOR (só a contagem): cada aluno conta.
            ids = [f"arquivo{self.arquivos}:{i}" for i in range(int(res.get("qtd_alunos") or 0))]
        self.aplicados.update(ids or [])
        if "linhas" in res:
            self.linhas += int(res.get("linhas") or 0)
        elif not sem_dados:
            self.linhas += max(1, int(res.get("qtd_alunos") or 0))
        if not sem_dados:
            self.com_linhas += 1
            if "turmas" in res:
                self.turmas.update(res.get("turmas") or [])
            else:
                self.turmas_sem_rotulo += int(res.get("qtd_turmas") or 0)
        self.em_revisao += int(res.get("em_revisao") or 0)
        self.ignorados.update(res.get("ignorados") or [])
        self.ids_outra_escola.update(str(i) for i in res.get("ids_de_outra_escola") or [])
        for motivo, n in (res.get("descartadas") or {}).items():
            self.descartes[motivo] = self.descartes.get(motivo, 0) + int(n or 0)
        self.avisos_criticos.extend(res.get("avisos_criticos") or [])
        if res.get("parser_incompativel"):
            # O arquivo inteiro perdeu um campo essencial: nada dele foi aplicado.
            self.falhas.append({"unidade": "arquivo", "id": str(self.arquivos),
                                "codigo": "parser_incompativel", "http": None})
        if res.get("importacao_id"):
            self.importacoes.append(int(res["importacao_id"]))

    @property
    def campos_nao_atualizados(self) -> list[str]:
        """Campos não essenciais que sumiram de todas as linhas de algum relatório
        (``orchestrator.campos_nao_atualizados``)."""
        prefixo = orchestrator.AVISO_NAO_ATUALIZADOS
        return sorted({c for a in self.avisos_criticos if str(a).startswith(prefixo)
                       for c in str(a)[len(prefixo):].split(",") if c})

    @property
    def interpretacao_incompativel(self) -> bool:
        """A resposta perdeu campo essencial (num arquivo inteiro ou em parte das
        linhas) ou um não essencial em todas as linhas — merece o alerta crítico
        'parser_incompativel'."""
        return (any(f.get("codigo") == "parser_incompativel" for f in self.falhas)
                or any(str(a).startswith("campos_ausentes") for a in self.avisos_criticos)
                or bool(self.campos_nao_atualizados))

    @property
    def conferiu_a_escola(self) -> bool:
        """A coleta CONFERIU ao menos uma conta já vinculada a um aluno da escola:
        aplicou dado novo, comparou e achou igual ('conferido sem mudança') ou
        reteve um total menor do Matific (a retenção só acontece para uuid já
        vinculado NESTA escola, comparado com o retrato gravado). Sem nada disso,
        uma coleta só de pendências não prova que o dado da escola está em dia
        (forma C da decisão 1)."""
        return bool(self.aplicados) or self.conferidos_sem_mudanca > 0 or self.retidos_queda > 0

    @property
    def defeitos(self) -> int:
        return sum(n for m, n in self.descartes.items() if m not in _MOTIVOS_FORA_DE_DEFEITO)

    @property
    def decididos(self) -> int:
        """Linhas descartadas por decisão da escola (conta aposentada)."""
        return sum(int(self.descartes.get(m, 0) or 0) for m in _MOTIVOS_DECIDIDOS)

    @property
    def qtd_turmas(self) -> int:
        return len(self.turmas) + self.turmas_sem_rotulo

    @property
    def qtd_erros(self) -> int:
        """Falhas DISTINTAS: unidades que falharam + contas/linhas distintas que
        ficaram sem aluno (revisão ou sem vínculo) + linhas descartadas por
        defeito. Antes somava as linhas não casadas de cada arquivo (o mesmo
        aluno contava no resumo e nas leituras)."""
        return len(self.falhas) + len(self.ignorados) + self.defeitos

    def resumo_falhas(self) -> str:
        """As unidades que falharam, contadas, na língua de quem lê os alertas da tela
        de Integrações ("livros lidos de uma turma: 1"), nunca o código ("lote: 1")."""
        por_unidade: dict[str, int] = {}
        for f in self.falhas:
            rotulo = _rotulo_unidade(f.get("unidade") or "parte da coleta")
            por_unidade[rotulo] = por_unidade.get(rotulo, 0) + 1
        return ", ".join(f"{u}: {n}" for u, n in sorted(por_unidade.items()))

    def resumo_descartes(self) -> str:
        """As linhas com defeito por motivo, na língua de quem lê os alertas da tela de
        Integrações ("sem o nome do aluno: 2"), nunca o código interno ("sem_nome")."""
        return ", ".join(f"{_rotulo_descarte(m)}: {n}" for m, n in sorted(self.descartes.items())
                         if m not in _MOTIVOS_FORA_DE_DEFEITO and n)


def decidir_status(ap: _Apuracao, *, falha_no_meio: bool = False) -> tuple[str, str | None]:
    """(status, motivo) pela contabilidade — a regra ÚNICA dos estados finais."""
    aplicados = len(ap.aplicados)
    if falha_no_meio:
        return ("parcial", "falha_apos_gravacao") if aplicados else ("erro", None)
    if aplicados:
        if ap.falhas:
            return "parcial", "coleta_parcial"
        # Campo sumido (S9) vem ANTES da linha com defeito: 'parcial/linhas_descartadas'
        # conta como "em dia" (``_filtro_em_dia``) e esconderia que tempo e questões
        # pararam de chegar. Os descartes continuam na mensagem do 'coleta_parcial'.
        if ap.campos_nao_atualizados:
            return "parcial", MOTIVO_CAMPOS_NAO_ATUALIZADOS
        if ap.defeitos:
            return "parcial", "linhas_descartadas"
        return "concluida", None
    if ap.falhas and ap.conferiu_a_escola and all(
            f.get("unidade") == "endpoint" for f in ap.falhas):
        # Decisão D2(6): falhou SÓ o endpoint acessório dos nomes do Matific
        # (``student-leaderboard``, a única unidade 'endpoint') e a coleta conferiu
        # contas já vinculadas: é 'parcial', não 'erro' — também quando nenhum
        # número mudou (antes só a coleta com dado novo saía 'parcial'; a sem
        # mudança virava 'erro/sem_acesso_ao_dado' crítico, sem o carimbo da
        # credencial nem a avaliação da queda retida). Na 1ª coleta, sem nenhuma
        # conta conferida, continua 'erro'.
        return "parcial", "coleta_parcial"
    if ap.falhas:
        # Nenhum dado aplicado e parte (ou tudo) falhou. O motivo é o CÓDIGO da
        # falha (``codigo_dominante`` — 'sem_acesso_ao_dado', 'falha_download',
        # 'parser_incompativel'), que a tela traduz; antes era 'coleta_incompleta'
        # e o histórico dizia só "falhou" para uma turma recusada.
        from app.sync.connectors.base import codigo_dominante
        return "erro", codigo_dominante(ap.falhas)
    if ap.linhas == 0:
        return "sem_dados", None
    # A linha que a escola já decidiu descartar (conta aposentada) não é defeito
    # nem pendência: fica fora da conta do "tudo com defeito".
    uteis = ap.linhas - ap.decididos
    if uteis > 0 and ap.defeitos >= uteis:
        return "erro", "linhas_descartadas"       # tudo o que veio tinha defeito
    if (ap.em_revisao or ap.ignorados) and not ap.conferiu_a_escola:
        # Forma C: pendência sem nenhuma conta da escola conferida é
        # 'tudo_em_revisao' — não é em dia (credencial de outra escola, casamento
        # quebrado ou 1ª coleta sem vínculo) e tem o texto próprio do alerta.
        return "sem_atualizacao", MOTIVO_TUDO_EM_REVISAO
    if ap.campos_nao_atualizados:
        # S9 antes da pendência comum e da linha com defeito: as duas contam como
        # "em dia" (``_filtro_em_dia``) e esconderiam que tempo e questões pararam
        # de chegar. Os alertas delas abrem do mesmo jeito (``_concluir`` os decide
        # pela contabilidade, não pelo motivo).
        return "sem_atualizacao", MOTIVO_CAMPOS_NAO_ATUALIZADOS
    if ap.em_revisao or ap.ignorados:
        # Forma C: pendência com ≥1 conta da escola conferida é "correspondência
        # pendente" (em dia, com o alerta próprio).
        return "sem_atualizacao", "correspondencia_pendente"
    if ap.retidos_queda:
        # Total do Matific MENOR que o gravado: o valor ficou retido (alerta
        # 'queda_matific'), mas NÃO há revisão de identidade a fazer — antes saía
        # "correspondência pendente" mandando a escola a uma fila vazia.
        return "sem_atualizacao", "queda_retida"
    if ap.defeitos:
        return "sem_atualizacao", "linhas_descartadas"
    if ap.decididos and not ap.conferiu_a_escola:
        # Só vieram contas que a escola já APOSENTOU: nada a revisar, mas nenhuma
        # conta da escola foi conferida — pela forma C isso não prova que o dado
        # está em dia (nem conta como verificação). Sem alerta de pendência: ela
        # não existe; o log da execução cita as contas aposentadas.
        return "sem_atualizacao", MOTIVO_TUDO_EM_REVISAO
    return "sem_atualizacao", MOTIVO_NADA_MUDOU


def _coletar(conector, cred, contexto_fetch: Contexto) -> list:
    """Roda o conector com TETO DE TEMPO TOTAL (``SYNC_TETO_EXECUCAO_S``): o
    ``SYNC_TIMEOUT_S`` vale por passo do navegador, e uma sessão que não trava em
    nenhum passo isolado podia segurar a execução (e o semáforo das manuais)
    indefinidamente. Estourou → ``ErroConector('timeout')`` recuperável."""
    teto = int(settings.SYNC_TETO_EXECUCAO_S or 0)
    inicio = time.monotonic()
    try:
        return asyncio.run(asyncio.wait_for(conector.sincronizar(cred, contexto_fetch),
                                            timeout=teto if teto > 0 else None))
    except (asyncio.TimeoutError, TimeoutError) as exc:
        decorrido = int(time.monotonic() - inicio)
        if teto > 0 and decorrido >= teto:
            mensagem = (f"A coleta passou do teto de {teto}s e foi interrompida. Tente "
                        "de novo; se repetir, a plataforma pode estar lenta.")
        else:
            mensagem = "Tempo esgotado esperando a plataforma responder."
        raise ErroConector(mensagem, codigo="timeout", recuperavel=True) from exc
    except asyncio.CancelledError as exc:
        # É BaseException: passava por todos os ``except Exception`` e a execução
        # ficava 'executando', sem log nem fim. Uma tarefa interna cancelada (ex.:
        # o navegador fechando no meio) é falha da coleta, e tem nova tentativa.
        raise ErroConector("A coleta foi cancelada no meio do caminho. Tente de novo.",
                           codigo="erro_navegador", recuperavel=True) from exc


_ONDE_AS_CONTAS_VEM = {
    "matific": ("Matific", "no Placar desta coleta"),
    "elefante": ("Elefante Letrado", "nos relatórios de turma desta coleta completa"),
}


def _avisar_contas_ausentes(db: Session, execucao: SincronizacaoExecucao,
                            ap: _Apuracao, *, coleta_completa: bool = False) -> None:
    """Conta JÁ vinculada a aluno ativo que não veio na coleta não é atualizada —
    e antes passava calada. Só o aviso (contagem, sem nome): o valor gravado
    fica, o status do aluno e o da execução não mudam, e a coleta seguinte
    confere de novo.

    Matific: o acumulado do ano (o Placar), em toda coleta regular. Elefante: só
    na coleta COMPLETA (cursor ignorado ou inexistente — a reconciliação semanal)
    e com TODAS as turmas respondendo (o conector só anota ``ids_recebidos``
    assim); entre duas completas o alerta fica como está. Antes o Elefante não
    tinha aviso nenhum: a criança que sumia do relatório ficava com o dado
    parado e a tela dizia "Atualizado"."""
    plataforma = execucao.plataforma
    if plataforma not in _ONDE_AS_CONTAS_VEM or ap.ids_recebidos is None:
        return
    if plataforma == "elefante" and not coleta_completa:
        return
    from app.models import Aluno, IdentidadeExterna

    consulta = (select(func.count(func.distinct(IdentidadeExterna.id_externo)))
                .join(Aluno, Aluno.id == IdentidadeExterna.aluno_id)
                .where(IdentidadeExterna.escola_id == execucao.escola_id,
                       IdentidadeExterna.plataforma == plataforma,
                       IdentidadeExterna.status != "aposentada",
                       Aluno.status == "ativo"))
    if ap.ids_recebidos:
        consulta = consulta.where(IdentidadeExterna.id_externo.notin_(ap.ids_recebidos))
    ausentes = int(db.scalar(consulta) or 0)
    if ausentes:
        nome, onde = _ONDE_AS_CONTAS_VEM[plataforma]
        mensagem = (f"{ausentes} conta(s) do {nome} vinculada(s) a aluno(s) ativo(s) "
                    f"não vieram {onde} (ausentes): o dado delas não foi atualizado. "
                    f"Confira as turmas visíveis na conta do {nome}.")
        registrar_log(db, execucao, "validacao", "warn", mensagem)
        # Aviso com a contagem (antes só o log, e a tela dizia "Atualizado"). O
        # status não muda: não está confirmado se o Placar lista quem não teve
        # nenhuma atividade no ano — tornar isso 'parcial' depende dessa resposta.
        abrir_alerta(db, execucao.escola_id, plataforma, "contas_ausentes", mensagem,
                     severidade="warn", execucao_id=execucao.id)
    else:
        resolver_alertas(db, execucao.escola_id, plataforma, ("contas_ausentes",))


def _ultima_com_dado(db: Session, execucao: SincronizacaoExecucao):
    """A última coleta do ACUMULADO que aplicou dado (a referência do alerta
    'plataforma_sem_dados'): uma coleta por período não serve de comparação.

    A 'parcial' sem nenhum aluno aplicado (D2(6): falhou só o endpoint dos nomes
    do Matific e nada mudou) também não serve: não trouxe dado, e como referência
    (``qtd_alunos`` 0) calava o alerta do Placar que esvazia depois dela. A
    'concluida' continua valendo sem condição (comportamento anterior). É o
    mesmo ``_filtro_aplicou_dado`` do último sucesso."""
    return db.execute(
        select(SincronizacaoExecucao).where(
            SincronizacaoExecucao.escola_id == execucao.escola_id,
            SincronizacaoExecucao.plataforma == execucao.plataforma,
            SincronizacaoExecucao.id != execucao.id,
            _filtro_aplicou_dado(),
            _filtro_do_acumulado())
        .order_by(SincronizacaoExecucao.id.desc()).limit(1)).scalars().first()


def _virou_o_ano(anterior: SincronizacaoExecucao, plataforma: str) -> bool:
    """O acumulado do Matific ('this-year') RECOMEÇA no ano civil novo (horário de
    Brasília): em janeiro, um Placar vazio depois do dezembro cheio é o normal."""
    if plataforma != "matific" or anterior.finalizada_em is None:
        return False
    return fuso.para_local(_naive_utc(anterior.finalizada_em)).year < fuso.hoje_local().year


def _gravar_contabilidade(execucao: SincronizacaoExecucao, ap: _Apuracao) -> None:
    execucao.qtd_arquivos = ap.arquivos
    execucao.qtd_alunos = len(ap.aplicados)
    execucao.qtd_alteracoes = len(ap.aplicados)
    execucao.qtd_turmas = ap.qtd_turmas
    execucao.qtd_erros = ap.qtd_erros
    execucao.qtd_linhas = ap.linhas
    execucao.qtd_em_revisao = ap.em_revisao
    execucao.qtd_falhas = len(ap.falhas)


def _registrar_trilha(db: Session, execucao: SincronizacaoExecucao, ap: _Apuracao) -> None:
    """A execução aponta para a importação que gerou (o campo existia e nunca era
    preenchido — 0 de 409 em produção). Uma execução gera uma importação por
    relatório (turma); fica a ÚLTIMA, e o log lista todas."""
    if ap.importacoes and db.get(Importacao, ap.importacoes[-1]) is not None:
        execucao.importacao_id = ap.importacoes[-1]
        if len(ap.importacoes) > 1:
            registrar_log(db, execucao, "importacao", "info",
                          f"{len(ap.importacoes)} importações geradas (ids "
                          + ", ".join(str(i) for i in ap.importacoes[:50])
                          + ("…" if len(ap.importacoes) > 50 else "") + ").")


def _contas_vinculadas(db: Session, escola_id: int, plataforma: str, *,
                       ativos: bool = True) -> int:
    """Quantas contas desta plataforma estão vinculadas a aluno ATIVO da escola
    (identidade externa não aposentada); com ``ativos=False``, a aluno que NÃO
    está ativo (transferido, fora da Lista Piloto, arquivado). Só contagem, sem
    nome."""
    from app.models import Aluno, IdentidadeExterna

    situacao = (Aluno.status == "ativo") if ativos else (Aluno.status != "ativo")
    return int(db.scalar(
        select(func.count(func.distinct(IdentidadeExterna.id_externo)))
        .join(Aluno, Aluno.id == IdentidadeExterna.aluno_id)
        .where(IdentidadeExterna.escola_id == escola_id,
               IdentidadeExterna.plataforma == plataforma,
               IdentidadeExterna.status != "aposentada",
               situacao)) or 0)


def _mensagem_tudo_em_revisao(db: Session, escola_id: int, plataforma: str,
                              pendentes: str) -> str:
    """Texto do 'correspondencia_pendente' quando NENHUMA conta da escola foi
    conferida (motivo 'tudo_em_revisao'). Distingue a escola que já tem contas
    vinculadas (o sinal de credencial de outra escola ou casamento quebrado), a
    que só tem contas de alunos que não estão ativos (transferidos etc.) e a que
    ainda não tem nenhuma (1ª coleta)."""
    vinculadas = _contas_vinculadas(db, escola_id, plataforma)
    inativas = 0 if vinculadas else _contas_vinculadas(db, escola_id, plataforma,
                                                       ativos=False)
    if vinculadas:
        causa = (f"A escola tem {vinculadas} conta(s) vinculada(s) nesta plataforma e "
                 "nenhuma foi reconhecida: confira se o acesso cadastrado é o desta "
                 "escola (uma conta de outra escola produz exatamente isto) antes de "
                 "resolver as revisões.")
    elif inativas:
        # Antes (revisão e95) caía no texto da 1ª coleta ("ainda não tem nenhuma
        # conta vinculada") com as contas vinculadas a fichas transferidas.
        causa = (f"As {inativas} conta(s) vinculada(s) desta escola nesta plataforma são "
                 "de alunos que não estão ativos (transferidos, fora da Lista Piloto ou "
                 "arquivados): confira as matrículas e se o acesso cadastrado é o desta "
                 "escola antes de resolver as revisões.")
    else:
        causa = ("A escola ainda não tem nenhuma conta vinculada nesta plataforma: na "
                 "primeira coleta, confirme que os nomes são desta escola e resolva as "
                 "pendências em Revisão de identidade.")
    return (f"Nenhum dado novo aplicado e nenhuma conta da escola conferida: {pendentes}. "
            "Isto não conta como coleta em dia. " + causa)


def _mensagem_parcial(ap: _Apuracao, motivo: str | None) -> str:
    partes = [f"Coleta parcial: {len(ap.aplicados)} aluno(s) com dado novo aplicado"]
    if motivo == "falha_apos_gravacao":
        partes.append("a sincronização falhou depois de já ter gravado parte dos dados")
    if ap.falhas:
        partes.append(f"{len(ap.falhas)} unidade(s) com falha ({ap.resumo_falhas()})")
    if ap.defeitos:
        partes.append(f"{ap.defeitos} linha(s) descartada(s) ({ap.resumo_descartes()})")
    if ap.campos_nao_atualizados:
        partes.append(f"{_rotulos_campos(ap.campos_nao_atualizados)} não vieram da "
                      "plataforma e ficaram com o valor da coleta anterior")
    texto = "; ".join(partes) + "."
    # Sincronizar de novo completa o que FALHOU (unidade, falha depois de gravar) ou
    # a linha com defeito de passagem do relatório de turma (pedido de novo a cada
    # coleta). NÃO completa: um campo renomeado na API (mandar repetir ensinava a
    # ignorar o par de alertas), a unidade que veio em outro formato (o crítico ao
    # lado diz que a coleta precisa de ajuste) e a leitura descartada — o cursor do
    # aluno já avançou e a próxima coleta não pede os livros dele.
    falha_que_repetir_completa = any(f.get("codigo") != "parser_incompativel"
                                     for f in ap.falhas)
    so_formato = bool(ap.falhas) and not falha_que_repetir_completa
    defeito_de_livro = any(ap.descartes.get(m) for m in _MOTIVOS_DE_LIVRO)
    defeito_que_repetir_completa = any(
        n for m, n in ap.descartes.items()
        if n and m not in _MOTIVOS_FORA_DE_DEFEITO and m not in _MOTIVOS_DE_LIVRO)
    if (falha_que_repetir_completa or defeito_que_repetir_completa
            or motivo == "falha_apos_gravacao"):
        texto += " Sincronize de novo para completar."
    if defeito_de_livro:
        texto += (" As leituras descartadas não voltam com outra coleta: só são pedidas "
                  "de novo na recoleta completa semanal.")
    if so_formato:
        texto += (" O que veio em outro formato não volta com outra coleta: "
                  f"{orchestrator.AJUSTE_DA_COLETA} (alerta “Formato do relatório mudou”).")
    if ap.campos_nao_atualizados:
        texto += (" Os números que não vieram não voltam com outra coleta: "
                  f"{orchestrator.AJUSTE_DA_COLETA} (alerta “Formato do relatório mudou”).")
    return texto


_ROTULO_CAMPO = {"tempo_leitura_min": "tempo de leitura",
                 "questoes_tentativas": "questões respondidas",
                 "questoes_acertos": "questões aprovadas"}


def _rotulos_campos(campos) -> str:
    return ", ".join(_ROTULO_CAMPO.get(c, c) for c in campos)


def _recalcular_se_preciso(db: Session, execucao: SincronizacaoExecucao, ap: _Apuracao,
                           contexto: Contexto, escola_id: int, plataforma: str) -> None:
    """Recalcula as notas quando a execução gravou dado novo — inclusive na
    falha DEPOIS de gravar (antes, o ranking ficava atrás dos retratos) — ou
    quando um recálculo anterior ficou pendente. Falhou: ``recalculo_pendente``
    na execução e alerta CRÍTICO (o dado está gravado, as notas não)."""
    if not ap.aplicados and not recalculo_pendente_aberto(db, escola_id):
        return
    # A execução fica consistente (e finalizada) mesmo se o recálculo derrubar a
    # sessão ou o processo; o fim de ``executar`` acerta o instante e a duração.
    # A MARCA de recálculo pendente vai junto neste commit: se o processo morrer
    # durante o recálculo (deploy, falta de memória — nada que o ``except`` pegue),
    # a execução fica 'concluida' com o dado gravado e as notas antigas, e só a
    # marca avisa (o /status, o pré-requisito do agendador e a próxima coleta, que
    # recalcula por ela). O recálculo que dá certo a zera
    # (``resolver_recalculo_pendente``, no ponto único de finalização).
    execucao.finalizada_em = _agora()
    execucao.recalculo_pendente = True
    fim = (execucao.status, execucao.motivo)     # lido antes do commit (depois expira)
    db.commit()
    # O estado final JÁ está no banco: se ``executar`` sair por exceção daqui até a
    # linha do fim, ela sai assim mesmo (``executar_interrompida``).
    ap.fim_gravado = fim
    try:
        _recalcular_ao_final(db, escola_id, plataforma, len(ap.aplicados))
        contexto.log("ranking", "info",
                     f"Notas recalculadas ao final ({len(ap.aplicados)} aluno(s)).")
    except Exception as exc:  # noqa: BLE001 — o dado já está gravado; a falha fica visível
        db.rollback()
        logger.exception("Recálculo falhou ao fim da sync (escola %s, plataforma %s)",
                         escola_id, plataforma)
        execucao.recalculo_pendente = True
        mensagem = (f"Os dados da sincronização foram gravados, mas o recálculo das notas "
                    f"falhou ({type(exc).__name__}). Rankings e notas podem estar atrás "
                    "dos dados: use “Recalcular” em Importações ou sincronize de novo.")
        registrar_log(db, execucao, "ranking", "error", mensagem)
        abrir_alerta(db, escola_id, plataforma, "recalculo_pendente", mensagem,
                     severidade="critico", execucao_id=execucao.id)


def _concluir(db: Session, execucao: SincronizacaoExecucao, ap: _Apuracao,
              contexto: Contexto, contexto_fetch: Contexto, completa: bool, *,
              escola_id: int, plataforma: str,
              falha: tuple[str, str, bool] | None = None) -> None:
    """Fecha a execução pela contabilidade: status, contadores, cursor,
    credencial, alertas e recálculo. ``falha`` = (código, mensagem, recuperável)
    de uma exceção no MEIO da aplicação (depois de a coleta ter dado certo)."""
    status, motivo = decidir_status(ap, falha_no_meio=falha is not None)
    if motivo == MOTIVO_TUDO_EM_REVISAO and execucao_por_periodo(execucao):
        # Coleta POR PERÍODO nunca conta como "em dia" (``_filtro_do_acumulado``) e
        # pode trazer só quem teve atividade no período (suposição a confirmar com o
        # Matific: o Placar por período omite quem não jogou?). Sem conta da escola
        # nela não há sinal de acesso de outra escola: é a pendência comum. Antes
        # (revisão e95) o alerta e o card mandavam conferir a credencial. Sem
        # pendência (só contas aposentadas no período), nada mudou.
        motivo = ("correspondencia_pendente" if (ap.em_revisao or ap.ignorados)
                  else MOTIVO_NADA_MUDOU)
    if not _fechar_se_ainda_executando(db, execucao, status):
        _perdeu_o_fechamento(db, execucao, ap)
        return
    _gravar_contabilidade(execucao, ap)
    _registrar_trilha(db, execucao, ap)
    execucao.motivo = motivo
    # A coleta voltou (só se chega aqui depois de ``_coletar``): o alerta do navegador
    # que não abria perdeu a causa também na 'parcial', na 'sem_dados' e no 'erro' por
    # unidades — antes só a coleta completa sem falha o fechava.
    if falha is None or falha[0] != "navegador_indisponivel":
        _fechar_alerta_do_navegador(db, escola_id, plataforma, execucao)

    if status == "erro":
        if falha is not None:
            codigo, mensagem, recuperavel = falha
        elif ap.falhas:
            from app.sync.connectors.base import codigo_dominante
            codigo = codigo_dominante(ap.falhas)
            mensagem = (f"Nenhum dado aplicado: {len(ap.falhas)} unidade(s) da coleta "
                        f"falharam ({ap.resumo_falhas()}).")
            recuperavel = codigo == "falha_download"
        else:
            codigo = "parser_incompativel"
            mensagem = (f"Nenhuma linha aproveitável: {ap.defeitos} linha(s) com defeito "
                        f"({ap.resumo_descartes()}). Avise o suporte: "
                        f"{orchestrator.AJUSTE_DA_COLETA}.")
            recuperavel = False
        execucao.motivo = motivo
        _tratar_falha(db, execucao, contexto, codigo, mensagem, recuperavel=recuperavel)
        return

    # CURSOR (incremental): avança só numa coleta que chegou ao fim. Falha no meio
    # não salva nada — a próxima sync busca de novo (as UNIQUE impedem duplicar).
    if falha is None and ap.com_linhas:
        # Linha sem aluno vinculado volta ao cursor anterior → a próxima sync busca
        # os livros de novo em vez de perdê-los para sempre.
        _desfazer_cursor_ignorados(contexto_fetch, ap.ignorados)
        # Recoleta COMPLETA com unidade que falhou (turma, lote, aluno): o cursor
        # fica só com quem chegou nesta rodada (``substituir``).
        _salvar_contadores(db, escola_id, plataforma, contexto_fetch.contadores_novos,
                           substituir=completa and bool(ap.falhas))
        # A recoleta completa que CHEGOU AO FIM reinicia o relógio semanal também
        # quando terminou 'parcial' (um livro sem data, um aluno cujo pedido
        # falha sempre): antes só 'concluida'/'sem_atualizacao' marcavam, e uma
        # linha com defeito permanente fazia TODA coleta seguinte ser completa
        # (~17 min cada) — o cursor nunca mais valia. Quem falhou nesta rodada
        # ficou SEM cursor (acima): a próxima incremental o busca inteiro, em vez
        # de pulá-lo por mais 7 dias quando o agregado da turma não muda.
        if completa and status in ("concluida", "parcial", "sem_atualizacao"):
            _marcar_coleta_completa(db, escola_id, plataforma)
    # CREDENCIAL: o login e o endpoint de dados responderam (só estes estados).
    if status in STATUS_CREDENCIAL_VALIDA:
        vault_linha = vault.obter_linha(db, escola_id, plataforma)
        if vault_linha is not None:
            vault.marcar_status(db, vault_linha, "valida")

    # ALERTAS. Coleta COMPLETA e sem falha de unidade (concluída, qualquer
    # 'sem_atualizacao', ou parcial só por linha com defeito) prova que as falhas
    # anteriores deixaram de valer: fecha TODA falha da integração — menos o que
    # ESTA execução reabre logo abaixo (pendência de revisão desta coleta, linha
    # com defeito, formato incompatível). Antes, a pendência de uma única criança
    # ('sem_atualizacao/correspondencia_pendente') deixava aberto um
    # 'sem_acesso_ao_dado' crítico de dias atrás, e uma 'concluida' com linhas que
    # ficaram em revisão nela mesma fechava o 'correspondencia_pendente'.
    pendencia_nesta = bool(ap.em_revisao or ap.ignorados)
    outra_escola_nesta = len(ap.ids_outra_escola)
    if status in ("concluida", "sem_atualizacao") or (status == "parcial" and not ap.falhas
                                                      and falha is None):
        manter = TIPOS_REGRA_PROPRIA + ("recalculo_pendente",)
        if pendencia_nesta:
            manter += ("correspondencia_pendente",)
        if outra_escola_nesta:
            manter += ("identidade_de_outra_escola",)
        if ap.defeitos:
            manter += ("coleta_parcial",)
        if ap.interpretacao_incompativel:
            manter += ("parser_incompativel",)
        fechados = resolver_falhas_da_integracao(db, escola_id, plataforma, manter=manter)
    else:
        tipos = TIPOS_ACESSO + ("interrompida",)
        if status == "parcial":
            tipos += ("plataforma_sem_dados",)       # a plataforma voltou a mandar linhas
            if not pendencia_nesta:
                tipos += ("correspondencia_pendente",)   # entrou dado novo, sem pendência
        fechados = resolver_alertas(db, escola_id, plataforma, tipos)
    if fechados:
        registrar_log(db, execucao, "scheduler", "info",
                      f"{fechados} alerta(s) desta integração fechado(s) pela execução "
                      f"({status}).")
    if status == "parcial":
        mensagem = _mensagem_parcial(ap, motivo)
        if falha is not None:
            codigo, texto, recuperavel = falha
            execucao.erro_resumo = texto[:300]
            registrar_log(db, execucao, "scheduler", "error", texto)
            tipo, sev = alerta_do_codigo(codigo)
            abrir_alerta(db, escola_id, plataforma, tipo, texto, severidade=sev,
                         execucao_id=execucao.id)
            _agendar_retentativa(db, execucao, recuperavel=recuperavel)
        registrar_log(db, execucao, "importacao", "warn", mensagem)
        abrir_alerta(db, escola_id, plataforma, "coleta_parcial", mensagem,
                     severidade="warn", execucao_id=execucao.id)
    if ap.interpretacao_incompativel:
        perdidas = sorted({a for a in ap.avisos_criticos
                           if not str(a).startswith(orchestrator.AVISO_NAO_ATUALIZADOS)})
        partes = []
        if perdidas or not ap.campos_nao_atualizados:
            partes.append("A resposta da plataforma veio sem campos que o Constela usa "
                          f"({', '.join(perdidas) or 'formato'}): essas linhas não foram "
                          "gravadas.")
        if ap.campos_nao_atualizados:
            # O que a coleta gravou depende do status: na 'parcial' há aluno com livro
            # novo, e os livros entraram; na 'sem_atualizacao' nenhum aluno foi
            # atualizado — dizer "os livros foram atualizados" ali era falso.
            gravou = ("os livros foram atualizados, mas esses números ficaram"
                      if ap.aplicados else
                      "nenhum aluno foi atualizado, e esses números ficaram")
            # As Questões do período só deixam de medir esta coleta quando o que sumiu
            # foram as QUESTÕES (a importação fica ``IMPORTACAO_SEM_QUESTOES``); com só o
            # tempo de leitura sumido, o retrato mede as questões e serve de borda.
            sem_questoes = set(orchestrator.CAMPOS_QUESTOES) & set(ap.campos_nao_atualizados)
            partes.append(
                f"A resposta da plataforma veio sem {_rotulos_campos(ap.campos_nao_atualizados)}"
                f" em todas as linhas: {gravou} com o valor da coleta anterior"
                + (", e as Questões do período não medem os dias desta coleta."
                   if sem_questoes else "."))
        mensagem = (" ".join(partes) + " Sincronizar de novo não resolve: "
                    f"{orchestrator.AJUSTE_DA_COLETA}.")
        registrar_log(db, execucao, "parser", "error", mensagem)
        abrir_alerta(db, escola_id, plataforma, "parser_incompativel", mensagem,
                     severidade="critico", execucao_id=execucao.id)
    if pendencia_nesta:
        # A pendência continua valendo enquanto a coleta a traz — também numa
        # 'concluida'/'parcial' (antes, o dado novo de outros alunos fechava o
        # alerta e a tela dizia "Atualizado" com crianças na fila).
        sem_vinculo = int(ap.descartes.get("sem_vinculo", 0) or 0)
        # Só as partes que existem: antes (revisão e95) saía "0 conta(s) desta
        # coleta ficaram na fila de revisão" quando só havia linhas sem vínculo.
        partes = ([f"{ap.em_revisao} conta(s) desta coleta ficaram na fila de revisão"]
                  if ap.em_revisao else [])
        if sem_vinculo:
            partes.append(f"{sem_vinculo} linha(s) sem vínculo seguro com uma ficha")
        pendentes = " e ".join(partes) or "linha(s) sem vínculo seguro com uma ficha"
        if motivo == MOTIVO_TUDO_EM_REVISAO:
            mensagem = _mensagem_tudo_em_revisao(db, escola_id, plataforma, pendentes)
        else:
            inicio = ("Nenhum dado novo aplicado" if status == "sem_atualizacao"
                      else f"{len(ap.aplicados)} aluno(s) atualizado(s), mas")
            fim = ("Resolva as pendências em Revisão de identidade." if ap.em_revisao
                   else "Nenhuma foi para a fila de revisão: veja os avisos desta "
                        "execução no histórico.")
            mensagem = f"{inicio}: {pendentes}. {fim}"
        registrar_log(db, execucao, "validacao", "warn", mensagem)
        abrir_alerta(db, escola_id, plataforma, "correspondencia_pendente", mensagem,
                     severidade="warn", execucao_id=execucao.id)
    if outra_escola_nesta:
        # Conta da plataforma já EFETIVA em outra escola do Constela: sinal forte
        # de credencial/turma de outra escola. Nada dela foi aplicado aqui e a
        # outra escola não foi tocada; a decisão é humana (Revisão de identidade).
        mensagem = (f"{outra_escola_nesta} conta(s) desta coleta já estão vinculadas a "
                    "aluno(s) de OUTRA escola do Constela: nada delas foi aplicado aqui (a "
                    "outra escola não foi alterada). Confira se a credencial e as turmas "
                    "são desta escola; as linhas ficaram na Revisão de identidade.")
        registrar_log(db, execucao, "validacao", "warn", mensagem)
        abrir_alerta(db, escola_id, plataforma, "identidade_de_outra_escola", mensagem,
                     severidade="critico", execucao_id=execucao.id)
    if status == "sem_atualizacao" and ap.defeitos:
        # Linha com defeito sem nenhuma mudança: antes nenhum alerta — o defeito
        # só aparecia no histórico.
        mensagem = (f"Nenhum dado novo aplicado e {ap.defeitos} linha(s) recebida(s) com "
                    f"defeito foram descartada(s) ({ap.resumo_descartes()}). Se repetir, "
                    "envie o relatório manualmente.")
        registrar_log(db, execucao, "importacao", "warn", mensagem)
        abrir_alerta(db, escola_id, plataforma, "coleta_parcial", mensagem,
                     severidade="warn", execucao_id=execucao.id)
    if status == "sem_dados" and not execucao_por_periodo(execucao):
        # Coleta POR PERÍODO sem ninguém no período é ausência legítima do
        # PERÍODO — não diz nada sobre a conta. Compara-se só com o acumulado.
        anterior = _ultima_com_dado(db, execucao)
        if anterior is not None and (anterior.qtd_alunos or 0) > 0 \
                and not _virou_o_ano(anterior, plataforma):
            mensagem = (f"A plataforma respondeu sem nenhum aluno, mas a última coleta com "
                        f"dado trouxe {anterior.qtd_alunos}. Confira a conta (escola/turmas "
                        "visíveis) na plataforma.")
            registrar_log(db, execucao, "download", "warn", mensagem)
            abrir_alerta(db, escola_id, plataforma, "plataforma_sem_dados", mensagem,
                         severidade="warn", execucao_id=execucao.id)
    if ap.decididos:
        # Conta APOSENTADA (a escola já escolheu qual conta vale): só o registro —
        # nem pendência, nem defeito, nem cursor desfeito (achado 5 da revisão e95).
        registrar_log(db, execucao, "validacao", "info",
                      f"{ap.decididos} linha(s) de conta(s) da plataforma que a escola "
                      "aposentou (conta duplicada já decidida) não foram aplicadas — nada "
                      "a revisar.")
    _avaliar_queda_matific(db, execucao, {"retidos_queda": ap.retidos_queda,
                                          "verificou_queda": ap.verificou_queda})
    # Coleta COMPLETA: cursor ignorado (``completa``) ou inexistente (1ª coleta).
    _avisar_contas_ausentes(db, execucao, ap, coleta_completa=completa or not getattr(
        contexto_fetch, "contadores_anteriores", None))
    registrar_log(db, execucao, "importacao", "info",
                  f"Fim ({status}{', ' + motivo if motivo else ''}): {len(ap.aplicados)} "
                  f"aluno(s) com dado novo, {ap.linhas} linha(s) recebida(s), "
                  f"{ap.em_revisao} em revisão, {len(ap.falhas)} falha(s), "
                  f"{ap.arquivos} arquivo(s) ({ap.com_linhas} com dados).")
    _recalcular_se_preciso(db, execucao, ap, contexto, escola_id, plataforma)


def _encerrar_com_falha(db: Session, execucao: SincronizacaoExecucao, ap: _Apuracao,
                        contexto: Contexto, contexto_fetch: Contexto | None, completa: bool,
                        *, escola_id: int, plataforma: str, coletou: bool,
                        falha: tuple[str, str, bool]) -> None:
    """Fecha uma execução que FALHOU. Se a falha veio depois de a coleta ter
    gravado dado novo (cada arquivo commita o seu), é 'parcial' com recálculo —
    antes era 'erro' e o ranking ficava atrás dos retratos. Senão, 'erro'. Se o
    próprio fechamento pela contabilidade falhar, cai no 'erro' simples: a
    execução nunca fica 'executando'."""
    if coletou and ap.aplicados:
        try:
            _concluir(db, execucao, ap, contexto, contexto_fetch, completa,
                      escola_id=escola_id, plataforma=plataforma, falha=falha)
            return
        except Exception:  # noqa: BLE001 — o registro da falha não pode se perder
            db.rollback()
            logger.exception("Falha ao fechar a execução parcial (escola %s, plataforma %s)",
                             escola_id, plataforma)
    codigo, mensagem, recuperavel = falha
    if not _fechar_se_ainda_executando(db, execucao, "erro"):
        _perdeu_o_fechamento(db, execucao, ap)
        return
    _gravar_contabilidade(execucao, ap)
    navegador_abriu = (getattr(contexto_fetch, "coleta", None) or {}).get("navegador_abriu")
    if codigo != "navegador_indisponivel" and (coletou or navegador_abriu):
        # A página de login respondeu ao navegador DESTA execução
        # (``ConectorNavegador._executar_login``), ou a coleta voltou, e a falha veio
        # depois (401/403 no dado, HTTP 500, escola externa…): o alerta crítico de
        # quando ele não subia não fica aberto ao lado do novo. Depois do rollback
        # acima, para o fechamento não se perder com ele.
        _fechar_alerta_do_navegador(db, escola_id, plataforma, execucao)
    _tratar_falha(db, execucao, contexto, codigo, mensagem, recuperavel=recuperavel)


def _navegador_que_caiu(exc: BaseException | None) -> tuple[str, str, bool] | None:
    """O NOSSO navegador que caiu no meio da execução (``TargetClosedError``, "Page
    crashed", o driver morto) é ``navegador_indisponivel`` — o mesmo critério da
    consulta ao vivo e do diagnóstico (``navegador.erro_conector_de_dentro``). Antes
    virava 'erro_inesperado' (sem ``ErroConector``) ou, pelo ``except`` do conector
    que embrulha a chamada ao site, 'falha_download' (culpando a plataforma) — e o
    alerta crítico do navegador era fechado como se ele estivesse bom."""
    if exc is None or isinstance(exc, ErroConector):
        return None
    from app.sync.connectors.navegador import erro_conector_de_dentro
    erro = erro_conector_de_dentro(exc)
    if erro is None or erro.codigo != "navegador_indisponivel":
        return None
    return (erro.codigo, str(erro), erro.recuperavel)


def _recusar_contas_de_outra_escola(db: Session, execucao: SincronizacaoExecucao,
                                    arquivos) -> None:
    """D8 (risco A2, LGPD). SEM vínculo da escola externa, a coleta em que TODAS
    as contas identificadas (linhas com uuid/studentId) já são a identidade
    EFETIVA de alunos de OUTRA escola do Constela é recusada ANTES de aplicar
    qualquer linha.

    É a assinatura da credencial da outra escola cadastrada aqui por engano.
    Antes, cada conta virava uma revisão ``identidade_de_outra_escola`` DESTA
    escola, com o nome e os números da criança de lá. Agora nada é gravado: nem
    ficha, nem retrato, nem revisão, nem o vínculo da escola externa. Basta UMA
    conta que já é a identidade EFETIVA de um aluno ATIVO desta escola
    (``efetivas_na_escola``: vínculo não aposentado, ficha nem excluída nem
    inativa) ou ainda desconhecida no Constela para a coleta seguir como antes
    (coleta mista: aplica as desta escola e manda as de lá para a revisão).

    Não contam como "desta escola" e não livram a coleta da recusa: a identidade
    aposentada aqui (a conta duplicada que a escola descartou), a presa a uma
    ficha excluída e a presa a uma ficha INATIVA — transferida, arquivada, fora
    da Lista Piloto (``STATUS_INATIVOS``). A criança que saiu desta escola para a
    outra é este último caso: a saída troca só o status da ficha e a conta
    continua efetiva, porque a conta única de uma criança não pode ser
    aposentada. Do lado da OUTRA escola (``efetivas_em_outra_escola``) a ficha
    inativa continua contando (regra única do D10 e da revisão
    ``identidade_de_outra_escola``): as duas funções não são espelho.

    Com vínculo gravado a regra não se
    aplica: a escola externa já foi conferida pelo id, e a conta efetiva noutra
    escola é a criança que mudou de escola (revisão própria, confirmada pelo Admin
    Global — D10). Linha sem id não entra na conta (não identifica ninguém).

    Levanta ``ErroConector`` ``contas_de_outra_escola`` ('erro', alerta crítico,
    sem nova tentativa). O id interno da outra escola fica só na auditoria."""
    from app.services.audit import registrar
    from app.services.identidade_aluno import efetivas_em_outra_escola, efetivas_na_escola

    contas = orchestrator.contas_dos_arquivos(arquivos)
    total = sum(len(ids) for ids in contas.values())
    if not total:
        return
    escola_id = execucao.escola_id
    outras: set[int] = set()
    for plat, ids in contas.items():
        if efetivas_na_escola(db, escola_id, plat, ids):
            return              # ≥1 conta EFETIVA de ficha ATIVA aqui: mista, segue
        de_fora = efetivas_em_outra_escola(db, escola_id, plat, ids)
        if len(de_fora) < len(ids):
            return              # ≥1 conta desconhecida: pode ser desta escola, segue
        outras.update(de_fora.values())
    registrar(db, "sync.contas_de_outra_escola_recusada", escola_id=escola_id,
              entidade="plataforma",
              detalhes={"plataforma": execucao.plataforma, "contas": total,
                        "outras_escolas": sorted(outras)})
    db.commit()
    raise ErroConector(
        f"Todas as {total} conta(s) desta coleta já estão vinculadas a alunos de OUTRA "
        "escola do Constela: a credencial cadastrada parece ser a de outra escola. Nada "
        "foi gravado (nem fichas, nem números, nem pendências com os nomes). Confira a "
        "credencial desta escola. Se as crianças são mesmo daqui, o Admin Global grava o "
        "vínculo da escola externa e confirma as contas em Revisão de identidade.",
        codigo=escola_externa.CONTAS_DE_OUTRA_ESCOLA, recuperavel=False)


def _conferir_escola_externa(db: Session, execucao: SincronizacaoExecucao, escola,
                             conector, contexto_fetch: Contexto,
                             vinculo: dict | None, arquivos=()) -> bool:
    """A escola externa da coleta, conferida ANTES de aplicar (regras em
    ``sync/escola_externa.py``):

      * o conector que confere a escola (Elefante, Matific) e não disse qual
        escola leu → ``escola_nao_identificada``;
      * a escola externa já vinculada a OUTRA escola do Constela →
        ``escola_externa_em_outra_escola`` (a credencial aqui é a da outra) —
        também com vínculo: duas escolas que aprenderam a mesma ao mesmo tempo
        ficam as duas paradas até alguém decidir;
      * sem vínculo e TODAS as contas da coleta já são de outra escola do
        Constela → ``contas_de_outra_escola`` (D8, ``_recusar_contas_de_outra_escola``);
      * sem vínculo → aprende o desta coleta (o conector só chega aqui quando a
        conta enxerga EXATAMENTE uma escola, ou com o vínculo) — menos com o nome
        da escola externa divergente do cadastro (D9): a coleta segue, sem
        aprender (log e auditoria ``sync.escola_externa_nao_aprendida``);
      * com vínculo, nome da escola na plataforma (ou dos relatórios) × cadastro
        → só AVISO no log.

    Levanta ``ErroConector``: nada é aplicado. Devolve True quando APRENDEU o
    vínculo nesta coleta (ver ``_desfazer_vinculo_aprendido``)."""
    coleta = getattr(contexto_fetch, "coleta", None) or {}
    detectada = coleta.get("escola_externa")
    plataforma = execucao.plataforma
    if not isinstance(detectada, dict) or not detectada.get("id"):
        if getattr(conector, "confere_escola_externa", False):
            raise ErroConector(
                "A coleta não informou de qual escola da plataforma são os dados. Nada "
                "foi aplicado.", codigo=escola_externa.ESCOLA_NAO_IDENTIFICADA,
                recuperavel=False)
        return False
    id_ext = escola_externa.normalizar_id(plataforma, detectada["id"])
    if not id_ext:
        raise ErroConector(
            f"A plataforma informou a escola com um identificador fora do formato "
            f"conhecido ({str(detectada['id'])[:40]}). Nada foi aplicado.",
            codigo=escola_externa.ESCOLA_NAO_IDENTIFICADA, recuperavel=False)
    if vinculo is not None and id_ext != vinculo.get("id"):
        # K: o conector já confere, mas o serviço não aplica dado de uma escola
        # externa diferente da vinculada, venha de onde vier.
        raise ErroConector(
            f"A coleta leu a escola {escola_externa.descrever([detectada])} da plataforma, "
            f"mas esta escola está vinculada à {escola_externa.descrever([vinculo])}. Nada "
            "foi aplicado.", codigo=escola_externa.ESCOLA_TROCADA, recuperavel=False)
    outras = escola_externa.escolas_com_o_mesmo_vinculo(
        db, plataforma, id_ext, exceto=execucao.escola_id)
    if outras:
        # O id INTERNO da outra escola fica só na AUDITORIA (suporte/Admin Global):
        # a mensagem vai para a execução, o log e o alerta que ESTA escola lê, e
        # não deve revelar outro inquilino (revisão e97).
        from app.services.audit import registrar
        registrar(db, "sync.escola_externa_em_outra_escola", escola_id=execucao.escola_id,
                  entidade="plataforma",
                  detalhes={"plataforma": plataforma, "id_externo": id_ext,
                            "outras_escolas": sorted(outras)})
        db.commit()
        raise ErroConector(
            f"A conta desta credencial lê a escola {escola_externa.descrever([detectada])} "
            "da plataforma, que já está vinculada a outra escola do Constela. Nada foi "
            "aplicado: confira se a credencial cadastrada é desta escola (o Admin Global "
            "vê qual escola tem o vínculo).",
            codigo=escola_externa.ESCOLA_EM_OUTRA_ESCOLA, recuperavel=False)
    nome_cadastro = getattr(escola, "nome", "") or ""
    nome_externa = (detectada.get("nome") or "").strip()
    nomes = [nome_externa] + list(coleta.get("nomes_escola_relatorio") or [])
    divergentes = escola_externa.nomes_divergentes(nomes, nome_cadastro)
    lista_divergentes = "; ".join(n[:80] for n in divergentes[:3])
    if vinculo is None:
        _recusar_contas_de_outra_escola(db, execucao, arquivos)
        from app.services.audit import registrar
        if nome_externa and not escola_externa.nomes_compativeis(nome_externa, nome_cadastro):
            # D9 (risco A3): o nome da escola externa (a que a conta enxerga) não
            # confere com o cadastrado — pode ser a credencial de OUTRA escola que
            # ainda não tem histórico no Constela (a identidade não pega). A
            # coleta SEGUE (nomes variam e o dado vale), mas o vínculo NÃO é
            # aprendido: senão a escola errada o guardaria e a dona pararia em
            # 'escola_externa_em_outra_escola'. O Admin Global grava o vínculo
            # depois de conferir no "Testar conexão". O nome que só aparece nos
            # relatórios de turma continua sendo só aviso (abaixo).
            registrar(db, "sync.escola_externa_nao_aprendida", escola_id=execucao.escola_id,
                      entidade="plataforma",
                      detalhes={"plataforma": plataforma, "id_externo": id_ext,
                                "motivo": "nome_divergente",
                                "nome_plataforma": nome_externa[:200],
                                "nome_cadastro": nome_cadastro[:200]})
            registrar_log(db, execucao, "validacao", "warn",
                          "Escola externa NÃO vinculada nesta coleta: o nome da escola na "
                          f"plataforma ({nome_externa[:80]}) não confere com o cadastrado "
                          f"({nome_cadastro[:80]}). A coleta seguiu, mas sem gravar o vínculo; "
                          "confira se a credencial é desta escola e peça ao Admin Global "
                          "para gravar o vínculo da escola externa.")
            db.commit()
            return False
        escola_externa.salvar(db, execucao.escola_id, plataforma, id_ext,
                              detectada.get("nome") or "", origem="aprendido")
        registrar(db, "sync.escola_externa_aprendida", escola_id=execucao.escola_id,
                  entidade="plataforma",
                  detalhes={"plataforma": plataforma, "id_externo": id_ext,
                            "nome": (detectada.get("nome") or "")[:200]})
        registrar_log(db, execucao, "autenticacao", "info",
                      f"Escola externa vinculada nesta coleta (a conta enxerga uma só "
                      f"escola): {escola_externa.descrever([detectada])}.")
        db.commit()
    if divergentes:
        # Com vínculo (gravado antes, pelo Admin Global, ou aprendido agora com o
        # nome da escola externa compatível), a escola externa já foi conferida
        # pelo id: o nome divergente (também o dos relatórios de turma) é só
        # AVISO — nomes variam (sigla, "Prof.", abreviação). Nunca bloqueia.
        registrar_log(db, execucao, "validacao", "warn",
                      f"Aviso: o nome da escola na plataforma ({lista_divergentes}) é "
                      f"diferente do cadastrado ({nome_cadastro[:80]}). Só um aviso: "
                      "confira se a credencial é desta escola.")
    return vinculo is None


def _desfazer_vinculo_aprendido(db: Session, execucao: SincronizacaoExecucao,
                                ap: "_Apuracao") -> None:
    """A1: o vínculo APRENDIDO nesta coleta não fica quando ela trouxe conta já
    EFETIVA em outra escola do Constela — é o sinal da credencial de outra
    escola, e o vínculo errado bloquearia a escola dona
    (``escola_externa_em_outra_escola``). A coleta segue igual; a seguinte
    tenta aprender de novo."""
    escola_externa.remover(db, execucao.escola_id, execucao.plataforma)
    from app.services.audit import registrar
    registrar(db, "sync.escola_externa_desfeita", escola_id=execucao.escola_id,
              entidade="plataforma",
              detalhes={"plataforma": execucao.plataforma,
                        "contas_de_outra_escola": len(ap.ids_outra_escola)})
    registrar_log(db, execucao, "validacao", "warn",
                  f"Escola externa NÃO vinculada: {len(ap.ids_outra_escola)} conta(s) "
                  "desta coleta já são de outra escola do Constela. Confira a credencial.")


def executar(db: Session, execucao: SincronizacaoExecucao) -> SincronizacaoExecucao:
    """Roda UMA execução do início ao fim. Atualiza status, contadores, logs e
    alertas. Em erro recuperável, re-enfileira com backoff. Toda saída que grava um
    estado final deixa UMA linha ``sync_execucao_finalizada`` (``ORIGENS_DO_FIM``)."""
    # CONTRATO, a última barreira antes da chamada externa: a execução que já
    # estava na fila (nova tentativa, agendada, script manual) quando o módulo da
    # plataforma saiu do plano da rede é CANCELADA, com registro — não coleta dado
    # de criança de um produto que a rede não assinou. Sem alerta: não é falha.
    if not plataforma_no_plano(db, execucao.escola_id, execucao.plataforma):
        _cancelar_na_fila(db, execucao, _MSG_FORA_DO_PLANO.format(
            plataforma=execucao.plataforma), origem="cancelada_fora_do_plano")
        db.commit()           # a linha do fim (se ESTE chamador cancelou) sai aqui
        return execucao
    # Claim ATÔMICO: garante que só UM worker pega a execução (vários uvicorn
    # workers/réplicas apontam para o mesmo banco). Quem perder a corrida sai.
    claim = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao.id,
               SincronizacaoExecucao.status == "fila")
        .values(status="executando", iniciada_em=_agora()))
    db.commit()
    if claim.rowcount == 0:
        # Claim perdido: outro worker/thread a pegou (ou ela já saiu da fila). Para
        # quem perdeu não é um fim — a linha do fim é de quem a encerrar.
        return execucao
    db.refresh(execucao)
    # Contabilidade fora do banco: sobrevive a um rollback no meio da aplicação.
    ap = _Apuracao()
    ids = (execucao.id, execucao.escola_id, execucao.plataforma)
    try:
        with _sinal_de_vida_enquanto_roda(execucao.id):
            return _executar_reivindicada(db, execucao, ap)
    except BaseException:
        # Saída por exceção DEPOIS de o estado final ir para o banco (o commit antes
        # do recálculo, ou o do fim) e antes da linha: falha de banco no fim, ou um
        # aborto que nenhum ``except Exception`` pega (KeyboardInterrupt, SystemExit,
        # CancelledError). Sem estado final gravado, a execução segue 'executando' e
        # a linha é de quem a encerrar (reaper, boot ou o próximo pedido).
        if ap.fim_gravado is not None and not ap.fim_logado:
            status, motivo = ap.fim_gravado
            _escrever_fim(*ids, status, motivo, origem="executar_interrompida",
                          alunos_aplicados=len(ap.aplicados))
        raise


def _executar_reivindicada(db: Session, execucao: SincronizacaoExecucao,
                           ap: _Apuracao) -> SincronizacaoExecucao:
    """O corpo de ``executar`` depois do claim: coleta, aplica, fecha a execução e
    escreve a linha do fim (origem 'executar') depois do commit final."""
    inicio = time.monotonic()
    # Capturados JÁ: depois de um rollback (falha de banco) ler um atributo da
    # execução faria um SELECT numa sessão que acabou de quebrar.
    escola_id, plataforma = execucao.escola_id, execucao.plataforma
    execucao_id = execucao.id
    contexto = _contexto(db, execucao)
    escola = db.get(Escola, execucao.escola_id)
    conector = connectors.obter(execucao.plataforma)
    contexto_fetch = None
    completa = False
    coletou = False         # a coleta (fetch) terminou e a aplicação começou

    try:
        if escola is None:
            raise ErroConector("Escola inexistente.", codigo="escola",
                               recuperavel=False)
        if conector is None:
            raise ErroConector(f"Sem conector para {execucao.plataforma}.",
                               codigo="parser_incompativel", recuperavel=False)
        cred = vault.obter_credencial(db, execucao.escola_id, execucao.plataforma)
        # Parâmetros DESTA execução (ex.: janela de datas do Matific) entram no
        # extra da credencial — o conector os lê (matific_start_date/end_date).
        if cred is not None and execucao.parametros:
            cred.extra = {**(cred.extra or {}), **execucao.parametros}
        if cred is None:
            if vault.obter_linha(db, execucao.escola_id, execucao.plataforma) is not None:
                # A credencial EXISTE, mas a cifra não abre (chaves trocadas sem
                # recifrar, valor corrompido). A plataforma não recusou nada: o
                # código próprio não regrava 'invalida' (``_tratar_falha`` só marca
                # nos CODIGOS_CREDENCIAL_RECUSADA; o /status já deriva 'ilegivel') e
                # a execução diz o motivo honesto, sem detalhe da cifra. Antes saía
                # 'senha_invalida' e a credencial era gravada como 'invalida'.
                raise ErroConector(
                    vault.mensagem_credencial_ilegivel([execucao.plataforma]),
                    codigo=vault.CODIGO_CREDENCIAL_ILEGIVEL, recuperavel=False)
            raise ErroConector(
                "Credenciais não configuradas.",
                codigo="senha_invalida", recuperavel=False)
        # Quem assina a importação automática (``orchestrator._resolver_ator``) é
        # conferido ANTES de coletar: sem admin/coordenador ativo, a aplicação
        # levantava RuntimeError depois da coleta inteira — "Falha inesperada"
        # recuperável, e a nova tentativa coletava tudo de novo para falhar igual.
        if orchestrator._resolver_ator(db, execucao.escola_id, execucao.usuario_id) is None:
            raise ErroConector(
                "A escola não tem administrador nem coordenador ativo para assinar a "
                "importação automática, e nada foi coletado. Cadastre ou reative um em "
                "Usuários e sincronize de novo.",
                codigo=CODIGO_SEM_RESPONSAVEL, recuperavel=False)

        registrar_log(db, execucao, "autenticacao", "info",
                      f"Conectando à {execucao.plataforma}…")
        # Não segurar uma transação aberta durante o FETCH externo (rede/
        # navegador): idle-in-transaction derrubaria a conexão em Postgres
        # gerenciado. Constrói o contexto de fetch ANTES do commit (captura
        # escola_id/execucao_id já carregados, sem reabrir transação depois),
        # commita o que leu/logou e roda o conector com logs AUTÔNOMOS — `cred`
        # é objeto simples (Credenciais) e `escola` recarrega sob demanda na
        # persistência, que segue transacional (commit único no fim).
        contexto_fetch = _contexto(db, execucao, autonomo=True)
        # INCREMENTAL SEGURO: passa as contagens por aluno da última sync — o
        # conector pula a coleta pesada de quem não mudou (aluno novo/atrasado
        # SEMPRE coleta tudo). 1ª sync = vazio = tudo.
        completa, motivo_completa = _coleta_completa_devida(
            db, execucao.escola_id, execucao.plataforma)
        contexto_fetch.contadores_anteriores = {} if completa else _carregar_contadores(
            db, execucao.escola_id, execucao.plataforma)
        if completa:
            registrar_log(db, execucao, "download", "info",
                          "Recoleta COMPLETA nesta execução (cursor ignorado): "
                          + motivo_completa + ".")
        # VÍNCULO da escola externa: o conector recusa a conta que não enxerga a
        # escola vinculada (ou que enxerga várias sem vínculo) antes de coletar.
        vinculo = escola_externa.obter(db, execucao.escola_id, execucao.plataforma)
        contexto_fetch.escola_externa = vinculo
        contexto_fetch.externas_de_outras_escolas = escola_externa.ids_de_outras_escolas(
            db, execucao.plataforma, execucao.escola_id)
        db.commit()
        arquivos = _coletar(conector, cred, contexto_fetch)
        execucao.parser_versao = "perfis_pdf/planilhas"
        ap.incorporar_coleta(getattr(contexto_fetch, "coleta", None))
        # Antes de aplicar QUALQUER linha: a escola da coleta é esta (e não é a de
        # outra escola do Constela); sem vínculo, aprende-o aqui. Levanta → 'erro'.
        aprendeu = _conferir_escola_externa(db, execucao, escola, conector,
                                            contexto_fetch, vinculo, arquivos)
        if ap.falhas:
            contexto.log("download", "warn",
                         f"Coleta incompleta: {len(ap.falhas)} unidade(s) não chegaram "
                         f"({ap.resumo_falhas()}).")
        coletou = True

        for arquivo in arquivos:
            # Nenhum arquivo recalcula sozinho: o recálculo roda UMA vez ao final,
            # se algo foi gravado (antes dependia de o último arquivo ser o que
            # tinha dados — um "sem_dados" no fim deixava a escola sem recálculo).
            res = orchestrator.aplicar_arquivo(
                db, escola, arquivo, usuario_id=execucao.usuario_id,
                recalcular=False, contexto=contexto)
            ap.somar(res)
        if aprendeu and ap.ids_outra_escola:
            _desfazer_vinculo_aprendido(db, execucao, ap)
        _concluir(db, execucao, ap, contexto, contexto_fetch, completa,
                  escola_id=escola_id, plataforma=plataforma)

    except ErroConector as exc:
        if coletou:
            db.rollback()       # o arquivo em aplicação não fica pela metade
        # O conector que embrulha a chamada ao site ("falhou na API") com o navegador
        # caído como causa: a falha é do navegador deste servidor, não da plataforma.
        _encerrar_com_falha(db, execucao, ap, contexto, contexto_fetch, completa,
                            escola_id=escola_id, plataforma=plataforma, coletou=coletou,
                            falha=_navegador_que_caiu(exc.__cause__)
                            or (exc.codigo, str(exc), exc.recuperavel))
    except Exception as exc:  # noqa: BLE001 — qualquer falha inesperada é logada
        # DESFAZ a transação ANTES de registrar a falha: se o erro foi de banco
        # (constraint no flush, conexão, deadlock), a sessão fica inutilizável e o
        # próprio registro da falha estourava — a execução ficava 'executando',
        # sem log, até a limpeza de 30 min (que só roda com o agendador ligado).
        # O que o pipeline já commitou fica; só o trabalho pendente é descartado.
        db.rollback()
        # Traceback completo vai para o log da aplicação/Sentry (diagnóstico),
        # enquanto a mensagem PERSISTIDA no SincronizacaoLog fica genérica por
        # LGPD (não retém dados da escola/aluno na linha visível ao gestor).
        # O navegador que caiu no meio já vai ao log ERROR por
        # ``erro_conector_de_dentro`` e vira ``navegador_indisponivel``.
        caiu = _navegador_que_caiu(exc)
        if caiu is None:
            logger.exception("Falha inesperada na sync (escola %s, plataforma %s)",
                             escola_id, plataforma)
        _encerrar_com_falha(db, execucao, ap, contexto, contexto_fetch, completa,
                            escola_id=escola_id, plataforma=plataforma, coletou=coletou,
                            falha=caiu or ("erro_inesperado",
                                           f"Falha inesperada: {type(exc).__name__}", True))

    if ap.perdeu_o_fechamento:
        # O estado final e a linha do fim são de quem encerrou: nada de instante,
        # duração, frescor ou métrica desta thread por cima deles.
        db.commit()
        return execucao
    execucao.finalizada_em = _agora()
    execucao.duracao_ms = int((time.monotonic() - inicio) * 1000)
    if execucao.status in ("concluida", "sem_atualizacao"):
        # 'sem_atualizacao' (coleta inteira, nada novo) dentro do normal também
        # FECHA o 'lento' — antes ele ficava aberto até a próxima 'concluida'. Só a
        # 'concluida' abre: a régua do normal é a das concluídas.
        _avaliar_lentidao(db, execucao, pode_abrir=execucao.status == "concluida")
    # Frescor: o alerta 'desatualizada' abre/fecha também aqui, não só dentro do
    # agendador (que em produção está desligado).
    atualizar_alerta_desatualizada(db, db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == escola_id,
        SincronizacaoConfig.plataforma == plataforma)).scalars().first())
    # Lido ANTES do commit: depois dele os atributos expiram e ler um faria um SELECT.
    fim = (execucao.status, execucao.motivo, execucao.duracao_ms)
    db.commit()
    ap.fim_gravado = fim[:2]
    _logar_fim_da_execucao(execucao_id, escola_id, plataforma, fim, ap)
    ap.fim_logado = True
    _registrar_metricas_do_fim(plataforma, fim, ap)
    return execucao


# --------------------------------------------------------------------------
# A linha do fim no log da APLICAÇÃO: UMA por execução que chega a estado final
#
# ``sync_execucao_finalizada`` saía só no fim de ``executar``. As outras saídas para
# um estado final (cancelamentos na fila, órfãs, travadas) não deixavam rastro no
# log de produção — e foi essa falta que impediu diagnosticar o episódio de 21/10.
# Agora todo caminho que GRAVA um estado final escreve a mesma linha, com o campo
# ``origem`` dizendo qual foi. Quem perde a corrida (o UPDATE condicional não pegou
# a linha: outro processo a reivindicou, cancelou ou encerrou) não encerrou nada e
# não escreve. A linha sai só DEPOIS do commit que gravou o estado final.
# --------------------------------------------------------------------------
ORIGENS_DO_FIM = {
    "executar": "fim de ``executar``: coletou, ou falhou e registrou a falha",
    "executar_interrompida": "``executar`` gravou o estado final e saiu por exceção "
                             "antes da linha",
    "cancelada_fora_do_plano": "``executar`` cancelou antes de coletar: o módulo da "
                               "plataforma não está no plano da rede",
    "cancelada_por_pedido_manual": "um \"Sincronizar agora\" substituiu a execução "
                                   "que esperava na fila",
    "cancelada_na_fila": "cancelada na fila por outro caminho (padrão de "
                         "``_cancelar_na_fila``)",
    "fila_sem_agendador": "agendador desligado: cancelada a execução da fila que só "
                          "ele rodaria (``liberar_fila_sem_agendador``)",
    "fila_manual_orfa": "agendador desligado: cancelada a manual sem ninguém "
                        "esperando por ela (``liberar_fila_sem_agendador``)",
    "travada_no_pedido": "um novo pedido achou a ativa presa em 'executando' "
                         "(``enfileirar_ou_reaproveitar``)",
    "travada_no_agendador": "o reaper do agendador achou a execução presa "
                            "(``recuperar_execucoes_travadas``)",
    "travada_no_status": "agendador desligado: a leitura do /status achou a execução "
                         "sem sinal de vida (``liberar_fila_sem_agendador``)",
    "orfa_no_boot": "o boot achou a execução presa (``finalizar_orfas_no_boot``)",
}

_FINS_PENDENTES = "sync_fins_pendentes"   # Session.info: linhas à espera do commit
_FINS_OUVINDO = "sync_fins_ouvindo"       # Session.info: ouvintes já registrados


def _escrever_fim(execucao_id: int, escola_id: int, plataforma: str, status: str,
                  motivo: str | None, *, origem: str, duracao_ms: int | None = None,
                  alunos_aplicados: int | None = None) -> None:
    """A linha do fim. INFO só para 'concluida' com aluno aplicado; o resto é
    WARNING. Sem PII, sem URL e sem texto da plataforma ou da credencial: ids,
    status, motivo e origem (códigos), duração e contagem — ``None`` quando o
    caminho não as conhece (a execução não rodou até o fim). Falhar aqui nunca
    afeta a execução."""
    try:
        ok = status == "concluida" and bool(alunos_aplicados)
        logger.log(logging.INFO if ok else logging.WARNING,
                   "sync_execucao_finalizada execucao=%s escola=%s plataforma=%s "
                   "status=%s motivo=%s", execucao_id, escola_id, plataforma,
                   status, motivo or "-",
                   extra={"execucao_id": execucao_id, "escola_id": escola_id,
                          "plataforma": plataforma, "status": status, "motivo": motivo,
                          "duracao_ms": duracao_ms, "alunos_aplicados": alunos_aplicados,
                          "origem": origem})
    except Exception:  # noqa: BLE001 — o log nunca afeta a sincronização
        pass


def _logar_fim_da_execucao(execucao_id: int, escola_id: int, plataforma: str,
                           fim: tuple, ap: _Apuracao) -> None:
    """A linha do fim de ``executar`` (origem 'executar'), depois do commit final:
    status, motivo e duração lidos antes dele; a contagem, da contabilidade."""
    status, motivo, duracao_ms = fim
    _escrever_fim(execucao_id, escola_id, plataforma, status, motivo, origem="executar",
                  duracao_ms=duracao_ms, alunos_aplicados=len(ap.aplicados))


def _anotar_fim(db: Session, execucao_id: int, escola_id: int, plataforma: str,
                status: str, *, origem: str, alunos_aplicados: int | None = None) -> None:
    """Anota a linha do fim de uma transição para estado final que ESTE chamador
    acabou de fazer na transação aberta (o UPDATE condicional que ele venceu). Ela
    sai no log no commit da transação RAIZ (``_emitir_fins``); a transação desfeita
    — o rollback do 409 do "Sincronizar agora", a sessão fechada sem commit, um
    savepoint revertido — não deixa linha (``_descartar_fins``). Sem ida ao banco."""
    if not db.info.get(_FINS_OUVINDO):
        event.listen(db, "after_commit", _emitir_fins)
        event.listen(db, "after_soft_rollback", _descartar_fins)
        db.info[_FINS_OUVINDO] = True
    db.info.setdefault(_FINS_PENDENTES, []).append(
        (db.get_transaction(), db.get_nested_transaction(),
         {"execucao_id": execucao_id, "escola_id": escola_id, "plataforma": plataforma,
          "status": status, "motivo": None, "origem": origem,
          "alunos_aplicados": alunos_aplicados}))


def _emitir_fins(sessao: Session) -> None:
    """after_commit: escreve as linhas anotadas na transação que commitou. O
    after_commit também dispara no RELEASE de um savepoint — só o commit da RAIZ
    grava de fato. Anotação de uma raiz que não commitou (sessão fechada sem
    commit) fica para trás e é descartada aqui."""
    if sessao.in_nested_transaction():
        return
    raiz = sessao.get_transaction()
    for dona, _savepoint, linha in sessao.info.pop(_FINS_PENDENTES, None) or ():
        if dona is raiz:
            _escrever_fim(**linha)


def _descartar_fins(sessao: Session, desfeita) -> None:
    """after_soft_rollback: a transação (ou o savepoint) desfeita não gravou as
    transições anotadas nela — elas não aconteceram e não têm linha."""
    pendentes = sessao.info.get(_FINS_PENDENTES)
    if pendentes:
        sessao.info[_FINS_PENDENTES] = [p for p in pendentes
                                        if not _anotada_em(p, desfeita)]


def _anotada_em(pendente: tuple, transacao) -> bool:
    """A anotação foi feita dentro de ``transacao`` (a raiz, ou um savepoint que a
    continha)?"""
    dona, savepoint, _linha = pendente
    if not transacao.nested:
        return dona is transacao
    while savepoint is not None:
        if savepoint is transacao:
            return True
        savepoint = savepoint.parent
    return False


def _registrar_metricas_do_fim(plataforma: str, fim: tuple, ap: _Apuracao) -> None:
    """Ponto ÚNICO das métricas de EVENTO da sincronização (``app/sync/metricas``):
    no fim de ``executar``, depois do commit — conta só o que ficou gravado. Uma
    falha aqui nunca derruba a execução (ela já está fechada no banco)."""
    try:
        from app.sync import metricas
        status, motivo, duracao_ms = fim
        metricas.execucao_finalizada(plataforma=plataforma, status=status, motivo=motivo,
                                     duracao_ms=duracao_ms,
                                     alunos_aplicados=len(ap.aplicados), falhas=ap.falhas)
    except Exception:  # noqa: BLE001 — métrica não pode afetar a sincronização
        logger.warning("metricas_sync_evento_falhou (plataforma %s)", plataforma,
                       exc_info=True)


# 'lento' é RELATIVO ao histórico da própria integração: o teto fixo de
# SYNC_LENTO_S (120 s) fica abaixo do normal de uma coleta completa do Elefante
# (minutos), então TODA execução era "lenta" e o alerta nunca fechava. Agora:
# lento = acima de max(SYNC_LENTO_S, 2 × mediana das últimas execuções concluídas
# da MESMA escola+plataforma); com histórico curto, vale só o piso.
LENTO_JANELA = 10
LENTO_MIN_HISTORICO = 5
LENTO_FATOR = 2


def limite_lento_ms(db: Session, escola_id: int, plataforma: str, *,
                    excluir_id: int | None = None) -> tuple[int, int | None]:
    """(limite em ms, mediana em ms | None) da duração normal da integração."""
    consulta = select(SincronizacaoExecucao.duracao_ms).where(
        SincronizacaoExecucao.escola_id == escola_id,
        SincronizacaoExecucao.plataforma == plataforma,
        SincronizacaoExecucao.status == "concluida",
        SincronizacaoExecucao.duracao_ms > 0)
    if excluir_id is not None:
        consulta = consulta.where(SincronizacaoExecucao.id != excluir_id)
    duracoes = list(db.scalars(
        consulta.order_by(SincronizacaoExecucao.id.desc()).limit(LENTO_JANELA)))
    piso = settings.SYNC_LENTO_S * 1000
    if len(duracoes) < LENTO_MIN_HISTORICO:
        return piso, None
    mediana = int(statistics.median(duracoes))
    return max(piso, LENTO_FATOR * mediana), mediana


def _avaliar_lentidao(db: Session, execucao: SincronizacaoExecucao, *,
                      pode_abrir: bool = True) -> None:
    """Abre o aviso 'lento' quando ESTA execução concluída fugiu do normal da
    integração; FECHA-o quando terminou dentro do normal (antes nunca fechava).
    ``pode_abrir=False``: só fecha (execução que não é 'concluida')."""
    limite, mediana = limite_lento_ms(db, execucao.escola_id, execucao.plataforma,
                                      excluir_id=execucao.id)
    if execucao.duracao_ms <= limite:
        resolver_alertas(db, execucao.escola_id, execucao.plataforma, ("lento",))
        return
    if not pode_abrir:
        return
    base = (f"o normal desta integração é {mediana // 1000}s" if mediana is not None
            else f"limite de {settings.SYNC_LENTO_S}s")
    abrir_alerta(db, execucao.escola_id, execucao.plataforma, "lento",
                 f"Sincronização levou {execucao.duracao_ms // 1000}s "
                 f"(> {limite // 1000}s; {base}).", severidade="info",
                 execucao_id=execucao.id)


def _avaliar_queda_matific(db: Session, execucao: SincronizacaoExecucao,
                           totais: dict) -> None:
    """Alerta de REVISÃO quando o Matific mandou, para algum aluno, um acumulado
    MENOR que o já gravado (ver ``orchestrator.reter_quedas_matific``): o valor
    gravado foi mantido e alguém precisa conferir. Fecha quando uma coleta que
    fez a conferência não encontra mais nenhuma queda."""
    if execucao.plataforma != "matific":
        return
    n = int(totais.get("retidos_queda") or 0)
    if n:
        abrir_alerta(
            db, execucao.escola_id, "matific", "queda_matific",
            f"{n} aluno(s) vieram do Matific com total de atividades/estrelas MENOR "
            "que o já gravado no ano. O valor gravado foi mantido (nada foi "
            "rebaixado). Confira no Matific; se a queda for real (correção da "
            "plataforma), importe o relatório oficial em Importações.",
            severidade="warn", execucao_id=execucao.id)
    elif totais.get("verificou_queda"):
        resolver_alertas(db, execucao.escola_id, "matific", ("queda_matific",))


def _tratar_falha(db: Session, execucao: SincronizacaoExecucao, contexto: Contexto,
                  codigo: str, mensagem: str, *, recuperavel: bool) -> None:
    """Registra a falha de uma execução que o chamador JÁ fechou como 'erro'
    (``_fechar_se_ainda_executando``)."""
    execucao.erro_resumo = mensagem[:300]
    # Sem motivo mais específico da contabilidade ('coleta_incompleta',
    # 'linhas_descartadas'), o motivo do 'erro' é o CÓDIGO da falha
    # ('sem_acesso_ao_dado', 'timeout', 'falha_download', 'parser_incompativel'…):
    # é o que a tela de Integrações traduz no histórico e no /status.
    if not execucao.motivo:
        execucao.motivo = (codigo or "")[:40] or None
    registrar_log(db, execucao, "scheduler", "error", mensagem)
    if codigo in CODIGOS_RESPOSTA_DO_LOGIN:
        # A execução chegou à página de login (o navegador abriu desta vez) e foi
        # recusada: o alerta crítico do Chromium que não subia perdeu a causa e não
        # fica na tela ao lado do novo. Antes, no "Sincronizar agora" depois de uma
        # execução cujo navegador não abriu, ficavam "plataforma indisponível" e
        # "senha recusada" (ou "CAPTCHA") abertos juntos. O "Credenciais não
        # configuradas" também sai como 'senha_invalida' sem abrir o navegador, mas
        # aí não há o que fechar: remover a credencial já resolve as falhas dela.
        _fechar_alerta_do_navegador(db, execucao.escola_id, execucao.plataforma, execucao)
    tipo, sev = alerta_do_codigo(codigo)        # MAPA ÚNICO (o mesmo da credencial)
    abrir_alerta(db, execucao.escola_id, execucao.plataforma, tipo, mensagem,
                 severidade=sev, execucao_id=execucao.id)
    # marca a credencial como inválida SÓ quando a plataforma recusou a senha
    if codigo in CODIGOS_CREDENCIAL_RECUSADA:
        linha = vault.obter_linha(db, execucao.escola_id, execucao.plataforma)
        if linha is not None:
            vault.marcar_status(db, linha, "invalida", mensagem)
    _agendar_retentativa(db, execucao, recuperavel=recuperavel)


def _fechar_alerta_do_navegador(db: Session, escola_id: int, plataforma: str,
                                execucao: SincronizacaoExecucao) -> int:
    """Fecha o alerta de quando o Chromium deste servidor não abriu
    ('plataforma_indisponivel', de ``navegador_indisponivel``) e diz no log da execução
    que o fechou. Devolve quantos fechou."""
    navegador, _ = alerta_do_codigo("navegador_indisponivel")
    n = resolver_alertas(db, escola_id, plataforma, (navegador,))
    if n:
        registrar_log(db, execucao, "scheduler", "info",
                      "Alerta “plataforma indisponível” (o navegador deste servidor não "
                      "abria) fechado: esta execução chegou à plataforma.")
    return n


def _agendar_retentativa(db: Session, execucao: SincronizacaoExecucao, *,
                         recuperavel: bool) -> None:
    """Nova tentativa com backoff exponencial para falha recuperável (também a
    'parcial' que falhou depois de gravar) — só com o agendador ligado."""
    if recuperavel and execucao.tentativa < settings.SYNC_MAX_TENTATIVAS:
        if not agendador_ligado():
            # Quem roda a nova tentativa (com disponivel_em no futuro) é o
            # agendador. Desligado, ela ficava na fila para sempre: a tela dizia
            # "Sincronizando" e a falha nunca aparecia. Sem agendador, a falha
            # fica como está e a escola tenta de novo quando quiser.
            registrar_log(db, execucao, "scheduler", "warn",
                          "Sem nova tentativa automática: o agendador está desligado "
                          "neste servidor. Use “Sincronizar agora” para tentar de novo.")
            return
        atraso = settings.SYNC_BACKOFF_BASE_S * (2 ** (execucao.tentativa - 1))
        proxima = _agora() + timedelta(seconds=atraso)
        enfileirar(db, execucao.escola_id, execucao.plataforma,
                   origem=execucao.origem, usuario_id=execucao.usuario_id,
                   tentativa=execucao.tentativa + 1, disponivel_em=proxima,
                   parametros=execucao.parametros or None)
        registrar_log(db, execucao, "scheduler", "warn",
                      f"Reenfileirado (tentativa {execucao.tentativa + 1}) em "
                      f"{atraso}s.")


def executar_por_id(execucao_id: int) -> None:
    """Roda uma execução com sessão PRÓPRIA (para thread de fundo)."""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        ex = db.get(SincronizacaoExecucao, execucao_id)
        if ex is not None:
            executar(db, ex)
    finally:
        db.close()


# Limita quantas sincronizações MANUAIS ("sincronizar agora") rodam de fato ao
# mesmo tempo. Cada uma pode subir um Chromium (login) e abrir conexões — sem
# esse teto, um pico de cliques de coordenadores poderia estourar RAM/pool e
# derrubar a instância. O caminho manual não passava pelo SYNC_WORKERS (que só
# limita o scheduler); este semáforo fecha essa lacuna. Excesso espera sua vez.
_semaforo_manual = threading.BoundedSemaphore(max(1, settings.SYNC_WORKERS))


def registrar_espera_na_fila(db: Session, execucao_id: int) -> bool:
    """Sinal de vida de uma manual que ainda espera a vez (ver
    ``_manual_orfa``): uma linha no log dela, que a tela mostra e os outros
    workers leem. Devolve False se ela já saiu da fila (cancelada, assumida por
    outro pedido ou reivindicada em outro worker) — não há mais o que esperar."""
    execucao = db.get(SincronizacaoExecucao, execucao_id)
    if execucao is None or execucao.status != "fila":
        return False
    criada = _naive_utc(execucao.created_at) or _agora()
    minutos = int(max(timedelta(0), _agora() - criada).total_seconds() // 60)
    registrar_log(db, execucao, "scheduler", "info",
                  "Aguardando a vez: outra sincronização está rodando neste "
                  f"servidor ({minutos} min na fila).")
    db.commit()
    return True


def _sinal_de_vida_da_espera(execucao_id: int) -> bool:
    """``registrar_espera_na_fila`` com sessão própria. Falha de banco NÃO
    abandona o pedido (devolve True): perder um sinal é tolerado — são seis por
    janela."""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        return registrar_espera_na_fila(db, execucao_id)
    except Exception:  # noqa: BLE001 — o sinal nunca derruba a thread que espera
        logger.warning("Falha ao registrar o sinal de vida da execução %s na fila",
                       execucao_id, exc_info=True)
        return True
    finally:
        db.close()


# --------------------------------------------------------------------------
# Sinal de vida de quem está em 'executando'
#
# Antes o único critério era a idade (``iniciada_em`` além de SYNC_TRAVADA_S): a
# execução morta num redeploy segurava a escola por até 60 min (o clique se juntava
# a ela e a tela dizia "Sincronizando"), e a viva além disso era reivindicada. Agora
# uma thread escreve no log da execução enquanto ela roda, cobrindo também a fase de
# aplicação, cujos registros só ficam visíveis no commit de cada arquivo.
# --------------------------------------------------------------------------
def batimento_execucao_s() -> float:
    """Intervalo do sinal de vida: 6 por janela de ``SYNC_SEM_SINAL_S``, para um
    atraso ou uma falha de banco não bastarem para a execução parecer morta."""
    return max(1.0, settings.SYNC_SEM_SINAL_S / 6)


def registrar_batimento_execucao(db: Session, execucao_id: int) -> bool:
    """Uma linha no log de quem está rodando — só se ninguém escreveu lá há um
    intervalo: a coleta já registra o próprio progresso e o histórico da tela não
    enche à toa. Devolve False se a execução já saiu de 'executando'."""
    execucao = db.get(SincronizacaoExecucao, execucao_id)
    if execucao is None or execucao.status != "executando":
        return False
    agora = _agora()
    ultimo = _naive_utc(db.scalar(select(func.max(SincronizacaoLog.created_at)).where(
        SincronizacaoLog.execucao_id == execucao_id)))
    if ultimo is not None and agora - ultimo < timedelta(seconds=batimento_execucao_s()):
        return True
    inicio = _naive_utc(execucao.iniciada_em) or agora
    minutos = int(max(timedelta(0), agora - inicio).total_seconds() // 60)
    registrar_log(db, execucao, "scheduler", "info",
                  f"Em andamento: a sincronização segue rodando neste servidor ({minutos} min).")
    db.commit()
    return True


def _sinal_de_vida_da_execucao(execucao_id: int) -> bool:
    """``registrar_batimento_execucao`` com sessão própria. Falha de banco não para
    o sinal (devolve True): perder um é tolerado, são seis por janela."""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        return registrar_batimento_execucao(db, execucao_id)
    except Exception:  # noqa: BLE001 — o sinal nunca derruba a coleta
        logger.warning("Falha ao registrar o sinal de vida da execução %s", execucao_id,
                       exc_info=True)
        return True
    finally:
        db.close()


@contextmanager
def _sinal_de_vida_enquanto_roda(execucao_id: int):
    """Mantém o sinal de vida da execução enquanto o bloco roda. Com teto: uma
    thread pendurada para sempre deixa de dar sinal depois de 2 × SYNC_TRAVADA_S e
    a escola é liberada — o sinal prova que o processo está de pé, não que há
    progresso. Sem thread (limite do sistema), a coleta segue sem o sinal."""
    parar = threading.Event()

    def _rodar() -> None:
        teto = time.monotonic() + 2 * settings.SYNC_TRAVADA_S
        while not parar.wait(batimento_execucao_s()):
            if time.monotonic() > teto or not _sinal_de_vida_da_execucao(execucao_id):
                return

    try:
        threading.Thread(target=_rodar, daemon=True,
                         name=f"sync-sinal-{execucao_id}").start()
    except RuntimeError:
        logger.warning("Sem thread para o sinal de vida da execução %s", execucao_id)
    try:
        yield
    finally:
        parar.set()


def precisa_de_thread(execucao: SincronizacaoExecucao) -> bool:
    """O "Sincronizar agora" deve disparar uma thread para esta execução? Só se
    ela ainda está na FILA — o claim de ``executar`` é ``WHERE status='fila'`` — e
    nenhuma thread DESTE processo já espera por ela. Para uma já 'executando'
    (coleta longa, clique repetido), ou na fila com a thread dela aqui, a thread
    nova só esperaria o semáforo (dando sinal de vida no log) para perder o claim
    e sair: no episódio de 21/10, 6 cliques durante uma coleta longa deixaram 11
    threads esperando. A manual na fila SEM thread aqui (de outro worker, ou de
    um processo que morreu antes de ela virar órfã) continua recebendo a sua: o
    claim decide quem roda."""
    if execucao.status != "fila":
        return False
    with _vivas_lock:
        return execucao.id not in _vivas_neste_processo


def disparar_em_thread(execucao_id: int) -> None:
    """Processa uma execução manual sem bloquear o request (thread daemon),
    respeitando ``_semaforo_manual`` para não estourar recursos num pico. Enquanto
    espera a vez, a thread fica no registro do processo e dá sinal de vida no
    log — é o que impede o /status e o boot de outro worker de a cancelarem como
    órfã (``_manual_orfa``)."""
    def _rodar() -> None:
        try:
            while not _semaforo_manual.acquire(timeout=batimento_fila_s()):
                if not _sinal_de_vida_da_espera(execucao_id):
                    return        # saiu da fila enquanto esperava: nada a rodar
            try:
                executar_por_id(execucao_id)
            except Exception:  # noqa: BLE001 — a thread não tem quem a trate
                # Sem isto a exceção morria no threading.excepthook (traceback cru no
                # stderr, com o DETAIL do banco); assim passa pelo log redigido, como no
                # agendador (_uma_rodada).
                logger.exception("sync_manual_falhou", extra={"execucao_id": execucao_id})
            finally:
                _semaforo_manual.release()
        finally:
            with _vivas_lock:
                _vivas_neste_processo.discard(execucao_id)

    with _vivas_lock:
        _vivas_neste_processo.add(execucao_id)
    try:
        threading.Thread(target=_rodar, daemon=True,
                         name=f"sync-manual-{execucao_id}").start()
    except BaseException:
        with _vivas_lock:              # sem thread, ninguém espera por ela
            _vivas_neste_processo.discard(execucao_id)
        raise


# --------------------------------------------------------------------------
# Agendamento (cadência → próxima execução)
# --------------------------------------------------------------------------
def calcular_proxima(config: SincronizacaoConfig, base: datetime | None = None) -> datetime | None:
    """Próxima execução a partir da cadência. None se manual/inativo.

    ``hora_local`` e ``dia_semana`` são do relógio de BRASÍLIA — é o que a escola
    escolhe na tela ("todos os dias às 03:00"). ``base`` e o resultado são UTC
    naive, como tudo que o banco guarda. Antes, o horário era aplicado direto
    sobre o relógio UTC do servidor: a agenda das "03:00" rodava às 03:00 UTC, à
    MEIA-NOITE em Brasília (e o "dia da semana" virava às 21h)."""
    if not config.ativo or config.cadencia == "manual":
        return None
    base_local = fuso.para_local(base or _agora())
    hh, mm = (config.hora_local or "03:00").split(":")
    # Aritmética no horário de PAREDE local: somar dias preserva "03:00" mesmo
    # se um dia houver horário de verão; a conversão para UTC é feita no fim.
    alvo = base_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if config.cadencia == "diaria":
        if alvo <= base_local:
            alvo += timedelta(days=1)
        return fuso.local_para_utc_naive(alvo.replace(tzinfo=None))
    if config.cadencia == "semanal":
        dia = config.dia_semana if config.dia_semana is not None else 0
        delta = (dia - alvo.weekday()) % 7
        alvo += timedelta(days=delta)
        if alvo <= base_local:
            alvo += timedelta(days=7)
        return fuso.local_para_utc_naive(alvo.replace(tzinfo=None))
    return None


# Atraso a partir do qual a agenda vencida só é recalculada (ver
# ``enfileirar_agendados``): a própria cadência.
ATRASO_MAXIMO_POR_CADENCIA = {"diaria": timedelta(days=1), "semanal": timedelta(days=7)}


def _vencida_ha_mais_que_a_cadencia(config: SincronizacaoConfig, agora: datetime) -> bool:
    limite = ATRASO_MAXIMO_POR_CADENCIA.get(config.cadencia)
    prevista = _naive_utc(config.proxima_execucao)
    return limite is not None and prevista is not None and agora - prevista > limite


def enfileirar_agendados(db: Session) -> int:
    """Varre configs vencidas e enfileira as execuções (chamado pelo worker).

    CLAIM ATÔMICO da config: ``UPDATE ... WHERE proxima_execucao<=agora`` avança
    a próxima e só enfileira se ganharmos a corrida (rowcount==1). Assim, N
    schedulers (um por réplica) nunca enfileiram a mesma agenda duas vezes — o
    lock de linha do UPDATE serializa e o WHERE re-checa a janela.

    AGENDA VENCIDA HÁ MAIS QUE A CADÊNCIA (o agendador ficou desligado, ou a agenda
    foi salva dias antes de ligá-lo) só é RECALCULADA para o próximo horário dela,
    sem enfileirar: antes ela rodava na 1ª rodada, a qualquer hora — religar o
    agendador entre 07:30 e 10:30 de Brasília colidia com o backup. O atraso curto
    (uma rodada perdida, um reinício) continua enfileirando."""
    agora = _agora()
    n = 0
    vencidas = db.execute(
        select(SincronizacaoConfig).where(
            SincronizacaoConfig.ativo.is_(True),
            SincronizacaoConfig.cadencia != "manual",
            SincronizacaoConfig.proxima_execucao.isnot(None),
            SincronizacaoConfig.proxima_execucao <= agora,
        )
    ).scalars().all()
    for config in vencidas:
        nova = calcular_proxima(config, agora)
        atrasada = _vencida_ha_mais_que_a_cadencia(config, agora)
        reivindicou = db.execute(
            update(SincronizacaoConfig)
            .where(SincronizacaoConfig.id == config.id,
                   SincronizacaoConfig.proxima_execucao <= agora)
            .values(proxima_execucao=nova)).rowcount
        if reivindicou == 1 and atrasada:
            # Sem PII: ids e a nova data. A coleta acontece no próximo horário.
            logger.warning("sync_agenda_vencida_recalculada escola=%s plataforma=%s "
                           "proxima=%s", config.escola_id, config.plataforma,
                           nova.isoformat() if nova else "-")
            db.commit()
        elif reivindicou == 1 and not plataforma_no_plano(db, config.escola_id,
                                                          config.plataforma):
            # Módulo fora do plano da rede: a agenda AVANÇA (não volta a vencer a
            # cada rodada), mas nada é enfileirado — a agenda fica como a escola a
            # deixou e volta a valer se o módulo for recontratado.
            db.commit()
        elif reivindicou == 1:
            enfileirar(db, config.escola_id, config.plataforma, origem="scheduler")
            db.commit()               # solta o lock da config e publica a fila
            n += 1
        else:
            db.rollback()             # outro worker reivindicou; descarta
    return n


def garantir_agendas_diarias(db: Session,
                             plataformas: tuple[str, ...] = ("matific", "elefante")) -> int:
    """AUTO-CURA da agenda: toda escola com credencial da plataforma mas SEM
    NENHUMA configuração de agenda ganha uma DIÁRIA (03:00) ativa.

    É o que elimina o "re-salvar credencial": rodando a cada rodada do scheduler,
    a sync diária passa a funcionar sozinha depois de configurar a credencial UMA
    vez — e se recria caso a linha suma. Respeita OPT-OUT: quem desliga usa
    ``ativo=False`` (a linha PERMANECE, então não é recriada); só escolas sem
    linha alguma recebem a agenda. Idempotente."""
    from app.models.sincronizacao import PlataformaCredencial

    n = 0
    for plat in plataformas:
        sem_config = select(PlataformaCredencial.escola_id).where(
            PlataformaCredencial.plataforma == plat,
            PlataformaCredencial.escola_id.notin_(
                select(SincronizacaoConfig.escola_id).where(
                    SincronizacaoConfig.plataforma == plat)))
        for escola_id in db.execute(sem_config).scalars().all():
            try:
                with db.begin_nested():   # savepoint: corrida entre réplicas na unique
                    cfg = SincronizacaoConfig(escola_id=escola_id, plataforma=plat,
                                              ativo=True, cadencia="diaria",
                                              hora_local="03:00")
                    db.add(cfg)
                    db.flush()
                cfg.proxima_execucao = calcular_proxima(cfg)
                n += 1
            except IntegrityError:
                # Outra réplica criou a config para esta escola primeiro — ok.
                pass
    if n:
        db.commit()
    return n


def finalizar_orfas_no_boot(db: Session) -> int:
    """No BOOT do processo: libera execuções presas em 'executando' sem sinal de vida
    há mais de ``SYNC_SEM_SINAL_S`` — o worker que as rodava morreu no
    restart/redeploy. Marca 'erro' e LIBERA a trava (uq_sync_exec_ativa) SEM
    re-enfileirar (o usuário retoma quando quiser). Idempotente.

    O GATE DO SINAL é essencial com MÚLTIPLOS workers (uvicorn --workers > 1): o
    boot de UM worker NÃO significa que o vizinho parou. Sem o gate, este reaper
    mataria a sincronização EM ANDAMENTO de outro worker (furando a exclusão
    mútua e podendo duplicar recálculos). Com o gate, só toca execuções caladas
    há tempo bastante para que ninguém mais as esteja executando — o mesmo limiar
    do reaper periódico (recuperar_execucoes_travadas). A que acabou de morrer no
    próprio redeploy ainda tem sinal recente: sai pela leitura do /status ou pelo
    próximo clique, passada a janela (``liberar_fila_sem_agendador``)."""
    n = 0
    for ex in _orfas_em_execucao(db):
        if _finalizar_travada(db, ex, origem="orfa_no_boot"):
            n += 1
    if n:
        db.commit()
    return n + liberar_fila_sem_agendador(db)


_MOTIVO_SO_O_AGENDADOR = (
    "Cancelada: o agendador automático está desligado neste servidor e só ele "
    "rodaria esta execução. Use “Sincronizar agora” para tentar de novo.")
_MOTIVO_MANUAL_ORFA = (
    "Cancelada: nenhum processo do servidor esperava mais por esta sincronização "
    "(sem sinal de vida na fila — o processo que a esperava parou, como num "
    "reinício do serviço). Use “Sincronizar agora” para tentar de novo.")


def liberar_fila_sem_agendador(db: Session, escola_id: int | None = None) -> int:
    """Com o agendador DESLIGADO, cancela (com registro) as execuções da fila que
    só ele rodaria (``so_o_agendador_roda``): novas tentativas com backoff,
    agendadas, manuais ÓRFÃS. Elas nunca vão rodar — deixá-las na fila fazia o
    card dizer "Sincronizando" para sempre e prendia a exclusão mútua até alguém
    clicar. Manual cuja thread ainda espera a vez — neste processo ou em outro
    worker, pelo sinal de vida — não é tocada, por mais antiga que seja. Encerra
    também a 'executando' sem sinal de vida (``_esta_travada``): sem o agendador,
    quem a libertava era só o próximo clique, e a tela ficava em "Sincronizando".
    Com o agendador ligado, não faz nada: ele as pega. Idempotente. Roda no boot e
    na leitura do /status (``escola_id``), na mesma consulta."""
    if agendador_ligado():
        return 0
    consulta = select(SincronizacaoExecucao).where(
        SincronizacaoExecucao.status.in_(("fila", "executando")))
    if escola_id is not None:
        consulta = consulta.where(SincronizacaoExecucao.escola_id == escola_id)
    agora = _agora()
    n = 0
    for ex in db.execute(consulta).scalars().all():
        if ex.status == "executando":
            if _esta_travada(ex) and _finalizar_travada(db, ex, origem="travada_no_status"):
                abrir_alerta(db, ex.escola_id, ex.plataforma, "interrompida",
                             "Sincronização interrompida (reinício do serviço). Use "
                             "“Sincronizar agora” para tentar de novo.",
                             severidade="warn", execucao_id=ex.id)
                n += 1
            continue
        if not so_o_agendador_roda(ex, agora=agora):
            continue
        manual = ex.origem != "scheduler" and ex.disponivel_em is None
        if _cancelar_na_fila(db, ex, _MOTIVO_MANUAL_ORFA if manual
                             else _MOTIVO_SO_O_AGENDADOR,
                             origem="fila_manual_orfa" if manual else "fila_sem_agendador"):
            n += 1
    if n:
        db.commit()
    return n


def recuperar_execucoes_travadas(db: Session) -> int:
    """Reaper (retomada após crash): execuções em 'executando' sem sinal de vida há
    mais de ``SYNC_SEM_SINAL_S`` — worker morto ou redeploy no meio — são finalizadas
    como 'erro' e re-enfileiradas (respeitando o limite de tentativas). Sem isto, o
    índice de exclusão mútua prenderia a escola até uma intervenção manual.

    Roda no início de cada rodada do scheduler. É seguro com várias réplicas: o
    UPDATE atômico garante que só um worker reivindica cada órfã."""
    n = 0
    for ex in _orfas_em_execucao(db):
        if not _finalizar_travada(db, ex, origem="travada_no_agendador"):
            db.rollback()             # outro worker já a reivindicou
            continue
        abrir_alerta(db, ex.escola_id, ex.plataforma, "interrompida",
                     "Sincronização interrompida (reinício do serviço) e reprogramada.",
                     severidade="warn", execucao_id=ex.id)
        if ex.tentativa < settings.SYNC_MAX_TENTATIVAS:
            # ``disponivel_em`` marca a nova tentativa como DA FILA (nenhuma
            # thread manual espera por ela — ``so_o_agendador_roda``).
            enfileirar(db, ex.escola_id, ex.plataforma, origem=ex.origem,
                       usuario_id=ex.usuario_id, tentativa=ex.tentativa + 1,
                       disponivel_em=_agora(), parametros=ex.parametros or None)
        db.commit()
        n += 1
    return n
