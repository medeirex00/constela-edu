"""indicadores oficiais de referência (ICA do município, de SP e do Brasil)

Revision ID: 0034_indicadores_referencia
Revises: 0033_identidade_aposentada
Create Date: 2026-10-16 00:00:00.000000

Cria duas tabelas NOVAS para os números públicos que o INEP divulga por
território — o primeiro é o Indicador Criança Alfabetizada (ICA) da rede
municipal, de SP e do Brasil, com as metas oficiais 2024–2030, o nível e a
participação:

* ``importacoes_indicador`` — cada importação de arquivo oficial: parser e
  versão, arquivo (nome, sha256, tamanho, data interna), URL e Last-Modified
  quando informados, quem importou, quando, status (prévia → aplicada →
  desfeita), contadores, o ``resumo`` (pequeno, lido nas consultas) e, numa
  coluna À PARTE (``desfazer``, nula na prévia), o estado anterior das linhas
  tocadas (desfazer exato) — uma entrada por número, que as consultas não leem.
  A coluna ``desfazer`` entrou AQUI antes da 1ª publicação (o plano ficava em
  ``resumo['desfazer']``): banco LOCAL que já aplicou a 0034/0035 sem ela fica sem a
  coluna (``upgrade heads`` não faz nada), e o app não lista nem desfaz importações
  nele (a coluna ``importacoes_indicador.desfazer`` "não existe" — o modelo a mapeia).
  REPARO: recrie o banco, ou crie a coluna à mão —
  ``ALTER TABLE importacoes_indicador ADD COLUMN desfazer JSON`` (igual no SQLite e no
  PostgreSQL) —, o que deixa o schema igual ao desta revisão sem perder nada: nas
  importações antigas a coluna fica nula e o desfazer lê o plano de
  ``resumo['desfazer']``. Descer até a 0033 e subir de novo NÃO é reparo: sem a coluna,
  o downgrade da 0035 recusa quando uma ausência esconde um número calculado (e só dá
  para desfazer a importação depois de criar a coluna); e, quando passa, as importações
  e os números de ``indicadores_referencia`` saem com as tabelas, mas os números
  oficiais POR ESCOLA (``resultados_avaliacao``) ficam, SEM a proveniência
  (``importacao_id``) — reimportar o SARESP/IEE os apresenta como substituição de
  número sem proveniência (antes = depois, pedindo a resposta da D2) e o Ideb/Saeb os
  mantém como ``igual``, ainda sem proveniência;
* ``indicadores_referencia`` — o número (ou a ausência, com o motivo) por
  território, edição e indicador. Chave natural = restrição única COMUM, sem
  ``COALESCE``: nenhuma coluna da chave é nula, então vale igual no SQLite e no
  PostgreSQL. Sem FK para escola nem para rede (dado público de referência).

ADITIVA: não toca em nenhuma tabela existente (``resultados_avaliacao`` fica
como está). No PostgreSQL, liga ``ROW LEVEL SECURITY`` nas duas — ENABLE, NUNCA
FORCE —, como as demais tabelas de ``public`` em produção (o Supabase alerta
"RLS disabled" para tabela nova). O dono da tabela (o backend) não é afetado
pelo ENABLE; FORCE o bloquearia. No SQLite não há RLS.

DOWNGRADE: remove as duas tabelas (com elas vai a política de RLS) e, DEPOIS delas,
na mesma transação, as linhas ``ica`` e ``iee`` do catálogo ``avaliacoes_externas``
— que nenhuma migração cria: o código desta etapa as cria sob demanda, na prévia da
importação do ICA e na do SARESP/IEE (``obter_avaliacao``; o GET /avaliacoes NÃO as
cria, para não recriá-las depois de uma volta com o código novo ainda no ar), e o
código antigo, que lista o catálogo inteiro no seletor da importação manual, as
mostraria depois de uma volta. Remove SÓ a linha que NADA referencia: as FKs de
``resultados_avaliacao`` e ``fontes_avaliacao`` para o catálogo são ON DELETE CASCADE,
e apagar com vínculo levaria os números ou a receita do robô junto. Com vínculo (ex.:
um resultado gravado à mão na ``ica``, uma receita do robô na ``iee``), a linha FICA,
o log do Alembic avisa com as contagens e nada é apagado. Com um vínculo que a
contagem por id não cobre (FK para outra coluna do catálogo; no PostgreSQL, FK vinda
de outro schema ou tabela com RLS ativa para quem roda), NADA sai do catálogo e o log
avisa. As referências que estavam nas duas tabelas desta revisão não seguram a linha:
saem com as tabelas, antes (e quem importou e não desfez perde esses números ao
descer, como sempre; o N3 manda desfazer antes). As outras avaliações (SAEB, IDEB,
SARESP, a estimativa, os dois CAEd) e os resultados delas não são tocados. Num
catálogo sem ``ica``/``iee`` (instalação que nunca importou o ICA nem o IEE) não há o
que remover. Subir de novo não recria as linhas: o código novo as cria quando
precisar. No modo offline (``--sql``) a limpeza do catálogo não roda (precisa ler o
banco): o SQL gerado tira só as tabelas, e o log avisa. O código IBGE da rede
(``redes.codigo_ibge``, da 0015) FICA numa volta (decisão do dono, 18/10).

Encadeada na 0033 (a única head versionada); a ``0029_curriculo_fase1`` não está
no git e NÃO é encadeada aqui (sem migração de junção).

LOCK_TIMEOUT (só PostgreSQL): as FKs para ``usuarios`` e ``avaliacoes_externas``
seguram SHARE ROW EXCLUSIVE nelas até o commit da transação das migrações (a 0034 e
a 0035 vão juntas). ``SET LOCAL lock_timeout`` faz a migração FALHAR rápido (e
reverter tudo) se outro processo segura um lock que ela precisa — em vez de esperar
sem prazo, congelando o login/heartbeat e as leituras do app antigo, que continua no
ar durante o deploy.
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = '0034_indicadores_referencia'
down_revision: Union[str, None] = '0033_identidade_aposentada'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IMPORTACOES = "importacoes_indicador"
_REFERENCIA = "indicadores_referencia"
_CATALOGO = "avaliacoes_externas"
# Linhas do catálogo que o código dos indicadores oficiais cria SOB DEMANDA
# (``services.avaliacoes.obter_avaliacao``, na prévia da importação própria; o GET
# /avaliacoes não as cria): o ICA (E2) e o IEE (E4). Nenhuma migração as cria, e o
# código anterior à 0034 não as conhece. A descida as remove SÓ quando nada aponta
# para elas.
_CHAVES_DOS_INDICADORES = ("ica", "iee")
# Vínculos com o catálogo que a descida conta MESMO sem a FK declarada (a 0017 e a
# 0019 criam as duas com FK): num banco em que uma delas tenha sumido, a reflexão não
# as acharia, e apagar sem contar deixaria linhas sem a avaliação.
_VINCULOS_CONHECIDOS = (("fontes_avaliacao", "avaliacao_id"),
                        ("resultados_avaliacao", "avaliacao_id"))
# PostgreSQL: TODA FK que aponta para o catálogo, de QUALQUER schema (o inspetor só lê
# o padrão), com as colunas dos dois lados. ``pg_constraint`` é legível por qualquer
# papel, inclusive para tabelas que quem roda não pode ler.
_FKS_PARA_O_CATALOGO_NO_POSTGRES = sa.text(
    "SELECT ns.nspname, cl.relname, col.attname, ref.attname, "
    "       cl.relnamespace = cat.relnamespace "
    "FROM pg_catalog.pg_constraint k "
    "JOIN pg_catalog.pg_class cat ON cat.oid = k.confrelid "
    "JOIN pg_catalog.pg_class cl ON cl.oid = k.conrelid "
    "JOIN pg_catalog.pg_namespace ns ON ns.oid = cl.relnamespace "
    "CROSS JOIN LATERAL unnest(k.conkey, k.confkey) AS par(n_local, n_remota) "
    "JOIN pg_catalog.pg_attribute col "
    "  ON col.attrelid = k.conrelid AND col.attnum = par.n_local "
    "JOIN pg_catalog.pg_attribute ref "
    "  ON ref.attrelid = k.confrelid AND ref.attnum = par.n_remota "
    "WHERE k.contype = 'f' AND k.confrelid = to_regclass(:catalogo) "
    "ORDER BY 1, 2, 3")
# PostgreSQL: a RLS filtra as linhas desta tabela para quem roda a descida? (FORCE, ou
# quem não é dono nem tem BYPASSRLS.) NULL = tabela não achada: também não dá para contar.
_RLS_ATIVA_NO_POSTGRES = sa.text("SELECT row_security_active(to_regclass(:tabela))")
# Espera máxima por um lock (PostgreSQL); vale até o fim da transação (SET LOCAL).
LOCK_TIMEOUT = "5s"

# O logger do próprio Alembic (INFO no alembic.ini): o aviso sai no mesmo log que as
# linhas "Running downgrade ...".
_log = logging.getLogger("alembic.runtime.migration")


def limitar_espera_por_lock() -> None:
    """PostgreSQL: a migração falha (e reverte) em vez de esperar lock sem prazo."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _fks_para_o_catalogo(insp):
    """(tabela, coluna local, coluna do catálogo) de cada FK do schema padrão que
    aponta para ``avaliacoes_externas``, lida do próprio banco."""
    for (_, tabela), fks in insp.get_multi_foreign_keys().items():
        for fk in fks:
            if fk.get("referred_table") != _CATALOGO or fk.get("referred_schema") not in (
                    None, insp.default_schema_name):
                continue
            for local, remota in zip(fk["constrained_columns"], fk["referred_columns"]):
                yield tabela, local, remota


