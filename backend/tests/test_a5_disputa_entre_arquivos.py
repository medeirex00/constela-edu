"""A5 entre arquivos: a disputa "duas contas sem vínculo para a mesma ficha" vale
também nos arquivos SEGUINTES da coleta, não só no relatório que a abriu.

Caso (revisão independente da branch fix/pp-identidade): o resumo do Elefante
traz as contas 701 e 702, as duas casando com a mesma ficha — as duas vão para a
revisão ``outra_identidade_na_plataforma`` (certo). O arquivo seguinte da mesma
coleta, o histórico de leituras, traz só a 701: ela casava pelo nome, levava a
ficha e gravava a leitura — quem decidia era qual conta aparecia no arquivo de
leituras —, e a triagem passava a chamar a pendência dela de "segura".

O mesmo para a ficha NOVA (``contas_repetidas_no_relatorio``): a conta que vem
sozinha no arquivo seguinte não cria a ficha que as duas disputam.
Dados fictícios.
"""
from app.models import RevisaoIdentidade
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes as tri
from tests.sync_integridade_comum import (aluno, aplicar, com_nome, dono, elefante_leituras,
                                          elefante_resumo, leituras, pendentes, sem_disco,
                                          vincular)

K = "3 ANO A TARDE ANUAL (300396804)"
NOME = "Zefa Quaresma Lima"


def _resumo_com_duas_contas(db, esc, nome=NOME):
    aplicar(db, esc, elefante_resumo(K, [
        {"studentId": 701, "studentName": nome, "totalBooksRead": 2},
        {"studentId": 702, "studentName": nome, "totalBooksRead": 40}]))


def _leituras_so_da_701(db, esc, nome=NOME):
    aplicar(db, esc, elefante_leituras(K, [
        {"nome": nome, "studentId": 701, "bookTitle": "Livro Ficticio A",
         "lastReadWhen": "2026-08-01T10:00:00"}]))


def test_conta_disputada_no_resumo_nao_leva_a_ficha_pelo_arquivo_de_leituras(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    f = aluno(db, esc.id, t, NOME, da_lista_piloto=True)
    db.commit()
    fid = f.id
    _resumo_com_duas_contas(db, esc)
    assert {(p.id_externo, p.motivo) for p in pendentes(db, esc.id)} == {
        ("701", "outra_identidade_na_plataforma"), ("702", "outra_identidade_na_plataforma")}
    _leituras_so_da_701(db, esc)
    assert dono(db, esc.id, "elefante", "701") is None
    assert leituras(db, fid) == 0
    # A leitura não se perdeu: está na fila, na pendência de leituras da 701.
    [lei] = [p for p in pendentes(db, esc.id) if p.formato == "leituras"]
    assert lei.id_externo == "701" and lei.motivo == "outra_identidade_na_plataforma"
    # E a triagem não chama nenhuma das duas de segura.
    revs = pendentes(db, esc.id)
    triagem = tri.triar_revisoes(ida.carregar_contexto(db, esc.id), revs)
    assert all(not triagem[r.id].segura for r in revs)


def test_descartada_a_disputa_a_conta_que_sobrou_segue_pelo_nome(
        db, escola_completa, monkeypatch):
    """A trava dura enquanto a pendência da OUTRA conta está aberta — não para sempre."""
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    f = aluno(db, esc.id, t, NOME, da_lista_piloto=True)
    db.commit()
    fid = f.id
    _resumo_com_duas_contas(db, esc)
    for p in pendentes(db, esc.id):
        if p.id_externo == "702":
            p.status = "descartada"
    db.commit()
    _leituras_so_da_701(db, esc)
    assert dono(db, esc.id, "elefante", "701") == fid
    assert leituras(db, fid) == 1


def _pendencia_disputa(db, esc_id, conta, ficha_id):
    chave_ident = ida.chave_identidade_da_conta("elefante", conta)
    rev = RevisaoIdentidade(escola_id=esc_id, chave=ida.chave_pendencia(chave_ident, "resumo"),
                            chave_identidade=chave_ident, plataforma="elefante",
                            formato="resumo", id_externo=conta, nome_recebido=NOME,
                            turma_informada=K, motivo="outra_identidade_na_plataforma",
                            candidatos=[{"aluno_id": ficha_id, "nome": NOME}],
                            linhas=[{"livros_unicos": 1}], contexto={},
                            origem="sincronizacao", ocorrencias=1, status="pendente")
    db.add(rev)
    db.flush()
    return rev


def test_triagem_nao_chama_de_segura_a_conta_vinculada_com_rival_aberta(db, escola_completa):
    """A 701 já está na ficha (como a coleta antiga a deixava) e a 702 ainda disputa a
    mesma ficha numa pendência aberta: a da 701 não é "segura" — nem quando a lista
    triada (a página da fila) não traz a pendência da 702."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    f = aluno(db, esc.id, t, NOME, da_lista_piloto=True)
    vincular(db, esc.id, f.id, "elefante", "701")
    r701 = _pendencia_disputa(db, esc.id, "701", f.id)
    r702 = _pendencia_disputa(db, esc.id, "702", f.id)
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    triagem = tri.triar_revisoes(ctx, [r701, r702])
    assert not triagem[r701.id].segura
    assert triagem[r701.id].motivo == tri.MULTI_IDENTIDADE
    so_a_701 = tri.triar_revisoes(ctx, [r701])
    assert not so_a_701[r701.id].segura


def test_conta_da_disputa_vinculada_a_outra_ficha_nao_trava_mais(db, escola_completa):
    """A rival que já ganhou OUTRA ficha deixou de disputar esta."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    f = aluno(db, esc.id, t, NOME, da_lista_piloto=True)
    g = aluno(db, esc.id, t, "Zefa Quintana Borba")
    vincular(db, esc.id, g.id, "elefante", "702")
    _pendencia_disputa(db, esc.id, "702", f.id)
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.contas_rivais("elefante", f.id, "701") == set()
    d = ida.decidir(ctx, ida.LinhaIdentidade(nome=NOME, plataforma="elefante",
                                             id_externo="701", turma_nome=K))
    assert d.acao == ida.ASSOCIAR and d.aluno_id == f.id


def test_conta_que_vem_sozinha_no_arquivo_seguinte_nao_cria_a_ficha_disputada(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc = escola_completa["escola"]
    nova = "Zefa Nunes Ficticia"
    _resumo_com_duas_contas(db, esc, nova)
    assert {(p.id_externo, p.motivo) for p in pendentes(db, esc.id)} == {
        ("701", "contas_repetidas_no_relatorio"), ("702", "contas_repetidas_no_relatorio")}
    _leituras_so_da_701(db, esc, nova)
    assert com_nome(db, esc.id, nova) == []
    assert dono(db, esc.id, "elefante", "701") is None
    [lei] = [p for p in pendentes(db, esc.id) if p.formato == "leituras"]
    assert lei.id_externo == "701" and lei.motivo == "contas_repetidas_no_relatorio"
