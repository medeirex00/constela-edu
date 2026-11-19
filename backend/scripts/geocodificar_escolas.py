"""Preenche latitude/longitude das escolas via Nominatim/OpenStreetMap.

Sem serviço pago, sem chave. Idempotente (só as sem coordenada, salvo --forcar),
respeita o rate-limit do OSM (intervalo entre requisições) e NÃO trava se uma
escola não for encontrada — registra e segue. A correção manual continua
possível pela API (PATCH /redes/escolas/{id} com latitude/longitude), e a mesma
geocodificação está disponível na tela de gestão de redes (botão).

    python -m scripts.geocodificar_escolas               # só as sem coordenada
    python -m scripts.geocodificar_escolas --rede 1      # só as de uma rede
    python -m scripts.geocodificar_escolas --forcar      # re-geocodifica todas
    python -m scripts.geocodificar_escolas --intervalo 1.2
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Escola  # noqa: E402
from app.services.geocodificacao import (  # noqa: E402
    INTERVALO_PADRAO,
    geocodificar_escola,
    montar_consulta,
    salvar_coordenadas,
)
from scripts._saida import forcar_saida_utf8  # noqa: E402


def main() -> None:
    forcar_saida_utf8()
    parser = argparse.ArgumentParser(description="Geocodifica escolas (lat/lng) via OSM.")
    parser.add_argument("--forcar", action="store_true",
                        help="re-geocodifica também escolas que já têm coordenada")
    parser.add_argument("--rede", type=int, default=None, help="limita a uma rede")
    parser.add_argument("--intervalo", type=float, default=INTERVALO_PADRAO,
                        help="segundos entre requisições (rate-limit do OSM; >= 1)")
    args = parser.parse_args()
    intervalo = max(1.0, args.intervalo)  # nunca abaixo do limite do OSM

    with SessionLocal() as db:
        consulta = select(Escola).order_by(Escola.nome)
        if not args.forcar:
            consulta = consulta.where(Escola.latitude.is_(None))
        if args.rede is not None:
            consulta = consulta.where(Escola.rede_id == args.rede)
        escolas = db.execute(consulta).scalars().all()
        db.expunge_all()

    if not escolas:
        print("Nada a geocodificar (todas já têm coordenada ou filtro vazio).")
        return

    print(f"Geocodificando {len(escolas)} escola(s) — intervalo {intervalo:.1f}s...\n")
    encontradas = falhas = alteradas = 0
    for i, escola in enumerate(escolas):
        if i:
            time.sleep(intervalo)  # rate-limit entre chamadas
        coord = geocodificar_escola(escola)
        if coord is None:
            falhas += 1
            print(f"  [--] {escola.nome}: não encontrada  ({montar_consulta(escola)})")
            continue
        with SessionLocal.begin() as db:
            gravada = salvar_coordenadas(db, escola, coord)
        if gravada:
            encontradas += 1
            print(f"  [OK] {escola.nome} -> {coord[0]:.5f}, {coord[1]:.5f}")
        else:
            alteradas += 1
            print(f"  [--] {escola.nome}: cadastro mudou durante a consulta")
    print(f"\nConcluído: {encontradas} localizada(s), {falhas} não encontrada(s), "
          f"{alteradas} com cadastro alterado.")


if __name__ == "__main__":
    main()
