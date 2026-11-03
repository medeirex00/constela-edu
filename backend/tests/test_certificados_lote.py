"""Certificados EM LOTE: o MESMO certificado da rota individual, para até 50 alunos.

O que este arquivo trava:
* as guardas são as da rota individual, aluno a aluno (módulo para o pedido inteiro;
  aluno da escola, professor só os seus, ativo, 1º–5º ano, Lista Piloto e — só no
  Geral — mérito), com os MESMOS motivos;
* a ordem pedida é a ordem do PDF, e o recusado NÃO é substituído pelo próximo;
* 404 (não encontrado/não permitido) não devolve nome nem turma;
* auditoria ``certificado.emitido`` por aluno emitido, nenhuma na prévia;
* teto de 50, ids repetidos recusados, nenhum apto = 422 com os itens;
* o fallback da arte (cai no Geral com as guardas de mérito) vale por aluno.

Sem Chromium: o renderizador é trocado (como em ``test_certificado_populacao``) por
um PDF de uma página com o nome do aluno — o que permite ler a ORDEM no PDF final.
Nomes fictícios.
"""
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF
from pypdf import PdfReader
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Escola, LogAuditoria, Matricula, ModuloRede, Nota,
                        Professor, Rede, Turma, Usuario)
from app.services import certificados_lote as svc_lote

API = "/api/v1"


def _pdf(texto: str) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_font("helvetica", "", 16)
    pdf.cell(0, 10, texto)
    return bytes(pdf.output())


@pytest.fixture()
def renderizador(monkeypatch):
    """Troca as duas funções que geram o PDF de UM certificado. Guarda as chamadas e
    deixa a arte falhar para os nomes em ``falhar``."""
    from app.services import relatorios as svc

    estado = {"arte": [], "geral": [], "falhar": set()}

    def _arte(escola_nome, aluno_nome, modelo, *, bimestre=None):
        estado["arte"].append((aluno_nome, modelo, bimestre))
        if aluno_nome in estado["falhar"]:
            raise RuntimeError("sem Chromium (simulado)")
        return _pdf(f"ARTE {modelo} {aluno_nome}")

    def _geral(**kw):
        estado["geral"].append(kw["aluno_nome"])
        return _pdf(f"GERAL {kw['aluno_nome']}")

    monkeypatch.setattr(svc, "gerar_certificado_plataforma", _arte)
    monkeypatch.setattr(svc, "gerar_certificado", _geral)
    return estado


def _turma(db, escola, nome="3º Ano A", serie="3º Ano"):
    turma = db.query(Turma).filter(Turma.escola_id == escola.id,
                                   Turma.nome == nome).first()
    if turma is None:
        turma = Turma(escola_id=escola.id, nome=nome, ano_escolar=serie,
                      ano_letivo=escola.ano_letivo_ativo)
        db.add(turma)
        db.flush()
    return turma


def _aluno(db, escola, nome, *, turma=None, status="ativo", piloto=True, nota=True):
    turma = turma or _turma(db, escola)
    aluno = Aluno(escola_id=escola.id, nome=nome, status=status, da_lista_piloto=piloto)
    aluno.data_nascimento = date(2017, 5, 5)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    if nota:
        db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=turma.ano_letivo,
                    nota_geral=72.5, nota_elefante=72.5, nota_matific=72.5,
                    aferido_leitura=True, aferido_matematica=True, posicao=1))
    db.commit()
    return aluno


def _textos(conteudo: bytes) -> list[str]:
    return [p.extract_text().strip() for p in PdfReader(io.BytesIO(conteudo)).pages]


def _emitidos(db) -> list[int]:
    return sorted(db.execute(select(LogAuditoria.entidade_id).where(
        LogAuditoria.acao == "certificado.emitido")).scalars())


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _previa(cliente, escola_id, ids, modelo=None):
    return cliente.post(f"{API}/escolas/{escola_id}/certificados/lote/previa",
                        json={"modelo": modelo, "aluno_ids": ids})


def _lote(cliente, escola_id, ids, modelo=None, bimestre=None):
    return cliente.post(f"{API}/escolas/{escola_id}/certificados/lote",
                        json={"modelo": modelo, "bimestre": bimestre, "aluno_ids": ids})


