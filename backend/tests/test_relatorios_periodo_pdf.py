"""O PDF do Relatório por Período: mesmos números, mesma permissão, nome seguro.

O teste que sustenta o arquivo é ``test_paridade_...``: o PDF é aberto de volta,
o texto é extraído e comparado contra o dicionário que o motor produziu. Não
basta o arquivo abrir — um PDF bonito com o número errado é pior que nenhum.

DOIS CAMINHOS, e os dois importam. Com Chromium, o PDF é o de vitrine
(``_relatorio_html_pdf``); sem ele, cai no simples (``gerar_pdf``/fpdf). O job de
testes do backend na integração contínua instala o ``requirements.txt`` e NÃO
baixa o Chromium (.github/workflows/ci.yml) — então lá roda a reserva. Por isso
o grosso dos testes força a reserva (determinístico e igual ao CI) e dois testes
exercitam o renderizador real, pulando quando o navegador não existe.
"""
import re
from datetime import date, datetime

import pdfplumber
import pytest

from app.core.security import hash_senha
from app.models import (Aluno, Escola, EventoAluno, Leitura, Livro, LogAuditoria,
                        Matricula, Professor, Rede, Turma, Usuario)
from app.services import relatorios_periodo as rp
from app.services import relatorios_periodo_pdf as pdf
from app.services.eventos import chave_evento
from sqlalchemy import select

ROTA = "/api/v1/escolas/{eid}/relatorios/periodo.pdf"
ROTA_JSON = "/api/v1/escolas/{eid}/relatorios/periodo"
HOJE = date(2026, 10, 5)


@pytest.fixture()
def sem_chromium(monkeypatch):
    """Força o caminho de RESERVA — o mesmo que roda na integração contínua."""
    def explode(*_a, **_k):
        raise RuntimeError("sem Chromium (forçado pelo teste)")
    monkeypatch.setattr(pdf, "_relatorio_html_pdf", explode)


def _texto(conteudo: bytes) -> str:
    """O texto de volta do PDF. Se o arquivo for inválido, isto levanta —
    e é assim que o teste descobre, em vez de passar por descuido."""
    import io
    with pdfplumber.open(io.BytesIO(conteudo)) as doc:
        return "\n".join((p.extract_text() or "") for p in doc.pages)


def _semear(db, escola_id, aluno_id, titulo, quando, tempo, nivel="D"):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel)
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id,
                   data=quando, tempo_leitura_min=tempo, nivel_codigo=nivel))
    db.add(EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=titulo,
        livro_id=livro.id, tempo_segundos=tempo * 60, nivel_codigo=nivel,
        chave_natural=chave_evento("elefante", "leitura", aluno_id, titulo,
                                   quando, "")))
    db.flush()
    return livro


@pytest.fixture()
def cenario(db, escola_completa):
    """Setembro com livro novo e releitura.

    Os números são DISTINTOS e de DOIS DÍGITOS de propósito. Com 2, 3 e 1, as
    asserções do tipo `"2" in texto` passavam por acidente — a data
    "01/09/2026" e a coluna "Nº" já traziam todos os dígitos de 0 a 9, e trocar
    o rótulo de `livros_novos` com o de `livros_com_atividade` ficava verde.
    Aqui: 11 livros novos, 5 relidos, 16 com atividade, 95 min — nenhum par
    coincide e nenhum é substring de outro campo.
    """
    escola = escola_completa["escola"]
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    # 5 livros importados em JULHO e relidos em SETEMBRO (só o evento marca)
    for i in range(5):
        antigo = _semear(db, escola.id, a.id, f"Lido em julho {i}",
                         datetime(2026, 7, 10, 9, i), 4)
        quando = datetime(2026, 9, 18, 14, i)
        db.add(EventoAluno(
            escola_id=escola.id, aluno_id=a.id, plataforma="elefante",
            tipo_evento="leitura", ocorrido_em=quando,
            conteudo_titulo=antigo.titulo, livro_id=antigo.id,
            tempo_segundos=7 * 60, nivel_codigo=antigo.nivel_codigo,
            chave_natural=chave_evento("elefante", "leitura", a.id,
                                       antigo.titulo, quando, "")))
    # 8 livros NOVOS do aluno A (8 x 10 min = 80) e 3 do aluno B (5 min cada)
    for i in range(8):
        _semear(db, escola.id, a.id, f"Novo A {i}", datetime(2026, 9, 3, 10, i), 10)
    for i in range(3):
        _semear(db, escola.id, b.id, f"Novo B {i}", datetime(2026, 9, 21, 10, i), 5)
    db.commit()
    return escola_completa


