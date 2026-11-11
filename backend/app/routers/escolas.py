from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import tempo
from app.core.database import get_db, leitura_sem_transacao
from app.core.deps import (
    exigir_admin_global,
    exigir_papeis,
    get_usuario_atual,
    negar_secretaria,
)
from app.models import Escola, Nota, Usuario
from app.schemas import EscolaCreate, EscolaOut, EscolaUpdate
from app.services import permissoes, provisionamento
from app.services.audit import registrar

router = APIRouter(prefix="/escolas", tags=["Escolas"])


@router.get("", response_model=list[EscolaOut])
@leitura_sem_transacao
def listar(
    incluir_inativas: bool = Query(default=False),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Seletor ESCOLA da página inicial (PRD §10, §20). O admin GLOBAL pode
    pedir também as inativas (tela Escolas) — sem isso, uma escola inativada
    sumiria de todas as listas sem caminho de volta."""
    consulta = select(Escola).order_by(Escola.nome)
    if not (incluir_inativas and usuario.is_global):
        consulta = consulta.where(Escola.status == "ativa")
    if not usuario.is_global:
        # Secretaria (rede vinculada): vê TODAS as escolas da rede dela; usuário
        # de escola única continua preso à própria escola.
        if usuario.rede_id is not None:
            consulta = consulta.where(Escola.rede_id == usuario.rede_id)
        else:
            consulta = consulta.where(Escola.id == usuario.escola_id)
    return db.execute(consulta).scalars().all()


@router.post("", response_model=EscolaOut, status_code=status.HTTP_201_CREATED)
def criar(
    dados: EscolaCreate,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Criar novas escolas é exclusivo de administradores globais (§136).
    Um admin local não pode inventar escolas fora do seu domínio."""
    nome = dados.nome.strip()
    # Nome repetido criaria um segundo "inquilino" indistinguível no seletor
    # de escolas — recusa aqui (um clique duplo/reenvio nunca duplica a rede).
    repetida = db.execute(
        select(Escola).where(func.lower(Escola.nome) == nome.lower())
    ).scalar_one_or_none()
    if repetida is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe uma escola chamada “{repetida.nome}”.")
    escola = Escola(**{**dados.model_dump(), "nome": nome})
    db.add(escola)
    db.flush()
    # Provisiona a config de partida (pesos, níveis de dificuldade, referências)
    # para a escola nascer pronta — sem isso, uma escola criada pela interface
    # ficava sem níveis e caía no beco de "cadastre os níveis de dificuldade".
    provisionamento.semear_config_inicial(db, escola.id)
    registrar(db, "escola.criada", escola_id=escola.id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola.id, detalhes={"nome": escola.nome})
    db.commit()
    db.refresh(escola)
    return escola


@router.patch("/{escola_id}", response_model=EscolaOut)
def atualizar(
    escola_id: int,
    dados: EscolaUpdate,
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
    _sem_secretaria: Usuario = Depends(negar_secretaria),
):
    # A Secretaria não altera escola (a regra central de `escola_autorizada`):
    # a conta promovida a Secretaria guarda o cargo e o `escola_id` de origem, e
    # sem o `negar_secretaria` renomeava ou inativava a escola de onde veio.
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    # A Secretaria não altera escola (mesma régua de `deps.escola_autorizada`, que
    # esta rota não usa). Sem isto, a conta PROMOVIDA a partir de um admin de escola
    # — guarda cargo e `escola_id` de origem — renomeava ou inativava a escola.
    if permissoes.e_secretaria(usuario):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "A Secretaria acompanha os dados da rede, mas não altera dados da escola.")
    if not usuario.is_global and usuario.escola_id != escola_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso negado a esta escola.")
    alteracoes = dados.model_dump(exclude_unset=True)
    # `status` e `ano_letivo_ativo` são NOT NULL: um `null` explícito passava
    # pelas travas abaixo (que olham só valor presente) e virava 500 no commit.
    nulos = [campo for campo in ("status", "ano_letivo_ativo")
             if campo in alteracoes and alteracoes[campo] is None]
    if nulos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Campo(s) que não aceitam vazio: {', '.join(nulos)}.")
    novo_status = alteracoes.get("status")
    if novo_status is not None and novo_status != escola.status and not usuario.is_global:
        # ATIVAR/INATIVAR é decisão da rede, como o ano letivo: a tela que faz isso
        # (Escolas) é só do Admin Global. Antes, o admin LOCAL desfazia pela API a
        # inativação feita pelo global (ou inativava a própria escola). Mandar o
        # status que a escola já tem segue aceito (cliente que reenvia o objeto).
        # O que "inativa" significa para o ACESSO (hoje só some das listas e do
        # painel público) é decisão pendente: docs/operacao/STATUS-ESCOLA-REDE.md.
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Só o administrador global ativa ou inativa escolas.")
    if "nome" in alteracoes:
        # Nome vazio (ou só espaços, ou null) deixava a escola sem nome no seletor
        # e nos relatórios; acima de 200 caracteres o PostgreSQL recusa a coluna
        # com 500. Mesmo limite do cadastro (``EscolaCreate``: 2 a 200). Unicidade
        # NÃO é exigida na edição: só o cadastro tem essa regra (decisão do dono).
        nome = (alteracoes["nome"] or "").strip()
        if not 2 <= len(nome) <= 200:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "O nome da escola precisa ter de 2 a 200 caracteres.")
        alteracoes["nome"] = nome
    novo_ano = alteracoes.get("ano_letivo_ativo")
    notas_descartadas: dict[str, int] = {}
    if novo_ano is not None and novo_ano != escola.ano_letivo_ativo:
        # HISTÓRICO PROTEGIDO: o recálculo grava as Notas do ANO ATIVO com os
        # snapshots/leituras ATUAIS. Voltar o ano ativo para antes de um ano com
        # notas de histórico reescreveria esse histórico com dados de hoje —
        # recusado para qualquer perfil. Avançar o ano é decisão da rede: só o
        # Admin Global.
        if not usuario.is_global:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Só o administrador global altera o ano letivo ativo.")
        # Histórico = as notas dos anos já ENCERRADOS (antes do ano ativo) e as de
        # um ano que já começou no calendário. As notas de um ano que ainda nem
        # começou (o ano ativo digitado adiante: 2072 em vez de 2027, gravado pela
        # Lista Piloto) não são histórico: voltar ao ano certo corrige o erro.
        ano_hoje = tempo.hoje_br().year
        anos_com_notas = db.execute(
            select(Nota.ano_letivo, func.count()).where(Nota.escola_id == escola_id)
            .group_by(Nota.ano_letivo)).all()
        historico = [ano for ano, _ in anos_com_notas
                     if ano < escola.ano_letivo_ativo or ano <= ano_hoje]
        if historico and novo_ano < max(historico):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Voltar o ano letivo ativo para {novo_ano} reescreveria o histórico de "
                f"notas de {max(historico)}. O histórico é protegido.")
        if novo_ano < escola.ano_letivo_ativo:
            # As notas dos anos DEPOIS do novo ano ativo (só as do ano que não
            # começou, pela regra acima) saem: são o cache do motor, refeito pelo
            # recálculo se a escola chegar a esse ano — e não ficam como um ano
            # fantasma nas telas. A contagem vai para a auditoria.
            notas_descartadas = {str(ano): n for ano, n in anos_com_notas if ano > novo_ano}
            if notas_descartadas:
                db.execute(delete(Nota).where(Nota.escola_id == escola_id,
                                              Nota.ano_letivo > novo_ano))
    for campo, valor in alteracoes.items():
        setattr(escola, campo, valor)
    registrar(db, "escola.atualizada", escola_id=escola.id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola.id,
              detalhes={**alteracoes, **({"notas_descartadas": notas_descartadas}
                                         if notas_descartadas else {})})
    db.commit()
    db.refresh(escola)
    return escola
