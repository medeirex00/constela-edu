"""Triagem da fila de revisão de identidade — o motor que diz "dá para encerrar
isto com segurança, e por quê".

A regra de ouro destes testes: a triagem só pode dizer SEGURA quando existe uma
evidência OBJETIVA que sustenta a conclusão. Na dúvida — duas contas na mesma
ficha, vários candidatos sem desempate, identidade de outra criança, série que
não bate — o veredito é ``decisao_humana`` com o motivo escrito.

Nada aqui depende de dados de produção: cada cenário monta a escola que precisa.
"""
import pytest
from sqlalchemy import select

from app.models import (Aluno, Escola, IdentidadeExterna, Matricula,
                        RevisaoIdentidade, Turma)
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes as tri

ANO = 2026


# --- montagem ---------------------------------------------------------------

def _escola(db, nome="Escola da Triagem"):
    e = Escola(nome=nome, ano_letivo_ativo=ANO)
    db.add(e)
    db.flush()
    return e


def _turma(db, escola, nome, ano_escolar, *, codigo=None, turno="tarde"):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=ANO, codigo_externo=codigo, turno=turno)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, status="ativo"):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, da_lista_piloto=True)
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ANO))
        db.flush()
    return a


def _vincular(db, escola, aluno, plataforma, id_externo):
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id,
                             plataforma=plataforma, id_externo=id_externo))
    db.flush()


def _revisao(db, escola, *, id_externo="uuid-1", plataforma="matific",
             formato="resumo", nome="FULANO D", turma_informada="3 ANO A TARDE (900)",
             candidatos=(), motivo="nome_casa_em_outra_sala", status="pendente",
             chave=None, linhas=None, escolhido=None):
    chave_ident = chave or f"{plataforma}|id:{id_externo}"
    r = RevisaoIdentidade(
        escola_id=escola.id, chave=f"{chave_ident}|{formato}||",
        chave_identidade=chave_ident, plataforma=plataforma, formato=formato,
        id_externo=id_externo, nome_recebido=nome, turma_informada=turma_informada,
        motivo=motivo,
        candidatos=[{"aluno_id": a.id, "nome": a.nome} for a in candidatos],
        linhas=linhas if linhas is not None else [{"atividades": 10, "estrelas": 20}],
        contexto={"tipo": "texto", "data_referencia": "2026-09-22T10:00:00"},
        origem="sincronizacao", status=status, aluno_escolhido_id=escolhido)
    db.add(r)
    db.flush()
    return r


def _triar(db, escola):
    revisoes = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id)
        .order_by(RevisaoIdentidade.id)).scalars().all()
    ctx = ida.carregar_contexto(db, escola.id, ANO)
    return tri.triar_revisoes(ctx, list(revisoes))


# --- 1. identidade externa → candidato único --------------------------------

def test_identidade_ja_vinculada_ao_candidato_e_segura(db):
    """A pendência órfã: a sincronização já criou o vínculo certo e só faltou
    encerrar o registro. É o caso de longe mais comum numa fila velha."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.SEGURA
    assert v.motivo == tri.IDENTIDADE_JA_VINCULADA
    assert v.aluno_id == a.id
    assert any("já está vinculada" in x for x in v.evidencias)


# --- 2. candidato único + série compatível (sem identidade ainda) ------------

def test_candidato_unico_com_serie_compativel_e_segura(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    r = _revisao(db, e, candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.SEGURA
    assert v.motivo == tri.CANDIDATO_UNICO_COMPATIVEL
    assert v.aluno_id == a.id
    assert any("série compatível" in x for x in v.evidencias)


# --- 3. candidato único + série INCOMPATÍVEL --------------------------------

def test_candidato_unico_com_serie_incompativel_vai_para_humano(db):
    """Mesmo nome, série diferente: o motor não pode assumir que é a mesma
    criança — é exatamente assim que dados de irmãos se misturam."""
    e = _escola(db)
    t = _turma(db, e, "5º Ano", "5º Ano", codigo="777")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    r = _revisao(db, e, candidatos=(a,), turma_informada="3 ANO A TARDE (900)")

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.SERIE_INCOMPATIVEL
    assert any("não é o da turma da ficha" in x for x in v.conflitos)


def test_codigo_da_turma_divergente_bloqueia_mesmo_com_serie_igual(db):
    """Duas turmas da MESMA série: o código externo é quem desempata a sala."""
    e = _escola(db)
    t_a = _turma(db, e, "3º Ano A", "3º Ano", codigo="901")
    _turma(db, e, "3º Ano B", "3º Ano", codigo="902")
    a = _aluno(db, e, t_a, "JOANA PEREIRA LIMA")
    r = _revisao(db, e, candidatos=(a,), turma_informada="3 ANO B TARDE (902)")

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.SERIE_INCOMPATIVEL


# --- 4. múltiplos candidatos ------------------------------------------------

def test_multiplos_candidatos_sem_identidade_nao_escolhe_ninguem(db):
    """Nunca escolher "o primeiro da lista" nem o de nome mais parecido."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a1 = _aluno(db, e, t, "MARIA HELENA LIMA")
    a2 = _aluno(db, e, t, "MARIA HELENA JESUS")
    r = _revisao(db, e, nome="MARIA H", candidatos=(a1, a2))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.AMBIGUA
    assert v.aluno_id is None
    # e ainda assim entrega ao humano o contexto de cada candidato
    assert len(v.evidencias) >= 2