def referencias_ao_catalogo(bind) -> list[tuple[str, str]]:
    """(tabela, coluna) do schema padrão que apontam para ``avaliacoes_externas.id``:
    TODA chave estrangeira lida do próprio banco, não de uma lista fixa (uma tabela
    acrescentada depois, ou que só exista num banco local, também conta), mais os
    vínculos conhecidos (``_VINCULOS_CONHECIDOS``) cuja coluna existe, mesmo sem FK.
    Na 0033 (e depois da descida desta revisão): ``fontes_avaliacao`` (0019) e
    ``resultados_avaliacao`` (0017), as duas com ON DELETE CASCADE. O que aponta para
    o catálogo por outro caminho está em ``vinculos_que_a_contagem_nao_cobre``."""
    insp = sa.inspect(bind)
    refs = {(tabela, local) for tabela, local, remota in _fks_para_o_catalogo(insp)
            if remota == "id"}
    for tabela, coluna in _VINCULOS_CONHECIDOS:
        if insp.has_table(tabela) and coluna in {c["name"] for c in insp.get_columns(tabela)}:
            refs.add((tabela, coluna))
    return sorted(refs)


def vinculos_que_a_contagem_nao_cobre(bind, refs) -> list[str]:
    """O que aponta para o catálogo e a contagem por id das ``refs`` NÃO enxerga. Com
    qualquer item, a descida não remove nada do catálogo (só avisa):

    * FK para OUTRA coluna do catálogo (ex.: ``chave``, que tem índice único): a
      contagem é por id. Lida do banco nos dois dialetos;
    * PostgreSQL: FK vinda de OUTRO schema (o inspetor só lê o padrão) ou qualquer FK
      que não esteja nas ``refs``, lidas de ``pg_constraint``;
    * PostgreSQL: tabela das ``refs`` com ROW LEVEL SECURITY ATIVA para quem roda a
      descida (FORCE, ou quem não é dono nem tem BYPASSRLS): a contagem veria só parte
      das linhas, e o CASCADE (ação de integridade, que ignora a RLS) levaria todas."""
    fora = {f"{tabela}.{local} -> {_CATALOGO}.{remota}"
            for tabela, local, remota in _fks_para_o_catalogo(sa.inspect(bind))
            if remota != "id"}
    if bind.dialect.name == "postgresql":
        contaveis = set(refs)
        for esquema, tabela, local, remota, mesmo_schema in bind.execute(
                _FKS_PARA_O_CATALOGO_NO_POSTGRES, {"catalogo": _CATALOGO}):
            if mesmo_schema and remota == "id" and (tabela, local) in contaveis:
                continue
            origem = f"{tabela}.{local}" if mesmo_schema else f"{esquema}.{tabela}.{local}"
            fora.add(f"{origem} -> {_CATALOGO}.{remota}")
        preparador = bind.dialect.identifier_preparer
        for tabela in sorted({t for t, _ in refs}):
            ativa = bind.execute(_RLS_ATIVA_NO_POSTGRES,
                                 {"tabela": preparador.quote(tabela)}).scalar_one()
            if ativa is not False:
                fora.add(f"{tabela} (row level security ativa para quem roda a descida)")
    return sorted(fora)


