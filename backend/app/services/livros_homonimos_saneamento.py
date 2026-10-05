"""Saneamento das duplicatas de ``Leitura`` nos dois títulos homônimos do
catálogo do Elefante.

POR QUE ISTO EXISTE. O catálogo oficial tem 752 livros e EXATAMENTE dois
títulos repetidos — "Cadê?" (ids 2356/nível B, 63 palavras, e 4799/nível BB, 32
palavras) e "Chapeuzinho Vermelho" (2304/I, 579 palavras, e 5539/K, 400
palavras). São obras distintas, e ``_IndiceLivros.resolver`` já faz a coisa
certa: quando o título é ambíguo, o NÍVEL decide. Nada disso é defeito.

O defeito é histórico. Antes de a escola ter o vínculo com o catálogo, existia
UMA linha de ``Livro`` por título (``origem_nivel="legado"``), e ela recebeu
leitura das DUAS obras. Quando a reconciliação criou a segunda linha
(``origem_nivel="fonte"``, com o ``elefante_id`` do catálogo), a leitura nova
passou a ir para a linha correta — e a antiga ficou onde estava. Como
``uq_leitura_unica`` é (aluno, livro) e os ``livro_id`` diferem, nada barrou: a
MESMA leitura passou a existir duas vezes, e ``livros_unicos`` conta as duas.

A EVIDÊNCIA que autoriza remover. Só o par cujo instante coincide ao SEGUNDO e
cujo tempo de leitura é o MESMO. Uma criança não lê duas obras diferentes no
mesmo segundo pela mesma duração: o par é anômalo por construção. Pares com
instantes distintos são o caso legítimo — a criança leu as duas obras — e este
serviço NÃO os toca.

QUAL LINHA SAI. A do livro ``legado``. O que sustenta a escolha é a identidade
de catálogo: a linha ``fonte`` carrega o ``elefante_id`` reconciliado, o nível e
o ``word_count`` oficiais; a ``legado`` nasceu sem vínculo e é a que misturou as
duas obras. LIMITAÇÃO HONESTA: ``Leitura.nivel_codigo`` é internamente coerente
nas DUAS linhas (cada uma guarda o nível do seu próprio livro), então ele NÃO
corrobora qual das duas está errada — ele só espelha o livro em que a linha foi
pendurada. Quem aprovar a execução precisa saber disso.

EVENTOS NÃO SÃO TOCADOS. ``chave_evento`` hasheia (plataforma, tipo, aluno,
título, MINUTO) e NÃO inclui ``livro_id``: para um par homônimo no mesmo minuto
as duas chaves colidem, e ``uq_evento_natural`` deixa passar UM evento só.
Medido: 195 dos 196 pares têm exatamente um evento, pendurado no livro legado.
Esse evento é a única prova documental da leitura e alimenta
``leituras_restauracao`` — removê-lo destruiria evidência. O espelho de eventos
é append-only por projeto (existe justamente para as linhas que a §35 descarta),
então um evento apontando um livro sem ``Leitura`` é consistente com o desenho.

REVERSIBILIDADE. ``Leitura`` não tem exclusão lógica; a remoção é física, como
já faz ``alunos_fusao.fundir_par`` com a leitura repetida. Não existe rollback
automático: o que permite reconstruir a linha é o registro de auditoria, que
guarda TODOS os campos removidos. É uma limitação da arquitetura atual, não uma
escolha deste módulo — e está dita aqui para não ser descoberta depois.

O QUE ESTE SERVIÇO NÃO FAZ, e por quê:

* NÃO toca os pares de instante distinto (130 na rede, medidos). Ali a criança
  leu as DUAS obras, em momentos diferentes: é dado legítimo, não duplicata.
* NÃO migra a ``Leitura`` do legado para o fonte. Migrar exigiria decidir, para
  cada linha SEM par, a qual das duas obras ela pertence — e essa evidência não
  existe: ``Leitura.nivel_codigo`` é internamente coerente nas duas linhas (cada
  uma guarda o nível do SEU livro), então ele espelha o livro em que a linha foi
  pendurada e não prova nada sobre a obra de origem.
* NÃO altera ``_IndiceLivros.resolver``. Ele está correto: quando o título é
  ambíguo, o nível decide — e o docstring de ``Catalogo.buscar`` já dizia que
  existem exatamente dois títulos nessa condição.
* NÃO altera o catálogo. Os quatro registros são obras distintas de verdade: as
  contagens de palavras diferem (63 × 32 e 579 × 400).
* NÃO age nas escolas cujas duas linhas nasceram ``fonte`` (medido: escolas 8 e
  17, criadas já reconciliadas). Lá não há padrão legado+fonte e, coerentemente,
  ZERO duplicata provada. ``auditar`` nem as considera candidatas — a regra é a
  evidência, não uma lista de escolas.

GOVERNANÇA. Mesma régua de ``leituras_restauracao``: motivo escrito, auditoria
item a item com o de/para, transação única, e este módulo NÃO commita — quem
chama confirma.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, EventoAluno, Leitura, Livro
from app.services import dificuldade_livro
from app.services.audit import registrar

ACAO_ITEM = "leitura.duplicata_homonima_removida"
ACAO_LOTE = "livros.saneamento_homonimos"

MOTIVO_MINIMO = 10

# Classificações. Só a primeira autoriza remoção.
PROVADA = "DUPLICATA_PROVADA"
PROVAVEL = "DUPLICATA_PROVAVEL_1min"
DIFERENTES = "DIFERENTES"
INDETERMINADO = "INDETERMINADO"


class SaneamentoInvalido(Exception):
    """A operação inteira é recusada. ``detalhe`` aponta o caso."""

    def __init__(self, mensagem: str, detalhe: dict | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.detalhe = detalhe or {}


@dataclass(frozen=True)
class Evidencia:
    """Tudo o que sustenta (ou derruba) UMA remoção. É o que vai para a
    auditoria, inteiro — é com isto que se reconstrói a linha removida."""

    escola_id: int
    aluno_id: int
    aluno_nome: str
    titulo_normalizado: str
    # lado LEGADO (o que sai, quando autorizado)
    legado_livro_id: int
    legado_livro_titulo: str
    legado_nivel: str | None
    legado_origem: str | None
    legado_elefante_id: int | None
    legado_leitura_id: int
    legado_data: datetime
    legado_tempo: int | None
    legado_leitura_nivel: str | None
    # lado FONTE (o que fica)
    fonte_livro_id: int
    fonte_livro_titulo: str
    fonte_nivel: str | None
    fonte_origem: str | None
    fonte_elefante_id: int | None
    fonte_leitura_id: int
    fonte_data: datetime
    fonte_tempo: int | None
    fonte_leitura_nivel: str | None
    # comparação
    delta_segundos: float
    delta_tempo: int | None
    eventos_no_legado: int
    eventos_no_fonte: int
    classificacao: str
    # por que NÃO autoriza, quando for o caso
    recusa: str = ""


def titulos_auditados() -> dict[str, dict[int, str]]:
    """Os títulos homônimos LIDOS DO CATÁLOGO, não escritos à mão.

    Se o catálogo mudar (um título homônimo novo, ou um deles deixar de ser
    ambíguo), isto muda com ele — e o serviço não passa a agir sobre um par que
    ninguém auditou, porque a ambiguidade é justamente o que define o escopo.
    """
    cat = dificuldade_livro.catalogo()
    grupos: dict[str, dict[int, str]] = {}
    for meta in cat.por_id.values():
        chave = dificuldade_livro.normalizar_titulo(meta.titulo)
        grupos.setdefault(chave, {})[meta.id] = meta.nivel
    return {k: v for k, v in grupos.items() if len(v) > 1}


def _sem_tz(momento: datetime) -> datetime:
    """``Leitura.data`` é naive (a data do relatório é naive)."""
    return momento.replace(tzinfo=None) if momento.tzinfo is not None else momento


def _json(valor):
    """``LogAuditoria.detalhes`` é JSON: datetime/date viram texto ISO.

    Sem isto o INSERT do log estoura com ``TypeError`` no flush e derruba a
    operação INTEIRA — o que é o comportamento correto, mas pelo motivo errado.
    """
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json(v) for v in valor]
    if hasattr(valor, "isoformat"):          # date
        return valor.isoformat()
    return valor


def _classificar(delta_s: float | None, delta_tempo: int | None) -> str:
    """As quatro classes são mutuamente exclusivas e dizem o que de fato houve.

    O caso ``delta_s == 0`` com tempos DIFERENTES não é "provável": o instante
    bate mas a duração não, e isso tem duas leituras possíveis — a plataforma
    revisou o tempo, ou são obras distintas abertas no mesmo segundo. Sem como
    decidir, é INDETERMINADO, e indeterminado não se toca.
    """
    if delta_s is None or delta_tempo is None:
        return INDETERMINADO
    if delta_s == 0:
        return PROVADA if delta_tempo == 0 else INDETERMINADO
    if delta_s <= 60:
        return PROVAVEL
    return DIFERENTES


def auditar(db: Session, escola_id: int) -> list[Evidencia]:
    """Levanta TODOS os pares homônimos da escola e classifica cada um.

    Só leitura. Não decide nada: devolve a evidência, inclusive dos casos que
    não autorizam remoção — é por isso que o dry-run consegue mostrar o que
    ficou de fora e por quê.
    """
    ambiguos = titulos_auditados()
    livros = list(db.execute(
        select(Livro).where(Livro.escola_id == escola_id)).scalars())
    por_titulo: dict[str, list[Livro]] = {}
    for livro in livros:
        chave = dificuldade_livro.normalizar_titulo(livro.titulo)
        if chave in ambiguos:
            por_titulo.setdefault(chave, []).append(livro)

    saida: list[Evidencia] = []
    for chave, grupo in sorted(por_titulo.items()):
        if len(grupo) < 2:
            continue
        legados = [lv for lv in grupo if lv.origem_nivel == "legado"]
        fontes = [lv for lv in grupo if lv.origem_nivel == "fonte"]
        # Sem um legado E um fonte não há o padrão: é o caso das escolas que
        # nasceram já reconciliadas (as duas linhas `fonte`). Nada a sanear.
        if len(legados) != 1 or len(fontes) != 1:
            continue
        legado, fonte = legados[0], fontes[0]
        leit_legado = {l.aluno_id: l for l in db.execute(
            select(Leitura).where(Leitura.livro_id == legado.id)).scalars()}
        leit_fonte = {l.aluno_id: l for l in db.execute(
            select(Leitura).where(Leitura.livro_id == fonte.id)).scalars()}
        for aluno_id in sorted(set(leit_legado) & set(leit_fonte)):
            a, b = leit_legado[aluno_id], leit_fonte[aluno_id]
            da, dbt = _sem_tz(a.data), _sem_tz(b.data)
            delta_s = abs((da - dbt).total_seconds()) if da and dbt else None
            ta = a.tempo_leitura_min if a.tempo_leitura_min is not None else None
            tb = b.tempo_leitura_min if b.tempo_leitura_min is not None else None
            delta_t = (abs(ta - tb) if (ta is not None and tb is not None) else None)
            aluno = db.get(Aluno, aluno_id)
            n_ev_legado = len(list(db.execute(select(EventoAluno.id).where(
                EventoAluno.aluno_id == aluno_id,
                EventoAluno.livro_id == legado.id)).scalars()))
            n_ev_fonte = len(list(db.execute(select(EventoAluno.id).where(
                EventoAluno.aluno_id == aluno_id,
                EventoAluno.livro_id == fonte.id)).scalars()))
            saida.append(Evidencia(
                escola_id=escola_id, aluno_id=aluno_id,
                aluno_nome=(aluno.nome if aluno else ""),
                titulo_normalizado=chave,
                legado_livro_id=legado.id, legado_livro_titulo=legado.titulo,
                legado_nivel=legado.nivel_codigo, legado_origem=legado.origem_nivel,
                legado_elefante_id=legado.elefante_id,
                legado_leitura_id=a.id, legado_data=da, legado_tempo=ta,
                legado_leitura_nivel=a.nivel_codigo,
                fonte_livro_id=fonte.id, fonte_livro_titulo=fonte.titulo,
                fonte_nivel=fonte.nivel_codigo, fonte_origem=fonte.origem_nivel,
                fonte_elefante_id=fonte.elefante_id,
                fonte_leitura_id=b.id, fonte_data=dbt, fonte_tempo=tb,
                fonte_leitura_nivel=b.nivel_codigo,
                delta_segundos=(delta_s if delta_s is not None else -1.0),
                delta_tempo=delta_t,
                eventos_no_legado=n_ev_legado, eventos_no_fonte=n_ev_fonte,
                classificacao=_classificar(delta_s, delta_t)))
    return saida


def validar(ev: Evidencia, *, ambiguos: dict[str, dict[int, str]] | None = None
            ) -> str:
    """Devolve "" quando a remoção é autorizada, ou o motivo da recusa.

    As oito condições são conferidas uma a uma, de propósito: a mensagem diz
    QUAL falhou, e é ela que vai para o relatório do dry-run.
    """
    ambiguos = ambiguos if ambiguos is not None else titulos_auditados()
    if ev.classificacao != PROVADA:
        return (f"classificação {ev.classificacao}: só {PROVADA} autoriza "
                "remoção — instantes distintos são o caso legítimo de duas obras.")
    if ev.delta_segundos != 0:
        return f"o instante difere em {ev.delta_segundos} s; exige-se 0."
    if ev.delta_tempo != 0:
        return (f"o tempo de leitura difere em {ev.delta_tempo} min; exige-se "
                "o mesmo tempo nas duas linhas.")
    if ev.legado_origem != "legado":
        return (f"a linha que sairia tem origem {ev.legado_origem!r}, não "
                "'legado' — fora do padrão auditado.")
    if ev.fonte_origem != "fonte":
        return (f"a linha que ficaria tem origem {ev.fonte_origem!r}, não "
                "'fonte' — fora do padrão auditado.")
    if ev.titulo_normalizado not in ambiguos:
        return (f"o título {ev.titulo_normalizado!r} não é um dos homônimos do "
                "catálogo oficial.")
    pares = ambiguos[ev.titulo_normalizado]
    for lado, eid in (("legado", ev.legado_elefante_id),
                      ("fonte", ev.fonte_elefante_id)):
        if eid is not None and eid not in pares:
            return (f"o elefante_id {eid} do lado {lado} não é uma das entradas "
                    f"homônimas do catálogo ({sorted(pares)}).")
    if ev.legado_livro_id == ev.fonte_livro_id:
        return "as duas linhas apontam o MESMO livro; não há par."
    if ev.legado_leitura_id == ev.fonte_leitura_id:
        return "as duas leituras são a MESMA linha; não há par."
    return ""


def _plano(db: Session, escolas: list[int], motivo: str) -> dict:
    if not (motivo or "").strip() or len(motivo.strip()) < MOTIVO_MINIMO:
        raise SaneamentoInvalido(
            "Remover linha de histórico exige motivo escrito, com pelo menos "
            f"{MOTIVO_MINIMO} caracteres — é o que a auditoria vai mostrar "
            "para quem perguntar depois.")
    if not escolas:
        raise SaneamentoInvalido("Nenhuma escola foi informada.")
    ambiguos = titulos_auditados()
    autorizados: list[Evidencia] = []
    recusados: list[Evidencia] = []
    for escola_id in escolas:
        if db.get(Escola, escola_id) is None:
            raise SaneamentoInvalido(f"A escola {escola_id} não existe.")
        for ev in auditar(db, escola_id):
            recusa = validar(ev, ambiguos=ambiguos)
            if recusa:
                recusados.append(Evidencia(**{**asdict(ev), "recusa": recusa}))
            else:
                autorizados.append(ev)
    # Uma leitura não pode sair duas vezes no mesmo lote.
    vistas: set[int] = set()
    for ev in autorizados:
        if ev.legado_leitura_id in vistas:
            raise SaneamentoInvalido(
                f"A leitura {ev.legado_leitura_id} aparece duas vezes no lote.",
                {"leitura_id": ev.legado_leitura_id})
        vistas.add(ev.legado_leitura_id)
    por_escola: dict[int, dict] = {}
    for ev in autorizados:
        d = por_escola.setdefault(ev.escola_id, {
            "remocoes": 0, "alunos": set(), "minutos": 0, "titulos": set()})
        d["remocoes"] += 1
        d["alunos"].add(ev.aluno_id)
        d["minutos"] += ev.legado_tempo or 0
        d["titulos"].add(ev.titulo_normalizado)
    classes: dict[str, int] = {}
    for ev in autorizados + recusados:
        classes[ev.classificacao] = classes.get(ev.classificacao, 0) + 1
    return {
        "escolas": list(escolas),
        "motivo": motivo.strip(),
        "autorizados": autorizados,
        "recusados": recusados,
        "classes": classes,
        "por_escola": {
            str(k): {"remocoes": v["remocoes"], "alunos": sorted(v["alunos"]),
                     "minutos": v["minutos"], "titulos": sorted(v["titulos"])}
            for k, v in sorted(por_escola.items())},
        "total_remocoes": len(autorizados),
        "total_recusados": len(recusados),
    }


def dry_run(db: Session, escolas: list[int], motivo: str) -> dict:
    """O ensaio. Mesma validação da execução, nenhuma escrita.

    Devolve o plano inteiro — o que sairia e o que foi recusado, com o motivo
    de cada recusa. Chamar isto nunca altera estado.
    """
    plano = _plano(db, escolas, motivo)
    return {**plano, "dry_run": True,
            "autorizados": [asdict(e) for e in plano["autorizados"]],
            "recusados": [asdict(e) for e in plano["recusados"]]}


def executar(db: Session, escolas: list[int], usuario_id: int | None,
             motivo: str) -> dict:
    """Remove as duplicatas autorizadas. Tudo ou nada; NÃO commita.

    Confere o lote inteiro ANTES de apagar qualquer linha. Cada remoção grava
    a evidência COMPLETA em ``logs_auditoria`` — é o que permite reconstruir a
    linha, já que ``Leitura`` não tem exclusão lógica. Eventos não são tocados.
    """
    plano = _plano(db, escolas, motivo)
    removidas: list[dict] = []
    for ev in plano["autorizados"]:
        leitura = db.get(Leitura, ev.legado_leitura_id)
        if leitura is None:          # pragma: no cover - conferido no plano
            raise SaneamentoInvalido(
                f"A leitura {ev.legado_leitura_id} desapareceu durante a "
                "operação. Nada foi aplicado.")
        # Retrato COMPLETO da linha antes de apagar: é a única reconstrução
        # possível depois (não há soft delete em Leitura).
        linha_removida = {c.name: getattr(leitura, c.name)
                          for c in Leitura.__table__.columns}
        db.delete(leitura)
        detalhes = {
            "regra": "duplicata homônima: mesmo aluno, mesmo título ambíguo do "
                     "catálogo, instante idêntico ao segundo e mesmo tempo de "
                     "leitura; sai a linha do livro de origem 'legado'",
            "motivo": plano["motivo"],
            "evidencia": _json(asdict(ev)),
            "leitura_removida": _json(linha_removida),
            "eventos_preservados": {
                "no_livro_legado": ev.eventos_no_legado,
                "no_livro_fonte": ev.eventos_no_fonte,
                "tratamento": "nenhum evento é removido ou migrado: a "
                              "chave_natural não inclui livro_id, então o par "
                              "homônimo compartilha um único evento, que é a "
                              "prova documental da leitura",
            },
        }
        registrar(db, ACAO_ITEM, escola_id=ev.escola_id, usuario_id=usuario_id,
                  entidade="leitura", entidade_id=ev.legado_leitura_id,
                  detalhes=detalhes)
        removidas.append(detalhes)

    resumo = {
        "escolas": plano["escolas"],
        "leituras_removidas": plano["total_remocoes"],
        "recusados": plano["total_recusados"],
        "classes": plano["classes"],
        "por_escola": plano["por_escola"],
        "minutos_corrigidos": sum((e.legado_tempo or 0)
                                  for e in plano["autorizados"]),
        "alunos": sorted({e.aluno_id for e in plano["autorizados"]}),
    }
    for escola_id in plano["escolas"]:
        registrar(db, ACAO_LOTE, escola_id=escola_id, usuario_id=usuario_id,
                  entidade="escola", entidade_id=escola_id,
                  detalhes={**resumo, "motivo": plano["motivo"]})
    db.flush()
    return {**resumo, "dry_run": False, "itens": removidas}
