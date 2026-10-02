"""Schemas dos módulos Matific, Elefante Letrado e Catálogo de Livros (PRD §55–§57)."""
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.comum import ORMModel

# Contagem de livros num ajuste MANUAL: inteiro entre 0 e 10.000 (negativo → 422).
ContagemLivros = Annotated[int, Field(ge=0, le=10000)]

MOTIVO_MINIMO = 5


def _motivo_obrigatorio(valor: str) -> str:
    """Motivo do ajuste manual: obrigatório, com pelo menos 5 caracteres úteis —
    é o que fica no log de auditoria para explicar a mudança."""
    texto = (valor or "").strip()
    if len(texto) < MOTIVO_MINIMO:
        raise ValueError(
            f"Informe o motivo do ajuste (pelo menos {MOTIVO_MINIMO} caracteres) — "
            "ele fica registrado no log de auditoria.")
    return texto


class MatificAlunoOut(BaseModel):
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None
    atividades: int
    estrelas: int
    pontuacao_media: float
    data_referencia: datetime | None


class MatificEdicao(BaseModel):
    atividades: int = Field(ge=0)
    estrelas: int = Field(ge=0)
    # A média do Matific é de 0 a 5 (a mesma escala do Placar da Escola).
    #
    # OPCIONAL de propósito: corrigir "atividades" ou "estrelas" não pode obrigar
    # a reescrever a MÉDIA. Snapshots antigos podem estar fora da escala (edição
    # manual gravada quando o limite era 100, ou base de demonstração); se a
    # média fosse obrigatória, o formulário — que pré-carrega o valor gravado e o
    # reenvia — devolveria 422 e o registro ficaria ineditável, empurrando o
    # gestor a INVENTAR um número ≤ 5. Ausente = preserva a média do snapshot
    # anterior (ver ``routers.plataformas.editar_matific``). O limite 0–5 vale
    # para o valor INFORMADO: ninguém grava média nova fora da escala.
    pontuacao_media: float | None = Field(default=None, ge=0, le=5)
    motivo: str | None = None


class ElefanteAlunoOut(BaseModel):
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None
    livros_unicos: int
    tempo_leitura_min: int
    questoes_tentativas: int
    questoes_acertos: int
    livros_por_nivel: dict
    data_referencia: datetime | None


class ElefanteEdicao(BaseModel):
    """Snapshot MANUAL do Elefante. As chaves de ``livros_por_nivel`` são validadas
    no servidor (vocabulário oficial AA…Z, Z+, A+ ou faixas da escola)."""
    livros_unicos: int | None = Field(default=None, ge=0, le=10000)
    tempo_leitura_min: int = Field(ge=0)
    questoes_tentativas: int = Field(ge=0)
    questoes_acertos: int = Field(ge=0)
    livros_por_nivel: dict[str, ContagemLivros] = {}
    motivo: str

    _motivo = field_validator("motivo")(_motivo_obrigatorio)


class NiveisLeituraEdicao(BaseModel):
    """Informar os livros concluídos por FAIXA de dificuldade (ex.:
    {"pre_leitor": 8, "nivel_1": 15, ...}). O total e os pontos de dificuldade
    são derivados; as demais métricas do Elefante são preservadas."""
    faixas: dict[str, ContagemLivros]
    motivo: str

    _motivo = field_validator("motivo")(_motivo_obrigatorio)


class LivroOut(ORMModel):
    id: int
    titulo: str
    autor: str | None
    nivel_codigo: str
    categoria: str | None
    paginas: int | None
    pontos: float = 0.0
    leituras: int = 0
    # --- Governança do catálogo oficial ---
    # id do livro no catálogo oficial do Elefante (nulo = não vinculado)
    elefante_id: int | None = None
    # último nível informado pela fonte (sincronização/importação). Livro FORA do
    # catálogo: é o nível do relatório, que a escola controla — não é oficial.
    nivel_fonte: str | None = None
    # nível OFICIAL: só o do CATÁLOGO, pelo id. Livro fora do catálogo → None.
    nivel_oficial: str | None = None
    word_count: int | None = None
    # quem definiu o nível efetivo: fonte | admin_global | legado
    origem_nivel: str = "legado"
    atualizado_em: datetime | None = None
    no_catalogo: bool = False
    # nível efetivo diferente do oficial (ou do último da fonte)
    divergente: bool = False
    # o usuário pode corrigir o livro (só o Admin Global)
    editavel: bool = False
    # --- Efeito de uma correção (PATCH de nível/título) ---
    # Cada ``Leitura`` guarda o NÍVEL CONGELADO do momento em que foi registrada:
    # a correção vale para as PRÓXIMAS leituras e o histórico fica como está.
    vale_para_proximas_leituras: bool = False
    # Nenhum nível congelado foi reescrito (só ``aplicar_ao_historico`` reescreve).
    historico_preservado: bool = True
    # Leituras cujo nível congelado foi reescrito por ``aplicar_ao_historico``.
    leituras_atualizadas: int = 0
    # Leituras ANTERIORES ao congelamento (nível nulo): a única ressalva honesta
    # — elas caem no nível ATUAL do livro, então mudam de valor no próximo cálculo.
    leituras_sem_nivel_congelado: int = 0
    # Mensagem exata do que a correção muda e a partir de quando (fonte única do
    # texto que a tela do Catálogo exibe).
    aviso_correcao: str | None = None


