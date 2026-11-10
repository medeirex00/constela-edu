"""As recusas do certificado dizem o caminho que EXISTE no menu de hoje.

Quem recebe o 409 precisa achar a saída. As mensagens citavam o menu antigo —
"Estrutura › Matrículas", "Alunos › Duplicatas", "Estrutura › Turmas" e "Alunos ›
Reativar" (a lista de Alunos só mostra os ativos) —, que não existe mais na barra
da coordenação (``apps/web/src/components/Layout.tsx``: "Minha Escola" e "Dados e
integrações"). Os caminhos novos são os mesmos da página de Suporte
(``apps/web/src/pages/suporteConteudo.ts``). Dados fictícios.
"""
from datetime import date

from app.models import Aluno, Matricula, Nota, Turma

API = "/api/v1"
MENU_ANTIGO = ("Estrutura ›", "Alunos › Duplicatas", "Alunos › Reativar", "› Matrículas")


def _aluno(db, escola, nome, *, piloto=True, status="ativo", turma=None):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, da_lista_piloto=piloto)
    a.data_nascimento = date(2017, 5, 5)
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=escola.ano_letivo_ativo))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=escola.ano_letivo_ativo,
                nota_geral=70.0, nota_elefante=70.0, nota_matific=70.0,
                aferido_leitura=True, aferido_matematica=True, posicao=5))
    db.commit()
    return a


def _recusa(cliente, escola, aluno) -> str:
    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{aluno.id}")
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    for antigo in MENU_ANTIGO:
        assert antigo not in detalhe, (antigo, detalhe)
    return detalhe


def _turma(db, escola):
    t = Turma(escola_id=escola.id, nome="4º Ano Q", ano_escolar="4º Ano",
              ano_letivo=escola.ano_letivo_ativo, status="ativa")
    db.add(t)
    db.flush()
    return t


def test_ficha_sem_lista_piloto_aponta_integracoes_e_fundir_duplicatas(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "CRIANCA FICTICIA SEM CONFIRMACAO", piloto=False, turma=_turma(db, escola))
    detalhe = _recusa(cliente, escola, a)
    assert "Dados e integrações › Integrações › “Atualizar Lista Piloto”" in detalhe
    assert "Minha Escola › Alunos › “Fundir duplicatas”" in detalhe


def test_sem_matricula_no_ano_aponta_editar_dados_no_perfil(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "CRIANCA FICTICIA SEM TURMA", turma=None)
    detalhe = _recusa(cliente, escola, a)
    assert "três pontinhos › “Editar dados” › Turma" in detalhe
    # A troca de turma recalcula as notas (``test_transferir_recalcula_posicao``):
    # a mensagem diz isso, em vez de mandar esperar um recálculo que a pessoa não
    # sabe quando vem nem como provocar.
    assert "a troca de turma já recalcula as notas e dá a posição atual" in detalhe
    assert "Emita em seguida" in detalhe
    assert "próximo recálculo" not in detalhe


def test_situacao_inativa_aponta_reativar_na_turma(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "CRIANCA FICTICIA ARQUIVADA", status="arquivado", turma=_turma(db, escola))
    detalhe = _recusa(cliente, escola, a)
    assert "Minha Escola › Turmas" in detalhe
    assert "“Mostrar arquivados”" in detalhe and "“Reativar”" in detalhe
