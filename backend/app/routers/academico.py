import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import email_reservado_ao_dono
from app.core.database import bloquear_escola_para_importacao, get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.core.tempo import hoje_br
from app.models import (
    Aluno,
    Escola,
    Leitura,
    Livro,
    Matricula,
    Nota,
    Professor,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.routers.rankings import _ranking
from app.schemas import (
    AcaoAlunos,
    AlunoCreate,
    AlunoGestaoOut,
    AlunoOut,
    AlunoPerfilOut,
    AlunoUpdate,
    ConsolidarTurmasIn,
    CorrigirDuplicadosAlunos,
    ExclusaoPermanenteAlunos,
    ExcluirTurmas,
    FusaoAlunos,
    ProfessorCompletoIn,
    ProfessorCreate,
    ProfessorOut,
    ProfessorUpdate,
    TurmaCreate,
    TurmaOut,
    TurmaUpdate,
)
from app.services import (
    alunos_dedup,
    alunos_fusao,
    elegibilidade,
    identidade_aluno,
    identidade_efetiva,
    matching,
    periodos,
    permissoes,
    scoring,
    turma_arquivada,
    turmas_dedup,
)
from app.services import dificuldade_livro
from app.services import dimensoes as svc_dimensoes
from app.services import modulos as svc_modulos
from app.services.audit import registrar
# A trava do destino mora em ``services.turma_arquivada`` (o /resolver de
# ``routers.importacoes`` também a usa); o nome antigo continua valendo aqui.
from app.services.turma_arquivada import (
    exigir_destino_do_ano_ativo as _exigir_destino_do_ano_ativo,
)

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Acadêmico"])


def _ano_ativo(db: Session, escola_id: int) -> int:
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    return escola.ano_letivo_ativo


def _blindar_superficial(saida: AlunoOut) -> AlunoOut:
    """Professor vê APENAS dados superficiais do aluno (posição no ranking e
    pontos — modelo de permissões, permissoes.py). data_nascimento e observacoes
    (campo livre, potencialmente sensível) pertencem ao cadastro, não à visão
    superficial: são zerados antes de sair na resposta."""
    saida.data_nascimento = None
    saida.observacoes = None
    return saida


# --- Alunos -----------------------------------------------------------------

@router.get("/alunos", response_model=dict)
def listar_alunos(
    escola_id: int = Depends(escola_autorizada),
    busca: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    # Teto de 100 virou 1000: a tela de Certificados pede UMA página e monta o
    # seletor com ela. Com 100 no teto, as quatro escolas da rede que passam de
    # 100 ativos (110, 243, 467 e 532) simplesmente não conseguiam emitir
    # certificado para quem ficasse fora dos 100 primeiros nomes — sem erro
    # nenhum na tela, o aluno só não existia na lista. O default segue 25.
    por_pagina: int = Query(default=25, ge=1, le=1000),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Lista paginada (PRD §23) com busca e filtros (PRD §53)."""
    ano = _ano_ativo(db, escola_id)
    consulta = (
        select(Aluno, Turma)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(
            Aluno.escola_id == escola_id,
            Matricula.ano_letivo == ano,
            Aluno.status == "ativo",
        )
    )
    if busca:
        consulta = consulta.where(Aluno.nome.ilike(f"%{busca}%"))
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    # Professor: enxerga apenas os alunos das turmas designadas a ele.
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        consulta = consulta.where(Turma.id.in_(permitidas))

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    linhas = db.execute(
        consulta.order_by(Aluno.nome).offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).all()

    superficial = not permissoes.acesso_total(usuario)
    itens = []
    for aluno, turma in linhas:
        item = AlunoOut.model_validate(aluno)
        item.turma = turma.nome
        item.ano_escolar = turma.ano_escolar
        if superficial:
            _blindar_superficial(item)
        itens.append(item)
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}


# Situação de uma ficha que não está ativa, como o cadastro manual a descreve.
_SITUACAO_INATIVA = {"arquivado": "arquivado", "transferido": "marcado como transferido",
                     "fora_lista_piloto": "fora da Lista Piloto", "excluido": "excluído"}
# O caminho para trazer de volta uma ficha que não está ativa (o mesmo que a recusa
# do certificado ensina): a lista de Alunos e o painel da turma só mostram os ativos.
_CAMINHO_REATIVAR = ("em Minha Escola › Turmas, abra esta turma, ligue “Mostrar "
                     "arquivados” e use “Reativar” no cadastro.")


def _parecidos_inativos(db: Session, escola_id: int, ano: int, turma: Turma,
                        dados: AlunoCreate, ra: str | None) -> list[Aluno]:
    """Os cadastros NÃO ATIVOS da turma que o motor de identidade achou parecidos
    com o nome digitado (correspondência insegura: os ``candidatos`` do REVISAR).

    Mesma pergunta que ``importacoes._casar_no_roster`` acabou de fazer — o mesmo
    roster (que não filtra situação) e o mesmo ``matching.classificar_linha`` —,
    refeita só no caminho da recusa para saber QUEM eram os candidatos."""
    from app.routers import importacoes as imp
    roster, por_id = imp._roster_identidades(db, escola_id, ano, turma.id)
    res = matching.classificar_linha(
        matching.Identidade(nome=dados.nome, chamada=dados.numero_chamada,
                            nascimento=dados.data_nascimento, ra=imp._ra_forte(ra)),
        roster)
    return [por_id[i] for i in res.candidatos
            if i in por_id and por_id[i].status != "ativo"]


def _mesma_crianca_na_escola(db: Session, escola_id: int, dados: AlunoCreate,
                             ra_informado: str | None) -> tuple[Aluno, str] | None:
    """A ficha que esta criança JÁ tem na escola, em qualquer turma e ano (não
    excluída), e o critério: ``"ra"`` (o mesmo RA, normalizado por ``ra_util``) ou
    ``"nome_nascimento"`` (o mesmo nome normalizado E o mesmo nascimento, sem RA
    divergente — RA diferente prova outra criança).

    A busca da turma de destino (``_aluno_existente_na_turma``/``_casar_no_roster``)
    não basta: na virada a turma do ano novo está vazia e a ficha do ano anterior
    nunca era candidata — nascia uma segunda ficha (no ranking com 0) e a coleta
    seguinte gravava o dado na antiga, fora de qualquer ranking. Só o nome igual não
    prova nada (homônimo é legítimo); o nº de chamada muda de um ano para o outro e
    não entra. Duas fichas achadas: a que está no ano/turma mais recente, a ativa."""
    from app.services._nomes import chave_nome
    from app.services.lista_piloto import ra_util
    ra = ra_util(ra_informado)
    alvo = chave_nome(dados.nome)
    nascimento = dados.data_nascimento
    achados: list[tuple[int, str]] = []
    for aluno_id, nome, nasc, ficha in db.execute(
        select(Aluno.id, Aluno.nome, Aluno.data_nascimento, Aluno.ficha)
        .where(Aluno.escola_id == escola_id, Aluno.status != "excluido")
    ).all():
        ra_dele = ra_util((ficha or {}).get("ra"))
        if ra and ra_dele == ra:
            achados.append((aluno_id, "ra"))
        elif (nascimento is not None and nasc == nascimento and chave_nome(nome) == alvo
              and not (ra and ra_dele)):
            achados.append((aluno_id, "nome_nascimento"))
    if not achados:
        return None
    ultimo_ano = dict(db.execute(
        select(Matricula.aluno_id, func.max(Matricula.ano_letivo))
        .where(Matricula.aluno_id.in_([i for i, _ in achados]))
        .group_by(Matricula.aluno_id)).all())
    fichas = {i: db.get(Aluno, i) for i, _ in achados}
    aluno_id, criterio = max(achados, key=lambda a: (
        a[1] == "ra", ultimo_ano.get(a[0]) or 0, fichas[a[0]].status == "ativo", -a[0]))
    return fichas[aluno_id], criterio


def _texto_ja_tem_ficha(db: Session, ja: Aluno, criterio: str, ano: int) -> str:
    """A recusa do cadastro quando a criança já tem ficha em OUTRA turma ou ano: onde
    a ficha está, a situação dela e o caminho para matriculá-la sem duplicar. A
    lista de Alunos só mostra quem tem matrícula ativa do ano: depois da virada, a
    ficha de 2026 se acha pela turma de 2026 (Turmas, com as de outros anos)."""
    ultima = db.execute(
        select(Turma.nome, Matricula.ano_letivo)
        .join(Turma, Turma.id == Matricula.turma_id)
        .where(Matricula.aluno_id == ja.id)
        .order_by(Matricula.ano_letivo.desc(), Matricula.id.desc())).first()
    inativa = ja.status != "ativo"
    deste_ano = ultima is not None and ultima[1] == ano
    onde = f"{ultima[0]}, {ultima[1]}" if ultima else "sem turma"
    por = "com o mesmo RA" if criterio == "ra" else "com o mesmo nome e nascimento"
    texto = f"Esta criança já tem ficha nesta escola: “{ja.nome}” ({onde}), {por}."
    if inativa:
        texto += f" O cadastro dela está {_SITUACAO_INATIVA.get(ja.status, ja.status)}."
    if ultima is None or (deste_ano and not inativa):
        caminho = "abra a ficha dela"
    else:
        caminho = "em Minha Escola › Turmas, "
        if not deste_ano:
            caminho += "ligue “Mostrar arquivadas e de outros anos”, "
        caminho += f"abra a turma {ultima[0]}" + ("" if deste_ano else f" de {ultima[1]}")
        caminho += (", ligue “Mostrar arquivados”" if inativa else "") + ", abra a ficha dela"
    if inativa:
        caminho += ", use “Reativar”"
    meta = "mudar de turma" if deste_ano else f"matriculá-la em {ano}"
    return (f"{texto} Não cadastre de novo: {caminho} e use ⋮ › Editar dados › Turma "
            f"para {meta}. Se for outra criança, confira o RA e a data de nascimento.")


@router.post("/alunos", response_model=AlunoOut, status_code=status.HTTP_201_CREATED)
def criar_aluno(
    dados: AlunoCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    ano = _ano_ativo(db, escola_id)
    # Mesma trava das importações: serializa a criação de alunos da MESMA escola,
    # senão dois cadastros simultâneos leem "não existe" e criam os dois. É
    # transacional (cai no commit) e no-op no SQLite.
    bloquear_escola_para_importacao(db, escola_id)
    turma = db.get(Turma, dados.turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida para esta escola.")
    # D17 (T24): aluno novo não nasce em turma arquivada — antes de qualquer
    # consulta de identidade ou auditoria.
    turma_arquivada.exigir_turma_ativa(turma)
    # Nem em turma de OUTRO ano letivo: a matrícula que nasce é a do ano ativo.
    _exigir_destino_do_ano_ativo(turma, ano)

    # Ficha cadastral: só as chaves conhecidas (mesmas da Lista Piloto) e
    # valores curtos — nada de dados arbitrários no JSON.
    from app.services.lista_piloto import ROTULOS_FICHA
    ficha = {chave: str(valor).strip()[:300]
             for chave, valor in (dados.ficha or {}).items()
             if chave in ROTULOS_FICHA and str(valor).strip()}

    # PORTA ÚNICA DE IDENTIDADE: o cadastro manual era o último caminho que criava
    # aluno sem perguntar "essa pessoa já existe?". Passa pela MESMA resolução das
    # importações. Homônimo REAL continua podendo ser cadastrado: o veto por
    # identidade (nº de chamada / nascimento / RA divergentes) faz o candidato não
    # casar, e aí a criação segue normalmente.
    from app.routers import importacoes as imp
    ra_informado = str(ficha.get("ra", "")).strip() or None
    ja = imp._aluno_existente_na_turma(db, escola_id, ano, turma.id, dados.nome,
                                       dados.numero_chamada, dados.data_nascimento,
                                       ra_informado)
    confianca = "baixa"
    if ja is None:
        ja, confianca = imp._casar_no_roster(db, escola_id, ano, dados.nome, turma,
                                             dados.numero_chamada,
                                             dados.data_nascimento, ra_informado)
    # A porta única reconhece de propósito as fichas ARQUIVADAS, transferidas e fora
    # da Lista Piloto da turma (não duplicar a criança). Mas a lista de Alunos e o
    # painel da turma só mostram os ativos: a recusa diz a situação da ficha e o
    # caminho para trazê-la de volta, em vez de mandar "usar o cadastro existente"
    # que o gestor não encontra.
    if ja is not None:
        registrar(db, "aluno.criacao_recusada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", entidade_id=ja.id,
                  detalhes={"nome": dados.nome, "decisao": "EXACT_MATCH",
                            "motivo": "aluno_ja_cadastrado_na_turma"})
        db.commit()
        if ja.status != "ativo":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"“{ja.nome}” já tem cadastro nesta turma, mas ele está "
                f"{_SITUACAO_INATIVA.get(ja.status, ja.status)} — por isso não aparece "
                f"na lista de Alunos. Não cadastre de novo: {_CAMINHO_REATIVAR} Se for "
                "outra criança de mesmo nome, informe o nº de chamada ou a data de "
                "nascimento para diferenciar.")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{ja.nome}” já está cadastrado nesta turma. Use o cadastro existente. "
            "Se for outra criança de mesmo nome, informe o nº de chamada ou a data "
            "de nascimento para diferenciar.")
    if confianca == "media":
        registrar(db, "aluno.criacao_recusada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", entidade_id=None,
                  detalhes={"nome": dados.nome, "decisao": "REVIEW_REQUIRED",
                            "motivo": "correspondencia_insegura"})
        db.commit()
        inativos = _parecidos_inativos(db, escola_id, ano, turma, dados, ra_informado)
        if inativos:
            nomes = ", ".join(
                f"“{a.nome}” ({_SITUACAO_INATIVA.get(a.status, a.status)})" for a in inativos)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"“{dados.nome}” é muito parecido com um cadastro desta turma que não "
                f"aparece na lista de Alunos: {nomes}. Confira antes de cadastrar. Se "
                f"for a mesma criança, não cadastre de novo: {_CAMINHO_REATIVAR} Se for "
                "outra criança, informe o nº de chamada ou a data de nascimento para "
                "diferenciar.")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{dados.nome}” é muito parecido com um aluno já cadastrado nesta turma. "
            "Confira a lista da turma antes de cadastrar. Se for outra criança, informe "
            "o nº de chamada ou a data de nascimento para diferenciar.")

    # A MESMA criança em outra turma ou outro ano (G_VIRADA-3): a rematrícula do ano
    # novo pelo cadastro abria uma 2ª ficha, e a coleta seguinte gravava o dado na
    # antiga, fora do ranking. A ficha certa ganha a turma por Editar dados › Turma.
    outra = _mesma_crianca_na_escola(db, escola_id, dados, ra_informado)
    if outra is not None:
        ja, criterio = outra
        registrar(db, "aluno.criacao_recusada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", entidade_id=ja.id,
                  detalhes={"nome": dados.nome, "decisao": "EXACT_MATCH",
                            "motivo": "aluno_ja_cadastrado_na_escola",
                            "criterio": criterio})
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            _texto_ja_tem_ficha(db, ja, criterio, ano))

    aluno = Aluno(
        escola_id=escola_id,
        nome=dados.nome.strip(),
        numero_chamada=dados.numero_chamada,
        data_nascimento=dados.data_nascimento,
        observacoes=dados.observacoes,
        ficha=ficha,
    )
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=ano))
    registrar(db, "aluno.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno.id, detalhes={"nome": aluno.nome})
    db.commit()
    db.refresh(aluno)
    saida = AlunoOut.model_validate(aluno)
    saida.turma = turma.nome
    saida.ano_escolar = turma.ano_escolar
    return saida


@router.get("/alunos/{aluno_id}/perfil", response_model=AlunoPerfilOut)
def perfil_aluno(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Perfil com a explicação completa da nota (PRD §45, §54).

    Professor: só alunos das turmas dele. Vê as notas, a posição e o PASSO A
    PASSO do cálculo (liberado pelo dono); a ficha cadastral (dados pessoais) e a
    distribuição de leituras seguem restritas à gestão."""
    ano = _ano_ativo(db, escola_id)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    permissoes.exigir_aluno_permitido(db, escola_id, ano, usuario, aluno_id)
    superficial = not permissoes.acesso_total(usuario)

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id, Matricula.ano_letivo == ano)
    ).first()
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id, Nota.ano_letivo == ano)
    ).scalar_one_or_none()

    saida = AlunoOut.model_validate(aluno)
    if superficial:
        _blindar_superficial(saida)
    ano_escolar = ""
    if matricula:
        saida.turma = matricula[1].nome
        saida.ano_escolar = matricula[1].ano_escolar
        ano_escolar = matricula[1].ano_escolar

    # Distribuição de leitura por faixa de dificuldade (gráfico + estatísticas).
    # Snapshot ATUAL por (data_referencia, id), não por max(id): um import
    # retroativo (backfill) grava id maior com data menor e NÃO pode virar o
    # estado atual. Mesma régua do dashboard/ranking (scoring.ids_snapshots_atuais).
    snap_e = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.escola_id == escola_id,
               SnapshotElefante.aluno_id == aluno_id,
               SnapshotElefante.id.in_(
                   scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)))
    ).scalar_one_or_none()
    # Mesma regra (e mesma turma) da nota anual; `livros_unicos` permite marcar
    # `incompleto` (livros contados sem distribuição por nível ≠ dificuldade 0).
    leitura_niveis = scoring.distribuicao_niveis(
        db, escola_id, snap_e.livros_por_nivel if snap_e else {}, ano_escolar,
        turma_id=matricula[1].id if matricula else None, aluno_id=aluno_id,
        livros_unicos=snap_e.livros_unicos if snap_e else None)

    # CONTRATO: a nota de plataforma de módulo que a rede não contratou sai nula
    # (mesma regra de ``rankings._ranking``), e o passo a passo / a distribuição
    # de leitura daquela plataforma não saem. A nota geral já vem do motor com os
    # pesos só dos módulos contratados.
    escola = db.get(Escola, escola_id)
    fora = svc_modulos.plataformas_fora_do_plano(svc_modulos.modulos_da_escola(db, escola))
    # CONTRATO com as telas: o desempenho POR DIMENSÃO (só as contratadas) é o que
    # separa "sem dado" de "zero". As notas de plataforma acima saem 0,0 para quem
    # não tem snapshot; é o `aferido` de cada bloco que faz a tela mostrar "—"
    # (``notaDaMateria``). Sem os blocos, a ficha afirmava 0,0 em Matemática para
    # a criança que nunca abriu o Matific. Quem TEM dado não muda: a nota do bloco
    # é a mesma coluna da Nota. A posição do bloco é a da ESCOLA inteira naquela
    # dimensão — não é a perspectiva do professor (ver ``_posicao_exibida``), então
    # ele não a recebe. Quem está FORA do ranking vigente (ficha inativa, sem
    # matrícula do ano, turma de Fase) também não: a posição gravada na Nota é de
    # um cálculo antigo e hoje pertence a outra criança (``_no_ranking_vigente``).
    no_ranking = _no_ranking_vigente(aluno, matricula)
    blocos_dimensao = svc_dimensoes.blocos(db, escola, nota)
    if superficial or not no_ranking:
        blocos_dimensao = [b.model_copy(update={"posicao": None}) for b in blocos_dimensao]
    return AlunoPerfilOut(
        aluno=saida,
        nota_matific=None if "matific" in fora else (nota.nota_matific if nota else 0.0),
        nota_elefante=(None if "elefante" in fora
                       else (nota.nota_elefante if nota else 0.0)),
        nota_geral=nota.nota_geral if nota else 0.0,
        posicao=_posicao_exibida(db, escola_id, ano, usuario, aluno_id, nota,
                                 no_ranking=no_ranking),
        dimensoes=blocos_dimensao,
        adocao=svc_dimensoes.adocao(db, escola, nota),
        # O professor também vê o PASSO A PASSO do cálculo (liberado pelo dono) —
        # só das crianças das turmas dele (exigir_aluno_permitido acima barra as
        # de fora). A ficha cadastral (dados pessoais) e as leituras seguem só p/
        # gestão.
        detalhes=_detalhes_no_plano(nota.detalhes if nota else {}, fora),
        calculada_em=nota.calculada_em if nota else None,
        leitura_niveis=(leitura_niveis if not superficial and "elefante" not in fora
                        else None),
        ficha=(aluno.ficha or {}) if not superficial else {},
    )