def _snap(db, escola_id, aluno_id, quando, tentativas, acertos):
    """Retrato do Elefante — as questões só existem como acumulado nele."""
    from app.models import Importacao, SnapshotElefante
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="seed", arquivo_original=None, qtd_alunos=0, qtd_erros=0,
                     tempo_ms=0, status="concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id,
                            importacao_id=imp.id, data_referencia=quando,
                            livros_unicos=0, tempo_leitura_min=0,
                            questoes_tentativas=tentativas,
                            questoes_acertos=acertos, livros_por_nivel={}))
    db.flush()


def _dados(db, escola_id, **kw):
    kw.setdefault("preset", "mes_anterior")
    kw.setdefault("plataformas", ("elefante",))
    kw.setdefault("hoje", HOJE)
    return rp.gerar(db, escola_id, **kw)


# ============================================================================
# 20. O TESTE QUE IMPORTA — os números do PDF são os do motor
# ============================================================================
def test_paridade_os_numeros_do_pdf_sao_os_do_motor(db, cenario, sem_chromium):
    """Gera pelo motor, gera o PDF com o MESMO filtro, abre o PDF e confere.

    Não valida presença genérica de palavras: compara cada número do resultado.
    """
    escola = cenario["escola"]
    dados = _dados(db, escola.id)
    ele = dados["elefante"]

    # (1) O motor produz o que o cenário promete. Literal, não derivado.
    assert ele["livros_novos"] == 11
    assert ele["livros_com_atividade"] == 16
    assert ele["livros_relidos"] == 5
    assert ele["tempo_min"] == 95

    # (2) Cada RÓTULO carrega o SEU valor — par a par, contra um dicionário
    # escrito aqui. Comparar `valor in texto` seria circular (o renderizador e o
    # teste leriam a mesma `linhas_resumo`) e deixaria passar a troca de duas
    # etiquetas, que é exatamente o erro que esta funcionalidade existe para
    # impedir: "Livros novos 16" discordaria do pódio, que diz 11.
    esperado = {
        "Estudantes no recorte": "3",
        "Com atividade no período": "2",
        "Livros novos": "11",
        "Tempo de leitura": "1h 35min",
        "Estudantes com livro novo": "2",
        "Livros com atividade": "16",
        "Livros relidos": "5",
        "Registros de leitura": "16",
        "Tempo por registro de leitura": pdf.SEM_SUPORTE,
    }
    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    for rotulo, valor in esperado.items():
        achado = re.search(rf"^{re.escape(rotulo)}\s+(\S+(?: \S+)?)", texto,
                           re.MULTILINE)
        assert achado, f"o PDF perdeu a linha {rotulo!r}"
        assert achado.group(1).startswith(valor), (
            f"{rotulo!r}: o PDF diz {achado.group(1)!r}, o motor diz {valor!r}")

    # (3) E nada do resumo pode sumir pelo caminho
    for rotulo, valor, _fonte in pdf.linhas_resumo(dados):
        assert rotulo in texto, f"o PDF perdeu a linha {rotulo!r}"
    assert dados["periodo"]["rotulo"] in texto
    assert escola.nome in texto


def test_paridade_vale_tambem_para_o_que_nao_e_suportado(db, cenario, sem_chromium):
    """Métrica sem dado sai declarada no papel — nunca como zero."""
    dados = _dados(db, cenario["escola"].id, plataformas=("elefante", "matific"))
    assert dados["elefante"]["tempo_min_por_evento"] is None
    assert dados["matific"]["questoes"] is None
    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    assert "Tempo por registro de leitura" in texto
    assert "Questões (Matific)" in texto
    assert texto.count(pdf.SEM_SUPORTE) >= 2


