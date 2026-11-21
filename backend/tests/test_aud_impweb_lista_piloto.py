"""Auditoria (Lista Piloto): a prévia e o modal "Gravar a Lista Piloto?" dizem quantos
ficam em revisão.

IMPORTACAO-10 (parte da tela): a prévia e o modal prometiam "N aluno(s) novo(s)
matriculado(s)" para quem a confirmação reconhece ou manda para revisão. O backend já
conta como a confirmação (``alunos_em_revisao`` na prévia); aqui, as respostas REAIS
(/matriculas/analisar e /matriculas/confirmar) que AudListaPilotoPrevia.test.tsx usa.
Para regravar: ``GERAR_FIXTURES_IMPORTACAO=1``. Dados fictícios.
"""
from tests.aud_impweb_exemplos import API, _exemplo
from tests.test_lista_piloto_identidade import CT_XLSX, _aluno, _planilha


def _post(cliente, eid, rota, conteudo):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/matriculas/{rota}",
                     files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def test_previa_e_confirmacao_com_linhas_em_revisao(cliente, db, escola_completa):
    """"ANA BEATRIZ SOUZA LIMA" (a ficha é "Ana Beatriz Souza") e o "João Pedro Barbosa"
    noutra sala: nenhum dos dois é criado — ficam em revisão. Só a criança nova de
    verdade é cadastrada. A prévia dá os três números da confirmação."""
    eid = escola_completa["escola"].id
    conteudo = _planilha(
        ("3º ANO A", [_aluno("ANA BEATRIZ SOUZA LIMA", numero=1),
                      _aluno("CRIANCA FICTICIA NOVA DA LISTA", numero=2)]),
        ("4º ANO B", [_aluno("JOAO PEDRO BARBOSA", numero=1)]))
    previa = _post(cliente, eid, "analisar", conteudo)
    assert (previa["total_alunos"], previa["alunos_novos"], previa["alunos_atualizar"],
            previa["alunos_em_revisao"]) == (3, 1, 0, 2)
    _exemplo("lista_piloto_analise.json", previa)
    resultado = _post(cliente, eid, "confirmar", conteudo)
    assert (resultado["alunos_criados"], resultado["alunos_atualizados"],
            resultado["alunos_em_revisao"]) == (1, 0, 2)
    _exemplo("lista_piloto_confirmar.json", resultado)
