"""Gera/atualiza ``app/dados/catalogo_elefante.json`` — o CATÁLOGO DE REFERÊNCIA
do Elefante Letrado usado pela dificuldade por livro (``services/dificuldade_livro``).

Uso (da pasta backend/):
    python scripts/gerar_catalogo_elefante.py <extracao1.json> [<extracao2.json> ...]

Cada entrada é um JSON do extrator autenticado (formato ``{"livros": [...]}`` ou
lista de livros, cada um com ``id, title, levelName, levelId, wordCount,
pageCount``). Os arquivos são UNIDOS e DEDUPLICADOS por ``id`` (o último vence),
só livros em português (``languageId == 1``) e não excluídos entram, e a saída é
DETERMINÍSTICA (ordenada por id, campos mínimos) — rodar duas vezes com as mesmas
entradas gera o mesmo arquivo byte a byte.

Por que ARQUIVO no repositório, e não tabela: o catálogo é uma REFERÊNCIA de
calibração, não dado transacional. Versionado em git ele é auditável (cada
atualização é um commit revisável, com diff livro a livro), reproduzível e não
exige migração de schema. A fórmula (``dificuldade_livro``) é o que dá valor;
este arquivo só fornece os metadados objetivos (nível + wordCount).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "catalogo_elefante.json"
CAMPOS = ("id", "title", "levelName", "levelId", "wordCount", "pageCount")


def _livros_de(caminho: Path) -> list[dict]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if isinstance(dados, dict):
        dados = dados.get("livros") or dados.get("books") or dados.get("data") or []
    saida = []
    for item in dados:
        # livros-faltantes traz campos escolhidos + ``__todos`` (registro completo)
        reg = item.get("__todos") if isinstance(item.get("__todos"), dict) else item
        if not isinstance(reg, dict) or reg.get("id") is None:
            continue
        saida.append(reg)
    return saida


def consolidar(entradas: list[Path]) -> dict:
    por_id: dict[int, dict] = {}
    ignorados = {"idioma": 0, "excluido": 0, "sem_nivel_ou_palavras": 0}
    for caminho in entradas:
        for reg in _livros_de(caminho):
            if int(reg.get("languageId") or 1) != 1:
                ignorados["idioma"] += 1
                continue
            if reg.get("isSoftDeleted"):
                ignorados["excluido"] += 1
                continue
            if not reg.get("levelName") or not reg.get("wordCount"):
                ignorados["sem_nivel_ou_palavras"] += 1
                continue
            por_id[int(reg["id"])] = {
                "id": int(reg["id"]),
                "title": str(reg.get("title") or "").strip(),
                "levelName": str(reg["levelName"]).strip(),
                "levelId": reg.get("levelId"),
                "wordCount": int(reg["wordCount"]),
                "pageCount": int(reg.get("pageCount") or 0),
            }
    livros = [por_id[k] for k in sorted(por_id)]
    return {
        "fonte": "admin.elefanteletrado.com.br — POST /library/elementary-school-search "
                 "(hasZPlusEnabled/hasAPlusEnabled=true) + GET /library/book?bookId=",
        "gerado_em": date.today().isoformat(),
        "n": len(livros),
        "ignorados": ignorados,
        "livros": livros,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    entradas = [Path(p) for p in argv[1:]]
    for p in entradas:
        if not p.exists():
            print(f"arquivo não encontrado: {p}")
            return 2
    pacote = consolidar(entradas)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(pacote, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"catálogo gravado em {SAIDA}: {pacote['n']} livros; ignorados={pacote['ignorados']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
