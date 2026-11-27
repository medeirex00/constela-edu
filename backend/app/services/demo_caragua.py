"""Cenário sintético da demonstração Caraguatatuba, sem dados de escolas cadastradas."""
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Escola, ModuloRede, Rede, Usuario
from app.schemas.demo_caragua import (
    AvaliacaoDemonstracao,
    DemonstracaoCaragua,
    EscolaDemonstracao,
    RegiaoDemonstracao,
)

NOME_REDE = "IFSP · Demonstração Caraguatatuba"
MODULO = "demo_caragua"
USERNAME = "ifsp2026sec"
EMAIL = "ifsp2026sec@demo.constela.invalid"
NOME_USUARIO = "Secretaria IFSP — Demonstração"


def marcador_da_rede(rede_id: int):
    return (ModuloRede.rede_id == rede_id) & (ModuloRede.modulo == MODULO)


def tem_rede_da_demonstracao(db: Session, redes: set[int]) -> bool:
    if not redes:
        return False
    return bool(db.scalar(select(exists().where(
        ModuloRede.rede_id.in_(redes), ModuloRede.modulo == MODULO,
    ))))


def pode_ver(db: Session, rede_id: int, usuario: Usuario) -> bool:
    username = (usuario.username or "").strip().lstrip("@").lower()
    if (usuario.is_global or usuario.escola_id is not None
            or usuario.rede_id != rede_id or username != USERNAME):
        return False

    rede_exclusiva = select(Rede.id).join(ModuloRede, ModuloRede.rede_id == Rede.id).where(
        marcador_da_rede(rede_id),
        ModuloRede.ativo.is_(True),
        Rede.nome == NOME_REDE,
        Rede.status == "ativa",
        Rede.codigo_ibge.is_(None),
        Rede.codigo_municipio_estadual.is_(None),
        Rede.token_publico.is_(None),
        ~exists().where(Escola.rede_id == Rede.id),
    )
    return bool(db.scalar(select(rede_exclusiva.exists())))


# Cada linha traz um ponto de demonstração e uma base sintética de proficiência.
# As coordenadas ilustram a região. Não identificam unidades escolares reais.
_PONTOS = (
    ("norte-1", "Escola Fictícia Maré Clara", "norte", -23.582, -45.339, 78, 105, 128, 193),
    ("norte-2", "Escola Fictícia Veredas do Mar", "norte", -23.565, -45.323, 65, 71, 104, 183),
    ("norte-3", "Escola Fictícia Farol Azul", "norte", -23.552, -45.292, 40, 53, 96, 201),
    ("centro-1", "Escola Fictícia Horizonte", "centro", -23.621, -45.412, 65, 129, 162, 204),
    ("centro-2", "Escola Fictícia Jardim das Conchas", "centro", -23.634, -45.424, 78, 97, 120, 186),
    ("centro-3", "Escola Fictícia Estrela do Vale", "centro", -23.613, -45.432, None, 0, 91, 193),
    ("sul-1", "Escola Fictícia Ponte do Sol", "sul", -23.666, -45.431, 40, 76, 135, 195),
    ("sul-2", "Escola Fictícia Caminhos do Rio", "sul", -23.676, -45.446, 45, 94, 137, 203),
    ("sul-3", "Escola Fictícia Brisa do Sul", "sul", -23.687, -45.452, None, 0, 102, 181),
    ("serra-1", "Escola Fictícia Mirante Verde", "serra", -23.630, -45.550, None, 0, 59, 190),
)

_CENARIOS_AVALIACAO = (("SARESP", 2024, 0), ("SARESP", 2025, 5), ("SAEB", 2023, 8))
_DISCIPLINAS = (("Língua Portuguesa", 0), ("Matemática", 7))

CENARIO = DemonstracaoCaragua(
    escolas=tuple(
        EscolaDemonstracao(id=id_, nome=nome, regiao=regiao, latitude=latitude,
                           longitude=longitude, nota=nota, com_dados=com_dados,
                           matriculados=matriculados)
        for id_, nome, regiao, latitude, longitude, nota, com_dados, matriculados, _ in _PONTOS
    ),
    regioes=(
        RegiaoDemonstracao(id="norte", nome="Norte", contexto="Faixa costeira ao norte da área central."),
        RegiaoDemonstracao(id="centro", nome="Centro", contexto="Entorno da sede urbana e da orla central."),
        RegiaoDemonstracao(id="sul", nome="Sul", contexto="No cenário fictício, vale investigar o transporte e a participação."),
        RegiaoDemonstracao(id="serra", nome="Serra", contexto="Área interior com registros de avaliação e sem dados de participação na plataforma."),
    ),
    avaliacoes=tuple(
        AvaliacaoDemonstracao(
            escola_id=id_, avaliacao=avaliacao, edicao=edicao, serie="5º ano",
            disciplina=disciplina, resultado=base + variacao_edicao + variacao_disciplina,
        )
        for id_, _, _, _, _, _, _, _, base in _PONTOS
        for avaliacao, edicao, variacao_edicao in _CENARIOS_AVALIACAO
        for disciplina, variacao_disciplina in _DISCIPLINAS
    ),
)
