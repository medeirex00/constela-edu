"""Exportação de relatórios e certificados (PRD §86–§103).

Cada exportação também deixa uma cópia em /exports e um registro no log.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.core.tempo import hoje_br
from app.models import Aluno, Escola, Matricula, Nota, Turma, Usuario
from app.routers.rankings import _ranking
from app.services import dimensoes as svc_dimensoes
from app.services import elegibilidade, frescor_ranking
from app.services import modulos as svc_modulos
from app.services import permissoes
from app.services import relatorios as svc
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Relatórios"])

logger = logging.getLogger("constela.relatorios")


def _expurgar_exports_antigos() -> None:
    """Remove cópias de relatórios além da retenção (LGPD/minimização — contêm
    nomes de alunos). Chamado a cada nova exportação — barato e evita acúmulo
    indefinido de PII em disco. EXPORTS_RETENCAO_DIAS=0 desliga."""
    dias = settings.EXPORTS_RETENCAO_DIAS
    if dias <= 0 or not settings.EXPORTS_DIR.exists():
        return
    limite = time.time() - dias * 86_400
    for arquivo in settings.EXPORTS_DIR.iterdir():
        # Preserva dotfiles de infraestrutura (ex.: .gitkeep) — só expurga as
        # cópias de relatórios de fato.
        if arquivo.name.startswith("."):
            continue
        try:
            if arquivo.is_file() and arquivo.stat().st_mtime < limite:
                arquivo.unlink(missing_ok=True)
        except OSError:
            pass


def _arquivar_copia(nome_arquivo: str, conteudo: bytes) -> None:
    """Cópia local em /exports — MELHOR ESFORÇO: se o disco não for gravável,
    o download segue normal (o arquivo vai na resposta); só a cópia é pulada.
    Expurga cópias antigas na mesma passada (retenção — não acumula PII)."""
    try:
        settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        _expurgar_exports_antigos()
        (settings.EXPORTS_DIR / nome_arquivo).write_bytes(conteudo)
    except OSError:
        logger.warning("Sem acesso de escrita em %s — relatório enviado, cópia "
                       "local não arquivada.", settings.EXPORTS_DIR)

FORMATOS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


@router.get("/relatorios/{tipo}")
def exportar_relatorio(
    tipo: str,
    formato: str = Query(pattern="^(csv|xlsx|pdf)$"),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    if tipo not in svc.FONTES:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Relatórios disponíveis: {', '.join(sorted(svc.FONTES))}.")
    escola = db.get(Escola, escola_id)
    modulos = svc_modulos.modulos_da_escola(db, escola)
    if tipo == "livros":
        # Catálogo de livros é dado do módulo Leitura: fora do plano, 403.
        svc_modulos.exigir(modulos, "leitura")
    titulo, fonte = svc.FONTES[tipo]

    # Professor: só o ranking e a lista de alunos, e apenas das turmas dele no
    # ano letivo ativo. O recorte é feito NA CONSULTA, pelo ID da turma da
    # matrícula (`turma_ids`) — nunca pelo nome da turma, que se repete entre
    # anos (uma matrícula do ano ativo pode apontar para a turma homônima de
    # outro ano). Fonte sem esse recorte não aceita `turma_ids` e falha fechada.
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None and tipo not in ("ranking", "alunos"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Seu perfil exporta apenas o ranking e a lista "
                            "de alunos das suas turmas.")
    if permitidas is None:
        cabecalho, linhas = fonte(db, escola_id)
    else:
        cabecalho, linhas = fonte(db, escola_id, turma_ids=permitidas)
    if tipo == "ranking":
        # Nota de plataforma de módulo não contratado não sai no arquivo.
        cabecalho, linhas = svc.sem_notas_fora_do_plano(cabecalho, linhas, modulos)

    if permitidas is not None:
        if tipo == "ranking":
            # Posição RELATIVA à turma do professor (1..N), como na tela — a
            # posição global (109, 111…) da escola inteira não cabe aqui.
            try:
                idx_pos = next(i for i, c in enumerate(cabecalho)
                               if c.strip().lower().startswith("posi"))
                linhas = [
                    [pos if j == idx_pos else v for j, v in enumerate(linha)]
                    for pos, linha in enumerate(linhas, start=1)
                ]
            except StopIteration:
                pass
    cor = svc.cor_primaria(db, escola_id)

    if formato == "csv":
        conteudo = svc.gerar_csv(cabecalho, linhas)
    elif formato == "xlsx":
        conteudo = svc.gerar_xlsx(titulo, escola.nome, cor, cabecalho, linhas)
    elif tipo == "ranking":
        # PDF do Ranking Geral = o CARTAZ (pôster). Gestão: escola inteira.
        # Professor: as linhas já vêm filtradas + renumeradas (1..N) nas turmas
        # dele, e as estatísticas do cartaz também recortadas para elas.
        # DE QUANDO é o dado (fa5947a): o mesmo selo de frescor do ranking que o
        # usuário vê — a escola inteira para a gestão (igual a /ranking/cartaz),
        # só as turmas dele para o professor (igual a /ranking/frescor). Este é
        # o ÚNICO caminho do cartaz para o professor (/ranking/cartaz dá 403).
        conteudo = svc.gerar_cartaz_ranking(
            escola.nome, cor, escola.ano_letivo_ativo, cabecalho, linhas,
            svc.estatisticas_cartaz(db, escola_id, turma_ids=permitidas),
            logos=svc.logos_da_escola(db, escola_id),
            dados_em=svc.legenda_data_dos_dados(
                frescor_ranking.frescor_da_escola(db, escola, hoje_br(),
                                                  turma_ids=permitidas),
                ["leitura", "matematica"]))
    elif tipo == "alunos":
        conteudo = svc.gerar_lista_alunos_pdf(
            escola.nome, cor, escola.ano_letivo_ativo, cabecalho, linhas,
            logos=svc.logos_da_escola(db, escola_id))
    elif tipo == "livros":
        conteudo = svc.gerar_catalogo_livros_pdf(
            escola.nome, cor, escola.ano_letivo_ativo, cabecalho, linhas,
            logos=svc.logos_da_escola(db, escola_id))
    else:
        conteudo = svc.gerar_pdf(titulo, escola.nome, cor, cabecalho, linhas)

    media_type, extensao = FORMATOS[formato]
    momento = datetime.now(timezone.utc)
    nome_arquivo = f"{tipo}_{momento:%Y%m%d_%H%M%S}.{extensao}"

    _arquivar_copia(nome_arquivo, conteudo)

    registrar(db, "relatorio.exportado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tipo": tipo, "formato": formato, "linhas": len(linhas)})
    db.commit()

    return Response(
        content=conteudo,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@router.get("/ranking/cartaz")
def cartaz_ranking(
    dimensao: str | None = Query(
        default=None, pattern="^(leitura|matematica)$",
        description="leitura | matematica. Ausente = cartaz do Ranking Geral."),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Cartaz (pôster) do Ranking Geral em PDF — TODOS os alunos, paginado.
    Documento de vitrine (gestão apenas): moldura Constela + logos da cidade,
    medalhas para o pódio e cartões de estatística.

    Com ``?dimensao=leitura`` ou ``?dimensao=matematica`` é o cartaz DA MATÉRIA:
    as linhas vêm do ranking oficial POR DIMENSÃO (`rankings._ranking` com
    ``dimensao`` — só os alunos AFERIDOS naquela matéria, na ordem da posição
    carimbada dela, com a mesma elegibilidade), sempre da ESCOLA INTEIRA, com
    uma só coluna de nota e o nome da matéria no título. Os cartões de
    estatística também são DA MATÉRIA e dos MESMOS alunos listados (Leitura:
    livros e tempo de leitura; Matemática: atividades e estrelas — ver
    `relatorios.estatisticas_cartaz_materia`). Exige o módulo da matéria
    contratado (403); dimensão fora da lista = 422."""
    permissoes.negar_restrito(db, escola_id, usuario)
    escola = db.get(Escola, escola_id)
    if dimensao:
        svc_modulos.exigir(svc_modulos.modulos_da_escola(db, escola), dimensao)
        cabecalho = svc.cabecalho_cartaz_materia(dimensao)
        itens = _ranking(db, escola_id, escola.ano_letivo_ativo, dimensao=dimensao)
        linhas = [
            [item.posicao, item.nome, item.turma, item.ano_escolar, item.nota]
            for item in itens
        ]
        # Cartões da matéria: os totais saem dos alunos DESTA lista, não da
        # escola inteira (senão "livros lidos" contaria quem não está no cartaz).
        estatisticas = svc.estatisticas_cartaz_materia(
            db, escola_id, dimensao, [item.aluno_id for item in itens])
    else:
        cabecalho, linhas = svc.linhas_ranking(db, escola_id)
        # Nota de plataforma de módulo não contratado não sai no cartaz (a mesma
        # regra do relatório de ranking).
        cabecalho, linhas = svc.sem_notas_fora_do_plano(
            cabecalho, linhas, svc_modulos.modulos_da_escola(db, escola))
        estatisticas = svc.estatisticas_cartaz(db, escola_id)
    # DE QUANDO é o dado do cartaz: a mesma data do selo de frescor do ranking
    # (a escola inteira — o cartaz é da escola inteira), impressa ao lado da
    # data de emissão. Sem isso, um pôster com a coleta parada há semanas
    # parecia atual.
    dados_em = svc.legenda_data_dos_dados(
        frescor_ranking.frescor_da_escola(db, escola, hoje_br()),
        [dimensao] if dimensao else ["leitura", "matematica"])
    conteudo = svc.gerar_cartaz_ranking(
        escola_nome=escola.nome,
        cor=svc.cor_primaria(db, escola_id),
        ano_letivo=escola.ano_letivo_ativo,
        cabecalho=cabecalho,
        linhas=linhas,
        estatisticas=estatisticas,
        logos=svc.logos_da_escola(db, escola_id),
        materia=dimensao,
        dados_em=dados_em,
    )
    momento = datetime.now(timezone.utc)
    sufixo = f"_{dimensao}" if dimensao else ""
    nome_arquivo = f"ranking_cartaz{sufixo}_{momento:%Y%m%d_%H%M%S}.pdf"
    _arquivar_copia(nome_arquivo, conteudo)
    registrar(db, "relatorio.exportado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tipo": f"ranking_cartaz{sufixo}", "formato": "pdf",
                        "linhas": len(linhas)})
    db.commit()
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


