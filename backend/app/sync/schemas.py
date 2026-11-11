"""Schemas (Pydantic) da API do módulo de sincronização."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- entrada ----------------------------------------------------------------
# Opções avançadas que a credencial aceita (o que os conectores leem dela):
#   url_login — endereço da página de login. O Chromium do SERVIDOR abre esse
#               endereço: só https e host do site de uma plataforma (domínios de
#               cada conector, ``dominios_login``). O conector confere de novo,
#               contra o domínio DELE, antes de abrir (credenciais já gravadas).
#   sso       — "google": conta só com login social (o Elefante recusa claro).
# As datas do período (matific_*) NÃO entram por aqui: a rota de sincronizar por
# período as valida e o serviço as junta à credencial só durante a execução.
CHAVES_EXTRA = frozenset({"url_login", "sso"})
_SSO_MAX = 40


def _sites_das_plataformas() -> list[tuple[str, tuple[str, ...]]]:
    """[(plataforma, domínios)] dos conectores que aceitam endereço de login."""
    from app.sync import connectors   # tardio: o registro importa os conectores
    return [(c.plataforma, tuple(getattr(c, "dominios_login", ()) or ()))
            for c in connectors.listar() if getattr(c, "dominios_login", ())]


class CredenciaisIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=200)
    senha: str = Field(min_length=1, max_length=300)
    extra: dict = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _extra_conhecido(cls, valor: dict) -> dict:
        # A mensagem não repete o que veio (chave ou endereço): diz o que vale.
        if set(valor) - CHAVES_EXTRA:
            raise ValueError("Opção avançada não reconhecida. Só são aceitos o endereço "
                             "de login (url_login) e o tipo de login social (sso).")
        limpo: dict = {}
        sso = valor.get("sso")
        if sso is not None:
            if not isinstance(sso, str) or len(sso.strip()) > _SSO_MAX:
                raise ValueError("Opção ‘sso’ inválida: use um texto curto (ex.: google).")
            if sso.strip():
                limpo["sso"] = sso.strip()
        url = valor.get("url_login")
        if url is not None:
            from app.sync.connectors.base import url_na_lista
            url = url.strip() if isinstance(url, str) else url
            if url != "":
                sites = _sites_das_plataformas()
                if not url_na_lista(url, [d for _, dominios in sites for d in dominios]):
                    lista = " ou ".join(
                        f"{', '.join(dominios)} ({plataforma.capitalize()})"
                        for plataforma, dominios in sites)
                    raise ValueError(
                        "Endereço de login não aceito. Ele precisa começar com https:// "
                        f"e ser do site da plataforma: {lista}. Deixe em branco para "
                        "usar o endereço oficial.")
                limpo["url_login"] = url
        return limpo


class ConfigIn(BaseModel):
    ativo: bool = False
    cadencia: str = Field(default="manual", pattern="^(manual|diaria|semanal)$")
    # Horário de BRASÍLIA (o agendador converte para UTC ao calcular a próxima).
    hora_local: str = Field(default="03:00", pattern=r"^\d{2}:\d{2}$")
    dia_semana: int | None = Field(default=None, ge=0, le=6)

    @field_validator("hora_local")
    @classmethod
    def _hora_valida(cls, valor: str) -> str:
        # O padrão aceita "25:99"; o cálculo da próxima execução estourava (500).
        hh, mm = (int(x) for x in valor.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("Horário inválido: use HH:MM entre 00:00 e 23:59.")
        return valor


class EscolaExternaIn(BaseModel):
    """Escolha EXPLÍCITA da escola da plataforma que esta escola é (conta que
    enxerga várias, ou troca de conta de propósito). ``id_externo``: o
    ``schoolId`` do Elefante (número) ou o ``school_id`` do Matific (uuid), como o
    "Testar conexão" mostra. Sem segredo."""
    id_externo: str = Field(min_length=1, max_length=80)
    nome: str = Field(default="", max_length=200)


# --- saída ------------------------------------------------------------------
class ResultadoTeste(BaseModel):
    ok: bool
    mensagem: str
    codigo: str | None = None
    # ESCOLA EXTERNA (sem segredo), para o gestor conferir a credencial: as
    # escolas que a conta enxerga ([{id, nome}]; None = não verificado), o vínculo
    # atual desta escola, se ele confere (None = não dá para dizer) e um aviso.
    escolas_externas: list[dict] | None = None
    escola_vinculada: dict | None = None
    escola_confere: bool | None = None
    aviso_escola: str | None = None


class EscolaExternaOut(BaseModel):
    plataforma: str
    vinculada: bool
    id_externo: str | None = None
    nome: str | None = None
    origem: str | None = None        # aprendido | explicito
    definido_em: str | None = None


class ExecucaoOut(_ORM):
    id: int
    plataforma: str
    origem: str
    usuario_id: int | None
    status: str
    iniciada_em: datetime | None
    finalizada_em: datetime | None
    duracao_ms: int
    qtd_alunos: int
    qtd_turmas: int
    qtd_alteracoes: int
    qtd_arquivos: int
    qtd_erros: int
    parser_versao: str | None
    conector_versao: str | None
    tentativa: int
    erro_resumo: str | None
    created_at: datetime
    # Contabilidade honesta (0039). None = execução anterior, que não mediu.
    qtd_linhas: int | None = None        # linhas recebidas da plataforma
    qtd_em_revisao: int | None = None    # contas distintas enviadas à revisão
    qtd_falhas: int | None = None        # unidades (turma/lote/aluno/endpoint/arquivo) com falha
    recalculo_pendente: bool = False     # dado gravado, recálculo das notas pendente/falhou
    # Por que o status: 'nada_mudou' | 'correspondencia_pendente' | 'tudo_em_revisao'
    # (tudo em revisão e nenhuma conta da escola conferida: não é "em dia") |
    # 'fora_do_ano_sem_conferencia' (coleta de fora do ano letivo ativo, linhas deixadas
    # para depois da virada e nenhuma conta da escola conferida: não é "em dia") |
    # 'queda_retida' | 'falha_apos_gravacao' | 'coleta_parcial' | 'linhas_descartadas'
    # | código do erro ('sem_acesso_ao_dado', 'falha_download', 'parser_incompativel'…)
    motivo: str | None = None
    # Período pedido (coleta do Matific por período): {inicio, fim} em AAAA-MM-DD,
    # dos parâmetros da execução. None = coleta do acumulado.
    periodo: dict | None = Field(default=None, validation_alias="parametros")

    @field_validator("periodo", mode="before")
    @classmethod
    def _periodo_dos_parametros(cls, valor):
        if not isinstance(valor, dict):
            return None
        inicio = valor.get("matific_start_date")
        fim = valor.get("matific_end_date")
        if not inicio and not fim:
            return None
        return {"inicio": inicio or None, "fim": fim or None}


class ExecucaoAgoraOut(ExecucaoOut):
    """Resposta do "Sincronizar agora": a execução de cada plataforma pedida."""
    # True: o pedido se juntou a uma execução que JÁ EXISTIA (na fila ou
    # executando — ver ``status`` e ``iniciada_em``) e nenhuma coleta nova foi
    # criada para ela. False: a execução foi criada por este pedido.
    reaproveitada: bool = False


class LogOut(_ORM):
    id: int
    execucao_id: int
    etapa: str
    nivel: str
    mensagem: str
    created_at: datetime


class AlertaOut(_ORM):
    id: int
    plataforma: str | None
    tipo: str
    severidade: str
    mensagem: str
    resolvido: bool
    resolvido_em: datetime | None
    created_at: datetime


class PlataformaStatus(BaseModel):
    plataforma: str
    estrategia: str
    conectada: bool                     # credencial válida
    # nao_configurada | nao_validada | valida | invalida | expirada | ilegivel (a cifra
    # não abre com as chaves do servidor: recadastrar; derivado, nunca gravado)
    credencial_status: str
    validada_em: datetime | None = None
    ultimo_erro: str | None = None
    agendada: bool = False
    cadencia: str = "manual"
    hora_local: str = "03:00"
    dia_semana: int | None = None
    proxima_execucao: datetime | None = None
    # A execução mais RECENTE, em qualquer estado (fila, em andamento, …).
    ultima_execucao: ExecucaoOut | None = None
    # A última TENTATIVA que terminou (concluída, sem dados ou erro) — não é o
    # mesmo que o último sucesso: uma falha hoje não apaga o sucesso de ontem, e
    # um sucesso de semanas atrás não diz que a coleta funciona hoje.
    ultima_tentativa: ExecucaoOut | None = None
    # Blindagem: "os dados estão envelhecendo em silêncio?" — quando foi a última
    # sincronização BEM-SUCEDIDA e se já passou do limite da cadência.
    ultimo_sucesso_em: datetime | None = None
    # Última vez que a integração foi VERIFICADA (dado aplicado, plataforma vazia
    # de verdade ou coleta completa em que nada mudou) — verificar ≠ atualizar.
    ultima_verificacao_em: datetime | None = None
    # Status e motivo da última TENTATIVA (concluida | parcial | sem_atualizacao |
    # sem_dados | erro) — a tela diz "nada mudou" × "ficou em revisão" × "falhou".
    ultimo_status: str | None = None
    ultimo_motivo: str | None = None
    # Há dado gravado esperando um recálculo de notas que falhou?
    recalculo_pendente: bool = False
    # Período de 1 dia (início = fim) só com a semântica do end_date do Matific
    # confirmada (MATIFIC_END_DATE): a tela desabilita quando False.
    periodo_um_dia_permitido: bool = False
    desatualizada: bool = False
    # FRESCOR do dado (vale também sem agenda): 'atualizado' | 'desatualizado' |
    # 'sem_sucesso', a idade do último sucesso e o limite usado (em horas).
    frescor: str = "sem_sucesso"
    idade_horas: int | None = None
    limite_horas: int | None = None
    # Que tipo de falha explica o estado (None = sem falha): 'autenticacao' |
    # 'indisponibilidade_externa' | 'processamento' | 'indisponivel' | 'configuracao'.
    falha_categoria: str | None = None
    # A execução mais recente está na fila esperando um agendador que está
    # desligado — não vai rodar sozinha (a tela não diz "Sincronizando").
    fila_parada: bool = False
    # Contagens HONESTAS da cobertura dos dados — cada número é um COUNT do banco,
    # nada é inferido. Universo: alunos ATIVOS matriculados no ano letivo ativo.
    # `None` = NÃO DÁ PARA CONTAR (plataforma sem tabela de snapshot ou escola
    # sem ano letivo ativo) — diferente de `0`, que é "contei e não há ninguém".
    alunos_com_dados: int | None = None  # com ≥1 snapshot desta plataforma
    alunos_sem_dados: int | None = None  # sem nenhum snapshot desta plataforma
    # Só Elefante: snapshot ATUAL com livros_unicos == 0 ("usa e ainda não
    # produziu" — um zero legítimo, diferente de "sem dado"). Matific: None.
    alunos_com_zero_registros: int | None = None
    # Frescor do dado dos alunos PONTUADOS: max(data_referencia) só dos snapshots
    # de alunos do MESMO universo acima (ativos + matriculados no ano ativo). Um
    # arquivado ou um aluno de outro ano não pode fazer a integração parecer em
    # dia. None = sem snapshot no universo (ou não dá para contar).
    dado_mais_recente_em: datetime | None = None
    # VÍNCULO da escola externa ({id, nome, origem, definido_em}; None = ainda não
    # aprendido): qual escola da plataforma esta escola é — sem segredo.
    escola_externa: dict | None = None


class EscolaStatus(BaseModel):
    escola_id: int
    escola_nome: str
    qtd_alunos: int      # ativos e matriculados no ano letivo ativo (como /alunos)
    qtd_turmas: int      # turmas do ano letivo ativo, não arquivadas (como /turmas)
    plataformas: list[PlataformaStatus]
    alertas_abertos: int
    # Estado do onboarding (fluxo "escola pronta em <5 min").
    lista_piloto_importada: bool = False   # já tem turmas cadastradas (qualquer ano)?
    integracao_configurada: bool = False   # já salvou ≥1 credencial de plataforma?
    # O agendador automático está ligado NESTE servidor? Desligado, a agenda da
    # escola continua "ativa" mas nada roda sozinho — a tela precisa dizer isso.
    agendador_ativo: bool = False
    # Pendências de CORRESPONDÊNCIA dos últimos 30 dias (LogAuditoria com
    # `aluno.revisao_necessaria` ou `importacao.linha_ignorada`): o que a escola
    # precisa revisar para a integração ficar íntegra. 0 = nada pendente.
    pendencias_correspondencia_30d: int = 0


class EscolaOnboarding(BaseModel):
    """GET /sync/onboarding: só o sinal do "Comece aqui" (a barra lateral), o
    mesmo ``lista_piloto_importada`` do ``EscolaStatus`` sem o resto dele."""
    lista_piloto_importada: bool = False


class DashboardOut(BaseModel):
    escolas_total: int
    escolas_configuradas: int
    escolas_sincronizadas: int
    escolas_com_erro: int
    escolas_desatualizadas: int = 0   # dado envelhecendo em silêncio (sem sucesso há X)
    em_andamento: int
    fila: int
    workers_ativos: int
    scheduler_ligado: bool
    ultima_sincronizacao: datetime | None
    duracao_ultima_ms: int | None
    tempo_medio_ms: int | None
    alertas_abertos: int