def test_pdf_nao_consulta_o_banco(db, cenario):
    """O módulo do PDF não importa Session nem modelo: a única entrada é o dict.

    É o que torna a divergência entre tela e papel impossível por construção,
    em vez de improvável por disciplina.
    """
    import ast
    import inspect
    arvore = ast.parse(inspect.getsource(pdf))
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")
        elif isinstance(no, ast.Import):
            importados.update(a.name for a in no.names)
    assert not any(m.startswith("app.models") for m in importados), importados
    assert not any(m.startswith("sqlalchemy") for m in importados), importados
    # a única dependência de app.* é a MOLDURA de relatório, não dado
    assert {m for m in importados if m.startswith("app.")} == {
        "app.core.tempo", "app.services.relatorios"}
    # e nenhuma função recebe sessão
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef):
            nomes = [a.arg for a in no.args.args + no.args.kwonlyargs]
            assert "db" not in nomes and "session" not in nomes, no.name


# ============================================================================
# 1 a 3 — os três escopos
# ============================================================================
def test_pdf_de_escola(db, cenario, cliente, sem_chromium):
    escola = cenario["escola"]
    r = cliente.get(ROTA.format(eid=escola.id),
                    params={"periodo": "mes_anterior", "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert "RESUMO DO PERÍODO" in texto
    assert "POR TURMA" in texto and "POR ESTUDANTE" in texto
    assert escola.nome in texto


def test_pdf_de_turma(db, cenario, cliente, sem_chromium):
    escola, turma = cenario["escola"], cenario["turma"]
    r = cliente.get(ROTA.format(eid=escola.id),
                    params={"periodo": "mes_anterior", "escopo": "turma",
                            "turma_id": turma.id, "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert turma.nome in texto
    assert "Turma" in texto


def test_pdf_de_aluno_nao_mostra_outro_aluno(db, cenario, cliente, sem_chromium):
    escola = cenario["escola"]
    a, b = cenario["alunos"][0], cenario["alunos"][1]
    r = cliente.get(ROTA.format(eid=escola.id),
                    params={"periodo": "mes_anterior", "escopo": "aluno",
                            "aluno_id": a.id, "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert a.nome in texto
    assert b.nome not in texto, "o relatório individual vazou outro estudante"


# ============================================================================
# 4 a 6 — as plataformas
# ============================================================================
def test_pdf_somente_elefante(db, cenario, cliente, sem_chromium):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "mes_anterior", "plataformas": "elefante"})
    assert r.status_code == 200
    texto = _texto(r.content)
    assert "Livros novos" in texto
    assert "Atividades (Matific)" not in texto


def test_pdf_somente_matific(db, cenario, cliente, sem_chromium):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "mes_anterior", "plataformas": "matific"})
    assert r.status_code == 200
    texto = _texto(r.content)
    assert "Atividades (Matific)" in texto
    assert "Livros novos" not in texto


def test_pdf_das_duas_plataformas(db, cenario, cliente, sem_chromium):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "mes_anterior",
                            "plataformas": ["elefante", "matific"]})
    assert r.status_code == 200
    texto = _texto(r.content)
    assert "Livros novos" in texto and "Atividades (Matific)" in texto
    assert "Elefante Letrado + Matific" in texto


# ============================================================================
# 7 a 10 — os períodos
# ============================================================================
@pytest.mark.parametrize("preset,esperado", [
    ("mes", "Este mês"),
    ("mes_anterior", "Mês anterior"),
    ("bimestre_3", "3º bimestre"),
    ("ano_letivo", "Ano letivo 2026"),
])
def test_pdf_por_preset(db, cenario, cliente, sem_chromium, preset, esperado):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": preset, "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    assert esperado in _texto(r.content)


def test_pdf_personalizado_imprime_as_duas_datas(db, cenario, cliente, sem_chromium):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "personalizado", "inicio": "2026-09-10",
                            "fim": "2026-09-25", "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert "10/09/2026 a 25/09/2026" in texto


def test_periodo_aberto_nao_vira_sem_dado(db, cenario, cliente, sem_chromium):
    """O preset "tudo" não tem início nem fim — de propósito.

    Imprimir "sem dado a sem dado" faria o relatório parecer quebrado
    justamente quando ele está completo.
    """
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "tudo", "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert "todo o histórico registrado" in texto
    assert f"{pdf.SEM_DADO} a {pdf.SEM_DADO}" not in texto