def _no_ranking_vigente(aluno: Aluno, matricula) -> bool:
    """A criança está na POPULAÇÃO do ranking do ano — a mesma do motor
    (``scoring._carregar_contexto``) e da guarda do certificado de mérito
    (``relatorios.exigir_merito``): ficha ativa, com matrícula no ano letivo ativo,
    numa turma que concorre (1º ao 5º ano, ``elegibilidade``). ``matricula`` é o
    par (Matricula, Turma) do ano letivo ativo, ou None.

    Fora dela, a Nota continua no banco (o recálculo não apaga a linha de quem
    sai: arquivado, transferido, excluído, Fase) com a posição de um cálculo
    antigo — que hoje pertence a outra criança."""
    return (aluno.status == "ativo" and matricula is not None
            and elegibilidade.participa_de_premiacao(matricula[1].ano_escolar))


def _posicao_exibida(db: Session, escola_id: int, ano: int, usuario: Usuario,
                     aluno_id: int, nota: Nota | None, *,
                     no_ranking: bool = True) -> int | None:
    """A posição do "Nº no ranking" do perfil, na MESMA perspectiva do ranking
    de onde o usuário veio (o toque na linha do Ranking abre este perfil, no app
    e na web — os dois leem esta rota).

    Gestão (sem recorte): a posição carimbada da escola (``Nota.posicao``) — só
    para quem está no ranking vigente (``no_ranking``, de ``_no_ranking_vigente``).
    A ficha arquivada, transferida, excluída, sem matrícula do ano ou de turma de
    Fase fica sem posição (``None``), como no ranking, que também não a mostra:
    antes a ficha arquivada dizia "1º no ranking" enquanto o 1º era outra criança.

    Professor (``turmas_permitidas`` não é None): a posição RELATIVA às turmas
    dele, com a mesma lista e a mesma ordem do ranking renumerado 1..N
    (``rankings._ranking`` com ``turma_ids``, como ``rankings.ranking_geral`` e
    o pacote ``/sincronizacao`` do app). Sem isso a aba dizia 1º e o perfil da
    mesma criança, para o mesmo professor, dizia 100º. Quem não está na lista
    (a Nota antiga de quem saiu da população, como a fase fora da premiação) fica
    sem posição (``None``), como no ranking, que também não o mostra.

    Nas duas perspectivas, a criança SEM NENHUM DADO (nem Leitura nem Matemática
    aferidas) fica sem posição e não entra na numeração: o Ranking Geral e o Top 10
    não a listam (``_ranking(so_com_dado=True)``, DEC-19 — ausência não é zero)."""
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if nota is None or not (nota.aferido_leitura or nota.aferido_matematica):
        return None
    if permitidas is None:
        return nota.posicao if no_ranking else None
    lista = _ranking(db, escola_id, ano, turma_ids=permitidas, so_com_dado=True)
    for posicao, item in enumerate(lista, start=1):
        if item.aluno_id == aluno_id:
            return posicao
    return None


def _detalhes_no_plano(detalhes: dict, fora: set[str]) -> dict:
    """O passo a passo da nota SEM o que é de plataforma fora do plano da rede.

    Tira o bloco da plataforma (indicadores brutos da criança) e as referências
    / a saturação dos indicadores dela, e NEUTRALIZA o bloco da dimensão dela em
    ``dimensoes`` (o motor grava ali a mesma nota, a posição, os dados brutos e
    a data do snapshot): fica como o motor escreve uma dimensão não contratada,
    sem nota, posição, dados nem ``snapshot_em``. A adoção e o
    ``geral.dimensoes_com_dados`` deixam de citar a plataforma.

    Vale também para a Nota gravada ANTES da mudança de contrato (escola
    vinculada a outra rede, recálculo que falhou): o filtro olha o contrato de
    AGORA, não o que estava em vigor quando a nota foi calculada. Os pesos de
    ``geral`` (configuração, sem dado da criança) ficam como o motor gravou,
    para a conta exibida bater com a ``nota_geral`` gravada.

    Só filtra a resposta — o que o motor gravou não muda. Tudo contratado (ou
    nota sem detalhes) → o dicionário intacto."""
    if not fora or not detalhes:
        return detalhes or {}
    saida = {chave: valor for chave, valor in detalhes.items() if chave not in fora}
    for chave in ("referencias", "saturacao"):
        bloco = saida.get(chave)
        if isinstance(bloco, dict):
            saida[chave] = {
                ind: valor for ind, valor in bloco.items()
                if scoring.DIMENSAO_DO_INDICADOR.get(ind.removeprefix("max_")) not in fora}
    dims_fora = {dim for dim, plataforma in scoring.DIMENSOES.items() if plataforma in fora}
    dimensoes = saida.get("dimensoes")
    if isinstance(dimensoes, dict):
        saida["dimensoes"] = {
            dim: (_dimensao_fora_do_plano(bloco)
                  if dim in dims_fora or (isinstance(bloco, dict)
                                          and bloco.get("plataforma") in fora)
                  else bloco)
            for dim, bloco in dimensoes.items()}
    adocao = saida.get("adocao")
    if isinstance(adocao, dict):
        contratadas = [d for d in adocao.get("contratadas") or [] if d not in dims_fora]
        com_dados = [d for d in adocao.get("com_dados") or [] if d not in dims_fora]
        # Mesma conta do motor (|D| / |P|, ``scoring._ordenar_por_dimensao``)
        # sobre as dimensões do plano de agora: com a nota já recalculada no
        # contrato atual, o número é o mesmo que o motor gravou.
        saida["adocao"] = {
            **adocao, "contratadas": contratadas, "com_dados": com_dados,
            "pct": (round(len(com_dados) / len(contratadas) * 100, 2)
                    if contratadas else 0.0)}
    geral = saida.get("geral")
    if isinstance(geral, dict) and isinstance(geral.get("dimensoes_com_dados"), list):
        saida["geral"] = {**geral, "dimensoes_com_dados": [
            p for p in geral["dimensoes_com_dados"] if p not in fora]}
    return saida


def _dimensao_fora_do_plano(bloco) -> dict:
    """Bloco de ``detalhes.dimensoes`` de módulo fora do plano: o formato que o
    motor grava para dimensão não contratada, sem a data do snapshot (que ele
    ainda grava) — nada do que a criança fez na plataforma."""
    base = bloco if isinstance(bloco, dict) else {}
    return {**base, "contratada": False, "aferido": False, "nota": None,
            "posicao": None, "n_aferidos": 0, "snapshot_em": None, "dados": {}}


# --- Histórico de leituras por período (base das premiações) ----------------

@router.get("/alunos/{aluno_id}/leituras", response_model=dict)
def historico_leituras(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    periodo: str = Query(default="tudo"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    dia: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Histórico CRONOLÓGICO de leituras do aluno, filtrado por período:
    um preset ("hoje", "este bimestre"...), um intervalo `inicio`/`fim`
    (AAAA-MM-DD) ou um único `dia`. Cada leitura traz livro, nível, plataforma,
    data/hora, tempo e pontos de dificuldade.

    Dado ESPECÍFICO ("quando o aluno leu X livro"): professor não acessa.
    Rede que não contratou Leitura → 403 (o módulo não existe para ela)."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    svc_modulos.exigir(svc_modulos.modulos_da_escola(db, db.get(Escola, escola_id)),
                       "leitura")
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    ano = _ano_ativo(db, escola_id)
    try:
        if dia:
            d = periodos._parse_data(dia)
            ini, fim_dt, rotulo = periodos.resolver("personalizado", hoje_br(), ano, d, d)
            chave = "dia"
        else:
            ini, fim_dt, rotulo = periodos.resolver(
                periodo, hoje_br(), ano,
                periodos._parse_data(inicio), periodos._parse_data(fim))
            chave = periodo
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use o formato AAAA-MM-DD).") from exc

    # NÍVEL CONGELADO da leitura; nulo (leitura anterior a esta versão) cai no
    # nível ATUAL do livro. Mesma ``coalesce`` do motor, do /ranking/leitura, das
    # premiações e da evolução: o histórico mostra o nível pelo qual a leitura
    # pontuou, não o que o catálogo passou a dizer depois.
    nivel_efetivo = func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)
    consulta = (
        select(Leitura, Livro, nivel_efetivo)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno.id)
    )
    if ini is not None:
        consulta = consulta.where(Leitura.data >= ini)
    if fim_dt is not None:
        consulta = consulta.where(Leitura.data <= fim_dt)
    consulta = consulta.order_by(Leitura.data.desc(), Leitura.id.desc())

    # Valor de cada livro pela FONTE ÚNICA de dificuldade (mesma regra do ranking
    # anual): v1 global por livro × série do aluno, ou a régua legada da escola.
    mat = db.execute(
        select(Turma.id, Turma.ano_escolar)
        .join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno.id, Matricula.ano_letivo == ano)
    ).first()
    _turma_id, _ano_escolar = (mat[0], mat[1]) if mat else (None, None)
    regra = dificuldade_livro.regra_da_escola(db, escola_id)
    itens = []
    pontos_exatos = 0.0    # soma SEM arredondar (bate com ranking/nota ao centavo)
    for leitura, livro, nivel in db.execute(consulta).all():
        valor = regra.valor_livro(nivel, livro.titulo, _ano_escolar, _turma_id,
                                  elefante_id=livro.elefante_id)
        pontos_exatos += valor
        itens.append({
            "id": leitura.id,
            "livro": livro.titulo,
            "nivel": nivel,
            "categoria": livro.categoria,
            "plataforma": "elefante",
            "data": leitura.data.isoformat(),
            "tempo_leitura_min": leitura.tempo_leitura_min,
            "pontos": round(valor, 2),
        })
    resumo = {
        "total_livros": len(itens),
        "pontos": round(pontos_exatos, 2),
        "tempo_total_min": sum((i["tempo_leitura_min"] or 0) for i in itens),
    }
    return {
        "periodo": {"chave": chave, "rotulo": rotulo,
                    "inicio": ini.isoformat() if ini else None,
                    "fim": fim_dt.isoformat() if fim_dt else None},
        "resumo": resumo,
        "itens": itens,
    }


# --- Gestão de alunos: editar, arquivar/reativar, transferir, excluir --------

def _aluno_da_escola(db: Session, escola_id: int, aluno_id: int) -> Aluno:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    return aluno


