"""Restauração histórica de leituras: a evidência manda, e sem ela não passa.

O que estes testes travam é uma assimetria deliberada: restaurar é FÁCIL de
pedir e DIFÍCIL de conseguir. Cada item traz a evidência — o ``EventoAluno`` que
sobreviveu à fusão —, e o serviço reconfere tudo contra o banco, inclusive
recalculando o hash da ``chave_natural``, que carrega dentro de si a ficha de
ORIGEM do dado. Nenhum caminho aqui aceita "é provavelmente essa data".

O caso real que originou o serviço: a fusão da ficha 1678 na 609 (Kemily,
escola 11) manteve a linha do sobrevivente com a data VELHA, e 14 livros saíram
da janela do 3º bimestre. Os números deste arquivo são os daquele caso.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import (Aluno, Configuracao, EventoAluno, Leitura, Livro,
                        LogAuditoria, Matricula)
from app.services import leituras_restauracao as lr
from app.services.eventos import chave_evento

# Ficha ABSORVIDA pela fusão: já não existe como registro, e não precisa — o que
# a identifica é estar DENTRO do hash da chave natural do evento.
ORIGEM = 1678
DATA_VELHA = datetime(2026, 3, 25, 16, 52)
DATA_REAL = datetime(2026, 8, 6, 0, 1)
MOTIVO = "fusao 1678->609 manteve a data velha; evento prova o 3o bimestre"


def _livro(db, escola_id, titulo="A Galinha do Vizinho", nivel="AA"):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel)
    db.add(livro)
    db.flush()
    return livro


def _leitura(db, escola_id, aluno_id, livro_id, data=DATA_VELHA, tempo=1):
    leitura = Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro_id,
                      data=data, tempo_leitura_min=tempo, nivel_codigo="AA")
    db.add(leitura)
    db.flush()
    return leitura


def _evento(db, escola_id, aluno_id, livro, quando=DATA_REAL, minutos=2,
            *, origem=ORIGEM, titulo=None):
    """Evento com a chave natural gerada para a ficha de ORIGEM — é exatamente
    o que a fusão deixa para trás e o que prova a procedência."""
    nome = titulo if titulo is not None else livro.titulo
    evento = EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=nome,
        livro_id=livro.id, tempo_segundos=minutos * 60, nivel_codigo="AA",
        chave_natural=chave_evento("elefante", "leitura", origem, nome, quando))
    db.add(evento)
    db.flush()
    return evento


def _item(aluno_id, livro_id, evento, *, data=None, tempo=None, origem=ORIGEM,
          motivo=MOTIVO, chave=None):
    return lr.ItemRestauracao(
        aluno_id=aluno_id, aluno_origem_id=origem, livro_id=livro_id,
        data_original=data if data is not None else evento.ocorrido_em,
        tempo_original=tempo if tempo is not None else (evento.tempo_segundos or 0) // 60,
        evidencia_evento_id=evento.id,
        evidencia_chave_natural=chave or evento.chave_natural,
        motivo=motivo)


@pytest.fixture()
def cena(db, escola_completa):
    """Um livro cuja data a fusão trocou, com a evidência que prova a original."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    leitura = _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()
    return {"escola": escola, "aluno": aluno, "livro": livro,
            "leitura": leitura, "evento": evento}


# --------------------------------------------------------------------------
# 1. o caminho felizinho
# --------------------------------------------------------------------------
def test_restaura_uma_leitura_comprovada(db, cena):
    resultado = lr.restaurar(db, cena["escola"].id,
                             [_item(cena["aluno"].id, cena["livro"].id, cena["evento"])],
                             usuario_id=None)
    db.commit()

    leitura = db.get(Leitura, cena["leitura"].id)
    assert leitura.data == DATA_REAL
    assert leitura.tempo_leitura_min == 2
    assert resultado["leituras_restauradas"] == 1
    assert resultado["minutos_de"] == 1 and resultado["minutos_para"] == 2
    item = resultado["itens"][0]
    assert item["data_anterior"] == DATA_VELHA
    assert item["data_restaurada"] == DATA_REAL
    assert item["evidencia_evento_id"] == cena["evento"].id