# ============================================================================
# Prévia
# ============================================================================
def test_previa_diz_quem_esta_apto_na_ordem_pedida(cliente, db, escola_completa,
                                                   renderizador):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "ALUNA FICTICIA UM")
    saiu = _aluno(db, escola, "ALUNO FICTICIO QUE SAIU", status="transferido")
    b = _aluno(db, escola, "ALUNA FICTICIA DOIS")
    stub = _aluno(db, escola, "FICHA FICTICIA SEM PILOTO", piloto=False)

    r = _previa(cliente, escola.id, [b.id, saiu.id, a.id, stub.id], "elefante")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["modelo"] == "elefante"
    assert [i["aluno_id"] for i in corpo["itens"]] == [b.id, saiu.id, a.id, stub.id]
    assert [i["apto"] for i in corpo["itens"]] == [True, False, True, False]
    apto = corpo["itens"][0]
    assert apto == {"aluno_id": b.id, "nome": "ALUNA FICTICIA DOIS",
                    "turma": "3º Ano A", "apto": True, "motivo": None}
    # O motivo é o MESMO texto da rota individual.
    individual = cliente.get(f"{API}/escolas/{escola.id}/certificados/{saiu.id}"
                             "?modelo=elefante")
    assert individual.status_code == 409
    assert corpo["itens"][1]["motivo"] == individual.json()["detail"]
    assert corpo["itens"][1]["nome"] == "ALUNO FICTICIO QUE SAIU"
    assert corpo["itens"][1]["turma"] == "3º Ano A"
    assert "Lista Piloto" in corpo["itens"][3]["motivo"]
    # A prévia não gera PDF nem grava auditoria.
    assert renderizador["arte"] == [] and renderizador["geral"] == []
    assert _emitidos(db) == []


def test_previa_do_geral_roda_a_guarda_de_merito(cliente, db, escola_completa,
                                                 renderizador):
    """No Geral (mérito) o aluno sem nota calculada é recusado — com o 422 da rota
    individual; na arte da plataforma (participação), o mesmo aluno está apto."""
    escola = escola_completa["escola"]
    sem_nota = _aluno(db, escola, "ALUNO FICTICIO SEM NOTA", nota=False)
    com_nota = _aluno(db, escola, "ALUNA FICTICIA COM NOTA")

    geral = _previa(cliente, escola.id, [sem_nota.id, com_nota.id]).json()["itens"]
    assert [i["apto"] for i in geral] == [False, True]
    individual = cliente.get(f"{API}/escolas/{escola.id}/certificados/{sem_nota.id}")
    assert individual.status_code == 422
    assert geral[0]["motivo"] == individual.json()["detail"]

    arte = _previa(cliente, escola.id, [sem_nota.id, com_nota.id], "matific").json()
    assert [i["apto"] for i in arte["itens"]] == [True, True]


def test_previa_recusa_fase_e_turma_fora_da_premiacao(cliente, db, escola_completa,
                                                      renderizador):
    escola = escola_completa["escola"]
    infantil = _turma(db, escola, nome="Infantil Fictício", serie="Educação Infantil")
    fase = _aluno(db, escola, "CRIANCA FICTICIA DA FASE", turma=infantil)
    item = _previa(cliente, escola.id, [fase.id], "elefante").json()["itens"][0]
    assert item["apto"] is False
    assert "não participa das premiações" in item["motivo"]
    assert item["turma"] == "Infantil Fictício"


def test_404_nao_vaza_nome_nem_turma(cliente, db, escola_completa, renderizador):
    """Aluno de OUTRA escola e id inexistente: recusa com nome e turma nulos."""
    escola = escola_completa["escola"]
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    alheio = _aluno(db, outra, "CRIANCA FICTICIA DE OUTRA ESCOLA",
                    turma=_turma(db, outra, nome="9º Ano Z", serie="9º Ano"))
    meu = _aluno(db, escola, "ALUNA FICTICIA DA CASA")

    r = _previa(cliente, escola.id, [alheio.id, 999_999, meu.id], "elefante")
    assert r.status_code == 200, r.text
    itens = r.json()["itens"]
    for item in itens[:2]:
        assert item == {"aluno_id": item["aluno_id"], "nome": None, "turma": None,
                        "apto": False, "motivo": "Aluno não encontrado."}
    assert "OUTRA ESCOLA" not in r.text and "9º Ano Z" not in r.text
    assert "CRIANCA FICTICIA DE OUTRA ESCOLA" not in r.text
    assert itens[2]["apto"] is True

    lote = _lote(cliente, escola.id, [alheio.id, meu.id], "elefante")
    assert lote.status_code == 200
    assert _textos(lote.content) == ["ARTE elefante ALUNA FICTICIA DA CASA"]
    assert _emitidos(db) == [meu.id]


