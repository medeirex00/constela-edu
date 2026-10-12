"""Ferramenta do OPERADOR (admin global): gera o link de redefinição de senha de
UMA conta não global — inclusive a conta SEM escola, que não tem rota nenhuma.

Por que existe
--------------
O botão "Gerar link de redefinição" mora na tela de Usuários de UMA escola
(``POST /admin/usuarios/{id}/redefinir-senha``): a conta sem escola (Secretaria
sem ``escola_id``, professor órfão) não aparece em tela nenhuma e ficaria sem
caminho de volta — é o caso que ``scripts/senhas_derivadas.py`` lista à parte
como "sem escola: recuperação manual pelo admin global".

Garantias
---------
* SEM ``--confirmar`` NADA É GRAVADO: só confere as regras e mostra o que faria.
* ``--por`` tem de ser uma conta de ADMINISTRAÇÃO GLOBAL ativa — é ela que fica
  como autora do link (``criado_por``), e o consumo confere o autor de novo
  (``routers/auth.py::_criador_ainda_pode``: conta global ativa passa).
* Recusa alvo global, alvo excluído e o e-mail reservado ao dono
  (``ADMIN_GLOBAL_EMAIL``) — a troca dessas é manual, não por link.
* Como a rota da escola: os links pendentes do alvo são invalidados (só o mais
  novo vale), o pedido fica na auditoria (``usuario.reset_solicitado``, com
  ``origem`` deste script) e o token NUNCA vai para o log nem para o banco em
  texto (só o hash SHA-256).
* O link sai UMA vez, na saída deste comando. Entregue-o por canal seguro ao
  dono da conta; ele escolhe a própria senha. Nenhuma senha é exibida.

Como executar
-------------
    python -m scripts.link_redefinicao --usuario-id N --por M              # prévia
    python -m scripts.link_redefinicao --usuario-id N --por M --confirmar  # gera
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import update  # noqa: E402

from app.core.config import email_reservado_ao_dono, settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import gerar_token_reset, hash_token  # noqa: E402
from app.models import TokenResetSenha, Usuario  # noqa: E402
from app.services.audit import registrar  # noqa: E402

ORIGEM = "scripts/link_redefinicao"
SAIDA_RECUSADO = 2


def _argumentos(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera (com --confirmar) o link de redefinição de senha de UMA "
                    "conta não global, com um admin global como autor.")
    parser.add_argument("--usuario-id", type=int, required=True, metavar="N",
                        help="id da conta que receberá o link")
    parser.add_argument("--por", type=int, required=True, metavar="M",
                        help="id da conta de ADMINISTRAÇÃO GLOBAL ativa que gera o link")
    parser.add_argument("--confirmar", action="store_true",
                        help="grava e imprime o link (sem isto, só mostra o que faria)")
    return parser.parse_args(argv)


def _motivo_da_recusa(autor: Usuario | None, alvo: Usuario | None) -> str | None:
    """A regra de quem gera e para quem; None = pode."""
    if autor is None:
        return "a conta de --por não existe."
    if not autor.is_global:
        return "--por tem de ser uma conta de administração GLOBAL."
    if autor.status != "ativo":
        return "a conta de --por não está ativa."
    if alvo is None:
        return "a conta de --usuario-id não existe."
    if alvo.is_global:
        return "conta de administração global: troca manual, não por link."
    if alvo.status == "excluido":
        return "conta excluída — restaure-a antes de gerar o link."
    if email_reservado_ao_dono(alvo.email):
        return "conta com o e-mail reservado ao dono: troca manual, não por link."
    return None


def main(argv=None) -> int:
    args = _argumentos(argv)
    db = SessionLocal()
    try:
        autor = db.get(Usuario, args.por)
        alvo = db.get(Usuario, args.usuario_id)
        motivo = _motivo_da_recusa(autor, alvo)
        if motivo:
            print(f"RECUSADO — {motivo} Nada foi gravado.", file=sys.stderr)
            return SAIDA_RECUSADO

        escola = "-" if alvo.escola_id is None else str(alvo.escola_id)
        print(f"alvo: usuario_id={alvo.id} @{alvo.username or '-'} cargo={alvo.cargo} "
              f"escola={escola} rede={alvo.rede_id or '-'} status={alvo.status}")
        print(f"autor do link: usuario_id={autor.id} (administração global)")
        if not args.confirmar:
            print("prévia — nada foi gravado. Use --confirmar para gerar o link "
                  "(os links pendentes desta conta deixam de valer).")
            db.rollback()
            return 0

        agora = datetime.now(timezone.utc)
        # Invalida links pendentes do mesmo usuário: só o mais novo vale (como a
        # rota da escola, routers/admin.py::redefinir_senha).
        db.execute(
            update(TokenResetSenha)
            .where(TokenResetSenha.usuario_id == alvo.id,
                   TokenResetSenha.usado_em.is_(None))
            .values(usado_em=agora))
        token = gerar_token_reset()
        expira = agora + timedelta(minutes=settings.RESET_SENHA_EXPIRA_MIN)
        db.add(TokenResetSenha(usuario_id=alvo.id, token_hash=hash_token(token),
                               expira_em=expira, criado_por=autor.id))
        registrar(db, "usuario.reset_solicitado", escola_id=alvo.escola_id,
                  usuario_id=autor.id, entidade="usuario", entidade_id=alvo.id,
                  detalhes={"email": alvo.email, "origem": ORIGEM})  # nunca o token
        db.commit()

        link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/redefinir-senha?token={token}"
        print(f"\nlink de redefinição (uso único, vale {settings.RESET_SENHA_EXPIRA_MIN} "
              f"min, até {expira.isoformat()}) — entregue por canal seguro, ele NÃO "
              "será mostrado de novo:")
        print(link)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
