"""Restaurar o backup da escola não desfaz a exclusão permanente (revisão independente
dados-lgpd, d4caac4; LGPD art. 18, eliminação).

Antes, ``backup.restaurar`` recriava tudo o que o arquivo trazia: o backup feito ANTES
de uma exclusão permanente trazia a criança de volta — ativa, com observação, data de
nascimento, matrícula, leituras, retratos e identidades —, em silêncio (``avisos=[]``),
enquanto o log dizia ``aluno.excluido_permanente``.

Agora o arquivo leva ``log_ate`` (o último id do log, de qualquer escola, quando foi
gerado: ``backup._ultimo_log``) e a
restauração pula a ficha que a escola excluiu de vez DEPOIS dele (prova: o
``aluno.excluido_permanente`` do log, cujo ``entidade_id`` é o ``_id`` do arquivo) e toda
linha que aponta para ela. ``avisos`` diz quantas ficaram de fora, sem nome. Arquivo
antigo, sem ``log_ate``, confere toda exclusão permanente.

Integração 80a27da (lente segurança-correção): a consulta filtrava as exclusões pela
escola de DESTINO, e a rota não confere a origem do arquivo — o arquivo da escola A
restaurado na escola B trazia de volta, sem aviso, a criança que A excluiu de vez. Agora
vale a exclusão feita em qualquer escola (no PostgreSQL o id do aluno nunca volta).

Dados 100% fictícios (fixture escola_completa)."""
import json
from datetime import date, datetime

from sqlalchemy import func, select

from app.models import (
    Aluno, Escola, IdentidadeExterna, Importacao, Leitura, Livro, Matricula,
    SnapshotMatific,
)

API = "/api/v1"
AVISO = ("excluída(s) permanentemente (nesta ou em outra escola) depois deste backup "
         "não foram restauradas")


def _contar(db, modelo, escola_id):
    return db.execute(select(func.count()).select_from(modelo)
                      .where(modelo.escola_id == escola_id)).scalar_one()


