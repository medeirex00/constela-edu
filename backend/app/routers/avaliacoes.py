"""Avaliações externas — catálogo e importação de resultados oficiais.

MVP: importação de ARQUIVO oficial (XLSX/CSV) — nenhuma das fontes (SAEB/IDEB/
SARESP/Criança Alfabetizada) tem API self-serve. Fluxo: `analisar` mostra a grade
crua (o gestor escolhe a linha de dados e mapeia as colunas), `importar` grava
casando escola por CÓDIGO INEP.

PERMISSÃO (decisão D4 do dono, 17/10): SÓ o administrador global importa (manual, 1
clique, robô) e desfaz (``DELETE /avaliacoes/resultados``) — de QUALQUER escola, casando
pelo código INEP em toda a base. A Secretaria, o coordenador e o professor recebem 403
nessas rotas (eles LEEM os resultados: a Secretaria em ``/redes/{id}/...``, o
coordenador em ``/escolas/{id}/indicadores``). O catálogo e a lista de presets são
leitura e continuam abertos a quem está logado.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, get_usuario_atual
from app.models import AvaliacaoExterna, FonteAvaliacao, ResultadoAvaliacao, Usuario
from app.services import avaliacoes as svc
from app.services.audit import registrar

router = APIRouter(prefix="/avaliacoes", tags=["Avaliações externas"])

# O arquivo oficial do IDEB por escola é grande (ZIP de "anos iniciais" ~97 MB).
# O caminho principal é o robô baixar sozinho pelo servidor; este teto cobre o
# upload manual (plano B) sem estourar a RAM. Ver _MAX_DOWNLOAD no serviço.
_MAX_BYTES = 150 * 1024 * 1024


# Alcance da gravação: as rotas de escrita são só do admin global (D4), que casa por
# código INEP em TODAS as escolas da base (``escopo_escolas=None`` no serviço). O
# recorte por perfil (rede ou escola) deixou de existir aqui junto com a escrita da
# Secretaria e do coordenador — o serviço continua aceitando um escopo (testes, robô).
_TODAS_AS_ESCOLAS = None


_MSG_SO_REFERENCIA = {
    "ica": ("O Indicador Criança Alfabetizada é da rede (município), não da escola: "
            "importe o arquivo oficial do INEP no cartão do ICA, em Avaliações externas. "
            "Nada foi gravado."),
    "iee": ("O IEE entra pelo arquivo oficial da SEDUC (Índice de Excelência "
            "Educacional), com prévia e desfazer, na importação do SARESP oficial — não "
            "pela importação manual por escola. Nada foi gravado."),
}


def _recusar_so_referencia(avaliacao: str) -> None:
    """O ICA oficial não existe por escola: gravá-lo em `resultados_avaliacao`
    (upload por escola ou robô) criaria um "ICA por escola" que o INEP não publica.
    O IEE tem importação oficial própria (arquivo da SEDUC, com prévia e desfazer)."""
    if avaliacao in svc.SO_REFERENCIA:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            _MSG_SO_REFERENCIA.get(avaliacao, "Esta avaliação tem importação oficial "
                                              "própria, com prévia. Nada foi gravado."))


@router.get("")
def catalogo(usuario: Usuario = Depends(get_usuario_atual), db: Session = Depends(get_db)):
    """Catálogo de avaliações/indicadores (materializa o catálogo inicial). Nome,
    órgão e descrição saem pela EXIBIÇÃO do serviço (vale mesmo com a linha antiga
    no banco) — a tela agrupa o seletor pelo órgão.

    É o catálogo da importação POR ESCOLA: o ICA oficial (``SO_REFERENCIA``) fica
    de fora — ele é da rede e tem importação própria (/redes/{id}/indicadores).

    Também NÃO cria as linhas de ``SO_REFERENCIA`` (o ICA e o IEE): elas nascem na
    prévia da importação própria (``obter_avaliacao`` no pipeline). Senão este GET as
    recriaria depois de uma volta (a descida da 0034 as tira do catálogo e o código
    novo pode continuar no ar alguns minutos), e o seletor do código antigo as
    mostraria."""
    for chave in svc.CATALOGO:
        if chave in svc.SO_REFERENCIA:
            continue
        svc.obter_avaliacao(db, chave)
    db.commit()
    itens = [
        {"chave": a.chave, "nome": svc.nome_exibicao(a.chave, a.nome), "tipo": a.tipo,
         "orgao": svc.orgao_exibicao(a.chave, a.orgao),
         "descricao": svc.descricao_exibicao(a.chave, a.descricao)}
        for a in db.execute(select(AvaliacaoExterna)).scalars()
        if a.chave not in svc.SO_REFERENCIA
    ]
    return sorted(itens, key=lambda i: (i["tipo"], i["nome"]))


# Endpoints SÍNCRONOS de propósito: o parse (openpyxl) e a gravação são CPU/DB
# bound; como `def` (não `async def`), o FastAPI os roda numa thread do pool, sem
# travar o event loop durante um arquivo grande. Por isso lemos o arquivo pelo
# objeto síncrono (arquivo.file.read()).

@router.post("/analisar")
def analisar(
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_admin_global),
):
    """Prévia: grade crua das primeiras linhas — a tela usa para escolher a linha
    de dados e mapear as colunas (por índice). Robusto a pré-âmbulo/edição. É o
    primeiro passo da importação manual: só o admin global (D4)."""
    conteudo = arquivo.file.read(_MAX_BYTES + 1)  # limitado: o teto limita a RAM
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande. Extraia/reduza a planilha antes de subir.")
    try:
        return svc.analisar_planilha(conteudo, arquivo.filename or "")
    except svc.ImportacaoRecusada as exc:   # planilha recusada antes de abrir (inflada)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/importar")
def importar(
    arquivo: UploadFile = File(...),
    avaliacao: str = Form(...),
    edicao: int = Form(...),
    indicador: str = Form(...),
    unidade: str = Form(...),
    linha_dados: int = Form(...),
    col_inep: int = Form(...),
    col_valor: int = Form(...),
    col_etapa: int | None = Form(None),
    col_componente: int | None = Form(None),
    col_turma: int | None = Form(None),
    etapa_fixa: str | None = Form(None),
    componente_fixo: str | None = Form(None),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Importa os resultados casando escola por CÓDIGO INEP (todas as escolas da
    base: só o admin global importa — D4). Idempotente por (avaliação, edição,
    indicador, escola, etapa, componente, turma). Só grava os níveis que o arquivo
    fornece."""
    if avaliacao not in svc.CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Avaliação desconhecida: {avaliacao}.")
    _recusar_so_referencia(avaliacao)
    if linha_dados < 0 or col_inep < 0 or col_valor < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mapeamento inválido.")
    conteudo = arquivo.file.read(_MAX_BYTES + 1)  # limitado: o teto limita a RAM
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo muito grande.")

    try:
        resultado = svc.importar_resultados(
            db, conteudo, arquivo.filename or "",
            avaliacao_chave=avaliacao, edicao=edicao, indicador=indicador, unidade=unidade,
            linha_dados=linha_dados, col_inep=col_inep, col_valor=col_valor,
            col_etapa=col_etapa, col_componente=col_componente, col_turma=col_turma,
            etapa_fixa=etapa_fixa, componente_fixo=componente_fixo,
            escopo_escolas=_TODAS_AS_ESCOLAS)
    except svc.ImportacaoRecusada as exc:   # recusada antes de gravar (sem commit)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    registrar(db, "avaliacao.importada", usuario_id=usuario.id,
              entidade="avaliacao_externa", detalhes=svc.resumo_para_auditoria(resultado))
    db.commit()
    return resultado


