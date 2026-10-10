"""Cenário sintético compartilhado pelos testes de segurança do P0
(``test_p0_professor_email.py`` e ``test_contestar_p0.py``).

Cópia FIEL do fixture ``mundo`` de ``tests/test_isolamento_escopo.py`` (linha
de trabalho da Fase 3A, ainda fora do ``main``): duas redes, duas escolas,
contas de gestão, professor, Secretaria e global — todas com e-mail
``@sint.local`` e nomes sintéticos. Quando ``test_isolamento_escopo.py`` entrar
no ``main``, os dois testes podem voltar a importar o fixture de lá e este
módulo some. Não começa com ``test_``: o pytest não o coleta como teste.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Escola, Livro, Matricula, Nota, Professor, Rede,
                        Turma, Usuario)

A25, A26, B26, OUTRA = ("ALUNO_PROFESSOR_A_2025", "ALUNO_PROFESSOR_A_2026",
                        "ALUNO_PROFESSOR_B_2026", "ALUNO_OUTRA_ESCOLA")
SENHA = "s3nh4-sintetica"


class Mundo:
    def __init__(self, db):
        self.db = db
        self.ids: dict[str, int] = {}
        self._clientes: dict[str, TestClient] = {}

    def cli(self, quem: str) -> TestClient:
        if quem not in self._clientes:
            c = TestClient(app)
            r = c.post("/api/v1/auth/login",
                       data={"username": f"{quem}@sint.local", "password": SENHA})
            assert r.status_code == 200, (quem, r.text)
            c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            self._clientes[quem] = c
        return self._clientes[quem]


@pytest.fixture()
def mundo(db, monkeypatch, tmp_path):
    # As exportações gravam uma cópia em EXPORTS_DIR; o teste não suja o repo.
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    m = Mundo(db)
    r1, r2 = Rede(nome="REDE_SINT_1"), Rede(nome="REDE_SINT_2")
    db.add_all([r1, r2]); db.flush()
    x = Escola(nome="ESCOLA_X_SINTETICA", ano_letivo_ativo=2026, rede_id=r1.id)
    y = Escola(nome="ESCOLA_Y_SINTETICA", ano_letivo_ativo=2026)
    db.add_all([x, y]); db.flush()
    m.ids.update(x=x.id, y=y.id, r1=r1.id, r2=r2.id)

    def usuario(apelido, escola, cargo, **kw):
        u = Usuario(escola_id=escola, nome=apelido.upper(), email=f"{apelido}@sint.local",
                    senha_hash=hash_senha(SENHA), cargo=cargo, **kw)
        db.add(u); db.flush()
        m.ids["u_" + apelido] = u.id
        return u

    usuario("coord_x", x.id, "coordenador")
    usuario("admin_x", x.id, "admin")
    usuario("prof_a", x.id, "professor")
    usuario("prof_b", x.id, "professor")
    usuario("coord_y", y.id, "coordenador")
    usuario("sec_r1", None, "coordenador", rede_id=r1.id)
    usuario("sec_r2", None, "coordenador", rede_id=r2.id)
    # Secretaria PROMOVIDA a partir de uma conta de escola: guarda o escola_id e
    # o cargo de origem (rede.definir_usuarios). Uma na rede da própria escola,
    # outra numa rede que não é a da escola de origem.
    usuario("secadm_x", x.id, "admin", rede_id=r1.id)
    usuario("secadm_y", y.id, "admin", rede_id=r2.id)
    usuario("global", x.id, "admin", is_global=True)

    pa = Professor(escola_id=x.id, nome="PROF_A_SINT", email="prof_a@sint.local")
    pb = Professor(escola_id=x.id, nome="PROF_B_SINT", email="prof_b@sint.local")
    pc = Professor(escola_id=y.id, nome="PROF_C_Y_SINT", email="prof_c@sint.local")
    db.add_all([pa, pb, pc]); db.flush()

    def turma(chave, escola, nome, ano, prof):
        # "5º Ano B" -> série "5º Ano"
        t = Turma(escola_id=escola, nome=nome, ano_escolar=nome.rsplit(" ", 1)[0],
                  ano_letivo=ano, professor_id=prof.id)
        db.add(t); db.flush()
        m.ids[chave] = t.id
        return t

    t_a25 = turma("t_a25", x.id, "5º Ano B", 2025, pa)
    t_a26 = turma("t_a26", x.id, "4º Ano A", 2026, pa)
    t_b26 = turma("t_b26", x.id, "5º Ano B", 2026, pb)
    t_y = turma("t_y", y.id, "4º Ano A", 2026, pc)

    def aluno(nome, escola, t, ano, posicao):
        a = Aluno(escola_id=escola, nome=nome)
        db.add(a); db.flush()
        db.add(Matricula(escola_id=escola, aluno_id=a.id, turma_id=t.id, ano_letivo=ano))
        db.add(Nota(escola_id=escola, aluno_id=a.id, ano_letivo=ano,
                    nota_elefante=70.0 + posicao, nota_matific=60.0 + posicao,
                    nota_geral=65.0 + posicao, posicao=posicao,
                    aferido_leitura=True, aferido_matematica=True,
                    posicao_leitura=posicao, posicao_matematica=posicao))
        m.ids[nome] = a.id
        return a

    aluno(A25, x.id, t_a25, 2025, 1)
    aluno(A26, x.id, t_a26, 2026, 2)
    aluno(B26, x.id, t_b26, 2026, 1)
    aluno(OUTRA, y.id, t_y, 2026, 1)
    livro_y = Livro(escola_id=y.id, titulo="LIVRO_SINT_ESCOLA_Y", nivel_codigo="A")
    db.add(livro_y); db.flush()
    m.ids["livro_y"] = livro_y.id
    db.commit()
    return m
