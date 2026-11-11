"""Recusa do Mérito para quem só tem matrícula num ano letivo já encerrado (S_G_VIRADA-3).

Depois da virada (escola em 2027), a formanda do 5º ano de 2026 não tem matrícula no
ano ativo. A recusa do certificado Geral dizia, para ela, o mesmo que para a criança
que perdeu a turma dentro do ano: "Coloque a criança numa turma do 1º ao 5º ano deste
ano letivo [...] Emita em seguida". Quem seguia punha no ranking, nas premiações e nos
certificados de 2027 uma criança que saiu da escola — e o certificado de 2026 seguia
sem caminho (voltar o ano é recusado). A recusa agora diz o que acontece: a matrícula
é só do ano encerrado e o Mérito é do ano ativo; e não manda pôr no ano novo quem saiu.

A criança que perdeu a matrícula DENTRO do ano (sem matrícula alguma) continua com a
orientação de sempre (``test_transferir_recalcula_posicao``). Dados fictícios.
"""
from datetime import date

from app.models import Aluno, Importacao, Matricula, Nota, SnapshotElefante, Turma

API = "/api/v1"
LEITOR = {"livros_unicos": 30, "tempo_leitura_min": 600,
          "questoes_tentativas": 100, "questoes_acertos": 100,
          "livros_por_nivel": {"D": 30}}


def _crianca(db, escola, nome, *, turma: Turma | None) -> Aluno:
    """Ativa, confirmada na Lista Piloto, com dado de leitura e a Nota do ano da
    escola (1ª colocada); matriculada em ``turma`` (no ano dela) ou em nenhuma."""
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo", da_lista_piloto=True)
    a.data_nascimento = date(2015, 6, 4)
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=turma.ano_letivo))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                            **LEITOR))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=escola.ano_letivo_ativo,
                nota_geral=70.0, nota_elefante=70.0, nota_matific=0.0,
                aferido_leitura=True, aferido_matematica=False, posicao=1))
    db.commit()
    return a


def test_merito_de_quem_so_tem_matricula_no_ano_encerrado_nao_manda_por_no_ano_novo(
        cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    quinto = Turma(escola_id=escola.id, nome="5º Ano A", ano_escolar="5º Ano",
                   ano_letivo=ano)
    db.add(quinto)
    db.flush()
    dora = _crianca(db, escola, "DORA FICTICIA MELO", turma=quinto)

    # Virada: o Admin Global passa a escola para o ano seguinte; a formanda saiu.
    virada = cliente_global.patch(f"{API}/escolas/{escola.id}",
                                  json={"ano_letivo_ativo": ano + 1})
    assert virada.status_code == 200, virada.text

    recusa = cliente.get(f"{API}/escolas/{escola.id}/certificados/{dora.id}")
    assert recusa.status_code == 409, recusa.text
    detalhe = recusa.json()["detail"]
    # Diz o que de fato acontece: matrícula só no ano encerrado; o Mérito é do ano ativo.
    assert f"só em {ano}" in detalhe, detalhe
    assert "encerrado" in detalhe, detalhe
    assert str(ano + 1) in detalhe, detalhe
    # E não manda matricular no ano novo quem saiu da escola.
    assert "deste ano letivo" not in detalhe, detalhe
    assert "Coloque a criança numa turma" not in detalhe, detalhe
    assert "Emita em seguida" not in detalhe, detalhe
    assert "não a coloque numa turma" in detalhe, detalhe

    # A prévia do lote (mesma guarda) dá o mesmo motivo.
    previa = cliente.post(f"{API}/escolas/{escola.id}/certificados/lote/previa",
                          json={"aluno_ids": [dora.id], "modelo": None})
    assert previa.status_code == 200, previa.text
    (item,) = previa.json()["itens"]
    assert item["apto"] is False and item["motivo"] == detalhe, item


def test_quem_perdeu_a_matricula_dentro_do_ano_segue_com_a_orientacao_de_sempre(
        cliente, db, escola_completa):
    escola = escola_completa["escola"]
    a = _crianca(db, escola, "CRIANCA FICTICIA SEM TURMA", turma=None)

    recusa = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert recusa.status_code == 409, recusa.text
    detalhe = recusa.json()["detail"]
    assert f"não tem matrícula no ano letivo {escola.ano_letivo_ativo}" in detalhe, detalhe
    assert "Coloque a criança numa turma do 1º ao 5º ano deste ano letivo" in detalhe, detalhe
