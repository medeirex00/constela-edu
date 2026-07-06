"""Biblioteca de Conquistas: catálogo, estatísticas e painel configurável."""
from app.models import Configuracao, Importacao, SnapshotElefante, SnapshotMatific
from app.services import gamificacao as svc


def _snapshots(db, escola_completa):
    """Ana: 12 livros/650 min; João: 1 livro; Sofia: sem dados."""
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    importacao = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(importacao)
    db.flush()
    db.add_all([
        SnapshotElefante(escola_id=escola.id, aluno_id=ana.id,
                         importacao_id=importacao.id, livros_unicos=12,
                         tempo_leitura_min=650, questoes_tentativas=30,
                         questoes_acertos=27),
        SnapshotMatific(escola_id=escola.id, aluno_id=ana.id,
                        importacao_id=importacao.id, atividades=60,
                        estrelas=1600, pontuacao_media=4.2),
        SnapshotElefante(escola_id=escola.id, aluno_id=joao.id,
                         importacao_id=importacao.id, livros_unicos=1,
                         tempo_leitura_min=30, questoes_tentativas=5,
                         questoes_acertos=4),
    ])
    db.commit()


def test_biblioteca_conta_desbloqueios_e_estatisticas(cliente, db, escola_completa):
    _snapshots(db, escola_completa)
    escola = escola_completa["escola"]

    corpo = cliente.get(f"/api/v1/escolas/{escola.id}/gamificacao/biblioteca").json()
    conquistas = {c["codigo"]: c for c in corpo["conquistas"]}

    # todas as conquistas aparecem, mesmo as que ninguém desbloqueou
    assert len(corpo["conquistas"]) == len(svc.CONQUISTAS_PADRAO)
    assert conquistas["leitor_ouro"]["desbloqueios"] == 0

    # Ana e João concluíram ≥1 livro; só Ana chegou ao bronze (10)
    assert conquistas["primeira_leitura"]["desbloqueios"] == 2
    assert conquistas["leitor_bronze"]["desbloqueios"] == 1
    # Constelação (1500 estrelas) — Ana tem 1600
    assert conquistas["constelacao"]["desbloqueios"] == 1

    # metadados completos para o modal da Biblioteca
    prata = conquistas["leitor_prata"]
    assert prata["xp"] == 250
    assert prata["raridade"] == "rara"
    assert prata["plataforma"] == "elefante"
    assert prata["criterio"] == "Concluir 25 livro(s) válido(s)"
    assert prata["criada_em"]
    assert prata["ativa"] is True

    estatisticas = corpo["estatisticas"]
    assert estatisticas["total"] == len(svc.CONQUISTAS_PADRAO)
    assert estatisticas["alunos"] == 3
    assert estatisticas["mais_comum"]["codigo"] == "primeira_leitura"
    assert estatisticas["maior_xp"]["codigo"] == "constelacao"
    assert estatisticas["pct_medio_conclusao"] > 0
    assert estatisticas["ranking_desbloqueios"][0]["codigo"] == "primeira_leitura"


def test_configuracao_antiga_continua_valida(db, escola_completa):
    """Escolas com a lista salva no formato antigo ganham os campos novos."""
    escola = escola_completa["escola"]
    db.add(Configuracao(escola_id=escola.id, namespace="gamificacao.conquistas",
                        chave="lista", valor=[
                            {"codigo": "leitor_bronze", "nome": "Leitor Bronze",
                             "icone": "🥉", "descricao": "5 livros",
                             "indicador": "livros_unicos", "limite": 5},
                        ]))
    db.commit()

    lista = svc.listar_conquistas(db, escola.id, incluir_inativas=True)
    assert len(lista) == 1
    unica = lista[0]
    assert unica["limite"] == 5            # o valor da escola é respeitado
    assert unica["raridade"] == "comum"    # campos novos ganham padrão
    assert unica["xp"] == 100
    assert unica["plataforma"] == "elefante"
    assert unica["ativa"] is True


def test_painel_salva_edita_e_cria_conquista(cliente, db, escola_completa):
    _snapshots(db, escola_completa)
    escola = escola_completa["escola"]
    base = f"/api/v1/escolas/{escola.id}/gamificacao"

    definicoes = cliente.get(f"{base}/conquistas/definicoes").json()
    assert definicoes["raridades"]["lendaria"] == "Lendária"
    lista = definicoes["conquistas"]

    # edita o limite do bronze, desativa o ouro e cria uma conquista nova
    for item in lista:
        if item["codigo"] == "leitor_bronze":
            item["limite"] = 3
        if item["codigo"] == "leitor_ouro":
            item["ativa"] = False
    lista.append({
        "codigo": "", "nome": "Estrela Cadente", "icone": "🌠",
        "descricao": "800 estrelas na Matific.", "objetivo": "Meta intermediária.",
        "indicador": "estrelas", "limite": 800, "plataforma": "",
        "xp": 350, "raridade": "rara", "ativa": True, "criada_em": "",
    })
    resposta = cliente.put(f"{base}/conquistas/definicoes",
                           json={"conquistas": lista})
    assert resposta.status_code == 200, resposta.text
    salvas = {c["codigo"]: c for c in resposta.json()["conquistas"]}

    # slug gerado automaticamente + plataforma derivada do indicador
    assert "estrela_cadente" in salvas
    assert salvas["estrela_cadente"]["plataforma"] == "matific"
    assert salvas["estrela_cadente"]["criada_em"]

    # a nova conquista vale imediatamente: Ana tem 1600 estrelas ≥ 800
    ana = escola_completa["alunos"][0]
    do_aluno = cliente.get(f"{base}/alunos/{ana.id}").json()
    por_codigo = {c["codigo"]: c for c in do_aluno["conquistas"]}
    assert por_codigo["estrela_cadente"]["atingida"] is True
    # conquista desativada some do painel do aluno, mas segue na biblioteca
    assert "leitor_ouro" not in por_codigo
    biblioteca = cliente.get(f"{base}/biblioteca").json()
    ouro = next(c for c in biblioteca["conquistas"] if c["codigo"] == "leitor_ouro")
    assert ouro["ativa"] is False


def test_painel_recusa_indicador_invalido(cliente, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.put(
        f"/api/v1/escolas/{escola.id}/gamificacao/conquistas/definicoes",
        json={"conquistas": [{
            "codigo": "", "nome": "Quebrada", "indicador": "inexistente",
            "limite": 10, "xp": 100, "raridade": "comum",
        }]})
    assert resposta.status_code == 400
    assert "Indicador desconhecido" in resposta.json()["detail"]


def test_progresso_traz_faltam_pct_e_unidade(cliente, db, escola_completa):
    _snapshots(db, escola_completa)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = cliente.get(
        f"/api/v1/escolas/{escola.id}/gamificacao/alunos/{ana.id}").json()
    prata = next(c for c in corpo["conquistas"] if c["codigo"] == "leitor_prata")
    # 12 de 25 livros → 48%, faltam 13
    assert prata["atingida"] is False
    assert prata["progresso"] == 12
    assert prata["pct"] == 48.0
    assert prata["faltam"] == 13
    assert prata["unidade"] == "livros"
