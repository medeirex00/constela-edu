"""Saneamento de duplicata homônima: a evidência manda, e sem ela não passa.

O que estes testes travam é a assimetria que o serviço existe para manter:
remover linha de histórico é FÁCIL de pedir e DIFÍCIL de conseguir. A única
coisa que autoriza é um par anômalo por construção — mesma criança, mesmo
título ambíguo do catálogo, MESMO SEGUNDO e MESMO tempo de leitura, com uma
linha de livro ``legado`` e uma ``fonte``. Qualquer afrouxamento nessas
condições é o que estes casos impedem.

O caso real que originou o serviço: o catálogo do Elefante tem exatamente dois
títulos homônimos — "Cadê?" (B/BB) e "Chapeuzinho Vermelho" (I/K) — e as linhas
``legado`` criadas antes do vínculo com o catálogo absorveram leitura das duas
obras. Os títulos e níveis daqui são os de verdade, lidos do catálogo oficial.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import EventoAluno, Leitura, Livro, LogAuditoria
from app.services import livros_homonimos_saneamento as san
from app.services.eventos import chave_evento

INSTANTE = datetime(2026, 3, 30, 20, 50, 43)
MOTIVO = "duplicata homonima provada: mesmo segundo e mesmo tempo"

# Os dois homônimos reais do catálogo, com os ids e níveis oficiais.
CADE = ("Cadê?", {"legado": (4799, "BB"), "fonte": (2356, "B")})
CHAPEU = ("Chapeuzinho Vermelho", {"legado": (2304, "I"), "fonte": (5539, "K")})


def _livro(db, escola_id, titulo, nivel, origem, elefante_id):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel,
                  nivel_fonte=nivel, origem_nivel=origem,
                  elefante_id=elefante_id)
    db.add(livro)
    db.flush()
    return livro


def _leitura(db, escola_id, aluno_id, livro, quando=INSTANTE, tempo=5):
    leitura = Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id,
                      data=quando, tempo_leitura_min=tempo,
                      nivel_codigo=livro.nivel_codigo)
    db.add(leitura)
    db.flush()
    return leitura


def _evento(db, escola_id, aluno_id, livro, quando=INSTANTE, minutos=5):
    """O evento vive no livro em que a linha foi pendurada. A chave_natural NÃO
    inclui livro_id — é por isso que o par homônimo compartilha um evento só."""
    evento = EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=livro.titulo,
        livro_id=livro.id, tempo_segundos=minutos * 60,
        nivel_codigo=livro.nivel_codigo,
        chave_natural=chave_evento("elefante", "leitura", aluno_id,
                                   livro.titulo, quando))
    db.add(evento)
    db.flush()
    return evento


def _par(db, escola_completa, titulo_def=CADE, *, origem_a="legado",
         origem_b="fonte", quando_a=INSTANTE, quando_b=INSTANTE,
         tempo_a=5, tempo_b=5, aluno_b=None, titulo_b=None, com_evento=True):
    """Monta o par (livro legado + livro fonte) e as duas leituras."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    titulo, ids = titulo_def
    eid_a, nivel_a = ids["legado"]
    eid_b, nivel_b = ids["fonte"]
    legado = _livro(db, escola.id, titulo, nivel_a, origem_a, eid_a)
    fonte = _livro(db, escola.id, titulo_b or titulo, nivel_b, origem_b, eid_b)
    a = _leitura(db, escola.id, aluno.id, legado, quando_a, tempo_a)
    outro = aluno_b if aluno_b is not None else aluno
    b = _leitura(db, escola.id, outro.id, fonte, quando_b, tempo_b)
    if com_evento:
        _evento(db, escola.id, aluno.id, legado, quando_a, tempo_a)
    return {"escola": escola, "aluno": aluno, "legado": legado, "fonte": fonte,
            "leitura_legado": a, "leitura_fonte": b}


# --------------------------------------------------------------- 1: remove
def test_mesmo_segundo_e_mesmo_tempo_autoriza_remocao(db, escola_completa):
    cena = _par(db, escola_completa)
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["total_remocoes"] == 1
    assert plano["autorizados"][0]["classificacao"] == san.PROVADA
    assert plano["autorizados"][0]["legado_leitura_id"] == cena["leitura_legado"].id
    assert plano["autorizados"][0]["fonte_leitura_id"] == cena["leitura_fonte"].id

    resultado = san.executar(db, [cena["escola"].id], None, MOTIVO)
    assert resultado["leituras_removidas"] == 1
    assert db.get(Leitura, cena["leitura_legado"].id) is None
    # a linha do catálogo reconciliado FICA
    assert db.get(Leitura, cena["leitura_fonte"].id) is not None


