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
Ele exige DATABASE_URL EXPORTADA no ambiente, apontando para um SQLite de teste
(ex.: ``DATABASE_URL=sqlite:///./e2e.db``, o do ``playwright.config.ts``), e APAGA
esse arquivo antes de recriar o schema, garantindo um estado limpo a cada execução
(``banco_de_teste``). Sem a variável ele recusa: o app cairia no banco do ``.env``
ou no de desenvolvimento, e o script semearia por cima dele. A trava e o
apagamento olham a MESMA URL — a do engine do app, que é onde o seed grava — e o
banco de desenvolvimento padrão (``database/sgpe.db``) nunca é apagado.
"""
import os
import sys
from pathlib import Path
from typing import NoReturn

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, update  # noqa: E402

from app.core.config import PROJECT_ROOT, settings  # noqa: E402
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


# O banco de DESENVOLVIMENTO padrão (o do config sem DATABASE_URL): este script nunca
# o apaga, nem com a variável apontando para ele.
BANCO_DE_DESENVOLVIMENTO = PROJECT_ROOT / "database" / "sgpe.db"
SUFIXOS_DO_SQLITE = ("", "-wal", "-shm", "-journal")


def _recusar(motivo: str) -> NoReturn:
    sys.stderr.write(f"seed_e2e recusado: {motivo}\n")
    raise SystemExit(2)


def _mesmo_arquivo(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def banco_de_teste() -> Path:
    """O arquivo SQLite que o script vai APAGAR e recriar: o do engine do app
    (``engine.url``), o MESMO que a trava confere e onde o seed grava. Recusa (código
    2) sem DATABASE_URL exportada, em produção, fora de um arquivo SQLite, no banco de
    desenvolvimento padrão e com alvo que não é arquivo comum (atalho, pasta)."""
    if not os.environ.get("DATABASE_URL", "").strip():
        _recusar("defina DATABASE_URL no ambiente com o SQLite de TESTE que pode ser "
                 "apagado (ex.: DATABASE_URL=sqlite:///./e2e.db). Sem ela, o script "
                 "escreveria por cima do banco do .env ou do de desenvolvimento.")
    if settings.em_producao:
        _recusar("só roda fora de produção: as senhas das contas de teste são conhecidas.")
    url = engine.url
    if (url.get_backend_name() != "sqlite" or not url.database
            or url.database.startswith(":memory:") or url.query):
        _recusar("a DATABASE_URL precisa apontar para um ARQUIVO SQLite de teste, sem "
                 "parâmetros (ex.: sqlite:///./e2e.db).")
    arquivo = Path(url.database)
    if not arquivo.is_absolute():
        arquivo = Path.cwd() / arquivo
    if arquivo.is_symlink() or (arquivo.exists() and not arquivo.is_file()):
        _recusar(f"o alvo da DATABASE_URL não é um arquivo comum: {arquivo}")
    if _mesmo_arquivo(arquivo, BANCO_DE_DESENVOLVIMENTO):
        _recusar("a DATABASE_URL aponta para o banco de desenvolvimento "
                 "(database/sgpe.db), que este script nunca apaga. Use um arquivo "
                 "próprio para o E2E (ex.: sqlite:///./e2e.db).")
    return arquivo


def _apagar(arquivo: Path) -> None:
    engine.dispose()        # nenhuma conexão do pool segura o arquivo (Windows)
    for sufixo in SUFIXOS_DO_SQLITE:
        try:
            Path(str(arquivo) + sufixo).unlink()
        except FileNotFoundError:
            pass


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
    _apagar(banco_de_teste())
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