# ============================================================================
# Lote
# ============================================================================
def test_lote_um_pdf_na_ordem_pedida_sem_substituir_o_recusado(cliente, db,
                                                               escola_completa,
                                                               renderizador):
    escola = escola_completa["escola"]
    primeiro = _aluno(db, escola, "PRIMEIRA FICTICIA")
    recusado = _aluno(db, escola, "SEGUNDO FICTICIO ARQUIVADO", status="arquivado")
    terceiro = _aluno(db, escola, "TERCEIRA FICTICIA")
    quarto_fora_do_pedido = _aluno(db, escola, "QUARTO FICTICIO FORA DO PEDIDO")

    r = _lote(cliente, escola.id, [terceiro.id, recusado.id, primeiro.id],
              "elefante", bimestre=3)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == (
        'attachment; filename="certificados_elefante_2.pdf"')
    assert _textos(r.content) == ["ARTE elefante TERCEIRA FICTICIA",
                                  "ARTE elefante PRIMEIRA FICTICIA"]
    # O bimestre chega a cada certificado; o recusado não é renderizado e o próximo
    # da lista (que não foi pedido) não entra no lugar dele.
    assert renderizador["arte"] == [("TERCEIRA FICTICIA", "elefante", 3),
                                    ("PRIMEIRA FICTICIA", "elefante", 3)]
    assert quarto_fora_do_pedido.nome not in str(renderizador)
    # Auditoria por aluno emitido, como a rota individual (+ a marca do lote).
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "certificado.emitido")).scalars().all()
    assert sorted(log.entidade_id for log in logs) == sorted([terceiro.id, primeiro.id])
    for log in logs:
        assert log.entidade == "aluno" and log.escola_id == escola.id
        assert log.detalhes == {"modelo": "elefante", "lote": True}


def test_lote_geral_usa_o_certificado_geral_e_a_guarda_de_merito(cliente, db,
                                                                 escola_completa,
                                                                 renderizador):
    escola = escola_completa["escola"]
    com_nota = _aluno(db, escola, "ALUNA FICTICIA MERITO")
    sem_nota = _aluno(db, escola, "ALUNO FICTICIO SEM MERITO", nota=False)

    r = _lote(cliente, escola.id, [sem_nota.id, com_nota.id])
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].endswith('"certificados_geral_1.pdf"')
    assert _textos(r.content) == ["GERAL ALUNA FICTICIA MERITO"]
    assert renderizador["arte"] == []
    assert _emitidos(db) == [com_nota.id]
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "certificado.emitido")).scalar_one()
    assert log.detalhes == {"modelo": "geral", "lote": True}


def test_fallback_da_arte_cai_no_geral_por_aluno(cliente, db, escola_completa,
                                                 renderizador):
    """Arte que falha cai no Geral COM as guardas de mérito, só para aquele aluno."""
    escola = escola_completa["escola"]
    ok = _aluno(db, escola, "ARTE FICTICIA OK")
    cai_com_merito = _aluno(db, escola, "ARTE FICTICIA FALHA COM NOTA")
    cai_sem_merito = _aluno(db, escola, "ARTE FICTICIA FALHA SEM NOTA", nota=False)
    renderizador["falhar"] |= {cai_com_merito.nome, cai_sem_merito.nome}

    r = _lote(cliente, escola.id, [cai_sem_merito.id, ok.id, cai_com_merito.id],
              "matific")
    assert r.status_code == 200, r.text
    assert _textos(r.content) == ["ARTE matific ARTE FICTICIA OK",
                                  "GERAL ARTE FICTICIA FALHA COM NOTA"]
    assert _emitidos(db) == sorted([ok.id, cai_com_merito.id])


