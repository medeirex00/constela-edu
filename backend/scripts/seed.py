"""Popula o banco com a configuração inicial do sistema.

Uso:
    python scripts/seed.py            # escola JORGE PASSOS + admin + padrões
    python scripts/seed.py --demo     # inclui turmas, alunos e dados de exemplo

Todos os valores criados aqui (pesos, níveis, critérios) são apenas o
ponto de partida descrito no PRD — depois do seed, a fonte da verdade é
o banco, editável pela interface.
"""
import os
import random
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.migracoes import aplicar_migracoes  # noqa: E402
from app.core.security import hash_senha  # noqa: E402
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

ANO_LETIVO = 2026

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


def seed_base(db) -> Escola:
    escola = db.execute(
        select(Escola).where(Escola.nome == "JORGE PASSOS")
    ).scalar_one_or_none()
    if escola is not None:
        print("Seed já executado anteriormente — nada a fazer.")
        return escola

    escola = Escola(nome="JORGE PASSOS", ano_letivo_ativo=ANO_LETIVO)
    db.add(escola)
    db.flush()

    # Senha inicial: aleatória e exibida UMA vez no console (nunca fixa no
    # código/documentação). Override por ambiente para deploys automatizados.
    senha_admin = os.environ.get("ADMIN_INITIAL_PASSWORD") or secrets.token_urlsafe(9)
    db.add(
        Usuario(
            escola_id=escola.id,
            nome="Administrador",
            email="admin@constela.local",
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
    print(f"Escola JORGE PASSOS criada (id={escola.id}).")
    print("=" * 60)
    print("  USUÁRIO INICIAL — anote agora (não será exibido de novo):")
    print(f"    E-mail: admin@constela.local")
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


def main() -> None:
    aplicar_migracoes(engine)   # cria o schema (banco novo) já versionado no Alembic
    db = SessionLocal()
    try:
        escola = seed_base(db)
        if "--demo" in sys.argv:
            seed_demo(db, escola)
    finally:
        db.close()


if __name__ == "__main__":
    main()
