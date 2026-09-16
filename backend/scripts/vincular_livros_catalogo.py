"""Vínculo dos livros ANTIGOS ao catálogo oficial do Elefante (identidade oficial)
e congelamento OPCIONAL do nível das leituras antigas.

Por que existe
--------------
A migração ``0030_livro_identidade_oficial`` acrescenta ``elefante_id``,
``nivel_fonte``, ``origem_nivel`` e ``word_count`` em ``livros`` SEM backfill.
Livros criados antes dela casam só pelo título. A sincronização vincula aos
poucos o que ela reencontra; este script faz o vínculo em lote, com relatório
prévio, para o acervo inteiro (inclusive livros que nenhum aluno releu).

Garantias
---------
* DRY-RUN POR PADRÃO: só lista, por escola, os livros vinculáveis, os ambíguos,
  os fora do catálogo e as divergências de nível. Nada é gravado sem ``--aplicar``.
* NUNCA muda ``nivel_codigo`` (o nível efetivo, que pontua): grava só
  ``elefante_id``, ``word_count`` (se faltar) e ``nivel_fonte``. A divergência
  fica listada para o Admin Global decidir — ou para a próxima sincronização
  reconciliar pela regra de origem do nível.
* NÃO recalcula notas.
* Auditoria AGREGADA: uma linha ``livro.vinculado_catalogo`` por escola (não uma
  por livro).
* Ambíguo não é vinculado: título presente em mais de um nível oficial sem casar
  o nível local, id oficial já usado por outro livro da escola ou dois livros da
  escola disputando o mesmo id.

``--congelar-niveis`` (OPCIONAL) — nível congelado das leituras antigas
-----------------------------------------------------------------------
A migração ``0031_leitura_nivel_congelado`` acrescenta ``leituras.nivel_codigo``
e ``leituras.catalogo_versao`` SEM backfill. Leitura com ``nivel_codigo`` nulo
vale pelo nível ATUAL do livro (``coalesce(Leitura.nivel_codigo,
Livro.nivel_codigo)``) — o mesmo número de sempre. Este passo grava nessas linhas
exatamente esse valor, o que **não muda nenhum número hoje**: só tira o histórico
da dependência do catálogo vigente, para que uma correção de nível futura valha
das PRÓXIMAS leituras em diante.

* **OPCIONAL**: sem a flag o script se comporta exatamente como antes. Nada no
  produto exige o congelamento — ele só antecipa a proteção do passado.
* **IDEMPOTENTE**: toca SÓ leituras com ``nivel_codigo`` NULO — o mesmo corte do
  ``coalesce`` do motor (o ``UPDATE`` repete a condição). Rodar de novo congela 0
  e não reescreve nada já congelado. Nível congelado VAZIO conta como congelado
  ("desconhecido", 0 ponto): regravá-lo mudaria o valor da leitura.
* **NÃO recalcula notas** e não muda nível de livro: o valor gravado é o que a
  leitura já vale hoje.
* Leitura cujo livro está SEM nível fica como está (nulo): congelar vazio não
  guarda informação e o fallback já dá o mesmo resultado.
* ``catalogo_versao`` recebe a versão do catálogo VIGENTE no congelamento — é ela
  que testemunha o valor congelado. Não é uma reconstrução do passado (o extrato
  que resolveu aquele nível na época não é recuperável, e inventá-lo falsearia a
  auditoria); a auditoria agregada registra a data e a origem.
* Auditoria AGREGADA: uma linha ``leitura.nivel_congelado`` por escola, com a
  contagem por nível.

Como executar
-------------
    python -m scripts.vincular_livros_catalogo                 # dry-run, todas as escolas
    python -m scripts.vincular_livros_catalogo --escola 42     # dry-run, só a escola 42
    python -m scripts.vincular_livros_catalogo --aplicar       # grava os vínculos
    python -m scripts.vincular_livros_catalogo --congelar-niveis            # dry-run do congelamento
    python -m scripts.vincular_livros_catalogo --congelar-niveis --aplicar  # grava o congelamento
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Escola, Leitura, Livro  # noqa: E402
from app.services import dificuldade_livro  # noqa: E402
from app.services.audit import registrar  # noqa: E402


@dataclass
class RelatorioEscola:
    escola_id: int
    nome: str
    vinculaveis: list = field(default_factory=list)       # [(Livro, LivroCatalogo)]
    ambiguos: list = field(default_factory=list)          # [(Livro, motivo)]
    fora_do_catalogo: list = field(default_factory=list)  # [Livro]
    divergencias: list = field(default_factory=list)      # [(Livro, nível oficial)]
    ja_vinculados: int = 0


def analisar_escola(db, escola_id: int, nome: str, cat=None) -> RelatorioEscola:
    """Classifica o acervo da escola SEM gravar nada."""
    cat = cat if cat is not None else dificuldade_livro.catalogo()
    relatorio = RelatorioEscola(escola_id=escola_id, nome=nome)
    livros = db.execute(select(Livro).where(Livro.escola_id == escola_id)
                        .order_by(Livro.id)).scalars().all()
    usados = {l.elefante_id: l for l in livros if l.elefante_id is not None}
    propostos: dict[int, list] = {}
    candidatos: list = []
    for livro in livros:
        if livro.elefante_id is not None:
            relatorio.ja_vinculados += 1
            meta = cat.por_id.get(livro.elefante_id)
            oficial = meta.nivel if meta is not None else livro.nivel_fonte
            if oficial and oficial != livro.nivel_codigo:
                relatorio.divergencias.append((livro, oficial))
            continue
        chave = dificuldade_livro.normalizar_titulo(livro.titulo)
        mesmos = cat.por_titulo.get(chave) or []
        exato = next((m for m in mesmos if m.nivel == livro.nivel_codigo), None)
        if exato is not None:
            meta = exato
        elif len(mesmos) == 1:
            meta = mesmos[0]
        elif mesmos:
            niveis = ", ".join(sorted(m.nivel for m in mesmos))
            relatorio.ambiguos.append(
                (livro, f"título em {len(mesmos)} níveis oficiais ({niveis}); "
                        f"nível local {livro.nivel_codigo} não casa"))
            continue
        else:
            relatorio.fora_do_catalogo.append(livro)
            continue
        if meta.id in usados:
            relatorio.ambiguos.append(
                (livro, f"id oficial {meta.id} já vinculado ao livro {usados[meta.id].id}"))
            continue
        propostos.setdefault(meta.id, []).append(livro)
        candidatos.append((livro, meta))
    for livro, meta in candidatos:
        if len(propostos[meta.id]) > 1:
            relatorio.ambiguos.append(
                (livro, f"{len(propostos[meta.id])} livros da escola casam o id oficial {meta.id}"))
            continue
        relatorio.vinculaveis.append((livro, meta))
        if meta.nivel != livro.nivel_codigo:
            relatorio.divergencias.append((livro, meta.nivel))
    return relatorio


def aplicar(db, relatorio: RelatorioEscola) -> int:
    """Grava os vínculos (id oficial, wordCount, nível da fonte) — NUNCA o nível
    efetivo — com UMA auditoria agregada. Devolve quantos livros vinculou."""
    vinculados = []
    for livro, meta in relatorio.vinculaveis:
        livro.elefante_id = meta.id
        if livro.word_count is None:
            livro.word_count = meta.word_count
        livro.nivel_fonte = meta.nivel
        vinculados.append({"livro_id": livro.id, "elefante_id": meta.id,
                           "nivel_efetivo": livro.nivel_codigo, "nivel_fonte": meta.nivel})
    if vinculados:
        registrar(db, "livro.vinculado_catalogo", escola_id=relatorio.escola_id,
                  entidade="escola", entidade_id=relatorio.escola_id,
                  detalhes={"origem": "scripts.vincular_livros_catalogo",
                            "qtd": len(vinculados),
                            "divergentes": sum(1 for v in vinculados
                                               if v["nivel_efetivo"] != v["nivel_fonte"]),
                            "livros": vinculados[:1000]})
    db.commit()
    return len(vinculados)


def _imprimir(relatorio: RelatorioEscola, limite: int = 50) -> None:
    print(f"\nEscola {relatorio.escola_id} — {relatorio.nome}")
    print(f"  já vinculados: {relatorio.ja_vinculados}")
    print(f"  vinculáveis: {len(relatorio.vinculaveis)}")
    for livro, meta in relatorio.vinculaveis[:limite]:
        print(f"    - [{livro.id}] {livro.titulo} ({livro.nivel_codigo}) → id {meta.id} ({meta.nivel})")
    print(f"  ambíguos (não vinculados): {len(relatorio.ambiguos)}")
    for livro, motivo in relatorio.ambiguos[:limite]:
        print(f"    - [{livro.id}] {livro.titulo} ({livro.nivel_codigo}): {motivo}")
    print(f"  fora do catálogo: {len(relatorio.fora_do_catalogo)}")
    for livro in relatorio.fora_do_catalogo[:limite]:
        print(f"    - [{livro.id}] {livro.titulo} ({livro.nivel_codigo})")
    print(f"  divergências de nível (efetivo ≠ oficial): {len(relatorio.divergencias)}")
    for livro, oficial in relatorio.divergencias[:limite]:
        print(f"    - [{livro.id}] {livro.titulo}: efetivo {livro.nivel_codigo}, oficial {oficial}")


# ---------------------------------------------------------------------------
# Congelamento do nível da leitura (opcional, idempotente) — ver o cabeçalho
# ---------------------------------------------------------------------------

_LOTE = 500   # ids por UPDATE (não estoura o limite de parâmetros do driver)


@dataclass
class RelatorioCongelamento:
    escola_id: int
    nome: str
    por_nivel: dict = field(default_factory=dict)   # nível → [leitura_id, ...]
    ja_congeladas: int = 0
    sem_nivel_no_livro: int = 0

    @property
    def congelaveis(self) -> int:
        return sum(len(ids) for ids in self.por_nivel.values())


def analisar_congelamento(db, escola_id: int, nome: str) -> RelatorioCongelamento:
    """Classifica as leituras da escola SEM gravar nada: quais têm nível a
    congelar (e qual nível), quais já estão congeladas e quais ficam de fora
    (livro sem nível).

    "Já congelada" é EXATAMENTE ``nivel_codigo IS NOT NULL`` — o mesmo corte do
    ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)`` que o motor usa, e não
    "tem texto". Nível congelado VAZIO é um congelamento válido ("nível
    desconhecido", 0 ponto — a régua ignora item sem letra); tratá-lo como
    ausente e regravá-lo com o nível do livro MUDARIA o valor da leitura, que é
    justamente o que este backfill promete nunca fazer. (Chega a existir:
    `aplicar_ao_historico` num livro legado sem nível grava "" na leitura.)"""
    relatorio = RelatorioCongelamento(escola_id=escola_id, nome=nome)
    linhas = db.execute(
        select(Leitura.id, Leitura.nivel_codigo, Livro.nivel_codigo)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.escola_id == escola_id)
        .order_by(Leitura.id)
    ).all()
    for leitura_id, congelado, nivel_do_livro in linhas:
        if congelado is not None:
            relatorio.ja_congeladas += 1
            continue
        nivel = (nivel_do_livro or "").strip().upper()
        if not nivel:
            # Livro sem nível: congelar vazio não guarda informação e o fallback
            # (coalesce) já devolve exatamente o mesmo — nível desconhecido, 0 pontos.
            relatorio.sem_nivel_no_livro += 1
            continue
        relatorio.por_nivel.setdefault(nivel, []).append(leitura_id)
    return relatorio


def congelar(db, relatorio: RelatorioCongelamento) -> int:
    """Grava o nível congelado (= o nível ATUAL do livro, o valor que a leitura
    já vale hoje) com UMA auditoria agregada. Devolve quantas leituras congelou.

    O ``UPDATE`` repete a condição de "ainda não congelada" (``IS NULL``, o mesmo
    corte do ``coalesce`` do motor): rodar duas vezes — ou rodar em paralelo com
    uma sincronização/ação do Admin Global que já congelou a linha — nunca
    sobrescreve um nível congelado antes."""
    versao = dificuldade_livro.versao_catalogo().get("versao")
    total = 0
    for nivel, ids in sorted(relatorio.por_nivel.items()):
        for inicio in range(0, len(ids), _LOTE):
            lote = ids[inicio:inicio + _LOTE]
            total += db.execute(
                update(Leitura)
                .where(Leitura.id.in_(lote), Leitura.nivel_codigo.is_(None))
                .values(nivel_codigo=nivel, catalogo_versao=versao)
            ).rowcount or 0
    if total:
        registrar(db, "leitura.nivel_congelado", escola_id=relatorio.escola_id,
                  entidade="escola", entidade_id=relatorio.escola_id,
                  detalhes={"origem": "scripts.vincular_livros_catalogo --congelar-niveis",
                            "qtd": total, "catalogo_versao": versao,
                            "por_nivel": {n: len(ids) for n, ids in sorted(relatorio.por_nivel.items())},
                            "sem_nivel_no_livro": relatorio.sem_nivel_no_livro,
                            "nota": "nível congelado = nível ATUAL do livro; nenhum "
                                    "valor de leitura muda, nenhuma nota é recalculada"})
    db.commit()
    return total


def _imprimir_congelamento(relatorio: RelatorioCongelamento) -> None:
    print(f"  congelamento de nível — já congeladas: {relatorio.ja_congeladas}; "
          f"a congelar: {relatorio.congelaveis}; "
          f"sem nível no livro (ficam nulas): {relatorio.sem_nivel_no_livro}")
    if relatorio.por_nivel:
        por_nivel = ", ".join(f"{n}={len(ids)}" for n, ids in sorted(relatorio.por_nivel.items()))
        print(f"    por nível: {por_nivel}")


def _saida_tolerante() -> None:
    """Não derrubar o relatório por causa do console.

    No Windows o terminal costuma estar em ``cp1252``, que não tem ``→`` nem
    ``≠``: o ``print`` do relatório de vínculo estourava ``UnicodeEncodeError`` e
    matava a execução ANTES de chegar ao congelamento — e um dry-run que aborta
    no meio é pior do que um caractere trocado. ``errors="replace"`` preserva a
    codificação do terminal (acentos continuam certos) e degrada só o que não
    couber. Em terminal UTF-8 nada muda."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):   # stream sem reconfigure
            pass


def main() -> int:
    _saida_tolerante()
    parser = argparse.ArgumentParser(
        description="Vincula livros antigos ao catálogo oficial do Elefante (dry-run por padrão).")
    parser.add_argument("--escola", type=int, default=None, help="só esta escola")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava elefante_id/word_count/nivel_fonte (nunca o nível efetivo)")
    parser.add_argument("--congelar-niveis", action="store_true",
                        help="também congela em leituras.nivel_codigo o nível ATUAL do livro "
                             "(opcional e idempotente; nenhum número muda — só tira o histórico "
                             "da dependência do catálogo vigente)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        consulta = select(Escola.id, Escola.nome).order_by(Escola.id)
        if args.escola is not None:
            consulta = consulta.where(Escola.id == args.escola)
        escolas = db.execute(consulta).all()
        cat = dificuldade_livro.catalogo()
        print(f"Catálogo oficial: {len(cat)} livro(s). Escolas: {len(escolas)}"
              + ("" if args.aplicar else " (DRY-RUN, nada será gravado)"))
        total = 0
        congeladas = 0
        falhas: list[tuple[int, str]] = []
        for escola_id, nome in escolas:
            relatorio = analisar_escola(db, escola_id, nome, cat)
            _imprimir(relatorio)
            if args.aplicar:
                try:
                    n = aplicar(db, relatorio)
                    total += n
                    print(f"  → {n} livro(s) vinculado(s).")
                except Exception as erro:  # noqa: BLE001 — uma escola ruim não derruba o lote
                    db.rollback()
                    falhas.append((escola_id, str(erro)[:200]))
                    print(f"  → FALHOU ({erro})")
            if not args.congelar_niveis:
                continue
            congelamento = analisar_congelamento(db, escola_id, nome)
            _imprimir_congelamento(congelamento)
            if not args.aplicar:
                continue
            try:
                n = congelar(db, congelamento)
                congeladas += n
                print(f"  → {n} leitura(s) com nível congelado.")
            except Exception as erro:  # noqa: BLE001 — uma escola ruim não derruba o lote
                db.rollback()
                falhas.append((escola_id, str(erro)[:200]))
                print(f"  → FALHOU no congelamento ({erro})")
        if args.aplicar:
            print(f"\nResumo: {total} livro(s) vinculado(s)"
                  + (f"; {congeladas} leitura(s) com nível congelado" if args.congelar_niveis else "")
                  + f"; falhas: {len(falhas)}")
            for escola_id, erro in falhas:
                print(f"  - escola {escola_id}: {erro}")
        return 1 if falhas else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
