"""Gera uma AMOSTRA ANONIMIZADA das capturas do crawler do Matific.

Lê tudo em matific_captura/, guarda UM exemplo por rota, redige nomes/e-mails e
encurta listas longas — produzindo matific_captura/_amostra_anonimizada.json,
seguro para compartilhar (sem dados de aluno) e suficiente para documentar a API
e construir a integração.

Uso (na pasta backend, com o Python do backend):
    .venv\\Scripts\\python.exe ..\\tools\\matific_amostra.py
"""
from __future__ import annotations

import glob
import json
import os

SAIDA = os.path.join(os.getcwd(), "matific_captura")

# Chaves cujo VALOR string é PII → redigir. (Estrutura/tipos são preservados.)
CHAVES_PII = {
    "name", "student_name", "account_id", "first_name", "last_name", "full_name",
    "display_name", "email", "username", "guardian_name", "teacher_name",
    "parent_name", "child_name", "login", "user_name",
}
MAX_ITENS_LISTA = 3   # de listas longas (ex.: 212 alunos) guarda só 3 exemplos


def _redigir(valor, chave: str = ""):
    if isinstance(valor, dict):
        return {k: _redigir(v, k) for k, v in valor.items()}
    if isinstance(valor, list):
        corte = [_redigir(v) for v in valor[:MAX_ITENS_LISTA]]
        return corte + ([f"… (+{len(valor) - MAX_ITENS_LISTA} itens)"]
                        if len(valor) > MAX_ITENS_LISTA else [])
    if isinstance(valor, str) and valor and chave.lower() in CHAVES_PII:
        return "‹redigido›"
    return valor


def main() -> None:
    if not os.path.isdir(SAIDA):
        print(f"Não achei a pasta {SAIDA}. Rode o crawler antes.")
        return
    por_rota: dict[str, dict] = {}
    for arq in sorted(glob.glob(os.path.join(SAIDA, "[0-9]*.json"))):
        try:
            with open(arq, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        rota = rec.get("rota")
        if not rota or rota in por_rota:
            continue
        por_rota[rota] = {
            "rota": rota,
            "metodo": rec.get("metodo"),
            "status": rec.get("status"),
            "response_amostra": _redigir(rec.get("response")),
        }
    destino = os.path.join(SAIDA, "_amostra_anonimizada.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(sorted(por_rota.values(), key=lambda r: r["rota"]),
                  f, ensure_ascii=False, indent=2)
    print(f"OK: {len(por_rota)} rotas únicas -> {destino}")
    print("Pode me enviar esse arquivo (já está sem nomes de alunos).")


if __name__ == "__main__":
    main()
