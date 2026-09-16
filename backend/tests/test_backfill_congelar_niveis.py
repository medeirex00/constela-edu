"""Backfill OPCIONAL do nível congelado da leitura
(``scripts.vincular_livros_catalogo --congelar-niveis``).

Contrato desta rodada: a leitura passa a guardar o nível que VALE para ela
(``Leitura.nivel_codigo``), para que corrigir o catálogo depois não reescreva o
passado. O backfill grava nas leituras antigas exatamente o nível que elas já
valem hoje (o nível ATUAL do livro, que é o fallback do ``coalesce``), então
**nenhum número muda** — e é idempotente, auditado e dry-run por padrão.
"""
import sys

import pytest
from sqlalchemy import select

from app.models import Leitura, LogAuditoria, Nota
from app.services import dificuldade_livro as dl
from app.services import scoring
from scripts import vincular_livros_catalogo as script


def _leituras(db, escola_id):
    return {l.id: l for l in db.execute(
        select(Leitura).where(Leitura.escola_id == escola_id)).scalars()}


@pytest.fixture()
def acervo(db, escola_completa):
    """Três leituras: uma a congelar, uma JÁ congelada (com nível diferente do
    livro, para provar que não é sobrescrita) e uma de livro SEM nível."""
    from app.models import Livro

    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    com_nivel = Livro(escola_id=esc.id, titulo="O Mapa Perdido", nivel_codigo="D")
    sem_nivel = Livro(escola_id=esc.id, titulo="Sem Nível", nivel_codigo="")
    db.add_all([com_nivel, sem_nivel])
    db.flush()
    a_congelar = Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=com_nivel.id,
                         tempo_leitura_min=10)
    ja_congelada = Leitura(escola_id=esc.id, aluno_id=joao.id, livro_id=com_nivel.id,
                           tempo_leitura_min=10, nivel_codigo="E", catalogo_versao="abc123456789")
    sem = Leitura(escola_id=esc.id, aluno_id=sofia.id, livro_id=sem_nivel.id,
                  tempo_leitura_min=10)
    db.add_all([a_congelar, ja_congelada, sem])
    db.commit()
    return {"escola": esc, "a_congelar": a_congelar.id, "ja_congelada": ja_congelada.id,
            "sem_nivel": sem.id}


def test_dry_run_classifica_e_nao_grava(db, acervo):
    esc = acervo["escola"]
    relatorio = script.analisar_congelamento(db, esc.id, esc.nome)

    assert relatorio.por_nivel == {"D": [acervo["a_congelar"]]}
    assert relatorio.congelaveis == 1
    assert relatorio.ja_congeladas == 1
    assert relatorio.sem_nivel_no_livro == 1
    # analisar não grava nada
    assert _leituras(db, esc.id)[acervo["a_congelar"]].nivel_codigo is None
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "leitura.nivel_congelado")).scalars().all() == []


def test_congela_o_nivel_atual_do_livro_com_auditoria_agregada_e_e_idempotente(db, acervo):
    esc = acervo["escola"]
    n = script.congelar(db, script.analisar_congelamento(db, esc.id, esc.nome))
    assert n == 1

    leituras = _leituras(db, esc.id)
    # 1) a leitura antiga guarda o nível que ela JÁ valia (o atual do livro)
    congelada = leituras[acervo["a_congelar"]]
    assert congelada.nivel_codigo == "D"
    assert congelada.catalogo_versao == dl.versao_catalogo()["versao"]
    # 2) a que já estava congelada NÃO é sobrescrita (mesmo com nível ≠ do livro)
    assert leituras[acervo["ja_congelada"]].nivel_codigo == "E"
    assert leituras[acervo["ja_congelada"]].catalogo_versao == "abc123456789"
    # 3) livro sem nível continua nulo (o fallback dá o mesmo resultado)
    assert leituras[acervo["sem_nivel"]].nivel_codigo is None

    # 4) auditoria AGREGADA: UMA linha por escola, com a contagem por nível
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "leitura.nivel_congelado")).scalars().all()
    assert len(logs) == 1
    assert logs[0].escola_id == esc.id
    assert logs[0].detalhes["qtd"] == 1
    assert logs[0].detalhes["por_nivel"] == {"D": 1}
    assert logs[0].detalhes["sem_nivel_no_livro"] == 1
    assert logs[0].detalhes["origem"].endswith("--congelar-niveis")

    # 5) IDEMPOTENTE: a segunda passada não tem o que congelar nem audita de novo
    assert script.congelar(db, script.analisar_congelamento(db, esc.id, esc.nome)) == 0
    assert len(db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "leitura.nivel_congelado")).scalars().all()) == 1