@pytest.mark.parametrize("periodo,esperado", [
    ({"inicio": None, "fim": None}, "todo o histórico registrado"),
    ({"inicio": "2026-10-01T00:00:00", "fim": "2026-10-31T23:59:59"},
     "01/10/2026 a 31/10/2026"),
    ({"inicio": None, "fim": "2026-10-31T23:59:59"}, "até 31/10/2026"),
    ({"inicio": "2026-10-01T00:00:00", "fim": None}, "a partir de 01/10/2026"),
])
def test_intervalo_por_extenso(periodo, esperado):
    assert pdf._intervalo(periodo) == esperado


def test_instante_de_coleta_sai_no_fuso_de_brasilia(db, cenario, sem_chromium):
    """O PDF e a tela têm de dizer a MESMA hora para o MESMO campo.

    `data_referencia` é gravada em UTC e serializada sem fuso; a tela anexa "Z"
    e renderiza em America/Sao_Paulo. Imprimir o UTC cru aqui deslocaria o papel
    em 3h — e numa coleta das 22h deslocaria o DIA, fazendo o aviso de janela
    efetiva dizer outubro onde a tela diz setembro.
    """
    assert pdf._data_hora("2026-10-01T01:20:00") == "30/09/2026 22:20"
    assert pdf._data_hora("2026-08-31T21:05:00") == "31/08/2026 18:05"
    # as datas do PERÍODO não são convertidas: já vêm no fuso da escola
    assert pdf._data("2026-09-01T00:00:00") == "01/09/2026"

    escola = cenario["escola"]
    aluno = cenario["alunos"][0]
    # coleta gravada 30/09 02:30 UTC = 29/09 23:30 em Brasília — a conversão
    # muda o DIA, que é o caso que faria tela e papel discordarem de mês.
    _snap(db, escola.id, aluno.id, datetime(2026, 8, 31, 12, 0), 10, 8)
    _snap(db, escola.id, aluno.id, datetime(2026, 9, 30, 2, 30), 40, 30)
    db.commit()
    dados = _dados(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert dados["elefante"]["janela_efetiva_questoes"] is not None
    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    assert "29/09/2026 23:30" in texto
    assert "30/09/2026 02:30" not in texto, "saiu o UTC cru, não o horário da escola"


def test_pdf_declara_o_recorte_do_professor(db, cenario, sem_chromium):
    """Escopo "escola" para um professor restrito NÃO é a escola inteira.

    O PDF circula sozinho: sem esta linha ele sai rotulado "Escola inteira" e,
    encaminhado à secretaria, lê-se como o mês da escola.
    """
    escola, turma = cenario["escola"], cenario["turma"]
    dados = _dados(db, escola.id, turma_ids=[turma.id])
    assert dados["escopo"]["restrito_a_turmas"] == [turma.id]
    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    assert "Recorte do usuário" in texto
    assert "1 turma" in texto
    # e no HTML de vitrine a frase inteira, que a célula do fpdf trunca
    assert "NÃO é a escola inteira" in pdf.montar_html(dados)
    # sem restrição, a linha não aparece
    limpo = _texto(pdf.gerar(_dados(db, escola.id), cor="#1B2A4A"))
    assert "Recorte do usuário" not in limpo


def test_reserva_carrega_as_ressalvas_e_a_janela_efetiva(db, cenario, sem_chromium):
    """Carregar o número e largar o que ele significa entrega um documento que
    parece completo e não está."""
    escola, aluno = cenario["escola"], cenario["alunos"][0]
    _snap(db, escola.id, aluno.id, datetime(2026, 8, 15, 12, 0), 10, 8)
    _snap(db, escola.id, aluno.id, datetime(2026, 9, 29, 12, 0), 40, 30)
    db.commit()
    dados = _dados(db, escola.id, plataformas=("elefante", "matific"))
    texto = _texto(pdf._reserva(dados, "#1B2A4A"))
    assert "Janela efetiva" in texto
    assert "Ressalva" in texto
    # a vitrine e a reserva dizem as MESMAS ressalvas
    assert pdf._ressalvas(dados), "o motor devolveu ressalvas?"
    for nome, _r in pdf._ressalvas(dados):
        assert nome.split(" · ")[1][:12] in texto


def test_queda_para_a_reserva_deixa_rastro(db, cenario, monkeypatch, caplog):
    """A degradação é deliberada, mas não silenciosa: sem log, um defeito meu em
    `montar_html` se disfarçaria de "esta máquina não tem navegador"."""
    import logging
    monkeypatch.setattr(pdf, "_relatorio_html_pdf",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    dados = _dados(db, cenario["escola"].id)
    with caplog.at_level(logging.WARNING):
        conteudo = pdf.gerar(dados, cor="#1B2A4A")
    assert conteudo[:5] == b"%PDF-"
    assert any("reserva" in r.message for r in caplog.records)


def test_reserva_nao_corta_numero(db, cenario):
    """`_couber` corta a célula na largura real e termina em "...".

    Um rótulo cortado é feio; um NÚMERO cortado é outra coisa: "98.765" vira
    "98.7..." e se lê como noventa e oito mil e setecentos. Por isso cada
    plataforma tem a sua coluna na reserva — e isto aqui guarda a decisão.
    """
    dados = _dados(db, cenario["escola"].id, plataformas=("elefante", "matific"))
    # pior caso REAL: nome comprido da rede + números de 6 dígitos. O nome é o
    # que mais rouba largura das colunas de número ao lado.
    for linha in dados.get("por_turma") or []:
        linha["turma"] = "5º Ano A - Integral Manhã"
        linha["elefante"] = {"livros_novos": 7777, "tempo_min": 99999,
                             "livros_com_atividade": 8888, "livros_relidos": 4567}
        linha["matific"] = {"atividades": 554321, "estrelas": 999999}
    for linha in dados.get("por_aluno") or []:
        linha["nome"] = "KAMILLY EMANUELLY ARAÚJO DA SILVA NASCIMENTO"
        linha["turma"] = "5º Ano A - Integral Manhã"
        linha["elefante"] = {"livros_novos": 1118, "tempo_min": 12345,
                             "livros_com_atividade": 1400, "livros_relidos": 9222}
        linha["matific"] = {"atividades": 112345, "estrelas": 998765}
    texto = _texto(pdf._reserva(dados, "#1B2A4A"))
    for linha in (dados.get("por_turma") or []) + (dados.get("por_aluno") or []):
        ele = linha.get("elefante") or {}
        mat = linha.get("matific") or {}
        for valor in (pdf._num(ele.get("livros_novos", 0)),
                      pdf._num(ele.get("livros_relidos", 0)),
                      pdf._num(mat.get("atividades", 0)),
                      pdf._num(mat.get("estrelas", 0))):
            assert valor in texto, f"o número {valor!r} foi cortado na reserva"
    # guarda GERAL, que não depende de eu lembrar de cada campo: nenhum trecho
    # que termine em "..." pode ter dígito logo antes — é assim que "98.765"
    # vira "98.7..." e uma data vira outra data.
    import re
    suspeitos = re.findall(r"\S*\d[\d.:/]*\.\.\.", texto)
    assert not suspeitos, f"valor numérico cortado na reserva: {suspeitos}"


def test_recorte_sem_coorte_ativa_nao_vira_inatividade(db, cenario, cliente,
                                                       sem_chromium):
    """Criança transferida: o motor filtra por `status == "ativo"`, a coorte
    fica vazia e o relatório sairia com zeros e SEM SUJEITO — lido como "ela não
    fez nada", quando o certo é "ela não está ativa neste ano"."""
    escola = cenario["escola"]
    alvo = cenario["alunos"][0]
    alvo.status = "transferido"
    db.commit()
    r = cliente.get(ROTA.format(eid=escola.id),
                    params={"periodo": "mes_anterior", "escopo": "aluno",
                            "aluno_id": alvo.id, "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert "inatividade" in texto, "o aviso essencial foi cortado"
    assert "ATENÇÃO" in texto
    # e o documento não fica sem sujeito: o PEDIDO nomeia a ficha
    assert str(alvo.id) in texto
    nome = r.headers["content-disposition"].split('filename="')[1].rstrip('"')
    assert str(alvo.id) in nome, "dois recortes vazios ficariam indistinguíveis"


def test_base_ausente_na_janela_efetiva_nao_e_sem_dado(db, cenario):
    """Base ausente significa "a conta partiu do zero", não "falta dado"."""
    dados = {"elefante": {"janela_efetiva_questoes": {
        "data_base_mais_antiga": None, "data_base_mais_recente": None,
        "data_atual_mais_antiga": "2026-10-04T21:10:00",
        "data_atual_mais_recente": "2026-10-04T21:10:00",
        "observacao": "entre COLETAS"}}}
    avisos = pdf._avisos_janela(dados)
    assert avisos and avisos[0][1] == "a primeira coleta"
    assert pdf.SEM_DADO not in avisos[0][1]


def test_questoes_sem_nenhuma_coleta_nao_viram_zero(db, cenario, sem_chromium):
    """Zero é uma afirmação: a criança foi medida e não produziu.

    Com NINGUÉM do recorte tendo coleta na janela, o "0" das questões não é
    medição — e a linha seguinte ("Sem coleta na janela: N") desmentiria as
    duas anteriores, sendo a única que o leitor pode não ler.
    """
    dados = _dados(db, cenario["escola"].id, plataformas=("elefante",))
    ele = dados["elefante"]
    assert ele["alunos_sem_retrato"] == dados["alunos"]["considerados"] > 0
    resumo = dict((r, v) for r, v, _f in pdf.linhas_resumo(dados))
    assert resumo["Questões tentadas"] == pdf.SEM_DADO
    assert resumo["Questões corretas"] == pdf.SEM_DADO
    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    assert "nenhuma coleta na janela" in texto

    # e COM coleta, o zero volta a ser um zero legítimo
    _snap(db, cenario["escola"].id, cenario["alunos"][0].id,
          datetime(2026, 9, 10, 12, 0), 0, 0)
    db.commit()
    com = dict((r, v) for r, v, _f in pdf.linhas_resumo(
        _dados(db, cenario["escola"].id, plataformas=("elefante",))))
    assert com["Questões tentadas"] == "0"


def test_gerador_aguenta_dicionario_incompleto():
    """Defensivo de propósito: um PDF que explode no meio da cerimônia é pior
    que um PDF magro. Nenhuma chave é obrigatória para o arquivo sair."""
    conteudo = pdf._reserva({}, "#1B2A4A")
    assert conteudo[:5] == b"%PDF-"
    assert pdf.nome_arquivo({}).endswith(".pdf")
    assert "<script>" not in pdf.montar_html(
        {"escola": {"nome": "<script>alert(1)</script>"}})


def test_pdf_personalizado_sem_datas_e_recusado(db, cenario, cliente):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "personalizado"})
    assert r.status_code == 422
    assert "data inicial" in r.json()["detail"].lower()
    assert r.headers["content-type"].startswith("application/json"), (
        "o erro precisa ser JSON com `detail` — é o que o front sabe ler")


# ============================================================================
# 11 a 14 — permissões: o PDF não pode escapar da autorização do JSON
# ============================================================================
def test_pdf_nega_secretaria(db, cenario):
    from fastapi.testclient import TestClient

    from app.main import app
    escola = cenario["escola"]
    rede = Rede(nome="REDE TESTE")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=escola.id, rede_id=rede.id, nome="Secretaria",
                   email="sec.pdf@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    c = TestClient(app)
    tok = c.post("/api/v1/auth/login",
                 data={"username": "sec.pdf@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    r = c.get(ROTA.format(eid=escola.id))
    assert r.status_code == 403
    assert "Secretaria" in r.json()["detail"]


def test_pdf_respeita_o_contrato_de_modulo_da_rede(db, cenario, cliente):
    """Não se emite relatório de um produto que a rede não assinou.

    Sem esta trava, bastava pedir `?plataformas=matific` para receber o que
    `/ranking/matematica` nega com 403 — e com nome de criança no documento.
    """
    from app.models import ModuloRede, Rede
    escola = cenario["escola"]
    rede = Rede(nome="REDE SEM MATEMATICA")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()

    negado = cliente.get(ROTA.format(eid=escola.id), params={"plataformas": "matific"})
    assert negado.status_code == 403
    assert "não faz parte do plano" in negado.json()["detail"]
    # e o JSON, que é a mesma função de autorização
    assert cliente.get(ROTA_JSON.format(eid=escola.id),
                       params={"plataformas": "matific"}).status_code == 403
    # a plataforma contratada continua funcionando
    assert cliente.get(ROTA.format(eid=escola.id),
                       params={"plataformas": "elefante"}).status_code == 200
    # plataforma inexistente cai no 422 do motor, não num 500 aqui
    assert cliente.get(ROTA.format(eid=escola.id),
                       params={"plataformas": "khan"}).status_code == 422


def test_pdf_exige_autenticacao(db, cenario):
    """Sem token não há PDF. O arquivo carrega nome de criança."""
    from fastapi.testclient import TestClient

    from app.main import app
    r = TestClient(app).get(ROTA.format(eid=cenario["escola"].id))
    assert r.status_code in (401, 403)
    assert r.headers["content-type"].startswith("application/json")


def test_pdf_nao_vaza_escola_alheia(db, cenario, cliente):
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    r = cliente.get(ROTA.format(eid=outra.id))
    assert r.status_code in (403, 404)


def test_pdf_recusa_turma_de_outra_escola(db, cenario, cliente):
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    turma_alheia = Turma(escola_id=outra.id, nome="9º Ano Z", ano_escolar="9º Ano",
                         ano_letivo=2026)
    db.add(turma_alheia)
    db.commit()
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"escopo": "turma", "turma_id": turma_alheia.id})
    assert r.status_code in (403, 404)
    assert r.headers["content-type"].startswith("application/json")


def test_pdf_recusa_aluno_de_outra_escola(db, cenario, cliente):
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    alheio = Aluno(escola_id=outra.id, nome="Crianca de outra escola")
    db.add(alheio)
    db.commit()
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"escopo": "aluno", "aluno_id": alheio.id})
    assert r.status_code in (403, 404)


