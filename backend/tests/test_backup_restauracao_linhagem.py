"""Linhagem das fichas entre restaurações (integração do ramo de prontidão, 80a27da;
LGPD art. 18). O caso de ponta a ponta, que só aparece no PostgreSQL (ids nunca
reaproveitados), está em ``test_backup_restauracao_apos_restauracao_pg.py``; aqui, no
SQLite do CI principal, ficam as peças:

* a restauração grava em ``backup.restaurado`` o mapa {id novo: id do arquivo} das
  fichas (``alunos_id_anterior``) — só números, sem nome;
* ``_excluidos_depois_do_backup`` segue esse mapa: a ficha excluída depois de uma
  restauração casa com o id que ela tinha no arquivo restaurado, em cadeia, com as
  restaurações de QUALQUER escola (o arquivo de A anterior a uma restauração de A,
  restaurado em B: revisão de integração do e97). Registro antigo, sem o mapa, ou com
  o mapa ilegível, é ignorado;
* a marca do arquivo (``log_ate``) é o último id do log INTEIRO, de qualquer escola, a
  mesma régua das exclusões e da linhagem (revisão adversarial do e97w-final);
* o expurgo por prazo não apaga ``backup.restaurado`` (sem ele a linhagem se perde).

Dados 100% fictícios (fixture escola_completa)."""
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.models import Aluno, Escola, LogAuditoria
from app.services import backup
from app.services.audit import ACOES_PRESERVADAS, CATEGORIAS, expurgar_retencao

API = "/api/v1"
CHAVE_MAPA = "alunos_id_anterior"   # backup.CHAVE_MAPA_ALUNOS (contrato do log)


def _log(db, escola_id, acao, *, entidade_id=None, detalhes=None, created_at=None):
    extra = {"created_at": created_at} if created_at else {}
    db.add(LogAuditoria(escola_id=escola_id, acao=acao,
                        entidade="aluno" if entidade_id else None,
                        entidade_id=entidade_id, detalhes=detalhes or {}, **extra))
    db.flush()


def _restauracao(db, escola_id, mapa):
    _log(db, escola_id, "backup.restaurado",
         detalhes={"tabelas": {"alunos": len(mapa)},
                   CHAVE_MAPA: {str(n): a for n, a in mapa.items()}})


