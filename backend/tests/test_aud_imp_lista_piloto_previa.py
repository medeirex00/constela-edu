"""Auditoria (frente importação): a prévia da Lista Piloto = a confirmação.

IMPORTACAO-10: ``/matriculas/analisar`` contava "novos × a atualizar" com um
casamento LEVE próprio (RA, ou nome idêntico + mesma sala), e a confirmação usa o
motor único (``matriculas.resolver_linha``), que reconhece nome completo × abreviado,
mudança de sala e grafia — ou manda para revisão. O modal "Gravar a Lista Piloto?"
prometia "2 aluno(s) novo(s) matriculado(s)" e a confirmação cadastrava 0 e mandava
2 para revisão. Agora a prévia passa pelas MESMAS decisões da confirmação, só
lendo (REV-IMP-2): novos, a atualizar e em revisão são os números que a confirmação
vai dar — e nada fica gravado pela prévia. Dados fictícios.
"""
from sqlalchemy import func, select

from tests.test_lista_piloto_identidade import CT_XLSX, _aluno, _planilha

API = "/api/v1"


def _post(cliente, eid, rota, conteudo):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/matriculas/{rota}",
                     files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def _contagens(db, eid):
    from app.models import Aluno, LogAuditoria, Matricula, Professor, Turma, Usuario
    db.expire_all()
    return {nome: db.scalar(select(func.count()).select_from(modelo))
            for nome, modelo in (("alunos", Aluno), ("turmas", Turma),
                                 ("matriculas", Matricula), ("usuarios", Usuario),
                                 ("professores", Professor), ("logs", LogAuditoria))}


def test_previa_conta_como_a_confirmacao(cliente, db, escola_completa):
    """A ficha "Ana Beatriz Souza" (3º Ano A) vem com o nome COMPLETO e o "João Pedro
    Barbosa" vem noutra sala: a confirmação não cria nenhum dos dois. A prévia diz o
    mesmo — e uma criança nova de verdade conta como nova."""
    eid = escola_completa["escola"].id
    conteudo = _planilha(
        ("3º ANO A", [_aluno("ANA BEATRIZ SOUZA LIMA", numero=1),
                      _aluno("CRIANCA FICTICIA NOVA DA LISTA", numero=2)]),
        ("4º ANO B", [_aluno("JOAO PEDRO BARBOSA", numero=1)]))
    antes = _contagens(db, eid)
    previa = _post(cliente, eid, "analisar", conteudo)
    assert _contagens(db, eid) == antes, "a prévia gravou alguma coisa"
    res = _post(cliente, eid, "confirmar", conteudo)
    assert (previa["alunos_novos"], previa["alunos_atualizar"], previa.get("alunos_em_revisao")) \
        == (res["alunos_criados"], res["alunos_atualizados"], res["alunos_em_revisao"]), (
        f"prévia {previa['alunos_novos']} novo(s) / {previa['alunos_atualizar']} a atualizar "
        f"/ {previa.get('alunos_em_revisao')} em revisão; confirmação "
        f"{ {k: v for k, v in res.items() if k not in ('avisos', 'mensagem')} }")
    assert res["alunos_criados"] == 1


def test_reenvio_da_mesma_lista_so_atualiza(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    conteudo = _planilha(("5º ANO C", [_aluno("CRIANCA FICTICIA UM", numero=1),
                                       _aluno("CRIANCA FICTICIA DOIS", numero=2)]))
    primeira = _post(cliente, eid, "analisar", conteudo)
    assert (primeira["alunos_novos"], primeira["alunos_atualizar"],
            primeira.get("alunos_em_revisao")) == (2, 0, 0)
    _post(cliente, eid, "confirmar", conteudo)
    antes = _contagens(db, eid)
    segunda = _post(cliente, eid, "analisar", conteudo)
    assert (segunda["alunos_novos"], segunda["alunos_atualizar"],
            segunda.get("alunos_em_revisao")) == (0, 2, 0)
    assert _contagens(db, eid) == antes