def _alunos_selecionados(db: Session, escola_id: int, aluno_ids: list[int]) -> list[Aluno]:
    """Alunos da lista que PERTENCEM a esta escola (ignora ids de fora)."""
    alunos = db.execute(
        select(Aluno).where(Aluno.id.in_(aluno_ids), Aluno.escola_id == escola_id)
    ).scalars().all()
    if not alunos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhum aluno válido selecionado.")
    return alunos


# O que "nada foi …" diz, por ação, quando uma ficha selecionada sumiu.
_FEITO_NA_ACAO = {"transferir": "transferido", "arquivar": "arquivado",
                  "reativar": "reativado", "excluir": "excluído",
                  "marcar_transferido": "marcado como transferido"}


def _exigir_fichas_selecionadas(ids: list[int], pedidos: list[int],
                                acao: str = "transferir") -> None:
    """Em toda ação em massa, cada ficha selecionada precisa existir nesta escola: a
    que sumiu (fundida em outra por outro gestor, com a lista ainda aberta) é 409
    para o pedido inteiro, sem mudar ninguém pela metade — o gestor recarrega e
    escolhe de novo (a criança agora está na ficha que ficou)."""
    faltam = set(pedidos) - set(ids)
    if not faltam:
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"{len(faltam)} aluno(s) selecionado(s) não existe(m) mais nesta escola — a ficha "
        "pode ter sido fundida com outra enquanto a lista estava aberta. Nada foi "
        f"{_FEITO_NA_ACAO.get(acao, 'alterado')}: recarregue a lista e tente de novo.")


def _recalcular_escola(db: Session, escola_id: int) -> None:
    """Recalcula notas/rankings e invalida o cache do painel — dashboards,
    estatísticas e gráficos se atualizam sem recarregar a página."""
    from app.routers.publico import invalidar_cache_painel
    scoring.recalcular_escola(db, escola_id)
    invalidar_cache_painel(escola_id)