_SITUACAO = {"transferido": "transferido (saiu da escola)",
             "fora_lista_piloto": "fora da Lista Piloto",
             "arquivado": "arquivado",
             "excluido": "excluído"}


@router.get("/certificados/{aluno_id}")
def certificado(
    aluno_id: int,
    modelo: str | None = Query(default=None, pattern="^(elefante|matific)$"),
    bimestre: int | None = Query(default=None, ge=1, le=4),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Certificado individual em PDF (PRD §99). Professor: só dos seus alunos.

    `modelo=elefante|matific` usa a ARTE oficial da plataforma (personagens),
    preenchida automaticamente (instituição, nome, bimestre e data). Sem `modelo`,
    emite o certificado geral (moldura azul-marinho, com turma e nota).

    `bimestre` (1–4) é o número impresso na arte da plataforma. Sem ele, o padrão
    continua sendo o bimestre do MÊS DE EMISSÃO — e é justamente por isso que o
    parâmetro existe: emitir no dia 30/09 imprimia "3", e no dia seguinte, 01/10,
    a MESMA criança com os MESMOS dados recebia "4", porque o único insumo era o
    relógio. Quando a entrega atravessa a virada do bimestre, quem emite escolhe
    qual período o documento afirma; o padrão não mudou, para não alterar nenhum
    certificado já combinado.

    A arte de uma plataforma exige o módulo dela no plano da rede (``matific`` →
    Matemática, ``elefante`` → Leitura); fora do plano, 403.

    O corpo vive em três funções (``exigir_modulo_do_modelo``,
    ``preparar_certificado`` e ``conteudo_certificado``) porque a emissão EM LOTE
    (``routers/certificados_lote.py``) roda exatamente as mesmas guardas, na mesma
    ordem, e gera exatamente o mesmo documento: uma cópia parecida envelheceria e
    viraria a porta de trás de alguma guarda."""
    escola = db.get(Escola, escola_id)
    exigir_modulo_do_modelo(db, escola, modelo)
    preparo = preparar_certificado(db, escola, usuario, aluno_id)
    conteudo = conteudo_certificado(db, preparo, modelo, bimestre)
    registrar_emissao(db, escola_id, usuario, aluno_id, modelo)
    db.commit()
    nome_arq = f"certificado_{modelo or 'geral'}_{aluno_id}.pdf"
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arq}"'},
    )


def exigir_modulo_do_modelo(db: Session, escola: Escola, modelo: str | None) -> None:
    """A arte de uma plataforma exige o módulo dela no plano da rede (403). É a
    PRIMEIRA guarda: vale para o pedido inteiro, antes de olhar qualquer aluno."""
    if modelo is not None:
        svc_modulos.exigir(svc_modulos.modulos_da_escola(db, escola),
                           svc_modulos.PLATAFORMA_MODULO[modelo])


@dataclass
class PreparoCertificado:
    """O aluno que passou pelas guardas de POPULAÇÃO, com o que a emissão usa."""
    escola: Escola
    aluno: Aluno
    matricula: tuple | None     # (Matricula, Turma) do ano letivo ativo, ou None

    @property
    def turma_nome(self) -> str | None:
        return self.matricula[1].nome if self.matricula is not None else None


def preparar_certificado(db: Session, escola: Escola, usuario: Usuario,
                         aluno_id: int) -> PreparoCertificado:
    """Guardas de POPULAÇÃO da emissão, na ordem da rota individual. LEVANTA o
    mesmo ``HTTPException`` (status e mensagem) que a rota sempre devolveu:
    404 (aluno de fora da escola, ou fora das turmas do professor), 409 (situação
    não ativa, turma que não participa das premiações, ficha fora da Lista
    Piloto). Valem para os três modelos; a guarda de MÉRITO, só do Geral, fica em
    :func:`exigir_merito`."""
    escola_id = escola.id
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    permissoes.exigir_aluno_permitido(db, escola_id, escola.ano_letivo_ativo,
                                      usuario, aluno_id)
    if aluno.status != "ativo":
        # QUEM NÃO ESTÁ NA POPULAÇÃO ATIVA NÃO RECEBE DOCUMENTO OFICIAL. O ranking,
        # os relatórios e o seletor desta tela já filtram `status == "ativo"`; só
        # esta rota aceitava um id direto e emitia. Para um aluno TRANSFERIDO isso
        # é um brasão afirmando que ele é da escola — o mesmo tipo de problema que
        # a guarda de "0,0" abaixo existe para evitar. Se a escola decidir que a
        # criança deve receber mesmo assim, o caminho é explícito e auditado:
        # Alunos › Reativar.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{aluno.nome}” está com situação {_SITUACAO.get(aluno.status, aluno.status)!r} "
            "e não faz parte da população ativa da escola — não dá para emitir um "
            "documento oficial em nome dela. Se a criança de fato deve receber, "
            "reative o cadastro em Alunos › Reativar e emita em seguida.")

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo)
    ).first()
    # AS FASES NÃO CONCORREM. A premiação é do Fundamental I (1º ao 5º ano); as
    # turmas de Educação Infantil que a Lista Piloto traz junto não disputam, e
    # portanto não recebem NENHUM dos três documentos — nem o Mérito nem a arte
    # de participação. Isto é elegibilidade, não cadastro: a criança continua
    # matriculada, ativa e com histórico intacto.
    #
    # Só bloqueia quando a série é CONHECIDA e não elegível. Sem matrícula no ano
    # (ou com rótulo em branco) não dá para afirmar que é fase, e o contrato
    # antigo — aluno sem matrícula alguma recebe a arte — continua valendo;
    # `test_certificado_plataforma` o trava.
    if matricula is not None and matricula[1].ano_escolar:
        if not elegibilidade.participa_de_premiacao(matricula[1].ano_escolar):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"“{aluno.nome}” está em {matricula[1].nome!r} "
                f"({matricula[1].ano_escolar}), que não participa das premiações "
                "— elas são do 1º ao 5º ano. O cadastro e a matrícula seguem "
                "normais; o que não há é certificado de premiação para esta turma.")

    # FICHA NÃO CONFIRMADA NA LISTA PILOTO NÃO RECEBE DOCUMENTO OFICIAL SOZINHA.
    # `da_lista_piloto=False` significa que a importação da Lista Piloto nunca
    # casou este nome: a ficha nasceu de um relatório de plataforma, pelo
    # `aluno.criado_auto`, e por isso vem sem RA e sem data de nascimento. Em
    # 01/10/2026 havia 120 fichas assim nos rankings da rede, duas delas criadas
    # naquela manhã por uma sincronização (2351 e 2352).
    #
    # Elas CONTINUAM no ranking de propósito — ver o módulo
    # ``test_elegibilidade_lista_piloto``: fechar a população neste campo apagaria
    # metade do desempenho de 25 crianças cujo dado está partido entre a ficha
    # oficial e o stub, e o conserto certo é FUSÃO. Mas um certificado é documento
    # com brasão afirmando o nome de uma criança, e aqui o custo do erro é
    # assimétrico: deixar de emitir é um clique a mais, emitir errado é um
    # documento oficial no nome de alguém que talvez não exista.
    #
    # O caminho da confirmação humana já existe e não é novo: importar a Lista
    # Piloto (que reconhece o cadastro e carimba o campo) ou fundir a duplicata em
    # Alunos › Duplicatas. Qualquer um dos dois libera a emissão. Esta guarda fica
    # ANTES da escolha do modelo, de propósito: vale para o Mérito e também para
    # as duas artes de participação, que não passam pela guarda de nota.
    if not aluno.da_lista_piloto:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{aluno.nome}” ainda não está confirmado na Lista Piloto desta "
            "escola, então não dá para emitir um documento oficial no nome dele. "
            "Esta ficha foi criada a partir de um relatório de plataforma e está "
            "sem RA e sem data de nascimento. Importe a Lista Piloto em Estrutura "
            "› Matrículas, ou funda a ficha duplicada em Alunos › Duplicatas, e "
            "emita em seguida.")
    return PreparoCertificado(escola=escola, aluno=aluno, matricula=matricula)


def exigir_merito(db: Session, preparo: PreparoCertificado) -> Nota:
    """Guarda de MÉRITO — só do certificado Geral (o que imprime nota e posição).
    LEVANTA 409 (posição congelada) ou 422 (sem nota calculada), com as mesmas
    mensagens de sempre; devolve a ``Nota`` que o documento imprime."""
    escola, aluno, matricula = preparo.escola, preparo.aluno, preparo.matricula
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno.id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()
    # Certificado de MÉRITO: sem desempenho aferido (aluno recém-cadastrado,
    # import ainda não recalculado, ou sem dado de plataforma) NÃO se emite —
    # um documento oficial com brasão afirmando "0,0" é constrangedor. A
    # guarda lê as DIMENSÕES (contratada, aferida e com nota > 0), não o
    # legado `nota_geral`: é a mesma condição de antes (a nota geral é média
    # ponderada de valores não negativos), sem decidir pela coluna legada.
    # O TEXTO do documento ainda cita nota geral e posição — o que o
    # certificado afirma é decisão do dono (spec-arquitetura-2, Aprovações 4).
    #
    # POSIÇÃO CONGELADA: o motor só renumera quem está na POPULAÇÃO (ativo,
    # matriculado no ano letivo numa turma que concorre). Quem perdeu a
    # matrícula do ano (turma excluída, desvinculado) ou está numa turma sem
    # série reconhecida sai da população, mas a Nota antiga dele fica no
    # banco com a posição de antes — que hoje pertence a outra criança. O
    # Mérito imprime essa posição, então recusa como nos outros casos de
    # população; a arte de participação (sem nota nem posição) não passa aqui.
    if matricula is None or not elegibilidade.participa_de_premiacao(
            matricula[1].ano_escolar):
        onde = (f"está em {matricula[1].nome!r} sem uma série do 1º ao 5º ano "
                "reconhecida" if matricula is not None
                else f"não tem matrícula no ano letivo {escola.ano_letivo_ativo}")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{aluno.nome}” {onde}, então não está no ranking vigente: a "
            "posição guardada para ela é de um cálculo antigo e não vale mais. "
            "Matricule a criança numa turma do ano letivo em Estrutura › "
            "Turmas (o recálculo dá a posição atual) e emita em seguida.")
    if nota is None or not svc_dimensoes.com_desempenho(db, escola, nota):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Este aluno ainda não tem nota calculada — não dá para emitir o "
            "certificado geral. Importe/sincronize os dados da escola (e "
            "aguarde o recálculo) antes de emitir.")
    return nota


def conteudo_certificado(db: Session, preparo: PreparoCertificado,
                         modelo: str | None, bimestre: int | None) -> bytes:
    """O PDF do certificado de UM aluno que já passou por
    :func:`preparar_certificado`. Pode LEVANTAR a guarda de mérito (409/422) no
    Geral — inclusive quando a arte da plataforma falha e a emissão cai nele."""
    escola, aluno, matricula = preparo.escola, preparo.aluno, preparo.matricula
    escola_id = escola.id

    def _geral() -> bytes:
        nota = exigir_merito(db, preparo)
        return svc.gerar_certificado(
            escola_nome=escola.nome,
            cor=svc.cor_primaria(db, escola_id),
            aluno_nome=aluno.nome,
            turma=matricula[1].nome if matricula else "",
            posicao=nota.posicao,
            nota_geral=nota.nota_geral,
            ano_letivo=escola.ano_letivo_ativo,
            logos=svc.logos_da_escola(db, escola_id),
            # A posição é a do ranking da escola: a data do dado é a do selo
            # de frescor dele (as duas dimensões contratadas).
            dados_em=svc.legenda_data_dos_dados(
                frescor_ranking.frescor_da_escola(db, escola, hoje_br()),
                ["leitura", "matematica"]),
        )

    if modelo in ("elefante", "matific"):
        # A arte da plataforma NÃO passa pela guarda de mérito do `_geral()`, e isso
        # é deliberado: ela não imprime nota nem posição — é documento de
        # participação na plataforma, não de mérito. `test_certificado_plataforma`
        # trava esse contrato (aluno sem nenhuma Nota recebe 200). Só a guarda de
        # POPULAÇÃO, acima, vale para os três botões da tela.
        try:
            return svc.gerar_certificado_plataforma(escola.nome, aluno.nome,
                                                    modelo, bimestre=bimestre)
        except Exception:  # noqa: BLE001 — sem Chromium/erro de render: cai no geral
            logger.warning("arte do certificado %s falhou; caindo no geral", modelo,
                           exc_info=True)
            return _geral()
    return _geral()


def registrar_emissao(db: Session, escola_id: int, usuario: Usuario, aluno_id: int,
                      modelo: str | None, *, detalhes_extra: dict | None = None) -> None:
    """A auditoria ``certificado.emitido`` de UM aluno (o commit é de quem chama)."""
    registrar(db, "certificado.emitido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={"modelo": modelo or "geral", **(detalhes_extra or {})})
