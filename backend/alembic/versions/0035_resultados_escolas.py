"""resultados por escola com ausência e proveniência; etapa = série; INEP único

Revision ID: 0035_resultados_escolas
Revises: 0034_indicadores_referencia
Create Date: 2026-10-17 00:00:00.000000

Etapa E4 dos indicadores oficiais (SARESP oficial). Prepara a tabela em uso
(``resultados_avaliacao``) para a importação oficial com prévia e desfazer:

* ``motivo_ausencia`` (String(40), nula) e ``importacao_id`` (FK para
  ``importacoes_indicador``, SET NULL) — novas;
* ``valor`` passa a aceitar nulo, com ``CHECK (valor IS NOT NULL OR
  motivo_ausencia IS NOT NULL)``: AUSÊNCIA ≠ ZERO, e nunca sem o motivo;
* o índice de expressão ``uq_resultado_natural`` (0022, com ``COALESCE``) é
  RECRIADO explicitamente: no SQLite o batch recria a tabela e não reflete índice
  de expressão (ele sumiria em silêncio). A definição é a mesma da 0022;
* NORMALIZAÇÃO DA ETAPA: SAEB e SARESP gravavam ``anos_iniciais``; passam a gravar
  a SÉRIE avaliada (``5_ano``; o SARESP oficial também ``2_ano``). O IDEB continua
  ``anos_iniciais`` (o índice cobre do 1º ao 5º ano). Vale toda GRAFIA de
  "anos_iniciais" ("Anos Iniciais", "anos-iniciais": o robô antigo gravava a
  ``etapa_fixa`` como veio) — a MESMA regra nas linhas e na receita, senão a coleta
  seguinte abriria uma segunda série. ``UPDATE`` parametrizado por id, conferido
  antes: se já houver a mesma chave com ``5_ano`` (colisão), a migração
  PARA com a lista (nunca funde nem apaga em silêncio). O número de linhas é o
  mesmo antes e depois (na cópia de 05/10: 135 → 135). A RECEITA DO ROBÔ
  (``fontes_avaliacao.mapeamento``, JSON) do SAEB/SARESP com ``etapa_fixa`` =
  "anos_iniciais" passa a "5_ano" pelo mesmo motivo: a importação recusa
  "anos_iniciais" nessas duas, e sem a troca toda coleta da receita antiga cairia em
  erro — o mapeamento não se edita pela API (o PUT só liga/desliga e muda a cadência);
* ``escolas``: índice único PARCIAL ``uq_escolas_codigo_inep`` (``WHERE
  codigo_inep IS NOT NULL``), igual no SQLite e no PostgreSQL. Conferido antes:
  código repetido PARA a migração com a lista (corrigir pelo PATCH da escola);
* ``redes``: ``codigo_municipio_estadual`` (String(8), nula) — o CODMUN da SEDUC
  (Caraguatatuba = 254), que NÃO é o IBGE. Gravado pela tela/PATCH, nunca aqui;
* catálogo (dado): a descrição do SARESP dizia "rede estadual"; o SARESP cobre
  também as redes municipais que aderem. Troca SÓ se o texto ainda for o antigo.
  O nome da série estimada ("Criança Alfabetizada", D1) NÃO muda aqui: a E1 já
  troca o rótulo na exibição (reversível) e a decisão do dono está pendente.

A FK ``escola_id`` continua CASCADE (plano, "Correções da revisão").

LOCK_TIMEOUT (só PostgreSQL, como na 0034): o ``DROP INDEX`` e o ``ALTER TABLE``
pedem ACCESS EXCLUSIVE; com um leitor longo aberto (o pg_dump do backup, uma
sincronização), a migração falha em segundos e reverte tudo, em vez de esperar sem
prazo segurando os locks da 0034 (``usuarios``) — o app antigo segue no ar.

DOWNGRADE: PARA (sem mexer em nada) se uma AUSÊNCIA de hoje esconde um número SEM
proveniência oficial (a média calculada pelo Constela, o 1 clique) que só está no plano
de desfazer de uma importação APLICADA — direto (a importação trocou o calculado pela
ausência) ou em cadeia (a #1 trocou o calculado pelo oficial e a #2, retificada, o
oficial pela ausência): apagar a ausência levaria o número, e o plano vai junto com a
0034 — desfaça antes a importação que gravou a ausência. Fora isso, apaga ANTES
as linhas com ``valor`` nulo (o schema antigo não as comporta; as oficiais voltam
reimportando a fonte), devolve ``5_ano`` → ``anos_iniciais`` no SAEB e no SARESP
(com a mesma conferência de colisão; o ``2_ano`` do SARESP oficial fica como está) e
na receita do robô, remove as colunas, o CHECK, o índice das escolas e a coluna da
rede, devolve a descrição antiga e recria o ``uq_resultado_natural``. Os números
oficiais com valor FICAM, mas sem a proveniência (a coluna ``importacao_id`` sai):
subindo de novo, passam por números sem proveniência oficial — reimportar o SARESP/IEE
os apresenta como substituição (antes = depois, pedindo a resposta da D2) e o Ideb/Saeb
os mantém como ``igual``, ainda sem proveniência. Banco LOCAL sem a coluna
``importacoes_indicador.desfazer`` (anterior a ela): a conferência acima lê o plano de
``resumo['desfazer']`` e, se recusar, a mensagem diz para criar a coluna antes de
desfazer (sem ela o app não lista nem desfaz importações; ver a 0034).

O downgrade NÃO recusa por haver importação aplicada: só pelo caso acima. Uma
importação aplicada e não desfeita perde, na descida da 0034, os números de
``indicadores_referencia`` (o ICA, o IEE, a participação) junto com a tabela — por isso
o procedimento de volta (N3) manda desfazer todas antes. O catálogo NÃO é mexido
aqui: as linhas ``ica`` e ``iee`` saem na descida da 0034, depois das tabelas dela (que
ainda apontam para elas neste ponto), e só se nada mais as referencia (ver a 0034).
A coluna ``redes.codigo_municipio_estadual`` (o CODMUN) sai; o ``redes.codigo_ibge`` é
da 0015 e FICA (decisão do dono, 18/10).

O downgrade NORMALIZA, não restaura grafia por grafia: todo ``5_ano`` do SAEB/SARESP
volta como ``anos_iniciais`` — nas linhas E nas receitas, inclusive as que já eram
``5_ano`` antes da 0035, e a receita "Anos Iniciais" volta como "anos_iniciais". É de
propósito: o schema não guarda qual linha a 0035 trocou (e as gravadas depois dela
também são ``5_ano``), então linhas e receitas precisam sair no MESMO vocabulário —
restaurar só a receita ("5_ano" ou "Anos Iniciais") ao lado das linhas normalizadas
faria o robô antigo abrir uma série paralela na coleta seguinte. Nenhum número se perde.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0035_resultados_escolas'
down_revision: Union[str, None] = '0034_indicadores_referencia'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESULTADOS = "resultados_avaliacao"
_UQ_NATURAL = "uq_resultado_natural"
_CK_VALOR = "ck_resultado_valor_ou_motivo"
_FK_IMPORTACAO = "fk_resultados_avaliacao_importacao_id"
_UQ_INEP = "uq_escolas_codigo_inep"

# Avaliações cuja etapa vira a SÉRIE (o IDEB fica de fora de propósito).
_CHAVES_SERIE = ("saeb", "saresp")
_ANOS_INICIAIS = "anos_iniciais"
_QUINTO_ANO = "5_ano"

_DESCRICAO_SARESP_ANTIGA = "Avaliação de rendimento da rede estadual de São Paulo."
_DESCRICAO_SARESP_NOVA = (
    "Sistema de Avaliação de Rendimento Escolar do Estado de São Paulo (SEDUC-SP): rede "
    "estadual e redes municipais que aderem (proficiência em escala SARESP).")
# Espera máxima por um lock (PostgreSQL); vale até o fim da transação (SET LOCAL).
LOCK_TIMEOUT = "5s"


def limitar_espera_por_lock() -> None:
    """PostgreSQL: a migração falha (e reverte) em vez de esperar lock sem prazo."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _etapa_normalizada(etapa) -> str:
    """'anos_iniciais', 'Anos Iniciais', 'anos-iniciais' → 'anos_iniciais' (a mesma
    regra de ``services.avaliacoes._eh_anos_iniciais``, copiada: migração não importa
    o app)."""
    return "_".join(str(etapa or "").replace("-", " ").casefold().split())