class LivroCreate(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)
    autor: str | None = None
    nivel_codigo: str = Field(min_length=1, max_length=5)
    categoria: str | None = None
    paginas: int | None = Field(default=None, ge=1)
    motivo: str | None = Field(default=None, max_length=500)


class LivroUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=300)
    autor: str | None = None
    nivel_codigo: str | None = Field(default=None, min_length=1, max_length=5)
    categoria: str | None = None
    paginas: int | None = Field(default=None, ge=1)
    # Obrigatório (≥ 5 caracteres) quando o nível muda ou quando a correção é
    # aplicada ao histórico — validado na rota, que sabe o nível atual do livro.
    motivo: str | None = Field(default=None, max_length=500)
    # AÇÃO RETROATIVA EXPLÍCITA do Admin Global. Padrão false: corrigir o
    # catálogo vale para as PRÓXIMAS leituras e não toca no nível congelado das
    # leituras já registradas. Com true, o nível congelado das leituras deste
    # livro passa a ser o nível vigente, com auditoria (de/para + contagem) e
    # recálculo da escola.
    aplicar_ao_historico: bool = False

    @model_validator(mode="after")
    def _titulo_e_nivel_nao_nulos(self):
        """Título e nível são obrigatórios no livro: enviá-los nulos/vazios é erro
        de validação (422), nunca uma violação de NOT NULL no banco (500)."""
        for campo, rotulo in (("titulo", "O título"), ("nivel_codigo", "O nível")):
            if campo in self.model_fields_set:
                valor = getattr(self, campo)
                if valor is None or not str(valor).strip():
                    raise ValueError(f"{rotulo} do livro não pode ficar vazio.")
        return self


class RestauracaoLeituraItem(BaseModel):
    """Uma leitura a ter data/tempo restaurados, COM a evidência que sustenta.

    O chamador declara o que afirma; o serviço confere cada afirmação contra o
    banco — inclusive recalculando o hash da ``chave_natural`` do evento, que
    carrega dentro de si a ficha de ORIGEM do dado. Por isso
    ``aluno_origem_id`` é obrigatório: ele é o que o hash prova, não um palpite.
    """
    aluno_id: int = Field(gt=0)
    # Ficha ABSORVIDA pela fusão, de onde a data/tempo vieram. Já não existe
    # como registro — existe dentro do hash do evento.
    aluno_origem_id: int = Field(gt=0)
    livro_id: int = Field(gt=0)
    data_original: datetime
    tempo_original: int | None = Field(default=None, ge=0, le=100000)
    evidencia_evento_id: int = Field(gt=0)
    # sha256 em hex: exatamente 64 caracteres.
    evidencia_chave_natural: str = Field(min_length=64, max_length=64)
    motivo: str = Field(min_length=10, max_length=500)


class RestauracaoLeituras(BaseModel):
    """Lote de restauração histórica (só Admin Global).

    ``dry_run`` é o PADRÃO: pedir sem dizer nada devolve o plano conferido e não
    escreve. Aplicar exige ``dry_run=false`` E a confirmação textual, pela mesma
    razão da fusão — reescrever histórico não pode acontecer por acidente de
    clique. ``permitir_fora_do_ano_letivo`` é uma decisão explícita: sem ele, uma
    data de outro ano letivo é recusada como provável erro de origem.
    """
    itens: list[RestauracaoLeituraItem] = Field(min_length=1, max_length=500)
    dry_run: bool = True
    confirmacao: str = ""
    permitir_fora_do_ano_letivo: bool = False