def test_planejar_nao_escreve_nada(db, cena):
    """O dry-run usa a MESMA validação e não deixa rastro — senão o ensaio não
    ensaia a operação, ensaia outra coisa."""
    plano = lr.planejar(db, cena["escola"].id,
                        [_item(cena["aluno"].id, cena["livro"].id, cena["evento"])])
    db.rollback()
    assert len(plano) == 1
    assert db.get(Leitura, cena["leitura"].id).data == DATA_VELHA
    assert db.scalar(select(LogAuditoria).limit(1)) is None


# --------------------------------------------------------------------------
# 2 a 6. a evidência tem que provar
# --------------------------------------------------------------------------
def test_rejeita_evidencia_de_outro_aluno(db, escola_completa):
    escola = escola_completa["escola"]
    dono, outro = escola_completa["alunos"][0], escola_completa["alunos"][1]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, dono.id, livro.id)
    evento_do_outro = _evento(db, escola.id, outro.id, livro)
    db.commit()

    with pytest.raises(lr.RestauracaoInvalida, match="outra criança"):
        lr.restaurar(db, escola.id,
                     [_item(dono.id, livro.id, evento_do_outro)], usuario_id=None)


def test_rejeita_livro_diferente(db, cena):
    outro_livro = _livro(db, cena["escola"].id, titulo="Gira-Gira")
    _leitura(db, cena["escola"].id, cena["aluno"].id, outro_livro.id)
    db.commit()
    item = _item(cena["aluno"].id, outro_livro.id, cena["evento"])

    with pytest.raises(lr.RestauracaoInvalida, match="é do livro"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)


def test_rejeita_evento_inexistente(db, cena):
    item = lr.ItemRestauracao(
        aluno_id=cena["aluno"].id, aluno_origem_id=ORIGEM,
        livro_id=cena["livro"].id, data_original=DATA_REAL, tempo_original=2,
        evidencia_evento_id=99999, evidencia_chave_natural="f" * 64,
        motivo=MOTIVO)
    with pytest.raises(lr.RestauracaoInvalida, match="não existe"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)


def test_rejeita_data_nao_comprovada(db, cena):
    """Pedir uma data que o evento não registra é recusado — é a porta por onde
    entraria "escolher" a data que convém."""
    item = _item(cena["aluno"].id, cena["livro"].id, cena["evento"],
                 data=datetime(2026, 9, 30, 10, 0))
    with pytest.raises(lr.RestauracaoInvalida, match="ocorreu em"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)
    assert db.get(Leitura, cena["leitura"].id).data == DATA_VELHA


def test_rejeita_tempo_nao_comprovado(db, cena):
    item = _item(cena["aluno"].id, cena["livro"].id, cena["evento"], tempo=45)
    with pytest.raises(lr.RestauracaoInvalida, match="minuto"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)


def test_rejeita_quando_o_hash_nao_prova_a_origem(db, cena):
    """O coração do método: a chave natural é recalculada. Declarar outra ficha
    de origem faz o hash não fechar, e a restauração cai."""
    item = _item(cena["aluno"].id, cena["livro"].id, cena["evento"], origem=4242)
    with pytest.raises(lr.RestauracaoInvalida, match="NÃO prova a origem"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)


def test_rejeita_chave_natural_declarada_diferente_da_gravada(db, cena):
    item = _item(cena["aluno"].id, cena["livro"].id, cena["evento"], chave="a" * 64)
    with pytest.raises(lr.RestauracaoInvalida, match="chave natural declarada"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)


