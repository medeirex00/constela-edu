"""Consolida as FICHAS-SOMBRA da sincronização na ficha oficial da Lista Piloto.

Por que existe
--------------
Em julho/agosto a sincronização do Matific criou fichas com o nome TRUNCADO pelo
relatório ao lado da ficha oficial da mesma criança (mesma turma, fora da Lista
Piloto, com a conta da plataforma). A criança passou a ser duas no ranking e na
contagem da turma. A política ``consolidar_sombras = automatico`` resolve isso
a cada sincronização daqui em diante; este script resolve o PASSIVO, escola a
escola, com as MESMAS regras (``app/services/consolidacao_sombras.py``).

As regras (iteração 2, 12/10)
-----------------------------
A 1ª simulação em produção achou só 1 par na rede: a regra antiga tratava como
"duas contas" qualquer dado da mesma plataforma nas duas fichas — e a oficial
tinha o Matific ligado por NOME até 31/07, antes de a sombra existir. Agora:

* CONTINUIDADE DA CONTA: dado da mesma plataforma nas duas fichas só passa se
  for a MESMA conta continuando — a oficial sem conta própria nela, retratos
  sem sobreposição de dias, contadores acumulados do limite iguais ou maiores
  do lado posterior, no máximo 31 dias entre os dois e nenhum dado novo na
  ficha anterior depois de a posterior começar. Senão, CONFLITO com o motivo
  (``dados_simultaneos_mesma_plataforma``, ``contador_regrediu``,
  ``intervalo_longo``, ``continuidade_sem_retrato``,
  ``leitura_repetida_nas_duas_fichas``, ``duas_contas_mesma_plataforma``);
* nome IDÊNTICO com dado só consolida continuando dado ANTERIOR da oficial;
* FORMA DO NOME: o sufixo da turma no fim do nome ("… 2B"), a partícula a
  menos (DOS) e a vogal acentuada que virou minúscula não impedem o par. O
  PRENOME diferente continua na revisão manual (decisão 3 do dono).

A linha de cada CONSOLIDAR mostra a continuidade por plataforma (dias do
limite, intervalo, contadores iguais/crescentes). RISCO que os dados não
eliminam: outra criança cuja conta começa com contadores iguais ou maiores
que os da oficial logo depois de ela parar passaria como continuidade — por
isso a conferência das linhas antes de ``--aplicar`` continua obrigatória.

Garantias
---------
* SIMULAÇÃO POR PADRÃO: sem ``--aplicar`` nada é gravado. No Postgres a
  transação nasce ``READ ONLY`` e o script CONFERE (``SHOW
  transaction_read_only``) antes de ler qualquer coisa; se não ficou somente
  leitura, aborta (código 4).
* Saída só com IDS (sombra, oficial, turma, fichas relacionadas). Nomes de
  criança só com ``--nomes`` — e nunca vão para a auditoria.
* ``--aplicar`` EXIGE ``--esperado N`` e ``--assinatura A``: N é o total de
  pares CONSOLIDAR e A a assinatura dos PARES (sha256 curto da lista ordenada de
  escola, sombra e oficial) que a simulação mostrou para o MESMO recorte
  (``--escola`` ou ``--todas``). O número sozinho não basta: entre a conferência
  e a aplicação um par pode sair e outro entrar mantendo N — e seria fundido um
  par que ninguém viu. Se esta execução achar outro número OU outros pares,
  aborta ANTES de gravar, com código 3.
* COMPARE-AND-SET: cada par é reconferido no banco atual antes de fundir; o que
  mudou entre a simulação e a aplicação é pulado e listado.
* Só pares CONSOLIDAR são fundidos. REVISAR e CONFLITO ficam para gente;
  SEM_PAR é outra criança.
* Cada fusão fica na auditoria (``aluno.fundido`` com a foto pré-fusão e a
  origem automática; ``aluno.consolidado_automatico`` com as evidências e os ids
  das linhas movidas, origem ``script``), sem usuário: nenhuma pessoa fundiu na
  tela. Fusões, auditoria e recálculo de cada escola caem num commit só — se o
  recálculo falha, nada daquela escola fica gravado.

Antes de aplicar — decisão operacional
--------------------------------------
A fusão APAGA a ficha-sombra (irreversível por design; a foto pré-fusão fica na
auditoria). Aplicar EXIGE AUTORIZAÇÃO DO DONO e BACKUP VALIDADO (restaurável),
tomado imediatamente antes.

Como executar
-------------
Simulação (não grava nada):

    python -m scripts.consolidar_sombras --escola 11
    python -m scripts.consolidar_sombras --todas
    python -m scripts.consolidar_sombras --escola 11 --nomes   # com os nomes

Aplicação (N e A = o total de CONSOLIDAR e a assinatura dos pares que a
simulação ACABOU de mostrar):

    python -m scripts.consolidar_sombras --escola 11 --aplicar --esperado N --assinatura A
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Aluno, Escola  # noqa: E402
from app.services import consolidacao_sombras as cs  # noqa: E402
from app.services import politica_sync  # noqa: E402

# Código de saída quando o --esperado não confere (nada gravado).
SAIDA_ESPERADO_DIVERGENTE = 3
# Código de saída quando a simulação não conseguiu uma transação somente leitura.
SAIDA_SEM_SOMENTE_LEITURA = 4


def _argumentos(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simula (e, com --aplicar --esperado N, aplica) a consolidação "
                    "das fichas-sombra na ficha oficial da Lista Piloto.")
    alvo = parser.add_mutually_exclusive_group(required=True)
    alvo.add_argument("--escola", type=int, default=None, help="só esta escola")
    alvo.add_argument("--todas", action="store_true", help="todas as escolas")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava: funde os pares CONSOLIDAR (sem isto, só simula). "
                             "Exige --esperado e --assinatura.")
    parser.add_argument("--esperado", type=int, default=None, metavar="N",
                        help="com --aplicar: total de pares CONSOLIDAR conferido na "
                             "simulação; se divergir, aborta sem gravar")
    parser.add_argument("--assinatura", default=None, metavar="A",
                        help="com --aplicar: assinatura dos pares CONSOLIDAR que a "
                             "simulação mostrou; se outros pares forem achados, aborta "
                             "sem gravar")
    parser.add_argument("--nomes", action="store_true",
                        help="mostra os nomes das fichas (dado pessoal: use só na "
                             "conferência)")
    args = parser.parse_args(argv)
    if args.esperado is not None and not args.aplicar:
        parser.error("--esperado só vale junto com --aplicar.")
    if args.assinatura is not None and not args.aplicar:
        parser.error("--assinatura só vale junto com --aplicar.")
    if args.aplicar and args.esperado is None:
        parser.error("--aplicar exige --esperado N (o total de pares CONSOLIDAR que "
                     "a simulação mostrou).")
    if args.aplicar and not (args.assinatura or "").strip():
        parser.error("--aplicar exige --assinatura A (a assinatura dos pares que a "
                     "simulação mostrou).")
    if args.esperado is not None and args.esperado < 0:
        parser.error("--esperado não pode ser negativo.")
    return args


def assinatura_dos_pares(planos: list[cs.Plano]) -> str:
    """Impressão digital ESTÁVEL de QUAIS pares a execução vai fundir: sha256 da
    lista ordenada de (escola, sombra, oficial), em 12 hexadecimais. Só ids —
    nenhum nome entra."""
    pares = sorted((p.escola_id, i.sombra_id, i.oficial_id)
                   for p in planos for i in p.consolidar)
    texto = ";".join(f"{e}:{s}>{o}" for e, s, o in pares)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def _abrir_somente_leitura(db) -> bool:
    """Simulação no Postgres: a transação nasce READ ONLY (primeira instrução) e
    o próprio banco confirma — nem um engano no caminho consegue gravar. Outros
    dialetos (o SQLite dos testes) não têm a instrução: lá vale o rollback ao
    final, e a função responde True."""
    if db.get_bind().dialect.name != "postgresql":
        return True
    db.execute(text("SET TRANSACTION READ ONLY"))
    return str(db.execute(text("SHOW transaction_read_only")).scalar()).lower() == "on"


def _nome(db, aluno_id: int | None) -> str:
    a = db.get(Aluno, aluno_id) if aluno_id is not None else None
    return a.nome if a is not None else "?"


def _continuidade(evidencias: dict) -> str:
    """A continuidade provada, por plataforma, numa linha: "matific oficial
    2026-07-31->2026-08-01 (1d) iguais". Só datas e rótulos (e só ASCII na
    seta: o console do Windows sem UTF-8 não imprime "→")."""
    partes = [f"{p} {ev['ficha_anterior']} {ev['ultimo_retrato_anterior']}->"
              f"{ev['primeiro_retrato_posterior']} ({ev['dias_entre']}d) {ev['contadores']}"
              for p, ev in sorted((evidencias.get("continuidade") or {}).items())]
    return f"; continuidade: {', '.join(partes)}" if partes else ""


def _linha(db, item: cs.Item, nomes: bool) -> str:
    rel = f" relacionados={list(item.relacionados)}" if item.relacionados else ""
    if item.classe == cs.CONSOLIDAR:
        texto = (f"  CONSOLIDAR sombra={item.sombra_id} -> oficial={item.oficial_id} "
                 f"turma={item.turma_id} [{item.evidencias.get('relacao_nome')}; "
                 f"plataformas: {', '.join(item.evidencias.get('plataformas_da_sombra')) or '-'}"
                 f"{_continuidade(item.evidencias)}]"
                 + rel)
    else:
        oficial = f" oficial={item.oficial_id}" if item.oficial_id else ""
        texto = (f"  {item.classe.upper():<10} sombra={item.sombra_id}{oficial} "
                 f"turma={item.turma_id} motivo={item.motivo}{rel}")
    if nomes:
        texto += f"  «{_nome(db, item.sombra_id)}»"
        if item.oficial_id:
            texto += f" × «{_nome(db, item.oficial_id)}»"
    return texto


def _imprimir(db, plano: cs.Plano, nome_escola: str, nomes: bool) -> None:
    c = plano.contagens()
    politica = politica_sync.obter(db, plano.escola_id)["consolidar_sombras"]
    print(f"escola {plano.escola_id} ({nome_escola}) ano {plano.ano}: "
          f"CONSOLIDAR {c[cs.CONSOLIDAR]} · REVISAR {c[cs.REVISAR]} · "
          f"CONFLITO {c[cs.CONFLITO]} · SEM_PAR {c[cs.SEM_PAR]} "
          f"(política da sincronização: {politica})")
    for classe in (cs.CONSOLIDAR, cs.CONFLITO, cs.REVISAR):
        for item in plano.da_classe(classe):
            print(_linha(db, item, nomes))


def main(argv=None) -> int:
    args = _argumentos(argv)

    db = SessionLocal()
    try:
        if not args.aplicar and not _abrir_somente_leitura(db):
            db.rollback()
            print("ABORTADO — a transação da simulação não ficou somente leitura. "
                  "Nada foi lido nem gravado.")
            return SAIDA_SEM_SOMENTE_LEITURA
        if args.escola is not None:
            if db.get(Escola, args.escola) is None:
                print(f"escola {args.escola} não existe.")
                db.rollback()
                return 2
            ids = [args.escola]
        else:
            ids = list(db.execute(select(Escola.id).order_by(Escola.id)).scalars())
        nomes_escola = dict(db.execute(select(Escola.id, Escola.nome)
                                       .where(Escola.id.in_(ids or [-1]))).all())
        planos = [cs.planejar(db, eid) for eid in ids]
        for plano in planos:
            _imprimir(db, plano, nomes_escola.get(plano.escola_id, "?"), args.nomes)
        total = sum(len(p.consolidar) for p in planos)
        assinatura = assinatura_dos_pares(planos)
        print(f"\ntotal de pares CONSOLIDAR: {total}")
        print(f"assinatura dos pares CONSOLIDAR: {assinatura}")

        if not args.aplicar:
            print("simulação apenas — nada foi gravado. Para consolidar (só com "
                  "autorização e backup validado): --aplicar --esperado N "
                  "--assinatura A.")
            db.rollback()
            return 0

        if total != args.esperado:
            db.rollback()
            print(f"\nABORTADO — esperado {args.esperado}, mas esta execução tem "
                  f"{total} par(es) CONSOLIDAR. Nada foi gravado. Rode a simulação de "
                  "novo e confira antes de aplicar.")
            return SAIDA_ESPERADO_DIVERGENTE
        if assinatura != args.assinatura.strip().lower():
            db.rollback()
            print(f"\nABORTADO — a assinatura dos pares desta execução ({assinatura}) "
                  f"não é a conferida ({args.assinatura.strip()}): os pares mudaram "
                  "desde a simulação. Nada foi gravado. Rode a simulação de novo e "
                  "confira antes de aplicar.")
            return SAIDA_ESPERADO_DIVERGENTE

        db.rollback()        # a leitura acabou; cada escola grava na sua transação
        fundidos = 0
        for plano in planos:
            if not plano.consolidar:
                continue
            resultado = cs.aplicar(db, plano, usuario_id=None, origem="script")
            fundidos += len(resultado["consolidados"])
            print(f"escola {plano.escola_id}: {len(resultado['consolidados'])} "
                  f"consolidada(s), {len(resultado['pulados'])} pulada(s)")
            for p in resultado["pulados"]:
                print(f"  PULADA sombra={p['sombra_id']} oficial={p['oficial_id']} "
                      f"agora={p['classe_atual']}/{p['motivo_atual']}")
        print(f"\nconsolidadas: {fundidos} de {total}.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