def test_nenhum_apto_devolve_422_com_os_itens(cliente, db, escola_completa,
                                              renderizador):
    escola = escola_completa["escola"]
    saiu = _aluno(db, escola, "FICTICIO QUE SAIU", status="transferido")
    stub = _aluno(db, escola, "FICTICIO SEM PILOTO", piloto=False)

    r = _lote(cliente, escola.id, [saiu.id, stub.id, 999_999], "elefante")
    assert r.status_code == 422, r.text
    corpo = r.json()
    assert corpo["detail"] == "Nenhum aluno apto para o certificado."
    previa = _previa(cliente, escola.id, [saiu.id, stub.id, 999_999], "elefante").json()
    assert corpo["itens"] == previa["itens"], "o mesmo formato (e conteúdo) da prévia"
    assert [i["apto"] for i in corpo["itens"]] == [False, False, False]
    assert _emitidos(db) == []
    assert renderizador["arte"] == []


def test_teto_de_50_e_ids_repetidos(cliente, db, escola_completa, renderizador):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "FICTICIA DO TETO")
    ids_51 = [a.id] + list(range(900_000, 900_050))
    assert len(ids_51) == 51
    for rota in (_previa, _lote):
        assert rota(cliente, escola.id, ids_51).status_code == 422
        assert rota(cliente, escola.id, []).status_code == 422
        repetido = rota(cliente, escola.id, [a.id, a.id])
        assert repetido.status_code == 422
        assert "repetidos" in repetido.text
        assert rota(cliente, escola.id, [0]).status_code == 422
    # 50 cabe: um apto e 49 ids que não existem.
    ids_50 = [a.id] + list(range(900_000, 900_049))
    r = _lote(cliente, escola.id, ids_50, "elefante")
    assert r.status_code == 200, r.text
    assert len(_textos(r.content)) == 1
    previa = _previa(cliente, escola.id, ids_50, "elefante").json()["itens"]
    assert len(previa) == 50 and [i["aluno_id"] for i in previa] == ids_50
    assert renderizador["arte"] == [("FICTICIA DO TETO", "elefante", None)]


def test_bimestre_fora_da_faixa_e_modelo_desconhecido(cliente, db, escola_completa,
                                                      renderizador):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "FICTICIA DA FAIXA")
    for bimestre in (0, 5):
        assert _lote(cliente, escola.id, [a.id], "elefante",
                     bimestre).status_code == 422
    assert _previa(cliente, escola.id, [a.id], "khan").status_code == 422


# ============================================================================
# Permissões
# ============================================================================
def test_modulo_fora_do_plano_barra_o_pedido_inteiro(cliente, db, escola_completa,
                                                     renderizador):
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE FICTICIA SEM MATEMATICA")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    a = _aluno(db, escola, "FICTICIA DO PLANO")

    for rota in (_previa, _lote):
        r = rota(cliente, escola.id, [a.id], "matific")
        assert r.status_code == 403, r.text
        assert "não faz parte do plano" in r.json()["detail"]
    # A arte da Leitura e o Geral seguem disponíveis.
    assert _lote(cliente, escola.id, [a.id], "elefante").status_code == 200
    assert _lote(cliente, escola.id, [a.id]).status_code == 200


def test_professor_so_emite_para_os_alunos_dele(db, escola_completa, renderizador):
    escola = escola_completa["escola"]
    minha = _turma(db, escola)
    outra = _turma(db, escola, nome="4º Ano B", serie="4º Ano")
    prof = Professor(escola_id=escola.id, nome="Prof Ficticio",
                     email="prof.lote@teste.local")
    db.add(prof)
    db.flush()
    minha.professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Prof Ficticio",
                   email="prof.lote@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="professor"))
    db.commit()
    meu = _aluno(db, escola, "ALUNA FICTICIA DO PROFESSOR", turma=minha)
    alheio = _aluno(db, escola, "ALUNO FICTICIO DE OUTRA TURMA", turma=outra)

    c = _login("prof.lote@teste.local")
    previa = c.post(f"{API}/escolas/{escola.id}/certificados/lote/previa",
                    json={"modelo": "elefante", "aluno_ids": [alheio.id, meu.id]})
    assert previa.status_code == 200, previa.text
    itens = previa.json()["itens"]
    assert itens[0] == {"aluno_id": alheio.id, "nome": None, "turma": None,
                        "apto": False, "motivo": "Aluno não encontrado."}
    assert "ALUNO FICTICIO DE OUTRA TURMA" not in previa.text and "4º Ano B" not in previa.text
    assert itens[1]["apto"] is True

    lote = c.post(f"{API}/escolas/{escola.id}/certificados/lote",
                  json={"modelo": "elefante", "aluno_ids": [alheio.id, meu.id]})
    assert lote.status_code == 200, lote.text
    assert _textos(lote.content) == ["ARTE elefante ALUNA FICTICIA DO PROFESSOR"]
    assert _emitidos(db) == [meu.id]