def test_pdf_do_professor_so_traz_as_turmas_dele(db, cenario, sem_chromium):
    """Escopo "escola" no PDF não fura o recorte do professor."""
    from fastapi.testclient import TestClient

    from app.main import app
    escola = cenario["escola"]
    minha = cenario["turma"]
    outra = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano",
                  ano_letivo=2026)
    db.add(outra)
    db.flush()
    prof = Professor(escola_id=escola.id, nome="Prof", email="prof.pdf@teste.local")
    db.add(prof)
    db.flush()
    minha.professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof.pdf@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    alheio = Aluno(escola_id=escola.id, nome="Crianca da outra turma")
    db.add(alheio)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=alheio.id, turma_id=outra.id,
                     ano_letivo=2026))
    _semear(db, escola.id, alheio.id, "Alheio", datetime(2026, 9, 9, 10, 0), 30)
    db.commit()

    c = TestClient(app)
    tok = c.post("/api/v1/auth/login",
                 data={"username": "prof.pdf@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    r = c.get(ROTA.format(eid=escola.id),
              params={"periodo": "mes_anterior", "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    texto = _texto(r.content)
    assert alheio.nome not in texto, "o PDF do professor vazou outra turma"
    assert cenario["alunos"][0].nome in texto


# ============================================================================
# 15 a 19 — o arquivo
# ============================================================================
def test_content_type_e_disposition(db, cenario, cliente, sem_chromium):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "mes_anterior"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    disp = r.headers["content-disposition"]
    assert disp.startswith("attachment; filename=")
    assert disp.endswith('.pdf"')
    # o cliente do front lê o nome por /filename="?([^";]+)"?/ — ASCII, sem
    # filename*=UTF-8'' e sem ponto-e-vírgula no meio do nome.
    nome = disp.split('filename="')[1].rstrip('"')
    assert nome.isascii() and ";" not in nome and "/" not in nome


def test_nome_do_arquivo_e_seguro_e_legivel(db, cenario, cliente, sem_chromium):
    escola, turma = cenario["escola"], cenario["turma"]
    r = cliente.get(ROTA.format(eid=escola.id),
                    params={"periodo": "personalizado", "inicio": "2026-09-01",
                            "fim": "2026-09-30", "escopo": "turma",
                            "turma_id": turma.id})
    nome = r.headers["content-disposition"].split('filename="')[1].rstrip('"')
    assert nome.startswith("constela-relatorio-turma-")
    assert nome.endswith("-2026-09-01_2026-09-30.pdf")


@pytest.mark.parametrize("perigoso", [
    "../../etc/passwd", "..\\..\\windows\\system32", "a/b/c", 'aspas"e;ponto',
    "nome com espaço e acentuação", "", "   ", "." * 80,
])
def test_slug_nunca_produz_caminho(perigoso):
    s = pdf._slug(perigoso)
    assert "/" not in s and "\\" not in s and ".." not in s
    assert '"' not in s and ";" not in s and " " not in s
    assert s == s.strip("-")
    assert s.isascii() and len(s) <= 40


def test_pdf_nao_e_vazio_e_e_estruturalmente_valido(db, cenario, cliente, sem_chromium):
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "mes_anterior"})
    assert r.content[:5] == b"%PDF-"
    assert b"%%EOF" in r.content[-2048:]
    assert len(r.content) > 1000
    import io
    with pdfplumber.open(io.BytesIO(r.content)) as doc:
        assert len(doc.pages) >= 1


def test_auditoria_registra_a_emissao_do_pdf(db, cenario, cliente, sem_chromium):
    """O PDF não é persistido; o log guarda o PEDIDO, e com ação própria — para
    'quem levou a lista impressa' ser uma pergunta respondível."""
    antes = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "relatorio.periodo_pdf")).scalars().all()
    r = cliente.get(ROTA.format(eid=cenario["escola"].id),
                    params={"periodo": "bimestre_3", "plataformas": "elefante"})
    assert r.status_code == 200
    depois = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "relatorio.periodo_pdf")).scalars().all()
    assert len(depois) == len(antes) + 1
    assert depois[-1].detalhes["periodo"] == "bimestre_3"
    assert "nome" not in str(depois[-1].detalhes).lower()