# Presets de IMPORT DE 1 CLIQUE: o gestor escolhe a base e sobe o arquivo (o
# mapeamento de colunas já é conhecido). Uma base pode gerar VÁRIAS séries numa
# leitura só (SAEB = Matemática + Português, ambos dentro do mesmo arquivo do IDEB).
# IDEB e SAEB vêm do arquivo OFICIAL do INEP (`layout_inep`): as colunas são
# localizadas PELO NOME na linha técnica, com a edição escolhida no nome da
# variável — nunca pela posição. A edição de 2025 insere colunas em cada bloco: ler
# as posições de 2023 (3, 103, 104, 115) gravaria outra variável como se fosse a
# edição escolhida. Sem a coluna da edição pedida, a importação é RECUSADA. A
# ETAPA sai do topo do arquivo (`marcadores_etapa`): os nomes das variáveis são os
# mesmos em Anos Iniciais e Anos Finais, e o arquivo errado gravaria por cima.
# SARESP e a estimativa de alfabetização usam arquivos que o Constela prepara
# (layout próprio e fixo): seguem por posição.
# ETAPA (0035): SAEB e SARESP gravam a SÉRIE avaliada ("5_ano"); o IDEB continua
# "anos_iniciais" (o índice cobre do 1º ao 5º ano). O SARESP OFICIAL por escola
# (proficiência do IEE, 2º e 5º ano) entra pela importação com prévia em
# /redes/{id}/indicadores/saresp — este preset é o do arquivo preparado pelo Constela.
_ARQUIVO_INEP_AI = "o arquivo oficial do INEP de Anos Iniciais (Ideb por escola) da edição {edicao}"
_MARCADORES_AI = ("Anos Iniciais", "1º ao 5º ano")   # como no arquivo oficial de 2023
_PRESETS_IMPORT: dict[str, dict] = {
    "ideb_ai": {
        "rotulo": "IDEB — Anos Iniciais", "avaliacao": "ideb",
        "dica": "Suba o .zip oficial do INEP — Anos Iniciais (o arquivo grande que você baixou).",
        "indicador": "ideb", "unidade": "indice",
        "layout_inep": {"col_inep": "ID_ESCOLA", "arquivo": _ARQUIVO_INEP_AI,
                        "marcadores_etapa": _MARCADORES_AI},
        "series": [{"coluna": "VL_OBSERVADO_{edicao}", "etapa_fixa": "anos_iniciais"}],
    },
    "saeb_ai": {
        "rotulo": "SAEB — Anos Iniciais (Matemática e Português)", "avaliacao": "saeb",
        "dica": "Suba o MESMO .zip do INEP — Anos Iniciais (o SAEB está dentro do arquivo do IDEB).",
        "indicador": "proficiencia", "unidade": "escala_saeb",
        "layout_inep": {"col_inep": "ID_ESCOLA", "arquivo": _ARQUIVO_INEP_AI,
                        "marcadores_etapa": _MARCADORES_AI},
        "series": [
            {"coluna": "VL_NOTA_MATEMATICA_{edicao}", "componente_fixo": "matematica",
             "etapa_fixa": "5_ano"},
            {"coluna": "VL_NOTA_PORTUGUES_{edicao}", "componente_fixo": "portugues",
             "etapa_fixa": "5_ano"},
        ],
    },
    "saresp_ai": {
        "rotulo": "SARESP — Anos Iniciais (5º ano)", "avaliacao": "saresp",
        "dica": "Suba o arquivo da SARESP que o Constela preparou para você (INEP · componente · nota).",
        "indicador": "proficiencia", "unidade": "escala_saresp", "linha_dados": 1, "col_inep": 0,
        # componente vem de uma COLUNA (não fixo): matemática/português na col 1.
        "series": [{"col_valor": 2, "col_componente": 1, "etapa_fixa": "5_ano"}],
    },
    # Rótulo pela D1: é a ESTIMATIVA do Constela (SARESP 2º ano), não o indicador
    # oficial do INEP. A chave do preset e a da avaliação ficam como estão.
    "crianca_alfab": {
        "rotulo": svc.nome_exibicao("crianca_alfabetizada",
                                    "Criança Alfabetizada — 2º ano (taxa %)"),
        "dica": "Suba o arquivo que o Constela preparou a partir do SARESP do 2º ano "
                "(código INEP · taxa % de Suficiente + Avançado). É uma estimativa do "
                "Constela, não o Indicador Criança Alfabetizada do INEP (que é da rede).",
        "avaliacao": "crianca_alfabetizada", "indicador": "taxa_alfabetizacao",
        "unidade": "percentual", "linha_dados": 1, "col_inep": 0,
        "series": [{"col_valor": 1, "etapa_fixa": "2_ano"}],
    },
}


