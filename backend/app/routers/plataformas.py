"""Módulos Matific e Elefante Letrado + Catálogo de Livros (PRD §55–§57).

A edição manual NUNCA sobrescreve histórico: cada correção gera uma
importação do tipo "manual" e um novo snapshot, preservando a linha do
tempo (§68) e deixando o antes/depois no log de auditoria.

GOVERNANÇA DO CATÁLOGO: o catálogo de livros é OFICIAL (Elefante Letrado) e
SOMENTE LEITURA para a escola (admin, coordenador, professor, Secretaria). Só o
Admin Global cria, corrige (nível/título) ou exclui livros.

SEMÂNTICA DA CORREÇÃO: cada ``Leitura`` guarda o NÍVEL CONGELADO do livro no
momento em que foi registrada (``Leitura.nivel_codigo``). Corrigir o catálogo,
portanto, vale para as PRÓXIMAS leituras — o histórico, as notas gravadas e os
rankings do passado não mudam. Aplicar ao histórico é uma ação EXPLÍCITA do
Admin Global (``aplicar_ao_historico=true`` no PATCH), auditada com de/para e
contagem, que reescreve o nível congelado daquele livro e recalcula a escola.

GOVERNANÇA DO AJUSTE MANUAL (snapshot/faixas): a trava não pode depender de
configuração que a própria escola desliga — ver
``evidencia_elefante_da_plataforma``.
"""
import inspect

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, exigir_modulo_da_escola
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Escola,
    EventoAluno,
    Importacao,
    Leitura,
    Livro,
    LogAuditoria,
    Matricula,
    NivelDificuldade,
    PlataformaCredencial,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.models.base import agora
from app.schemas import (
    ElefanteAlunoOut,
    ElefanteEdicao,
    LivroCreate,
    LivroOut,
    LivroUpdate,
    MatificAlunoOut,
    MatificEdicao,
    NiveisLeituraEdicao,
)
from app.services import dificuldade_livro, permissoes, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Plataformas"])

# Vocabulário OFICIAL de níveis do Elefante: a escada A3 (AA…Z) mais o tier
# avançado Z+ e o A+ do catálogo. Qualquer outro código é recusado na edição.
NIVEIS_OFICIAIS: frozenset[str] = frozenset(scoring.NIVEIS_ORDENADOS) | {"Z+", "A+"}

MSG_CATALOGO_SOMENTE_LEITURA = (
    "O catálogo de livros é oficial (Elefante Letrado) e somente leitura para a "
    "escola. Correções de nível ou título são feitas pelo Admin Global da Constela.")

MSG_AJUSTE_COM_INTEGRACAO = (
    "Esta escola recebe o Elefante Letrado pela integração automática: o ajuste "
    "manual de livros por nível fica com o Admin Global da Constela, para não "
    "sobrescrever o dado oficial. Fale com o suporte.")

MSG_AJUSTE_COM_DADO_RECEBIDO = (
    "Esta escola já recebeu dados do Elefante Letrado vindos da plataforma: o "
    "ajuste manual de livros por nível fica com o Admin Global da Constela, para "
    "não sobrescrever o dado oficial. Desligar a integração ou remover a "
    "credencial NÃO reabre o ajuste — o que já foi recebido continua valendo. "
    "Fale com o suporte.")


