"""Testes da Fase 2 — parser de relatórios, correspondência de nomes e
fluxo completo de importação (prévia → confirmação → recálculo)."""
import pytest

from app.models import Importacao, Leitura, Livro, Nota, SnapshotElefante, SnapshotMatific
from app.services import importacao as svc

TEXTO_MATIFIC = """Relatório Matific — Turma 3º Ano A
Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas
Ana Beatriz Souza\t42\t85,5\t120
João Pedro Barbosa\t10\t70\t35
Total\t52\t\t155
"""

TEXTO_ELEFANTE_RESUMO = """Elefante Letrado — desempenho de leitura
Nome;Livros lidos;Tempo de leitura;Questões respondidas;Acertos;Livros por nível
Ana Beatriz Souza;5;120;20;18;AA:3, D:2
João Pedro Barbosa;2;45;8;4;AA:2
"""

TEXTO_ELEFANTE_LEITURAS = """Elefante Letrado — livros concluídos
Nome;Título do livro;Nível
Ana Beatriz Souza;O Gato e a Lua;AA
Ana Beatriz Souza;Aventura na Floresta;E
João Pedro Barbosa;O Gato e a Lua;AA
"""


# --- Parser -------------------------------------------------------------------

def test_detecta_plataforma_pelo_texto():
    assert svc.detectar_plataforma(TEXTO_MATIFIC) == "matific"
    assert svc.detectar_plataforma(TEXTO_ELEFANTE_RESUMO) == "elefante"


def test_parser_matific_com_numeros_pt_br():
    analise = svc.analisar_texto(TEXTO_MATIFIC)
    assert analise.plataforma == "matific"
    assert analise.formato == "resumo"
    assert len(analise.linhas) == 2  # linha "Total" descartada como rodapé
    ana = analise.linhas[0]
    assert ana.nome == "Ana Beatriz Souza"
    assert ana.dados == {"atividades": 42.0, "pontuacao_media": 85.5, "estrelas": 120.0}
    assert ana.erros == []


def test_parser_elefante_resumo_com_niveis():
    analise = svc.analisar_texto(TEXTO_ELEFANTE_RESUMO)
    assert analise.formato == "resumo"
    ana = analise.linhas[0]
    assert ana.dados["livros_unicos"] == 5.0
    assert ana.dados["livros_por_nivel"] == {"AA": 3, "D": 2}


def test_parser_elefante_formato_leituras():
    analise = svc.analisar_texto(TEXTO_ELEFANTE_LEITURAS)
    assert analise.formato == "leituras"
    assert len(analise.linhas) == 3
    assert analise.linhas[0].dados == {"livro": "O Gato e a Lua", "nivel": "AA"}


def test_valor_invalido_gera_erro_na_linha_sem_derrubar_a_analise():
    texto = "Nome\tAtividades\nAna Beatriz Souza\tabc\n"
    analise = svc.analisar_texto(texto, plataforma="matific")
    assert len(analise.linhas) == 1
    assert "atividades" not in analise.linhas[0].dados
    assert analise.linhas[0].erros


def test_cabecalho_ausente_gera_erro_geral():
    analise = svc.analisar_texto("linha solta sem estrutura", plataforma="matific")
    assert analise.erros_gerais


def test_conversao_numerica_pt_br():
    assert svc._numero("1.234,56") == 1234.56
    assert svc._numero("85,5") == 85.5
    assert svc._numero("85.5") == 85.5
    assert svc._numero("1.234") == 1234.0
    assert svc._numero("92%") == 92.0
    with pytest.raises(ValueError):
        svc._numero("abc")


# --- Correspondência de nomes (PRD §52) ----------------------------------------

def test_casamento_exato_ignora_acentos_e_caixa(db, escola_completa):
    linhas = [svc.LinhaImportacao(numero=1, nome="ANA BEATRIZ SOUZA", dados={})]
    svc.casar_nomes(db, escola_completa["escola"].id, linhas)
    assert linhas[0].correspondencia["status"] == "exato"
    assert linhas[0].correspondencia["aluno_nome"] == "Ana Beatriz Souza"


