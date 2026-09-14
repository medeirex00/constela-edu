"""Dificuldade por livro (v1) — os CONSUMIDORES usam a MESMA fonte.

Requisitos 10–15 do mandato: nota anual, ranking por período e premiações
pontuam o mesmo livro pelo mesmo valor; a regra é global entre escolas; override
não autorizado é bloqueado; nenhum cálculo antigo de dificuldade sobrevive fora
da fonte única (varredura estática)."""
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.security import hash_senha
from app.models import Nota, Usuario
from app.services import dificuldade_livro as dl
from app.services import scoring

APP = Path(__file__).resolve().parent.parent / "app"


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _ler(cliente, escola_id, aluno, titulo, nivel, data_iso):
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"livro": titulo, "nivel": nivel, "data": data_iso}}]})
    assert r.status_code == 200, r.text


def test_nota_anual_ranking_periodo_e_premiacoes_usam_a_mesma_fonte(cliente, db, escola_completa):
    """(10, 11, 12) O MESMO livro do catálogo — 'O Castelo Encantado' (Z, 68.915
    palavras, ajuste no teto 1,35) — vale o MESMO número na nota anual (híbrido
    itemizado), no ranking por período e no pódio 'Melhor Leitor'."""
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _ler(cliente, esc.id, ana, "O Castelo Encantado", "Z", "2026-07-05T09:00:00")
    _ler(cliente, esc.id, ana, "Domingo", "A", "2026-07-06T09:00:00")   # A, 35 palavras
    regra = dl.RegraV1()
    esperado = (regra.valor_livro("Z", "O Castelo Encantado", "3º Ano")
                + regra.valor_livro("A", "Domingo", "3º Ano"))
    assert regra.explicar("Z", "O Castelo Encantado", "3º Ano")["ajuste_intrinseco"] == 1.35

    # nota anual (recalculada pelo import): dados da dimensão + carimbo da versão
    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    dados = nota.detalhes["dimensoes"]["leitura"]["dados"]
    assert dados["pontos_dificuldade"] == pytest.approx(esperado, abs=0.02)
    assert dados["versao_dificuldade"] == dl.VERSAO_VIGENTE
    assert nota.detalhes["elefante"]["dificuldade"]["versao"] == dl.VERSAO_VIGENTE

    # ranking por período (aba Leitura)
    r = cliente.get(f"{_base(esc.id)}/ranking/leitura"
                    "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    assert r[0]["nome"] == ana.nome and r[0]["pontos"] == pytest.approx(esperado, abs=0.02)

    # premiações (Melhor Leitor)
    p = cliente.get(f"{_base(esc.id)}/premiacoes"
                    "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    ml = {c["chave"]: c["podio"] for c in p["categorias"]}["melhor_leitor"]
    assert ml[0]["nome"] == ana.nome and ml[0]["valor"] == pytest.approx(esperado, abs=0.02)

    # histórico do aluno: cada item vale o valor do livro; o resumo é a soma
    h = cliente.get(f"{_base(esc.id)}/alunos/{ana.id}/leituras").json()
    valores = {i["livro"]: i["pontos"] for i in h["itens"]}
    assert valores["O Castelo Encantado"] == pytest.approx(
        regra.valor_livro("Z", "O Castelo Encantado", "3º Ano"), abs=0.01)
    assert h["resumo"]["pontos"] == pytest.approx(esperado, abs=0.02)


def test_duas_escolas_padrao_com_os_mesmos_dados_tem_a_mesma_dificuldade(db, escola_completa):
    """(14) A regra é GLOBAL: escolas diferentes, mesmos dados ⇒ mesmos pontos."""
    from app.models import Aluno, Escola, Importacao, Matricula, SnapshotElefante, Turma

    def _escola(nome):
        e = Escola(nome=nome, ano_letivo_ativo=2026)
        db.add(e); db.flush()
        t = Turma(escola_id=e.id, nome="2A", ano_escolar="2º Ano", ano_letivo=2026)
        db.add(t); db.flush()
        a = Aluno(escola_id=e.id, nome=f"Aluno {nome}")
        db.add(a); db.flush()
        db.add(Matricula(escola_id=e.id, aluno_id=a.id, turma_id=t.id, ano_letivo=2026))
        imp = Importacao(escola_id=e.id, plataforma="elefante", tipo="texto")
        db.add(imp); db.flush()
        db.add(SnapshotElefante(escola_id=e.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=5, tempo_leitura_min=50,
                                livros_por_nivel={"D": 3, "K": 2}))
        db.commit()
        scoring.recalcular_escola(db, e.id)
        return db.execute(select(Nota).where(Nota.aluno_id == a.id)).scalars().one()

    n1, n2 = _escola("Escola Norte"), _escola("Escola Sul")
    d1 = n1.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"]
    d2 = n2.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"]
    assert d1 == d2 == pytest.approx(dl.RegraV1().pontos_aluno({"D": 3, "K": 2}, "2º Ano"), abs=0.01)


def test_coordenador_nao_consegue_sair_da_regra_global(cliente, db, escola_completa):
    """(15) Override não autorizado é bloqueado: só o Admin Global troca o perfil."""
    esc = escola_completa["escola"]
    db.add(Usuario(escola_id=esc.id, nome="Coord", email="coord@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    login = cliente.post("/api/v1/auth/login",
                         data={"username": "coord@teste.local", "password": "s3nh4"})
    assert login.status_code == 200, login.text
    cliente.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    base = f"{_base(esc.id)}/configuracoes/perfil-scoring"
    assert cliente.put(base, json={"modo": "personalizado"}).status_code == 403
    assert cliente.get(base).json()["modo"] == "institucional"
    # e a leitura da regra vigente é aberta à coordenação (explicável), sem edição
    r = cliente.get(f"{_base(esc.id)}/configuracoes/dificuldade-livro"
                    "?nivel=Z&titulo=O%20Castelo%20Encantado&ano_escolar=1%C2%BA%20Ano")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["versao_vigente"] == dl.VERSAO_VIGENTE == corpo["regra_da_escola"]
    assert corpo["parametros"]["alpha"] == 0.35 and corpo["catalogo"]["n"] >= 752
    assert corpo["exemplo"]["ajuste_intrinseco"] == 1.35 and corpo["exemplo"]["fator_serie"] == 1.40


def test_nenhum_calculo_antigo_de_dificuldade_sobrevive_fora_da_fonte_unica():
    """(13) Varredura estática: fora de ``dificuldade_livro`` (a fonte) e de
    ``scoring`` (onde vivem os helpers LEGADOS que a régua legada reusa), nenhum
    módulo da aplicação chama a régua antiga por faixa/turma nem a A3 direto."""
    # CHAMADAS às funções da régua antiga (o atributo `PontuacaoNivelTurma.
    # pontos_por_codigo` é armazenamento de config, não cálculo — permitido).
    proibidos = re.compile(
        r"\b(mapa_pontos_turmas|pontos_por_codigo|_mapa_dificuldade|_pontos_dificuldade"
        r"|peso_a3)\s*\(|\bA3_MAPA_DIFICULDADE\b")
    permitidos = {"services/dificuldade_livro.py", "services/scoring.py"}
    # `services/pontuacao/` é o motor V2 (workstream paralelo, fora deste escopo).
    ignorados = ("services/pontuacao/",)
    infratores = []
    for arquivo in APP.rglob("*.py"):
        rel = arquivo.relative_to(APP).as_posix()
        if rel in permitidos or rel.startswith(ignorados):
            continue
        for n, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if proibidos.search(linha) and not linha.lstrip().startswith("#"):
                infratores.append(f"{rel}:{n}: {linha.strip()}")
    assert not infratores, "\n".join(infratores)