def test_rejeita_evento_que_nao_e_a_primeira_ocorrencia(db, cena):
    """A linha de leitura nasce na PRIMEIRA importação. Aceitar um evento
    posterior seria pegar a data mais conveniente entre as disponíveis — a
    inferência que este serviço existe para proibir."""
    posterior = _evento(db, cena["escola"].id, cena["aluno"].id, cena["livro"],
                        quando=datetime(2026, 8, 7, 1, 44), minutos=9)
    db.commit()
    item = _item(cena["aluno"].id, cena["livro"].id, posterior)

    with pytest.raises(lr.RestauracaoInvalida, match="primeira ocorrência"):
        lr.restaurar(db, cena["escola"].id, [item], usuario_id=None)
    # e a primeira continua sendo aceita
    lr.restaurar(db, cena["escola"].id,
                 [_item(cena["aluno"].id, cena["livro"].id, cena["evento"])],
                 usuario_id=None)
    db.commit()
    assert db.get(Leitura, cena["leitura"].id).data == DATA_REAL


# --------------------------------------------------------------------------
# 7 a 10. integridade do lote
# --------------------------------------------------------------------------
def test_impede_duplicacao_no_mesmo_lote(db, cena):
    item = _item(cena["aluno"].id, cena["livro"].id, cena["evento"])
    with pytest.raises(lr.RestauracaoInvalida, match="repete o livro"):
        lr.restaurar(db, cena["escola"].id, [item, item], usuario_id=None)


def test_rollback_quando_um_item_do_lote_falha(db, escola_completa):
    """Se o último item não se sustenta, os primeiros nem são escritos."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    itens, leituras = [], []
    for i in range(3):
        livro = _livro(db, escola.id, titulo=f"Livro {i}")
        leituras.append(_leitura(db, escola.id, aluno.id, livro.id))
        evento = _evento(db, escola.id, aluno.id, livro)
        itens.append(_item(aluno.id, livro.id, evento))
    livro_ruim = _livro(db, escola.id, titulo="Sem evidencia")
    _leitura(db, escola.id, aluno.id, livro_ruim.id)
    db.commit()
    itens.append(lr.ItemRestauracao(
        aluno_id=aluno.id, aluno_origem_id=ORIGEM, livro_id=livro_ruim.id,
        data_original=DATA_REAL, tempo_original=2,
        evidencia_evento_id=88888, evidencia_chave_natural="b" * 64,
        motivo=MOTIVO))

    with pytest.raises(lr.RestauracaoInvalida):
        lr.restaurar(db, escola.id, itens, usuario_id=None)
    db.rollback()
    for leitura in leituras:
        assert db.get(Leitura, leitura.id).data == DATA_VELHA
    assert db.scalar(select(LogAuditoria).limit(1)) is None


def test_nao_restaura_livro_cuja_data_ja_e_a_comprovada(db, escola_completa):
    """O caso dos livros em que as DUAS fichas tinham a mesma data: a fusão não
    perdeu nada, então "restaurar" só maquiaria um número. Recusa explícita, não
    sucesso silencioso."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id, titulo="Cadê?")
    _leitura(db, escola.id, aluno.id, livro.id, data=DATA_REAL, tempo=2)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()

    with pytest.raises(lr.RestauracaoInvalida, match="Nada foi perdido"):
        lr.restaurar(db, escola.id, [_item(aluno.id, livro.id, evento)],
                     usuario_id=None)