# ------------------------------------------------- 2: tempo diferente não sai
def test_mesmo_segundo_com_tempo_diferente_nao_remove(db, escola_completa):
    cena = _par(db, escola_completa, tempo_a=5, tempo_b=9)
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["total_remocoes"] == 0
    assert plano["total_recusados"] == 1
    # o instante bate e a duracao nao: INDETERMINADO, nao "provavel"
    assert plano["recusados"][0]["classificacao"] == san.INDETERMINADO
    assert san.INDETERMINADO in plano["recusados"][0]["recusa"]
    assert db.get(Leitura, cena["leitura_legado"].id) is not None


# --------------------------------------------- 3: timestamp diferente não sai
def test_timestamp_diferente_nao_remove(db, escola_completa):
    cena = _par(db, escola_completa,
                quando_b=INSTANTE + timedelta(days=3))
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["total_remocoes"] == 0
    assert plano["recusados"][0]["classificacao"] == san.DIFERENTES
    assert san.DIFERENTES in plano["recusados"][0]["recusa"]


# --------------------------------------------------- 4: dois fonte não sai
def test_dois_livros_fonte_nao_remove(db, escola_completa):
    cena = _par(db, escola_completa, origem_a="fonte")
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    # sem um legado E um fonte o padrão não existe: nem entra como candidato
    assert plano["total_remocoes"] == 0
    assert plano["total_recusados"] == 0
    assert db.get(Leitura, cena["leitura_legado"].id) is not None


# -------------------------------------------------- 5: dois legado não sai
def test_dois_livros_legado_nao_remove(db, escola_completa):
    cena = _par(db, escola_completa, origem_b="legado")
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["total_remocoes"] == 0
    assert plano["total_recusados"] == 0


# ------------------------------------------------- 6: título diferente não sai
def test_titulo_diferente_nao_remove(db, escola_completa):
    cena = _par(db, escola_completa, titulo_b="Cadê o bicho?")
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["total_remocoes"] == 0
    assert plano["total_recusados"] == 0


# -------------------------------------------------- 7: aluno diferente não sai
def test_aluno_diferente_nao_remove(db, escola_completa):
    outro = escola_completa["alunos"][1]
    cena = _par(db, escola_completa, aluno_b=outro)
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["total_remocoes"] == 0
    assert plano["total_recusados"] == 0
    assert db.get(Leitura, cena["leitura_legado"].id) is not None


