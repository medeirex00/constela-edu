"""Lado do professor (consumido pelo Edu web): cartões de acesso.

Permissões idênticas às demais rotas do Edu: papel validado no backend e
isolamento por escola via escola_autorizada.
"""
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import bloquear_escola_para_cartoes_quest, get_db
from app.core.deps import escola_autorizada, exigir_papeis, negar_secretaria
from app.models import Aluno, Escola, Turma, Usuario
from app.quest import schemas
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.services import cartoes_pdf
from app.quest.services import credenciais as svc
from app.services import permissoes
from app.services import relatorios as svc_relatorios
from app.services.audit import registrar

# Rotas OPERACIONAIS de credencial do aluno (código de login / cartões). O
# `codigo_login` É a credencial de acesso da criança no Quest (não há senha), e
# a Secretaria (rede vinculada, não-global) enxerga TODA escola da rede — sem
# esta trava ela leria/geraria o segredo de login de qualquer criança da rede.
# A Secretaria acompanha resultados agregados, não opera as escolas → barrada.
router = APIRouter(prefix="/escolas/{escola_id}/quest",
                   tags=["Quest — Professor"],
                   dependencies=[Depends(negar_secretaria)])

PODE_GERAR = exigir_papeis("admin", "coordenador", "professor")


def _turma_da_escola(db: Session, escola_id: int, turma_id: int) -> Turma:
    turma = db.get(Turma, turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    return turma


def _exigir_reimpressao_no_ano_ativo(turma: Turma, escola: Escola | None) -> None:
    """Reimpressão (sem revogação) da folha de uma turma de OUTRO ano letivo: 409.

    A turma de outro ano lista as matrículas daquele ano (histórico), mas a
    credencial é uma por criança: a folha sairia com o nome da turma velha em cada
    cartão ("3º Ano A" para quem já está no "4º Ano A") e criaria credencial e
    perfil para quem não tinha. O cartão sai na turma atual da criança.

    A revogação (``regenerar``/``rotacionar_codigo``) dessa turma segue valendo:
    depois da virada, é o caminho em lote que derruba o cartão de quem saiu da
    escola e segue com a ficha ativa (G_VIRADA-2, decisão pendente do dono)."""
    ano = escola.ano_letivo_ativo if escola is not None else None
    if ano is None or turma.ano_letivo == ano:
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"A turma “{turma.nome}” é do ano letivo {turma.ano_letivo}, e as matrículas "
        "dela são histórico. Os cartões do Quest saem com o nome da turma, e cada "
        f"criança já está na turma dela do ano letivo {ano}. Nenhum cartão foi gerado. "
        f"Para imprimir os cartões, abra a turma atual da criança, do ano letivo {ano}.")


def _slug_ascii(texto: str) -> str:
    # Cabeçalho HTTP só aceita ASCII: "3º Ano A" → "3-ano-a"
    limpo = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore")
    return "-".join(limpo.decode().lower().split()) or "turma"


def _resposta_pdf(pdf: bytes, nome_arquivo: str) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


def _revogar_cartao_de_inativo(db: Session, escola_id: int, usuario: Usuario,
                               aluno: Aluno, regenerar: bool) -> Response:
    """Revogação pedida para ficha inativa: código e QR novos e sessões
    derrubadas, SEM cartão novo (204). Sem credencial não há o que revogar, e a
    ficha inativa não ganha uma: 422, como na reimpressão."""
    credencial = svc.credencial_do_aluno(db, aluno.id)
    if credencial is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Aluno inativo não recebe cartão.")
    svc.revogar_cartao(db, credencial)
    registrar(db, "quest.cartao_revogado_inativo", escola_id=escola_id,
              usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
              detalhes={"regenerou": regenerar, "rotacionou_codigo": True,
                        "status_aluno": aluno.status})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _montar_cartoes(dados: list[dict]) -> list[dict]:
    return [{
        "nome": item["aluno"].nome,
        "apelido": item["perfil"].apelido,
        # No cartão da criança o código sai legível (LUA-FAROL-731); o valor
        # consultado no login é o HMAC do normalizado (sem hífen).
        "codigo": svc.formatar_codigo_exibicao(
            svc.codigo_para_exibicao(item["credencial"])),
        "qr_url": svc.url_qr(item["credencial"]),
    } for item in dados]


@router.get("/turmas/{turma_id}/acessos",
            response_model=list[schemas.AcessoAlunoOut])
