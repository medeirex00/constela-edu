"""Schemas do fluxo de importação (PRD §15–§16, §50–§52)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.comum import ORMModel


class CorrespondenciaOut(BaseModel):
    status: str  # exato | vinculado | revisar | bloqueado | nao_encontrado
    aluno_id: int | None = None
    aluno_nome: str | None = None
    similaridade: float | None = None
    # O MOTIVO da decisão do motor (``services.importacao._correspondencia``): na
    # revisão, o de ``identidade_aluno.MOTIVOS`` (nome_incompleto,
    # contas_repetidas_no_relatorio…), que a tela usa para mandar a linha para
    # Revisões de identidade em vez de "Criar"; no vínculo, o mesmo que ``via``; sem
    # candidato, "novo" ou "conflito". Sem o campo aqui, o Pydantic o descartava e a
    # tela nunca o recebia.
    motivo: str | None = None
    via: str | None = None          # como casou (identidade|exato|ra|abreviacao|…)
    alternativas: list[dict] = []
    # ONDE A FICHA NOVA NASCE (status "nao_encontrado"/"bloqueado") — a decisão da
    # porta única (``identidade_aluno._turma_para_criar``), para a tela não
    # adivinhar a turma pelo nome:
    #   * ``turma_id``/``turma_nome``: a turma cadastrada que recebe a ficha — a tela
    #     manda ``criar_em_turma_id`` = ``turma_id``;
    #   * ``turma_nova``: a sala do relatório não tem turma no cadastro, e a
    #     confirmação cria uma com este nome — a tela manda ``criar_em_turma_nome``
    #     = a turma do RELATÓRIO como veio (``dados.turma_relatorio`` ou
    #     ``turma_detectada``), não este nome curto (dele sai a etapa da turma);
    #   * os três nulos: a linha não cria ficha (vínculo ou revisão) ou o relatório
    #     não informa turma — aí a tela pede a turma.
    turma_id: int | None = None
    turma_nome: str | None = None
    turma_nova: str | None = None


class LinhaAnaliseOut(BaseModel):
    numero: int
    nome: str
    dados: dict
    erros: list[str]
    avisos: list[str]
    correspondencia: CorrespondenciaOut | None


class AnaliseOut(BaseModel):
    plataforma: str
    formato: str
    tipo: str  # pdf | texto
    arquivo_token: str | None
    arquivo_nome: str | None
    estrategia: str = ""            # tabela | cabecalho_vertical | rotulos | posicional
    mensagem_deteccao: str = ""     # "Este arquivo pertence ao Matific."
    turma_detectada: str = ""       # turma lida do PDF (cabeçalho do Elefante)
    # Escola lida do relatório (cabeçalho do PDF / schoolName do Elefante) e o
    # AVISO quando o nome não parece o da escola cadastrada (só aviso: nomes variam).
    escola_detectada: str = ""
    aviso_escola: str = ""
    origem_nome: str = ""           # arquivo | conteudo | nenhum (como o nome foi achado)
    # "Intervalo de datas" impresso no relatório (Matific): datas ISO. O
    # frontend devolve estes valores no /confirmar para datar os dados.
    periodo_inicio: str = ""
    periodo_fim: str = ""
    # A política da escola é 'bloquear' (a matrícula vem da Lista Piloto): o
    # /confirmar NÃO cria ficha para quem não casa — a linha vai para a Revisão de
    # identidade. A prévia avisa ANTES de o gestor escolher "criar".
    criacao_bloqueada_por_politica: bool = False
    total_alunos: int = 0           # nomes únicos encontrados
    total_linhas: int
    total_erros: int
    total_avisos: int = 0
    erros_gerais: list[str]
    linhas: list[LinhaAnaliseOut]


class LinhaConfirmacao(BaseModel):
    nome: str
    dados: dict
    aluno_id: int | None = None
    criar_em_turma_id: int | None = None
    # Nome de turma AINDA INEXISTENTE (a lida do PDF): a confirmação cria a
    # turma uma única vez e matricula o aluno nela — primeiro import da escola
    # funciona sem cadastrar turmas antes.
    criar_em_turma_nome: str | None = None
    # COMO o aluno foi identificado (uuid|exato|provavel): a sincronização usa
    # para só mover de turma quem casou com segurança (só vem da sync automática).
    via: str | None = None
    # "Deixar para a Revisão" (escolha de quem confirma, na prévia): a linha NUNCA
    # associa nem cria — vai para a Revisão de identidade com o motivo que o backend
    # achar, ou, se para ele a linha associaria ou criaria (o contexto mudou desde a
    # prévia: outra conta ignorada, outra linha fixada…), com o motivo
    # ``deixada_para_revisao``. Antes a tela mandava o mesmo corpo de um "Criar" e
    # confiava que a confirmação repetiria a prévia. Os campos de turma continuam
    # valendo como contexto da pendência (a turma do relatório pelo nome, como a
    # prévia a leu). A sincronização não manda.
    deixar_para_revisao: bool = False


class ImportacaoConfirm(BaseModel):
    plataforma: str = Field(pattern="^(matific|elefante)$")
    formato: str = Field(pattern="^(resumo|leituras)$")
    tipo: str = Field(pattern="^(pdf|texto|xlsx)$")
    arquivo_token: str | None = None
    arquivo_nome: str | None = None
    data_referencia: datetime | None = None
    # Intervalo do relatório (Matific "Intervalo de datas"): quando presente,
    # os valores das linhas são SOMADOS ao acumulado anterior ao início e o
    # snapshot é datado dentro do intervalo (rankings por período corretos).
    periodo_inicio: datetime | None = None
    periodo_fim: datetime | None = None
    linhas: list[LinhaConfirmacao]
    # No lote, cada arquivo confirma com recalcular=False; o recálculo roda
    # uma vez ao final via POST /recalcular.
    recalcular: bool = True
    # Sincronização AUTOMÁTICA (não upload manual): autoriza mover a matrícula do
    # aluno quando a turma do Matific muda. Só o orquestrador liga isto — o
    # upload manual pela tela NUNCA move turma sozinho.
    sincronizar_turma: bool = False
    # Permite CRIAR turma que não existe no cadastro a partir do rótulo da
    # plataforma. Default True = importação MANUAL (opt-in explícito do gestor). A
    # sincronização automática passa False (gate anti-turma-fantasma): turma
    # desconhecida NÃO é criada, vira aviso; só a Lista Piloto e o manual criam.
    permitir_criar_turma: bool = True
    # Permite CRIAR a FICHA DO ALUNO quando a linha não casa com ninguém.
    # Padrão (None) = a POLÍTICA da escola (``services/politica_sync``), no upload
    # manual de relatório de plataforma e na sincronização: numa escola cuja
    # matrícula vem da Lista Piloto ('bloquear'), a plataforma não é fonte de
    # matrícula e a linha sem candidato seguro vira PENDÊNCIA DE REVISÃO
    # ('criacao_bloqueada_por_politica') em vez de ficha nova. ``False`` nunca
    # cria; ``True`` NÃO fura 'bloquear' (a política é do Admin Global). Escola
    # sem política ('permitir') cria, como sempre. A Lista Piloto (/matriculas)
    # não passa por aqui: ela É a fonte.
    permitir_criar_aluno: bool | None = None


class ImportacaoOut(ORMModel):
    id: int
    plataforma: str
    tipo: str
    arquivo_original: str | None
    qtd_alunos: int
    qtd_erros: int
    tempo_ms: int
    status: str
    created_at: datetime
    usuario_nome: str | None = None


class ImportacaoResultadoOut(BaseModel):
    mensagem: str
    importacao_id: int
    qtd_alunos: int
    qtd_erros: int
    avisos: list[str] = []
    # Nomes (normalizados) das linhas que NÃO puderam ser vinculadas a um aluno
    # (correspondência insegura / sem vínculo). Nunca silêncio: a sync desfaz o
    # cursor desses alunos e retenta; a tela lista a pendência.
    ignorados: list[str] = []
    # Pendências abertas/atualizadas na fila de revisão de identidade por esta
    # importação (linhas preservadas, não associadas nem criadas).
    qtd_revisoes: int = 0
    # Contabilidade da importação (a sincronização decide o status por ela):
    # alunos cujo dado MUDOU de fato, linhas recebidas, linhas que foram para a
    # fila de revisão, linhas que não viraram dado (motivo → n) e avisos
    # críticos em código estável, sem nome de aluno (ex.: 'campos_ausentes:x').
    alunos_aplicados_ids: list[int] = []
    linhas_recebidas: int = 0
    linhas_em_revisao: int = 0
    linhas_descartadas: dict[str, int] = {}
    avisos_criticos: list[str] = []
    # Contas DISTINTAS que foram para a revisão (uma criança com 5 livros = 1).
    contas_em_revisao: int = 0
    # Contas (id da plataforma) que já são EFETIVAS em OUTRA escola do Constela e
    # foram para a revisão 'identidade_de_outra_escola' — nada delas aplicado aqui.
    ids_de_outra_escola: list[str] = []
    # Alunos SEM ficha que a importação criaria e que a política 'bloquear' da
    # escola mandou para a revisão ('criacao_bloqueada_por_politica') — a tela
    # mostra o motivo e o caminho (Revisão de identidade).
    criacao_bloqueada: int = 0


# --- Fila de revisão de identidade --------------------------------------------

class RevisaoIdentidadeOut(ORMModel):
    id: int
    plataforma: str
    formato: str
    id_externo: str | None = None
    nome_recebido: str
    turma_informada: str | None = None
    turma_id: int | None = None
    motivo: str
    motivo_texto: str = ""
    candidatos: list[dict] = []
    linhas: list[dict] = []
    contexto: dict = {}
    origem: str
    importacao_id: int | None = None
    ocorrencias: int
    status: str
    aluno_escolhido_id: int | None = None
    resolvida_por_id: int | None = None
    resolvida_em: datetime | None = None
    resolucao: dict | None = None
    created_at: datetime
    atualizada_em: datetime
    # Veredito determinístico da triagem ("dá para encerrar com segurança, e por
    # quê") — ver ``services/triagem_revisoes``. Só na listagem da fila.
    triagem: dict | None = None
    # O nome que "Criar novo aluno" grava (A10: sem o sufixo de turma digitado junto
    # do nome) e, por turma, só onde ele muda. Só nas pendentes da listagem.
    nome_ficha_nova: str | None = None
    nome_ficha_nova_por_turma: dict[str, str] = {}


class ResolverRevisaoIn(BaseModel):
    """Decisão EXPLÍCITA do gestor: o aluno dono destes dados (``aluno_id``) OU
    uma ficha nova numa turma escolhida (``criar_em_turma_id``) — exatamente um."""
    aluno_id: int | None = None
    criar_em_turma_id: int | None = None


class DefinirIdentidadeEfetivaIn(BaseModel):
    """CONTA DUPLICADA: qual conta da plataforma vale para este aluno.

    As demais ficam APOSENTADAS — preservadas, mas fora da importação e da
    pontuação. Decisão interna do Constela; nada muda na plataforma externa."""
    aluno_id: int
    id_externo_efetivo: str = Field(min_length=1, max_length=80)
    aposentar: list[str] = Field(default_factory=list)
    motivo: str = Field(min_length=3, max_length=300)


class ReativarIdentidadeIn(BaseModel):
    aluno_id: int
    id_externo: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=3, max_length=300)


class DescartarRevisaoIn(BaseModel):
    motivo: str = Field(default="", max_length=300)


class ResolucaoRevisaoOut(BaseModel):
    revisao: RevisaoIdentidadeOut
    aluno_id: int
    revisoes_resolvidas: list[int] = []
    importacoes: list[int] = []
    avisos: list[str] = []


# --- Importação da planilha de matrículas da escola ("Lista Piloto") --------

class MatriculaTurmaOut(BaseModel):
    nome: str
    ano_escolar: str
    turno: str | None = None
    professor: str = ""
    sed: str = ""
    total_alunos: int
    ja_existe: bool = False          # a turma já está cadastrada?
    exemplos: list[str] = []         # primeiros nomes, para conferência


class MatriculasAnaliseOut(BaseModel):
    escola_detectada: str = ""
    ano_letivo: int | None = None
    total_turmas: int
    total_alunos: int                 # alunos DISTINTOS (o que será cadastrado)
    total_registros: int = 0          # linhas na planilha (pode repetir aluno)
    # Resumo por efeito (prévia antes de confirmar): quantos serão CRIADOS vs
    # ATUALIZADOS (já existem) e quantas turmas já existem (duplicidade).
    # São os números da CONFIRMAÇÃO (a prévia roda a mesma e a desfaz): criados,
    # atualizados (distintos) e linhas que irão para revisão — nem criam nem alteram.
    alunos_novos: int = 0
    alunos_atualizar: int = 0
    alunos_em_revisao: int = 0
    turmas_existentes: int = 0
    turmas: list[MatriculaTurmaOut]
    avisos: list[str] = []
    # A lista é de OUTRO ano letivo que o ativo da escola (``ano_letivo`` ≠ ano ativo):
    # a confirmação recusa (409) e a tela não deixa gravar. ``aviso_ano`` diz por quê
    # e o que fazer; sem o ano na planilha, só pede para conferir (não bloqueia).
    ano_divergente: bool = False
    aviso_ano: str | None = None


class MatriculasResultadoOut(BaseModel):
    mensagem: str
    turmas_criadas: int
    alunos_criados: int
    alunos_atualizados: int
    # Alunos do piloto que sumiram da lista e foram marcados "fora_lista_piloto"
    # (continuam cadastrados; nada é apagado).
    alunos_fora_lista: int = 0
    # Linhas cuja identidade NÃO pôde ser decidida com segurança: não criaram nem
    # alteraram ninguém (evita a 2ª ficha da mesma criança) e viraram aviso.
    alunos_em_revisao: int = 0
    # Contas de professor criadas automaticamente (login = NomeSobrenome).
    professores_criados: int = 0
    avisos: list[str] = []


class PoliticaSincronizacaoOut(BaseModel):
    """A política de sincronização vigente da escola (ver ``politica_sync``)."""
    criar_aluno: str


class PoliticaSincronizacaoIn(BaseModel):
    """``permitir`` (padrão histórico) ou ``bloquear`` (a sync não cria ficha).

    Trocar isto não mexe em nenhum dado já gravado: vale da próxima
    sincronização em diante, e o motivo fica no log de auditoria.
    """
    criar_aluno: str = Field(pattern="^(permitir|bloquear)$")
    motivo: str | None = Field(default=None, max_length=300)