@router.get("/presets-import")
def presets_import(usuario: Usuario = Depends(get_usuario_atual)):
    """As bases oficiais que importam em 1 clique (só escolher + subir o arquivo)."""
    return [{"chave": k, "rotulo": p["rotulo"], "avaliacao": p["avaliacao"],
             "dica": p.get("dica", "")}
            for k, p in _PRESETS_IMPORT.items()]


@router.post("/importar-preset")
def importar_preset(
    arquivo: UploadFile = File(...),
    preset: str = Form(...),
    edicao: int = Form(...),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Import de 1 CLIQUE: escolha a base (preset) + suba o arquivo oficial do INEP.
    O mapeamento (colunas) já é conhecido; roda as séries do preset (ex.: SAEB =
    matemática + português) numa única leitura. Casa por INEP em todas as escolas
    (só o admin global importa — D4).
    No arquivo do INEP, a etapa (pelo topo) e TODAS as colunas (pelo nome) são
    conferidas ANTES de gravar: não conferiu (layout, etapa ou edição errados) →
    400 e nada é gravado."""
    p = _PRESETS_IMPORT.get(preset)
    if p is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Base desconhecida: {preset}.")
    conteudo = arquivo.file.read(_MAX_BYTES + 1)
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo muito grande.")
    layout = p.get("layout_inep")
    if layout is not None:
        variaveis = [s["coluna"].format(edicao=edicao) for s in p["series"]]
        try:
            linha_dados, colunas = svc.localizar_colunas_inep(
                conteudo, arquivo.filename or "", [layout["col_inep"], *variaveis],
                marcadores_etapa=layout["marcadores_etapa"],
                arquivo_esperado=layout["arquivo"].format(edicao=edicao))
        except svc.ImportacaoRecusada as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        col_inep = colunas[layout["col_inep"]]
        series = [{**s, "coluna": v, "col_valor": colunas[v]}
                  for s, v in zip(p["series"], variaveis)]
    else:
        linha_dados, col_inep, series = p["linha_dados"], p["col_inep"], p["series"]
    escopo = _TODAS_AS_ESCOLAS
    series_out = []
    for s in series:
        try:
            r = svc.importar_resultados(
                db, conteudo, arquivo.filename or "",
                avaliacao_chave=p["avaliacao"], edicao=edicao,
                indicador=p["indicador"], unidade=p["unidade"],
                linha_dados=linha_dados, col_inep=col_inep,
                col_valor=s["col_valor"], componente_fixo=s.get("componente_fixo"),
                col_componente=s.get("col_componente"),  # SARESP: componente vem da coluna
                etapa_fixa=s.get("etapa_fixa"), escopo_escolas=escopo)
        except svc.ImportacaoRecusada as exc:   # recusada antes de gravar (sem commit)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        series_out.append({"componente": s.get("componente_fixo"),
                           "coluna": s.get("coluna"),   # variável lida (arquivo do INEP)
                           "casados": r["casados"], "inseridos": r["inseridos"],
                           "atualizados": r["atualizados"],
                           # números oficiais (importação com prévia) preservados
                           "mantidos_oficiais": r["mantidos_oficiais"],
                           "nao_casados": r["nao_casados"],
                           "inep_nao_casados": r["inep_nao_casados"]})
    registrar(db, "avaliacao.importada_preset", usuario_id=usuario.id,
              entidade="avaliacao_externa",
              detalhes={"preset": preset, "edicao": edicao,
                        "series": [svc.resumo_para_auditoria(s) for s in series_out]})
    db.commit()
    return {"avaliacao": p["avaliacao"], "rotulo": p["rotulo"],
            "edicao": edicao, "series": series_out}


@router.delete("/resultados")
def excluir_resultados(
    avaliacao: str,
    edicao: int,
    indicador: str,
    etapa: str | None = None,
    componente: str | None = None,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Remove UMA série específica de resultados — para DESFAZER uma importação
    errada (ano trocado, arquivo errado). A série é identificada por (avaliação,
    edição, indicador, etapa, componente): assim remover a série mostrada NÃO
    apaga as irmãs da mesma edição (ex.: SAEB matemática ≠ português; anos_iniciais
    ≠ anos_finais). Dimensão OMITIDA casa quem NÃO tem essa dimensão (NULL).
    Só o admin global desfaz (D4) — de todas as escolas.

    Só linhas de ESCOLA (``resultados_avaliacao``): nunca toca em
    ``indicadores_referencia`` (município, UF, Brasil, metas, níveis). Série que
    tem número de importação OFICIAL com prévia (``importacao_id``, desde a 0035)
    não é apagada aqui: 409, e a mensagem diz qual importação desfazer — apagar por
    fora deixaria aquela importação sem desfazer e sumiria com as ausências
    registradas (valor nulo + motivo) junto com os números."""
    if avaliacao not in svc.CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Avaliação desconhecida: {avaliacao}.")
    av = svc.obter_avaliacao(db, avaliacao)
    filtros = [
        ResultadoAvaliacao.avaliacao_id == av.id,
        ResultadoAvaliacao.edicao == edicao,
        ResultadoAvaliacao.indicador == indicador,
        ResultadoAvaliacao.escola_id.isnot(None),   # só escola (a tabela é de escola)
        # etapa/componente ausentes ⇒ casa NULL (a série não tem a dimensão);
        # presentes ⇒ casa o valor exato — nunca apaga série irmã não selecionada.
        ResultadoAvaliacao.etapa == etapa if etapa is not None
        else ResultadoAvaliacao.etapa.is_(None),
        ResultadoAvaliacao.componente == componente if componente is not None
        else ResultadoAvaliacao.componente.is_(None),
    ]
    oficiais = sorted(set(db.execute(
        select(ResultadoAvaliacao.importacao_id).where(
            *filtros, ResultadoAvaliacao.importacao_id.isnot(None))).scalars()))
    if oficiais:
        lista = ", ".join(f"#{i}" for i in oficiais)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Esta série tem números da importação oficial {lista} (com prévia). Para "
            "removê-los, desfaça a importação em Indicadores oficiais — assim volta "
            "exatamente o estado anterior. Nada foi apagado.")
    removidos = db.execute(sa_delete(ResultadoAvaliacao).where(*filtros)).rowcount
    registrar(db, "avaliacao.resultados_removidos", usuario_id=usuario.id,
              entidade="avaliacao_externa",
              detalhes={"avaliacao": avaliacao, "edicao": edicao, "indicador": indicador,
                        "etapa": etapa, "componente": componente, "removidos": removidos})
    db.commit()
    return {"removidos": removidos}


