"""Etapa de deploy da Fase 3A — tira de circulação a senha de professor derivada do nome.

Por que existe
--------------
Até a Fase 3A a senha inicial do professor era derivável do nome (o @ em
minúsculas + "123"; antes, o primeiro nome + "123"), a regra estava escrita no
código de um repositório público e não havia troca obrigatória. O código novo
não cria mais senhas assim — mas as contas ANTIGAS continuam com elas até alguém
trocar. Este script as encontra e, só quando pedido, as invalida.

Garantias
---------
* DIAGNÓSTICO POR PADRÃO: sem ``--aplicar`` nada é gravado. Só confere o hash
  bcrypt de cada conta de professor contra as senhas das convenções antigas.
* NENHUMA SENHA É IMPRESSA, nem a antiga nem a nova: a nova é aleatória e
  ninguém a recebe. O professor volta a entrar pelo link de redefinição de uso
  único ("Gerar link de redefinição", em Usuários), escolhendo a própria senha.
* NÃO BLOQUEIA ninguém para sempre e NÃO cria senha conhecida de reserva: a
  conta continua ativa; só a senha pública deixa de funcionar.
* Classifica cada conta: NUNCA USADA (sem login registrado de forma alguma),
  USADA (tem ``ultimo_acesso``) ou INDETERMINADA (sinais divergentes — ex.:
  presença registrada sem ``ultimo_acesso``). ``--so-nunca-usadas`` só toca as
  NUNCA USADAS. Conta cujo hash não pôde ser conferido é listada à parte e
  nunca é tocada.
* As sessões abertas dessas contas caem (``token_version``).
* Cada conta invalidada fica no log de auditoria (``usuario.senha_derivada_invalidada``).

Antes de aplicar — decisão operacional
--------------------------------------
Contas JÁ USADAS com a senha antiga deixam de entrar até o professor receber o
link. Combine com as escolas QUANDO aplicar e quem gera os links (coordenação
para professores, admin da escola para todos). Contas nunca usadas não afetam
ninguém e podem ser invalidadas a qualquer momento.

Como executar
-------------
    python -m scripts.senhas_derivadas                    # diagnóstico, todas as escolas
    python -m scripts.senhas_derivadas --escola 42        # diagnóstico, uma escola
    python -m scripts.senhas_derivadas --aplicar --escola 42
    python -m scripts.senhas_derivadas --aplicar --so-nunca-usadas   # sem impacto em quem usa

Contas de REDE (Secretaria) não entram no ``--escola``: alcançam a rede inteira e
só o admin global gera o link delas. Saem marcadas "(REDE n)" na execução completa.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.services import professores  # noqa: E402


def _escola(conta: dict) -> str:
    return "-" if conta["escola_id"] is None else str(conta["escola_id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Encontra (e, com --aplicar, invalida) senhas de professor derivadas do nome.")
    parser.add_argument("--escola", type=int, default=None, help="só esta escola")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava: invalida as senhas encontradas (sem isto, só diagnostica)")
    parser.add_argument("--so-nunca-usadas", action="store_true",
                        help="com --aplicar, mexe só em contas que nunca entraram")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        achadas = professores.contas_com_senha_derivada(db, args.escola)
        por_uso = {uso: [c for c in achadas if c["uso"] == uso]
                   for uso in (professores.USO_NUNCA_USADA, professores.USO_USADA,
                               professores.USO_INDETERMINADO)}
        print(f"contas com senha derivada do nome: {len(achadas)} "
              f"({len(por_uso['nunca_usada'])} nunca usadas, "
              f"{len(por_uso['usada'])} já usadas, "
              f"{len(por_uso['indeterminada'])} indeterminadas)")
        for c in achadas:
            # Conta de rede (Secretaria) pode não ter escola: "-" em vez de quebrar.
            excluida = " (EXCLUÍDA)" if c.get("status") == "excluido" else ""
            rede = (f" (REDE {c['rede_id']}: link só pelo admin global)"
                    if c.get("rede_id") else "")
            print(f"  usuario_id={c['usuario_id']:<6} escola={_escola(c):<5} "
                  f"@{(c['usuario'] or '-'):<28} {c['cargo']:<12} {c['uso'].upper()}"
                  f"{excluida}{rede}")
        if args.escola is None:
            globais = professores.contas_globais_com_senha_derivada(db)
            if globais:
                print(f"\nADMINISTRAÇÃO GLOBAL com senha derivada (troca MANUAL, "
                      f"fora da etapa): {len(globais)}")
                for c in globais:
                    print(f"  usuario_id={c['usuario_id']:<6} @{(c['usuario'] or '-')}")
        nao_verificaveis = professores.contas_nao_verificaveis(db, args.escola)
        if nao_verificaveis:
            print(f"\ncontas cujo hash não pôde ser conferido (fora da etapa): "
                  f"{len(nao_verificaveis)}")
            for c in nao_verificaveis:
                print(f"  usuario_id={c['usuario_id']:<6} escola={_escola(c):<5} "
                      f"@{(c['usuario'] or '-')}")

        if not args.aplicar:
            print("\ndiagnóstico apenas — nada foi gravado. Use --aplicar para invalidar.")
            return 0

        resultado = professores.invalidar_senhas_derivadas(
            db, args.escola, aplicar=True, so_nunca_usadas=args.so_nunca_usadas)
        db.commit()
        print(f"\ninvalidadas: {resultado['invalidadas']} de {resultado['encontradas']} "
              "encontradas. Os professores voltam a entrar pelo link de redefinição.")
        if args.so_nunca_usadas:
            print("(--so-nunca-usadas: as já usadas e as indeterminadas não foram tocadas)")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