# ------------------------------- 8: título fora dos homônimos auditados não sai
def test_titulo_fora_dos_homonimos_do_catalogo_nao_remove(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    legado = _livro(db, escola.id, "A Galinha do Vizinho", "AA", "legado", 111)
    fonte = _livro(db, escola.id, "A Galinha do Vizinho", "BB", "fonte", 222)
    a = _leitura(db, escola.id, aluno.id, legado)
    _leitura(db, escola.id, aluno.id, fonte)
    plano = san.dry_run(db, [escola.id], MOTIVO)
    assert plano["total_remocoes"] == 0
    assert plano["total_recusados"] == 0, (
        "título que não é homônimo no CATÁLOGO não deve nem ser candidato")
    assert db.get(Leitura, a.id) is not None


def test_titulos_auditados_vem_do_catalogo_e_sao_exatamente_dois():
    ambiguos = san.titulos_auditados()
    assert set(ambiguos) == {"cade?", "chapeuzinho vermelho"}
    assert ambiguos["cade?"] == {2356: "B", 4799: "BB"}
    assert ambiguos["chapeuzinho vermelho"] == {2304: "I", 5539: "K"}


# ---------------------------------------------------- 9: evento é preservado
def test_evento_nunca_e_removido_nem_migrado(db, escola_completa):
    cena = _par(db, escola_completa)
    antes = list(db.execute(select(EventoAluno.id, EventoAluno.livro_id)).all())
    assert len(antes) == 1
    san.executar(db, [cena["escola"].id], None, MOTIVO)
    depois = list(db.execute(select(EventoAluno.id, EventoAluno.livro_id)).all())
    assert depois == antes, (
        "o evento é a única prova documental da leitura e é compartilhado pelo "
        "par homônimo — não sai e não troca de livro")


def test_evento_ambiguo_nos_dois_livros_e_registrado_mas_preservado(
        db, escola_completa):
    cena = _par(db, escola_completa)
    # um segundo evento, no livro FONTE, com chave distinta (outro minuto)
    _evento(db, cena["escola"].id, cena["aluno"].id, cena["fonte"],
            INSTANTE + timedelta(minutes=7))
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    ev = plano["autorizados"][0]
    assert ev["eventos_no_legado"] == 1 and ev["eventos_no_fonte"] == 1
    san.executar(db, [cena["escola"].id], None, MOTIVO)
    assert db.execute(select(EventoAluno.id)).scalars().all() != []
    assert len(db.execute(select(EventoAluno.id)).scalars().all()) == 2


# ------------------------------------------------------- 10: idempotência
def test_execucao_repetida_e_idempotente(db, escola_completa):
    cena = _par(db, escola_completa)
    primeira = san.executar(db, [cena["escola"].id], None, MOTIVO)
    assert primeira["leituras_removidas"] == 1
    segundo_ensaio = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert segundo_ensaio["total_remocoes"] == 0
    segunda = san.executar(db, [cena["escola"].id], None, MOTIVO)
    assert segunda["leituras_removidas"] == 0
    assert db.get(Leitura, cena["leitura_fonte"].id) is not None


# --------------------------------------------------- 11: dry-run não escreve
def test_dry_run_nao_altera_nada(db, escola_completa):
    cena = _par(db, escola_completa)
    leituras_antes = db.execute(select(Leitura.id)).scalars().all()
    logs_antes = db.execute(select(LogAuditoria.id)).scalars().all()
    plano = san.dry_run(db, [cena["escola"].id], MOTIVO)
    assert plano["dry_run"] is True and plano["total_remocoes"] == 1
    assert db.execute(select(Leitura.id)).scalars().all() == leituras_antes
    assert db.execute(select(LogAuditoria.id)).scalars().all() == logs_antes


# ------------------------------------- 12: falha no meio derruba o lote todo
def test_lote_inteiro_e_recusado_quando_o_motivo_falta(db, escola_completa):
    cena = _par(db, escola_completa)
    with pytest.raises(san.SaneamentoInvalido) as erro:
        san.executar(db, [cena["escola"].id], None, "curto")
    assert "motivo escrito" in str(erro.value)
    assert db.get(Leitura, cena["leitura_legado"].id) is not None
    assert db.execute(select(LogAuditoria.id)).scalars().all() == []


def test_escola_inexistente_derruba_o_lote_sem_tocar_a_valida(db, escola_completa):
    cena = _par(db, escola_completa)
    with pytest.raises(san.SaneamentoInvalido):
        san.executar(db, [cena["escola"].id, 987654], None, MOTIVO)
    assert db.get(Leitura, cena["leitura_legado"].id) is not None, (
        "o plano é conferido INTEIRO antes de apagar qualquer linha")
    assert db.execute(select(LogAuditoria.id)).scalars().all() == []


# ------------------------------------------- 13: auditoria tem o suficiente
def test_auditoria_guarda_a_linha_removida_inteira(db, escola_completa):
    cena = _par(db, escola_completa)
    alvo = cena["leitura_legado"]
    operador = escola_completa["admin"]
    esperado = {c.name: getattr(alvo, c.name) for c in Leitura.__table__.columns}
    san.executar(db, [cena["escola"].id], operador.id, MOTIVO)

    item = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == san.ACAO_ITEM)).scalars().one()
    assert item.entidade == "leitura" and item.entidade_id == alvo.id
    assert item.usuario_id == operador.id
    assert item.escola_id == cena["escola"].id
    removida = item.detalhes["leitura_removida"]
    # reconstrução: todos os campos da linha estão lá
    assert set(removida) == set(esperado)
    assert removida["aluno_id"] == esperado["aluno_id"]
    assert removida["livro_id"] == esperado["livro_id"]
    assert removida["tempo_leitura_min"] == esperado["tempo_leitura_min"]
    assert removida["data"].startswith("2026-03-30T20:50:43")
    assert item.detalhes["motivo"] == MOTIVO
    assert "regra" in item.detalhes
    evid = item.detalhes["evidencia"]
    for campo in ("escola_id", "aluno_id", "aluno_nome", "titulo_normalizado",
                  "legado_livro_id", "fonte_livro_id", "legado_elefante_id",
                  "fonte_elefante_id", "legado_nivel", "fonte_nivel",
                  "legado_origem", "fonte_origem", "legado_leitura_id",
                  "fonte_leitura_id", "legado_tempo", "fonte_tempo",
                  "delta_segundos", "delta_tempo", "classificacao"):
        assert campo in evid, campo
    assert item.detalhes["eventos_preservados"]["no_livro_legado"] == 1

    lote = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == san.ACAO_LOTE)).scalars().one()
    assert lote.detalhes["leituras_removidas"] == 1
    assert lote.detalhes["motivo"] == MOTIVO