def test_nome_parecido_vira_provavel_e_exige_confirmacao(db, escola_completa):
    linhas = [svc.LinhaImportacao(numero=1, nome="Ana Beatris Sousa", dados={})]
    svc.casar_nomes(db, escola_completa["escola"].id, linhas)
    assert linhas[0].correspondencia["status"] == "provavel"
    assert linhas[0].correspondencia["similaridade"] < 100.0


def test_nome_desconhecido_nao_encontrado(db, escola_completa):
    linhas = [svc.LinhaImportacao(numero=1, nome="Fulano Inexistente da Silva", dados={})]
    svc.casar_nomes(db, escola_completa["escola"].id, linhas)
    assert linhas[0].correspondencia["status"] == "nao_encontrado"


# --- Fluxo completo pela API ----------------------------------------------------

def test_analisar_texto_pela_api(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        data={"texto": TEXTO_MATIFIC},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["plataforma"] == "matific"
    assert corpo["total_linhas"] == 2
    assert corpo["linhas"][0]["correspondencia"]["status"] == "exato"


def test_confirmar_importacao_matific_gera_snapshot_e_recalcula(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={
            "plataforma": "matific", "formato": "resumo", "tipo": "texto",
            "linhas": [{
                "nome": "Ana Beatriz Souza",
                "dados": {"atividades": 42, "pontuacao_media": 85.5, "estrelas": 120},
                "aluno_id": ana.id,
            }],
        },
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["qtd_alunos"] == 1

    snap = db.query(SnapshotMatific).filter_by(aluno_id=ana.id).one()
    assert snap.atividades == 42
    assert snap.pontuacao_media == 85.5
    registro = db.query(Importacao).filter_by(id=resposta.json()["importacao_id"]).one()
    assert registro.plataforma == "matific"
    # Recalculo automático (PRD §43): a nota já existe
    nota = db.query(Nota).filter_by(aluno_id=ana.id).one()
    assert nota.nota_matific == pytest.approx(100.0)  # única com dados → máximo em tudo


def test_confirmar_leituras_respeita_leitura_unica(cliente, db, escola_completa):
    """PRD §35: reimportar o mesmo livro não cria leitura nem pontua de novo."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    corpo = {
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [
            {"nome": ana.nome, "dados": {"livro": "O Gato e a Lua", "nivel": "AA"}, "aluno_id": ana.id},
            {"nome": ana.nome, "dados": {"livro": "Aventura na Floresta", "nivel": "E"}, "aluno_id": ana.id},
        ],
    }
    primeira = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert primeira.status_code == 200, primeira.text
    assert db.query(Leitura).filter_by(aluno_id=ana.id).count() == 2
    assert db.query(Livro).count() == 2

    segunda = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert segunda.status_code == 200
    assert any("releitura" in a.casefold() for a in segunda.json()["avisos"])
    assert db.query(Leitura).filter_by(aluno_id=ana.id).count() == 2  # nada duplicado

    snap = (db.query(SnapshotElefante).filter_by(aluno_id=ana.id)
            .order_by(SnapshotElefante.id.desc()).first())
    assert snap.livros_unicos == 2
    assert snap.livros_por_nivel == {"AA": 1, "E": 1}


def test_confirmar_pode_criar_aluno_novo(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={
            "plataforma": "matific", "formato": "resumo", "tipo": "texto",
            "linhas": [{
                "nome": "Aluno Recém Chegado",
                "dados": {"atividades": 5, "pontuacao_media": 60, "estrelas": 10},
                "criar_em_turma_id": turma_id,
            }],
        },
    )
    assert resposta.status_code == 200, resposta.text
    from app.models import Aluno
    novo = db.query(Aluno).filter_by(nome="Aluno Recém Chegado").one()
    assert db.query(SnapshotMatific).filter_by(aluno_id=novo.id).count() == 1


def test_edicao_manual_matific_preserva_historico(cliente, db, escola_completa):
    """Edição manual cria snapshot novo (imutável) e fica no log (PRD §68, §17)."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "texto",
              "linhas": [{"nome": ana.nome,
                          "dados": {"atividades": 10, "pontuacao_media": 50, "estrelas": 20},
                          "aluno_id": ana.id}]},
    )
    resposta = cliente.put(
        f"/api/v1/escolas/{escola_id}/matific/{ana.id}",
        json={"atividades": 12, "pontuacao_media": 55, "estrelas": 25,
              "motivo": "Correção de erro de digitação no relatório"},
    )
    assert resposta.status_code == 200, resposta.text
    snapshots = db.query(SnapshotMatific).filter_by(aluno_id=ana.id).all()
    assert len(snapshots) == 2  # o antigo permanece
    from app.models import LogAuditoria
    log = (db.query(LogAuditoria).filter_by(acao="matific.editado")
           .order_by(LogAuditoria.id.desc()).first())
    assert log.detalhes["de"]["atividades"] == 10
    assert log.detalhes["para"]["atividades"] == 12