def _json(valor):
    """JSON lido por SQL cru: o SQLite devolve texto; o PostgreSQL, o objeto."""
    if isinstance(valor, (str, bytes, bytearray)):
        return json.loads(valor)
    return valor


def _criar_uq_natural() -> None:
    """A MESMA definição da 0022 (os NULOS de etapa/componente/turma como '')."""
    op.create_index(
        _UQ_NATURAL, _RESULTADOS,
        ["avaliacao_id", "edicao", "indicador", "escola_id",
         sa.text("COALESCE(etapa, '')"), sa.text("COALESCE(componente, '')"),
         sa.text("COALESCE(turma, '')")],
        unique=True,
    )


def _ids_serie(bind) -> list[int]:
    consulta = sa.text("SELECT id FROM avaliacoes_externas WHERE chave IN :chaves").bindparams(
        sa.bindparam("chaves", expanding=True))
    return [linha[0] for linha in bind.execute(consulta, {"chaves": list(_CHAVES_SERIE)})]


def _contar_resultados(bind) -> int:
    return bind.execute(sa.text(f"SELECT COUNT(*) FROM {_RESULTADOS}")).scalar_one()


def _trocar_etapa(bind, de: str, para: str) -> None:
    """``etapa`` de → para no SAEB e no SARESP, pela MESMA regra da receita do robô
    (``_etapa_normalizada``): o robô antigo gravava a ``etapa_fixa`` como veio ("Anos
    Iniciais", "anos-iniciais"), e trocar só a grafia exata deixaria essas linhas para
    trás enquanto a receita passa a "5_ano" — a coleta seguinte abriria uma SEGUNDA série
    da mesma escola, edição e componente. PARA se a troca criaria uma chave natural
    repetida: já existe a linha com a etapa de destino (em qualquer grafia) ou duas
    grafias da etapa de origem viram a mesma linha."""
    ids = _ids_serie(bind)
    if not ids:
        return
    linhas = bind.execute(sa.text(
        f"SELECT id, avaliacao_id, edicao, indicador, escola_id, etapa, componente, turma "
        f"FROM {_RESULTADOS} WHERE avaliacao_id IN :ids AND etapa IS NOT NULL "
        "ORDER BY id").bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids}).all()

    def chave(ln) -> tuple:                 # a do uq_resultado_natural, sem a etapa
        return (ln.avaliacao_id, ln.edicao, ln.indicador,
                -1 if ln.escola_id is None else ln.escola_id, ln.componente or "",
                ln.turma or "")

    destino = {chave(ln): ln.id for ln in linhas if _etapa_normalizada(ln.etapa) == para}
    trocar, colisoes = [], []
    for ln in linhas:
        if _etapa_normalizada(ln.etapa) != de:
            continue
        outra = destino.get(chave(ln))
        if outra is not None:
            colisoes.append((ln.id, outra))
        else:
            destino[chave(ln)] = ln.id
            trocar.append(ln.id)
    if colisoes:
        pares = ", ".join(f"{a}×{b}" for a, b in colisoes[:20])
        raise RuntimeError(
            f"0035: trocar a etapa '{de}' por '{para}' no SAEB/SARESP repetiria a chave "
            f"natural de {len(colisoes)} resultado(s) (ids {pares}). Nada foi alterado: "
            "resolva as duplicatas (apagando a série errada) e rode a migração de novo.")
    antes = _contar_resultados(bind)
    atualizar = sa.text(f"UPDATE {_RESULTADOS} SET etapa = :para WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True))
    for inicio in range(0, len(trocar), 500):          # teto de parâmetros do SQLite
        bind.execute(atualizar, {"para": para, "ids": trocar[inicio:inicio + 500]})
    depois = _contar_resultados(bind)
    if antes != depois:                     # defensivo: UPDATE não muda contagem
        raise RuntimeError(f"0035: a troca de etapa mudou o total de resultados "
                           f"({antes} → {depois}).")


def _trocar_etapa_fixa_das_fontes(bind, de: str, para: str) -> None:
    """``etapa_fixa`` de → para na receita do robô (``fontes_avaliacao.mapeamento``) do
    SAEB e do SARESP. JSON: lido e regravado em Python (igual nos dois bancos)."""
    ids = _ids_serie(bind)
    if not ids:
        return
    consulta = sa.text("SELECT id, mapeamento FROM fontes_avaliacao "
                       "WHERE avaliacao_id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True))
    gravar = sa.text("UPDATE fontes_avaliacao SET mapeamento = :m WHERE id = :i").bindparams(
        sa.bindparam("m", type_=sa.JSON()))
    for fonte_id, mapeamento in bind.execute(consulta, {"ids": ids}).all():
        receita = dict(_json(mapeamento) or {})
        if _etapa_normalizada(receita.get("etapa_fixa")) == de:
            receita["etapa_fixa"] = para
            bind.execute(gravar, {"m": receita, "i": fonte_id})


def _chave_resultado(avaliacao_id, edicao, indicador, escola_id, etapa, componente,
                     turma) -> tuple:
    """Chave natural de ``resultados_avaliacao`` (dimensões nulas como '', a regra do
    ``uq_resultado_natural``) — a mesma de ``pipeline_seduc._tupla`` na escola."""
    return (avaliacao_id, edicao, indicador, escola_id, etapa or "", componente or "",
            turma or "")


def _tem_coluna_desfazer(bind) -> bool:
    """False num banco local que aplicou a 0034 ANTES da coluna ``desfazer`` existir
    (branch não publicado; o plano em ``resumo['desfazer']``)."""
    colunas = {c["name"] for c in sa.inspect(bind).get_columns("importacoes_indicador")}
    return "desfazer" in colunas


def _planos_aplicados(bind):
    """(id, plano de desfazer) das importações APLICADAS. O plano fica na coluna
    ``desfazer``; um banco local que aplicou a 0034 ANTES dela existir (branch não
    publicado) o guarda em ``resumo['desfazer']`` — lido como reserva, para a recusa do
    downgrade valer também nesse banco (o reparo dele é criar a coluna; ver a 0034)."""
    campo = "desfazer" if _tem_coluna_desfazer(bind) else "NULL"
    for imp_id, plano, resumo in bind.execute(sa.text(
            f"SELECT id, {campo}, resumo FROM importacoes_indicador WHERE status = :s "
            "ORDER BY id"), {"s": "aplicada"}).all():
        plano = _json(plano)
        if plano is None:
            plano = (_json(resumo) or {}).get("desfazer")
        yield imp_id, plano or {}


def _ausencias_sobre_numero_sem_registro(bind) -> list[tuple[int, int]]:
    """(importação a desfazer, quantos) — AUSÊNCIAS de hoje (``valor`` nulo em
    ``resultados_avaliacao``, que o downgrade apaga) cuja chave, no plano de alguma
    importação APLICADA, tinha ANTES um número SEM proveniência oficial (sem
    ``importacao_id``: a média calculada pelo Constela). Esse número só existe no plano,
    que some com a 0034. Decide pela linha de HOJE, não pelo item isolado: vale também
    em cadeia — a #1 trocou o calculado X pelo oficial Y e a #2 (um arquivo retificado)
    trocou Y por ausência; o ANTES da #2 é a #1, e X está só no plano da #1. A
    importação a desfazer é a que gravou a ausência (o ``importacao_id`` da linha;
    desfeita ela, a linha volta a ter número); sem ele, a que guarda o número."""
    ausentes = {_chave_resultado(*linha[:7]): linha[7] for linha in bind.execute(sa.text(
        "SELECT avaliacao_id, edicao, indicador, escola_id, etapa, componente, turma, "
        f"importacao_id FROM {_RESULTADOS} WHERE valor IS NULL")).all()}
    if not ausentes:
        return []
    perdas: dict[int, set[tuple]] = {}
    for imp_id, plano in _planos_aplicados(bind):
        for item in plano.get("alteradas") or []:
            chave, antes = item.get("chave") or {}, item.get("antes") or {}
            if (chave.get("alvo") != "esc" or antes.get("valor") is None
                    or antes.get("importacao_id") is not None):
                continue
            k = _chave_resultado(*(chave.get(c) for c in (
                "avaliacao_id", "edicao", "indicador", "escola_id", "etapa", "componente",
                "turma")))
            if k in ausentes:
                perdas.setdefault(ausentes[k] or imp_id, set()).add(k)
    return sorted((imp, len(chaves)) for imp, chaves in perdas.items())


def _exigir_inep_unico(bind) -> None:
    repetidos = bind.execute(sa.text(
        "SELECT codigo_inep, COUNT(*) FROM escolas WHERE codigo_inep IS NOT NULL "
        "GROUP BY codigo_inep HAVING COUNT(*) > 1 ORDER BY codigo_inep")).all()
    if repetidos:
        lista = ", ".join(f"{codigo} ({n} escolas)" for codigo, n in repetidos)
        raise RuntimeError(
            "0035: o mesmo código INEP está em mais de uma escola — " + lista + ". "
            "Corrija o cadastro (PATCH /redes/escolas/{id}) e rode a migração de novo; "
            "nada foi alterado.")


def _trocar_descricao_saresp(bind, de: str, para: str) -> None:
    bind.execute(sa.text(
        "UPDATE avaliacoes_externas SET descricao = :para "
        "WHERE chave = :chave AND descricao = :de"),
        {"para": para, "de": de, "chave": "saresp"})


def upgrade() -> None:
    limitar_espera_por_lock()
    bind = op.get_bind()
    _exigir_inep_unico(bind)
    _trocar_etapa(bind, _ANOS_INICIAIS, _QUINTO_ANO)
    _trocar_etapa_fixa_das_fontes(bind, _ANOS_INICIAIS, _QUINTO_ANO)

    # O batch do SQLite recria a tabela e perderia o índice de expressão: sai
    # antes e volta depois, nos dois bancos (comportamento igual e conferível).
    op.drop_index(_UQ_NATURAL, table_name=_RESULTADOS)
    with op.batch_alter_table(_RESULTADOS) as tabela:
        tabela.add_column(sa.Column("motivo_ausencia", sa.String(length=40), nullable=True))
        tabela.add_column(sa.Column("importacao_id", sa.Integer(), nullable=True))
        tabela.create_foreign_key(_FK_IMPORTACAO, "importacoes_indicador",
                                  ["importacao_id"], ["id"], ondelete="SET NULL")
        tabela.alter_column("valor", existing_type=sa.Float(), nullable=True)
        tabela.create_check_constraint(
            _CK_VALOR, "valor IS NOT NULL OR motivo_ausencia IS NOT NULL")
    _criar_uq_natural()

    op.create_index(_UQ_INEP, "escolas", ["codigo_inep"], unique=True,
                    sqlite_where=sa.text("codigo_inep IS NOT NULL"),
                    postgresql_where=sa.text("codigo_inep IS NOT NULL"))
    with op.batch_alter_table("redes") as tabela:
        tabela.add_column(sa.Column("codigo_municipio_estadual", sa.String(length=8),
                                    nullable=True))
    _trocar_descricao_saresp(bind, _DESCRICAO_SARESP_ANTIGA, _DESCRICAO_SARESP_NOVA)


def downgrade() -> None:
    limitar_espera_por_lock()
    bind = op.get_bind()
    perdas = _ausencias_sobre_numero_sem_registro(bind)
    if perdas:
        lista = ", ".join(f"#{imp} ({n} número(s))" for imp, n in perdas)
        como = ("Desfaça antes essas importações (o desfazer devolve o número anterior) e "
                "rode o downgrade de novo")
        if not _tem_coluna_desfazer(bind):
            # Sem a coluna o app não lista nem desfaz (coluna inexistente): mandar desfazer
            # seria um beco sem saída. Criada a coluna, o desfazer lê o plano do resumo.
            como = ("Este banco não tem a coluna importacoes_indicador.desfazer (banco local "
                    "anterior a ela) e, sem ela, o app não lista nem desfaz importações: crie-a "
                    "antes — ALTER TABLE importacoes_indicador ADD COLUMN desfazer JSON (o "
                    "schema fica igual ao da 0034 e o desfazer lê o plano antigo do resumo; ver "
                    "a 0034) —, desfaça essas importações e, se ainda precisar, rode o "
                    "downgrade de novo")
        raise RuntimeError(
            "0035 (downgrade): importação oficial aplicada deixou como ausência números que, "
            "antes dela (ou de uma anterior na mesma linha), NÃO tinham proveniência oficial "
            f"(ex.: a média calculada pelo Constela) — {lista}. O downgrade apagaria as "
            "ausências e esses números não voltariam (só existem no plano de desfazer, que "
            f"a 0034 leva junto). {como}; nada foi alterado.")
    _trocar_descricao_saresp(bind, _DESCRICAO_SARESP_NOVA, _DESCRICAO_SARESP_ANTIGA)
    with op.batch_alter_table("redes") as tabela:
        tabela.drop_column("codigo_municipio_estadual")
    op.drop_index(_UQ_INEP, table_name="escolas")

    # Ausências (valor nulo) não cabem no schema antigo (valor NOT NULL): saem
    # ANTES — registros de "sem resultado" da fonte oficial, reimportáveis (a que
    # escondia um número sem registro oficial parou a migração lá em cima).
    bind.execute(sa.text(f"DELETE FROM {_RESULTADOS} WHERE valor IS NULL"))
    _trocar_etapa(bind, _QUINTO_ANO, _ANOS_INICIAIS)
    _trocar_etapa_fixa_das_fontes(bind, _QUINTO_ANO, _ANOS_INICIAIS)

    op.drop_index(_UQ_NATURAL, table_name=_RESULTADOS)
    with op.batch_alter_table(_RESULTADOS) as tabela:
        tabela.drop_constraint(_CK_VALOR, type_="check")
        tabela.drop_constraint(_FK_IMPORTACAO, type_="foreignkey")
        tabela.alter_column("valor", existing_type=sa.Float(), nullable=False)
        tabela.drop_column("importacao_id")
        tabela.drop_column("motivo_ausencia")
    _criar_uq_natural()