def test_nao_toca_em_leitura_fora_do_lote_nem_em_outro_aluno(db, escola_completa):
    escola = escola_completa["escola"]
    alvo, vizinho = escola_completa["alunos"][0], escola_completa["alunos"][1]
    livro = _livro(db, escola.id)
    intacto_livro = _livro(db, escola.id, titulo="Intacto")
    leitura_alvo = _leitura(db, escola.id, alvo.id, livro.id)
    leitura_intacta = _leitura(db, escola.id, alvo.id, intacto_livro.id)
    leitura_vizinho = _leitura(db, escola.id, vizinho.id, livro.id)
    evento = _evento(db, escola.id, alvo.id, livro)
    db.commit()

    lr.restaurar(db, escola.id, [_item(alvo.id, livro.id, evento)], usuario_id=None)
    db.commit()
    assert db.get(Leitura, leitura_alvo.id).data == DATA_REAL
    assert db.get(Leitura, leitura_intacta.id).data == DATA_VELHA
    assert db.get(Leitura, leitura_vizinho.id).data == DATA_VELHA
    assert db.get(Leitura, leitura_vizinho.id).tempo_leitura_min == 1


def test_recusa_aluno_de_outra_escola_e_aluno_inativo(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    aluno.status = "transferido"
    db.commit()

    with pytest.raises(lr.RestauracaoInvalida, match="transferido"):
        lr.restaurar(db, escola.id, [_item(aluno.id, livro.id, evento)],
                     usuario_id=None)
    with pytest.raises(lr.RestauracaoInvalida, match="não é desta escola"):
        lr.restaurar(db, escola.id + 99,
                     [_item(aluno.id, livro.id, evento)], usuario_id=None)


def test_recusa_motivo_curto_e_origem_igual_ao_destino(db, cena):
    with pytest.raises(lr.RestauracaoInvalida, match="sem motivo escrito"):
        lr.restaurar(db, cena["escola"].id,
                     [_item(cena["aluno"].id, cena["livro"].id, cena["evento"],
                            motivo="erro")], usuario_id=None)
    with pytest.raises(lr.RestauracaoInvalida, match="a mesma"):
        lr.restaurar(db, cena["escola"].id,
                     [_item(cena["aluno"].id, cena["livro"].id, cena["evento"],
                            origem=cena["aluno"].id)], usuario_id=None)


def test_recusa_data_de_outro_ano_letivo_sem_decisao_explicita(db, escola_completa):
    escola = escola_completa["escola"]            # ano_letivo_ativo = 2026
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro.id, data=datetime(2024, 5, 2, 9, 0))
    antigo = datetime(2025, 6, 11, 17, 17)
    evento = _evento(db, escola.id, aluno.id, livro, quando=antigo)
    db.commit()
    item = _item(aluno.id, livro.id, evento)

    with pytest.raises(lr.RestauracaoInvalida, match="fora do ano letivo"):
        lr.restaurar(db, escola.id, [item], usuario_id=None)
    lr.restaurar(db, escola.id, [item], usuario_id=None,
                 permitir_fora_do_ano_letivo=True)
    db.commit()
    assert db.scalar(select(Leitura.data).where(Leitura.aluno_id == aluno.id)) == antigo


# --------------------------------------------------------------------------
# 11 e 12. auditoria e recálculo
# --------------------------------------------------------------------------
def test_auditoria_responde_quem_o_que_e_com_que_evidencia(db, cena):
    lr.restaurar(db, cena["escola"].id,
                 [_item(cena["aluno"].id, cena["livro"].id, cena["evento"])],
                 usuario_id=cena.get("admin_id"))
    db.commit()

    logs = {log.acao: log for log in db.execute(select(LogAuditoria)).scalars()}
    assert set(logs) == {lr.ACAO_ITEM, lr.ACAO_LOTE}
    item = logs[lr.ACAO_ITEM]
    assert item.entidade == "leitura" and item.entidade_id == cena["leitura"].id
    d = item.detalhes
    assert d["data_anterior"].startswith("2026-03-25")
    assert d["data_restaurada"].startswith("2026-08-06")
    assert d["tempo_anterior"] == 1 and d["tempo_restaurado"] == 2
    assert d["evidencia_evento_id"] == cena["evento"].id
    assert d["evidencia_chave_natural"] == cena["evento"].chave_natural
    assert d["aluno_origem_id"] == ORIGEM
    assert d["livro_titulo"] == cena["livro"].titulo and d["motivo"] == MOTIVO
    lote = logs[lr.ACAO_LOTE]
    assert lote.detalhes["leituras_restauradas"] == 1
    assert lote.detalhes["minutos_de"] == 1 and lote.detalhes["minutos_para"] == 2