def _contar(bind, tabela: str, coluna: str | None = None, ids=None) -> int:
    """COUNT(*) da tabela inteira, ou só das linhas com ``coluna`` em ``ids``.
    Montado pelo SQLAlchemy (nomes citados pelo dialeto), igual nos dois bancos."""
    t = sa.table(tabela, *([sa.column(coluna)] if coluna else []))
    consulta = sa.select(sa.func.count()).select_from(t)
    if coluna:
        consulta = consulta.where(t.c[coluna].in_(list(ids)))
    return bind.execute(consulta).scalar_one()


def remover_linhas_sem_vinculo_do_catalogo(bind) -> dict[str, list[str]]:
    """Remove do catálogo as linhas ``ica`` e ``iee`` QUE NADA REFERENCIA e devolve
    ``{"removidas": [...], "mantidas": [...]}`` (o mesmo vai para o log do Alembic).

    Roda DEPOIS do DROP das duas tabelas desta revisão (``importacoes_indicador`` e
    ``indicadores_referencia``, que também apontam para o catálogo): o que estava nelas
    já saiu com elas e não segura a linha. Contam as tabelas anteriores à 0034,
    ``resultados_avaliacao`` e ``fontes_avaliacao`` (mesmo sem a FK), e qualquer outra
    com FK para o id do catálogo (``referencias_ao_catalogo``).

    NUNCA EM CASCATA: essas FKs são ON DELETE CASCADE, então apagar uma linha com
    vínculo levaria junto os resultados ou a receita do robô. Com qualquer vínculo, a
    linha FICA (aviso com as contagens) e nada dela é apagado. Se algo aponta para o
    catálogo por um caminho que a contagem por id não cobre
    (``vinculos_que_a_contagem_nao_cobre``), NENHUMA linha sai (aviso com a lista). As
    demais avaliações nunca são tocadas: o DELETE vai por id, só das linhas
    ``ica``/``iee`` livres.

    Concorrência (PostgreSQL): as linhas do catálogo são travadas (FOR UPDATE) antes da
    contagem. Gravar um resultado ou uma fonte apontando para elas pede FOR KEY SHARE
    na mesma linha (a checagem da FK), que conflita com o FOR UPDATE: quem já gravou e
    não confirmou faz esta descida esperar (no máximo o ``lock_timeout``, e então ela
    falha e reverte tudo); quem chega depois espera o commit dela. Sem a trava, a
    contagem não veria a gravação ainda não confirmada e o DELETE, liberado depois dela,
    levaria a linha nova em cascata. Na descida inteira, o PostgreSQL 17 já trava o
    catálogo antes, no DROP das tabelas desta revisão (tirar as FKs delas espera quem
    está gravando no catálogo; visto no teste de concorrência); a trava daqui vale
    mesmo sem isso. No SQLite a transação de escrita já trava o banco (o FOR UPDATE não
    é emitido).

    Conferência final, defensiva: depois do DELETE, nenhuma tabela com vínculo pode ter
    perdido linha (o CASCADE do PostgreSQL) nem ficar com linha apontando para a linha
    removida (o SQLite das migrações roda com ``foreign_keys=OFF``, sem cascata); se
    acontecer, a descida inteira PARA e reverte."""
    catalogo = sa.table(_CATALOGO, sa.column("id"), sa.column("chave"))
    linhas = bind.execute(
        sa.select(catalogo.c.id, catalogo.c.chave)
        .where(catalogo.c.chave.in_(_CHAVES_DOS_INDICADORES))
        .order_by(catalogo.c.chave)
        .with_for_update()).all()
    saida: dict[str, list[str]] = {"removidas": [], "mantidas": []}
    if not linhas:
        return saida
    refs = referencias_ao_catalogo(bind)
    fora = vinculos_que_a_contagem_nao_cobre(bind, refs)
    if fora:
        saida["mantidas"] = [chave for _, chave in linhas]
        _log.warning(
            "0034 (downgrade): %s do catálogo %s %s: há vínculo com o catálogo que esta "
            "descida não sabe contar (%s), e apagar poderia levar linhas em cascata ou "
            "deixá-las sem a avaliação. Nada foi apagado.",
            ", ".join(f"'{c}'" for c in saida["mantidas"]), _CATALOGO,
            "FICOU" if len(saida["mantidas"]) == 1 else "FICARAM", "; ".join(fora))
        return saida
    livres = []
    for avaliacao_id, chave in linhas:
        vinculos = {f"{t}.{c}": n for t, c in refs
                    if (n := _contar(bind, t, c, [avaliacao_id]))}
        if not vinculos:
            livres.append((avaliacao_id, chave))
            continue
        saida["mantidas"].append(chave)
        _log.warning(
            "0034 (downgrade): a linha '%s' do catálogo %s FICOU: %s apontam para ela, "
            "e apagá-la levaria essas linhas em cascata. Nada foi apagado.",
            chave, _CATALOGO, ", ".join(f"{n} linha(s) de {onde}"
                                         for onde, n in vinculos.items()))
    if not livres:
        return saida
    ids = [i for i, _ in livres]
    antes = {t: _contar(bind, t) for t in sorted({t for t, _ in refs})}
    bind.execute(sa.delete(catalogo).where(catalogo.c.id.in_(ids)))
    # Defensivo (a contagem por id acima deu zero): nada em cascata, nada órfão.
    perdas = {t: (n, _contar(bind, t)) for t, n in antes.items()}
    perdas = {t: par for t, par in perdas.items() if par[1] < par[0]}
    orfas = {f"{t}.{c}": n for t, c in refs if (n := _contar(bind, t, c, ids))}
    if perdas or orfas:
        raise RuntimeError(
            f"0034 (downgrade): remover {[c for _, c in livres]} do catálogo apagaria "
            f"linhas em cascata (antes, depois: {perdas}) ou as deixaria sem a avaliação "
            f"({orfas}). Nada foi alterado: confira o que aponta para essas linhas e rode "
            "a descida de novo.")
    saida["removidas"] = [c for _, c in livres]
    _log.info("0034 (downgrade): removida(s) do catálogo %s, sem nenhum vínculo: %s.",
              _CATALOGO, ", ".join(saida["removidas"]))
    return saida