def test_secretaria_e_outra_escola_sao_negadas(db, escola_completa, cliente,
                                               renderizador):
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "FICTICIA PROTEGIDA")
    rede = Rede(nome="REDE FICTICIA")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=escola.id, rede_id=rede.id, nome="Secretaria",
                   email="sec.lote@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()

    sec = _login("sec.lote@teste.local")
    for rota in (_previa, _lote):
        r = rota(sec, escola.id, [a.id], "elefante")
        assert r.status_code == 403, r.text
        assert "FICTICIA PROTEGIDA" not in r.text
        # o coordenador da escola não opera a escola vizinha
        assert rota(cliente, outra.id, [a.id], "elefante").status_code == 403
    assert _emitidos(db) == []
    assert renderizador["arte"] == []


def test_sem_login_e_401(db, escola_completa):
    r = TestClient(app).post(
        f"{API}/escolas/{escola_completa['escola'].id}/certificados/lote",
        json={"modelo": None, "aluno_ids": [1]})
    assert r.status_code == 401


# ============================================================================
# Junção do PDF
# ============================================================================
def _png_rgb() -> bytes:
    from PIL import Image

    imagem = Image.new("RGB", (400, 280))
    imagem.putdata([((x * 7) % 256, (y * 5) % 256, (x * y) % 256)
                    for y in range(280) for x in range(400)])
    saida = io.BytesIO()
    imagem.save(saida, format="PNG")
    return saida.getvalue()


def test_juntar_deduplica_a_arte_repetida_sem_mudar_as_paginas():
    """A arte de fundo repetida em cada certificado vira UM objeto no PDF final."""
    png = _png_rgb()

    def _com_arte(nome):
        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.add_page()
        pdf.image(io.BytesIO(png), x=0, y=0, w=297, h=210)
        pdf.set_font("helvetica", "", 16)
        pdf.cell(0, 10, nome)
        return bytes(pdf.output())

    documentos = [_com_arte(f"FICTICIO {i}") for i in range(5)]
    junto = svc_lote.juntar_pdfs(documentos)
    leitor = PdfReader(io.BytesIO(junto))
    assert [p.extract_text().strip() for p in leitor.pages] == [
        f"FICTICIO {i}" for i in range(5)]
    for pagina in leitor.pages:
        assert len(pagina.images) == 1 and pagina.images[0].image.size == (400, 280)
    um = len(documentos[0])
    assert len(junto) < 2 * um, (len(junto), um)
    assert sum(map(len, documentos)) > 4 * um


def test_juntar_sem_deduplicacao_ainda_entrega_o_pdf(monkeypatch):
    def _falha(_escritor):
        raise RuntimeError("simulado")

    monkeypatch.setattr(svc_lote, "_deduplicar_imagens", _falha)
    junto = svc_lote.juntar_pdfs([_pdf("UM FICTICIO"), _pdf("DOIS FICTICIO")])
    assert _textos(junto) == ["UM FICTICIO", "DOIS FICTICIO"]
    with pytest.raises(ValueError):
        svc_lote.juntar_pdfs([])


def test_lote_com_a_rota_individual_intacta(cliente, db, escola_completa,
                                            renderizador):
    """A rota individual continua emitindo e auditando sozinha (sem a marca do lote)."""
    escola = escola_completa["escola"]
    a = _aluno(db, escola, "FICTICIA INDIVIDUAL")
    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo=elefante")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        f'attachment; filename="certificado_elefante_{a.id}.pdf"')
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "certificado.emitido")).scalar_one()
    assert log.detalhes == {"modelo": "elefante"}
    assert db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "certificado.emitido")).scalar() == 1
