"""Schemas do fluxo de importação (PRD §15–§16, §50–§52)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.comum import ORMModel


class CorrespondenciaOut(BaseModel):
    status: str  # exato | provavel | nao_encontrado
    aluno_id: int | None = None
    aluno_nome: str | None = None
    similaridade: float | None = None
    alternativas: list[dict] = []


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
    origem_nome: str = ""           # arquivo | conteudo | nenhum (como o nome foi achado)
    # "Intervalo de datas" impresso no relatório (Matific): datas ISO. O
    # frontend devolve estes valores no /confirmar para datar os dados.
    periodo_inicio: str = ""
    periodo_fim: str = ""
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
    alunos_novos: int = 0
    alunos_atualizar: int = 0
    turmas_existentes: int = 0
    turmas: list[MatriculaTurmaOut]
    avisos: list[str] = []


class MatriculasResultadoOut(BaseModel):
    mensagem: str
    turmas_criadas: int
    alunos_criados: int
    alunos_atualizados: int
    # Alunos do piloto que sumiram da lista e foram marcados "fora_lista_piloto"
    # (continuam cadastrados; nada é apagado).
    alunos_fora_lista: int = 0
    avisos: list[str] = []