def _linhas_modulo(db: Session, escola_id: int, modelo,
                   turma_ids: list[int] | None = None):
    """Alunos ativos do ano letivo com o snapshot mais recente da plataforma.

    "Mais recente" pela data_referencia (id desempata): um relatório de
    período antigo importado depois (backfill mensal do Matific) não pode
    virar o estado atual do módulo.

    `turma_ids` restringe às turmas informadas (professor vê só as dele);
    None = escola inteira (admin/coordenador)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    ids = scoring.ids_snapshots_atuais(modelo, escola_id)
    consulta = (
        select(Aluno, Turma, modelo)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        .outerjoin(modelo, (modelo.aluno_id == Aluno.id) & modelo.id.in_(ids))
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
        .order_by(Aluno.nome)
    )
    if turma_ids is not None:
        consulta = consulta.where(Matricula.turma_id.in_(turma_ids))
    return db.execute(consulta).all()


def _aluno_da_escola(db: Session, escola_id: int, aluno_id: int) -> Aluno:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    return aluno


def _importacao_manual(db, escola_id, usuario_id, plataforma) -> Importacao:
    importacao = Importacao(escola_id=escola_id, usuario_id=usuario_id,
                            plataforma=plataforma, tipo="manual", qtd_alunos=1)
    db.add(importacao)
    db.flush()
    return importacao


# --- Matific (PRD §55) --------------------------------------------------------

@router.get("/matific", response_model=list[MatificAlunoOut],
            dependencies=[Depends(exigir_modulo_da_escola("matematica"))])
def modulo_matific(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    # Professor restrito vê só as turmas dele (None = escola inteira p/ admin/coord).
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    return [
        MatificAlunoOut(
            aluno_id=aluno.id, nome=aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            atividades=snap.atividades if snap else 0,
            estrelas=snap.estrelas if snap else 0,
            pontuacao_media=snap.pontuacao_media if snap else 0.0,
            data_referencia=snap.data_referencia if snap else None,
        )
        for aluno, turma, snap in _linhas_modulo(
            db, escola_id, SnapshotMatific, turma_ids=permitidas)
    ]


@router.put("/matific/{aluno_id}", response_model=MatificAlunoOut,
            dependencies=[Depends(exigir_modulo_da_escola("matematica"))])
def editar_matific(
    aluno_id: int,
    dados: MatificEdicao,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    anterior = db.execute(
        select(SnapshotMatific)
        .where(SnapshotMatific.aluno_id == aluno_id)
        .order_by(SnapshotMatific.data_referencia.desc(),
                  SnapshotMatific.id.desc()).limit(1)
    ).scalar_one_or_none()

    # MÉDIA AUSENTE = "não mexi nisso": preserva a do snapshot anterior. Sem
    # isto, corrigir só as atividades de um registro cuja média está fora da
    # escala 0–5 (edição antiga, quando o limite era 100, ou base de demo)
    # devolveria 422 — e a única saída seria digitar uma média nova, isto é,
    # inventar um número no lugar do que foi medido.
    media_preservada = dados.pontuacao_media is None
    media = (anterior.pontuacao_media if anterior else 0.0) if media_preservada \
        else dados.pontuacao_media
    importacao = _importacao_manual(db, escola_id, usuario.id, "matific")
    snap = SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        atividades=dados.atividades, estrelas=dados.estrelas,
        pontuacao_media=media,
    )
    db.add(snap)
    registrar(db, "matific.editado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={
                  "motivo": dados.motivo,
                  "de": {"atividades": anterior.atividades if anterior else 0,
                         "estrelas": anterior.estrelas if anterior else 0,
                         "pontuacao_media": anterior.pontuacao_media if anterior else 0.0},
                  "para": {"atividades": dados.atividades, "estrelas": dados.estrelas,
                           "pontuacao_media": media},
                  # A auditoria distingue "média mantida" de "média digitada".
                  "media_preservada": media_preservada,
              })
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    db.refresh(snap)
    return MatificAlunoOut(
        aluno_id=aluno.id, nome=aluno.nome, turma=None, ano_escolar=None,
        atividades=snap.atividades, estrelas=snap.estrelas,
        pontuacao_media=snap.pontuacao_media, data_referencia=snap.data_referencia,
    )


# --- Elefante Letrado (PRD §56) -------------------------------------------------

def integracao_elefante_ativa(db: Session, escola_id: int) -> bool:
    """A escola recebe o Elefante pela INTEGRAÇÃO automática? Mesmo critério da
    tela Integrações (``sync/router.status_escola``): credencial do Elefante
    VÁLIDA (``conectada``) ou agenda de sincronização LIGADA (``agendada``)."""
    credencial = db.execute(
        select(PlataformaCredencial.status).where(
            PlataformaCredencial.escola_id == escola_id,
            PlataformaCredencial.plataforma == "elefante")
    ).scalars().first()
    if credencial == "valida":
        return True
    return db.execute(
        select(SincronizacaoConfig.id).where(
            SincronizacaoConfig.escola_id == escola_id,
            SincronizacaoConfig.plataforma == "elefante",
            SincronizacaoConfig.ativo.is_(True)).limit(1)
    ).first() is not None


# Marcas de auditoria de que o Elefante DESTA escola passou pela plataforma.
# ``LogAuditoria`` NUNCA é apagado — a exclusão permanente de usuário só anonimiza
# a autoria (``routers/admin.py``) e não há rota que remova linhas —, então é a
# marca mais imutável que a sincronização deixa.
#
# Conexão da credencial (tela Integrações) e conclusão de importação: as duas
# servem a QUALQUER plataforma, o detalhe diz qual (e, na importação, o ``tipo``
# separa o relatório da plataforma do ajuste manual da própria escola).
ACOES_CREDENCIAL: frozenset[str] = frozenset({
    "sync.credencial_salva", "sync.credencial_removida"})
ACAO_IMPORTACAO = "importacao.concluida"
# Reconciliações de catálogo: só a importação/sincronização do Elefante as grava
# (``routers.importacoes._AcervoEscola``), então já são específicas.
ACOES_CATALOGO_ELEFANTE: frozenset[str] = frozenset({
    "livro.vinculado_catalogo",
    "livro.nivel_oficial_restaurado",
    "livro.nivel_divergente",
    "livro.id_oficial_inconsistente",
})


def evidencia_elefante_da_plataforma(db: Session, escola_id: int) -> str | None:
    """Marca HISTÓRICA de que o Elefante desta escola já veio da plataforma.

    A trava do ajuste manual não pode depender da integração estar LIGADA: a
    própria escola apaga a credencial e desliga a agenda (``sync/router``), o que
    reabriria a edição do dado oficial. Aqui a pergunta é outra e a escola não
    apaga a resposta: *este Elefante já chegou da plataforma alguma vez?*

    Marcas verificadas, da mais imutável para a mais direta:

    1. ``LogAuditoria`` — nunca apagado (nem pela exclusão permanente de usuário,
       que só anonimiza a autoria, nem pela restauração de backup, que não
       inclui a tabela): ``sync.credencial_salva``/``removida`` com
       ``plataforma="elefante"`` no detalhe (a escola conectou a plataforma),
       ``importacao.concluida`` de um relatório do Elefante que não seja
       ``tipo="manual"`` e as reconciliações de catálogo que só a
       importação/sync do Elefante grava;
    2. ``Importacao`` do Elefante que NÃO seja ``tipo="manual"`` — o registro que
       a sincronização/API cria ao aplicar um relatório (``_importacao_manual``
       é o ajuste da própria escola e por isso fica de fora);
    3. ``EventoAluno`` do Elefante — o espelho evento a evento da sync;
    4. ``Leitura`` — só nasce de importação/sincronização do Elefante;
    5. ``SincronizacaoExecucao`` do Elefante — o histórico de execuções.

    As marcas 2 a 4 estão no backup (``services.backup.MODELOS``) e portanto
    somem numa restauração; as de auditoria e a de sincronização não — por isso
    a auditoria vem primeiro e cobre os mesmos fatos.

    Devolve o nome da marca encontrada (para auditoria/depuração) ou ``None``.
    """
    # A plataforma está no DETALHE (JSON), não numa coluna: o filtro é em Python.
    # ``importacao.concluida`` se acumula (uma por arquivo, das duas plataformas),
    # então a leitura é em LOTES e para no primeiro acerto — nunca materializa o
    # log inteiro da escola só para responder "já chegou alguma vez?".
    for acao, detalhes in db.execute(
        select(LogAuditoria.acao, LogAuditoria.detalhes).where(
            LogAuditoria.escola_id == escola_id,
            LogAuditoria.acao.in_(ACOES_CREDENCIAL | {ACAO_IMPORTACAO}))
        .execution_options(yield_per=200)
    ):
        detalhe = detalhes or {}
        if detalhe.get("plataforma") != "elefante":
            continue
        # A importação MANUAL é o registro do próprio ajuste da escola: contá-la
        # trancaria a porta no primeiro uso legítimo.
        if acao == ACAO_IMPORTACAO and detalhe.get("tipo") == "manual":
            continue
        return f"auditoria:{acao}"
    marcas = (
        ("auditoria:catalogo", select(LogAuditoria.id).where(
            LogAuditoria.escola_id == escola_id,
            LogAuditoria.acao.in_(ACOES_CATALOGO_ELEFANTE))),
        ("importacao", select(Importacao.id).where(
            Importacao.escola_id == escola_id,
            Importacao.plataforma == "elefante",
            Importacao.tipo != "manual")),
        ("evento", select(EventoAluno.id).where(
            EventoAluno.escola_id == escola_id,
            EventoAluno.plataforma == "elefante")),
        ("leitura", select(Leitura.id).where(Leitura.escola_id == escola_id)),
        ("sincronizacao", select(SincronizacaoExecucao.id).where(
            SincronizacaoExecucao.escola_id == escola_id,
            SincronizacaoExecucao.plataforma == "elefante")),
    )
    for nome, consulta in marcas:
        if db.execute(consulta.limit(1)).first() is not None:
            return nome
    return None


def _exigir_governanca_ajuste_manual(db: Session, escola_id: int, usuario: Usuario) -> None:
    """Quem ajusta o snapshot/faixas do Elefante à mão.

    Bloqueia quando a integração está ATIVA **ou** quando existe evidência
    HISTÓRICA de dado do Elefante vindo da plataforma — a escola desliga a
    integração, mas não apaga a história (ver
    ``evidencia_elefante_da_plataforma``). Numa escola que nunca recebeu o
    Elefante da plataforma, admin e coordenador mantêm o ajuste manual: ali ele é
    a única fonte do dado. O Admin Global faz manutenção em qualquer caso."""
    if usuario.is_global:
        return
    if integracao_elefante_ativa(db, escola_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, MSG_AJUSTE_COM_INTEGRACAO)
    if evidencia_elefante_da_plataforma(db, escola_id) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, MSG_AJUSTE_COM_DADO_RECEBIDO)


def _contagens_validadas(db: Session, escola_id: int, contagens: dict[str, int]) -> dict[str, int]:
    """Chaves de ``livros_por_nivel``: SÓ o vocabulário oficial (AA…Z, Z+, A+,
    normalizado em maiúsculas) ou os códigos de faixa cadastrados na escola
    (``pre_leitor``, ``nivel_2``…). Qualquer outra chave → 400, nada é gravado.
    As contagens já chegam validadas pelo schema (inteiros de 0 a 10.000)."""
    faixas = {
        n.codigo for n in db.execute(
            select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
        ).scalars() if n.codigo
    }
    faixas_sem_caixa = {c.casefold(): c for c in faixas}
    saida: dict[str, int] = {}
    desconhecidas: list[str] = []
    for chave, quantidade in contagens.items():
        bruto = str(chave or "").strip()
        if bruto.upper() in NIVEIS_OFICIAIS:
            canonica = bruto.upper()
        elif bruto in faixas:
            canonica = bruto
        elif bruto.casefold() in faixas_sem_caixa:
            canonica = faixas_sem_caixa[bruto.casefold()]
        else:
            desconhecidas.append(bruto or "(vazia)")
            continue
        saida[canonica] = saida.get(canonica, 0) + int(quantidade)
    if desconhecidas:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Faixa desconhecida: " + ", ".join(f"“{c}”" for c in desconhecidas)
            + ". Use os níveis oficiais do Elefante (AA…Z, Z+, A+) ou as faixas "
              "cadastradas para a escola.")
    return saida


def _snapshot_anterior(db: Session, aluno_id: int) -> SnapshotElefante | None:
    return db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.data_referencia.desc(),
                  SnapshotElefante.id.desc()).limit(1)
    ).scalar_one_or_none()


def _estado_elefante(snap: SnapshotElefante | None) -> dict:
    """Retrato do snapshot para o "de" da auditoria (zeros quando não havia)."""
    return {"livros_unicos": snap.livros_unicos if snap else 0,
            "tempo_leitura_min": snap.tempo_leitura_min if snap else 0,
            "questoes_tentativas": snap.questoes_tentativas if snap else 0,
            "questoes_acertos": snap.questoes_acertos if snap else 0,
            "livros_por_nivel": snap.livros_por_nivel if snap else {}}


@router.get("/elefante", response_model=list[ElefanteAlunoOut],
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def modulo_elefante(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    # Professor restrito vê só as turmas dele (None = escola inteira p/ admin/coord).
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    return [
        ElefanteAlunoOut(
            aluno_id=aluno.id, nome=aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            livros_unicos=snap.livros_unicos if snap else 0,
            tempo_leitura_min=snap.tempo_leitura_min if snap else 0,
            questoes_tentativas=snap.questoes_tentativas if snap else 0,
            questoes_acertos=snap.questoes_acertos if snap else 0,
            livros_por_nivel=snap.livros_por_nivel if snap else {},
            data_referencia=snap.data_referencia if snap else None,
        )
        for aluno, turma, snap in _linhas_modulo(
            db, escola_id, SnapshotElefante, turma_ids=permitidas)
    ]


@router.put("/elefante/{aluno_id}", response_model=ElefanteAlunoOut,
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def editar_elefante(
    aluno_id: int,
    dados: ElefanteEdicao,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Snapshot MANUAL do Elefante (novo ponto no histórico, nunca sobrescreve).

    Validações: chaves só do vocabulário oficial ou faixas da escola (400);
    contagens de 0 a 10.000 (422); ``livros_unicos`` informado não pode ser menor
    que a soma das contagens (400); motivo obrigatório (422). Com a integração do
    Elefante ativa, só o Admin Global ajusta (403)."""
    if dados.questoes_acertos > dados.questoes_tentativas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Acertos não podem exceder as tentativas.")
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    _exigir_governanca_ajuste_manual(db, escola_id, usuario)
    por_nivel = _contagens_validadas(db, escola_id, dados.livros_por_nivel)
    soma = sum(por_nivel.values())
    if dados.livros_unicos is not None and dados.livros_unicos < soma:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Os livros únicos informados ({dados.livros_unicos}) são menos que a "
            f"soma dos livros por nível ({soma}).")
    livros = dados.livros_unicos if dados.livros_unicos is not None else soma
    anterior = _snapshot_anterior(db, aluno_id)

    importacao = _importacao_manual(db, escola_id, usuario.id, "elefante")
    snap = SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        livros_unicos=livros, tempo_leitura_min=dados.tempo_leitura_min,
        questoes_tentativas=dados.questoes_tentativas,
        questoes_acertos=dados.questoes_acertos,
        livros_por_nivel=por_nivel,
    )
    db.add(snap)
    registrar(db, "elefante.editado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={
                  "motivo": dados.motivo,
                  "de": _estado_elefante(anterior),
                  "para": {**dados.model_dump(exclude={"motivo", "livros_por_nivel",
                                                       "livros_unicos"}),
                           "livros_unicos": livros, "livros_por_nivel": por_nivel},
              })
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    db.refresh(snap)
    return ElefanteAlunoOut(
        aluno_id=aluno.id, nome=aluno.nome, turma=None, ano_escolar=None,
        livros_unicos=snap.livros_unicos, tempo_leitura_min=snap.tempo_leitura_min,
        questoes_tentativas=snap.questoes_tentativas,
        questoes_acertos=snap.questoes_acertos,
        livros_por_nivel=snap.livros_por_nivel,
        data_referencia=snap.data_referencia,
    )