@router.patch("/alunos/{aluno_id}", response_model=AlunoOut)
def atualizar_aluno(
    aluno_id: int,
    dados: AlunoUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Edita o cadastro (nome, nº de chamada, nascimento, observações).

    FICHA FUNDIDA NO MEIO (auditoria, ALUNOS-5): toma a trava da escola ANTES de
    ler a ficha, como as ações em massa. A fusão toma a mesma trava e apaga a ficha
    absorvida; no PostgreSQL a edição agora espera a fusão terminar e responde 404
    (a ficha não existe mais). Antes ela lia a ficha por fora da trava: ou o UPDATE
    batia em 0 linhas (``StaleDataError``, 500 "Erro interno"), ou gravava na ficha
    que a fusão já tinha copiado e a edição se perdia calada. Se a ficha sumir
    mesmo assim entre a leitura e a gravação (no SQLite a trava não existe), a
    resposta é 409, sem gravar nada."""
    bloquear_escola_para_importacao(db, escola_id)
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nada para atualizar.")
    if campos.get("nome"):
        campos["nome"] = campos["nome"].strip()
    for chave, valor in campos.items():
        setattr(aluno, chave, valor)
    registrar(db, "aluno.atualizado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"nome": aluno.nome, "campos": sorted(campos.keys())})
    try:
        db.commit()
    except StaleDataError:
        # O UPDATE bateu em 0 linhas: a ficha foi apagada (fundida em outra) entre a
        # leitura e a gravação. Nada fica gravado; o gestor recebe o 409 que diz o
        # que houve, não um 500.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Este aluno não existe mais nesta escola — a ficha pode ter sido fundida "
            "com outra enquanto “Editar dados” estava aberto. Nada foi alterado: "
            "recarregue a página e edite a ficha que ficou.") from None
    db.refresh(aluno)
    ano = _ano_ativo(db, escola_id)
    turma = db.execute(
        select(Turma).join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno.id, Matricula.ano_letivo == ano)
    ).scalar_one_or_none()
    saida = AlunoOut.model_validate(aluno)
    if turma:
        saida.turma = turma.nome
        saida.ano_escolar = turma.ano_escolar
    return saida


_STATUS_ACAO = {"arquivar": "arquivado", "reativar": "ativo", "excluir": "excluido",
                "marcar_transferido": "transferido"}


@router.post("/alunos/acoes", response_model=dict)
def acoes_em_alunos(
    dados: AcaoAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Ações em massa (ou individual): arquivar, reativar, excluir (lógico),
    marcar como transferido (saiu da escola) e transferir de turma. Ao final
    recalcula notas/rankings e invalida o cache — inclusive na transferência,
    que muda a população do ranking (ver ``test_transferir_recalcula_posicao``).

    Nenhuma delas apaga histórico: matrículas, leituras, eventos e snapshots
    continuam no banco. O que muda é o status da ficha, e todo filtro de visão
    usa ``status == "ativo"`` — por isso o aluno some dos rankings sem sumir
    do banco, e "Reativar" desfaz qualquer uma delas.

    D10 pela ficha (revisão de integração do e97): tirar de "excluido" uma ficha
    cuja conta da plataforma hoje é a identidade efetiva de um aluno de OUTRA
    escola (reativar, arquivar ou marcar como transferido — qualquer saída de
    "excluido" faz a conta voltar a valer aqui) é só do Admin Global:
    os demais recebem 403 e nada muda; ele segue, com ``avisos`` na resposta e a
    auditoria ``aluno.reativacao_outra_escola_confirmada``
    (``identidade_efetiva.trava_ficha_sai_de_excluido``). ``avisos`` vem sempre
    (lista vazia nos demais casos).

    D17 (T24) pelo outro lado: turma arquivada não recebe aluno ativo. Transferir
    PARA turma arquivada é 409 (``turma_arquivada.exigir_turma_ativa``), e
    reativar ficha cuja matrícula do ano letivo ativo está em turma arquivada
    também é 409 — a saída é transferir antes
    (``turma_arquivada.exigir_reativacao_em_turma_ativa``). Nos dois casos nada
    muda. Reativar também é 409 quando essa matrícula (legada) está numa turma de
    OUTRO ano letivo, ativa ou arquivada: a saída é transferir (sem
    ``turma_origem_id``) para uma turma do ano.

    TRANSFERIR A PARTIR DO PAINEL DE UMA TURMA (``turma_origem_id``): o que se
    move é a matrícula do ano letivo ATIVO que está NESSA turma — e só ela, sem
    criar matrícula nova. Turma de origem de OUTRO ano letivo é 409: o painel
    dela lista os alunos pela matrícula daquele ano (histórico), e transferir
    moveria a matrícula do ano ativo, que está na turma ATUAL da criança, em
    outra sala, em silêncio (3ª revisão de integração, contas-turmas-push). Aluno
    selecionado que não está na origem no ano ativo (lista desatualizada) também
    é 409 para o pedido inteiro. A auditoria ``aluno.transferido`` guarda a
    origem. Sem ``turma_origem_id`` (o perfil do aluno) o comportamento é o de
    sempre: move a matrícula do ano ativo onde ela estiver e cria uma no
    destino para quem não tem.

    DESTINO DE OUTRO ANO LETIVO: 409, com ou sem ``turma_origem_id``, e nada
    muda (``_exigir_destino_do_ano_ativo``). A matrícula que se move (ou nasce)
    é a do ano ativo; numa turma de outro ano ela continuava contando na escola
    e sumia das turmas do ano, e a diferença entregava a criança à Secretaria
    por subtração (revisão do grupo pequeno, rodada 4).

    FICHA QUE SUMIU NO MEIO (revisão de integração, 10/11): a transferência toma a
    trava da escola ANTES de ler os alunos. A fusão toma a mesma trava e apaga a
    ficha absorvida; lidos antes, os alunos incluíam essa ficha, e a matrícula
    criada para ela no destino estourava a FK (500). Agora, se alguma ficha
    selecionada não existe mais nesta escola, é 409 e ninguém é transferido.
    Revisão final: o mesmo vale para arquivar, reativar, excluir e marcar como
    transferido — elas também tomam a trava antes de ler e dão 409 ("Nada foi
    arquivado…"); antes gravavam o status da lista lida e, com a ficha apagada no
    meio, o UPDATE batia em menos linhas (StaleDataError, 500). Se a ficha sumir
    mesmo assim entre a leitura e a gravação (fusão que não passou pela trava; no
    SQLite ela não existe), a resposta é o mesmo 409, sem mudar ninguém."""
    if dados.acao == "transferir" and not dados.turma_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Selecione a turma de destino.")
    # Mesma trava do arquivamento (D17) e da fusão, ANTES de ler os alunos e o
    # status da turma: nenhum dos dois muda entre a leitura e a ação (no-op no
    # SQLite).
    bloquear_escola_para_importacao(db, escola_id)
    alunos = _alunos_selecionados(db, escola_id, dados.aluno_ids)
    ids = [a.id for a in alunos]
    _exigir_fichas_selecionadas(ids, dados.aluno_ids, dados.acao)
    ano = _ano_ativo(db, escola_id)
    avisos: list[str] = []

    if dados.acao == "transferir":
        origem: Turma | None = None
        if dados.turma_origem_id is not None:
            origem = _turma_da_escola(db, escola_id, dados.turma_origem_id)
            _exigir_origem_do_ano_ativo(origem, ano)
        turma = _turma_da_escola(db, escola_id, dados.turma_id)
        turma_arquivada.exigir_turma_ativa(turma)
        _exigir_destino_do_ano_ativo(turma, ano)
        if origem is not None:
            _exigir_alunos_na_origem(db, ids, origem, ano)
            db.execute(
                update(Matricula)
                .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano,
                       Matricula.turma_id == origem.id)
                .values(turma_id=turma.id)
            )
        else:
            db.execute(
                update(Matricula)
                .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano)
                .values(turma_id=turma.id)
            )
            # Alunos sem matrícula no ano ativo ganham uma nova na turma destino.
            com_matricula = set(db.execute(
                select(Matricula.aluno_id)
                .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano)
            ).scalars().all())
            for aid in ids:
                if aid not in com_matricula:
                    db.add(Matricula(escola_id=escola_id, aluno_id=aid,
                                     turma_id=turma.id, ano_letivo=ano))
        detalhes = {"alunos": ids, "turma_id": turma.id, "turma": turma.nome}
        if origem is not None:
            detalhes |= {"turma_origem_id": origem.id, "turma_origem": origem.nome}
        registrar(db, "aluno.transferido", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", detalhes=detalhes)
        mensagem = (f"{len(ids)} aluno(s) transferido(s) de {origem.nome} para "
                    f"{turma.nome}." if origem is not None
                    else f"{len(ids)} aluno(s) transferido(s) para {turma.nome}.")
    else:
        novo_status = _STATUS_ACAO[dados.acao]
        if novo_status == "ativo":
            # D17: ninguém volta a "ativo" dentro de turma arquivada.
            turma_arquivada.exigir_reativacao_em_turma_ativa(db, escola_id, alunos, ano)
        # ANTES de trocar o status: ficha excluída com conta efetiva em outra
        # escola só sai de "excluido" com o Admin Global (D10).
        try:
            avisos.extend(identidade_efetiva.trava_ficha_sai_de_excluido(
                db, escola_id, alunos, novo_status,
                admin_global=bool(usuario.is_global), usuario_id=usuario.id,
                acao=dados.acao))
        except identidade_efetiva.ErroIdentidade as exc:
            db.rollback()
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
        for aluno in alunos:
            aluno.status = novo_status
        registrar(db, f"aluno.{dados.acao}", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", detalhes={"alunos": ids, "status": novo_status})
        rotulos = {"arquivar": "arquivado(s)", "reativar": "reativado(s)",
                   "excluir": "excluído(s)",
                   "marcar_transferido": "marcado(s) como transferido(s)"}
        mensagem = f"{len(ids)} aluno(s) {rotulos[dados.acao]}."

    try:
        db.commit()
    except StaleDataError:
        # O UPDATE do status bateu em menos linhas que as lidas: uma ficha sumiu
        # entre a leitura e a gravação. Nada fica gravado; o gestor recebe o 409 da
        # ficha fundida, não um 500.
        db.rollback()
        restantes = db.execute(select(Aluno.id).where(
            Aluno.id.in_(ids), Aluno.escola_id == escola_id)).scalars().all()
        _exigir_fichas_selecionadas(restantes, dados.aluno_ids, dados.acao)
        raise
    # Toda ação recalcula, porque todas mudam quem está no ranking: o status muda
    # o conjunto de alunos ativos, e a transferência dá (ou tira) a matrícula do
    # ano numa turma do 1º ao 5º ano. Sem o recálculo na transferência, a posição
    # guardada na Nota era a do cálculo de antes — que hoje pode ser de outra
    # criança —, e o Mérito emitido logo depois saía com ela; é justamente o
    # caminho que a recusa do Mérito manda seguir (perfil › "Editar dados" › Turma).
    _recalcular_escola(db, escola_id)
    return {"mensagem": mensagem, "afetados": len(ids), "avisos": avisos}


# Chaves em que a produção grava NOME DE PESSOA no ``detalhes`` da auditoria.
# Levantadas dos ``registrar(...)`` reais: ``nome`` (aluno.criado/atualizado/
# criacao_recusada/fora_lista_piloto, e aninhado em aluno.fundido →
# mantido/removido/foto_pre_fusao), ``origem``/``origem_linha`` (o nome como
# veio da PLANILHA — que difere do nome da base, por isso houve casamento
# aproximado), ``aluno`` (aluno.vinculado_auto), ``nome_antigo``/``nome_novo``
# (aluno.identidade_vinculada) e ``nome_recebido`` (identidade.revisao_resolvida —
# o nome como veio da plataforma). Tudo o mais em ``detalhes`` é código, contagem
# ou id — o que mantém a trilha útil depois da redação.
_CHAVES_COM_NOME_DE_PESSOA = frozenset({
    "nome", "nome_antigo", "nome_novo", "nome_exibicao", "apelido",
    "aluno", "origem", "origem_linha", "nome_recebido",
})
# As que SÓ guardam nome de pessoa: na entrada do próprio excluído, caem sempre —
# inclusive o nome que a criança escolheu no Quest ("Bia" para "Ana Beatriz"),
# que não tem pedaço nenhum do nome civil. ``origem``/``origem_linha`` ficam de
# fora: são sobrecarregadas (ver abaixo).
_CHAVES_SO_DE_NOME = _CHAVES_COM_NOME_DE_PESSOA - {"origem", "origem_linha"}

# ``origem`` é sobrecarregada: às vezes é o nome cru da planilha
# (aluno.criado_auto/revisao_necessaria/vinculado_auto), às vezes é a PROCEDÊNCIA
# do dado — "importacao", "importacao_matriculas", "matific". Por isso a redação
# por chave exige parentesco com o nome do excluído (ver ``_parece_nome_do_alvo``):
# procedência não compartilha nenhum pedaço do nome e sobrevive intacta.
_PARTICULAS_DE_NOME = frozenset({"de", "da", "do", "dos", "das", "e"})

# Dado pessoal da criança que NÃO é nome e que algumas entradas guardam: a foto da
# ficha absorvida na fusão (``aluno.fundido`` → ``foto_pre_fusao``: nascimento,
# observações — campo livre, sensível — e foto), as duas datas de
# ``aluno.nascimento_divergente`` e o RA da linha da Lista Piloto em
# ``aluno.identidade_vinculada`` (``routers/importacoes``: gravado em TODO vínculo
# que troca o nome, qualquer que seja o motivo — o log não guarda a via do
# casamento, então o número não é "o motivo da decisão"; o ``motivo`` fica). Nas
# entradas da própria criança, caem pela chave.
_CHAVES_DE_DADO_PESSOAL = frozenset({
    "data_nascimento", "observacoes", "foto_url", "na_ficha", "na_planilha", "ra",
})

_MARCA_REMOVIDO = "[removido]"

# ``aluno.fundido_com_conflito`` guarda em ``divergencias``, em texto, os sinais
# de serem crianças diferentes que a gestão aceitou passar por cima
# (``_divergencias_de_identidade``): "nascimento 2017-04-10 × 2017-04-09", "RA … ×
# …", o nº de chamada. Nas entradas da própria criança, os itens de nascimento e de
# RA perdem os valores e ficam "nascimento [removido]" / "RA [removido]": o porquê
# técnico (houve conflito de nascimento, de RA) continua; a data e o número, não.
_CHAVES_DE_DIVERGENCIA = frozenset({"divergencias"})
_PREFIXO_NASCIMENTO = "nascimento "
_PREFIXO_RA = "RA "
_PREFIXOS_DE_DADO_NA_DIVERGENCIA = (_PREFIXO_NASCIMENTO, _PREFIXO_RA)

# ``aluno.fundido`` → ``foto_pre_fusao`` → ``ficha``: o retrato do cadastro da
# ficha absorvida (pela minimização da Lista Piloto, hoje só o RA). Não é o motivo
# de nenhuma decisão: nas entradas da própria criança, todo valor dela vira
# "[removido]" (as chaves ficam). Os outros RAs que o código grava hoje nas
# entradas dela também caem: o de ``aluno.identidade_vinculada`` pela chave
# (``_CHAVES_DE_DADO_PESSOAL``), o das ``divergencias`` pelo prefixo.
_CHAVES_DE_RETRATO = frozenset({"foto_pre_fusao"})
_CAMPO_FICHA_DO_RETRATO = "ficha"


def _divergencia_sem_dado(texto):
    """"RA 123 × 456" → "RA [removido]"; "nascimento A × B" → "nascimento [removido]"."""
    if isinstance(texto, str):
        for prefixo in _PREFIXOS_DE_DADO_NA_DIVERGENCIA:
            if texto.startswith(prefixo):
                return prefixo + _MARCA_REMOVIDO
    return texto


def _retrato_sem_ficha(retrato: dict) -> dict:
    """A foto pré-fusão com os valores da ``ficha`` trocados por "[removido]"."""
    ficha = retrato.get(_CAMPO_FICHA_DO_RETRATO)
    if not isinstance(ficha, dict):
        return retrato
    return {**retrato, _CAMPO_FICHA_DO_RETRATO: {
        chave: _MARCA_REMOVIDO if valor not in (None, "") else valor
        for chave, valor in ficha.items()}}


def _anonimizar_logs_do_aluno(db: Session, escola_id: int,
                              aluno_ids: list[int], nomes: set[str],
                              absorvidas: dict[int, set[str]] | None = None) -> None:
    """Redige o nome civil das entradas ANTERIORES do log de auditoria que se
    referem ao aluno excluído (LGPD/direito ao esquecimento).

    Anonimiza, NÃO apaga: o "quê/quando/por quem/sobre qual registro" — e o
    porquê técnico (decisão, motivo, turma, a origem de um vínculo) — continuam
    intactos; só o nome de pessoa (e o dado pessoal de ``_CHAVES_DE_DADO_PESSOAL``
    — com o RA do ``aluno.identidade_vinculada`` —, os valores dos itens de
    nascimento e de RA de ``divergencias`` e a ``ficha`` da ``foto_pre_fusao``, com
    o RA dela) vira ``"[removido]"``. O ``entidade_id`` fica como referência
    anônima.
    ``logs_auditoria`` é permanente por design (``models/nota.py``).

    ``absorvidas`` ({id: {nomes}}, de ``exclusao_aluno.fichas_absorvidas``): as
    fichas que a criança absorveu por fusão. São ELA: as entradas com o id delas
    contam como "do aluno excluído" (critério 2), e os nomes delas entram no
    critério 2 e — quando nenhuma criança que continua na escola tem o mesmo
    nome — no critério 1.

    A varredura é por ESCOLA, sem filtrar ``entidade``/``entidade_id`` (C-07):
    o caminho de importação — que é o normal — grava ``entidade_id=None``, e
    ``IN (...)`` nunca casa NULL, então filtrar ali deixava para trás
    justamente as entradas mais comuns. Dois critérios de redação, combinados:

    1. **por VALOR** — qualquer string, em qualquer chave ou dentro de lista,
       cujo nome normalizado (sem acento/caixa/espaço repetido) seja o de um
       aluno excluído. Pega o nome gravado em caixa alta e sem acento para um
       cadastro com acento, e o nome solto dentro de lista;
    2. **por CHAVE semântica** — nas entradas que comprovadamente falam do
       aluno excluído (``entidade == "aluno"`` e ``entidade_id`` dele), uma
       chave de nome cai também com grafia que a normalização não alcança
       (abreviação: "ANA B. SOUZA" para "Ana Beatriz Souza"), desde que o valor
       tenha parentesco com o nome do excluído.

    O critério 2 é restrito às entradas do próprio aluno de propósito: aplicá-lo
    a todas apagaria o nome de crianças que continuam matriculadas — a
    sobre-redação destrói a auditoria de quem não pediu esquecimento.

    TROCA ASSUMIDA (homônimo adulto): o critério 1 vale para a escola inteira,
    então a entrada de um professor com o MESMO nome do aluno excluído também é
    redigida. Os dados não permitem distinguir as duas strings, e a entrada do
    professor continua identificada por ``entidade``/``entidade_id`` — perder o
    nome de um adulto homônimo é preferível a manter o de um menor.

    Entradas SEM escola (login de conta inexistente, ações da rede, avaliações,
    indicadores) ficam FORA dos dois critérios, salvo a entrada que é da própria
    criança (``entidade == "aluno"`` e ``entidade_id`` dela). Quem exclui é a
    gestão de UMA escola: aplicar ali o critério por valor deixaria um
    aluno-isca, com o nome igual ao texto que se quer apagar (um e-mail, o nome
    de uma fonte da rede), reescrever o que nenhum perfil de escola alcança. Ação
    global nova que cite uma criança tem de levar ``escola_id`` ou
    ``entidade``/``entidade_id`` dela para ser alcançada aqui.
    """
    from app.models import LogAuditoria  # noqa: E402
    from app.services.importacao import normalizar_nome  # noqa: E402

    def _tokens(texto: str) -> set[str]:
        return {parte.strip(".") for parte in normalizar_nome(texto).split()
                if len(parte.strip(".")) > 1
                and parte.strip(".") not in _PARTICULAS_DE_NOME}

    absorvidas = absorvidas or {}
    nomes_absorvidos = {n for ns in absorvidas.values() for n in ns if n and n.strip()}
    alvos = {normalizar_nome(n) for n in nomes if n and n.strip()}
    if nomes_absorvidos:
        # O nome da ficha absorvida (muitas vezes abreviado: "ANA B. SOUZA",
        # "JOAO PEDRO") só vale no critério por valor se não for também o nome —
        # ou parte do nome — de quem continua na escola.
        vivos = [normalizar_nome(n) for n in db.execute(select(Aluno.nome).where(
            Aluno.escola_id == escola_id, Aluno.id.not_in(list(aluno_ids)))).scalars()
            if n]
        alvos |= {a for a in map(normalizar_nome, nomes_absorvidos)
                  if not any(re.search(rf"\b{re.escape(a)}\b", v) for v in vivos)}
    if not alvos and not absorvidas:
        return
    tokens_alvo = set().union(*(_tokens(n) for n in (*nomes, *nomes_absorvidos)
                                if n and n.strip()))
    ids_alvo = set(aluno_ids) | set(absorvidas)
    # Nomes com 2+ partes são específicos o bastante para serem procurados
    # DENTRO de um texto maior sem risco de falso positivo. Um nome de uma
    # palavra só ("Ana") não entra aqui: casaria "Susana", "Ananias".
    alvos_em_texto = {a for a in alvos if len(_tokens(a)) >= 2}

    def _e_nome_de_alvo(valor: str) -> bool:
        if not valor.strip():
            return False
        normalizado = normalizar_nome(valor)
        if normalizado in alvos:
            return True
        # Nome citado no meio de uma frase (ex.: um aviso guardado em detalhes).
        # Hoje nenhuma ação grava assim; a checagem impede que uma ação nova
        # reabra o vazamento sem ninguém perceber. Com FRONTEIRA DE PALAVRA:
        # sem ela, apagar "Ana Souza" redigiria "Mariana Souza Silva", que é
        # outra criança — busca crua por substring produz colisão de verdade.
        return any(re.search(rf"\b{re.escape(alvo)}\b", normalizado)
                   for alvo in alvos_em_texto)

    def _parece_nome_do_alvo(valor: str) -> bool:
        """Compartilha algum pedaço do nome do excluído — o que separa o nome
        abreviado ("ANA B. SOUZA") de uma procedência ("importacao_matriculas",
        "matific"), que não tem nenhum token em comum."""
        return bool(_tokens(valor) & tokens_alvo)

    def _redigir_campo(chave: str, item, *, por_chave: bool):
        if isinstance(item, str) and (
                (chave in _CHAVES_COM_NOME_DE_PESSOA
                 and (_e_nome_de_alvo(item)
                      or (por_chave and (chave in _CHAVES_SO_DE_NOME
                                         or _parece_nome_do_alvo(item)))))
                or (por_chave and chave in _CHAVES_DE_DADO_PESSOAL and item.strip())):
            return _MARCA_REMOVIDO
        redigido = _redigir(item, por_chave=por_chave)
        if por_chave and chave in _CHAVES_DE_DIVERGENCIA and isinstance(redigido, list):
            return [_divergencia_sem_dado(texto) for texto in redigido]
        if por_chave and chave in _CHAVES_DE_RETRATO and isinstance(redigido, dict):
            return _retrato_sem_ficha(redigido)
        return redigido

    def _redigir(valor, *, por_chave: bool):
        """``por_chave``: a entrada é comprovadamente do aluno excluído."""
        if isinstance(valor, dict):
            return {chave: _redigir_campo(chave, item, por_chave=por_chave)
                    for chave, item in valor.items()}
        if isinstance(valor, list):
            return [_redigir(item, por_chave=por_chave) for item in valor]
        if isinstance(valor, str) and _e_nome_de_alvo(valor):
            return _MARCA_REMOVIDO
        return valor

    # ``logs_auditoria`` é permanente e cresce para sempre; a varredura é da
    # escola inteira e, das entradas SEM escola, só as da própria criança (ver o
    # docstring: o critério por valor não vale nas globais). ``yield_per``
    # transmite em lotes em vez de materializar tudo de uma vez (a exclusão
    # permanente é rara, mas não pode explodir a memória de uma escola com
    # histórico longo).
    logs = db.execute(
        select(LogAuditoria).where(
            (LogAuditoria.escola_id == escola_id)
            | (LogAuditoria.escola_id.is_(None)
               & (LogAuditoria.entidade == "aluno")
               & LogAuditoria.entidade_id.in_(sorted(ids_alvo))))
        .execution_options(yield_per=500)
    ).scalars()
    for log in logs:
        if not log.detalhes:
            continue
        do_aluno = log.entidade == "aluno" and log.entidade_id in ids_alvo
        redigido = _redigir(log.detalhes, por_chave=do_aluno)
        if redigido != log.detalhes:
            log.detalhes = redigido  # reatribui → dirty tracking


def _apagar_avisos_do_aluno(db: Session, escola_id: int,
                            aluno_ids: list[int]) -> None:
    """Remove os avisos que apontam para a criança excluída.

    ``Notificacao.aluno_id`` é um int solto (sem FK, logo sem cascade): sem
    isto o aviso sobrevive apontando para quem pediu para ser esquecido — e,
    como o banco reaproveita IDs de linhas apagadas, passaria a apontar para
    OUTRA criança, aparecendo no mural do professor errado. Aviso é estado
    derivado (renasce do próximo evento), não é a trilha de auditoria. Pega
    também o aviso que aponta a criança só por ``entidade``/``entidade_id``."""
    from app.models import Notificacao  # noqa: E402
    db.execute(delete(Notificacao).where(
        Notificacao.escola_id == escola_id,
        Notificacao.aluno_id.in_(aluno_ids)
        | ((Notificacao.entidade == "aluno")
           & Notificacao.entidade_id.in_(aluno_ids))))


def _apagar_alunos_e_dados(db: Session, escola_id: int, usuario: Usuario,
                           aluno_ids: list[int], contagens: dict | None = None, *,
                           esquecer_contas: bool = False) -> int:
    """Exclusão FÍSICA de alunos + TODOS os dados vinculados (leituras, snapshots
    Matific/Elefante, notas, matrículas, eventos, identidades externas) e — LGPD/
    direito ao esquecimento — as conversas da IA que citem o nome e o que guarda
    o nome/id da criança fora do cadastro (revisões de identidade, mensagens de
    sincronização, original de relatório individual, cópias em /exports: regra
    em ``services/exclusao_aluno``). Auditado (§17). NÃO commita nem recalcula:
    o chamador decide. Reusado pela exclusão permanente e pela exclusão de turma
    com alunos. Devolve quantos alunos foram removidos.

    ``contagens`` (opcional): dicionário que recebe, SEM nome nenhum, quantas
    linhas de cada tipo saíram — para o chamador auditar e mostrar o que apagou
    (a exclusão de turma com alunos usa; nada muda para quem não passa).

    ``esquecer_contas`` (a exclusão permanente — o pedido de esquecimento): grava
    no ``aluno.excluido_permanente`` de cada criança a MARCA das contas dela nas
    plataformas (HMAC, sem nome nem id em claro — ``exclusao_aluno.contas_da_crianca``)
    para a coleta seguinte ignorá-las, em vez de recriar a ficha ou devolver o nome
    à fila de revisões. A exclusão de turma com alunos não passa: limpar uma turma
    não é pedido de esquecimento, e a conta de quem continua estudando voltaria a
    ser ignorada para sempre."""
    from app.models import EventoAluno, IdentidadeExterna  # noqa: E402
    from app.quest.models import QuestPerfil  # noqa: E402
    from app.services import exclusao_aluno  # noqa: E402

    nomes = {a.id: a.nome for a in db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id, Aluno.id.in_(aluno_ids))
    ).scalars()}
    ids = list(nomes)
    if not ids:
        return 0
    conta = contagens if contagens is not None else {}
    # As identidades externas DELA (plataforma + id) antes de apagá-las: é por
    # elas que se reconhece a revisão pendente que é dela mesmo sem o nome igual.
    identidades = {(p, i) for p, i in db.execute(
        select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo)
        .where(IdentidadeExterna.aluno_id.in_(ids)))}
    # As contas de cada criança — as vinculadas e as das revisões dela — também
    # antes de apagar identidades e revisões: viram a marca de esquecimento.
    contas_dela = (exclusao_aluno.contas_da_crianca(db, escola_id, nomes)
                   if esquecer_contas else {})
    if contagens is not None:
        # O perfil do Quest (com a telemetria) sai pelo ON DELETE CASCADE do
        # banco: contado ANTES, para a auditoria não omitir o que a cascata leva.
        conta["perfis_quest"] = db.execute(
            select(func.count()).select_from(QuestPerfil)
            .where(QuestPerfil.aluno_id.in_(ids))).scalar_one()
    # Filhos Edu explícitos (ordem p/ recálculo/log) — eventos e identidades
    # também, sem depender do ON DELETE CASCADE do banco; Quest/responsáveis
    # somem por ON DELETE CASCADE (migração 0003) ao deletar o aluno.
    conta["leituras"] = db.execute(
        delete(Leitura).where(Leitura.aluno_id.in_(ids))).rowcount
    conta["snapshots_matific"] = db.execute(
        delete(SnapshotMatific).where(SnapshotMatific.aluno_id.in_(ids))).rowcount
    conta["snapshots_elefante"] = db.execute(
        delete(SnapshotElefante).where(SnapshotElefante.aluno_id.in_(ids))).rowcount
    conta["eventos"] = db.execute(
        delete(EventoAluno).where(EventoAluno.aluno_id.in_(ids))).rowcount
    conta["notas"] = db.execute(delete(Nota).where(Nota.aluno_id.in_(ids))).rowcount
    conta["matriculas"] = db.execute(
        delete(Matricula).where(Matricula.aluno_id.in_(ids))).rowcount
    # LGPD/esquecimento: NÃO gravar o nome da criança no log permanente (o
    # entidade_id basta como referência; o nome, uma vez apagado, não deve
    # sobreviver em texto claro). Guarda só a contagem por lote — e, no pedido de
    # esquecimento, a marca das contas dela (plataforma + HMAC do id externo), que a
    # porta única de identidade lê para ignorar a conta na coleta seguinte.
    for aid in ids:
        detalhes = {"tipo": "exclusao_permanente"}
        if contas_dela.get(aid):
            detalhes[exclusao_aluno.CHAVE_CONTAS_ESQUECIDAS] = (
                exclusao_aluno.marcas_para_o_log(contas_dela[aid]))
        registrar(db, exclusao_aluno.ACAO_EXCLUSAO_PERMANENTE, escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=aid,
                  detalhes=detalhes)
    # E anonimiza as entradas ANTERIORES do log que citam o nome deste aluno
    # (criação/edição/fusão/importação) — sem isso o nome civil do menor
    # persistiria para sempre no histórico de auditoria. Inclui as fichas que ele
    # absorveu por fusão: o stub da importação e a foto pré-fusão são dele.
    _anonimizar_logs_do_aluno(db, escola_id, ids, set(nomes.values()),
                              exclusao_aluno.fichas_absorvidas(db, escola_id, ids))
    # Avisos que apontam para a criança não têm FK e não somem no cascade.
    _apagar_avisos_do_aluno(db, escola_id, ids)
    # O que guarda o nome/id fora do cadastro (ANTES do DELETE em alunos: a
    # revisão resolvida para ela ainda aponta o id). Só contagens no log.
    fora = exclusao_aluno.esquecer_fora_do_cadastro(db, escola_id, nomes, identidades)
    conta["identidades_externas"] = db.execute(
        delete(IdentidadeExterna).where(IdentidadeExterna.aluno_id.in_(ids))).rowcount
    db.execute(delete(Aluno).where(Aluno.id.in_(ids)))
    if any(fora.values()):
        registrar(db, "aluno.esquecimento_fora_do_cadastro", escola_id=escola_id,
                  usuario_id=usuario.id, detalhes={**fora, "alunos": len(ids)})
        conta["fora_do_cadastro"] = dict(fora)

    # LGPD: esquecimento das conversas da IA que citem algum aluno excluído (a
    # cascata da 0003 apaga as mensagens). Por palavra inteira e sem contar o
    # nome maior de quem fica — regra em ``exclusao_aluno.conversas_ia_que_citam``.
    from app.models import ConversaIA
    ids_conversas = exclusao_aluno.conversas_ia_que_citam(db, escola_id, nomes)
    if ids_conversas:
        db.execute(delete(ConversaIA).where(ConversaIA.id.in_(ids_conversas)))
        registrar(db, "ia.conversas_esquecimento", escola_id=escola_id,
                  usuario_id=usuario.id,
                  detalhes={"conversas_removidas": len(ids_conversas),
                            "motivo": "exclusao_permanente_aluno"})
    conta["conversas_ia"] = len(ids_conversas)
    return len(ids)


