"""Popula o banco com a configuração inicial do sistema.

Uso:
    python scripts/seed.py            # escola de demonstração + admin + padrões
    python scripts/seed.py --demo     # inclui turmas, alunos e dados de exemplo
    python scripts/seed.py --forcar   # semeia mesmo num banco que já tem dados

O seed é só para banco NOVO (instalação nova, desenvolvimento): antes de migrar ou
gravar qualquer coisa, ele recusa o banco que já tem escola que não é a dele ou conta
de administração global que não é a inicial (``dados_alheios``). Rodar de novo no
banco que ele mesmo semeou continua sem efeito. ``--forcar`` existe para o caso
consciente. ``--demo`` (crianças inventadas com notas) só roda com ENV de
desenvolvimento, com ou sem ``--forcar``.

Todos os valores criados aqui (pesos, níveis, critérios) são apenas o
ponto de partida descrito no PRD — depois do seed, a fonte da verdade é
o banco, editável pela interface.

Tudo o que o seed cria é FICTÍCIO, a começar pelo nome da escola
(``ESCOLA_DEMO``): a demonstração e os E2E não mostram nome de escola
real da rede (a matriz de prontidão, §4.1, proíbe nome real de escola em
tela de dado fictício). ``tests/test_seed_ficticio.py`` trava isso.
"""
import argparse
import os
import random
import secrets
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, inspect, select  # noqa: E402

