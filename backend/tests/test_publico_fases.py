"""A Educação Infantil (Fases) não aparece em NENHUMA rota sem login.

As premiações são do 1º ao 5º ano (`services/elegibilidade.py`). O painel
PÚBLICO monta as próprias listas, sem passar por `rankings._ranking`, e a Nota
já carimbada de quem saiu da população não some no recálculo — então cada
caminho sem login que lista ou abre criança precisa repetir o corte. c54856d
fez isso para o ranking e para a parte do ranking de `_ids_visiveis`; este
arquivo trava o resto: evolução, destaques, mural e o perfil público.

Versão que vale para o código PUBLICADO (o painel com os slides ranking,
evolução, destaques e mural). Os casos por dimensão (`rankings_dimensao`,
`n_aferidos` do telão) só existem com a Arquitetura 2 e ficam no arquivo
completo dela.

O cenário reproduz o caso que motivou a regra: uma criança de Fase com a Nota
ANTIGA no topo (posição 1, carimbada antes de sair da população) e com o MAIOR
crescimento do mês — ou seja, ela ganharia qualquer lista do telão se o corte
faltasse. A criança do 5º ano é o controle positivo: tem de continuar
aparecendo em todas.

Os nomes são fictícios.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import (Aluno, Importacao, Matricula, Nota, Rede, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.services import scoring

API = "/api/v1"
NOME_FASE = "ZEFIRINO EMEI FICTICIO"
NOME_FUND = "VALDOMIRO FUNDAMENTAL FICTICIO"
SLIDES = ["ranking", "evolucao", "destaques", "mural"]


# ---------------------------------------------------------------------------
# Cenário
# ---------------------------------------------------------------------------
def _turma(db, escola, nome, ano_escolar):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo)
    db.add(t)
    db.flush()
    return t


def _crianca(db, escola, turma, nome):
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo", da_lista_piloto=True)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    return a


def _snapshots(db, escola, aluno, imp_m, imp_e, *, fim_atividades, fim_estrelas,
               fim_livros, agora):
    """Base 20 dias atrás + valor de hoje: há crescimento REAL dentro da janela
    de 30 dias do telão (base_no_periodo=True) e conquistas recentes no mural."""
    antes = agora - timedelta(days=20)
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=imp_m.id, atividades=10, estrelas=5,
                           pontuacao_media=50, data_referencia=antes))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=imp_m.id, atividades=fim_atividades,
                           estrelas=fim_estrelas, pontuacao_media=80,
                           data_referencia=agora))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=imp_e.id, livros_unicos=1,
                            tempo_leitura_min=10, data_referencia=antes))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=imp_e.id, livros_unicos=fim_livros,
                            tempo_leitura_min=fim_livros * 20,
                            data_referencia=agora))


def _montar(db, escola, *, com_fundamental=True):
    fund = _turma(db, escola, "5º Ano Z", "5º Ano") if com_fundamental else None
    emei = _turma(db, escola, "2ª Fase Z", "2ª Fase")
    do_fund = _crianca(db, escola, fund, NOME_FUND) if fund else None
    da_fase = _crianca(db, escola, emei, NOME_FASE)
    imp_m = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    imp_e = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add_all([imp_m, imp_e])
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    if do_fund is not None:
        _snapshots(db, escola, do_fund, imp_m, imp_e, fim_atividades=300,
                   fim_estrelas=200, fim_livros=20, agora=agora)
    # A criança da Fase cresce MAIS: sem o corte, ela lidera a evolução e o
    # destaque do mês.
    _snapshots(db, escola, da_fase, imp_m, imp_e, fim_atividades=600,
               fim_estrelas=400, fim_livros=40, agora=agora)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    # A Nota ANTIGA da Fase (carimbada antes de ela sair da população) continua
    # no banco, no topo — o caso das fichas de Fase depois de c496cec.
    nota = db.execute(select(Nota).where(
        Nota.aluno_id == da_fase.id,
        Nota.ano_letivo == escola.ano_letivo_ativo)).scalar_one_or_none()
    if nota is None:
        nota = Nota(escola_id=escola.id, aluno_id=da_fase.id,
                    ano_letivo=escola.ano_letivo_ativo)
        db.add(nota)
    nota.nota_geral = nota.nota_elefante = nota.nota_matific = 99.0
    nota.posicao = 1
    db.commit()
    return {"escola": escola, "fund": do_fund, "fase": da_fase}


@pytest.fixture()
def cenario(db, escola_completa):
    return _montar(db, escola_completa["escola"])


def _ligar(cliente, escola_id, slides=None, **extra) -> str:
    corpo = {"ativo": True, "slides": slides or SLIDES,
             "intervalo_s": 8, "max_posicoes": 50}
    corpo.update(extra)
    r = cliente.put(f"{API}/escolas/{escola_id}/painel-publico", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[-1]


def _painel(token) -> dict:
    r = TestClient(app).get(f"{API}/publico/{token}/painel")   # SEM login
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /publico/{token}/painel — cada lista do telão
# ---------------------------------------------------------------------------
def test_ranking_do_telao_sem_a_fase(cliente, cenario):
    """O que c54856d já corrigiu — fica travado aqui junto com o resto."""
    corpo = _painel(_ligar(cliente, cenario["escola"].id))
    ids = [i["aluno_id"] for i in corpo["ranking"]]
    assert cenario["fund"].id in ids
    assert cenario["fase"].id not in ids, "Nota antiga da Fase voltou ao telão"


def test_evolucao_do_telao_sem_a_fase_e_posicao_entre_quem_concorre(cliente, cenario):
    corpo = _painel(_ligar(cliente, cenario["escola"].id))
    itens = corpo["evolucao"]
    ids = [i["aluno_id"] for i in itens]
    assert cenario["fase"].id not in ids, "a Fase lideraria a evolução do telão"
    assert ids and ids[0] == cenario["fund"].id
    assert itens[0]["posicao"] == 1      # renumerada entre quem concorre


def test_destaques_do_telao_sem_a_fase(cliente, cenario):
    corpo = _painel(_ligar(cliente, cenario["escola"].id))
    destaques = [d for d in corpo["destaques"].values() if d]
    assert cenario["fase"].id not in {d["aluno_id"] for d in destaques}
    # Controle positivo: o pódio do mês existe e é da criança do 5º ano.
    assert corpo["destaques"]["mes"] is not None
    assert corpo["destaques"]["mes"]["aluno_id"] == cenario["fund"].id


def test_mural_do_telao_nao_nomeia_a_fase(cliente, cenario):
    corpo = _painel(_ligar(cliente, cenario["escola"].id))
    textos = " | ".join(e["texto"] for e in corpo["mural"]).upper()
    assert NOME_FUND.split()[0] in textos           # controle positivo
    assert NOME_FASE.split()[0] not in textos


def test_nenhum_campo_do_payload_cita_a_fase(cliente, cenario):
    """Varredura do payload inteiro: nem id em lista, nem primeiro nome."""
    corpo = _painel(_ligar(cliente, cenario["escola"].id))
    texto = json.dumps(corpo, ensure_ascii=False).upper()
    assert NOME_FASE.split()[0] not in texto
    assert NOME_FUND.split()[0] in texto


def test_escola_so_de_fase_publica_listas_vazias(cliente, db, escola_completa):
    """Sem nenhuma turma que concorra, o recorte é vazio por definição: o telão
    abre (200), não nomeia ninguém e não quebra com o `IN ()` vazio."""
    # A turma da fixture também vira Fase: nenhuma turma da escola concorre.
    escola_completa["turma"].ano_escolar = "1ª Fase"
    db.commit()
    cen = _montar(db, escola_completa["escola"], com_fundamental=False)
    corpo = _painel(_ligar(cliente, cen["escola"].id))
    assert corpo["ranking"] == [] and corpo["evolucao"] == []
    assert corpo["mural"] == []
    assert all(v is None for v in corpo["destaques"].values())
    assert NOME_FASE.split()[0] not in json.dumps(corpo, ensure_ascii=False).upper()


# ---------------------------------------------------------------------------
# GET /publico/{token}/alunos/{aluno_id} — o perfil público
# ---------------------------------------------------------------------------
def test_perfil_publico_da_fase_e_404_e_o_do_fundamental_abre(cliente, cenario):
    token = _ligar(cliente, cenario["escola"].id)
    anon = TestClient(app)
    r_fund = anon.get(f"{API}/publico/{token}/alunos/{cenario['fund'].id}")
    assert r_fund.status_code == 200, r_fund.text
    r_fase = anon.get(f"{API}/publico/{token}/alunos/{cenario['fase'].id}")
    assert r_fase.status_code == 404
    # Mesma resposta de "fora do telão": o link não revela a etapa.
    assert r_fase.json() == {"detail": "Aluno não encontrado."}


def test_perfil_publico_da_fase_e_404_mesmo_se_a_lista_de_visiveis_falhar(
        cliente, cenario, monkeypatch):
    """Segunda linha de defesa: um slide futuro que esqueça o corte e devolva a
    criança da Fase em `_ids_visiveis` não reabre o perfil dela."""
    from app.routers import publico

    token = _ligar(cliente, cenario["escola"].id)
    vazou = {cenario["fase"].id, cenario["fund"].id}
    monkeypatch.setattr(publico, "_ids_visiveis", lambda *a, **k: vazou)
    anon = TestClient(app)
    assert anon.get(
        f"{API}/publico/{token}/alunos/{cenario['fase'].id}").status_code == 404
    assert anon.get(
        f"{API}/publico/{token}/alunos/{cenario['fund'].id}").status_code == 200


# ---------------------------------------------------------------------------
# O corte não mexe no que a escola configurou
# ---------------------------------------------------------------------------
def test_corte_nao_muda_anonimizacao_token_nem_desligar(cliente, cenario):
    escola_id = cenario["escola"].id
    token = _ligar(cliente, escola_id, slides=["ranking"])
    anon = TestClient(app)
    item = next(i for i in _painel(token)["ranking"]
                if i["aluno_id"] == cenario["fund"].id)
    assert item["nome"] == "VALDOMIRO F."        # anonimizado por padrão
    assert item["turma"] is None                 # k-anonimato

    # Nome completo só com a confirmação explícita (barreira do servidor).
    r = cliente.put(f"{API}/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking"], "intervalo_s": 8,
                          "max_posicoes": 50, "anonimizar": False})
    assert r.status_code == 400
    _ligar(cliente, escola_id, slides=["ranking"], anonimizar=False,
           confirmar_exposicao=True)
    corpo = _painel(token)                       # painel ativo: mesmo endereço
    nomes = {i["nome"] for i in corpo["ranking"]}
    assert NOME_FUND in nomes and NOME_FASE not in nomes

    # Desligar bloqueia painel e perfil na hora; religar gera endereço novo.
    r = cliente.put(f"{API}/escolas/{escola_id}/painel-publico",
                    json={"ativo": False, "slides": ["ranking"]})
    assert r.status_code == 200
    assert anon.get(f"{API}/publico/{token}/painel").status_code == 404
    assert anon.get(
        f"{API}/publico/{token}/alunos/{cenario['fund'].id}").status_code == 404
    novo = _ligar(cliente, escola_id, slides=["ranking"])
    assert novo != token
    assert anon.get(f"{API}/publico/{token}/painel").status_code == 404
    assert anon.get(f"{API}/publico/{novo}/painel").status_code == 200


# ---------------------------------------------------------------------------
# GET /publico/rede/{token} — vitrine da Secretaria
# ---------------------------------------------------------------------------
def test_vitrine_da_rede_nao_lista_crianca(db, cenario):
    from app.services import rede as svc_rede

    rede = Rede(nome="Rede Ficticia", status="ativa")
    db.add(rede)
    db.flush()
    cenario["escola"].rede_id = rede.id
    token = svc_rede.definir_painel_publico(db, rede.id, True)
    db.commit()
    r = TestClient(app).get(f"{API}/publico/rede/{token}")
    assert r.status_code == 200, r.text
    corpo = r.json()
    texto = json.dumps(corpo, ensure_ascii=False).upper()
    for nome in (NOME_FASE, NOME_FUND):
        assert nome.split()[0] not in texto
    for linha in corpo["top_leitura"] + corpo["top_matematica"]:
        assert set(linha) == {"nome", "valor"}       # só escola + métrica


# ---------------------------------------------------------------------------
# Catraca: toda rota SEM login está coberta acima ou declarada inofensiva
# ---------------------------------------------------------------------------
#: Dependências que exigem identidade (gestor, aluno do Quest ou rede).
_AUTENTICA = {"get_usuario_atual", "get_aluno_atual", "exigir_admin_global",
              "escola_autorizada", "exigir_rede", "negar_secretaria"}

#: Rotas sem login que LISTAM ou ABREM criança — exercitadas neste arquivo.
COBERTAS = {
    "/api/v1/publico/{token}/painel",
    "/api/v1/publico/{token}/alunos/{aluno_id}",
    "/api/v1/publico/rede/{token}",
}

#: Rotas sem login que não listam nem abrem criança de outra pessoa.
NAO_LISTAM_CRIANCA = {
    "/api/health": "saúde do processo",
    "/api/health/live": "saúde do processo",
    "/api/health/ready": "saúde do processo",
    "/metrics": "telemetria; token próprio, fechada em produção sem token",
    "/api/v1/auth/login": "login de gestor",
    "/api/v1/auth/redefinir-senha": "consumo do link de redefinição",
    "/api/v1/auth/redefinir-senha/{token}": "validação do link de redefinição",
    "/api/v1/quest/auth/entrar": "login da criança com o PRÓPRIO código",
    "/api/v1/quest/auth/entrar-qr": "login da criança com o PRÓPRIO QR",
    "/api/v1/quest/auth/quem": "confirma o dono do código digitado (não lista)",
    "/api/v1/quest/perfil/aparencia": "catálogo estático de aparência",
    "/api/v1/quest/perfil/cores": "catálogo estático de cores",
    "/api/v1/quest/perfil/personagens": "catálogo estático de personagens",
}


def _dependencias(dependant) -> set[str]:
    nomes = set()
    for dep in dependant.dependencies:
        nomes.add(getattr(dep.call, "__name__", repr(dep.call)))
        nomes |= _dependencias(dep)
    return nomes


def test_toda_lista_do_modulo_publico_recebe_o_recorte():
    """Trava ESTRUTURAL (barata, independe de cenário): toda chamada que monta
    lista de crianças no módulo sem login — `ranking_evolucao` e `mural` — passa
    `turma_ids`. Pega um slide novo que esqueça o corte e, principalmente, um
    commit de uma cópia antiga de `publico.py` que desfaça a correção (o que já
    aconteceu com c54856d)."""
    import ast
    import inspect

    from app.routers import publico

    arvore = ast.parse(inspect.getsource(publico))
    chamadas = [n for n in ast.walk(arvore)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in {"ranking_evolucao", "mural"}]
    assert chamadas, "o módulo público deixou de montar evolução/mural?"
    sem_corte = [f"{c.func.attr} (linha {c.lineno})" for c in chamadas
                 if "turma_ids" not in {k.arg for k in c.keywords}]
    assert not sem_corte, f"lista pública sem o recorte das Fases: {sem_corte}"


def test_toda_rota_sem_login_esta_coberta_ou_declarada():
    abertas = {r.path for r in app.routes
               if isinstance(r, APIRoute)
               and not (_dependencias(r.dependant) & _AUTENTICA)}
    sem_dono = abertas - COBERTAS - set(NAO_LISTAM_CRIANCA)
    assert not sem_dono, (
        f"Rota SEM login nova: {sorted(sem_dono)}. Se ela lista ou abre "
        "criança, aplique `elegibilidade.turmas_premiaveis` e cubra aqui; senão "
        "declare em NAO_LISTAM_CRIANCA com o motivo.")
    assert COBERTAS <= abertas, "rota pública coberta sumiu — revisar a catraca"