# --------------------------------- 14: escola já reconciliada: zero candidatos
def test_escola_com_os_dois_livros_fonte_tem_zero_candidatos(db, escola_completa):
    """É o caso medido das escolas 8 e 17: as duas linhas nasceram `fonte`."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    titulo, ids = CADE
    a = _livro(db, escola.id, titulo, ids["legado"][1], "fonte", ids["legado"][0])
    b = _livro(db, escola.id, titulo, ids["fonte"][1], "fonte", ids["fonte"][0])
    _leitura(db, escola.id, aluno.id, a)
    _leitura(db, escola.id, aluno.id, b)
    assert san.auditar(db, escola.id) == []
    plano = san.dry_run(db, [escola.id], MOTIVO)
    assert plano["total_remocoes"] == 0 and plano["total_recusados"] == 0


# ------------------------------------------ 15: caso DIFERENTE fica intacto
def test_caso_diferente_permanece_intacto_ao_lado_de_um_provado(
        db, escola_completa):
    """O lote mistura um par provado e um par legítimo: só o provado sai."""
    escola = escola_completa["escola"]
    prova, legitimo = escola_completa["alunos"][0], escola_completa["alunos"][1]
    titulo, ids = CHAPEU
    legado = _livro(db, escola.id, titulo, ids["legado"][1], "legado",
                    ids["legado"][0])
    fonte = _livro(db, escola.id, titulo, ids["fonte"][1], "fonte",
                   ids["fonte"][0])
    sai_a = _leitura(db, escola.id, prova.id, legado, INSTANTE, 5)
    _leitura(db, escola.id, prova.id, fonte, INSTANTE, 5)
    fica_a = _leitura(db, escola.id, legitimo.id, legado, INSTANTE, 5)
    fica_b = _leitura(db, escola.id, legitimo.id, fonte,
                      INSTANTE + timedelta(days=10), 8)

    plano = san.dry_run(db, [escola.id], MOTIVO)
    assert plano["total_remocoes"] == 1 and plano["total_recusados"] == 1
    assert plano["classes"] == {san.PROVADA: 1, san.DIFERENTES: 1}

    san.executar(db, [escola.id], None, MOTIVO)
    assert db.get(Leitura, sai_a.id) is None
    assert db.get(Leitura, fica_a.id) is not None, "o par legítimo não se toca"
    assert db.get(Leitura, fica_b.id) is not None


# ------------------------------------------------------------- extras úteis
def test_resumo_por_escola_e_minutos_corrigidos(db, escola_completa):
    cena = _par(db, escola_completa, tempo_a=7, tempo_b=7)
    resultado = san.executar(db, [cena["escola"].id], None, MOTIVO)
    assert resultado["minutos_corrigidos"] == 7
    assert resultado["alunos"] == [cena["aluno"].id]
    por = resultado["por_escola"][str(cena["escola"].id)]
    assert por["remocoes"] == 1 and por["minutos"] == 7
    assert por["titulos"] == ["cade?"]


def test_validar_aponta_qual_condicao_falhou(db, escola_completa):
    cena = _par(db, escola_completa, quando_b=INSTANTE + timedelta(seconds=30))
    evidencias = san.auditar(db, cena["escola"].id)
    assert len(evidencias) == 1
    recusa = san.validar(evidencias[0])
    assert evidencias[0].classificacao == san.PROVAVEL
    assert san.PROVAVEL in recusa, (
        "provável não vira provado: 30 s de diferença não autoriza remoção")