def test_rota_dry_run_nao_escreve_e_aplica_so_com_confirmacao(cliente_global, db,
                                                              escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    leitura = _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()
    corpo = {"itens": [{
        "aluno_id": aluno.id, "aluno_origem_id": ORIGEM, "livro_id": livro.id,
        "data_original": DATA_REAL.isoformat(), "tempo_original": 2,
        "evidencia_evento_id": evento.id,
        "evidencia_chave_natural": evento.chave_natural, "motivo": MOTIVO}]}
    url = f"/api/v1/escolas/{escola.id}/leituras/restaurar-historico"

    ensaio = cliente_global.post(url, json=corpo)
    assert ensaio.status_code == 200, ensaio.text
    assert ensaio.json()["dry_run"] is True
    assert ensaio.json()["leituras_a_restaurar"] == 1
    db.expire_all()
    assert db.get(Leitura, leitura.id).data == DATA_VELHA

    sem_confirmar = cliente_global.post(url, json={**corpo, "dry_run": False})
    assert sem_confirmar.status_code == 400
    assert "RESTAURAR HISTORICO" in sem_confirmar.text
    db.expire_all()
    assert db.get(Leitura, leitura.id).data == DATA_VELHA

    ok = cliente_global.post(url, json={**corpo, "dry_run": False,
                                        "confirmacao": "restaurar historico"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["leituras_restauradas"] == 1
    db.expire_all()
    assert db.get(Leitura, leitura.id).data == DATA_REAL


def test_rota_recalcula_sem_mexer_na_formula(cliente_global, db, escola_completa):
    """A restauração muda o INSUMO (data e tempo da leitura), nunca a régua: os
    pesos e a referência de normalização continuam exatamente como estavam."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id, nivel="D")
    _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro, minutos=40)
    db.commit()
    pesos_antes = {c.namespace: dict(c.valor) for c in db.execute(
        select(Configuracao).where(Configuracao.escola_id == escola.id)).scalars()}

    resposta = cliente_global.post(
        f"/api/v1/escolas/{escola.id}/leituras/restaurar-historico",
        json={"itens": [{
            "aluno_id": aluno.id, "aluno_origem_id": ORIGEM,
            "livro_id": livro.id, "data_original": DATA_REAL.isoformat(),
            "tempo_original": 40, "evidencia_evento_id": evento.id,
            "evidencia_chave_natural": evento.chave_natural, "motivo": MOTIVO}],
            "dry_run": False, "confirmacao": "RESTAURAR HISTORICO"})
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    pesos_depois = {c.namespace: dict(c.valor) for c in db.execute(
        select(Configuracao).where(Configuracao.escola_id == escola.id)).scalars()}
    assert pesos_depois == pesos_antes
    # e a nota do aluno foi recalculada na mesma transação
    from app.models import Nota
    nota = db.execute(select(Nota).where(Nota.aluno_id == aluno.id)).scalars().first()
    assert nota is not None


def test_rota_exige_admin_global(cliente, db, escola_completa):
    """Reescrever histórico é da mesma régua do ``aplicar_ao_historico`` do
    catálogo: o admin da escola não alcança."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()

    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/leituras/restaurar-historico",
        json={"itens": [{
            "aluno_id": aluno.id, "aluno_origem_id": ORIGEM,
            "livro_id": livro.id, "data_original": DATA_REAL.isoformat(),
            "tempo_original": 2, "evidencia_evento_id": evento.id,
            "evidencia_chave_natural": evento.chave_natural, "motivo": MOTIVO}]})
    assert resposta.status_code == 403


def test_lote_vazio_e_recusado(db, escola_completa):
    with pytest.raises(lr.RestauracaoInvalida, match="Nenhuma restauração"):
        lr.restaurar(db, escola_completa["escola"].id, [], usuario_id=None)


def test_caso_real_14_livros_somam_58_minutos(db, escola_completa):
    """O caso da Kemily em miniatura: 14 livros com data velha, cada um com a
    evidência do primeiro evento da ficha absorvida. O lote tem que fechar nos
    três números — contagem, minutos e nada mais tocado."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    minutos = [2, 3, 9, 4, 3, 5, 2, 3, 6, 6, 1, 2, 10, 2]   # soma 58
    itens, ids = [], []
    for i, minuto in enumerate(minutos):
        livro = _livro(db, escola.id, titulo=f"Livro do bimestre {i}")
        ids.append(_leitura(db, escola.id, aluno.id, livro.id).id)
        evento = _evento(db, escola.id, aluno.id, livro,
                         quando=datetime(2026, 8, 6, 0, i + 1), minutos=minuto)
        itens.append(_item(aluno.id, livro.id, evento))
    db.commit()

    resultado = lr.restaurar(db, escola.id, itens, usuario_id=None)
    db.commit()
    assert resultado["leituras_restauradas"] == 14
    assert resultado["minutos_para"] - resultado["minutos_de"] == 58 - 14
    assert resultado["minutos_para"] == 58
    for leitura_id in ids:
        assert db.get(Leitura, leitura_id).data.month == 8
    assert db.scalar(select(Matricula.turma_id).where(
        Matricula.aluno_id == aluno.id)) == escola_completa["turma"].id
    assert db.execute(select(LogAuditoria)
                      .where(LogAuditoria.acao == lr.ACAO_ITEM)).scalars().all().__len__() == 14


def test_nao_cria_leitura_que_nao_existe(db, escola_completa):
    """Sem leitura registrada não há o que corrigir — criar seria inventar que a
    criança leu."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()
    antes = db.execute(select(Leitura)).scalars().all()

    with pytest.raises(lr.RestauracaoInvalida, match="não tem leitura registrada"):
        lr.restaurar(db, escola.id, [_item(aluno.id, livro.id, evento)],
                     usuario_id=None)
    assert db.execute(select(Leitura)).scalars().all() == antes


def test_recusa_data_no_futuro(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro.id)
    futuro = datetime(2026, 12, 31, 23, 59)
    evento = _evento(db, escola.id, aluno.id, livro, quando=futuro)
    db.commit()
    # (ano letivo ativo é 2026, então o que barra aqui é a guarda de futuro)
    with pytest.raises(lr.RestauracaoInvalida, match="no futuro"):
        lr.restaurar(db, escola.id, [_item(aluno.id, livro.id, evento)],
                     usuario_id=None)


def test_evidencia_de_outra_escola_e_recusada(db, escola_completa):
    from app.models import Escola
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    evento.escola_id = outra.id
    db.commit()

    with pytest.raises(lr.RestauracaoInvalida, match="de outra escola"):
        lr.restaurar(db, escola.id, [_item(aluno.id, livro.id, evento)],
                     usuario_id=None)


def test_livro_de_outra_escola_e_recusado(db, escola_completa):
    from app.models import Escola
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    livro = _livro(db, outra.id)
    _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()

    with pytest.raises(lr.RestauracaoInvalida, match="acervo"):
        lr.restaurar(db, escola.id, [_item(aluno.id, livro.id, evento)],
                     usuario_id=None)


def test_aluno_inexistente(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro.id)
    evento = _evento(db, escola.id, aluno.id, livro)
    db.commit()
    item = _item(99999, livro.id, evento)
    with pytest.raises(lr.RestauracaoInvalida, match="não é desta escola"):
        lr.restaurar(db, escola.id, [item], usuario_id=None)
    assert db.get(Aluno, 99999) is None