def test_multiplos_candidatos_com_identidade_vinculada_a_um_deles_desempata(db):
    """A conta da plataforma já pertence a UM dos candidatos: isso é evidência
    objetiva, não probabilidade — é o passo 1 do próprio motor de identidade."""
    e = _escola(db)
    t3 = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    t1 = _turma(db, e, "1º Ano", "1º Ano", codigo="800")
    a_certa = _aluno(db, e, t3, "MARIA HELENA DE JESUS")
    a_outra = _aluno(db, e, t1, "MARIA HELENA LIMA")
    _vincular(db, e, a_certa, "matific", "uuid-1")
    _vincular(db, e, a_outra, "matific", "uuid-outro")
    r = _revisao(db, e, nome="MARIA H", candidatos=(a_outra, a_certa))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.SEGURA
    assert v.motivo == tri.IDENTIDADE_DESEMPATA
    assert v.aluno_id == a_certa.id
    assert any(f"{a_outra.id}" in x for x in v.evidencias)


def test_nunca_escolhe_o_primeiro_candidato_arbitrariamente(db):
    """Invariante de segurança: com N candidatos e nenhuma evidência, o alvo é
    None — não o primeiro, não o último, não o de id menor."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    alunos = [_aluno(db, e, t, f"NOME PARECIDO {i}") for i in range(4)]
    r = _revisao(db, e, candidatos=tuple(alunos))

    v = _triar(db, e)[r.id]
    assert v.aluno_id is None
    assert v.classificacao == tri.DECISAO_HUMANA
    for a in alunos:
        assert v.aluno_id != a.id


# --- 5. múltiplas contas no mesmo aluno -------------------------------------

def test_ficha_com_duas_contas_da_mesma_plataforma_vai_para_humano(db):
    """Nunca escolher entre duas contas — nem pela que tem mais atividades."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "ALLYCE CRISTINA")
    _vincular(db, e, a, "matific", "uuid-1")
    _vincular(db, e, a, "matific", "uuid-2")
    r = _revisao(db, e, candidatos=(a,), linhas=[{"atividades": 999, "estrelas": 999}])

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.MULTI_IDENTIDADE
    assert v.aluno_id == a.id          # o alvo é conhecido; a DECISÃO é que não
    assert any("uuid-2" in x for x in v.conflitos)


