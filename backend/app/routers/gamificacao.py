"""Gamificação (PRD §64, §79–§84): mural, destaques, XP e conquistas."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import Aluno, Configuracao, Escola, Usuario
from app.services import gamificacao as svc
from app.services import permissoes
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/gamificacao", tags=["Gamificação"])


@router.get("/mural")
def mural(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Mural da escola: Aluno do Dia/Semana/Mês + eventos recentes (§83).
    Vitrine da ESCOLA TODA — professor não acessa (gamificação só dos seus)."""
    permissoes.negar_restrito(db, escola_id, usuario)
    return svc.mural(db, escola_id)


@router.get("/ranking-xp")
def ranking_xp(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking por XP/nível — motivacional, separado das notas (§81).
    Professor recebe apenas os alunos das turmas dele."""
    itens = svc.ranking_xp(db, escola_id)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        escola = db.get(Escola, escola_id)
        alunos = permissoes.alunos_permitidos(db, escola_id,
                                              escola.ano_letivo_ativo, permitidas)
        itens = permissoes.filtrar_por_aluno(itens, alunos)
    return itens


@router.get("/alunos/{aluno_id}")
def gamificacao_do_aluno(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """XP, nível, sequência e todas as conquistas (com progresso) do aluno.
    Professor: apenas alunos das turmas dele."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    escola = db.get(Escola, escola_id)
    permissoes.exigir_aluno_permitido(db, escola_id, escola.ano_letivo_ativo,
                                      usuario, aluno_id)
    resultado = svc.gamificacao_do_aluno(db, escola_id, aluno_id)
    resultado["nome"] = aluno.nome
    return resultado


# --- Biblioteca de Conquistas --------------------------------------------------

@router.get("/biblioteca")
def biblioteca(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Catálogo completo de conquistas (inclusive inativas e nunca
    desbloqueadas) + desbloqueios por conquista + painel de estatísticas."""
    return svc.biblioteca(db, escola_id)


# --- Configurações → Conquistas (painel administrativo) ------------------------

class ConquistaDef(BaseModel):
    """Definição editável — nada de critério fixo no código."""
    codigo: str = ""                       # vazio = nova (o servidor gera o slug)
    nome: str = Field(min_length=2, max_length=80)
    icone: str = Field(default="🏅", max_length=8)
    descricao: str = Field(default="", max_length=300)
    objetivo: str = Field(default="", max_length=300)
    indicador: str
    limite: float = Field(gt=0, le=1_000_000)
    plataforma: str = Field(default="", pattern="^(elefante|matific|geral)?$")
    xp: int = Field(ge=0, le=100_000)
    raridade: str = Field(pattern="^(comum|rara|epica|lendaria)$")
    ativa: bool = True
    criada_em: str = ""

    def para_config(self, ordem: int, existentes: set[str]) -> dict:
        codigo = self.codigo or svc.gerar_codigo(self.nome, existentes)
        info = svc.INDICADORES[self.indicador]
        return {
            "codigo": codigo, "nome": self.nome.strip(), "icone": self.icone,
            "descricao": self.descricao.strip(), "objetivo": self.objetivo.strip(),
            "indicador": self.indicador, "limite": self.limite,
            "plataforma": self.plataforma or info["plataforma"],
            "xp": self.xp, "raridade": self.raridade, "ordem": ordem,
            "ativa": self.ativa,
            "criada_em": self.criada_em or date.today().isoformat(),
        }


class ListaConquistas(BaseModel):
    conquistas: list[ConquistaDef] = Field(max_length=100)


@router.get("/conquistas/definicoes")
def obter_definicoes(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    return {
        "conquistas": svc.listar_conquistas(db, escola_id, incluir_inativas=True),
        "indicadores": {
            chave: {"rotulo": info["rotulo"], "plataforma": info["plataforma"],
                    "unidade": info["unidade"]}
            for chave, info in svc.INDICADORES.items()
        },
        "raridades": svc.NOMES_RARIDADE,
        "xp_sugerido": svc.XP_POR_RARIDADE,
    }


@router.put("/conquistas/definicoes")
def salvar_definicoes(
    dados: ListaConquistas,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Grava a lista completa (a ordem enviada é a ordem de exibição).
    Novas conquistas passam a valer imediatamente em todo o sistema."""
    if not dados.conquistas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Cadastre pelo menos uma conquista.")
    for item in dados.conquistas:
        if item.indicador not in svc.INDICADORES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Indicador desconhecido: {item.indicador!r}. Válidos: "
                f"{', '.join(svc.INDICADORES)}.")

    lista: list[dict] = []
    codigos: set[str] = set()
    for ordem, item in enumerate(dados.conquistas):
        definicao = item.para_config(ordem, codigos)
        if definicao["codigo"] in codigos:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Código repetido: “{definicao['codigo']}”.")
        codigos.add(definicao["codigo"])
        lista.append(definicao)

    linha = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "gamificacao.conquistas",
            Configuracao.chave == "lista",
        )
    ).scalar_one_or_none()
    if linha is None:
        db.add(Configuracao(escola_id=escola_id, namespace="gamificacao.conquistas",
                            chave="lista", valor=lista))
    else:
        linha.valor = lista
    registrar(db, "conquistas.configuradas", escola_id=escola_id,
              usuario_id=usuario.id, entidade="configuracao",
              detalhes={"total": len(lista),
                        "codigos": [c["codigo"] for c in lista]})
    db.commit()
    return {"mensagem": f"{len(lista)} conquistas salvas. As mudanças já valem "
                        "para todos os alunos.",
            "conquistas": svc.listar_conquistas(db, escola_id,
                                                incluir_inativas=True)}