def test_restauracao_grava_o_mapa_de_ids_das_fichas_sem_nome(
        cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    conteudo = cliente.get(f"{API}/escolas/{escola.id}/backup").content
    ids_do_arquivo = {linha["_id"] for linha in json.loads(conteudo)["tabelas"]["alunos"]}
    r = cliente_global.post(f"{API}/escolas/{escola.id}/restaurar",
                            files={"arquivo": ("backup.json", conteudo, "application/json")})
    assert r.status_code == 200, r.text
    db.expire_all()
    (log,) = db.execute(select(LogAuditoria).where(
        LogAuditoria.escola_id == escola.id,
        LogAuditoria.acao == "backup.restaurado")).scalars().all()
    mapa = log.detalhes[CHAVE_MAPA]
    ids_atuais = set(db.execute(select(Aluno.id).where(
        Aluno.escola_id == escola.id)).scalars())
    assert {int(novo) for novo in mapa} == ids_atuais
    assert set(mapa.values()) == ids_do_arquivo
    assert all(isinstance(antigo, int) for antigo in mapa.values())
    assert log.detalhes["tabelas"]["alunos"] == len(ids_atuais)
    texto = json.dumps(log.detalhes, ensure_ascii=False)
    assert not any(a.nome in texto for a in escola_completa["alunos"])


def test_exclusao_depois_de_restauracao_casa_com_o_id_do_arquivo(db, escola_completa):
    eid = escola_completa["escola"].id
    _log(db, eid, "backup.gerado")
    marca = backup._ultimo_log(db)                      # o arquivo leva ids 101 e 102
    _restauracao(db, eid, {901: 101, 902: 102})
    _log(db, eid, "aluno.excluido_permanente", entidade_id=902)
    excluidos = backup._excluidos_depois_do_backup(db, eid, marca)
    assert 102 in excluidos and 101 not in excluidos and 901 not in excluidos


def test_linhagem_em_cadeia_inclusive_restauracao_anterior_ao_arquivo(db, escola_completa):
    """Arquivo mais antigo (ids 101/102) restaurado ANTES do arquivo que volta agora
    (ids 501/502) e de novo DEPOIS dele (ids 901/902); a exclusão é do 902."""
    eid = escola_completa["escola"].id
    _restauracao(db, eid, {501: 101, 502: 102})
    _log(db, eid, "backup.gerado")
    marca = backup._ultimo_log(db)                      # o arquivo leva 501 e 502
    _restauracao(db, eid, {901: 101, 902: 102})
    _log(db, eid, "aluno.excluido_permanente", entidade_id=902)
    excluidos = backup._excluidos_depois_do_backup(db, eid, marca)
    assert 502 in excluidos and 501 not in excluidos


def test_linhagem_gravada_em_outra_escola_vale_e_registro_sem_mapa_ou_ilegivel_nao(
        db, escola_completa):
    """O arquivo da ORIGEM (id 333) foi gerado antes de uma restauração da origem
    (333 -> 902); a origem exclui de vez o 902; o arquivo volta no DESTINO. Só o log da
    origem liga 902 a 333, e a ligação vale (no PostgreSQL o id do aluno é global).
    Antes, só as restaurações da escola de destino contavam e o 333 voltava. Registro
    sem o mapa (anterior a ele) ou com o mapa ilegível, em qualquer escola, não liga
    nada."""
    destino = escola_completa["escola"].id
    origem = Escola(nome="Escola Ficticia Linhagem", ano_letivo_ativo=2026)
    db.add(origem)
    db.flush()
    _log(db, origem.id, "backup.gerado")
    marca = backup._ultimo_log(db)                       # o arquivo leva o id 333
    _restauracao(db, origem.id, {902: 333})              # restauração NA ORIGEM
    _log(db, destino, "backup.restaurado", detalhes={"tabelas": {"alunos": 2}})  # pré-mapa
    _log(db, origem.id, "backup.restaurado",
         detalhes={CHAVE_MAPA: {"x": 1, "903": None}})        # ilegível
    _log(db, destino, "backup.restaurado", detalhes={CHAVE_MAPA: ["904", 905]})  # ilegível
    _log(db, origem.id, "aluno.excluido_permanente", entidade_id=902)
    assert backup._excluidos_depois_do_backup(db, destino, marca) == {902, 333}


def test_marca_do_arquivo_e_o_log_inteiro_e_a_exclusao_anterior_em_outra_escola_nao_conta(
        db, escola_completa):
    """``log_ate`` é o último id do log INTEIRO, a régua das exclusões e da linhagem
    (revisão adversarial do e97w-final). Era o último id do log desta escola: a exclusão
    de vez em OUTRA escola feita ANTES do arquivo, com id maior que o último log daqui,
    contava como "depois" e tirava da restauração a ficha viva daqui ligada a ela."""
    eid = escola_completa["escola"].id
    outra = Escola(nome="Escola Ficticia Marca Global", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    _restauracao(db, outra.id, {902: 101})       # arquivo daqui (ficha 101) virou 902 lá
    _log(db, outra.id, "aluno.excluido_permanente", entidade_id=902)   # lá, ANTES
    ultimo_daqui = db.execute(select(func.max(LogAuditoria.id)).where(
        LogAuditoria.escola_id == eid)).scalar() or 0
    ultimo_geral = db.execute(select(func.max(LogAuditoria.id))).scalar()
    assert ultimo_geral > ultimo_daqui            # a exclusão de lá é o último registro
    assert backup._ultimo_log(db) == ultimo_geral
    dados = backup.exportar(db, eid)              # o arquivo daqui, DEPOIS da exclusão
    assert dados["log_ate"] == ultimo_geral
    assert backup._excluidos_depois_do_backup(db, eid, dados["log_ate"]) == set()
    # Controle: a mesma exclusão DEPOIS do arquivo conta, e a linhagem leva ao 101.
    _log(db, outra.id, "aluno.excluido_permanente", entidade_id=902)
    assert backup._excluidos_depois_do_backup(db, eid, dados["log_ate"]) == {902, 101}


def test_expurgo_por_prazo_nao_apaga_o_registro_da_restauracao(db, escola_completa):
    eid = escola_completa["escola"].id
    assert "backup.restaurado" in ACOES_PRESERVADAS
    agora = datetime(2026, 10, 20, 12, 0)
    velho = agora - timedelta(days=4000)
    _log(db, eid, "backup.restaurado", created_at=velho,
         detalhes={CHAVE_MAPA: {"902": 102}})
    _log(db, eid, "backup.gerado", created_at=velho)
    db.commit()
    expurgar_retencao(db, simular=False, prazos={c: 1 for c in CATEGORIAS},
                      agora=agora, aceitar_abaixo_do_piso=True)
    db.commit()
    acoes = {log.acao for log in db.execute(select(LogAuditoria)).scalars()}
    assert "backup.restaurado" in acoes and "backup.gerado" not in acoes
