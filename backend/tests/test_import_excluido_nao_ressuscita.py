"""Regressão: o guard de idempotência da importação NÃO reusa aluno soft-excluído.

`excluir` é delete LÓGICO (status='excluido') e NÃO remove a Matrícula. Antes,
`_aluno_existente_na_turma` (idempotência do /confirmar por nome exato) consultava
a turma SEM filtrar status, então uma reimportação do mesmo nome "ressuscitava" a
criança excluída — gravando um snapshot novo nela e divergindo da prévia/roster,
que já ignoram excluídos. Agora ele os ignora (alinhado a `_roster_identidades`):
o excluído não é reusado; o motor cria um aluno ATIVO novo. Arquivado
(status != 'excluido') continua reusável — não vira duplicata na reimportação.
"""
from app.routers.importacoes import _aluno_existente_na_turma


def test_nao_reusa_aluno_excluido(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    ano = escola.ano_letivo_ativo
    aluno = escola_completa["alunos"][0]

    # Controle: ativo com o mesmo nome É reusado (idempotência funciona).
    assert _aluno_existente_na_turma(db, escola.id, ano, turma.id, aluno.nome) is not None

    # Soft-delete e re-consulta: agora NÃO é reusado (não ressuscita o excluído).
    aluno.status = "excluido"
    db.flush()
    assert _aluno_existente_na_turma(db, escola.id, ano, turma.id, aluno.nome) is None


def test_reusa_aluno_arquivado(db, escola_completa):
    """`!= 'excluido'` ainda inclui arquivado — arquivado permanece reusável."""
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    ano = escola.ano_letivo_ativo
    aluno = escola_completa["alunos"][1]

    aluno.status = "arquivado"
    db.flush()
    achado = _aluno_existente_na_turma(db, escola.id, ano, turma.id, aluno.nome)
    assert achado is not None and achado.id == aluno.id
