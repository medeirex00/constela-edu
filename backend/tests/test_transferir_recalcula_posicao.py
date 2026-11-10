"""Transferir de turma recalcula as notas — o Mérito não sai com a posição velha.

A recusa do certificado Geral para quem está fora do ranking vigente (sem
matrícula no ano, ou numa turma sem série do 1º ao 5º ano) manda colocar a
criança numa turma do ano pelo perfil ("Editar dados" › Turma), que chama a ação
``transferir``. Essa ação não recalculava ("a nota não muda; só a turma"): a
criança passava na guarda de população logo em seguida, mas a ``Nota`` dela
seguia com a posição do cálculo antigo — que hoje é de outra criança — e o
Mérito saía com ela. Entrar ou sair da população muda o ranking; a transferência
agora recalcula, como as outras ações da mesma rota. Dados fictícios.
"""
from datetime import date

from sqlalchemy import select

from app.models import Aluno, Importacao, Nota, SnapshotElefante

API = "/api/v1"
LEITOR = {"livros_unicos": 30, "tempo_leitura_min": 600,
          "questoes_tentativas": 100, "questoes_acertos": 100,
          "livros_por_nivel": {"D": 30}}


def _crianca_sem_turma_com_posicao_antiga(db, escola) -> Aluno:
    """Ativa, confirmada na Lista Piloto, SEM matrícula no ano, com dado de
    leitura e a Nota de um cálculo antigo (posição 5)."""
    a = Aluno(escola_id=escola.id, nome="CRIANCA FICTICIA FORA DO RANKING",
              status="ativo", da_lista_piloto=True)
    a.data_nascimento = date(2017, 5, 5)
    db.add(a)
    db.flush()
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                            **LEITOR))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=escola.ano_letivo_ativo,
                nota_geral=70.0, nota_elefante=70.0, nota_matific=0.0,
                aferido_leitura=True, aferido_matematica=False, posicao=5))
    db.commit()
    return a


def _posicao(db, aluno_id):
    db.expire_all()
    return db.execute(select(Nota.posicao).where(Nota.aluno_id == aluno_id)).scalar_one()


def test_colocar_na_turma_pelo_perfil_recalcula_a_posicao_antes_do_merito(
        cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    a = _crianca_sem_turma_com_posicao_antiga(db, escola)
    base = f"{API}/escolas/{escola.id}"

    recusa = cliente.get(f"{base}/certificados/{a.id}")
    assert recusa.status_code == 409, recusa.text

    # O que a mensagem manda fazer: perfil › "Editar dados" › Turma.
    r = cliente.post(f"{base}/alunos/acoes",
                     json={"aluno_ids": [a.id], "acao": "transferir", "turma_id": turma.id})
    assert r.status_code == 200, r.text

    # Única criança da turma com dado: a posição vigente é a 1ª, não a 5ª antiga.
    assert _posicao(db, a.id) == 1
    emitido = cliente.get(f"{base}/certificados/{a.id}")
    assert emitido.status_code == 200, emitido.text
    assert emitido.headers["content-type"] == "application/pdf"