from app.core.config import ENV_DE_DESENVOLVIMENTO, normalizar_env, settings  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.migracoes import aplicar_migracoes  # noqa: E402
from app.core.security import hash_senha, validar_forca_senha  # noqa: E402
from app.models import (  # noqa: E402
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    NivelDificuldade,
    Professor,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import scoring  # noqa: E402
from scripts._saida import forcar_saida_utf8  # noqa: E402

ANO_LETIVO = 2026

# Nome INVENTADO e inequivocamente fictício (a palavra está no nome). Antes era o
# nome de uma escola real da rede, que aparecia na demonstração e nos E2E.
ESCOLA_DEMO = "EMEF FICTÍCIA VILA CONSTELAÇÃO"
ADMIN_EMAIL = "admin@constela.local"
# Senha da conta inicial para deploy automatizado (docs/PUBLICAR.md, passo 5).
VAR_SENHA_ADMIN = "ADMIN_INITIAL_PASSWORD"

# Configuração inicial dos níveis de dificuldade (PRD §38).
# (nome, código estável, códigos de letra agrupados, pontos por livro)
NIVEIS_INICIAIS = [
    ("Pré-Leitor", "pre_leitor", ["AA", "BB", "CC", "DD"], 1.0),
    ("Nível 1", "nivel_1", ["A", "B", "C"], 2.0),
    ("Nível 2", "nivel_2", ["D", "E", "F", "G", "H", "I", "J"], 4.0),
    ("Nível 3", "nivel_3", ["K", "L", "M", "N", "O", "P", "Q", "R"], 8.0),
    ("Nível 4", "nivel_4", ["S", "T", "U", "V", "W", "X"], 12.0),
    ("Nível 5", "nivel_5", ["Y", "Z"], 16.0),
]

DEMO_ALUNOS = [
    "Ana Beatriz Souza", "Bruno Carvalho Lima", "Camila Ferreira Dias",
    "Davi Oliveira Santos", "Elisa Martins Rocha", "Felipe Andrade Costa",
    "Gabriela Nunes Pereira", "Heitor Silva Ramos", "Isabela Moreira Alves",
    "João Pedro Barbosa", "Larissa Cardoso Melo", "Miguel Teixeira Pinto",
    "Natália Ribeiro Gomes", "Otávio Fernandes Cruz", "Sofia Almeida Duarte",
]

DEMO_LIVROS = [
    ("O Gato e a Lua", "Clara Mendes", "AA"),
    ("A Formiga Curiosa", "Paulo Reis", "BB"),
    ("O Balão Vermelho", "Rita Campos", "CC"),
    ("Amigos do Quintal", "Clara Mendes", "A"),
    ("O Segredo do Rio", "Marcos Vila", "C"),
    ("Aventura na Floresta", "Paulo Reis", "E"),
    ("O Mapa Perdido", "Rita Campos", "G"),
    ("Viagem ao Fundo do Mar", "Marcos Vila", "J"),
    ("A Cidade das Estrelas", "Helena Prado", "L"),
    ("O Enigma da Biblioteca", "Helena Prado", "N"),
    ("Contos da Montanha", "Marcos Vila", "Q"),
    ("O Último Farol", "Helena Prado", "T"),
]


def _recusar(motivo: str) -> NoReturn:
    sys.stderr.write(f"Seed recusado: {motivo}\n")
    raise SystemExit(2)


def dados_alheios(motor) -> tuple[int, int]:
    """(escolas, contas de administração global) do banco que NÃO vieram deste seed.

    A escola do seed é a de demonstração (``ESCOLA_DEMO``) ou, num banco semeado
    quando ela tinha outro nome, a escola do admin inicial — a mesma regra de
    ``_escola_ja_semeada``. A conta global do seed é a do ``ADMIN_EMAIL``. Banco sem
    as tabelas (novo, antes das migrações) devolve (0, 0). Só lê, e só as colunas de
    que precisa: roda ANTES das migrações."""
    tabelas = set(inspect(motor).get_table_names())
    if not tabelas & {Escola.__tablename__, Usuario.__tablename__}:
        return 0, 0
    with motor.connect() as conn:
        escola_do_admin = conn.execute(
            select(Usuario.escola_id).where(Usuario.email == ADMIN_EMAIL)
        ).scalar_one_or_none()
        filtro_escola = [Escola.nome != ESCOLA_DEMO]
        if escola_do_admin is not None:
            filtro_escola.append(Escola.id != escola_do_admin)
        escolas = conn.execute(
            select(func.count()).select_from(Escola).where(*filtro_escola)
        ).scalar_one()
        globais = conn.execute(
            select(func.count()).select_from(Usuario)
            .where(Usuario.is_global.is_(True), Usuario.email != ADMIN_EMAIL)
        ).scalar_one()
    return escolas, globais


def _escola_ja_semeada(db) -> Escola | None:
    """A escola de um seed anterior: pelo nome de hoje ou, num banco semeado
    quando a escola de demonstração tinha OUTRO nome, pela escola do admin
    inicial — o e-mail é único, então criar de novo quebraria na constraint em
    vez de ser idempotente."""
    escola = db.execute(
        select(Escola).where(Escola.nome == ESCOLA_DEMO)
    ).scalar_one_or_none()
    if escola is not None:
        return escola
    admin = db.execute(
        select(Usuario).where(Usuario.email == ADMIN_EMAIL)
    ).scalar_one_or_none()
    if admin is None:
        return None
    if admin.escola_id is None:
        raise SystemExit(f"Seed recusado: {ADMIN_EMAIL} já existe sem escola; "
                         "não há escola de demonstração para reaproveitar.")
    return db.get(Escola, admin.escola_id)


def _senha_do_admin_inicial() -> tuple[str, bool]:
    """(senha, veio do ambiente?) da conta inicial de administração global.

    Sem ``ADMIN_INITIAL_PASSWORD``: aleatória, exibida UMA vez no console (nunca fixa
    no código ou na documentação). Com ela (deploy automatizado, cuja saída vai para
    log): passa pela regra de senha de todos os outros fluxos
    (``validar_forca_senha``) e nunca é impressa — fraca, o seed recusa antes de
    gravar qualquer coisa, sem ecoar a senha."""
    do_ambiente = os.environ.get(VAR_SENHA_ADMIN)
    if not do_ambiente:
        return secrets.token_urlsafe(9), False
    motivo = validar_forca_senha(do_ambiente, ADMIN_EMAIL)
    if motivo:
        _recusar(f"a senha de {VAR_SENHA_ADMIN} não passa na regra de senha do "
                 f"sistema: {motivo} Defina uma senha forte ou remova a variável para "
                 "o seed gerar uma aleatória.")
    return do_ambiente, True


def seed_base(db) -> Escola:
    escola = _escola_ja_semeada(db)
    if escola is not None:
        print("Seed já executado anteriormente — nada a fazer.")
        return escola

    senha_admin, do_ambiente = _senha_do_admin_inicial()

    escola = Escola(nome=ESCOLA_DEMO, ano_letivo_ativo=ANO_LETIVO)
    db.add(escola)
    db.flush()

    db.add(
        Usuario(
            escola_id=escola.id,
            nome="Administrador",
            email=ADMIN_EMAIL,
            senha_hash=hash_senha(senha_admin),
            cargo="admin",
            is_global=True,
        )
    )

    # Pesos iniciais (PRD §32, §34, §36, §41) — editáveis pela interface
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(
            Configuracao(escola_id=escola.id, namespace=namespace, chave="valores", valor=valores)
        )
    db.add(
        Configuracao(
            escola_id=escola.id,
            namespace="desempate",
            chave="criterios",
            valor=scoring.CRITERIOS_DESEMPATE_PADRAO,
        )
    )

    for ordem, (nome, codigo, codigos, pontos) in enumerate(NIVEIS_INICIAIS):
        db.add(
            NivelDificuldade(
                escola_id=escola.id, nome=nome, codigo=codigo, codigos=codigos,
                pontos_padrao=pontos, ordem=ordem,
            )
        )

    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
    db.commit()
    print(f"Escola {ESCOLA_DEMO} criada (id={escola.id}).")
    print("=" * 60)
    if do_ambiente:
        print("  USUÁRIO INICIAL:")
        print(f"    E-mail: {ADMIN_EMAIL}")
        print(f"    Senha:  a definida em {VAR_SENHA_ADMIN} (não é exibida)")
    else:
        print("  USUÁRIO INICIAL — anote agora (não será exibido de novo):")
        print(f"    E-mail: {ADMIN_EMAIL}")
        print(f"    Senha:  {senha_admin}")
    print("  Troque a senha no primeiro acesso, em Usuários.")
    print("=" * 60)
    return escola


def seed_demo(db, escola: Escola) -> None:
    if db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).first():
        print("Dados de demonstração já existem — nada a fazer.")
        return

    random.seed(42)

    prof_a = Professor(escola_id=escola.id, nome="Mariana Lopes")
    prof_b = Professor(escola_id=escola.id, nome="Carlos Eduardo Braga")
    db.add_all([prof_a, prof_b])
    db.flush()

    turmas = [
        Turma(escola_id=escola.id, nome="2º Ano A", ano_escolar="2º Ano",
              ano_letivo=ANO_LETIVO, professor_id=prof_a.id),
        Turma(escola_id=escola.id, nome="4º Ano A", ano_escolar="4º Ano",
              ano_letivo=ANO_LETIVO, professor_id=prof_a.id),
        Turma(escola_id=escola.id, nome="5º Ano A", ano_escolar="5º Ano",
              ano_letivo=ANO_LETIVO, professor_id=prof_b.id),
    ]
    db.add_all(turmas)
    db.flush()

    livros = [
        Livro(escola_id=escola.id, titulo=t, autor=a, nivel_codigo=n)
        for t, a, n in DEMO_LIVROS
    ]
    db.add_all(livros)
    db.flush()

    importacao_m = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed",
                              qtd_alunos=len(DEMO_ALUNOS))
    importacao_e = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed",
                              qtd_alunos=len(DEMO_ALUNOS))
    db.add_all([importacao_m, importacao_e])
    db.flush()

    for indice, nome in enumerate(DEMO_ALUNOS):
        turma = turmas[indice % len(turmas)]
        aluno = Aluno(escola_id=escola.id, nome=nome, numero_chamada=indice + 1)
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=ANO_LETIVO))

        # Matific — valores cumulativos plausíveis
        db.add(
            SnapshotMatific(
                escola_id=escola.id, aluno_id=aluno.id, importacao_id=importacao_m.id,
                atividades=random.randint(8, 120),
                estrelas=random.randint(40, 600),
                pontuacao_media=round(random.uniform(55, 98), 1),
            )
        )

        # Elefante Letrado — leituras únicas + snapshot derivado delas
        lidos = random.sample(livros, k=random.randint(1, 8))
        por_nivel: dict[str, int] = {}
        for livro in lidos:
            db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id))
            por_nivel[livro.nivel_codigo] = por_nivel.get(livro.nivel_codigo, 0) + 1
        tentativas = len(lidos) * random.randint(3, 6)
        db.add(
            SnapshotElefante(
                escola_id=escola.id, aluno_id=aluno.id, importacao_id=importacao_e.id,
                livros_unicos=len(lidos),
                tempo_leitura_min=len(lidos) * random.randint(15, 40),
                questoes_tentativas=tentativas,
                questoes_acertos=int(tentativas * random.uniform(0.5, 0.95)),
                livros_por_nivel=por_nivel,
            )
        )

    db.commit()
    total = scoring.recalcular_escola(db, escola.id)
    print(f"Dados de demonstração criados: {total} alunos com notas e ranking calculados.")


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Configuração inicial de um banco NOVO.")
    p.add_argument("--demo", action="store_true",
                   help="inclui turmas, alunos inventados e dados de exemplo (só em dev)")
    p.add_argument("--forcar", action="store_true",
                   help="semeia mesmo num banco que já tem escolas ou contas globais")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    forcar_saida_utf8()
    args = _argumentos(argv)
    # As travas vêm ANTES das migrações e de qualquer gravação.
    if args.demo and normalizar_env(settings.ENV) not in ENV_DE_DESENVOLVIMENTO:
        _recusar(f"--demo cria crianças inventadas com notas e só roda com ENV de "
                 f"desenvolvimento (aqui ENV={settings.ENV or 'vazio'}). Para uma "
                 "demonstração, use um banco próprio com ENV=dev.")
    escolas, globais = dados_alheios(engine)
    if (escolas or globais) and not args.forcar:
        _recusar(f"este banco já tem dados que não vieram do seed: {escolas} escola(s) e "
                 f"{globais} conta(s) de administração global. O seed é só para banco "
                 "NOVO (instalação nova ou desenvolvimento): num banco em uso ele pode "
                 "criar outra conta de administração global, a escola de demonstração e, "
                 "com --demo, crianças inventadas. Confira a DATABASE_URL. Se tiver "
                 "certeza, rode de novo com --forcar.")
    aplicar_migracoes(engine)   # cria o schema (banco novo) já versionado no Alembic
    db = SessionLocal()
    try:
        escola = seed_base(db)
        if args.demo:
            seed_demo(db, escola)
    finally:
        db.close()


if __name__ == "__main__":
    main()