@router.post("/alunos/excluir-permanente", response_model=dict)
def excluir_alunos_permanente(
    dados: ExclusaoPermanenteAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Exclusão FÍSICA e IRREVERSÍVEL: remove o aluno e TODOS os registros
    vinculados (leituras, snapshots Matific/Elefante, notas, matrículas).
    Exige confirmação textual ("EXCLUIR"). A auditoria é preservada (§17).

    Decisão D19 (T25), sem atalho: a exclusão física de aluno é exclusiva do
    Admin Global — a mesma régua do DELETE /turmas?com_alunos=true. Antes, o
    admin e a coordenação da escola, barrados ali, apagavam os MESMOS alunos por
    esta rota (inclusive quem tinha matrícula em outra turma, que o D19 só
    desvincula) e depois excluíam a turma vazia. Agora recebem 403 com a mesma
    mensagem do D19, ANTES de qualquer leitura ou DELETE; o caminho deles é a
    exclusão lógica (/alunos/acoes ``excluir``), reversível."""
    _exigir_admin_global_para_exclusao_fisica(usuario, len(set(dados.aluno_ids)))
    if dados.confirmacao.strip().upper() != "EXCLUIR":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Confirmação inválida. Digite EXCLUIR para confirmar a exclusão "
            "permanente e irreversível.")
    # Mesma trava da fusão, da importação e da coleta (no-op no SQLite), ANTES de
    # ler as fichas: nenhuma fusão grava no log da criança (nem lhe passa dados)
    # entre a leitura do estado e a anonimização.
    bloquear_escola_para_importacao(db, escola_id)
    alunos = _alunos_selecionados(db, escola_id, dados.aluno_ids)
    n = _apagar_alunos_e_dados(db, escola_id, usuario, [a.id for a in alunos],
                               esquecer_contas=True)
    db.commit()
    _recalcular_escola(db, escola_id)
    return {"mensagem": f"{n} aluno(s) excluído(s) permanentemente, com "
                        "todos os dados vinculados.", "afetados": n}


_CONFIRMA_CONFLITO = "FUNDIR MESMO COM CONFLITO"


def _divergencias_de_identidade(a: Aluno, b: Aluno) -> dict[str, str]:
    """Os sinais que o MOTOR ÚNICO trata como prova de serem crianças diferentes,
    em português, para a mensagem e para o log: ``{campo: texto}``, com ``campo``
    em ``nascimento`` | ``ra`` | ``chamada`` | ``motor`` (na ordem da mensagem).

    Usa ``matching.conflito_identidade`` como juiz — a mesma função que decide
    isso em toda importação e sincronização — em vez de uma regra própria daqui.
    Com isso o RA passa pela normalização canônica (``ra_forte``), então dois
    RAs que só diferem na pontuação NÃO contam como divergência, e a decisão
    sobre nº de chamada (renumeração de sala não é outra criança) é herdada em
    vez de reinventada. Devolve {} quando não há prova de conflito."""
    ia, ib = identidade_aluno.identidade_do_aluno(a), identidade_aluno.identidade_do_aluno(b)
    if not matching.conflito_identidade(ia, ib):
        return {}
    motivos: dict[str, str] = {}
    if ia.nascimento and ib.nascimento and ia.nascimento != ib.nascimento:
        motivos["nascimento"] = f"{_PREFIXO_NASCIMENTO}{ia.nascimento} × {ib.nascimento}"
    if ia.ra and ib.ra and ia.ra != ib.ra:
        motivos["ra"] = f"{_PREFIXO_RA}{ia.ra} × {ib.ra}"
    if (ia.chamada is not None and ib.chamada is not None
            and ia.chamada != ib.chamada):
        motivos["chamada"] = f"nº de chamada {ia.chamada} × {ib.chamada}"
    return motivos or {"motor": "o motor de identidade aponta conflito"}


def _saida_do_conflito(divergencias: dict[str, str]) -> str:
    """O que fazer quando não se tem certeza, dito só com caminhos que EXISTEM.

    Nascimento e nº de chamada se corrigem em “Editar dados”; o RA NÃO — o modal e
    ``AlunoUpdate`` não têm o campo (achado ALUNOS-10 da auditoria: a mensagem
    mandava corrigir ali um RA que não se edita). Para o RA a saída real é a da
    própria fusão: a ficha principal guarda o RA dela (``alunos_fusao`` só
    preenche campos VAZIOS da ficha que fica)."""
    ra = ("deixe como principal a ficha com o RA certo antes de confirmar — a fusão "
          "guarda o RA da ficha principal.")
    if "ra" not in divergencias:
        return ("Se não tiver certeza, não funda: corrija antes o dado divergente em "
                "Alunos › Editar dados.")
    if len(divergencias) == 1:
        return f"Se só um dos RAs estiver errado, {ra} Se não tiver certeza, não funda."
    return ("Se não tiver certeza, não funda: o nascimento e o nº de chamada se "
            "corrigem antes em Alunos › Editar dados. O RA não se corrige ali: se só um "
            f"dos RAs estiver errado, {ra}")


@router.get("/alunos/fundir/previa", response_model=dict)
def previa_fundir_alunos(
    manter_id: int,
    remover_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """PRÉVIA da fusão manual (só leitura): o que acontece com os livros que estão
    nas DUAS fichas, nesta direção (fica a data de ``manter_id``). Não grava nada e
    não toma a trava. A Secretaria é barrada como em /alunos/duplicados: a resposta
    traz nome de criança e os livros dela."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    if manter_id == remover_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Escolha dois alunos diferentes para fundir.")
    manter = _aluno_da_escola(db, escola_id, manter_id)
    remover = _aluno_da_escola(db, escola_id, remover_id)
    return alunos_dedup.previa_da_fusao(db, escola_id, manter, remover)