def acessos_da_turma(turma_id: int,
                     escola_id: int = Depends(escola_autorizada),
                     usuario: Usuario = Depends(PODE_GERAR),
                     db: Session = Depends(get_db)):
    """Situação de acesso de cada aluno — alimenta a tela do Edu."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    # Professor restrito só vê as turmas dele — o código de login (credencial do
    # aluno na Quest) não pode vazar para turmas de outros professores.
    permissoes.exigir_turma_permitida(db, escola_id, usuario, turma_id)
    alunos = svc.alunos_da_turma(db, escola_id, turma)
    ids = [aluno.id for aluno in alunos]
    # Carrega credenciais e perfis da turma em 2 consultas (aluno_id IN (...)),
    # não 2 por aluno — evita N+1 numa turma de N (era 2N+1 idas ao banco).
    # aluno_id é UNIQUE em ambas as tabelas, então há no máx. 1 por aluno.
    credenciais = {c.aluno_id: c for c in db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id.in_(ids))
    ).scalars()} if ids else {}
    perfis = {p.aluno_id: p for p in db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id.in_(ids))
    ).scalars()} if ids else {}
    saida: list[schemas.AcessoAlunoOut] = []
    for aluno in alunos:
        credencial = credenciais.get(aluno.id)
        perfil = perfis.get(aluno.id)
        saida.append(schemas.AcessoAlunoOut(
            aluno_id=aluno.id,
            nome=aluno.nome,
            nome_exibicao=perfil.nome_exibicao if perfil else None,
            apelido=perfil.apelido if perfil else None,
            codigo_login=(svc.codigo_para_exibicao(credencial)
                          if credencial else None),
            ultimo_acesso=credencial.ultimo_acesso if credencial else None,
            tem_credencial=credencial is not None,
        ))
    return saida


@router.post("/turmas/{turma_id}/cartoes")
def gerar_cartoes(turma_id: int,
                  regenerar: bool = False,
                  rotacionar_codigo: bool = False,
                  escola_id: int = Depends(escola_autorizada),
                  usuario: Usuario = Depends(PODE_GERAR),
                  db: Session = Depends(get_db)):
    """Gera (ou regenera) credenciais da turma e devolve o PDF dos cartões
    + a parte "só do professor" (tabela nome → código e roteiro da 1ª aula).

    Sem parâmetro é reimpressão: código e QR de cada aluno continuam os mesmos.

    `regenerar=true` revoga os cartões de TODOS os alunos da turma: código e QR
    novos, sessões antigas derrubadas — os cartões impressos antes deixam de
    entrar. Isso inclui quem está INATIVO naquela hora (arquivado, transferido,
    fora da Lista Piloto): o cartão dele cai também, sem entrar no PDF, e a
    reativação posterior não reabre o cartão nem as sessões antigas (a auditoria
    conta os revogados inativos). E inclui quem estava numa folha da turma impressa
    desde a última revogação dela e depois TROCOU de turma (a auditoria de cada
    folha guarda os ``aluno_ids`` do PDF): o cartão dele cai também, sem entrar no
    PDF — o novo sai na turma em que ele está agora —, e a auditoria traz
    ``revogados_fora_da_turma`` (e os ids). Para um cartão perdido ou em mãos
    erradas, use o individual (POST /alunos/{id}/cartao?regenerar=true), que não
    derruba a turma.

    `rotacionar_codigo=true` tem o mesmo efeito (nome mantido por
    compatibilidade; virada de ano letivo). Sem expiração automática durante o
    ano — a criança nunca perde acesso sozinha.

    Turma de OUTRO ano letivo: a reimpressão é 409 (o cartão sairia com o nome
    da turma velha); a revogação segue valendo (``_exigir_reimpressao_no_ano_ativo``).
    """
    turma = _turma_da_escola(db, escola_id, turma_id)
    # Professor restrito não gera/regenera/rotaciona credenciais de turma alheia
    # (troca o QR/código de todos e derruba sessões — antes do efeito).
    permissoes.exigir_turma_permitida(db, escola_id, usuario, turma_id)
    revogar = regenerar or rotacionar_codigo
    escola = db.get(Escola, escola_id)
    if revogar:
        # Antes de ler ou travar qualquer credencial: duas revogações de turma da
        # mesma escola (troca cruzada de crianças desde a última folha) travavam as
        # credenciais em ordens opostas — deadlock no PostgreSQL, 500 numa delas.
        bloquear_escola_para_cartoes_quest(db, escola_id)
    else:
        _exigir_reimpressao_no_ano_ativo(turma, escola)
    revogados_inativos = (svc.revogar_cartoes_inativos_da_turma(db, escola_id, turma)
                          if revogar else 0)
    # Lê as folhas ANTERIORES (a auditoria desta ainda não foi gravada).
    revogados_fora = (svc.revogar_cartoes_que_sairam_da_turma(db, escola_id, turma)
                      if revogar else [])
    dados = svc.garantir_credenciais_turma(
        db, escola_id, turma, regenerar=regenerar,
        rotacionar_codigo=rotacionar_codigo)
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        escola_nome=escola.nome if escola else "Escola",
        cor=svc_relatorios.cor_primaria(db, escola_id),
        turma_nome=turma.nome,
        cartoes=_montar_cartoes(dados),
    )

    # `regenerar` também troca o código: o log registra o que aconteceu. Os
    # `aluno_ids` do PDF são a memória de quem esteve NESTA folha: o próximo
    # regenerar da turma revoga quem saiu dela (a matrícula não guarda histórico).
    registrar(db, svc.ACAO_FOLHA_DA_TURMA, escola_id=escola_id,
              usuario_id=usuario.id, entidade="turma", entidade_id=turma.id,
              detalhes={"alunos": len(dados), "regenerou": regenerar,
                        "rotacionou_codigo": revogar,
                        "revogados_inativos": revogados_inativos,
                        "revogados_fora_da_turma": len(revogados_fora),
                        "revogados_fora_da_turma_ids": revogados_fora,
                        "aluno_ids": svc.aluno_ids_da_folha(dados)})
    db.commit()
    return _resposta_pdf(pdf, f"cartoes-quest-{_slug_ascii(turma.nome)}.pdf")


@router.post("/alunos/{aluno_id}/cartao")
def gerar_cartao_individual(aluno_id: int,
                            regenerar: bool = False,
                            rotacionar_codigo: bool = False,
                            escola_id: int = Depends(escola_autorizada),
                            usuario: Usuario = Depends(PODE_GERAR),
                            db: Session = Depends(get_db)):
    """Cartão de UM aluno — cartão perdido não derruba a turma inteira.

    Sem parâmetro é reimpressão (mesmo código, mesmo QR). `regenerar=true` (ou
    `rotacionar_codigo=true`, mesmo efeito) revoga o cartão desse aluno: código
    e QR novos e as sessões dele caem; os colegas seguem intocados.

    Aluno INATIVO não recebe cartão (422 na reimpressão — "cartão descansando").
    Com `regenerar`/`rotacionar_codigo`, o cartão dele é revogado mesmo assim, sem
    emitir cartão novo: 204, sem PDF. A reativação posterior não reabre o cartão
    nem as sessões antigas; sem revogação pedida, a criança que volta segue com o
    mesmo cartão.
    """
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    revogar = regenerar or rotacionar_codigo
    inativo = aluno.status != "ativo"
    if inativo and not revogar:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Aluno inativo não recebe cartão.")
    escola = db.get(Escola, escola_id)
    # Professor restrito só gera cartão de aluno das turmas dele (antes de criar,
    # regenerar ou rotacionar a credencial). Para revogar o de quem está inativo,
    # a matrícula na turma dele basta (o status não o tira da turma).
    permissoes.exigir_aluno_permitido(db, escola_id, escola.ano_letivo_ativo,
                                      usuario, aluno_id, incluir_inativos=inativo)
    if inativo:
        return _revogar_cartao_de_inativo(db, escola_id, usuario, aluno, regenerar)

    item = svc.garantir_credencial_aluno(db, escola_id, aluno,
                                         regenerar=regenerar,
                                         rotacionar_codigo=rotacionar_codigo)
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        escola_nome=escola.nome if escola else "Escola",
        cor=svc_relatorios.cor_primaria(db, escola_id),
        turma_nome="",
        cartoes=_montar_cartoes([item]),
        com_pagina_professor=False,
    )

    registrar(db, "quest.cartao_individual", escola_id=escola_id,
              usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
              detalhes={"regenerou": regenerar,
                        "rotacionou_codigo": regenerar or rotacionar_codigo})
    db.commit()
    return _resposta_pdf(pdf, f"cartao-quest-{_slug_ascii(aluno.nome)}.pdf")