def test_congelamento_nao_muda_nenhuma_nota(db, acervo):
    """O valor congelado é o que a leitura já valia: recalcular depois do backfill
    dá exatamente a mesma nota (o backfill não é um recálculo disfarçado)."""
    esc = acervo["escola"]
    scoring.recalcular_escola(db, esc.id)
    antes = {n.aluno_id: (n.nota_elefante, n.nota_geral,
                          n.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"])
             for n in db.execute(select(Nota).where(Nota.escola_id == esc.id)).scalars()}

    script.congelar(db, script.analisar_congelamento(db, esc.id, esc.nome))
    scoring.recalcular_escola(db, esc.id)
    db.expire_all()

    depois = {n.aluno_id: (n.nota_elefante, n.nota_geral,
                           n.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"])
              for n in db.execute(select(Nota).where(Nota.escola_id == esc.id)).scalars()}
    assert depois == antes


def test_nivel_congelado_vazio_conta_como_congelado_e_nao_e_regravado(db, escola_completa):
    """RECONFERÊNCIA — o corte é ``IS NULL``, não "sem texto".

    O motor lê ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)``: em SQL o
    ``coalesce`` só cai no livro quando a coluna é NULA, então uma leitura com
    nível congelado VAZIO já vale 0 ponto (a régua ignora item sem letra). Se o
    backfill a tratasse como "não congelada" e gravasse o nível do livro, ela
    passaria de 0 para o valor do nível — o backfill MUDARIA um número, que é
    exatamente o que ele promete nunca fazer.

    O caso chega a existir: `aplicar_ao_historico` num livro legado sem nível
    grava "" no congelado das leituras dele."""
    from app.models import Livro

    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = Livro(escola_id=esc.id, titulo="Congelado Vazio", nivel_codigo="D")
    db.add(livro)
    db.flush()
    vazia = Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=livro.id,
                    tempo_leitura_min=10, nivel_codigo="")
    db.add(vazia)
    db.commit()

    # 1) o motor já a considera congelada (o coalesce devolve "", não "D")
    itens = dl.leituras_por_aluno(db, esc.id, {ana.id})[ana.id]
    assert [i.nivel for i in itens] == [""]
    assert dl.RegraGlobal().pontos_por_chave({}, "5", leituras=itens) == {}

    # 2) o backfill a classifica como JÁ congelada e não a toca
    relatorio = script.analisar_congelamento(db, esc.id, esc.nome)
    assert relatorio.ja_congeladas == 1
    assert relatorio.por_nivel == {}
    assert script.congelar(db, relatorio) == 0
    db.expire_all()
    assert db.get(Leitura, vazia.id).nivel_codigo == ""


def test_auditoria_valora_a_leitura_como_o_motor(db, escola_completa):
    """RECONFERÊNCIA do ajuste 3 — ``auditar_notas_elefante._valor_da_leitura``
    tem de dar EXATAMENTE o mesmo valor que a régua dá ao item que o motor monta
    (id oficial antes do título; nível congelado com fallback só no NULO)."""
    from app.models import Livro
    from scripts import auditar_notas_elefante as auditoria

    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    oficial = dl.catalogo().por_id[sorted(dl.catalogo().por_id)[0]]

    # (a) título RENOMEADO na escola, mas com o id oficial: vale pelo id
    renomeado = Livro(escola_id=esc.id, titulo="Título Trocado Pela Escola",
                      nivel_codigo=oficial.nivel, elefante_id=oficial.id)
    # (b) leitura com nível congelado ≠ do livro: vale pelo congelado
    outro = Livro(escola_id=esc.id, titulo="Outro", nivel_codigo="B")
    db.add_all([renomeado, outro])
    db.flush()
    leituras = [
        Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=renomeado.id),
        Leitura(escola_id=esc.id, aluno_id=joao.id, livro_id=outro.id, nivel_codigo="Z"),
        Leitura(escola_id=esc.id, aluno_id=sofia.id, livro_id=outro.id, nivel_codigo=""),
    ]
    db.add_all(leituras)
    db.commit()

    regra = dl.RegraGlobal()
    livro_por_id = {renomeado.id: renomeado, outro.id: outro}
    for leitura in leituras:
        livro = livro_por_id[leitura.livro_id]
        # o item EXATO que o motor monta para esta leitura (mesmo coalesce em SQL)
        item = next(i for i in dl.leituras_por_aluno(db, esc.id, {leitura.aluno_id})[leitura.aluno_id]
                    if i.titulo == livro.titulo)
        esperado = regra.valor_livro(item.nivel, item.titulo, "5", elefante_id=item.elefante_id)
        obtido = auditoria._valor_da_leitura(regra, leitura, livro, "5", None)
        assert obtido == pytest.approx(esperado), \
            f"auditoria {obtido} ≠ motor {esperado} em {livro.titulo}"

    # (a) o id oficial vence o título renomeado na escola
    assert auditoria._valor_da_leitura(regra, leituras[0], renomeado, "5", None) == pytest.approx(
        regra.valor_livro(oficial.nivel, "qualquer outro título", "5", elefante_id=oficial.id))
    # (b) o congelado ("Z") vence o nível ATUAL do livro ("B")
    valor_b = regra.valor_livro("B", outro.titulo, "5")
    assert auditoria._valor_da_leitura(regra, leituras[1], outro, "5", None) == pytest.approx(
        regra.valor_livro("Z", outro.titulo, "5"))
    assert regra.valor_livro("Z", outro.titulo, "5") > valor_b
    # (c) congelado VAZIO não cai no nível do livro (seria `or`, não `coalesce`):
    #     o motor não pontua esse item, e a auditoria acompanha.
    vazio = next(i for i in dl.leituras_por_aluno(db, esc.id, {sofia.id})[sofia.id])
    assert vazio.nivel == "" and regra.pontos_por_chave({}, "5", leituras=[vazio]) == {}
    assert auditoria._valor_da_leitura(regra, leituras[2], outro, "5", None) < valor_b