@router.post("/alunos/fundir", response_model=dict)
def fundir_alunos(
    dados: FusaoAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Funde dois cadastros do MESMO aluno (duplicados).

    Junta no `manter` TUDO do `remover` — snapshots Matific e Elefante,
    leituras, matrículas, notas, a linha do tempo de eventos, o vínculo de
    identidade externa (UUID das plataformas) e também o lado Quest (perfil +
    telemetria, credencial e responsáveis) — e apaga o `remover`. É o caso do
    aluno cujos dados vieram separados (Matific num cadastro, Elefante noutro).

    Conflitos são resolvidos sem perder nem duplicar:
      * leitura do mesmo livro nos dois → mantém uma (a releitura nunca
        pontua duas vezes, §35);
      * matrícula no mesmo ano nos dois → mantém a do `manter` (a turma
        dele prevalece);
      * perfil/credencial Quest é único por aluno → migra (com toda a
        telemetria) se o `manter` não tiver; se ambos tiverem, fica o que a
        criança usa (``alunos_fusao.plano_quest``) e o outro é descartado (contado
        no log); as duas fichas com jogo no Quest → 409, nada é fundido;
      * conta da MESMA plataforma nas duas fichas (contas diferentes) → 409,
        nada é fundido: o retrato não guarda a conta de origem e as duas séries
        se misturariam (``alunos_fusao.contas_em_conflito``);
      * campos vazios do `manter` (foto, nº de chamada, nascimento,
        observações) são preenchidos com os do `remover`.
    Irreversível → exige confirmação textual "FUNDIR". Recalcula ao final."""
    if dados.confirmacao.strip().upper() != "FUNDIR":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Confirmação inválida. Digite FUNDIR para confirmar.")
    if dados.manter_id == dados.remover_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Escolha dois alunos diferentes para fundir.")
    # A MESMA trava da importação e da coleta, e pelo mesmo motivo. Sem ela, uma
    # coleta em andamento gravava retrato ou vínculo na ficha que está sendo apagada,
    # e o CASCADE levava junto (ou a coleta caía por FK). A ORDEM é a da importação:
    # a trava vem ANTES de ler as duas fichas e de escrever qualquer linha — quem
    # chega depois espera, e relê o que o outro gravou — e cai no commit, antes do
    # recálculo (hierarquia de ``bloquear_escola_para_recalculo``). Travar depois de
    # escrever daria deadlock com a coleta, que trava primeiro e escreve depois.
    bloquear_escola_para_importacao(db, escola_id)
    manter = _aluno_da_escola(db, escola_id, dados.manter_id)
    remover = _aluno_da_escola(db, escola_id, dados.remover_id)
    # Só funde alunos ATIVOS: manter um arquivado/excluído absorvendo um ativo
    # faria o aluno sumir de todas as telas (que filtram status "ativo").
    if manter.status != "ativo" or remover.status != "ativo":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Só é possível fundir alunos ativos. Reative o "
                            "cadastro arquivado ou excluído antes de fundir.")
    # PROVA DE SEREM CRIANÇAS DIFERENTES: a fusão apaga uma ficha, mas a tela
    # mostra só nome e turma — quem digita "FUNDIR" não vê nascimento nem RA.
    # A fusão em LOTE recomputa os candidatos e já barra esses pares; a manual
    # não tinha rede nenhuma. Não vira bloqueio: fundir é ato humano e o gestor
    # pode saber de algo que o dado não conta (um dos cadastros com nascimento
    # errado, por exemplo). Vira uma segunda confirmação que NOMEIA a
    # divergência, para que ela seja lida antes e fique no log.
    divergencias = _divergencias_de_identidade(manter, remover)
    if divergencias and dados.confirmar_conflito.strip().upper() != _CONFIRMA_CONFLITO:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Estes dois cadastros têm sinais de serem crianças DIFERENTES: "
            + "; ".join(divergencias.values())
            + f". Se ainda assim for a mesma criança, digite “{_CONFIRMA_CONFLITO}” "
              "para confirmar. " + _saida_do_conflito(divergencias))


    # Núcleo compartilhado com a fusão em lote (Fundir duplicatas): reatribui/
    # deduplica cada relação, funde a ficha, registra a auditoria (com a foto
    # pré-fusão) e apaga o `remover`. Não commita nem recalcula — isso é aqui.
    # Recusa (contas diferentes da mesma plataforma, ou as duas fichas com jogo no
    # Constela Quest) vem antes de qualquer escrita (``alunos_fusao.motivo_da_recusa``).
    try:
        r = alunos_fusao.fundir_par(db, escola_id, manter, remover, usuario.id)
    except alunos_fusao.FusaoRecusada as recusa:
        raise HTTPException(status.HTTP_409_CONFLICT, recusa.motivo) from None
    if divergencias:
        # Fundiu APESAR da prova de conflito: o log tem de dizer o que o gestor
        # aceitou passar por cima, senão a decisão some.
        registrar(db, "aluno.fundido_com_conflito", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=manter.id,
                  detalhes={"manter_id": manter.id, "remover_id": dados.remover_id,
                            "divergencias": list(divergencias.values()),
                            "confirmacao_especifica": _CONFIRMA_CONFLITO})
    db.commit()
    _recalcular_escola(db, escola_id)
    return {
        "mensagem": f"“{r['remover_nome']}” foi fundido em “{r['manter_nome']}”. "
                    f"{r['leituras_movidas']} leitura(s) e "
                    f"{r['snapshots_matific'] + r['snapshots_elefante']} "
                    "registro(s) de plataforma combinados.",
        **r,
    }


@router.get("/alunos/duplicados", response_model=dict)
def alunos_duplicados(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """PRÉVIA da fusão em lote (read-only): candidatos a aluno duplicado por
    nível de confiança (nome idêntico/subconjunto/abreviação + MESMA turma).
    Nada é alterado; o gestor marca quais confirmar. Admin global e coordenador
    da PRÓPRIA escola veem. A Secretaria (rede) é barrada: a prévia lista NOMES
    de criança (LGPD) — escola_autorizada só nega a ESCRITA, não este GET."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    candidatos = alunos_dedup.plano_deduplicacao(db, escola_id)
    return {"candidatos": candidatos, "total": len(candidatos),
            "alta": sum(1 for c in candidatos if c["confianca"] == "alta"),
            "provavel": sum(1 for c in candidatos if c["confianca"] == "provavel"),
            "revisar": sum(1 for c in candidatos if c["confianca"] == "revisar")}


@router.post("/alunos/duplicados/corrigir", response_model=dict)
def corrigir_alunos_duplicados(
    dados: CorrigirDuplicadosAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Aplica só as fusões CONFIRMADAS (``loser_ids``), par-a-par, numa única
    transação — UM commit e UM recálculo de escola no fim. Cada par vira um log
    ``aluno.fundido`` (com a foto pré-fusão); falhas individuais são reportadas
    sem abortar o lote. Irreversível → exige confirmação "FUNDIR"."""
    if dados.confirmacao.strip().upper() != "FUNDIR":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Confirmação inválida. Digite FUNDIR para confirmar.")
    resultado = alunos_dedup.aplicar_deduplicacao(
        db, escola_id, dados.loser_ids, usuario.id)
    registrar(db, "aluno.duplicados_corrigidos", escola_id=escola_id,
              usuario_id=usuario.id, entidade="escola", entidade_id=escola_id,
              detalhes={"fusoes": resultado["fundidos"],
                        "falhas": len(resultado["falhas"])})
    db.commit()
    if resultado["fundidos"]:
        _recalcular_escola(db, escola_id)
    n = resultado["fundidos"]
    return {**resultado,
            "mensagem": (f"{n} fusão(ões) aplicada(s)." if n
                         else "Nenhuma fusão aplicada.")}


# A fusão AUTOMÁTICA do passivo foi removida (revisão adversarial: nenhum sinal é
# seguro o bastante para fundir/deletar registro de criança sem revisão humana).
# O passivo é resolvido pela ferramenta MANUAL acima (detecção + Selecionar todos).


# --- Turmas e Professores ---------------------------------------------------

def _validar_professor(db: Session, escola_id: int, professor_id: int | None) -> None:
    if professor_id is None:
        return
    professor = db.get(Professor, professor_id)
    if professor is None or professor.escola_id != escola_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Professor inválido para esta escola.")


def _validar_nome_unico(db: Session, escola_id: int, nome: str, ano_letivo: int,
                        ignorar_id: int | None = None) -> None:
    consulta = select(Turma).where(
        Turma.escola_id == escola_id,
        Turma.ano_letivo == ano_letivo,
        func.lower(Turma.nome) == nome.strip().lower(),
    )
    if ignorar_id is not None:
        consulta = consulta.where(Turma.id != ignorar_id)
    if db.execute(consulta).scalars().first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe a turma “{nome.strip()}” no ano letivo "
                            f"{ano_letivo}.")


def _turma_da_escola(db: Session, escola_id: int, turma_id: int) -> Turma:
    turma = db.get(Turma, turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    return turma


def _turma_out(db: Session, turma: Turma) -> TurmaOut:
    saida = TurmaOut.model_validate(turma)
    if turma.professor_id:
        professor = db.get(Professor, turma.professor_id)
        saida.professor_nome = professor.nome if professor else None
    saida.total_alunos = db.execute(
        select(func.count())
        .select_from(Matricula)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.turma_id == turma.id,
               Matricula.ano_letivo == turma.ano_letivo,
               Aluno.status == "ativo")
    ).scalar_one()
    # Contagem CRUA (qualquer ano/situação): é o que a exclusão enxerga.
    saida.total_matriculas = db.execute(
        select(func.count()).select_from(Matricula)
        .where(Matricula.turma_id == turma.id)
    ).scalar_one()
    return saida


@router.get("/turmas", response_model=list[TurmaOut])
def listar_turmas(
    escola_id: int = Depends(escola_autorizada),
    todas: bool = Query(default=False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Turmas ativas do ano letivo ativo; `todas=true` inclui arquivadas e
    outros anos (tela de gestão). Filtros e seletores usam o padrão."""
    ano = _ano_ativo(db, escola_id)
    # Matrículas CRUAS por turma (qualquer ano/situação) — subconsulta
    # correlacionada para não conflitar com o JOIN filtrado do total_alunos.
    sub_matriculas = (
        select(func.count())
        .select_from(Matricula)
        .where(Matricula.turma_id == Turma.id)
        .correlate(Turma)
        .scalar_subquery()
    )
    consulta = (
        select(Turma, Professor.nome, func.count(Aluno.id), sub_matriculas)
        .outerjoin(Professor, Turma.professor_id == Professor.id)
        .outerjoin(Matricula, (Matricula.turma_id == Turma.id)
                   & (Matricula.ano_letivo == Turma.ano_letivo))
        .outerjoin(Aluno, (Aluno.id == Matricula.aluno_id)
                   & (Aluno.status == "ativo"))
        .where(Turma.escola_id == escola_id)
        .group_by(Turma.id, Professor.nome)
        .order_by(Turma.ano_letivo.desc(), Turma.ano_escolar, Turma.nome)
    )
    if not todas:
        consulta = consulta.where(Turma.ano_letivo == ano,
                                  Turma.status == "ativa")
    # Professor: só as turmas designadas a ele (isto também restringe os
    # filtros de turma em todas as telas).
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        consulta = consulta.where(Turma.id.in_(permitidas))
    saida = []
    for turma, professor_nome, total_alunos, total_matriculas in db.execute(consulta).all():
        item = TurmaOut.model_validate(turma)
        item.professor_nome = professor_nome
        item.total_alunos = total_alunos
        item.total_matriculas = total_matriculas
        saida.append(item)
    return saida


def _ordem_alunos(ordenar: str) -> list:
    """Cláusulas ORDER BY portáveis (SQLite/Postgres) por critério do painel.
    Os ".is_(None)" jogam os NULOS para o fim de forma independente do banco."""
    if ordenar == "data":
        return [Aluno.created_at.desc()]
    if ordenar == "chamada":
        return [Aluno.numero_chamada.is_(None), Aluno.numero_chamada.asc()]
    if ordenar == "desempenho":
        return [Nota.nota_geral.is_(None), Nota.nota_geral.desc()]
    # "nome" | "alfabetica" | "serie" (numa turma a série é única) | padrão
    return [Aluno.nome.asc()]


@router.get("/turmas/{turma_id}/alunos", response_model=list[AlunoGestaoOut])
def listar_alunos_da_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    busca: str | None = Query(default=None),
    ordenar: str = Query(default="nome"),
    incluir_inativos: bool = Query(default=False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Alunos da turma para o painel de gestão: com nota, posição e data de
    cadastro; busca por nome e ordenação. `incluir_inativos` traz também os
    arquivados/excluídos (para restaurar ou apagar de vez).

    A posição só sai para quem está no ranking: ficha ativa numa turma que
    concorre (1º ao 5º ano). A Nota de quem saiu (arquivado, transferido,
    excluído) ou está numa turma de Fase é de um cálculo antigo, e a posição dela
    hoje é de outra criança — o painel mostrava duas crianças em 1º."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None and turma_id not in permitidas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    if permitidas is not None:
        # `incluir_inativos` serve à GESTÃO (restaurar/apagar de vez, ações de
        # admin/coordenador): o professor restrito segue só com os ativos, como
        # em /alunos, no perfil e na evolução (permissoes.alunos_permitidos).
        incluir_inativos = False
    consulta = (
        select(Aluno, Nota)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .outerjoin(Nota, (Nota.aluno_id == Aluno.id)
                   & (Nota.ano_letivo == turma.ano_letivo))
        .where(Aluno.escola_id == escola_id,
               Matricula.turma_id == turma_id,
               Matricula.ano_letivo == turma.ano_letivo)
    )
    if not incluir_inativos:
        consulta = consulta.where(Aluno.status == "ativo")
    if busca:
        consulta = consulta.where(Aluno.nome.ilike(f"%{busca}%"))
    consulta = consulta.order_by(*_ordem_alunos(ordenar), Aluno.nome.asc())

    premiavel = elegibilidade.participa_de_premiacao(turma.ano_escolar)
    saida = []
    for aluno, nota in db.execute(consulta).all():
        item = AlunoGestaoOut.model_validate(aluno)
        item.turma = turma.nome
        item.ano_escolar = turma.ano_escolar
        item.nota_geral = nota.nota_geral if nota else None
        # Só quem está no ranking (turma premiável, ficha ativa) mostra posição.
        no_ranking = nota is not None and premiavel and aluno.status == "ativo"
        item.posicao = nota.posicao if no_ranking else None
        saida.append(item)
    return saida


@router.post("/turmas", response_model=TurmaOut, status_code=status.HTTP_201_CREATED)
def criar_turma(
    dados: TurmaCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    _validar_professor(db, escola_id, dados.professor_id)
    _validar_nome_unico(db, escola_id, dados.nome, dados.ano_letivo)
    turma = Turma(escola_id=escola_id, **{**dados.model_dump(),
                                          "nome": dados.nome.strip()})
    db.add(turma)
    try:
        db.flush()
        registrar(db, "turma.criada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="turma", entidade_id=turma.id, detalhes={"nome": turma.nome})
        db.commit()
    except IntegrityError:
        # Corrida na criação manual (dois gestores, mesma turma): o índice único
        # uq_turma_escola_ano_nome barra a 2ª — vira 409, não 500 nem duplicata.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe a turma “{dados.nome.strip()}” no ano letivo "
                            f"{dados.ano_letivo}.")
    db.refresh(turma)
    return _turma_out(db, turma)


def _exigir_turma_sem_alunos_ativos(db: Session, escola_id: int, turma: Turma) -> None:
    """Decisão D17: não se arquiva turma com matrícula ativa.

    Arquivar só tira a turma dos filtros; NÃO encerra as matrículas. Com aluno
    ativo dentro, a criança seguia em /alunos, rankings, premiações e
    certificado ligada a uma turma invisível, e a sincronização mandava as
    fichas dela para revisão. Por isso o arquivamento exige que a turma esteja
    sem aluno ativo: quem ainda está nela é transferido (ou marcado como
    transferido) antes.

    "Matrícula ativa" = matrícula NESTA turma, do ano letivo ativo da escola ou
    posterior, de aluno com status "ativo". Matrícula de ano anterior é
    histórico: arquivar as turmas do ano que passou continua livre, mesmo com as
    crianças ativas hoje em outras turmas. Conta pelo ano da MATRÍCULA (não da
    turma): dado legado (de antes da trava do destino,
    ``_exigir_destino_do_ano_ativo``) pode ter a matrícula do ano ativo numa
    turma de outro ano, e essa criança está, de fato, nela.

    Toma a mesma trava das importações e sincronizações da escola (no-op no
    SQLite): uma importação em andamento não grava matrícula nova entre a
    contagem e o arquivamento."""
    bloquear_escola_para_importacao(db, escola_id)
    ano = _ano_ativo(db, escola_id)
    ativos = db.execute(
        select(func.count(func.distinct(Matricula.aluno_id)))
        .select_from(Matricula)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.turma_id == turma.id,
               Matricula.ano_letivo >= ano,
               Aluno.status == "ativo")
    ).scalar_one()
    if ativos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A turma “{turma.nome}” não pode ser arquivada: tem {ativos} "
            f"aluno(s) ativo(s) matriculado(s) nela a partir do ano letivo "
            f"{ano}. Arquivar não encerra as matrículas — esses alunos "
            "continuariam nos rankings, premiações e relatórios ligados a uma "
            "turma fora dos filtros. Antes de arquivar, abra a turma e use "
            "“Transferir de turma” (ou, para quem saiu da escola, “Marcar como "
            "transferido”).")


def _exigir_origem_do_ano_ativo(origem: Turma, ano: int) -> None:
    """"Transferir de turma" a partir do painel de uma turma de OUTRO ano letivo:
    409. O painel lista os alunos pela matrícula do ano da turma (histórico), mas
    transferir move a matrícula do ano ATIVO — a da turma atual da criança, em
    outra sala. A turma antiga continuaria com as matrículas dela (e sem poder
    ser excluída): o caminho para tirá-la da lista é arquivar."""
    if origem.ano_letivo == ano:
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"A turma “{origem.nome}” é do ano letivo {origem.ano_letivo}. “Transferir de "
        f"turma” move a matrícula do ano letivo ativo ({ano}) — a da turma atual do "
        f"aluno, não a desta turma —, e as matrículas de {origem.ano_letivo} são "
        "histórico. Nada foi transferido. Para tirar esta turma da lista, arquive-a "
        "em Turmas: o histórico fica preservado. Para mudar a turma atual de um "
        f"aluno, abra a turma dele do ano letivo {ano}.")


def _exigir_duplicadas_do_ano_da_canonica(db: Session, escola_id: int, canonica: Turma,
                                          duplicada_ids: list[int]) -> None:
    """"Corrigir turmas duplicadas": a canônica RECEBE as matrículas das
    duplicadas, que têm de ser do MESMO ano letivo dela — senão 409 para o pedido
    inteiro, antes de mover qualquer matrícula. É a trava do destino
    (``_exigir_destino_do_ano_ativo``) nesta porta: com a canônica de 2025, as
    matrículas de 2026 de uma duplicada de 2026 iriam para uma turma de outro ano.
    A tela só propõe grupos do mesmo ano (``turmas_dedup.detectar`` agrupa por
    ano letivo), e consolidar entre si as duplicadas de um ano anterior segue
    livre. Duplicada inexistente ou de outra escola: o 400 de sempre, de
    ``turmas_dedup.consolidar``."""
    for duplicada_id in duplicada_ids:
        dup = db.get(Turma, duplicada_id)
        if dup is None or dup.escola_id != escola_id or dup.id == canonica.id:
            continue
        if dup.ano_letivo != canonica.ano_letivo:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A turma “{dup.nome}” é do ano letivo {dup.ano_letivo}, e a canônica "
                f"“{canonica.nome}” é de {canonica.ano_letivo}: consolidar levaria as "
                "matrículas de uma para uma turma de outro ano. Nada foi consolidado. "
                "Só se consolidam turmas do mesmo ano letivo.")


def _exigir_turma_sem_matricula_de_outro_ano(db: Session, turma: Turma,
                                             novo_ano: int) -> None:
    """Mudar o ANO LETIVO de uma turma muda o ano da turma de quem está nela: com
    matrícula de outro ano dentro (a de 2026 numa turma que passaria a 2025, ou o
    histórico de 2025 numa que passaria a 2026), a matrícula ficaria numa turma de
    outro ano — o estado que a trava do destino (``_exigir_destino_do_ano_ativo``)
    fecha em transferir e cadastrar. 409, nada muda. Corrigir o ano de uma turma
    vazia, ou cujas matrículas já são todas do ano novo, segue livre."""
    outras = db.execute(
        select(func.count()).select_from(Matricula)
        .where(Matricula.turma_id == turma.id, Matricula.ano_letivo != novo_ano)
    ).scalar_one()
    if not outras:
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"A turma “{turma.nome}” tem {outras} matrícula(s) de ano letivo diferente de "
        f"{novo_ano}: mudar o ano letivo dela deixaria essas matrículas numa turma de "
        "outro ano. Nada foi alterado. Para outro ano letivo, cadastre uma turma nova; "
        "esta fica com as matrículas dela.")