@router.put("/elefante/{aluno_id}/niveis", response_model=ElefanteAlunoOut,
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def informar_niveis_leitura(
    aluno_id: int,
    dados: NiveisLeituraEdicao,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Informa os livros concluídos por FAIXA de dificuldade (§38). O total e
    os pontos de dificuldade são recalculados; tempo e questões do último
    snapshot são preservados. Aceita só códigos de faixa configurados ou níveis
    do vocabulário oficial; motivo obrigatório; com a integração do Elefante
    ativa, só o Admin Global ajusta."""
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    _exigir_governanca_ajuste_manual(db, escola_id, usuario)
    por_nivel = _contagens_validadas(db, escola_id, dados.faixas)
    anterior = _snapshot_anterior(db, aluno_id)

    importacao = _importacao_manual(db, escola_id, usuario.id, "elefante")
    snap = SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        livros_unicos=sum(por_nivel.values()),
        tempo_leitura_min=anterior.tempo_leitura_min if anterior else 0,
        questoes_tentativas=anterior.questoes_tentativas if anterior else 0,
        questoes_acertos=anterior.questoes_acertos if anterior else 0,
        livros_por_nivel=por_nivel,
    )
    db.add(snap)
    registrar(db, "elefante.niveis_informados", escola_id=escola_id,
              usuario_id=usuario.id, entidade="aluno", entidade_id=aluno_id,
              detalhes={"motivo": dados.motivo, "faixas": por_nivel,
                        "de": {"livros_unicos": anterior.livros_unicos if anterior else 0,
                               "livros_por_nivel": anterior.livros_por_nivel if anterior else {}}})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    db.refresh(snap)
    return ElefanteAlunoOut(
        aluno_id=aluno.id, nome=aluno.nome, turma=None, ano_escolar=None,
        livros_unicos=snap.livros_unicos, tempo_leitura_min=snap.tempo_leitura_min,
        questoes_tentativas=snap.questoes_tentativas,
        questoes_acertos=snap.questoes_acertos,
        livros_por_nivel=snap.livros_por_nivel,
        data_referencia=snap.data_referencia,
    )


# --- Catálogo de Livros (PRD §57) ----------------------------------------------

def _admin_global_do_catalogo(usuario: Usuario = Depends(get_usuario_atual)) -> Usuario:
    """Escrita no catálogo: SÓ o Admin Global (``exigir_admin_global``), com a
    mensagem de governança do catálogo oficial para todos os demais perfis."""
    try:
        return exigir_admin_global(usuario)
    except HTTPException as erro:
        raise HTTPException(erro.status_code, MSG_CATALOGO_SOMENTE_LEITURA) from erro


def _nivel_do_vocabulario(codigo: str | None) -> str:
    """Nível normalizado; fora do vocabulário oficial → 400."""
    nivel = str(codigo or "").strip().upper()
    if nivel not in NIVEIS_OFICIAIS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Nível “{nivel or codigo}” não existe no Elefante Letrado. Use um nível "
            "oficial: AA, BB, CC, DD, A…Z, Z+ ou A+.")
    return nivel


def _aceita_elefante_id(metodo) -> bool:
    """A régua aceita o id oficial do livro (contrato com a frente da régua v2)?
    Enquanto a assinatura não tiver o parâmetro, o valor sai pelo título."""
    try:
        return "elefante_id" in inspect.signature(metodo).parameters
    except (TypeError, ValueError):
        return False


def _pontos_livro(regra, livro: Livro) -> float:
    """Valor BASE do livro no catálogo (fonte única de dificuldade). Sem série
    (o catálogo não é de um aluno), o valor é o do 5º ano (fator 1,0); para um
    aluno do 1º–4º ano a leitura vale mais (ver histórico/ranking). O livro é
    identificado pelo id oficial do Elefante quando vinculado."""
    extra = ({"elefante_id": livro.elefante_id}
             if _aceita_elefante_id(regra.valor_livro) else {})
    return round(regra.valor_livro(livro.nivel_codigo, livro.titulo, None, **extra), 2)


def _dados_oficiais(livro: Livro) -> tuple[str | None, int | None, bool]:
    """(nível oficial, wordCount, divergente) do livro.

    Nível oficial = o do CATÁLOGO, pelo ``elefante_id`` — e só ele. Livro fora do
    catálogo não tem nível oficial (``None``), ainda que a fonte já tenha
    informado um: ``nivel_fonte``, nesse caso, é o nível que veio no RELATÓRIO, e
    o relatório é da escola. Chamá-lo de "oficial" convidaria a escola a plantar
    o número que ela quisesse na coluna que o Admin Global usa para decidir uma
    correção — a mesma porta que a reconciliação já fecha no nível efetivo
    (``importacoes._AcervoEscola._conciliar``). O campo ``nivel_fonte`` continua
    na resposta, com o nome honesto.

    Divergente = o nível efetivo difere do oficial ou do último informado pela
    fonte (o segundo termo é o que sinaliza o livro fora do catálogo)."""
    meta = (dificuldade_livro.catalogo().por_id.get(livro.elefante_id)
            if livro.elefante_id is not None else None)
    nivel_oficial = meta.nivel if meta is not None else None
    word_count = livro.word_count if livro.word_count is not None else (
        meta.word_count if meta is not None else None)
    divergente = bool(
        (nivel_oficial and livro.nivel_codigo != nivel_oficial)
        or (livro.nivel_fonte and livro.nivel_codigo != livro.nivel_fonte))
    return nivel_oficial, word_count, divergente


# O QUE UMA CORREÇÃO DE NÍVEL/TÍTULO MUDA — e a partir de quando.
#
# Cada ``Leitura`` guarda o NÍVEL CONGELADO do livro no instante em que foi
# registrada (``Leitura.nivel_codigo`` + ``catalogo_versao``). Quem pontua lê
# ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)``: corrigir o catálogo
# vale para as PRÓXIMAS leituras e não reescreve o passado — nem nas telas por
# período, nem na nota gravada. Não existe, portanto, "recálculo pendente".
AVISO_PROXIMAS_LEITURAS = (
    "Correção registrada — ela vale para as PRÓXIMAS leituras. As leituras já "
    "registradas guardam o nível que valia quando o aluno leu o livro, então o "
    "histórico, as notas gravadas e os rankings do passado continuam como estão."
)

# Ressalva HONESTA: leitura anterior ao congelamento (``nivel_codigo`` nulo) cai
# no nível ATUAL do livro. Essas — e só essas — mudam de valor no próximo cálculo.
AVISO_LEITURAS_SEM_CONGELAMENTO = (
    " {n} leitura(s) deste livro são anteriores ao congelamento do nível e "
    "seguem o nível atual do livro: só elas mudam de valor no próximo cálculo "
    "da escola."
)

AVISO_HISTORICO_APLICADO = (
    "Correção aplicada também ao HISTÓRICO, por escolha explícita do Admin "
    "Global: {n} leitura(s) deste livro passaram a valer o nível {nivel}. A "
    "escola foi recalculada e o antes/depois ficou no log de auditoria."
)

# Pedido retroativo que não encontrou o que reescrever (livro sem leitura, ou
# todas já no nível vigente): dizer "a escola foi recalculada" seria falso — o
# recálculo só roda quando alguma leitura muda.
AVISO_HISTORICO_SEM_EFEITO = (
    "Aplicar ao histórico não mudou nada: nenhuma leitura deste livro estava em "
    "outro nível. O pedido ficou registrado no log de auditoria."
)


def _livro_out(livro: Livro, regra, usuario: Usuario, leituras: int = 0, *,
               vale_para_proximas_leituras: bool = False,
               historico_preservado: bool = True,
               leituras_atualizadas: int = 0,
               leituras_sem_nivel_congelado: int = 0,
               aviso_correcao: str | None = None) -> LivroOut:
    saida = LivroOut.model_validate(livro)
    nivel_oficial, word_count, divergente = _dados_oficiais(livro)
    saida.pontos = _pontos_livro(regra, livro)
    saida.leituras = leituras
    saida.origem_nivel = livro.origem_nivel or "legado"
    saida.nivel_oficial = nivel_oficial
    saida.word_count = word_count
    # No catálogo = o id vinculado existe no catálogo oficial (um id sem entrada
    # no arquivo do catálogo não conta).
    saida.no_catalogo = (livro.elefante_id is not None
                         and livro.elefante_id in dificuldade_livro.catalogo().por_id)
    saida.divergente = divergente
    saida.editavel = bool(usuario.is_global)
    saida.vale_para_proximas_leituras = vale_para_proximas_leituras
    saida.historico_preservado = historico_preservado
    saida.leituras_atualizadas = leituras_atualizadas
    saida.leituras_sem_nivel_congelado = leituras_sem_nivel_congelado
    saida.aviso_correcao = aviso_correcao
    return saida


def _conflito_de_titulo(db: Session, escola_id: int, titulo: str, nivel: str,
                        ignorar_id: int | None = None) -> Livro | None:
    """Outro livro da escola com o mesmo título (normalizado: sem acento/caixa).

    Exceção: HOMÔNIMOS OFICIAIS — o mesmo título em níveis diferentes no catálogo
    do Elefante (ex.: "Cadê?" B e BB) são livros distintos e não conflitam entre
    si enquanto estiverem em níveis diferentes."""
    chave = dificuldade_livro.normalizar_titulo(titulo)
    homonimo_oficial = len(dificuldade_livro.catalogo().por_titulo.get(chave) or []) > 1
    for outro in db.execute(select(Livro).where(Livro.escola_id == escola_id)).scalars():
        if outro.id == ignorar_id or dificuldade_livro.normalizar_titulo(outro.titulo) != chave:
            continue
        if homonimo_oficial and outro.nivel_codigo != nivel:
            continue
        return outro
    return None


@router.get("/livros", response_model=dict,
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def listar_livros(
    escola_id: int = Depends(escola_autorizada),
    busca: str | None = Query(default=None),
    nivel: str | None = Query(default=None),
    categoria: str | None = Query(default=None),
    divergentes: bool = Query(default=False,
                              description="só livros com nível efetivo ≠ oficial"),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    consulta = select(Livro).where(Livro.escola_id == escola_id)
    if busca:
        consulta = consulta.where(
            Livro.titulo.ilike(f"%{busca}%") | Livro.autor.ilike(f"%{busca}%")
        )
    if nivel:
        consulta = consulta.where(Livro.nivel_codigo == nivel.upper())
    if categoria:
        consulta = consulta.where(Livro.categoria == categoria)

    ordenada = consulta.order_by(Livro.titulo, Livro.id)
    if divergentes:
        # A divergência depende do catálogo oficial (arquivo), não só do banco:
        # filtra em memória — o acervo de uma escola cabe folgado (~centenas).
        todos = [l for l in db.execute(ordenada).scalars().all() if _dados_oficiais(l)[2]]
        total = len(todos)
        livros = todos[(pagina - 1) * por_pagina:pagina * por_pagina]
    else:
        total = db.execute(
            select(func.count()).select_from(consulta.subquery())
        ).scalar_one()
        livros = db.execute(
            ordenada.offset((pagina - 1) * por_pagina).limit(por_pagina)
        ).scalars().all()

    contagem = dict(db.execute(
        select(Leitura.livro_id, func.count(Leitura.id))
        .where(Leitura.escola_id == escola_id)
        .group_by(Leitura.livro_id)
    ).all())
    regra = dificuldade_livro.regra_da_escola(db, escola_id)

    itens = [_livro_out(livro, regra, usuario, contagem.get(livro.id, 0)) for livro in livros]
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}


@router.post("/livros", response_model=LivroOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def criar_livro(
    dados: LivroCreate,
    usuario: Usuario = Depends(_admin_global_do_catalogo),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
):
    """Cadastra um livro no acervo (só Admin Global). O livro é resolvido no
    catálogo oficial por título+nível: casando, grava o id oficial, o wordCount e
    o nível da fonte; a origem do nível é ``fonte`` se o nível informado bate com
    o oficial, senão ``admin_global`` (correção deliberada)."""
    titulo = dados.titulo.strip()
    if not titulo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "O título do livro não pode ficar vazio.")
    nivel = _nivel_do_vocabulario(dados.nivel_codigo)
    if _conflito_de_titulo(db, escola_id, titulo, nivel):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Já existe um livro com este título no catálogo.")
    meta = dificuldade_livro.catalogo().buscar(titulo, nivel)
    if meta is not None and db.execute(
            select(Livro.id).where(Livro.escola_id == escola_id,
                                   Livro.elefante_id == meta.id).limit(1)).first():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Este livro do catálogo oficial já está no acervo da escola.")
    livro = Livro(
        escola_id=escola_id, titulo=titulo, autor=dados.autor, nivel_codigo=nivel,
        categoria=dados.categoria, paginas=dados.paginas,
        elefante_id=meta.id if meta is not None else None,
        word_count=meta.word_count if meta is not None else None,
        nivel_fonte=meta.nivel if meta is not None else None,
        origem_nivel="fonte" if meta is not None and meta.nivel == nivel else "admin_global",
        atualizado_em=agora(),
    )
    db.add(livro)
    db.flush()
    registrar(db, "livro.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="livro", entidade_id=livro.id,
              detalhes={"titulo": livro.titulo, "nivel": nivel,
                        "elefante_id": livro.elefante_id, "nivel_fonte": livro.nivel_fonte,
                        "origem_nivel": livro.origem_nivel, "motivo": dados.motivo})
    db.commit()
    db.refresh(livro)
    return _livro_out(livro, dificuldade_livro.regra_da_escola(db, escola_id), usuario)


def _aplicar_nivel_ao_historico(db: Session, escola_id: int, livro: Livro,
                                usuario: Usuario, motivo: str) -> int:
    """Reescreve o NÍVEL CONGELADO das leituras deste livro para o nível vigente.

    Ação retroativa EXPLÍCITA do Admin Global (``aplicar_ao_historico``): audita
    o de/para com a contagem por nível anterior e recalcula a escola. Sem ela,
    corrigir o catálogo não toca em nenhuma leitura já registrada."""
    novo = livro.nivel_codigo
    versao = dificuldade_livro.versao_catalogo().get("versao")
    de = {
        (nivel or "sem_nivel_congelado"): quantidade
        for nivel, quantidade in db.execute(
            select(Leitura.nivel_codigo, func.count(Leitura.id))
            .where(Leitura.livro_id == livro.id, Leitura.escola_id == escola_id)
            .group_by(Leitura.nivel_codigo)).all()
        if nivel != novo
    }
    atualizadas = db.execute(
        update(Leitura)
        .where(Leitura.livro_id == livro.id, Leitura.escola_id == escola_id,
               (Leitura.nivel_codigo.is_(None)) | (Leitura.nivel_codigo != novo))
        .values(nivel_codigo=novo, catalogo_versao=versao)
        .execution_options(synchronize_session=False)
    ).rowcount
    registrar(db, "livro.historico_renivelado", escola_id=escola_id,
              usuario_id=usuario.id, entidade="livro", entidade_id=livro.id,
              detalhes={"de": de, "para": novo, "leituras_atualizadas": atualizadas,
                        "catalogo_versao": versao, "motivo": motivo or None,
                        "elefante_id": livro.elefante_id})
    db.commit()
    if atualizadas:
        scoring.recalcular_escola(db, escola_id)
    return int(atualizadas or 0)


@router.patch("/livros/{livro_id}", response_model=LivroOut,
              dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def atualizar_livro(
    livro_id: int,
    dados: LivroUpdate,
    usuario: Usuario = Depends(_admin_global_do_catalogo),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
):
    """Correção de livro pelo Admin Global.

    Nível só do vocabulário oficial (400); título/nível nulos (422); título
    duplicado (409); ``motivo`` obrigatório quando o nível muda (400). Mudar o
    nível marca ``origem_nivel='admin_global'`` — a sincronização passa a
    PRESERVAR esse nível e só audita a divergência com a fonte.

    A CORREÇÃO VALE PARA AS PRÓXIMAS LEITURAS. Cada ``Leitura`` guarda o nível
    congelado do momento em que foi registrada, e quem pontua lê
    ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)``: o histórico, as notas
    gravadas e os rankings do passado NÃO mudam — não há "recálculo pendente".
    A única ressalva, devolvida em ``leituras_sem_nivel_congelado``, são as
    leituras anteriores ao congelamento (nível nulo), que caem no nível atual do
    livro.

    ``aplicar_ao_historico=true`` (opcional, só do Admin Global, exige
    ``motivo``) é a ação EXPLÍCITA que reescreve o nível congelado das leituras
    deste livro para o nível vigente, audita de/para com a contagem
    (``livro.historico_renivelado``) e recalcula a escola. Sem ele, NADA
    retroativo acontece."""
    livro = db.get(Livro, livro_id)
    if livro is None or livro.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Livro não encontrado.")
    alteracoes = dados.model_dump(exclude_unset=True)
    motivo = (alteracoes.pop("motivo", None) or "").strip()
    aplicar_ao_historico = bool(alteracoes.pop("aplicar_ao_historico", False))
    if "titulo" in alteracoes:
        alteracoes["titulo"] = alteracoes["titulo"].strip()
    if "nivel_codigo" in alteracoes:
        alteracoes["nivel_codigo"] = _nivel_do_vocabulario(alteracoes["nivel_codigo"])
    mudancas = {campo: valor for campo, valor in alteracoes.items()
                if getattr(livro, campo) != valor}
    nivel_muda = "nivel_codigo" in mudancas
    titulo_muda = "titulo" in mudancas
    if (nivel_muda or aplicar_ao_historico) and len(motivo) < 5:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Informe o motivo da correção de nível (pelo menos 5 caracteres) — ele "
            "fica registrado no log de auditoria.")
    if (nivel_muda or titulo_muda) and _conflito_de_titulo(
            db, escola_id, mudancas.get("titulo", livro.titulo),
            mudancas.get("nivel_codigo", livro.nivel_codigo), ignorar_id=livro.id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Já existe um livro com este título no catálogo.")

    if mudancas:
        de = {campo: getattr(livro, campo) for campo in mudancas}
        for campo, valor in mudancas.items():
            setattr(livro, campo, valor)
        if nivel_muda:
            livro.origem_nivel = "admin_global"
        livro.atualizado_em = agora()
        registrar(db, "livro.atualizado", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="livro", entidade_id=livro.id,
                  detalhes={"de": de, "para": mudancas, "motivo": motivo or None,
                            "elefante_id": livro.elefante_id,
                            # A correção vale daqui para a frente; o histórico só
                            # muda por ação explícita (``aplicar_ao_historico``).
                            "vale_para_proximas_leituras": nivel_muda or titulo_muda,
                            "aplicar_ao_historico": aplicar_ao_historico})
        db.commit()
        db.refresh(livro)

    atualizadas = (_aplicar_nivel_ao_historico(db, escola_id, livro, usuario, motivo)
                   if aplicar_ao_historico else 0)

    contagem = db.execute(
        select(func.count(Leitura.id)).where(Leitura.livro_id == livro.id)).scalar_one()
    # Leituras ANTERIORES ao congelamento: são as únicas que ainda seguem o nível
    # atual do livro — a ressalva honesta da mensagem devolvida.
    sem_congelamento = db.execute(
        select(func.count(Leitura.id)).where(Leitura.livro_id == livro.id,
                                             Leitura.nivel_codigo.is_(None))).scalar_one()
    vale_para_proximas = nivel_muda or titulo_muda
    aviso = None
    if vale_para_proximas:
        aviso = AVISO_PROXIMAS_LEITURAS
        if sem_congelamento and not aplicar_ao_historico:
            aviso += AVISO_LEITURAS_SEM_CONGELAMENTO.format(n=sem_congelamento)
    if aplicar_ao_historico:
        aplicado = (AVISO_HISTORICO_APLICADO.format(n=atualizadas,
                                                    nivel=livro.nivel_codigo)
                    if atualizadas else AVISO_HISTORICO_SEM_EFEITO)
        aviso = f"{aviso} {aplicado}" if aviso else aplicado
    return _livro_out(livro, dificuldade_livro.regra_da_escola(db, escola_id), usuario,
                      contagem,
                      vale_para_proximas_leituras=vale_para_proximas,
                      # "Preservado" é sobre o FATO, não sobre o pedido: pedir o
                      # retroativo num livro sem leitura não reescreveu nada.
                      historico_preservado=atualizadas == 0,
                      leituras_atualizadas=atualizadas,
                      leituras_sem_nivel_congelado=sem_congelamento,
                      aviso_correcao=aviso)


@router.delete("/livros/{livro_id}",
               dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def excluir_livro(
    livro_id: int,
    usuario: Usuario = Depends(_admin_global_do_catalogo),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
):
    livro = db.get(Livro, livro_id)
    if livro is None or livro.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Livro não encontrado.")
    tem_leituras = db.execute(
        select(Leitura.id).where(Leitura.livro_id == livro_id).limit(1)
    ).scalar_one_or_none()
    if tem_leituras:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Este livro tem leituras registradas e não pode ser excluído — "
            "isso apagaria histórico de alunos.",
        )
    registrar(db, "livro.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="livro", entidade_id=livro.id,
              detalhes={"titulo": livro.titulo, "nivel": livro.nivel_codigo,
                        "elefante_id": livro.elefante_id})
    db.delete(livro)
    db.commit()
    return {"mensagem": f"Livro “{livro.titulo}” excluído do catálogo."}