# --- Fontes de COLETA AUTOMÁTICA (o "robô") — só admin global -----------------
# A Secretaria não sobe nada: o admin global cadastra a RECEITA uma vez (URL do
# arquivo oficial + o mapeamento de colunas, travado ao subir o arquivo real na
# tela) e o software passa a baixar/importar sozinho, casando por INEP.

class _MapeamentoIn(BaseModel):
    linha_dados: int = 0
    col_inep: int = 0
    col_valor: int = 0
    col_etapa: int | None = None
    col_componente: int | None = None
    col_turma: int | None = None
    etapa_fixa: str | None = None
    componente_fixo: str | None = None


class _FonteIn(BaseModel):
    avaliacao: str
    nome: str
    url: str
    edicao: int
    indicador: str
    unidade: str
    cadencia: str = "manual"  # manual (coleta sob demanda) | mensal (agendada)
    mapeamento: _MapeamentoIn


def _fonte_saida(f: FonteAvaliacao, av: AvaliacaoExterna | None) -> dict:
    return {
        "id": f.id, "avaliacao": av.chave if av else None,
        "avaliacao_nome": svc.nome_exibicao(av.chave, av.nome) if av else None,
        "nome": f.nome, "url": f.url, "edicao": f.edicao,
        "indicador": f.indicador, "unidade": f.unidade,
        "cadencia": f.cadencia, "ativo": f.ativo, "mapeamento": f.mapeamento,
        "ultima_coleta": f.ultima_coleta.isoformat() if f.ultima_coleta else None,
        "proxima_coleta": f.proxima_coleta.isoformat() if f.proxima_coleta else None,
        "ultimo_status": f.ultimo_status, "ultimo_erro": f.ultimo_erro,
        "ultimo_resumo": f.ultimo_resumo,
    }