def _exigir_alunos_na_origem(db: Session, ids: list[int], origem: Turma, ano: int) -> None:
    """Com ``turma_origem_id``, todo aluno selecionado precisa ter a matrícula do
    ano ativo NA origem; senão (lista desatualizada — outro gestor já o moveu)
    409 para o pedido inteiro, sem mover ninguém pela metade."""
    na_origem = set(db.execute(
        select(Matricula.aluno_id)
        .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano,
               Matricula.turma_id == origem.id)
    ).scalars().all())
    fora = [i for i in ids if i not in na_origem]
    if not fora:
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"{len(fora)} aluno(s) selecionado(s) não está(ão) na turma “{origem.nome}” no "
        f"ano letivo {ano} — a lista pode estar desatualizada. Nada foi transferido: "
        "recarregue a turma e tente de novo.")


# Campos da turma que entram no ranking: a série (elegibilidade e fator de série,
# no motor e na leitura), o turno (bônus de leitura na escola, no motor) e o ano
# letivo (a leitura do ranking só considera as turmas do ano ativo; o recálculo
# também invalida o cache do painel, que já mostrava a lista de antes).
_CAMPOS_DA_TURMA_NO_CALCULO = ("ano_escolar", "turno", "ano_letivo")


@router.put("/turmas/{turma_id}", response_model=TurmaOut)
def atualizar_turma(
    turma_id: int,
    dados: TurmaUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Edição parcial — também cobre Arquivar/Reativar via `status`.

    Arquivar (passar de "ativa" para "arquivada") é RECUSADO com 409 enquanto a
    turma tiver aluno ativo matriculado nela no ano letivo ativo (ou posterior):
    ver ``_exigir_turma_sem_alunos_ativos``. Reativar e editar uma turma que já
    está arquivada seguem como antes.

    Mudar o ``ano_letivo`` de turma com matrícula de outro ano dentro também é
    409 (``_exigir_turma_sem_matricula_de_outro_ano``): a matrícula ficaria numa
    turma de outro ano. Toma antes a trava da escola (no-op no SQLite), a mesma das
    portas que gravam matrícula: um cadastro, uma transferência ou um /resolver não
    grava, entre a contagem e a troca do ano, uma matrícula do ano que a turma está
    deixando (ela ficaria numa turma de outro ano).

    Mudar a SÉRIE, o TURNO ou o ANO LETIVO recalcula a escola depois do commit,
    como toda outra porta que mexe na população do ranking (ações em massa, fusão,
    exclusões, consolidar turmas). A série decide quem concorre (1º ao 5º ano; as
    Fases não) e o fator de série da dificuldade; o turno, no perfil personalizado,
    o bônus de livro lido na escola. Sem o recálculo, a criança da turma que virava
    "2º Ano" ficava sem nota e fora do ranking, a turma que virava Fase deixava
    buraco nas posições dos outros, e a Nota congelada de quem voltava de Fase para
    Ano repetia a posição de outra criança — no ranking e no certificado de mérito.
    Os outros campos (nome, professor, capacidade, observações, situação) não
    entram na conta e não recalculam."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    campos = dados.model_dump(exclude_unset=True)
    muda_a_conta = any(chave in campos and campos[chave] != getattr(turma, chave)
                       for chave in _CAMPOS_DA_TURMA_NO_CALCULO)
    if campos.get("status") == "arquivada" and turma.status != "arquivada":
        _exigir_turma_sem_alunos_ativos(db, escola_id, turma)
    if campos.get("ano_letivo") is not None and campos["ano_letivo"] != turma.ano_letivo:
        bloquear_escola_para_importacao(db, escola_id)
        _exigir_turma_sem_matricula_de_outro_ano(db, turma, campos["ano_letivo"])
    if "professor_id" in campos:
        _validar_professor(db, escola_id, campos["professor_id"])
    nome = campos.get("nome", turma.nome).strip()
    ano_letivo = campos.get("ano_letivo", turma.ano_letivo)
    if "nome" in campos or "ano_letivo" in campos:
        _validar_nome_unico(db, escola_id, nome, ano_letivo, ignorar_id=turma.id)
    if "nome" in campos:
        campos["nome"] = nome
    for chave, valor in campos.items():
        setattr(turma, chave, valor)
    registrar(db, "turma.atualizada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="turma", entidade_id=turma.id, detalhes=campos)
    try:
        db.commit()
    except IntegrityError:  # renomear para uma turma que já existe (índice único)
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe a turma “{nome}” no ano letivo {ano_letivo}.")
    if muda_a_conta:
        _recalcular_escola(db, escola_id)
    db.refresh(turma)
    return _turma_out(db, turma)


def _excluir_turmas(db: Session, escola_id: int, usuario: Usuario,
                    turma_ids: list[int], com_alunos: bool) -> dict:
    """Exclui turmas (validadas por escola).

    Com ``com_alunos``: apaga fisicamente (com todos os dados) SOMENTE os alunos
    cujas matrículas estão TODAS dentro das turmas selecionadas. Um aluno que
    ainda tenha matrícula em OUTRA turma (ex.: o ano letivo ativo, quando se
    exclui uma turma antiga) NÃO é apagado — é apenas DESVINCULADO das turmas
    excluídas, preservando a ficha e os dados dos outros anos. Isso evita apagar
    permanentemente a criança e os dados atuais dela ao limpar um histórico.

    Sem ``com_alunos``: as turmas com QUALQUER matrícula ficam BLOQUEADAS (só as
    vazias são excluídas). Recalcula uma vez ao final se algum aluno foi afetado.

    Decisão D19: com ``com_alunos`` e aluno matriculado em alguma das turmas, só
    o Admin Global passa (403 para os demais, ANTES de qualquer DELETE). Tudo —
    alunos, dados, vínculos, turmas e a auditoria — sai num ÚNICO commit: uma
    falha no meio desfaz a operação inteira. A auditoria ``turma.exclusao_com_
    alunos`` guarda, só com ids e contagens (sem nome), o que foi apagado.

    Devolve: excluidas, bloqueadas, alunos_excluidos, alunos_desvinculados e
    dados_removidos (contagens por tipo; vazio quando nenhum aluno foi tocado)."""
    # Mesma trava das importações e sincronizações da escola (no-op no SQLite):
    # nenhuma matrícula nova entra entre a leitura do estado e a exclusão.
    bloquear_escola_para_importacao(db, escola_id)
    turmas = list(db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.id.in_(turma_ids))
    ).scalars())
    if not turmas:
        return {"excluidas": 0, "bloqueadas": 0, "alunos_excluidos": 0,
                "alunos_desvinculados": 0, "dados_removidos": {}}
    ids = [t.id for t in turmas]
    # Alunos com matrícula (qualquer ano/situação) em alguma das turmas.
    aluno_ids = list(db.execute(
        select(Matricula.aluno_id).where(Matricula.turma_id.in_(ids)).distinct()
    ).scalars())

    a_excluir = turmas
    bloqueadas = 0
    alunos_excluidos = 0
    alunos_desvinculados = 0
    contagens: dict = {}
    if aluno_ids:
        if com_alunos:
            _exigir_admin_global_para_apagar_alunos(usuario, turmas, len(aluno_ids))
            # Quem AINDA tem matrícula fora do conjunto excluído é preservado.
            ainda = set(db.execute(
                select(Matricula.aluno_id).where(
                    Matricula.aluno_id.in_(aluno_ids),
                    Matricula.turma_id.notin_(ids),
                ).distinct()
            ).scalars())
            apagar = [aid for aid in aluno_ids if aid not in ainda]
            if apagar:
                # Só destes as matrículas estão todas nas turmas excluídas.
                alunos_excluidos = _apagar_alunos_e_dados(
                    db, escola_id, usuario, apagar, contagens=contagens)
            if ainda:
                # Remove APENAS o vínculo com as turmas excluídas (mantém o aluno).
                contagens["matriculas_desvinculadas"] = db.execute(delete(Matricula).where(
                    Matricula.aluno_id.in_(ainda), Matricula.turma_id.in_(ids))).rowcount
                alunos_desvinculados = len(ainda)
                registrar(db, "turma.alunos_desvinculados", escola_id=escola_id,
                          usuario_id=usuario.id,
                          detalhes={"turmas": ids, "alunos": alunos_desvinculados,
                                    "motivo": "exclusao_turma_com_alunos_matriculado_em_outra"})
        else:
            com = set(db.execute(
                select(Matricula.turma_id).where(Matricula.turma_id.in_(ids)).distinct()
            ).scalars())
            a_excluir = [t for t in turmas if t.id not in com]
            bloqueadas = len(turmas) - len(a_excluir)

    for t in a_excluir:
        registrar(db, "turma.excluida", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="turma", entidade_id=t.id,
                  detalhes={"nome": t.nome, "com_alunos": com_alunos})
        db.delete(t)
    if alunos_excluidos or alunos_desvinculados:
        # Resumo ÚNICO da exclusão física, na mesma transação: quem, quais
        # turmas e quanto saiu de cada tipo. Só ids e contagens (LGPD).
        registrar(db, "turma.exclusao_com_alunos", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="turma",
                  entidade_id=ids[0] if len(ids) == 1 else None,
                  detalhes={"turmas": ids, "alunos_excluidos": alunos_excluidos,
                            "alunos_desvinculados": alunos_desvinculados,
                            "dados_removidos": contagens})
    db.commit()
    if alunos_excluidos or alunos_desvinculados:
        _recalcular_escola(db, escola_id)
    return {"excluidas": len(a_excluir), "bloqueadas": bloqueadas,
            "alunos_excluidos": alunos_excluidos,
            "alunos_desvinculados": alunos_desvinculados,
            "dados_removidos": contagens}


def _exigir_admin_global_para_apagar_alunos(usuario: Usuario, turmas: list[Turma],
                                             matriculados: int) -> None:
    """Decisão D19: excluir turma JUNTO com os alunos (exclusão física da ficha
    e de todos os dados de quem só está nela) é exclusivo do Admin Global. O
    admin e o coordenador da escola recebem 403 com o caminho que têm: mover
    os alunos e excluir só a turma, ou arquivá-la (D17)."""
    if usuario.is_global:
        return
    alvo = (f"A turma “{turmas[0].nome}” tem" if len(turmas) == 1
            else f"As {len(turmas)} turmas selecionadas têm")
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"{alvo} {matriculados} aluno(s) matriculado(s). Excluir a turma junto com "
        f"os alunos {_D19_APAGA_EM_DEFINITIVO} de quem só está nela — "
        f"{_D19_EXCLUSIVO}. Sem ele: transfira os alunos para outra turma "
        "e exclua só a turma, ou arquive a turma quando nenhum aluno ativo estiver "
        "nela.")


# Texto do D19, comum às duas portas de exclusão física de aluno (a turma com os
# alunos e a exclusão permanente direta): o mesmo motivo e a mesma régua.
_D19_APAGA_EM_DEFINITIVO = ("apaga em definitivo a ficha e todos os dados (leituras, "
                            "notas, retratos das plataformas, Quest)")
_D19_EXCLUSIVO = "por isso é exclusivo do Admin Global"


def _exigir_admin_global_para_exclusao_fisica(usuario: Usuario, quantidade: int) -> None:
    """Decisão D19 na exclusão permanente direta (/alunos/excluir-permanente):
    exclusão física de aluno é só do Admin Global. Os demais recebem 403 com o
    motivo do D19 e o caminho que têm (excluir — reversível —, arquivar ou
    marcar como transferido), antes de qualquer DELETE."""
    if usuario.is_global:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Excluir permanentemente {quantidade} aluno(s) {_D19_APAGA_EM_DEFINITIVO} "
        f"— {_D19_EXCLUSIVO}. Sem ele: use “Excluir” (o aluno sai das listas e "
        "rankings e pode ser restaurado depois), “Arquivar” ou, para quem saiu da "
        "escola, “Marcar como transferido”.")


def _resumo_dados_removidos(contagens: dict) -> str:
    """Texto curto do que a exclusão física levou (só o que é > 0), para a
    mensagem de retorno: nada é apagado em silêncio."""
    rotulos = (("leituras", "leitura(s)"), ("notas", "nota(s)"),
               ("snapshots", "retrato(s) das plataformas"), ("eventos", "evento(s)"),
               ("perfis_quest", "perfil(is) do Quest"))
    valores = {**contagens, "snapshots": (contagens.get("snapshots_matific", 0)
                                          + contagens.get("snapshots_elefante", 0))}
    partes = [f"{valores[chave]} {rotulo}" for chave, rotulo in rotulos
              if valores.get(chave)]
    return ", ".join(partes)


@router.delete("/turmas/{turma_id}", response_model=dict)
def excluir_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
    com_alunos: bool = Query(default=False),
):
    """Exclusão definitiva de uma turma. Por padrão é BLOQUEADA se houver alunos
    vinculados (arquive para preservar o histórico). Com ``com_alunos=true``,
    remove TAMBÉM os alunos matriculados na turma e todos os seus dados
    (leituras, snapshots, notas, matrículas) — irreversível e, havendo aluno
    matriculado, exclusivo do Admin Global (D19; 403 para os demais)."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    nome = turma.nome
    if not com_alunos:
        # Trava clássica: sem alunos → exclui; com alunos → 409 orientando a
        # mover/remover, arquivar, ou (Admin Global) usar com_alunos=true.
        bloquear_escola_para_importacao(db, escola_id)
        vinculados = db.execute(
            select(func.count()).select_from(Matricula)
            .where(Matricula.turma_id == turma.id)
        ).scalar_one()
        if vinculados:
            ano = _ano_ativo(db, escola_id)
            if turma.ano_letivo < ano:
                # Turma de ano ANTERIOR: as matrículas dela são histórico e não
                # saem por "Transferir de turma" (ele move a matrícula do ano
                # ativo, da turma atual da criança). A saída é arquivar.
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"A turma “{nome}” é do ano letivo {turma.ano_letivo} e possui "
                    f"{vinculados} aluno(s) vinculado(s). Matrículas de ano anterior "
                    "são histórico e não saem por “Transferir de turma” (ele move a "
                    "matrícula do ano letivo ativo, da turma atual do aluno). Para "
                    "tirar esta turma da lista, arquive-a: o histórico fica preservado."
                    + (" Ou exclua a turma junto com os alunos." if usuario.is_global
                       else " Excluir a turma junto com os alunos é exclusivo do "
                            "Admin Global."))
            caminho_destrutivo = (
                "ou exclua a turma junto com os alunos, " if usuario.is_global
                else "")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A turma “{nome}” possui {vinculados} aluno(s) vinculado(s). "
                "Mova ou remova os alunos antes de excluir — "
                f"{caminho_destrutivo}ou arquive a turma para preservar o "
                "histórico (arquivar exige que nenhum aluno ativo esteja nela)."
                + ("" if usuario.is_global else
                   " Excluir a turma junto com os alunos é exclusivo do Admin Global."))
    r = _excluir_turmas(db, escola_id, usuario, [turma.id], com_alunos)
    msg = f"Turma “{nome}” excluída"
    if r["alunos_excluidos"]:
        msg += f" com {r['alunos_excluidos']} aluno(s) e todos os dados"
        resumo = _resumo_dados_removidos(r["dados_removidos"])
        if resumo:
            msg += f" ({resumo})"
    if r["alunos_desvinculados"]:
        msg += (f" ({r['alunos_desvinculados']} aluno(s) mantido(s) por ainda "
                "estarem em outra turma)")
    msg += "."
    return {"mensagem": msg, **r}


@router.post("/turmas/excluir", response_model=dict)
def excluir_turmas_massa(
    dados: ExcluirTurmas,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Exclusão em massa de turmas (botão 'excluir selecionadas'). Com
    ``com_alunos``, remove também os alunos e seus dados (havendo aluno
    matriculado, exclusivo do Admin Global — D19). Sem, as turmas com alunos
    são mantidas e reportadas em ``bloqueadas``."""
    r = _excluir_turmas(db, escola_id, usuario, dados.turma_ids, dados.com_alunos)
    partes = [f"{r['excluidas']} turma(s) excluída(s)"]
    if r["alunos_excluidos"]:
        resumo = _resumo_dados_removidos(r["dados_removidos"])
        partes.append(f"{r['alunos_excluidos']} aluno(s) e todos os dados removidos"
                      + (f" ({resumo})" if resumo else ""))
    if r["alunos_desvinculados"]:
        partes.append(f"{r['alunos_desvinculados']} aluno(s) mantido(s) por ainda "
                      "estarem em outra turma")
    if r["bloqueadas"]:
        partes.append(
            f"{r['bloqueadas']} com alunos foram mantida(s) — "
            + ("use ‘excluir com os alunos’ para removê-las" if usuario.is_global
               else "mova os alunos antes (excluir com os alunos é exclusivo do "
                    "Admin Global)"))
    return {"mensagem": "; ".join(partes) + ".", **r}