def upgrade() -> None:
    limitar_espera_por_lock()
    op.create_table(
        _IMPORTACOES,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("avaliacao_id", sa.Integer(),
                  sa.ForeignKey("avaliacoes_externas.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("parser", sa.String(length=40), nullable=False),
        sa.Column("parser_versao", sa.String(length=20), nullable=False),
        sa.Column("fonte_nome", sa.String(length=120), nullable=False),
        sa.Column("url_origem", sa.String(length=500), nullable=True),
        sa.Column("arquivo_nome", sa.String(length=255), nullable=False),
        sa.Column("arquivo_sha256", sa.String(length=64), nullable=False),
        sa.Column("arquivo_bytes", sa.Integer(), nullable=False),
        sa.Column("last_modified_origem", sa.String(length=64), nullable=True),
        sa.Column("arquivo_data", sa.DateTime(), nullable=True),
        sa.Column("edicao_arquivo", sa.Integer(), nullable=False),
        sa.Column("versao_rotulo", sa.String(length=60), nullable=True),
        sa.Column("codigo_territorio_alvo", sa.String(length=7), nullable=False),
        sa.Column("citacao", sa.String(length=500), nullable=True),
        sa.Column("licenca", sa.String(length=200), nullable=True),
        sa.Column("modo", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("contadores", sa.JSON(), nullable=False),
        sa.Column("resumo", sa.JSON(), nullable=False),
        sa.Column("desfazer", sa.JSON(), nullable=True),
        sa.Column("pacote_sha256", sa.String(length=64), nullable=True),
        sa.Column("usuario_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("coletado_em", sa.DateTime(), nullable=True),
        sa.Column("aplicado_em", sa.DateTime(), nullable=True),
        sa.Column("desfeito_em", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_importacoes_indicador_avaliacao_status", _IMPORTACOES,
                    ["avaliacao_id", "status"])

    op.create_table(
        _REFERENCIA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("avaliacao_id", sa.Integer(),
                  sa.ForeignKey("avaliacoes_externas.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("edicao", sa.Integer(), nullable=False),
        sa.Column("indicador", sa.String(length=40), nullable=False),
        sa.Column("abrangencia", sa.String(length=10), nullable=False),
        sa.Column("codigo_territorio", sa.String(length=7), nullable=False),
        sa.Column("codigo_inep", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("rede_ensino", sa.String(length=20), nullable=False),
        sa.Column("localizacao", sa.String(length=10), nullable=False,
                  server_default="total"),
        sa.Column("etapa", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("componente", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("nivel", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("valor", sa.Float(), nullable=True),
        sa.Column("valor_detalhado", sa.Float(), nullable=True),
        sa.Column("detalhe_importacao_id", sa.Integer(),
                  sa.ForeignKey(f"{_IMPORTACOES}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operador", sa.String(length=2), nullable=True),
        sa.Column("casas_decimais", sa.SmallInteger(), nullable=True),
        sa.Column("casas_decimais_detalhe", sa.SmallInteger(), nullable=True),
        sa.Column("unidade", sa.String(length=20), nullable=False),
        sa.Column("desenho", sa.String(length=12), nullable=True),
        sa.Column("motivo_ausencia", sa.String(length=40), nullable=True),
        sa.Column("importacao_id", sa.Integer(),
                  sa.ForeignKey(f"{_IMPORTACOES}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "avaliacao_id", "edicao", "indicador", "abrangencia", "codigo_territorio",
            "codigo_inep", "rede_ensino", "localizacao", "etapa", "componente", "nivel",
            name="uq_indicador_referencia_natural"),
        sa.CheckConstraint("valor IS NOT NULL OR motivo_ausencia IS NOT NULL",
                           name="ck_indicador_valor_ou_motivo"),
    )
    op.create_index("ix_indicadores_referencia_territorio", _REFERENCIA,
                    ["codigo_territorio", "avaliacao_id", "indicador"])

    # Supabase: tabela nova em `public` sem RLS reabre o alerta "RLS disabled".
    # ENABLE (nunca FORCE): o dono das tabelas — o backend — continua lendo e
    # gravando; o acesso direto pela API do Supabase (anon/authenticated) fica
    # fechado, sem política. Só no PostgreSQL: o SQLite não tem RLS.
    if op.get_bind().dialect.name == "postgresql":
        for tabela in (_IMPORTACOES, _REFERENCIA):
            op.execute(sa.text(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    limitar_espera_por_lock()
    # Remove SÓ o que a 0034 criou (o RLS vai junto com a tabela)...
    op.drop_index("ix_indicadores_referencia_territorio", table_name=_REFERENCIA)
    op.drop_table(_REFERENCIA)
    op.drop_index("ix_importacoes_indicador_avaliacao_status", table_name=_IMPORTACOES)
    op.drop_table(_IMPORTACOES)
    # ...e, DEPOIS das tabelas (que também apontam para o catálogo), as linhas
    # ``ica``/``iee`` que o código desta etapa criou, só se nada mais as referencia.
    # Mesma transação: se a descida parar adiante, a remoção volta junto.
    if context.is_offline_mode():
        # ``alembic downgrade A:B --sql``: o bind é simulado (não lê o catálogo nem conta
        # os vínculos). O SQL gerado tira só as tabelas.
        _log.warning(
            "0034 (downgrade) em modo offline (--sql): a limpeza das linhas 'ica'/'iee' "
            "do catálogo %s só roda online (precisa ler o banco); o SQL gerado NÃO a "
            "inclui.", _CATALOGO)
        return
    remover_linhas_sem_vinculo_do_catalogo(op.get_bind())
