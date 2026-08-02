"""Import do relatório individual do Elefante: turma do PDF, auto-match e catálogo."""
from sqlalchemy import func, select

from app.models import Aluno, Leitura, Livro, Matricula, SnapshotElefante, Turma
from app.services import perfis_pdf


def _pdf_individual(nome="MARIA CLARA TESTE", turma="9 ANO Z TESTE") -> bytes:
    """Relatório individual sintético (posicional) com cabeçalho e 2 livros."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    t = pdf.text
    t(40, 40, "Relatório de Performance do Estudante")
    t(40, 60, "01/02/2026 - 06/07/2026")
    t(40, 80, nome)
    t(40, 95, f"{turma} - ESCOLA MODELO")
    t(40, 110, "Q")
    t(40, 128, "Professor")
    t(220, 128, "Escola")
    t(413, 128, "Turma")
    t(40, 142, "Fulano de Tal")
    t(220, 142, "ESCOLA MODELO")
    t(413, 142, turma)
    t(15.7, 175, "Leituras Concluídas")
    t(305.6, 175, "Tempo de Leitura")
    t(15.7, 190, "2")
    t(305.6, 190, "5:30:00")
    t(15.7, 230, "Histórico de Livros Lidos")
    t(330, 260, "Tempo")
    t(330, 272, "de")
    t(15.7, 284, "Titulo")
    t(47, 284, "do")
    t(62, 284, "Livro")
    t(180, 284, "Nível")
    t(230, 284, "Gênero")
    t(268, 284, "Textual")
    t(330, 284, "Leitura")
    t(400, 284, "Data/Hora")
    t(15.7, 310, "O Pequeno Livro Azul")
    t(180, 310, "K")
    t(230, 310, "Fantasia")
    t(330, 310, "0:06:04")
    t(400, 310, "01/07/2026")
    t(15.7, 336, "A Casa Amarela")
    t(180, 336, "D")
    t(230, 336, "Aventura")
    t(330, 336, "0:08:15")
    t(400, 336, "02/07/2026")
    return bytes(pdf.output())


def test_nome_do_arquivo_extrai_e_rejeita_lixo():
    from app.services.perfis_pdf import nome_do_arquivo
    assert nome_do_arquivo(
        "Relatório de performance do estudante - ISABELA LOHANA DE JESUS LAVINSKY.pdf"
    ) == "ISABELA LOHANA DE JESUS LAVINSKY"
    # variação (desempenho/aluno) e nome com hífen
    assert nome_do_arquivo(
        "relatorio de desempenho do aluno - ANA - MARIA SOUSA.pdf") == "ANA - MARIA SOUSA"
    # arquivos que NÃO seguem o padrão -> None (nunca vira nome)
    assert nome_do_arquivo("Imagem de tela.pdf") is None
    assert nome_do_arquivo("documento.pdf") is None
    assert nome_do_arquivo("") is None


def test_nome_do_arquivo_tem_prioridade_sobre_conteudo():
    """Mesmo com nome no conteúdo, o nome do ARQUIVO é a fonte primária."""
    pdf = _pdf_individual(nome="NOME NO CONTEUDO ERRADO")
    a = perfis_pdf.analisar_pdf(
        pdf, nome_arquivo="Relatório de performance do estudante - JOANA DA SILVA REAL.pdf")
    assert a.origem_nome == "arquivo"
    assert all(l.nome == "JOANA DA SILVA REAL" for l in a.linhas)
    assert "pelo nome do arquivo" in a.mensagem_deteccao


def test_legenda_de_imagem_nao_vira_nome():
    """'Imagem de...' no conteúdo nunca é aceito como nome do aluno."""
    from app.services.perfis_pdf import _parece_nome_pessoa
    assert not _parece_nome_pessoa("Imagem de perfil do aluno")
    assert not _parece_nome_pessoa("Logotipo Elefante Letrado")
    assert _parece_nome_pessoa("Veronica Oliveira Marcolino Goes")


def test_parser_individual_extrai_turma():
    analise = perfis_pdf.analisar_pdf(_pdf_individual())
    assert analise.estrategia == "perfil_elefante_estudante"
    assert analise.turma_detectada == "9 ANO Z TESTE"
    assert analise.escola_detectada == "ESCOLA MODELO"
    # cada linha de livro carrega a turma para casar/criar sem intervenção
    assert all(l.dados.get("turma_relatorio") == "9 ANO Z TESTE" for l in analise.linhas)
    assert analise.linhas[0].nome == "MARIA CLARA TESTE"


def test_nome_com_hifen_nao_vira_turma():
    """Nome composto com hífen não pode ser confundido com 'TURMA - ESCOLA'."""
    analise = perfis_pdf.analisar_pdf(_pdf_individual(nome="ANA - MARIA SOUSA"))
    assert analise.linhas[0].nome == "ANA - MARIA SOUSA"   # nome preservado
    assert analise.turma_detectada == "9 ANO Z TESTE"      # turma correta
    assert "leituras" not in analise.turma_detectada.lower()


def test_turma_com_hifen_nao_e_truncada():
    """rpartition mantém a turma inteira quando o nome dela contém ' - '."""
    analise = perfis_pdf.analisar_pdf(
        _pdf_individual(turma="9 ANO - MANHA"))
    assert analise.turma_detectada == "9 ANO - MANHA"
    assert analise.escola_detectada == "ESCOLA MODELO"


def test_individual_casa_aluno_do_relatorio_geral(cliente, db, escola_completa):
    """Fluxo real: geral cria o aluno; individual reconhece e importa sozinho."""
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]

    # 1) o "relatório geral" já cadastrou a aluna (simulado pelo cadastro direto)
    aluna = Aluno(escola_id=escola.id, nome="Maria Clara Teste")
    db.add(aluna)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluna.id,
                     turma_id=turma.id, ano_letivo=escola.ano_letivo_ativo))
    db.commit()

    # 2) análise do individual: reconhece a aluna existente (sem informar quem é)
    resp = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/analisar",
        files={"arquivo": ("individual.pdf", _pdf_individual(nome="MARIA CLARA TESTE"),
                           "application/pdf")})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["plataforma"] == "elefante" and corpo["formato"] == "leituras"
    assert corpo["turma_detectada"] == "9 ANO Z TESTE"
    # todas as linhas de livro apontam para a MESMA aluna, por correspondência
    correspondencias = {l["correspondencia"]["status"] for l in corpo["linhas"]}
    assert correspondencias == {"exato"}
    assert all(l["correspondencia"]["aluno_id"] == aluna.id for l in corpo["linhas"])

    # 3) confirmação importa o histórico e alimenta o catálogo
    linhas = [{"nome": l["nome"], "dados": l["dados"], "aluno_id": aluna.id}
              for l in corpo["linhas"]]
    conf = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "leituras", "tipo": "pdf",
              "linhas": linhas})
    assert conf.status_code == 200, conf.text

    # livros entraram no catálogo com nível e categoria
    livros = db.execute(select(Livro).where(Livro.escola_id == escola.id)).scalars().all()
    assert {l.titulo for l in livros} == {"O Pequeno Livro Azul", "A Casa Amarela"}
    assert {l.nivel_codigo for l in livros} == {"K", "D"}
    # 2 leituras para a aluna
    n_leituras = db.execute(
        select(func.count()).select_from(Leitura).where(Leitura.aluno_id == aluna.id)
    ).scalar_one()
    assert n_leituras == 2
    # NÃO duplicou a aluna
    assert db.execute(
        select(func.count()).select_from(Aluno).where(Aluno.escola_id == escola.id)
    ).scalar_one() == len(escola_completa["alunos"]) + 1


def test_import_individual_gera_eventos_e_e_idempotente(cliente, db, escola_completa):
    """O relatório individual alimenta a LINHA DO TEMPO: 1 EventoAluno por
    leitura do histórico (com data/hora, título, nível, gênero), e reimportar o
    MESMO relatório não duplica (idempotência por chave_natural)."""
    from datetime import datetime

    from app.models import EventoAluno

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    aluna = Aluno(escola_id=escola.id, nome="Maria Clara Teste")
    db.add(aluna)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluna.id,
                     turma_id=turma.id, ano_letivo=escola.ano_letivo_ativo))
    db.commit()

    def _confirmar():
        resp = cliente.post(
            f"/api/v1/escolas/{escola.id}/importacoes/analisar",
            files={"arquivo": ("individual.pdf",
                               _pdf_individual(nome="MARIA CLARA TESTE"),
                               "application/pdf")})
        assert resp.status_code == 200, resp.text
        linhas = [{"nome": l["nome"], "dados": l["dados"], "aluno_id": aluna.id}
                  for l in resp.json()["linhas"]]
        conf = cliente.post(
            f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
            json={"plataforma": "elefante", "formato": "leituras", "tipo": "pdf",
                  "linhas": linhas})
        assert conf.status_code == 200, conf.text

    _confirmar()
    eventos = db.execute(
        select(EventoAluno).where(EventoAluno.aluno_id == aluna.id,
                                  EventoAluno.plataforma == "elefante")
        .order_by(EventoAluno.ocorrido_em)).scalars().all()
    assert len(eventos) == 2
    assert all(e.tipo_evento == "leitura" for e in eventos)
    assert {e.conteudo_titulo for e in eventos} == {"O Pequeno Livro Azul",
                                                    "A Casa Amarela"}
    assert {e.nivel_codigo for e in eventos} == {"K", "D"}
    assert eventos[0].ocorrido_em == datetime(2026, 7, 1)
    assert eventos[1].ocorrido_em == datetime(2026, 7, 2)
    assert eventos[0].dados.get("genero")            # gênero preservado
    assert all(e.livro_id is not None for e in eventos)   # ligado ao catálogo

    # Reimportar o MESMO relatório: nenhum evento novo (idempotente).
    _confirmar()
    n = db.execute(
        select(func.count()).select_from(EventoAluno)
        .where(EventoAluno.aluno_id == aluna.id)).scalar_one()
    assert n == 2


def test_ingerir_eventos_dedup_por_chave(db, escola_completa):
    """O serviço de eventos ingere só os novos e é determinístico na chave."""
    from datetime import datetime

    from app.models import EventoAluno
    from app.services.eventos import chave_evento, ingerir_eventos

    escola = escola_completa["escola"]
    aluno = Aluno(escola_id=escola.id, nome="Zé Evento")
    db.add(aluno)
    db.flush()
    quando = datetime(2026, 5, 3, 9, 15)
    k = chave_evento("elefante", "leitura", aluno.id, "Livro X", quando)
    assert k == chave_evento("elefante", "leitura", aluno.id, "livro x  ", quando)  # normaliza
    ev = {"escola_id": escola.id, "aluno_id": aluno.id, "plataforma": "elefante",
          "tipo_evento": "leitura", "ocorrido_em": quando, "chave_natural": k,
          "conteudo_titulo": "Livro X", "dados": {}}
    assert ingerir_eventos(db, aluno.id, "elefante", [ev, dict(ev)]) == 1   # lote dedup
    db.flush()
    assert ingerir_eventos(db, aluno.id, "elefante", [ev]) == 0             # já existe
    assert db.execute(select(func.count()).select_from(EventoAluno)
                      .where(EventoAluno.aluno_id == aluno.id)).scalar_one() == 1


def test_individual_cria_aluno_uma_vez_na_turma_detectada(cliente, db, escola_completa):
    """Aluno inexistente + turma do PDF conhecida: cria UMA vez (não 1 por livro)."""
    escola = escola_completa["escola"]
    # turma com o nome que o PDF traz
    turma = Turma(escola_id=escola.id, nome="9 ANO Z TESTE", ano_escolar="9º Ano",
                  ano_letivo=escola.ano_letivo_ativo)
    db.add(turma)
    db.commit()

    resp = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/analisar",
        files={"arquivo": ("ind.pdf", _pdf_individual(nome="NOVO ALUNO SILVA",
                                                      turma="9 ANO Z TESTE"),
                           "application/pdf")}).json()
    # confirma criando na turma detectada (2 linhas de livro, mesmo aluno)
    linhas = [{"nome": l["nome"], "dados": l["dados"], "criar_em_turma_id": turma.id}
              for l in resp["linhas"]]
    conf = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "leituras", "tipo": "pdf",
              "linhas": linhas})
    assert conf.status_code == 200, conf.text

    novos = db.execute(
        select(Aluno).where(Aluno.escola_id == escola.id,
                            Aluno.nome == "NOVO ALUNO SILVA")
    ).scalars().all()
    assert len(novos) == 1                       # criado UMA vez, não por livro
    snap = db.execute(
        select(SnapshotElefante).where(SnapshotElefante.aluno_id == novos[0].id)
    ).scalars().first()
    assert snap is not None and snap.livros_unicos == 2


def test_homonimos_nao_casam_automaticamente(db, escola_completa):
    """Dois alunos com nome idêntico: a turma do relatório desempata; sem ela,
    o usuário decide (nunca pontua o aluno errado)."""
    from app.services import importacao as svc

    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]  # "3º Ano A"
    turma_b = Turma(escola_id=escola.id, nome="3º Ano B", ano_escolar="3º Ano",
                    ano_letivo=escola.ano_letivo_ativo)
    db.add(turma_b)
    db.flush()
    joao_a = Aluno(escola_id=escola.id, nome="João Silva")
    joao_b = Aluno(escola_id=escola.id, nome="João Silva")
    db.add_all([joao_a, joao_b])
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=joao_a.id, turma_id=turma_a.id,
                     ano_letivo=escola.ano_letivo_ativo))
    db.add(Matricula(escola_id=escola.id, aluno_id=joao_b.id, turma_id=turma_b.id,
                     ano_letivo=escola.ano_letivo_ativo))
    db.commit()

    com_turma = svc.LinhaImportacao(
        numero=1, nome="JOÃO SILVA", dados={"turma_relatorio": "3 ANO B"})
    sem_turma = svc.LinhaImportacao(numero=2, nome="JOÃO SILVA", dados={})
    svc.casar_nomes(db, escola.id, [com_turma, sem_turma])

    # com a turma do relatório: o motor único procura no roster da turma 3B, onde há
    # UM único João (o joao_b) → vincula (spec do dono: 1 candidato na MESMA turma =
    # alta confiança). O homônimo da 3A não é candidato NESTA turma.
    assert com_turma.correspondencia["status"] == "vinculado"
    assert com_turma.correspondencia["aluno_id"] == joao_b.id
    # sem turma: NÃO casa automaticamente — o usuário escolhe entre os homônimos
    assert sem_turma.correspondencia["status"] == "nao_encontrado"
    assert len(sem_turma.correspondencia["alternativas"]) == 2
    assert all("turma" in a for a in sem_turma.correspondencia["alternativas"])


def test_releitura_no_mesmo_relatorio_nao_derruba_import(cliente, db, escola_completa):
    """Livro repetido no mesmo relatório é contado uma vez, sem IntegrityError."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    conf = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "leituras", "tipo": "pdf",
              "linhas": [
                  {"nome": ana.nome, "aluno_id": ana.id,
                   "dados": {"livro": "O Mesmo Livro", "nivel": "D"}},
                  {"nome": ana.nome, "aluno_id": ana.id,
                   "dados": {"livro": "O Mesmo Livro", "nivel": "D"}},  # releitura
              ]})
    assert conf.status_code == 200, conf.text
    assert any("mais de uma vez" in a for a in conf.json()["avisos"])
    leituras = db.execute(
        select(func.count()).select_from(Leitura).where(Leitura.aluno_id == ana.id)
    ).scalar_one()
    assert leituras == 1   # contado UMA vez


def test_nivel_fora_das_faixas_gera_aviso(cliente, db, escola_completa):
    """Nível de letra não configurado avisa que não pontua por dificuldade."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    # "ZZ" não está em nenhuma faixa da fixture (Pré-Leitor AA/BB, Nível 2 D/E)
    conf = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "leituras", "tipo": "pdf",
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                          "dados": {"livro": "Livro Raro", "nivel": "ZZ"}}]})
    assert conf.status_code == 200, conf.text
    assert any("ZZ" in a and "faixa" in a for a in conf.json()["avisos"])
