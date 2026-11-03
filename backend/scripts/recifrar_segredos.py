"""Recifra os segredos em repouso para a chave ATUAL (rotação planejada da DEK/SECRET_KEY).

    python -m scripts.recifrar_segredos              # = --contar: só conta, não grava
    python -m scripts.recifrar_segredos --executar   # recifra (idempotente)

Sequência (A1 §3.2; nunca no meio de um incidente — lá vale a troca simples + recadastro):

1. publicar o código com o chaveiro;
2. no ambiente: DATA_ENCRYPTION_KEY = a NOVA, DATA_ENCRYPTION_KEYS_ANTERIORES = a DEK que
   saiu; se a SECRET_KEY também girar, CHAVE_CIFRA_LEGADA_ANTERIOR = a SECRET_KEY que saiu
   (só decifra as cifras legadas; NUNCA valida JWT: todas as sessões caem);
3. deploy;
4. ``--contar`` → ``--executar`` → ``--contar`` com tudo em "primaria";
5. APAGAR as anteriores do ambiente e fazer deploy;
6. ``GET /api/v1/sistema/diagnostico`` com ``cifra.anteriores_configuradas = 0``.

Saída: só números por origem (nunca valores). Código de saída: 0 = nada sobrou numa chave
anterior nem ilegível; 1 = sobrou (``--aceitar-ilegiveis`` tolera os ilegíveis, que só o
recadastro pela tela resolve); 2 = recusado (``--executar`` sem DATA_ENCRYPTION_KEY ativa
levaria tudo para a chave derivada da SECRET_KEY). A sessão salva do Matific é apagada em
vez de recifrada (refeita sozinha). O --executar registra a auditoria
``seguranca.recifragem`` só com as contagens.
"""
from __future__ import annotations

import argparse
import sys

from app.core.security import SITUACOES_CIFRA, diagnostico_cifra
from app.services import recifragem
from scripts._saida import forcar_saida_utf8


def _imprimir(titulo: str, contagens: dict, saida) -> None:
    print(titulo, file=saida)
    for origem in recifragem.ORIGENS:
        c = contagens[origem]
        print(f"  {origem}: " + " ".join(f"{s}={c[s]}" for s in SITUACOES_CIFRA), file=saida)


def main(argv: list[str] | None = None, *, sessao=None, saida=None) -> int:
    """``sessao``: fábrica de sessões (testes); padrão = a do app (DATABASE_URL)."""
    forcar_saida_utf8()
    saida = saida or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--contar", action="store_true",
                      help="só conta por origem e chave (padrão; não grava nada)")
    modo.add_argument("--executar", action="store_true",
                      help="recifra na chave atual o que estiver numa anterior (idempotente)")
    parser.add_argument("--aceitar-ilegiveis", action="store_true",
                        help="saída 0 mesmo com cifras ilegíveis (a recadastrar pela tela)")
    args = parser.parse_args(argv)

    cifra = diagnostico_cifra()
    print("cifra: " + " ".join(f"{k}={v}" for k, v in cifra.items()), file=saida)
    if args.executar and not cifra["dedicada_ativa"]:
        print("Recusado: DATA_ENCRYPTION_KEY vazia, só espaços ou igual à SECRET_KEY — "
              "recifrar agora levaria os segredos para a chave derivada da SECRET_KEY. "
              "Defina a DATA_ENCRYPTION_KEY nova antes.", file=sys.stderr)
        return 2

    if sessao is None:
        from app.core.database import SessionLocal as sessao
    db = sessao()
    try:
        if args.executar:
            resumo = recifragem.executar(db)
            _imprimir("antes:", resumo["antes"], saida)
            for origem in recifragem.ORIGENS:
                f = resumo["feito"][origem]
                print(f"  {origem}: recifradas={f['recifradas']} apagadas={f['apagadas']} "
                      f"ilegiveis_mantidas={f['ilegiveis_mantidas']}", file=saida)
            print(f"hashes do Quest recalculados: {resumo['hashes_quest_corrigidos']}",
                  file=saida)
            contagens = resumo["depois"]
            _imprimir("depois:", contagens, saida)
        else:
            contagens = recifragem.contar(db)
            db.rollback()                  # só leitura: nada a gravar
            _imprimir("contagem:", contagens, saida)
    finally:
        db.close()

    sobra = recifragem.pendentes(contagens, aceitar_ilegiveis=args.aceitar_ilegiveis)
    if sobra:
        print(f"Pendente: {sobra} cifra(s) ainda numa chave anterior ou ilegível(is). "
              "Não apague as chaves anteriores ainda.", file=saida)
        return 1
    print("Tudo na chave atual: as chaves anteriores podem ser apagadas do ambiente.",
          file=saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