@router.get("/turmas/duplicadas", response_model=list[dict])
def listar_turmas_duplicadas(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Grupos de turmas que são a MESMA sala escrita de formas diferentes
    (ex.: '1 ANO A TARDE ANUAL (300302821)' e '1ºA'). Sugere como canônica o
    nome curto/padronizado e lista as duplicadas com a contagem de alunos."""
    return turmas_dedup.detectar(db, escola_id)


@router.post("/turmas/duplicadas/corrigir", response_model=dict)
def corrigir_turmas_duplicadas(
    grupos: list[ConsolidarTurmasIn],
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Consolida os grupos escolhidos: move as matrículas das duplicadas para a
    canônica, herda o titular quando ela não tem e remove as turmas duplicadas.
    Recalcula ao final. Não funde alunos — reporta possíveis duplicados.

    D17: a canônica RECEBE as matrículas (de alunos ativos, do ano ativo) das
    duplicadas — canônica arquivada é 409 para o pedido inteiro, ANTES de mover
    qualquer matrícula (``turma_arquivada.exigir_turma_ativa``). A tela só
    propõe grupos de turmas ativas (``turmas_dedup.detectar``); a recusa fecha a
    API direta e a corrida com o arquivamento, porque a trava da escola (a mesma
    do arquivamento e das importações) é tomada antes de ler as turmas.

    Duplicada de ano letivo diferente do da canônica: também 409 para o pedido
    inteiro, antes de mover qualquer matrícula
    (``_exigir_duplicadas_do_ano_da_canonica``).

    Duplicada com pontuação por nível própria (parâmetro do Admin Global),
    diferente da canônica: 409 para o pedido inteiro, antes de mover — o CASCADE
    apagava a configuração em silêncio (``turmas_dedup.motivo_da_recusa``)."""
    bloquear_escola_para_importacao(db, escola_id)
    for g in grupos:
        canonica = db.get(Turma, g.canonica_id)
        if canonica is not None and canonica.escola_id == escola_id:
            turma_arquivada.exigir_turma_ativa(canonica)
            _exigir_duplicadas_do_ano_da_canonica(db, escola_id, canonica,
                                                  g.duplicada_ids)
            duplicadas = [d for d in (db.get(Turma, i) for i in g.duplicada_ids
                                      if i != canonica.id)
                          if d is not None and d.escola_id == escola_id]
            motivo = turmas_dedup.motivo_da_recusa(db, escola_id, canonica, duplicadas)
            if motivo is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, motivo)
        # Canônica inexistente ou de outra escola: o 400 de sempre, de consolidar.
    resumos: list[dict] = []
    try:
        for g in grupos:
            resumos.append(turmas_dedup.consolidar(db, escola_id, g.canonica_id, g.duplicada_ids))
    except turmas_dedup.ConsolidacaoRecusada as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.motivo) from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    total_rem = sum(r["turmas_removidas"] for r in resumos)
    total_mov = sum(r["alunos_movidos"] for r in resumos)
    dup_total = sum(r["possiveis_alunos_duplicados"] for r in resumos)
    registrar(db, "turmas.consolidadas", escola_id=escola_id, usuario_id=usuario.id,
              entidade="turma", detalhes={"grupos": len(grupos),
                                          "removidas": total_rem, "alunos_movidos": total_mov})
    db.commit()
    _recalcular_escola(db, escola_id)

    msg = f"{total_rem} turma(s) duplicada(s) consolidada(s); {total_mov} aluno(s) migrado(s)."
    if dup_total:
        msg += (f" Atenção: {dup_total} nome(s) aparecem repetidos na(s) turma(s) — "
                "confira em Alunos e use “Fundir alunos” se for a mesma pessoa.")
    return {"mensagem": msg, "grupos": resumos, "turmas_removidas": total_rem,
            "alunos_movidos": total_mov, "possiveis_alunos_duplicados": dup_total}


@router.get("/professores", response_model=list[ProfessorOut])
def listar_professores(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    return db.execute(
        select(Professor).where(Professor.escola_id == escola_id).order_by(Professor.nome)
    ).scalars().all()


# --- E-mail do Professor = login da conta de professor -------------------------
#
# O e-mail de um `Professor` é a chave que liga uma CONTA às turmas dele
# (`permissoes.turmas_permitidas`) e é por ele que a edição acha a conta cujo
# LOGIN acompanha a troca. A autorização para reescrever um login vem só do
# SERVIDOR — da escola da rota (`escola_autorizada`) e do tipo da conta achada
# — e nunca do e-mail gravado no cadastro ou enviado no corpo. Por isso:
#   * a única conta que acompanha o e-mail de um Professor é a conta de
#     PROFESSOR desta escola (cargo professor, mesma escola, sem rede, não
#     global) — `_conta_do_professor`;
#   * um Professor só recebe um e-mail livre ou o da conta de professor desta
#     escola (vínculo do cadastro com a conta) — nunca o login de conta de
#     gestão, de outra escola, de rede (Secretaria) ou global, nem o e-mail
#     reservado ao dono (`ADMIN_GLOBAL_EMAIL`, promovido a `is_global` no boot)
#     — `_exigir_email_de_professor`.
# Sem isso (P0), um gestor de escola cadastrava um Professor com o e-mail de
# outra conta e, ao editá-lo, reescrevia o login dela: lockout de outra escola
# ou do dono e, com ADMIN_GLOBAL_EMAIL declarado, o coordenador virava admin
# global no reboot seguinte (`database._promover_admin_global`).

def _e_conta_de_professor_da_escola(conta: Usuario, escola_id: int) -> bool:
    return (conta.escola_id == escola_id and conta.cargo == "professor"
            and conta.rede_id is None and not conta.is_global)


def _conta_do_professor(db: Session, escola_id: int, email: str | None) -> Usuario | None:
    """A conta de login que acompanha o e-mail de um Professor: SÓ a conta de
    professor DESTA escola — nunca a de gestão, de outra escola, de rede ou
    global, mesmo que o cadastro (legado) carregue o e-mail dela. Nem a conta
    com o e-mail reservado ao dono (ainda não promovida no boot)."""
    email = (email or "").strip().lower()
    if not email or email_reservado_ao_dono(email):
        return None
    return db.execute(
        select(Usuario).where(func.lower(Usuario.email) == email,
                              Usuario.escola_id == escola_id,
                              Usuario.cargo == "professor",
                              Usuario.rede_id.is_(None),
                              Usuario.is_global.is_(False))
    ).scalars().first()


def _exigir_email_de_professor(db: Session, escola_id: int, email: str,
                               conta_atual: Usuario | None = None) -> None:
    """Recusa o e-mail que um Professor desta escola não pode ter.

    ``email`` já normalizado (strip + minúsculas). ``conta_atual`` é a conta de
    professor que vai ACOMPANHAR a troca (a do próprio professor, na edição) —
    ela não colide consigo mesma. Sem ``conta_atual`` (cadastro, ou professor
    ainda sem conta), o e-mail pode ser o da conta de professor desta escola.

    403 — e-mail reservado ao dono. Vale também para o admin global: a conta que
          acompanha um Professor tem a senha do PROFESSOR, e o boot a promoveria
          a ``is_global``.
    409 — o e-mail já é o login de outra conta: e-mail OU @username (o login
          aceita os dois, sem diferenciar caixa)."""
    if email_reservado_ao_dono(email):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Este e-mail é reservado à administração da plataforma.")
    donos = db.execute(
        select(Usuario).where((func.lower(Usuario.email) == email)
                              | (func.lower(Usuario.username) == email))
    ).scalars().all()
    for dono in donos:
        if conta_atual is not None and dono.id == conta_atual.id:
            continue
        if (conta_atual is None and (dono.email or "").strip().lower() == email
                and _e_conta_de_professor_da_escola(dono, escola_id)):
            continue
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Este e-mail já é o login de outra conta de acesso.")


@router.post("/professores", response_model=ProfessorOut, status_code=status.HTTP_201_CREATED)
def criar_professor(
    dados: ProfessorCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    campos = dados.model_dump()
    if campos.get("email"):
        campos["email"] = str(campos["email"]).strip().lower()
        _exigir_email_de_professor(db, escola_id, campos["email"])
    professor = Professor(escola_id=escola_id, **campos)
    db.add(professor)
    registrar(db, "professor.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", detalhes={"nome": dados.nome})
    db.commit()
    db.refresh(professor)
    return professor


@router.patch("/professores/{professor_id}", response_model=ProfessorOut)
def atualizar_professor(
    professor_id: int,
    dados: ProfessorUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Edita o NOME e/ou o E-MAIL do professor — ex.: completar um nome que veio
    só como apelido na importação, ou corrigir o e-mail. O e-mail é o LOGIN do
    professor e o que liga a conta às turmas dele: por isso, ao trocá-lo, a conta
    de acesso vinculada é atualizada junto (senão o professor perderia as turmas).
    Não mexe nos vínculos de turma (esses continuam pelo botão de vincular turmas)."""
    professor = db.get(Professor, professor_id)
    if professor is None or professor.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Professor não encontrado.")

    campos = dados.model_dump(exclude_unset=True)
    if campos.get("nome"):
        professor.nome = campos["nome"].strip()
    if campos.get("email"):
        novo_email = str(campos["email"]).strip().lower()
        atual = (professor.email or "").strip().lower()
        if novo_email != atual:
            # Conta de login vinculada a este professor (casa pelo e-mail ATUAL):
            # se existir, o e-mail dela acompanha a troca — é o mesmo e-mail que
            # o RBAC usa para achar as turmas do professor. SÓ a conta de
            # professor desta escola (`_conta_do_professor`); e o novo e-mail não
            # pode ser o login de outra conta nem o reservado ao dono.
            conta = _conta_do_professor(db, escola_id, atual)
            _exigir_email_de_professor(db, escola_id, novo_email, conta_atual=conta)
            if conta is not None:
                conta.email = novo_email
        professor.email = novo_email

    registrar(db, "professor.atualizado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", entidade_id=professor.id,
              detalhes={"nome": professor.nome, "email": professor.email})
    try:
        db.commit()
    except IntegrityError:
        # Corrida com outra gravação do mesmo login: o índice único decide.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Este e-mail já é o login de outra conta de acesso.")
    db.refresh(professor)
    return professor


@router.delete("/professores/{professor_id}", response_model=dict)
def excluir_professor(
    professor_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Remove o professor da equipe da escola. As TURMAS dele NÃO são apagadas —
    apenas ficam sem titular (professor_id nulo), para você revincular depois. A
    CONTA DE ACESSO (login) não é tocada aqui: para tirar o acesso, exclua também
    o usuário na tela de Usuários."""
    professor = db.get(Professor, professor_id)
    if professor is None or professor.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Professor não encontrado.")
    # Solta as turmas antes de excluir (evita quebrar o vínculo e não apaga as
    # salas — elas só ficam sem titular).
    turmas = db.execute(
        select(Turma).where(Turma.professor_id == professor_id)
    ).scalars().all()
    for turma in turmas:
        turma.professor_id = None
    nome = professor.nome
    db.delete(professor)
    registrar(db, "professor.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", entidade_id=professor_id,
              detalhes={"nome": nome, "turmas_desvinculadas": len(turmas)})
    db.commit()
    return {"mensagem": f"Professor “{nome}” removido."
                        + (f" {len(turmas)} turma(s) ficaram sem titular."
                           if turmas else "")}


@router.post("/professores/completo", status_code=status.HTTP_201_CREATED)
def criar_professor_completo(
    dados: ProfessorCompletoIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Cadastro completo do professor em um passo: o registro na equipe, a
    turma sob responsabilidade e a CONTA DE ACESSO (cargo professor) com senha
    legível gerada — devolvida uma ÚNICA vez aqui (não é armazenada; se for
    perdida, use a redefinição de senha por token). O e-mail liga a conta às
    turmas dele (é assim que o acesso restrito descobre quais turmas mostrar)."""
    from app.core.security import gerar_senha_legivel, hash_senha

    email = dados.email.strip().lower()
    turma = None
    if dados.turma_id is not None:
        turma = db.get(Turma, dados.turma_id)
        if turma is None or turma.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Turma inválida para esta escola.")

    # Com OU sem conta de acesso, o e-mail de um Professor não pode ser o login
    # de outra conta nem o reservado ao dono (ver `_exigir_email_de_professor`).
    # Antes, com `criar_acesso=False`, nada era conferido: o cadastro com o
    # e-mail da Secretaria (que guarda o escola_id de origem) ou da gestão
    # entrava por aqui e a fusão de duplicados apagava ou reescrevia aquela conta.
    _exigir_email_de_professor(db, escola_id, email)

    acesso = None
    if dados.criar_acesso:
        ja_existe = db.execute(
            select(Usuario).where(func.lower(Usuario.email) == email)
        ).scalar_one_or_none()
        if ja_existe is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Já existe uma conta com este e-mail — use outro ou desligue "
                "a criação do acesso.")
        senha = gerar_senha_legivel()
        db.add(Usuario(escola_id=escola_id, nome=dados.nome.strip(), email=email,
                       senha_hash=hash_senha(senha),
                       cargo="professor"))
        # Senha legível devolvida UMA vez ao criar o acesso — nunca é
        # armazenada em texto; se for perdida, use "Redefinir senha".
        acesso = {"email": email, "senha": senha}

    professor = Professor(escola_id=escola_id, nome=dados.nome.strip(), email=email)
    db.add(professor)
    db.flush()
    if turma is not None:
        turma.professor_id = professor.id

    registrar(db, "professor.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", entidade_id=professor.id,
              detalhes={"nome": professor.nome, "turma": turma.nome if turma else None,
                        "acesso_criado": dados.criar_acesso})
    db.commit()
    db.refresh(professor)
    return {
        "professor": ProfessorOut.model_validate(professor),
        "turma": turma.nome if turma else None,
        "acesso": acesso,
    }
