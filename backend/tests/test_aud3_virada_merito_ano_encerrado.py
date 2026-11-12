"""Recusa do Mérito para quem só tem matrícula num ano letivo já encerrado (S_G_VIRADA-3).

Depois da virada (escola em 2027), a formanda do 5º ano de 2026 não tem matrícula no
ano ativo. A recusa do certificado Geral dizia, para ela, o mesmo que para a criança
que perdeu a turma dentro do ano: "Coloque a criança numa turma do 1º ao 5º ano deste
ano letivo [...] Emita em seguida". Quem seguia punha no ranking, nas premiações e nos
certificados de 2027 uma criança que saiu da escola — e o certificado de 2026 seguia
sem caminho (voltar o ano é recusado). A recusa agora diz o que acontece: a matrícula
é só do ano encerrado e o Mérito é do ano ativo; e não manda pôr no ano novo quem saiu.

A recusa também não diz que a posição do ano encerrado "não vale mais" (REV3-VIRADA-3):
depois da virada, a Nota guardada é o resultado oficial daquele ano, histórico que não é
reescrito. E fala de "a criança", não de "ela" sem antecedente (o nome vem entre aspas,
e o texto ficava errado para meninos).

A criança que perdeu a matrícula DENTRO do ano (sem matrícula alguma) continua com a
orientação de sempre (``test_transferir_recalcula_posicao``). Dados fictícios.
"""
from datetime import date

from sqlalchemy import delete

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
    # A Nota de 2026 é o resultado oficial do ano encerrado: não "deixou de valer".
    assert "não vale mais" not in detalhe and "cálculo antigo" not in detalhe, detalhe
    assert f"A nota e a posição de {ano} continuam guardadas" in detalhe, detalhe
    assert f"no ranking de {ano + 1} a criança não está" in detalhe, detalhe

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


def _virar(cliente_global, escola):
    virada = cliente_global.patch(f"{API}/escolas/{escola.id}",
                                  json={"ano_letivo_ativo": escola.ano_letivo_ativo + 1})
    assert virada.status_code == 200, virada.text


def test_recusa_do_formando_nao_diz_que_a_posicao_do_ano_encerrado_nao_vale(
        cliente, cliente_global, db, escola_completa):
    """Sonda do revisor (REV3-VIRADA-3): formando, 5º Ano A de 2026 com Nota 70,0 e 1º
    lugar; o Admin Global vira para 2027. A Nota de 2026 continua lá, e a recusa não pode
    fazer a coordenação ler que o 1º lugar dele foi invalidado — nem tratá-lo por "ela"."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    quinto = Turma(escola_id=escola.id, nome="5º Ano A", ano_escolar="5º Ano", ano_letivo=ano)
    db.add(quinto)
    db.flush()
    beto = _crianca(db, escola, "BETO FICTICIO LIMA", turma=quinto)
    _virar(cliente_global, escola)

    recusa = cliente.get(f"{API}/escolas/{escola.id}/certificados/{beto.id}")
    db.expire_all()
    notas = {n.ano_letivo: (n.nota_geral, n.posicao) for n in db.query(Nota).filter(
        Nota.aluno_id == beto.id)}
    assert notas == {ano: (70.0, 1)}                      # o resultado de 2026 ficou

    assert recusa.status_code == 409, recusa.text
    detalhe = recusa.json()["detail"]
    assert "não vale mais" not in detalhe and "cálculo antigo" not in detalhe, detalhe
    assert f"A nota e a posição de {ano} continuam guardadas" in detalhe, detalhe
    # "a criança", nunca "ela" sem antecedente.
    assert "Se ela " not in detalhe and "para ela" not in detalhe, detalhe
    assert "dela" not in detalhe and "ela não está" not in detalhe, detalhe
    assert "Se a criança saiu da escola ou se formou" in detalhe, detalhe


def test_sem_nota_do_ano_encerrado_a_recusa_nao_afirma_que_ela_ficou_guardada(
        cliente, cliente_global, db, escola_completa):
    """Sem Nota calculada no ano encerrado, a recusa não promete "nota e posição
    guardadas": diz só que o Mérito é do ano ativo e que a criança não está nele."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    quinto = Turma(escola_id=escola.id, nome="5º Ano A", ano_escolar="5º Ano", ano_letivo=ano)
    db.add(quinto)
    db.flush()
    eva = _crianca(db, escola, "EVA FICTICIA ROCHA", turma=quinto)
    db.execute(delete(Nota).where(Nota.aluno_id == eva.id))
    db.commit()
    _virar(cliente_global, escola)

    recusa = cliente.get(f"{API}/escolas/{escola.id}/certificados/{eva.id}")
    assert recusa.status_code == 409, recusa.text
    detalhe = recusa.json()["detail"]
    assert f"tem matrícula só em {ano}" in detalhe, detalhe
    assert "continuam guardadas" not in detalhe, detalhe
    assert "não vale mais" not in detalhe, detalhe
    assert f"no ranking de {ano + 1} a criança não está" in detalhe, detalhe