@router.get("/fontes")
def listar_fontes(
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Lista as fontes cadastradas com o último status de coleta (para o painel)."""
    fontes = db.execute(
        select(FonteAvaliacao).order_by(FonteAvaliacao.nome)).scalars().all()
    avs = {a.id: a for a in db.execute(select(AvaliacaoExterna)).scalars()}
    return [_fonte_saida(f, avs.get(f.avaliacao_id)) for f in fontes]


@router.post("/fontes", status_code=status.HTTP_201_CREATED)
def criar_fonte(
    dados: _FonteIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Cadastra a receita do robô (URL + mapeamento). ``mensal`` já agenda a 1ª
    coleta para agora (o scheduler pega no próximo tick)."""
    if dados.avaliacao not in svc.CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Avaliação desconhecida: {dados.avaliacao}.")
    _recusar_so_referencia(dados.avaliacao)
    if not dados.url.strip().lower().startswith("https://"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A URL precisa ser https:// (endereço oficial do arquivo).")
    if dados.mapeamento.linha_dados < 0 or dados.mapeamento.col_inep < 0 \
            or dados.mapeamento.col_valor < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mapeamento inválido.")
    # A mesma trava da importação (SAEB/SARESP não gravam "anos_iniciais") já no
    # CADASTRO: senão a receita é aceita e toda coleta cai em erro — e o mapeamento
    # não se edita depois (PUT só liga/desliga e troca a cadência).
    try:
        svc.exigir_etapa_por_serie(dados.avaliacao, dados.mapeamento.etapa_fixa)
    except svc.ImportacaoRecusada as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    av = svc.obter_avaliacao(db, dados.avaliacao)
    cadencia = "mensal" if dados.cadencia == "mensal" else "manual"
    fonte = FonteAvaliacao(
        avaliacao_id=av.id, nome=dados.nome.strip(), url=dados.url.strip(),
        edicao=dados.edicao, indicador=dados.indicador.strip(),
        unidade=dados.unidade.strip(), cadencia=cadencia,
        mapeamento=dados.mapeamento.model_dump(),
        proxima_coleta=svc._agora() if cadencia == "mensal" else None)
    db.add(fonte)
    db.flush()
    registrar(db, "avaliacao.fonte.criada", usuario_id=usuario.id,
              entidade="fonte_avaliacao", entidade_id=fonte.id,
              detalhes={"nome": fonte.nome, "url": fonte.url})
    db.commit()
    db.refresh(fonte)
    return _fonte_saida(fonte, av)


@router.post("/fontes/{fonte_id}/coletar")
def coletar_agora(
    fonte_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Dispara a coleta AGORA (baixa o arquivo oficial e importa). Nunca levanta
    por erro de rede/parse: devolve o status para a tela mostrar."""
    fonte = db.get(FonteAvaliacao, fonte_id)
    if fonte is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    resumo = svc.coletar_fonte(db, fonte)
    registrar(db, "avaliacao.fonte.coletada", usuario_id=usuario.id,
              entidade="fonte_avaliacao", entidade_id=fonte.id, detalhes=resumo)
    db.commit()
    db.refresh(fonte)
    return _fonte_saida(fonte, db.get(AvaliacaoExterna, fonte.avaliacao_id))


@router.put("/fontes/{fonte_id}")
def atualizar_fonte(
    fonte_id: int,
    ativo: bool | None = None,
    cadencia: str | None = None,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Liga/desliga a fonte ou troca a cadência (pausar a coleta agendada)."""
    fonte = db.get(FonteAvaliacao, fonte_id)
    if fonte is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    if ativo is not None:
        fonte.ativo = ativo
    if cadencia is not None:
        fonte.cadencia = "mensal" if cadencia == "mensal" else "manual"
    # Invariante (reconciliado após tratar AMBOS os campos): fonte mensal ATIVA
    # sempre tem proxima_coleta; qualquer outra fica None. Sem isto, reativar uma
    # fonte mensal (só ?ativo=true) a deixaria com proxima_coleta=None e o
    # scheduler a ignoraria em silêncio.
    if fonte.ativo and fonte.cadencia == "mensal":
        fonte.proxima_coleta = fonte.proxima_coleta or svc._agora()
    else:
        fonte.proxima_coleta = None
    db.commit()
    db.refresh(fonte)
    return _fonte_saida(fonte, db.get(AvaliacaoExterna, fonte.avaliacao_id))


@router.delete("/fontes/{fonte_id}")
def excluir_fonte(
    fonte_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Remove a receita (não apaga os resultados já importados)."""
    fonte = db.get(FonteAvaliacao, fonte_id)
    if fonte is not None:
        registrar(db, "avaliacao.fonte.excluida", usuario_id=usuario.id,
                  entidade="fonte_avaliacao", entidade_id=fonte.id,
                  detalhes={"nome": fonte.nome})
        db.delete(fonte)
        db.commit()
    return {"ok": True}
