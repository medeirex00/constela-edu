"""Simulação da fila de revisão de identidade com o matcher DESTE código — SOMENTE
LEITURA. Uso (da pasta backend/, com DATABASE_URL apontando para o banco):

    python scripts/simular_revisoes_identidade.py [--escola ID] [--detalhe]

Para cada revisão PENDENTE, remonta a linha guardada como a sincronização monta e
chama ``identidade_aluno.decidir`` contra o cadastro ATUAL — na ordem das
revisões, aplicando em memória o vínculo de cada ASSOCIAR (``Contexto.vincular``),
como o importador faz: a 2ª pendência da MESMA conta (resumo + leituras) casa pela
conta e a 2ª conta na MESMA ficha vira conflito, exatamente como na sync real.

Classes (os três estados da vinculação):
  * VINCULO_SEGURO — a próxima sincronização associa e encerra a pendência
    (``revisao.encerrada_automaticamente``);
  * AMBIGUO — continua na revisão (vários candidatos, nome que só casa em outra
    sala, evidência insuficiente);
  * CONFLITO — continua na revisão (conta da plataforma em disputa: segunda conta
    na mesma ficha, conta de outra ficha ou de ficha inativa, RA repetido);
  * SEM_CORRESPONDENCIA — nenhum candidato: nunca vira vínculo por aproximação.

Nada é gravado: a sessão é aberta em modo READ ONLY (o Postgres recusa qualquer
escrita) e termina em rollback. A saída NÃO tem nome de aluno: só ids, contagens,
via/motivo e chaves de sala.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # rodar de backend/

from sqlalchemy import event, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.models.academico import RevisaoIdentidade  # noqa: E402
from app.services import identidade_aluno as ida  # noqa: E402

_CONFLITOS = frozenset({"outra_identidade_na_plataforma", "identidade_de_outro_aluno",
                        "identidade_de_ficha_inativa", "ra_repetido"})


def classe(dec: ida.Decisao) -> str:
    if dec.acao == ida.ASSOCIAR:
        return "VINCULO_SEGURO"
    if dec.acao == ida.REVISAR:
        return "CONFLITO" if dec.motivo in _CONFLITOS else "AMBIGUO"
    if dec.acao == ida.CRIAR:
        return "SEM_CORRESPONDENCIA"
    return f"OUTRO({dec.acao})"


def _somente_leitura(db: Session) -> None:
    """Trava TODA transação desta sessão em somente leitura e confere antes de ler
    qualquer dado. Postgres: ``SET TRANSACTION READ ONLY`` a cada início de
    transação (o pooler ignora parâmetros de conexão, então vai por SQL). SQLite
    (o banco local): ``PRAGMA query_only``."""
    postgres = db.get_bind().dialect.name == "postgresql"

    @event.listens_for(db, "after_begin")
    def _travar(_sessao, _transacao, conexao):
        conexao.exec_driver_sql("SET TRANSACTION READ ONLY" if postgres
                                else "PRAGMA query_only = ON")

    consulta = "SHOW transaction_read_only" if postgres else "PRAGMA query_only"
    if str(db.execute(text(consulta)).scalar()).lower() not in ("on", "1"):
        raise SystemExit("A sessão não ficou somente leitura — abortado sem ler dados.")


def simular_escola(db: Session, escola_id: int, detalhe: bool) -> tuple[Counter, Counter, Counter]:
    ctx = ida.carregar_contexto(db, escola_id)
    pendentes = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola_id, RevisaoIdentidade.status == "pendente")
        .order_by(RevisaoIdentidade.id)).scalars().all()
    por_classe, por_regra = Counter(), Counter()
    por_conta: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rev in pendentes:
        dados = (rev.linhas or [{}])[-1] if rev.linhas else {}
        linha = ida.linha_de_dados(rev.nome_recebido, dados, plataforma=rev.plataforma,
                                   turma_nome=rev.turma_informada or "")
        dec = ida.decidir(ctx, linha)
        c = classe(dec)
        por_classe[c] += 1
        por_regra[f"{dec.acao}:{dec.via if dec.acao == ida.ASSOCIAR else dec.motivo}"] += 1
        por_conta[(rev.plataforma, rev.id_externo or f"revisao#{rev.id}")].add(c)
        if dec.acao == ida.ASSOCIAR and linha.id_externo:
            ctx.vincular(dec.aluno_id, linha.plataforma, linha.id_externo)
        if detalhe:
            print(f"    revisão #{rev.id:<6} {rev.plataforma:9} {rev.formato or '-':9} {c:20} "
                  f"via={dec.via or '-':20} motivo={dec.motivo or '-':32} "
                  f"ficha=#{dec.aluno_id} sala={dec.chave_sala!r}")
    contas = Counter("VINCULO_SEGURO" if cs == {"VINCULO_SEGURO"} else "+".join(sorted(cs))
                     for cs in por_conta.values())
    print(f"escola #{escola_id}: {len(pendentes)} pendentes → {dict(por_classe)} | "
          f"{len(por_conta)} contas/identidades → {dict(contas)}")
    return por_classe, por_regra, contas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escola", type=int, help="só esta escola (padrão: todas com pendência)")
    ap.add_argument("--detalhe", action="store_true", help="destino de cada revisão (sem nomes)")
    args = ap.parse_args()
    with Session(engine) as db:
        _somente_leitura(db)
        escolas = [args.escola] if args.escola else [r[0] for r in db.execute(text(
            "SELECT DISTINCT escola_id FROM revisoes_identidade "
            "WHERE status = 'pendente' ORDER BY 1")).all()]
        total, regras, contas = Counter(), Counter(), Counter()
        for eid in escolas:
            c, r, k = simular_escola(db, eid, args.detalhe)
            total.update(c); regras.update(r); contas.update(k)
        db.rollback()
    print(f"\nTOTAL ({len(escolas)} escola(s)): {dict(total)}")
    print(f"por regra/motivo: {dict(sorted(regras.items()))}")
    print(f"por conta/identidade: {dict(contas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