def _cena(db, cliente, cliente_global, escola_completa):
    """Dados da criança-alvo em várias tabelas filhas, backup baixado pelo admin da
    escola e, DEPOIS, exclusão permanente pelo Admin Global. Devolve (escola, nome do
    alvo, nomes dos outros, conteúdo do arquivo)."""
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][2]
    nome, alvo_id = alvo.nome, alvo.id
    outros = {a.nome for a in escola_completa["alunos"][:2]}
    alvo.observacoes = "LAUDO-FICTICIO-ESQUECIMENTO"
    alvo.data_nascimento = date(2017, 5, 6)
    livro = Livro(escola_id=escola.id, titulo="Livro Ficticio Esquecimento",
                  nivel_codigo="D")
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add_all([livro, imp])
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=alvo_id, livro_id=livro.id,
                   data=datetime(2026, 9, 1, 12, 0)))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=alvo_id, importacao_id=imp.id,
                           atividades=12, estrelas=30, pontuacao_media=70))
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=alvo_id, plataforma="matific",
                             id_externo="u-ficticia-esquecimento", status="efetiva"))
    db.commit()

    baixado = cliente.get(f"{API}/escolas/{escola.id}/backup")
    assert baixado.status_code == 200, baixado.text
    r = cliente_global.post(f"{API}/escolas/{escola.id}/alunos/excluir-permanente",
                            json={"aluno_ids": [alvo_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    return escola, nome, outros, baixado.content


def _restaurar(cliente_global, escola_id, conteudo):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/restaurar",
                            files={"arquivo": ("backup.json", conteudo, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()


def _conferir_sem_a_excluida(db, escola, nome, outros):
    db.expire_all()
    nomes = set(db.execute(select(Aluno.nome).where(Aluno.escola_id == escola.id)).scalars())
    assert nome not in nomes and outros <= nomes
    assert db.execute(select(func.count()).select_from(Aluno).where(
        Aluno.observacoes == "LAUDO-FICTICIO-ESQUECIMENTO")).scalar_one() == 0
    assert _contar(db, Leitura, escola.id) == 0
    assert _contar(db, SnapshotMatific, escola.id) == 0
    assert _contar(db, IdentidadeExterna, escola.id) == 0
    assert _contar(db, Matricula, escola.id) == 2


def test_backup_antigo_nao_ressuscita_a_crianca_excluida_e_avisa(
        cliente, cliente_global, db, escola_completa):
    escola, nome, outros, conteudo = _cena(db, cliente, cliente_global, escola_completa)
    corpo = _restaurar(cliente_global, escola.id, conteudo)
    _conferir_sem_a_excluida(db, escola, nome, outros)
    assert [a for a in corpo["avisos"] if AVISO in a] == [
        f"1 criança(s) {AVISO} (direito de eliminação, LGPD art. 18)."]
    assert nome not in json.dumps(corpo, ensure_ascii=False)
    assert isinstance(json.loads(conteudo)["log_ate"], int)


def test_arquivo_antigo_sem_a_marca_do_log_tambem_respeita_a_exclusao(
        cliente, cliente_global, db, escola_completa):
    escola, nome, outros, conteudo = _cena(db, cliente, cliente_global, escola_completa)
    dados = json.loads(conteudo)
    dados.pop("log_ate", None)             # backup gerado antes desta correção
    corpo = _restaurar(cliente_global, escola.id, json.dumps(dados).encode("utf-8"))
    _conferir_sem_a_excluida(db, escola, nome, outros)
    assert any(AVISO in a for a in corpo["avisos"])


def test_backup_feito_depois_da_exclusao_restaura_tudo_sem_aviso(
        cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][2]
    r = cliente_global.post(f"{API}/escolas/{escola.id}/alunos/excluir-permanente",
                            json={"aluno_ids": [alvo.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    baixado = cliente.get(f"{API}/escolas/{escola.id}/backup")
    assert baixado.status_code == 200, baixado.text
    assert _restaurar(cliente_global, escola.id, baixado.content)["avisos"] == []
    db.expire_all()
    assert _contar(db, Aluno, escola.id) == 2
    assert _contar(db, Matricula, escola.id) == 2


def test_backup_sem_exclusao_restaura_todas_as_criancas(
        cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    baixado = cliente.get(f"{API}/escolas/{escola.id}/backup")
    assert baixado.status_code == 200, baixado.text
    assert _restaurar(cliente_global, escola.id, baixado.content)["avisos"] == []
    db.expire_all()
    assert _contar(db, Aluno, escola.id) == 3
    assert _contar(db, Matricula, escola.id) == 3


def _outra_escola(db):
    destino = Escola(nome="ESCOLA DESTINO FICTICIA ESQUECIMENTO", ano_letivo_ativo=2026)
    db.add(destino)
    db.commit()
    return destino


def test_arquivo_de_outra_escola_nao_ressuscita_a_crianca_excluida_na_origem(
        cliente, cliente_global, db, escola_completa):
    """O arquivo da escola A, restaurado na escola B, não traz de volta a criança que A
    excluiu de vez depois do arquivo — nem os dados dela — e avisa."""
    origem, nome, outros, conteudo = _cena(db, cliente, cliente_global, escola_completa)
    destino = _outra_escola(db)
    corpo = _restaurar(cliente_global, destino.id, conteudo)
    _conferir_sem_a_excluida(db, destino, nome, outros)
    assert _contar(db, Aluno, origem.id) == 2              # a origem não é tocada
    assert [a for a in corpo["avisos"] if AVISO in a] == [
        f"1 criança(s) {AVISO} (direito de eliminação, LGPD art. 18)."]
    assert nome not in json.dumps(corpo, ensure_ascii=False)


def test_arquivo_de_outra_escola_sem_exclusao_restaura_todas(
        cliente, cliente_global, db, escola_completa):
    """Sem exclusão depois do arquivo, a exclusão em qualquer escola não pula ninguém."""
    origem = escola_completa["escola"]
    baixado = cliente.get(f"{API}/escolas/{origem.id}/backup")
    assert baixado.status_code == 200, baixado.text
    destino = _outra_escola(db)
    corpo = _restaurar(cliente_global, destino.id, baixado.content)
    assert not [a for a in corpo["avisos"] if AVISO in a]
    db.expire_all()
    assert _contar(db, Aluno, destino.id) == 3
    assert _contar(db, Matricula, destino.id) == 3