def test_relatorio_nao_quebra_em_console_cp1252(db, acervo, monkeypatch):
    """RECONFERÊNCIA — o script tem de rodar no console PADRÃO do Windows.

    O relatório imprime ``→`` e ``≠``, que não existem em ``cp1252``: num terminal
    Windows comum o ``print`` estourava ``UnicodeEncodeError`` e matava a execução
    ANTES do congelamento (o teste de ``main`` não via porque o ``capsys`` do
    pytest captura em UTF-8, e um dry-run contra banco vazio nunca chega a
    imprimir o relatório por escola). ``_saida_tolerante`` degrada o caractere
    em vez de abortar."""
    import io

    class _SessaoSemFechar:
        def __init__(self, sessao): self._sessao = sessao
        def __getattr__(self, nome): return getattr(self._sessao, nome)
        def close(self): pass

    esc = acervo["escola"]
    monkeypatch.setattr(script, "SessionLocal", lambda: _SessaoSemFechar(db))
    monkeypatch.setattr(sys, "argv", ["vincular_livros_catalogo", "--congelar-niveis",
                                      "--aplicar", "--escola", str(esc.id)])
    bruto = io.BytesIO()
    console = io.TextIOWrapper(bruto, encoding="cp1252", newline="")   # errors="strict"
    monkeypatch.setattr(sys, "stdout", console)
    try:
        assert script.main() == 0            # sem o fix: UnicodeEncodeError
    finally:
        console.flush()
        monkeypatch.undo()

    saida = bruto.getvalue().decode("cp1252")
    assert "divergências de nível" in saida          # a linha do `≠` saiu
    assert "leitura(s) com nível congelado" in saida  # a linha do `→` saiu
    assert "ê" in saida                               # acento preservado


def test_main_congelar_niveis_e_dry_run_por_padrao(db, acervo, monkeypatch, capsys):
    """A flag na linha de comando: sem ``--aplicar`` só relata; com ``--aplicar``
    grava. (Mesma disciplina do resto do script.)"""
    class _SessaoSemFechar:                       # main() fecha a sessão no finally
        def __init__(self, sessao):
            self._sessao = sessao

        def __getattr__(self, nome):
            return getattr(self._sessao, nome)

        def close(self):
            pass

    esc = acervo["escola"]
    monkeypatch.setattr(script, "SessionLocal", lambda: _SessaoSemFechar(db))

    monkeypatch.setattr(sys, "argv", ["vincular_livros_catalogo", "--congelar-niveis",
                                      "--escola", str(esc.id)])
    assert script.main() == 0
    saida = capsys.readouterr().out
    assert "DRY-RUN" in saida and "a congelar: 1" in saida
    assert _leituras(db, esc.id)[acervo["a_congelar"]].nivel_codigo is None   # nada gravado

    monkeypatch.setattr(sys, "argv", ["vincular_livros_catalogo", "--congelar-niveis",
                                      "--aplicar", "--escola", str(esc.id)])
    assert script.main() == 0
    assert "1 leitura(s) com nível congelado" in capsys.readouterr().out
    assert _leituras(db, esc.id)[acervo["a_congelar"]].nivel_codigo == "D"