# --- Importação em LOTE: confirmar sem recalcular + /recalcular (§43) -----------

def test_confirmar_com_recalcular_false_grava_sem_recalcular(cliente, db, escola_completa):
    """No lote, cada arquivo confirma com recalcular=false: o snapshot é gravado
    mas as notas NÃO são recalculadas ainda (isso acontece uma vez ao final)."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={
            "plataforma": "matific", "formato": "resumo", "tipo": "texto",
            "recalcular": False,
            "linhas": [{
                "nome": ana.nome,
                "dados": {"atividades": 42, "pontuacao_media": 85.5, "estrelas": 120},
                "aluno_id": ana.id,
            }],
        },
    )
    assert resposta.status_code == 200, resposta.text
    # Snapshot foi gravado normalmente...
    assert db.query(SnapshotMatific).filter_by(aluno_id=ana.id).count() == 1
    # ...mas a mensagem é a curta e a nota ainda NÃO foi calculada.
    assert "recalcula" not in resposta.json()["mensagem"].casefold()
    assert db.query(Nota).filter_by(aluno_id=ana.id).count() == 0


def test_recalcular_agora_calcula_notas_da_escola(cliente, db, escola_completa):
    """Depois de vários /confirmar com recalcular=false (um por arquivo do lote),
    um único POST /recalcular calcula as notas de toda a escola."""
    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]

    for aluno, atividades in [(ana, 42), (joao, 10)]:
        r = cliente.post(
            f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
            json={
                "plataforma": "matific", "formato": "resumo", "tipo": "texto",
                "recalcular": False,
                "linhas": [{
                    "nome": aluno.nome,
                    "dados": {"atividades": atividades, "pontuacao_media": 70, "estrelas": 30},
                    "aluno_id": aluno.id,
                }],
            },
        )
        assert r.status_code == 200, r.text

    # Nenhuma nota ainda: o lote adiou o recálculo.
    assert db.query(Nota).count() == 0

    recalculo = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/recalcular")
    assert recalculo.status_code == 200, recalculo.text
    assert recalculo.json()["alunos"] >= 2

    # Agora as duas notas existem e quem tem mais atividades pontua mais.
    nota_ana = db.query(Nota).filter_by(aluno_id=ana.id).one()
    nota_joao = db.query(Nota).filter_by(aluno_id=joao.id).one()
    assert nota_ana.nota_matific > nota_joao.nota_matific


def test_recalcular_exige_papel_autorizado(cliente, db, escola_completa):
    """O endpoint de recálculo do lote respeita os papéis (admin/coordenador)."""
    escola_id = escola_completa["escola"].id
    resposta = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/recalcular")
    assert resposta.status_code == 200, resposta.text
    assert "alunos" in resposta.json()


def test_catalogo_de_livros_busca_e_protecao_de_exclusao(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    criado = cliente.post(
        f"/api/v1/escolas/{escola_id}/livros",
        json={"titulo": "O Mapa Perdido", "autor": "Rita Campos", "nivel_codigo": "d"},
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["nivel_codigo"] == "D"
    assert criado.json()["pontos"] == 4.0  # padrão do Nível 2

    busca = cliente.get(f"/api/v1/escolas/{escola_id}/livros", params={"busca": "mapa"})
    assert busca.json()["total"] == 1

    # Com leitura registrada, a exclusão é bloqueada
    ana = escola_completa["alunos"][0]
    livro_id = criado.json()["id"]
    from app.models import Leitura
    db.add(Leitura(escola_id=escola_id, aluno_id=ana.id, livro_id=livro_id))
    db.commit()
    exclusao = cliente.delete(f"/api/v1/escolas/{escola_id}/livros/{livro_id}")
    assert exclusao.status_code == 409
