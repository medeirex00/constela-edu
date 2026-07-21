"""Preenche latitude/longitude das escolas via Nominatim/OpenStreetMap.

Sem serviço pago, sem chave. Idempotente (só as sem coordenada, salvo --forcar),
respeita o rate-limit do OSM (intervalo entre requisições) e NÃO trava se uma
escola não for encontrada — registra e segue. A correção manual continua
possível pela API (`PATCH /escolas/{id}` com latitude/longitude).

    python -m scripts.geocodificar_escolas               # só as sem coordenada
    python -m scripts.geocodificar_escolas --rede 1      # só as de uma rede
    python -m scripts.geocodificar_escolas --forcar      # re-geocodifica todas
    python -m scripts.geocodificar_escolas --intervalo 1.2
"""
import argparse
import time

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Escola
from app.services.geocodificacao import geocodificar_escola, montar_consulta


def main() -> None:
    parser = argparse.ArgumentParser(description="Geocodifica escolas (lat/lng) via OSM.")
    parser.add_argument("--forcar", action="store_true",
                        help="re-geocodifica também escolas que já têm coordenada")
    parser.add_argument("--rede", type=int, default=None, help="limita a uma rede")
    parser.add_argument("--intervalo", type=float, default=1.1,
                        help="segundos entre requisições (rate-limit do OSM; >= 1)")
    args = parser.parse_args()
    intervalo = max(1.0, args.intervalo)  # nunca abaixo do limite do OSM

    db = SessionLocal()
    try:
        consulta = select(Escola).order_by(Escola.nome)
        if not args.forcar:
            consulta = consulta.where(Escola.latitude.is_(None))
        if args.rede is not None:
            consulta = consulta.where(Escola.rede_id == args.rede)
        escolas = db.execute(consulta).scalars().all()

        if not escolas:
            print("Nada a geocodificar (todas já têm coordenada ou filtro vazio).")
            return

        print(f"Geocodificando {len(escolas)} escola(s) — intervalo {intervalo:.1f}s...\n")
        encontradas = falhas = 0
        for i, escola in enumerate(escolas):
            if i:
                time.sleep(intervalo)  # rate-limit entre chamadas
            coord = geocodificar_escola(escola)
            if coord:
                escola.latitude, escola.longitude = coord
                db.commit()  # persiste uma a uma (uma falha depois não perde as anteriores)
                encontradas += 1
                print(f"  [OK] {escola.nome} -> {coord[0]:.5f}, {coord[1]:.5f}")
            else:
                falhas += 1
                print(f"  [--] {escola.nome}: não encontrada  ({montar_consulta(escola)})")

        print(f"\nConcluído: {encontradas} geocodificada(s), {falhas} não encontrada(s) "
              f"de {len(escolas)}. As não encontradas podem ser corrigidas à mão "
              f"(PATCH /escolas/{{id}} com latitude/longitude).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