# ============================================================================
# O renderizador REAL (pulado quando não há Chromium — como na CI)
# ============================================================================
def _tem_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                nav = p.chromium.launch()
            except Exception:  # noqa: BLE001
                nav = p.chromium.launch(channel="chrome")
            nav.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _tem_chromium(), reason="sem Chromium (igual ao job da CI)")
def test_pdf_de_vitrine_tem_os_mesmos_numeros_da_reserva(db, cenario):
    """O caminho bonito e o caminho simples não podem discordar."""
    dados = _dados(db, cenario["escola"].id, plataformas=("elefante", "matific"))
    vitrine = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    reserva = _texto(pdf._reserva(dados, "#1B2A4A"))
    for rotulo, valor, _f in pdf.linhas_resumo(dados):
        assert rotulo in vitrine and rotulo in reserva
        assert valor in vitrine and valor in reserva


@pytest.mark.skipif(not _tem_chromium(), reason="sem Chromium (igual ao job da CI)")
def test_pdf_de_vitrine_traz_a_moldura_da_casa(db, cenario):
    dados = _dados(db, cenario["escola"].id)
    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))
    assert "Relatório por Período" in texto
    assert "IDENTIFICAÇÃO" in texto
    assert "COMO LER ESTES NÚMEROS" in texto
    assert "O QUE ESTE RELATÓRIO NÃO RESPONDE" in texto
    assert "CONSTELA EDU" in texto.upper()


