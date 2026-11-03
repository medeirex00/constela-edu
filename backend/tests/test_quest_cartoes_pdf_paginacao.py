"""Quest — a folha "SÓ DO PROFESSOR" dos cartões quebra página.

``gerar_cartoes_pdf`` desliga a quebra automática e ``_pagina_professor``
desenhava a tabela nome → código numa página A4 só. Com mais de ~33 alunos o
roteiro da 1ª aula caía abaixo da folha; com 41 ou mais, as linhas dos últimos
alunos (nome e CÓDIGO) eram desenhadas abaixo de 297 mm: estavam no arquivo, mas
não apareciam na tela nem na impressão — e a folha é onde o professor consulta o
código da criança que esqueceu o cartão. Agora a tabela continua em outra página
(com a faixa "SO DO PROFESSOR" e o cabeçalho da tabela de novo) e o roteiro vai
inteiro para a página seguinte quando não cabe.

O PDF é lido de volta (pdfplumber, das dependências do backend): número de
páginas, cada caractere dentro da folha e cada código uma vez na parte do
professor. Regressão do achado 3 do módulo quest na revisão e97 (prova
test_prova_3, invertida aqui). Dados fictícios.
"""
import io
import math

import pdfplumber
import pytest
from sqlalchemy import select

from app.models import Aluno, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from app.quest.services import cartoes_pdf
from app.quest.services import credenciais as svc

POR_PAGINA = 8   # cartões por página (grade 2×4)


def _cartoes(n: int) -> list[dict]:
    return [{"nome": f"Aluno Ficticio {i:02d}", "apelido": "Estrela Valente",
             "codigo": f"ZETA{i:03d}",
             "qr_url": f"https://quest.exemplo.test/entrar?qr=ficticio{i}"}
            for i in range(1, n + 1)]


def _paginas(pdf: bytes) -> list[dict]:
    """Por página: texto e palavras VISÍVEIS (inteiramente dentro da folha) e os
    caracteres FORA dela, com folga de 0,5 pt para arredondamento. O texto
    desenhado abaixo da folha continua no arquivo — e o extrator o leria sem o
    recorte."""
    saida = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for pagina in doc.pages:
            largura, altura = float(pagina.width), float(pagina.height)
            fora = [c["text"] for c in pagina.chars
                    if c["top"] < -0.5 or c["bottom"] > altura + 0.5
                    or c["x0"] < -0.5 or c["x1"] > largura + 0.5]
            visivel = pagina.within_bbox(pagina.bbox)
            saida.append({
                "texto": visivel.extract_text() or "",
                "palavras": [p["text"] for p in visivel.extract_words()],
                "fora": fora,
            })
    return saida


def _parte_do_professor(paginas: list[dict], n: int) -> list[dict]:
    return paginas[math.ceil(n / POR_PAGINA):]


# n alunos -> páginas: cartões (8 por página) + folha do professor (39 linhas por
# página; o roteiro de 38,5 mm precisa caber inteiro acima da margem de 10 mm).
@pytest.mark.parametrize("n, paginas_total, paginas_professor", [
    (3, 2, 1),
    (33, 6, 1),     # 33 linhas + roteiro ainda cabem numa folha
    (34, 7, 2),     # o roteiro passa para a 2ª folha (antes: saía da página)
    (40, 7, 2),     # 40ª linha na 2ª folha
    (41, 8, 2),     # antes: o 41º aluno ficava abaixo de 297 mm
    (45, 8, 2),
    (80, 13, 3),
])
def test_folha_do_professor_pagina_e_nada_sai_da_folha(n, paginas_total,
                                                       paginas_professor):
    cartoes = _cartoes(n)
    paginas = _paginas(cartoes_pdf.gerar_cartoes_pdf(
        "ESCOLA TESTE", "#7C6FF0", "5º Ano Z", cartoes))
    assert len(paginas) == paginas_total

    # Nenhum caractere fora da folha, em página nenhuma (cartões e professor).
    assert [(i + 1, p["fora"]) for i, p in enumerate(paginas) if p["fora"]] == []

    professor = _parte_do_professor(paginas, n)
    assert len(professor) == paginas_professor
    # Toda página da parte do professor leva o aviso (as folhas se separam).
    # Página com linhas da tabela repete o cabeçalho Aluno | Código.
    for pagina in professor:
        assert "SO DO PROFESSOR" in pagina["texto"]
        if any(w.startswith("ZETA") for w in pagina["palavras"]):
            assert "Aluno" in pagina["palavras"] and "Código" in pagina["palavras"]

    # Cada código e cada nome uma vez na parte do professor — nenhum perdido.
    palavras = [w for p in professor for w in p["palavras"]]
    texto = "\n".join(p["texto"] for p in professor)
    for cartao in cartoes:
        assert palavras.count(cartao["codigo"]) == 1, cartao["codigo"]
        assert texto.count(cartao["nome"]) == 1, cartao["nome"]

    # O roteiro da 1ª aula sai inteiro (título e os 3 passos), uma vez, na
    # última folha.
    assert texto.count("Primeira aula em 3 passos") == 1
    ultima = professor[-1]["texto"].splitlines()
    assert "Primeira aula em 3 passos" in ultima
    for passo in ("1. ", "2. ", "3. "):
        assert sum(linha.startswith(passo) for linha in ultima) == 1, passo


def test_cartoes_seguem_oito_por_pagina_na_ordem():
    n = 45
    cartoes = _cartoes(n)
    paginas = _paginas(cartoes_pdf.gerar_cartoes_pdf(
        "ESCOLA TESTE", "#7C6FF0", "5º Ano Z", cartoes))
    for indice in range(math.ceil(n / POR_PAGINA)):
        esperados = {c["codigo"] for c in cartoes[indice * 8:(indice + 1) * 8]}
        achados = {w for w in paginas[indice]["palavras"] if w.startswith("ZETA")}
        assert achados == esperados


def test_rota_da_turma_de_45_gera_a_folha_inteira(cliente, db, escola_completa):
    """Pela rota real (POST .../turmas/{id}/cartoes), turma fictícia de 45."""
    escola = escola_completa["escola"]
    turma = Turma(escola_id=escola.id, nome="5º Ano Z", ano_escolar="5º Ano",
                  ano_letivo=2026)
    db.add(turma)
    db.flush()
    ids = []
    for i in range(1, 46):
        aluno = Aluno(escola_id=escola.id, nome=f"Aluno Ficticio {i:02d}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
        ids.append(aluno.id)
    db.commit()

    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    paginas = _paginas(r.content)
    assert len(paginas) == 8                      # antes: 7, com 16 células fora
    assert [p["fora"] for p in paginas if p["fora"]] == []

    db.expire_all()
    codigos = [svc.formatar_codigo_exibicao(svc.codigo_para_exibicao(c))
               for c in db.execute(select(QuestCredencialAluno)
                                   .where(QuestCredencialAluno.aluno_id.in_(ids))
                                   ).scalars()]
    assert len(codigos) == 45
    professor = _parte_do_professor(paginas, 45)
    palavras = [w for p in professor for w in p["palavras"]]
    texto = "\n".join(p["texto"] for p in professor)
    for codigo in codigos:
        assert palavras.count(codigo) == 1, codigo
    for i in range(1, 46):
        assert f"Aluno Ficticio {i:02d}" in texto
    assert "Primeira aula em 3 passos" in professor[-1]["texto"]
