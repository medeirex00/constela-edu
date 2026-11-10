"""Orquestrador — cola o conector ao PIPELINE DE IMPORTAÇÃO EXISTENTE.

Recebe um ``ArquivoObtido`` (bytes idênticos a um upload manual) e o entrega ao
mesmo caminho ``analisar`` → ``confirmar`` que o humano usa. Assim tudo o que já
funciona é reaproveitado SEM duplicação: parser multi-estratégia, casamento de
nomes, snapshots imutáveis, scoring/rankings, push, Quest e medalhas
(recalculados por ``scoring.recalcular_escola`` dentro do ``confirmar``).

DECISÃO ARQUITETURAL (justificativa): não refatoramos ``confirmar`` — o
orquestrador o CHAMA diretamente, com um "ator" resolvido (o usuário que pediu
a sync manual, ou um admin/coordenador da escola quando é o scheduler). Isso
preserva o pipeline 100% (zero risco de regressão). A verdade de auditoria de
"quem/como disparou" (manual × scheduler) vive em ``SincronizacaoExecucao``.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Usuario
from app.models.academico import Turma
from app.models.escola import Escola
from app.routers import importacoes as imp  # reuso: confirmar, _guardar_temporario
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import importacao as svc
from app.services import perfis_pdf, planilhas, politica_sync, professores
# AJUSTE_DA_COLETA: quem resolve a resposta que mudou de formato — o service o lê daqui
# (``orchestrator.AJUSTE_DA_COLETA``); mora em ``interfaces`` porque os conectores (que
# este módulo importa) usam o mesmo texto na mensagem do erro.
from app.sync.interfaces import AJUSTE_DA_COLETA, ArquivoObtido, Contexto, ErroConector


# Marcador do conteúdo JSON vindo da API interna do Elefante (overall-course-
# report) — roteia direto para o analisador da API, SEM tocar na detecção do
# upload manual (pdf/xlsx/texto), que fica intacta.
CT_ELEFANTE_API = "application/x-elefante-course-report"
# Marcador do JSON vindo da API interna do Matific (Placar da Escola). Roteia
# direto para o analisador da API, sem tocar na detecção do upload manual.
CT_MATIFIC_API = "application/x-matific-leaderboard"


def _parsear(arquivo: ArquivoObtido):
    """Detecta o formato pelos bytes (mesma regra do ``analisar``) e roteia para
    o parser certo. Devolve (analise, tipo)."""
    conteudo = arquivo.conteudo
    plataforma = arquivo.plataforma
    nome = arquivo.nome_arquivo or ""
    # Sync do Elefante pela API interna: o conteúdo é JSON do relatório de turma
    # (não um arquivo binário). Vai direto p/ o analisador da API.
    if arquivo.content_type == CT_ELEFANTE_API:
        import json
        payload = json.loads(conteudo.decode("utf-8"))
        # "texto" é o tipo aceito pelo ImportacaoConfirm (^pdf|texto|xlsx$) para
        # conteúdo não-binário; o arquivamento cai no ramo padrão.
        return svc.analisar_elefante_api(payload, plataforma or "elefante"), "texto"
    # Sync do Matific pela API interna (Placar da Escola): conteúdo é JSON já com
    # o nome completo casado; uma turma por arquivo.
    if arquivo.content_type == CT_MATIFIC_API:
        import json
        payload = json.loads(conteudo.decode("utf-8"))
        return svc.analisar_matific_api(payload), "texto"
    # Mesma detecção do upload manual (fonte única) — nunca divergem.
    tipo = svc.detectar_tipo(conteudo, nome, arquivo.content_type)
    if tipo == "pdf":
        # O mesmo teto do upload manual (descompactado, páginas, texto e desenhos —
        # ``PdfRecusado``): o PDF baixado da plataforma também vem de fora. A recusa
        # vira o mesmo erro de conector da planilha recusada (sem nova tentativa).
        try:
            return perfis_pdf.analisar_pdf(conteudo, plataforma, nome_arquivo=nome), "pdf"
        except perfis_pdf.PdfRecusado as exc:
            raise ErroConector(str(exc), codigo="parser_incompativel",
                               recuperavel=False) from exc
    if tipo == "xlsx":
        # Mesmo teto do DESCOMPRIMIDO do upload manual, antes do openpyxl (dentro de
        # ``analisar_planilha``): o arquivo vem de fora (a plataforma) e um zip de
        # poucos KB pode inflar para GB. O orçamento de leitura (dimensão declarada
        # enorme) também recusa durante a análise — mesmo destino.
        try:
            return planilhas.analisar_planilha(conteudo, plataforma,
                                               nome_arquivo=nome), "xlsx"
        except planilhas.PlanilhaRecusada as exc:
            raise ErroConector(str(exc), codigo="parser_incompativel",
                               recuperavel=False) from exc
    return svc.analisar_texto(conteudo.decode("utf-8", errors="replace"), plataforma), "texto"


def contas_dos_arquivos(arquivos) -> dict[str, set[str]]:
    """``plataforma → ids externos`` das linhas de TODOS os arquivos obtidos, lidos
    ANTES de aplicar qualquer um (decisão D8: a coleta só de contas de outra escola
    é recusada sem gravar nada). Só interpreta (o mesmo ``_parsear`` do
    ``aplicar_arquivo``), não grava. O arquivo que não se deixa interpretar fica
    de fora daqui — o ``aplicar_arquivo`` dele levanta o erro de sempre depois."""
    from app.services import identidade_aluno as ida

    contas: dict[str, set[str]] = {}
    for arquivo in arquivos or ():
        try:
            analise, _tipo = _parsear(arquivo)
        except Exception:  # noqa: BLE001 — o erro é tratado no aplicar_arquivo
            continue
        for plat, ids in ida.contas_das_linhas(
                analise.linhas, analise.plataforma or arquivo.plataforma).items():
            contas.setdefault(plat, set()).update(ids)
    return contas


def _resolver_ator(db: Session, escola_id: int, usuario_id: int | None) -> Usuario | None:
    """Ator da importação: o usuário informado (sync manual) ou o primeiro
    admin/coordenador ATIVO da escola (scheduler). Isolado por ``escola_id``."""
    if usuario_id is not None:
        u = db.get(Usuario, usuario_id)
        if u is not None and u.escola_id == escola_id:
            return u
    return db.execute(
        select(Usuario)
        .where(Usuario.escola_id == escola_id,
               Usuario.cargo.in_(("admin", "coordenador")),
               Usuario.status == "ativo")
        .order_by(Usuario.id)
    ).scalars().first()


# Aviso crítico (código estável, sem PII) do campo não essencial que sumiu da
# resposta: "campos_nao_atualizados:questoes_acertos,questoes_tentativas".
AVISO_NAO_ATUALIZADOS = "campos_nao_atualizados:"
# Os campos do retrato que as Questões do período medem: se um deles não veio, o
# retrato não mede as questões (``IMPORTACAO_SEM_QUESTOES``).
CAMPOS_QUESTOES = ("questoes_tentativas", "questoes_acertos")


def campos_nao_atualizados(analise) -> list[str]:
    """Campos do retrato fora dos essenciais da sync que SUMIRAM de todas as linhas
    do relatório (``Analise.campos_sumidos``): a resposta perdeu o campo — não é
    "sem dado". Os essenciais têm a regra própria (nada é aplicado)."""
    n = len(analise.linhas or [])
    essenciais = set(imp.CAMPOS_ESSENCIAIS_SYNC.get(
        (analise.plataforma or "", analise.formato or ""), ()))
    return sorted(c for c, q in (getattr(analise, "campos_sumidos", None) or {}).items()
                  if n and q >= n and c not in essenciais)


def _acumulado_matific(arquivo: ArquivoObtido, analise) -> bool:
    """O arquivo é o ACUMULADO do ano do Matific (``duration=this-year``)? Só
    nele um total menor que o gravado é suspeito: na coleta POR PERÍODO
    (start/end) os números são do intervalo e menor é o normal."""
    return ((analise.plataforma or arquivo.plataforma) == "matific"
            and (analise.formato or "resumo") == "resumo"
            and arquivo.periodo_inicio is None and arquivo.periodo_fim is None
            and not getattr(analise, "periodo_inicio", "")
            and not getattr(analise, "periodo_fim", ""))


def reter_quedas_matific(db: Session, escola: Escola, linhas: list,
                         contexto: Contexto) -> tuple[list, int]:
    """TRAVA CONTRA QUEDA do acumulado do Matific (coleta automática).

    O Placar com ``duration=this-year`` é um CONTADOR DO ANO por aluno
    (atividades e estrelas só sobem dentro do ano — é a mesma premissa de
    ``scoring.snapshots_matific_do_ano``). Um total MENOR que o já gravado no
    mesmo ano não é progresso: é correção da plataforma, conta trocada/zerada,
    resposta parcial — ou identidade errada. Antes, o relatório mais novo vencia
    e rebaixava o aluno em silêncio (ranking, premiação, certificado).

    Regra conservadora: a linha do aluno cuja IDENTIDADE no Matific já está
    vinculada (UUID → ficha) e cujo total novo de atividades OU estrelas é menor
    que o do retrato atual DENTRO do ano (ver a virada abaixo) NÃO é aplicada — o
    valor gravado fica, a ocorrência vai para a auditoria (sem nome: só ids e
    números) e o serviço abre o alerta 'queda_matific' para revisão humana.

    VIRADA LEGÍTIMA (documentada): o acumulado recomeça no ano novo. A base de
    comparação são só os retratos que estão AO MESMO TEMPO no ano letivo ativo
    da escola e no ano civil da COLETA (relógio de Brasília) — o ano a que o
    "this-year" do Matific se refere. Antes bastava o ano letivo ativo: em
    janeiro, com a escola ainda em 2026 (a gestão vira o ano depois), o primeiro
    acumulado de 2027 era comparado com dezembro e TODA linha ficava retida —
    coletas "sem dados", alerta para a escola inteira e nenhum retrato de
    janeiro gravado. Fora dessa interseção não há base: tudo entra. Uma queda
    real dentro do ano (correção do Matific) é aceita pela importação MANUAL do
    relatório oficial (Importações), que tem prévia e um humano olhando.

    Limitação: linha ainda sem UUID vinculado (1º encontro, casada por nome no
    /confirmar) não é conferida — não há como saber, antes da porta de
    identidade, de qual ficha ela é. Devolve ``(linhas_a_aplicar, n_retidas)``."""
    from app.models import Aluno, IdentidadeExterna, SnapshotMatific
    from app.services import matific_destaque, scoring
    from app.services.audit import registrar
    from app.sync import fuso

    por_uuid = {}
    for linha in linhas:
        uuid = str((linha.dados or {}).get("matific_uuid") or "").strip()
        if uuid:
            por_uuid.setdefault(uuid, []).append(linha)
    # uuid em CONFLITO neste arquivo (duas contas coladas no mesmo uuid: nomes ou
    # números diferentes) não é conferido aqui: TODAS as linhas dele seguem para o
    # /confirmar, que as manda para a revisão 'id_externo_duplicado'. Antes, a
    # linha abaixo do gravado era retida ANTES dessa marca e a outra, sozinha,
    # passava como se não houvesse conflito — os números dela entravam na ficha.
    from types import SimpleNamespace

    from app.services import identidade_aluno as ida
    em_conflito = {id_ext for _plat, id_ext in ida.marcar_ids_em_conflito(
        SimpleNamespace(ids_em_conflito=set()), linhas, "matific")}
    por_uuid = {u: ls for u, ls in por_uuid.items() if u not in em_conflito}
    if not por_uuid:
        return linhas, 0
    # Só conta vinculada a aluno ATIVO: a linha de uma ficha transferida (ou fora
    # da Lista Piloto, arquivada) segue para o /confirmar, que a manda para a
    # revisão como sem a queda. Antes (revisão e95) a retenção dela contava como
    # "conta da escola conferida" e a forma C do "em dia" dava em dia uma coleta
    # em que nenhuma criança ATIVA da escola veio.
    aluno_por_uuid = dict(db.execute(
        select(IdentidadeExterna.id_externo, IdentidadeExterna.aluno_id)
        .join(Aluno, Aluno.id == IdentidadeExterna.aluno_id)
        .where(
            IdentidadeExterna.escola_id == escola.id,
            IdentidadeExterna.plataforma == "matific",
            IdentidadeExterna.status != "aposentada",
            Aluno.status == "ativo",
            IdentidadeExterna.id_externo.in_(list(por_uuid)))).all())
    if not aluno_por_uuid:
        return linhas, 0
    ano_coleta = fuso.hoje_local().year
    ano = escola.ano_letivo_ativo or ano_coleta
    # janela_ano_letivo é jan–dez: aplicada ao ano da coleta, é o ano CIVIL dela.
    inicio_civil, fim_civil = matific_destaque.janela_ano_letivo(ano_coleta)
    janela = matific_destaque.janela_efetiva(inicio_civil, fim_civil, ano)
    if janela is None:
        return linhas, 0
    atuais = {s.aluno_id: s for s in db.execute(
        select(SnapshotMatific).where(
            SnapshotMatific.id.in_(scoring.ids_snapshots_atuais(
                SnapshotMatific, escola.id, janela=janela)),
            SnapshotMatific.aluno_id.in_(list(aluno_por_uuid.values())))).scalars()}

    retidas: set[int] = set()
    for uuid, aluno_id in aluno_por_uuid.items():
        atual = atuais.get(aluno_id)
        if atual is None:
            continue
        for linha in por_uuid[uuid]:
            dados = linha.dados or {}
            caiu = [campo for campo in ("atividades", "estrelas")
                    if campo in dados and dados[campo] is not None
                    and int(dados[campo]) < int(getattr(atual, campo) or 0)]
            if not caiu:
                continue
            retidas.add(id(linha))
            registrar(db, "sync.matific_queda_retida", escola_id=escola.id,
                      entidade="aluno", entidade_id=aluno_id,
                      detalhes={campo: {"gravado": int(getattr(atual, campo) or 0),
                                        "recebido": int(dados[campo])}
                                for campo in caiu}
                      | {"snapshot_id": atual.id, "ano_letivo": ano})
    if retidas:
        contexto.log("validacao", "warn",
                     f"{len(retidas)} aluno(s) com total do Matific MENOR que o já "
                     "gravado no ano: valores mantidos, enviados para revisão.")
    return [linha for linha in linhas if id(linha) not in retidas], len(retidas)


def aplicar_arquivo(db: Session, escola: Escola, arquivo: ArquivoObtido, *,
                    usuario_id: int | None, recalcular: bool,
                    contexto: Contexto) -> dict:
    """Interpreta e importa UM arquivo obtido, reusando ``confirmar``.

    Retorna contadores (qtd_alunos, qtd_erros, qtd_turmas, importacao_id, avisos,
    sem_dados, retidos_queda, verificou_queda) para o histórico da execução e a
    CONTABILIDADE que decide o status (sem PII): ``alunos_aplicados_ids`` (dado
    que mudou de fato), ``conferidos_sem_mudanca`` (alunos com ficha cujo dado veio
    igual), ``turmas`` (rótulos distintos recebidos), ``linhas``
    (recebidas, inclusive as descartadas), ``em_revisao``, ``descartadas``
    (motivo → n), ``avisos_criticos`` e ``parser_incompativel`` (o arquivo não foi
    aplicado porque a resposta perdeu um campo essencial)."""
    # NÃO logar o nome do arquivo: relatórios individuais trazem o nome do aluno
    # (PII de menor) no nome, e o log é retido (LGPD/§14 — mesma política do
    # upload manual em routers/importacoes.py). Logamos só a plataforma.
    contexto.log("parser", "info", f"Interpretando relatório da {arquivo.plataforma}…")
    analise, tipo = _parsear(arquivo)
    descartadas_parser = {k: int(v) for k, v in (getattr(analise, "descartadas", None)
                                                 or {}).items() if v}
    n_descartadas = sum(descartadas_parser.values())
    # Os avisos da interpretação (ex.: "Campos ausentes…") só existiam na resposta
    # do upload manual: na sync sumiam. Vão para o log (só campos e contagens).
    for aviso in getattr(analise, "erros_gerais", None) or []:
        contexto.log("parser", "warn", str(aviso)[:900])
    if descartadas_parser:
        contexto.log("parser", "warn",
                     f"{n_descartadas} linha(s) da plataforma não viraram dado: "
                     + ", ".join(f"{m}={n}" for m, n in sorted(descartadas_parser.items()))
                     + ".")
    base_res = {"qtd_alunos": 0, "qtd_erros": 0, "qtd_turmas": 0, "importacao_id": None,
                "ignorados": [], "alunos_aplicados_ids": [], "turmas": [],
                "em_revisao": 0, "avisos_criticos": [], "parser_incompativel": False}
    retidos, verificou = 0, False
    if analise.linhas and _acumulado_matific(arquivo, analise):
        analise.linhas, retidos = reter_quedas_matific(db, escola, analise.linhas, contexto)
        verificou = True
    if not analise.linhas:
        contexto.log("parser", "warn",
                     "Nenhuma linha reconhecida no relatório obtido." if not retidos
                     else "Nenhuma linha aplicada: todas ficaram retidas para revisão.")
        # Linha RETIDA por queda não é revisão de identidade (não há pendência na
        # fila): conta como linha recebida e em ``retidos_queda`` — o serviço dá o
        # motivo 'queda_retida' e o alerta 'queda_matific'.
        return {**base_res, "avisos": ["Relatório sem linhas."],
                "sem_dados": True, "retidos_queda": retidos,
                "verificou_queda": verificou,
                "linhas": retidos + n_descartadas, "descartadas": descartadas_parser}

    # Resposta da API que perdeu um campo ESSENCIAL em TODAS as linhas (campo
    # renomeado/removido): nada é aplicado — o retrato herdaria o valor antigo
    # com a data de hoje. Erro de interpretação, com alerta crítico no serviço.
    if arquivo.content_type in (CT_ELEFANTE_API, CT_MATIFIC_API):
        validas, ausentes = imp.campos_essenciais_ausentes(
            analise.plataforma or arquivo.plataforma, analise.formato or "resumo",
            analise.linhas)
        if ausentes and not validas:
            n = len(analise.linhas)
            contexto.log("parser", "error",
                         f"Resposta da plataforma sem {', '.join(ausentes)} em todas as "
                         f"{n} linha(s): nada aplicado ({AJUSTE_DA_COLETA}).")
            return {**base_res, "avisos": [], "sem_dados": True, "retidos_queda": retidos,
                    "verificou_queda": verificou,
                    "linhas": n + retidos + n_descartadas,
                    "descartadas": {**descartadas_parser, "campos_ausentes": n},
                    "avisos_criticos": ["campos_ausentes:" + ",".join(ausentes)],
                    "parser_incompativel": True}

    # S9: campo NÃO essencial (tempo, questões do Elefante) que sumiu de TODAS as
    # linhas — renomeado na API. Os livros entram (nada é destruído), mas a coleta
    # não sai 'concluida' calada: o serviço a fecha 'parcial' (ou sem atualização)
    # com o alerta crítico, e quem não mudou não ganha retrato repetido com a data
    # de hoje (as Questões do período o leriam como "0 no período").
    nao_atualizados = campos_nao_atualizados(analise) \
        if arquivo.content_type == CT_ELEFANTE_API else []
    perdidos_na_execucao = getattr(contexto, "campos_nao_atualizados", None)
    if nao_atualizados:
        contexto.log("parser", "error",
                     f"Resposta da plataforma sem {', '.join(nao_atualizados)} em todas as "
                     f"{len(analise.linhas)} linha(s): esses números ficam com o valor da "
                     f"coleta anterior ({AJUSTE_DA_COLETA}).")
        if isinstance(perdidos_na_execucao, set):
            perdidos_na_execucao.update(nao_atualizados)
    # As LEITURAS copiam tempo/questões do retrato atual quando nasce um retrato novo:
    # depois de um resumo sem esses campos, também não repetem números de antes.
    sem_retrato_repetido = bool(nao_atualizados) or (
        arquivo.content_type == CT_ELEFANTE_API and bool(perdidos_na_execucao))
    # Quem MUDOU (livro novo) ganha retrato com as questões da coleta anterior e a
    # data de agora; as Questões do período o leriam como "0 no período" com
    # cobertura completa. A importação é marcada e esses retratos deixam de ser
    # borda das questões. O resumo decide pelo próprio arquivo; as leituras (que
    # copiam as questões do retrato do dia) pela execução.
    questoes_herdadas = arquivo.content_type == CT_ELEFANTE_API and bool(
        set(CAMPOS_QUESTOES) & (set(perdidos_na_execucao or ())
                                if (analise.formato or "") == "leituras"
                                else set(nao_atualizados)))

    contexto.log("validacao", "info",
                 f"{len(analise.linhas)} linha(s); identificando alunos…")

    # Arquiva a fonte no MESMO diretório temporário do upload manual (o
    # confirmar move para a pasta definitiva — trilha/§15 LGPD idêntica).
    token = imp._guardar_temporario(arquivo.conteudo, tipo if tipo in ("pdf", "xlsx") else "pdf")

    turmas_novas = set()
    linhas: list[LinhaConfirmacao] = []
    for l in analise.linhas:
        # A sync é NÃO SUPERVISIONADA e NÃO tem atalho próprio de identidade: toda
        # linha vai sem aluno fixado para o /confirmar, que aplica a PORTA ÚNICA
        # (identidade_aluno.decidir — a mesma da prévia): identidade externa
        # (UUID/studentId) → RA → sala (nome idêntico, candidato único estrutural)
        # → revisão → criação só sem candidato. Linha ambígua não é descartada:
        # vai para a fila de revisão de identidade.
        turma_nome = str((l.dados or {}).get("turma_relatorio") or analise.turma_detectada or "")
        if turma_nome:
            turmas_novas.add(turma_nome)
        linhas.append(LinhaConfirmacao(nome=l.nome, dados=l.dados,
                                       criar_em_turma_nome=turma_nome or None))

    confirm = ImportacaoConfirm(
        plataforma=analise.plataforma or arquivo.plataforma,
        formato=analise.formato or arquivo.formato_hint or "resumo",
        tipo=tipo,
        arquivo_token=token,
        arquivo_nome=arquivo.nome_arquivo,
        periodo_inicio=arquivo.periodo_inicio,
        periodo_fim=arquivo.periodo_fim,
        linhas=linhas,
        recalcular=recalcular,
        sincronizar_turma=True,   # sync automática: pode mover de turma (com segurança;
                                  # com a política 'bloquear', não move — P15)
        permitir_criar_turma=False,  # gate anti-turma-fantasma (item 4): a sync NUNCA
                                     # cria turma fora do cadastro a partir do rótulo da
                                     # plataforma — turma desconhecida vira aviso/pendência.
        # FONTE DE VERDADE DA MATRÍCULA: a escola declara se a sincronização pode
        # criar ficha de criança. Escola sem política configurada responde True —
        # comportamento idêntico ao de antes. Com ``bloquear``, a linha sem
        # candidato seguro vira pendência de revisão em vez de ficha nova.
        permitir_criar_aluno=politica_sync.pode_criar_aluno(db, escola.id),
    )

    ator = _resolver_ator(db, escola.id, usuario_id)
    if ator is None:
        raise RuntimeError(
            "A escola não tem admin/coordenador ativo para atribuir a "
            "importação automática.")

    contexto.log("importacao", "info",
                 f"Aplicando {len(linhas)} linha(s) pelo pipeline existente…")
    try:
        resultado = imp.confirmar(
            dados=imp.confirmacao_da_sincronizacao(
                confirm, sem_retrato_repetido=sem_retrato_repetido,
                questoes_herdadas=questoes_herdadas),
            escola_id=escola.id, usuario=ator, db=db)
    except HTTPException as exc:
        # A importação RECUSOU o pedido (ex.: intervalo de datas inválido). Não é
        # "falha inesperada" recuperável ("erro do nosso lado"): é o pedido — não
        # adianta tentar de novo igual.
        periodo = arquivo.periodo_inicio is not None or arquivo.periodo_fim is not None
        raise ErroConector(
            f"A importação recusou o relatório: {exc.detail}",
            codigo="periodo_invalido" if periodo else "parser_incompativel",
            recuperavel=False) from exc
    contexto.log("ranking", "info",
                 f"{resultado.qtd_alunos} aluno(s) atualizado(s)"
                 + (" e notas recalculadas." if recalcular else "."))

    # Cria automaticamente a conta de login dos PROFESSORES da turma detectada
    # (login = NomeSobrenome; a conta nasce SEM senha conhecida — o primeiro
    # acesso é pelo link de redefinição gerado pela gestão em Usuários) e
    # vincula o titular para o RBAC. Acessório e idempotente: roda numa transação própria (o
    # confirmar já commitou os alunos) e NUNCA derruba a sync se falhar.
    professor_txt = getattr(analise, "professor_detectado", "") or ""
    turma_txt = getattr(analise, "turma_detectada", "") or ""
    if professor_txt and turma_txt:
        try:
            turma_obj = db.execute(
                select(Turma).where(
                    Turma.escola_id == escola.id,
                    func.lower(Turma.nome) == turma_txt.strip().lower())
            ).scalars().first()
            n_prof = professores.garantir_professores_da_turma(
                db, escola.id, turma_obj, professor_txt)
            db.commit()
            if n_prof:
                contexto.log("professores", "info",
                             f"{n_prof} conta(s) de professor criada(s) "
                             "automaticamente (usuário = NomeSobrenome), sem "
                             "senha: para o primeiro acesso, a gestão gera o "
                             "link de redefinição em Usuários.")
        except Exception:  # noqa: BLE001 — professor é acessório; aluno é o essencial
            db.rollback()
            contexto.log("professores", "warn",
                         "Não foi possível criar as contas de professor da turma.")
    # Surfaça (SEM PII — só a contagem) linhas não casadas/ignoradas, para o gestor
    # perceber alunos que ficaram de fora em vez de sumirem em silêncio.
    if resultado.avisos:
        contexto.log("validacao", "warn",
                     f"{len(resultado.avisos)} aviso(s): linhas não casadas ou "
                     "ignoradas nesta turma (ver detalhes na importação).")
    linhas_revisao = int(getattr(resultado, "linhas_em_revisao", 0) or 0)
    # "Em revisão" na execução = CONTAS distintas (uma criança sem ficha com 5
    # livros é 1, não 6 — a tela mostra esse número com destaque).
    em_revisao = int(getattr(resultado, "contas_em_revisao", 0) or 0) or linhas_revisao
    if linhas_revisao or getattr(resultado, "qtd_revisoes", 0):
        contexto.log("validacao", "warn",
                     f"{linhas_revisao} linha(s) de {em_revisao} conta(s) foram para a fila "
                     f"de revisão de identidade ({getattr(resultado, 'qtd_revisoes', 0)} "
                     "pendência(s)).")
    descartadas = dict(descartadas_parser)
    for motivo, n in (getattr(resultado, "linhas_descartadas", None) or {}).items():
        descartadas[motivo] = descartadas.get(motivo, 0) + int(n or 0)
    aplicados_ids = list(getattr(resultado, "alunos_aplicados_ids", None) or [])
    return {
        "qtd_alunos": resultado.qtd_alunos,
        "qtd_erros": resultado.qtd_erros,
        "qtd_turmas": len(turmas_novas),
        "importacao_id": resultado.importacao_id,
        "avisos": resultado.avisos,
        # Linhas sem aluno vinculado: o serviço NÃO avança o cursor incremental
        # desses alunos (a próxima sync retenta) e a pendência fica auditada.
        "ignorados": list(getattr(resultado, "ignorados", None) or []),
        "sem_dados": False,
        "retidos_queda": retidos,
        "verificou_queda": verificou,
        "alunos_aplicados_ids": aplicados_ids,
        # Alunos com ficha que a importação resolveu e cujo dado veio IGUAL ao
        # gravado: ``qtd_alunos`` do /confirmar é ``len(resolvidos)``; os que não
        # mudaram são a diferença — a mesma conta do "N aluno(s) conferido(s) sem
        # mudança" da importação manual. Decide se uma coleta só de pendências
        # conferiu a escola (forma C do "em dia", ``service.decidir_status``).
        "conferidos_sem_mudanca": max(0, int(resultado.qtd_alunos or 0) - len(aplicados_ids)),
        "turmas": sorted(turmas_novas),
        "linhas": (int(getattr(resultado, "linhas_recebidas", 0) or len(linhas))
                   + retidos + n_descartadas),
        "em_revisao": em_revisao,
        "descartadas": descartadas,
        "avisos_criticos": (list(getattr(resultado, "avisos_criticos", None) or [])
                            + ([AVISO_NAO_ATUALIZADOS + ",".join(nao_atualizados)]
                               if nao_atualizados else [])),
        "parser_incompativel": False,
        # Contas já efetivas em OUTRA escola do Constela (revisão própria): o
        # serviço abre o alerta crítico 'identidade_de_outra_escola'.
        "ids_de_outra_escola": list(getattr(resultado, "ids_de_outra_escola", None) or []),
    }
