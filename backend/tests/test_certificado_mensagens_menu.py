"""As recusas do certificado dizem o caminho que EXISTE no menu de hoje.

Quem recebe o 409 precisa achar a saída. As mensagens citavam o menu antigo —
"Estrutura › Matrículas", "Alunos › Duplicatas", "Estrutura › Turmas" e "Alunos ›
Reativar" (a lista de Alunos só mostra os ativos) —, que não existe mais na barra
da coordenação (``apps/web/src/components/Layout.tsx``: "Minha Escola" e "Dados e
integrações"). Os caminhos novos são os mesmos da página de Suporte
(``apps/web/src/pages/suporteConteudo.ts``). Dados fictícios.

A professora também emite (Meus Relatórios, só dos alunos dela), mas não abre
nenhuma dessas telas — nem o menu do aluno: para ela, as recusas dizem o que
pedir à coordenação da escola.
"""
import pathlib
import re
from datetime import date

from app.models import Aluno, Matricula, Nota, Turma
from tests.test_permissoes import cenario_professor  # noqa: F401 — fixture

API = "/api/v1"
MENU_ANTIGO = ("Estrutura ›", "Alunos › Duplicatas", "Alunos › Reativar", "› Matrículas")
SINCRONIZACAO_TSX = (pathlib.Path(__file__).resolve().parents[2]
                     / "apps" / "web" / "src" / "pages" / "Sincronizacao.tsx")
# Telas e menus que só a gestão abre — nenhum deles pode aparecer como "faça você".
TELAS_DA_GESTAO = ("Dados e integrações", "três pontinhos", "“Editar dados”",
                   "“Fundir duplicatas”", "“Mostrar arquivados”", "Importe", "Coloque")


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
    assert "Dados e integrações › Integrações" in detalhe
    assert "Minha Escola › Alunos › “Fundir duplicatas”" in detalhe


def test_ficha_sem_lista_piloto_cita_os_dois_nomes_do_botao(cliente, db, escola_completa):
    """Na escola que nunca importou a Lista Piloto — onde TODA ficha cai nesta
    recusa — o botão de Integrações se chama "Importar Lista Piloto"; depois da
    primeira importação, "Atualizar Lista Piloto". A mensagem cita os dois, e os
    dois existem em Sincronizacao.tsx."""
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "CRIANCA FICTICIA ESCOLA SEM LISTA", piloto=False, turma=_turma(db, escola))
    detalhe = _recusa(cliente, escola, a)
    assert "(botão “Importar Lista Piloto” ou “Atualizar Lista Piloto”)" in detalhe
    fonte = SINCRONIZACAO_TSX.read_text(encoding="utf-8")
    for botao in re.findall(r"botão “([^”]+)” ou “([^”]+)”", detalhe)[0]:
        assert f'"{botao}"' in fonte, botao


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


# --- A professora: o que pedir à coordenação --------------------------------------

def _turma_da_professora(db, c, nome, ano_escolar):
    t = Turma(escola_id=c["escola"].id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=c["escola"].ano_letivo_ativo, status="ativa",
              professor_id=c["turma_a"].professor_id)
    db.add(t)
    db.flush()
    return t


def _recusa_da_professora(c, aluno, status_esperado=409) -> str:
    r = c["professor"].get(f"{API}/escolas/{c['escola'].id}/certificados/{aluno.id}")
    assert r.status_code == status_esperado, r.text
    detalhe = r.json()["detail"]
    assert "Peça à coordenação da escola" in detalhe, detalhe
    for tela in TELAS_DA_GESTAO:
        assert tela not in detalhe, (tela, detalhe)
    return detalhe


def test_professora_sem_lista_piloto_e_mandada_a_coordenacao(db, cenario_professor):
    c = cenario_professor
    a = _aluno(db, c["escola"], "CRIANCA FICTICIA DA PROFESSORA SEM LISTA", piloto=False,
               turma=c["turma_a"])
    detalhe = _recusa_da_professora(c, a)
    assert "importar ou atualizar a Lista Piloto" in detalhe


def test_professora_turma_sem_serie_e_mandada_a_coordenacao(db, cenario_professor):
    c = cenario_professor
    a = _aluno(db, c["escola"], "CRIANCA FICTICIA EM TURMA SEM SERIE",
               turma=_turma_da_professora(db, c, "Turma Projeto", ""))
    detalhe = _recusa_da_professora(c, a)
    assert "colocar a criança numa turma do 1º ao 5º ano" in detalhe


def test_professora_sem_nota_e_mandada_a_coordenacao(db, cenario_professor):
    c = cenario_professor
    a = Aluno(escola_id=c["escola"].id, nome="CRIANCA FICTICIA SEM NOTA", status="ativo",
              da_lista_piloto=True)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=c["escola"].id, aluno_id=a.id, turma_id=c["turma_a"].id,
                     ano_letivo=c["escola"].ano_letivo_ativo))
    db.commit()
    detalhe = _recusa_da_professora(c, a, status_esperado=422)
    assert "importar ou sincronizar os dados das plataformas" in detalhe


def test_professora_nao_chega_a_recusa_de_situacao(db, cenario_professor):
    """Aluno que não está ativo é 404 para a professora (só os ativos das turmas
    dela) — a recusa de situação, que cita Minha Escola › Turmas, é só da gestão."""
    c = cenario_professor
    a = _aluno(db, c["escola"], "CRIANCA FICTICIA ARQUIVADA DA PROFESSORA",
               status="arquivado", turma=c["turma_a"])
    r = c["professor"].get(f"{API}/escolas/{c['escola'].id}/certificados/{a.id}")
    assert r.status_code == 404, r.text


def test_coordenacao_continua_com_o_caminho_do_menu(db, cenario_professor):
    c = cenario_professor
    a = _aluno(db, c["escola"], "CRIANCA FICTICIA SEM LISTA DA COORDENACAO", piloto=False,
               turma=c["turma_a"])
    r = c["coordenador"].get(f"{API}/escolas/{c['escola'].id}/certificados/{a.id}")
    assert r.status_code == 409, r.text
    assert "Dados e integrações › Integrações" in r.json()["detail"]
    assert "Peça à coordenação" not in r.json()["detail"]