def test_reserva_entra_sozinha_quando_o_navegador_falha(db, cenario, sem_chromium):
    """Sem Chromium o relatório sai mesmo assim — e sai com os números."""
    dados = _dados(db, cenario["escola"].id)
    conteudo = pdf.gerar(dados, cor="#1B2A4A")
    assert conteudo[:5] == b"%PDF-"
    texto = _texto(conteudo)
    assert str(dados["elefante"]["livros_novos"]) in texto
    assert "POR ESTUDANTE" in texto


def test_o_pdf_e_o_json_vem_do_mesmo_resultado(db, cenario, cliente, sem_chromium):
    """Mesmo filtro, duas rotas: os números têm de bater."""
    eid = cenario["escola"].id
    params = {"periodo": "mes_anterior", "plataformas": "elefante"}
    json_resp = cliente.get(ROTA_JSON.format(eid=eid), params=params)
    pdf_resp = cliente.get(ROTA.format(eid=eid), params=params)
    assert json_resp.status_code == 200 and pdf_resp.status_code == 200
    corpo = json_resp.json()
    texto = _texto(pdf_resp.content)
    ele = corpo["elefante"]
    for chave in ("livros_novos", "livros_com_atividade", "livros_relidos"):
        assert str(ele[chave]) in texto, f"{chave} não apareceu no PDF"
    assert corpo["periodo"]["rotulo"] in texto
    assert str(corpo["alunos"]["considerados"]) in texto