def test_duas_pendencias_abertas_disputando_a_mesma_ficha_bloqueiam_as_duas(db):
    """A mesma situação vista do outro lado: nenhuma das duas contas está
    vinculada ainda, então nenhum portão individual as pegaria — mas encerrar a
    primeira criaria a ficha com duas contas."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "MELISSA DIAS")
    r1 = _revisao(db, e, id_externo="uuid-A", candidatos=(a,))
    r2 = _revisao(db, e, id_externo="uuid-B", candidatos=(a,))

    saida = _triar(db, e)
    for r in (r1, r2):
        assert saida[r.id].classificacao == tri.DECISAO_HUMANA
        assert saida[r.id].motivo == tri.MULTI_IDENTIDADE


# --- 6. identidade conflitante ----------------------------------------------

def test_identidade_que_pertence_a_outra_ficha_nunca_e_segura(db):
    """Encerrar isto TRANSFERIRIA a conta de uma criança para outra."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    dono = _aluno(db, e, t, "PEDRO DONO DA CONTA")
    outro = _aluno(db, e, t, "PAULO CANDIDATO")
    _vincular(db, e, dono, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(outro,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.CONFLITO_IDENTIDADE
    assert v.aluno_id == dono.id
    assert any(f"ficha {dono.id}" in x for x in v.conflitos)


# --- 7. sem candidato -------------------------------------------------------

def test_sem_candidato_nao_propoe_criar_ficha(db):
    e = _escola(db)
    _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    r = _revisao(db, e, candidatos=())

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.SEM_CANDIDATO
    assert v.aluno_id is None


# --- 8. retrato superado ----------------------------------------------------

def test_retrato_superado_e_informativo_e_nao_muda_a_classificacao(db):
    """A guarda de retrato é do ``/resolver``; aqui ela só aparece no relatório —
    uma pendência com retrato superado continua sendo segura de encerrar."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,))

    ctx = ida.carregar_contexto(db, e.id, ANO)
    v = tri.triar_revisoes(ctx, [r], superados={r.id: True})[r.id]
    assert v.classificacao == tri.SEGURA
    assert v.retrato_superado is True
    assert v.como_dict()["retrato_superado"] is True


# --- 9. irmãs resumo + leituras --------------------------------------------

def test_irmas_da_mesma_identidade_sao_triadas_juntas(db):
    e = _escola(db)
    t = _turma(db, e, "4º Ano", "4º Ano", codigo="910")
    a = _aluno(db, e, t, "NICOLLAS PEREIRA")
    _vincular(db, e, a, "elefante", "2745169")
    r1 = _revisao(db, e, plataforma="elefante", formato="resumo",
                  id_externo="2745169", candidatos=(a,),
                  turma_informada="4 ANO A INTEGRAL (910)")
    r2 = _revisao(db, e, plataforma="elefante", formato="leituras",
                  id_externo="2745169", candidatos=(a,),
                  turma_informada="4 ANO A INTEGRAL (910)")

    saida = _triar(db, e)
    assert saida[r1.id].classificacao == tri.SEGURA
    assert saida[r2.id].classificacao == tri.SEGURA
    assert saida[r1.id].irmas == (r2.id,)
    assert saida[r2.id].irmas == (r1.id,)


def test_irma_bloqueada_bloqueia_o_grupo_inteiro(db):
    """Encerrar uma irmã encerra todas na mesma transação — então uma irmã que
    exige decisão humana trava o grupo, senão a decisão vazaria pela outra."""
    e = _escola(db)
    t = _turma(db, e, "4º Ano", "4º Ano", codigo="910")
    a = _aluno(db, e, t, "NICOLLAS PEREIRA")
    _vincular(db, e, a, "elefante", "2745169")
    _vincular(db, e, a, "elefante", "outra-conta")
    r1 = _revisao(db, e, plataforma="elefante", formato="resumo",
                  id_externo="2745169", candidatos=(a,),
                  turma_informada="4 ANO A INTEGRAL (910)")
    r2 = _revisao(db, e, plataforma="elefante", formato="leituras",
                  id_externo="2745169", candidatos=(a,),
                  turma_informada="4 ANO A INTEGRAL (910)")

    saida = _triar(db, e)
    assert saida[r1.id].classificacao == tri.DECISAO_HUMANA
    assert saida[r2.id].classificacao == tri.DECISAO_HUMANA
    assert {saida[r1.id].motivo, saida[r2.id].motivo} == {tri.MULTI_IDENTIDADE}


def test_irma_segura_sozinha_e_arrastada_pela_irma_bloqueada(db):
    """O contágio propriamente dito: a irmã `leituras` passaria por todos os
    portões sozinha — quem a bloqueia é a irmã `resumo`, cujo rótulo de sala
    aponta para OUTRA turma. Sem contágio, encerrar a boa encerraria a ruim."""
    e = _escola(db)
    t = _turma(db, e, "4º Ano", "4º Ano", codigo="910")
    _turma(db, e, "5º Ano", "5º Ano", codigo="920")
    a = _aluno(db, e, t, "NICOLLAS PEREIRA")
    _vincular(db, e, a, "elefante", "2745169")
    ruim = _revisao(db, e, plataforma="elefante", formato="resumo",
                    id_externo="2745169", candidatos=(a,),
                    turma_informada="5 ANO A INTEGRAL (920)")
    boa = _revisao(db, e, plataforma="elefante", formato="leituras",
                   id_externo="2745169", candidatos=(a,),
                   turma_informada="4 ANO A INTEGRAL (910)")

    saida = _triar(db, e)
    assert saida[ruim.id].motivo == tri.SERIE_INCOMPATIVEL
    assert saida[boa.id].classificacao == tri.DECISAO_HUMANA
    assert saida[boa.id].motivo == tri.IRMA_BLOQUEADA
    assert any(str(ruim.id) in c for c in saida[boa.id].conflitos)


def test_irmas_que_apontam_para_fichas_diferentes_bloqueiam_as_duas(db):
    """Mesma chave de identidade, alvos divergentes: encerrar uma escolheria
    silenciosamente a ficha da outra."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a1 = _aluno(db, e, t, "JOANA UM")
    a2 = _aluno(db, e, t, "JOANA DOIS")
    chave = "matific|nome:joana|sala:3|a"
    r1 = _revisao(db, e, id_externo="uuid-x", chave=chave, candidatos=(a1,))
    r2 = _revisao(db, e, id_externo="uuid-x", chave=chave, formato="leituras",
                  candidatos=(a2,))

    saida = _triar(db, e)
    assert saida[r1.id].classificacao == tri.DECISAO_HUMANA
    assert saida[r2.id].classificacao == tri.DECISAO_HUMANA
    assert saida[r1.id].aluno_id is None and saida[r2.id].aluno_id is None


# --- 10 e 11. transferência / fora da lista piloto --------------------------

@pytest.mark.parametrize("status", ["arquivado", "fora_lista_piloto"])
def test_ficha_inativa_nao_vira_identidade_diferente_mas_pede_gente(db, status):
    """Ausência da lista piloto é STATUS DE MATRÍCULA, não identidade: a conta
    continua sendo daquela criança. Mas aplicar dado a uma ficha fora do ranking
    é decisão de gestão, então não se encerra sozinho."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "DAVI TRANSFERIDO", status=status)
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.FICHA_INATIVA
    # a identidade NÃO foi tratada como de outra criança
    assert v.aluno_id == a.id
    assert v.motivo != tri.CONFLITO_IDENTIDADE


# --- 12. revisão órfã cujo vínculo já foi criado ----------------------------

def test_pendencia_orfa_e_reconhecida_mesmo_com_o_nome_truncado(db):
    """O caso real da escola 17: a sincronização criou o vínculo depois que a
    pendência nasceu, e o nome congelado é um prefixo ("SAMUEL Y")."""
    e = _escola(db)
    t = _turma(db, e, "4º Ano", "4º Ano", codigo="910")
    a = _aluno(db, e, t, "SAMUEL YUJRA AGUILERA")
    _vincular(db, e, a, "matific", "uuid-samuel")
    r = _revisao(db, e, id_externo="uuid-samuel", nome="SAMUEL Y",
                 candidatos=(a,), turma_informada="4 ANO A INTEGRAL (910)")

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.SEGURA
    assert v.motivo == tri.IDENTIDADE_JA_VINCULADA


# --- 13. decisão humana existente -------------------------------------------

def test_decisao_humana_anterior_destrava_ficha_inativa(db):
    """Se um gestor já escolheu ESTA ficha para ESTA identidade, a inatividade
    deixa de ser novidade e a pendência volta a ser encerrável."""
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "DAVI TRANSFERIDO", status="fora_lista_piloto")
    _vincular(db, e, a, "matific", "uuid-1")
    _revisao(db, e, formato="leituras", candidatos=(a,), status="resolvida",
             escolhido=a.id)
    r = _revisao(db, e, candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.SEGURA
    assert any("já escolheu esta mesma ficha" in x for x in v.evidencias)


# --- 14. não reabrir o que já foi resolvido ---------------------------------

def test_revisao_ja_resolvida_e_encerrada_e_nunca_volta_a_ser_acionavel(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,), status="resolvida", escolhido=a.id)

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.ENCERRADA
    assert v.segura is False
    assert v.motivo == "resolvida"


def test_revisao_descartada_tambem_fica_encerrada(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    r = _revisao(db, e, candidatos=(a,), status="descartada")

    assert _triar(db, e)[r.id].classificacao == tri.ENCERRADA


# --- 15. portões estruturais ------------------------------------------------

def test_sem_identificador_externo_nao_e_verificavel(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    r = _revisao(db, e, id_externo="", chave="matific|nome:joana|sala:3|a",
                 candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.SEM_IDENTIFICADOR


def test_candidato_sem_matricula_no_ano_nao_e_encerravel(db):
    e = _escola(db)
    _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, None, "JOANA SEM TURMA")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.SEM_MATRICULA


def test_serie_ilegivel_dos_dois_lados_sem_identidade_pede_gente(db):
    """"Maternal" x "Turma Azul": sem série e sem identidade não há o que checar."""
    e = _escola(db)
    t = _turma(db, e, "Turma Azul", "Maternal")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    r = _revisao(db, e, candidatos=(a,), turma_informada="MATERNAL MANHA")

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.SERIE_INDETERMINADA


def test_serie_ilegivel_com_identidade_vinculada_continua_segura(db):
    """A identidade externa é evidência mais forte que o rótulo da sala."""
    e = _escola(db)
    t = _turma(db, e, "Turma Azul", "Maternal")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,), turma_informada="MATERNAL MANHA")

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.SEGURA


def test_ficha_excluida_nunca_recebe_dado(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA", status="excluido")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,))

    v = _triar(db, e)[r.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.FICHA_EXCLUIDA


# --- explicabilidade --------------------------------------------------------

def test_todo_veredito_e_explicavel_por_maquina_e_por_gente(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    _vincular(db, e, a, "matific", "uuid-1")
    _vincular(db, e, a, "matific", "uuid-2")
    r = _revisao(db, e, candidatos=(a,))

    d = _triar(db, e)[r.id].como_dict()
    assert set(d) == {"classificacao", "motivo", "motivo_texto", "aluno_id",
                      "evidencias", "conflitos", "retrato_superado", "irmas"}
    assert d["motivo_texto"]                      # frase pronta para a tela
    assert d["conflitos"]                         # e o porquê, em português
    # nenhum "score de confiança" que esconda um palpite
    assert "confianca" not in d and "score" not in d


def test_resumo_agrega_por_motivo(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    boa = _aluno(db, e, t, "ALUNA BOA")
    _vincular(db, e, boa, "matific", "uuid-boa")
    _revisao(db, e, id_externo="uuid-boa", candidatos=(boa,))
    _revisao(db, e, id_externo="uuid-orfa", candidatos=())

    contagem = tri.resumo(_triar(db, e))
    assert contagem[f"{tri.SEGURA}:{tri.IDENTIDADE_JA_VINCULADA}"] == 1
    assert contagem[f"{tri.DECISAO_HUMANA}:{tri.SEM_CANDIDATO}"] == 1


def test_a_fila_da_api_ja_vem_triada(db, escola_completa, cliente):
    """A triagem chega junto com a fila, para a tela poder separar "encerrável"
    de "precisa de gente" sem refazer a conta no cliente."""
    e, turma = escola_completa["escola"], escola_completa["turma"]
    boa = escola_completa["alunos"][0]
    _vincular(db, e, boa, "matific", "uuid-boa")
    r_boa = _revisao(db, e, id_externo="uuid-boa", candidatos=(boa,),
                     turma_informada="3 ANO A TARDE (0)")
    r_ruim = _revisao(db, e, id_externo="uuid-orfa", candidatos=())
    turma.codigo_externo = None
    db.commit()

    resposta = cliente.get(f"/api/v1/escolas/{e.id}/importacoes/revisoes")
    assert resposta.status_code == 200, resposta.text
    por_id = {x["id"]: x["triagem"] for x in resposta.json()}

    assert por_id[r_boa.id]["classificacao"] == tri.SEGURA
    assert por_id[r_boa.id]["aluno_id"] == boa.id
    assert por_id[r_boa.id]["evidencias"]
    assert por_id[r_ruim.id]["classificacao"] == tri.DECISAO_HUMANA
    assert por_id[r_ruim.id]["motivo"] == tri.SEM_CANDIDATO
    assert por_id[r_ruim.id]["motivo_texto"]


def test_triar_escola_carrega_contexto_sozinha(db):
    e = _escola(db)
    t = _turma(db, e, "3º Ano", "3º Ano", codigo="900")
    a = _aluno(db, e, t, "JOANA PEREIRA LIMA")
    _vincular(db, e, a, "matific", "uuid-1")
    r = _revisao(db, e, candidatos=(a,))

    saida = tri.triar_escola(db, e.id)
    assert saida[r.id].classificacao == tri.SEGURA
    assert tri.triar_escola(db, e.id + 999) == {}
