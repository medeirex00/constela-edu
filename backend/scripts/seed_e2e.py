"""Seed DETERMINÍSTICO para os testes E2E (Playwright).

Reseta o banco de teste e cria dados conhecidos:
  * escola de demonstração FICTÍCIA (``seed.ESCOLA_DEMO``) + demonstração
    (turmas, alunos, snapshots e ranking já calculado) — reaproveita o seed
    oficial (scripts/seed.py);
  * três contas com senhas FIXAS (de variáveis de ambiente) para exercitar
    login, cadastro, CRUD e permissões:
      - admin@constela.local  (admin global)   -> ADMIN_INITIAL_PASSWORD
      - coord@constela.local  (coordenador)    -> COORD_PASSWORD
      - prof@constela.local   (professor)      -> PROF_PASSWORD
  * o Professor E2E como titular das turmas da professora "Mariana Lopes" do seed
    (o vínculo é pelo e-mail do cadastro de Professor): a visão do professor tem
    alunos de verdade, só os dessas turmas;
  * os alunos da demonstração CONFIRMADOS na Lista Piloto (`da_lista_piloto`),
    menos um (``ALUNO_SEM_LISTA_PILOTO``): o lote de certificados do E2E gera o PDF
    dos confirmados e mostra a recusa, com o motivo, do que não está na lista.

NUNCA rode este script em produção: as senhas são conhecidas por definição.
Ele exige DATABASE_URL apontando para um SQLite de teste (ex.: ./e2e.db) e
APAGA esse arquivo antes de recriar o schema, garantindo um estado limpo a
cada execução.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# --- Reset ANTES de importar o app -------------------------------------------
# O engine do SQLAlchemy é criado no import de app.core.database a partir da
# DATABASE_URL; por isso apagamos o arquivo do SQLite aqui, antes disso.
_URL = os.environ.get("DATABASE_URL", "")
if _URL.startswith("sqlite") and ":///" in _URL:
    _caminho = _URL.split(":///", 1)[1]
    if _caminho and _caminho != ":memory:":
        _arq = Path(_caminho)
        if not _arq.is_absolute():
            _arq = Path.cwd() / _arq
        for sufixo in ("", "-wal", "-shm", "-journal"):
            try:
                Path(str(_arq) + sufixo).unlink()
            except FileNotFoundError:
                pass

from sqlalchemy import select, update  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.migracoes import aplicar_migracoes  # noqa: E402
from app.core.security import hash_senha  # noqa: E402
from app.models import Aluno, Professor, Usuario  # noqa: E402
from scripts.seed import seed_base, seed_demo  # noqa: E402
from scripts._saida import forcar_saida_utf8  # noqa: E402

COORD_EMAIL = "coord@constela.local"
# Fica FORA da Lista Piloto: é o 1º do Ranking Geral do seed, então o Top 3 do lote
# mostra os dois caminhos (aptos e uma recusa com motivo).
ALUNO_SEM_LISTA_PILOTO = "Otávio Fernandes Cruz"
# Cadastro de Professor do seed cujas turmas ficam com a conta prof@ (e-mail igual).
PROFESSOR_DO_PROF_E2E = "Mariana Lopes"
PROF_EMAIL = "prof@constela.local"


def _garantir_usuario(db, escola_id: int, nome: str, email: str, senha: str, cargo: str) -> None:
    ja = db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
    if ja is not None:
        return
    db.add(Usuario(escola_id=escola_id, nome=nome, email=email,
                   senha_hash=hash_senha(senha), cargo=cargo, is_global=False))


def main() -> None:
    forcar_saida_utf8()
    # O script APAGA e repovoa o banco com contas de senha conhecida (padrão
    # publicado no repositório): só existe para o SQLite descartável do E2E.
    from app.core.config import settings
    if settings.em_producao or not settings.DATABASE_URL.startswith("sqlite"):
        raise SystemExit("seed_e2e recusado: só roda fora de produção e com "
                         "DATABASE_URL apontando para um SQLite de teste.")
    aplicar_migracoes(engine)
    db = SessionLocal()
    try:
        escola = seed_base(db)          # escola + admin global (ADMIN_INITIAL_PASSWORD)
        seed_demo(db, escola)           # turmas, alunos, snapshots e ranking calculado
        db.execute(update(Aluno)
                   .where(Aluno.escola_id == escola.id, Aluno.nome != ALUNO_SEM_LISTA_PILOTO)
                   .values(da_lista_piloto=True))
        db.execute(update(Professor)
                   .where(Professor.escola_id == escola.id, Professor.nome == PROFESSOR_DO_PROF_E2E)
                   .values(email=PROF_EMAIL))
        _garantir_usuario(db, escola.id, "Coordenadora E2E", COORD_EMAIL,
                          os.environ.get("COORD_PASSWORD", "CoordE2E@2026"), "coordenador")
        _garantir_usuario(db, escola.id, "Professor E2E", PROF_EMAIL,
                          os.environ.get("PROF_PASSWORD", "ProfE2E@2026"), "professor")
        db.commit()
        print("Seed E2E pronto: admin global + coordenador + professor + demo.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
