"""Schemas Pydantic — contrato da API.

Mantidos em um módulo único nesta fase; ao crescer, dividir por domínio
sem alterar os imports (o pacote reexporta tudo).
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Autenticação -----------------------------------------------------------

class UsuarioOut(ORMModel):
    id: int
    nome: str
    email: str
    username: str | None = None
    cargo: str
    is_global: bool
    escola_id: int | None
    # Vínculo com a rede/Secretaria (nulo = usuário de escola única). Habilita a
    # visão da Secretaria no frontend (menu + /rede).
    rede_id: int | None = None
    status: str = "ativo"
    ultimo_acesso: datetime | None = None
    created_at: datetime | None = None
    # Módulos CONTRATADOS que valem para este usuário (SaaS). Preenchido em
    # /auth/me e no login; é a fonte que o frontend usa para montar menu, abas e
    # telas. Vazio-por-default só em listagens de usuários, onde não se aplica.
    modulos: list[str] = []


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut


# --- Escolas ----------------------------------------------------------------

class EscolaOut(ORMModel):
    id: int
    nome: str
    cidade: str | None
    estado: str | None
    logotipo_url: str | None
    ano_letivo_ativo: int
    status: str


class EscolaCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    cidade: str | None = None
    estado: str | None = Field(default=None, max_length=2)
    ano_letivo_ativo: int = 2026


class EscolaUpdate(BaseModel):
    nome: str | None = None
    cidade: str | None = None
    estado: str | None = Field(default=None, max_length=2)
    logotipo_url: str | None = None
    ano_letivo_ativo: int | None = None
    # Um status fora do vocabulário faria a escola sumir de TODAS as listas
    # (o GET filtra por igualdade exata) sem caminho de volta pela interface.
    status: str | None = Field(default=None, pattern="^(ativa|inativa)$")


# --- Acadêmico --------------------------------------------------------------

class ProfessorOut(ORMModel):
    id: int
    nome: str
    email: str | None
    observacoes: str | None


class ProfessorCreate(BaseModel):
    nome: str
    email: EmailStr | None = None
    observacoes: str | None = None


class ProfessorUpdate(BaseModel):
    """Edita o nome e/ou o e-mail do professor (ex.: completar um apelido vindo da
    importação, ou corrigir o e-mail — que é o login e o vínculo com as turmas).
    Só os campos enviados mudam."""
    nome: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None


class ProfessorCompletoIn(BaseModel):
    """Cadastro completo: professor + turma sob responsabilidade + conta de
    acesso (cargo professor) com senha gerada. O e-mail é obrigatório porque
    é ele que liga a conta às turmas do professor (acesso restrito)."""
    nome: str = Field(min_length=2, max_length=200)
    email: EmailStr
    turma_id: int | None = None
    criar_acesso: bool = True


PADRAO_TURNO = "^(manha|tarde|noite|integral)$"


class TurmaOut(ORMModel):
    id: int
    nome: str
    ano_escolar: str
    ano_letivo: int
    professor_id: int | None
    turno: str | None = None
    capacidade_maxima: int | None = None
    observacoes: str | None = None
    status: str = "ativa"
    # Preenchidos na listagem para a tela de gestão
    professor_nome: str | None = None
    # Alunos ATIVOS do ano letivo da turma (o número "amigável" exibido).
    total_alunos: int = 0
    # Matrículas CRUAS vinculadas à turma (qualquer ano/situação). É o que a
    # trava de exclusão enxerga (a FK bloqueia excluir turma com QUALQUER
    # matrícula) — a tela usa este número para decidir se há dados a apagar.
    total_matriculas: int = 0


class TurmaCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    ano_escolar: str = Field(min_length=1, max_length=30)
    ano_letivo: int = Field(ge=2000, le=2100)
    professor_id: int | None = None
    turno: str | None = Field(default=None, pattern=PADRAO_TURNO)
    capacidade_maxima: int | None = Field(default=None, ge=1, le=500)
    observacoes: str | None = Field(default=None, max_length=2000)


class TurmaUpdate(BaseModel):
    """Atualização parcial — só o que foi enviado é alterado."""
    nome: str | None = Field(default=None, min_length=1, max_length=100)
    ano_escolar: str | None = Field(default=None, min_length=1, max_length=30)
    ano_letivo: int | None = Field(default=None, ge=2000, le=2100)
    professor_id: int | None = None
    turno: str | None = Field(default=None, pattern=PADRAO_TURNO)
    capacidade_maxima: int | None = Field(default=None, ge=1, le=500)
    observacoes: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(ativa|arquivada)$")


class AlunoOut(ORMModel):
    id: int
    nome: str
    foto_url: str | None
    numero_chamada: int | None
    status: str
    turma: str | None = None
    ano_escolar: str | None = None
    # Para o modal "Editar aluno" pré-preencher todos os campos do cadastro.
    data_nascimento: date | None = None
    observacoes: str | None = None


class AlunoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    turma_id: int
    numero_chamada: int | None = None
    data_nascimento: date | None = None
    observacoes: str | None = None
    # Ficha cadastral (RA, responsável, telefone, endereço...): mesmas chaves
    # da planilha de matrículas; o backend guarda só as chaves conhecidas.
    ficha: dict[str, str] = {}


class AlunoUpdate(BaseModel):
    """Edição parcial do cadastro do aluno (só os campos enviados mudam)."""
    nome: str | None = Field(default=None, min_length=2, max_length=200)
    numero_chamada: int | None = None
    data_nascimento: date | None = None
    observacoes: str | None = Field(default=None, max_length=1000)


class DimensaoAlunoOut(BaseModel):
    """Desempenho do aluno em UMA dimensão (Leitura / Matemática).

    Arquitetura 2 (`docs/spec-arquitetura-2.md` §1.1): a dimensão é a unidade de
    verdade do desempenho. As quatro informações viajam SEMPRE juntas — nota,
    posição, denominador e quantidade de dados —, porque nenhuma delas se
    interpreta sozinha ("3º" sem `n_aferidos` parece comparável entre dimensões,
    e não é).

    `aferido=False` significa AUSÊNCIA de snapshot: `nota` e `posicao` vêm
    `None` (a tela mostra `—`), jamais 0,0. O zero fica reservado ao zero
    LEGÍTIMO (tem snapshot, ainda não produziu), que vem com `aferido=True`.
    """
    dimensao: str
    plataforma: str
    contratada: bool = True
    aferido: bool = False
    nota: float | None = None
    posicao: int | None = None
    n_aferidos: int = 0
    # Data do snapshot que sustenta a nota — é o que distingue "nota baixa" de
    # "nota velha"; existia no banco e não chegava a nenhuma tela de aluno.
    snapshot_em: str | None = None
    # Indicadores brutos da própria dimensão (livros/tempo/questões ou
    # atividades/estrelas/média).
    dados: dict = {}


class AdocaoAlunoOut(BaseModel):
    """Cobertura do aluno: |D| / |P| (§3.2). Fica AO LADO do desempenho —
    nunca somada, multiplicada ou promediada com ele (§3.4)."""
    contratadas: list[str] = []
    com_dados: list[str] = []
    pct: float = 0.0


class AlunoGestaoOut(ORMModel):
    """Aluno com nota e data de cadastro — usado no painel de gestão da turma."""
    id: int
    nome: str
    foto_url: str | None
    numero_chamada: int | None
    status: str
    turma: str | None = None
    ano_escolar: str | None = None
    created_at: datetime | None = None
    # LEGADO (composição entre dimensões): não ordena mais nada. Preservado
    # enquanto os clientes não migrados ainda o leem.
    nota_geral: float | None = None
    posicao: int | None = None
    # Desempenho por DIMENSÃO — a verdade oficial. `None` = não aferido (`—`).
    nota_leitura: float | None = None
    nota_matematica: float | None = None
    aferido_leitura: bool = False
    aferido_matematica: bool = False
    posicao_leitura: int | None = None
    posicao_matematica: int | None = None


class AcaoAlunos(BaseModel):
    """Ação em massa (ou individual) sobre alunos: arquivar, reativar, excluir
    (lógico) ou transferir de turma."""
    aluno_ids: list[int] = Field(min_length=1)
    acao: str = Field(pattern="^(arquivar|reativar|excluir|transferir)$")
    turma_id: int | None = None  # obrigatório quando acao == "transferir"


class ExclusaoPermanenteAlunos(BaseModel):
    """Exclusão FÍSICA irreversível: exige confirmação textual explícita."""
    aluno_ids: list[int] = Field(min_length=1)
    confirmacao: str = ""


class FusaoAlunos(BaseModel):
    """Funde dois cadastros do MESMO aluno (duplicados): todos os dados do
    `remover` passam para o `manter`, e o `remover` é apagado. Confirmação
    textual ("FUNDIR") por ser irreversível."""
    manter_id: int
    remover_id: int
    confirmacao: str = ""


class CorrigirDuplicadosAlunos(BaseModel):
    """Fusão em LOTE das duplicatas de alunos CONFIRMADAS (os ``loser_ids``
    marcados na tela). Irreversível → exige confirmação textual "FUNDIR"."""
    loser_ids: list[int] = Field(default_factory=list)
    confirmacao: str = ""


class ConsolidarTurmasIn(BaseModel):
    """Um grupo de consolidação de turmas duplicadas: a turma CANÔNICA que
    permanece + as DUPLICADAS cujas matrículas migram para ela (e depois são
    removidas)."""
    canonica_id: int
    duplicada_ids: list[int] = Field(min_length=1)


class ExcluirTurmas(BaseModel):
    """Exclusão em massa de turmas. Com ``com_alunos``, remove também os alunos
    matriculados nessas turmas e todos os seus dados (irreversível); sem, as
    turmas que ainda têm alunos são mantidas e reportadas."""
    turma_ids: list[int] = Field(min_length=1)
    com_alunos: bool = False


class FaixaLeituraOut(BaseModel):
    codigo: str
    nome: str
    quantidade: int
    pontos_por_livro: float
    pontos: float
    percentual: float


class LeituraNiveisOut(BaseModel):
    faixas: list[FaixaLeituraOut]
    total_livros: int
    pontos_dificuldade: float
    faixa_predominante: str | None = None


class AlunoPerfilOut(BaseModel):
    aluno: AlunoOut
    nota_matific: float
    nota_elefante: float
    # LEGADO: a composição entre dimensões. Não ordena mais nada e não é a
    # fonte oficial — `dimensoes` é. Preservado enquanto os clientes migram.
    nota_geral: float
    posicao: int | None
    # Desempenho por DIMENSÃO (a verdade oficial) + a cobertura ao lado.
    dimensoes: list[DimensaoAlunoOut] = []
    adocao: AdocaoAlunoOut | None = None
    detalhes: dict
    calculada_em: datetime | None
    leitura_niveis: LeituraNiveisOut | None = None
    # Ficha cadastral (planilha de matrículas): {} para professor (superficial).
    ficha: dict = {}


# --- Configurações ----------------------------------------------------------

class PesosOut(BaseModel):
    namespace: str
    valores: dict[str, float]
    soma: float


class PesosUpdate(BaseModel):
    valores: dict[str, float]


class NivelOut(ORMModel):
    id: int
    nome: str
    codigo: str | None = None
    codigos: list
    pontos_padrao: float
    ordem: int


class NivelCreate(BaseModel):
    """Cadastro de um novo nível de dificuldade (faixa) do Elefante Letrado."""
    nome: str = Field(min_length=1, max_length=60)
    # Códigos de letra dos livros que pertencem à faixa (ex.: ["AA","BB"]).
    codigos: list[str] = Field(default_factory=list)
    pontos_padrao: float = Field(default=1.0, ge=0)


class NivelUpdate(BaseModel):
    """Edição parcial de um nível — só os campos enviados mudam."""
    nome: str | None = Field(default=None, min_length=1, max_length=60)
    codigos: list[str] | None = None
    pontos_padrao: float | None = Field(default=None, ge=0)
    ordem: int | None = Field(default=None, ge=0)


class DificuldadeSerieOut(BaseModel):
    ano_escolar: str
    pontos: dict[int, float]  # nivel_id -> pontos


class DificuldadeUpdate(BaseModel):
    ano_escolar: str
    nivel_id: int
    pontos: float = Field(ge=0)


class ElefanteExtraOut(BaseModel):
    """Config dos PONTOS EXTRAS por livro lido na escola (Elefante Letrado)."""
    ativo: bool
    pontos_por_livro: float


class ElefanteExtraUpdate(BaseModel):
    ativo: bool
    pontos_por_livro: float = Field(ge=0, le=1000)


class ReferenciasOut(BaseModel):
    modo: str
    valores_manuais: dict
    valores_em_uso: dict


class ReferenciasUpdate(BaseModel):
    modo: str = Field(pattern="^(auto|manual)$")
    valores_manuais: dict[str, float] = {}


# --- Ranking e Dashboard ----------------------------------------------------

class RankingItemOut(BaseModel):
    """Item de ranking de aluno.

    Serve às DUAS formas: o ranking por DIMENSÃO (Leitura / Matemática — a
    ordenação oficial da Arquitetura 2) e o Ranking Geral LEGADO, ainda
    consumido pelas vitrines e pelos clientes não migrados. Os campos por
    dimensão vêm nulos quando a rota é chamada sem `?dimensao=`, então o
    contrato antigo continua válido bit a bit.
    """
    posicao: int
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None
    nota_matific: float
    nota_elefante: float
    # LEGADO: composição entre dimensões; não ordena mais nada.
    nota_geral: float
    # Discriminante de AFERIÇÃO por dimensão — carimbado SEMPRE, inclusive na
    # rota LEGADA (sem `?dimensao=`). O Top 5 do painel (web e app) imprime
    # `nota_elefante · nota_matific` lado a lado: sem estes dois campos o
    # cliente não tem como separar "não usa o Matific" (ausência: `—`) de "usa
    # e tirou 0,0" (zero legítimo), e a criança que só lê aparecia como
    # "72,0 · 0,0" na tela mais visível do produto. `notaDaMateria`
    # (packages/core) já renderiza o `—` a partir deles.
    # `None` = servidor antigo/cliente que não recebeu o carimbo — nesse caso o
    # cliente mantém o comportamento anterior em vez de inventar uma ausência.
    aferido_leitura: bool | None = None
    aferido_matematica: bool | None = None
    # --- Por dimensão (preenchidos só quando a rota recebe `?dimensao=`) ------
    dimensao: str | None = None
    # A nota DAQUELA dimensão. Nunca 0,0 por ausência: quem não é aferido não
    # entra na lista (aparece na visão de "ainda não aferidos").
    nota: float | None = None
    aferido: bool | None = None
    # Denominador da posição — "8º de 21 aferidos em Leitura". Sem ele, um "3º"
    # numa dimensão e um "3º" na outra parecem comparáveis, e não são.
    n_aferidos: int | None = None
    # Indicadores brutos DAQUELA dimensão (livros/tempo/questões ou
    # atividades/estrelas/média) + a data do snapshot que sustenta a nota.
    dados: dict = {}
    snapshot_em: str | None = None
    # Cobertura do aluno (|D| / |P| × 100): quantas das dimensões contratadas
    # ele de fato usa. Fica AO LADO do desempenho, nunca somada a ele.
    adocao: float | None = None
    # TURNO da turma do aluno (`Turma.turno` cru: manha|tarde|noite|integral|None).
    # Preenchido só no ranking de leitura POR TURNO; a série (`ano_escolar`) segue
    # sendo só informação exibida ao lado — nunca entra na nota.
    turno: str | None = None


class RankingTurnoOut(BaseModel):
    """Um turno e o ranking de leitura dos alunos DAQUELE turno.

    A competição escolar de leitura é dividida por ``Turma.turno`` (descoberto do
    banco, nunca hardcoded): dentro de cada turno competem TODOS os alunos ativos
    do 1º ao 5º ano juntos, ordenados pela MESMA ``nota_elefante`` (régua única da
    escola). A posição reinicia em 1 a cada turno."""
    turno: str | None            # valor cru de Turma.turno (None = turma sem turno)
    turno_rotulo: str            # rótulo de apresentação ("Manhã", "Tarde", ...)
    total: int
    alunos: list["RankingItemOut"]


class AlunoNaoAferidoOut(BaseModel):
    """Aluno SEM dado numa dimensão — visão operacional, não competitiva.

    Sem nota e sem posição de propósito: quem nunca foi alcançado não é o pior
    da escola, é a criança que a coordenação precisa ver.
    """
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None


class DimensaoNaoAferidaOut(BaseModel):
    dimensao: str
    plataforma: str
    n_aferidos: int
    total: int
    alunos: list[AlunoNaoAferidoOut]


class NaoAferidosOut(BaseModel):
    contratadas: list[str]
    total_alunos: int
    dimensoes: list[DimensaoNaoAferidaOut]
    # Sem dado em NENHUMA dimensão contratada: adoção 0%, `—` em toda parte.
    sem_nenhuma: list[AlunoNaoAferidoOut]


class DashboardOut(BaseModel):
    escola: EscolaOut
    total_alunos: int
    total_turmas: int
    total_professores: int
    total_atividades: int
    total_livros: int
    tempo_leitura_min: int
    # Desempenho por DIMENSÃO — cada média sobre os alunos QUE TÊM dado daquela
    # plataforma, com o seu próprio denominador ao lado.
    media_leitura: float = 0.0
    alunos_com_dado_leitura: int = 0
    media_matematica: float = 0.0
    alunos_com_dado_matematica: int = 0
    # Média das dimensões COM DADO (a mesma régua do cartão da escola no painel
    # da rede). Mantida por compatibilidade; não ordena nada.
    media_geral: float
    # Cobertura: % de alunos com dado de ALGUMA plataforma contratada, e quantos
    # não têm dado de nenhuma (a lista de ação da coordenação).
    alcance: float = 0.0
    nao_aferidos: int = 0
    top10: list[RankingItemOut]


# --- Rede / Secretaria (CRUD do admin global) -------------------------------

class RedeOut(ORMModel):
    id: int
    nome: str
    uf: str | None = None
    codigo_ibge: str | None = None
    status: str = "ativa"


class RedeCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    uf: str | None = Field(default=None, max_length=2)
    codigo_ibge: str | None = Field(default=None, max_length=7)


class RedeUpdate(BaseModel):
    """Atualização parcial — só o que foi enviado muda."""
    nome: str | None = Field(default=None, min_length=2, max_length=200)
    uf: str | None = Field(default=None, max_length=2)
    codigo_ibge: str | None = Field(default=None, max_length=7)
    status: str | None = Field(default=None, pattern="^(ativa|inativa)$")


class RedeEscolasIn(BaseModel):
    """Define o CONJUNTO de escolas da rede: as listadas passam a pertencer a
    ela; as que estavam na rede e não vieram na lista são desvinculadas."""
    escola_ids: list[int] = Field(default_factory=list)


class RedeUsuariosIn(BaseModel):
    """Define QUAIS usuários são a Secretaria desta rede (recebem o rede_id);
    os que estavam na rede e saíram da lista voltam a ficar sem rede."""
    usuario_ids: list[int] = Field(default_factory=list)


class RedePublicoIn(BaseModel):
    """Liga/desliga a vitrine pública da rede (sem login). Ligar gera um token
    novo; desligar limpa (invalida o link)."""
    ativo: bool


class MetaRedeIn(BaseModel):
    """Cadastro/edição de uma meta da rede para um indicador consolidado. UMA por
    (rede, métrica) — redefinir a mesma métrica sobrescreve o alvo."""
    metrica: str = Field(
        pattern="^(pontuacao_geral|adocao|media_geral|media_elefante|media_matific"
                "|livros|atividades)$")
    alvo: float = Field(gt=0)
    descricao: str | None = Field(default=None, max_length=200)


class EscolaLocalIn(BaseModel):
    """Localização da escola (para o mapa da Secretaria) — cidade/UF, bairro/
    endereço (geocodificação), coordenadas — e o código INEP (para casar
    avaliações oficiais). Atualização parcial."""
    cidade: str | None = Field(default=None, max_length=120)
    estado: str | None = Field(default=None, max_length=2)
    bairro: str | None = Field(default=None, max_length=120)
    endereco: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    # "" limpa o código; qualquer valor é normalizado p/ 8 dígitos no endpoint.
    codigo_inep: str | None = Field(default=None, max_length=20)
