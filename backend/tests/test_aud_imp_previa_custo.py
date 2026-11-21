"""A prévia de importação tem custo limitado.

* O casamento de nomes (``casar_nomes``) comparava CADA linha que criaria ficha com
  TODOS os alunos ativos da escola (duas ``SequenceMatcher.ratio()`` por aluno), sem
  memória: o relatório de leituras repete o nome da criança numa linha por livro e
  pagava a varredura inteira em cada uma (600 linhas de 30 crianças ≈ 1 min). Agora a
  busca dos parecidos é feita uma vez por nome, com os nomes dos ativos preparados uma
  vez e um pré-filtro exato (``real_quick_ratio``/``quick_ratio`` são tetos do
  ``ratio``) — as alternativas oferecidas são as mesmas.
* O texto colado ou enviado como .txt/.csv tem teto de linhas (o de 10 MB deixava
  ~200 mil linhas, minutos de parse), com mensagem clara.
* Durante o parse, a requisição não segura uma conexão do banco (a checagem de módulos
  abria a transação antes dele).

Dados fictícios.
"""
from difflib import SequenceMatcher

from app.core.database import get_db
from app.main import app
from app.models import Aluno, Matricula, Turma
from app.services import importacao as svc

API = "/api/v1"


def _povoar(db, escola_id: int, n_alunos: int) -> None:
    turmas = []
    for i in range(10):
        t = Turma(escola_id=escola_id, nome=f"{1 + i % 5}º Ano {'FG'[i // 5]}",
                  ano_escolar=f"{1 + i % 5}º Ano", ano_letivo=2026)
        db.add(t)
        turmas.append(t)
    db.flush()
    sobrenomes = ["Souza", "Lima", "Pereira", "Almeida", "Costa", "Ribeiro"]
    for i in range(n_alunos):
        a = Aluno(escola_id=escola_id,
                  nome=f"Crianca Ficticia {i:04d} {sobrenomes[i % len(sobrenomes)]}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id,
                         turma_id=turmas[i % 10].id, ano_letivo=2026))
    db.commit()


def _linhas(nomes):
    return [svc.LinhaImportacao(numero=i, nome=n,
                                dados={"livro": f"Livro {i}", "turma_relatorio": "3º Ano A"})
            for i, n in enumerate(nomes, start=1)]


def _contar_ratio(monkeypatch) -> dict:
    contagem = {"n": 0}
    original = SequenceMatcher.ratio

    def contando(self):
        contagem["n"] += 1
        return original(self)

    monkeypatch.setattr(SequenceMatcher, "ratio", contando)
    return contagem


def test_nome_repetido_nao_refaz_a_busca_dos_parecidos(db, escola_completa, monkeypatch):
    escola_id = escola_completa["escola"].id
    _povoar(db, escola_id, 300)
    contagem = _contar_ratio(monkeypatch)
    svc.casar_nomes(db, escola_id, _linhas(["Crianca Ficticia Nova Souza"]))
    uma = contagem["n"]
    contagem["n"] = 0
    linhas = _linhas(["Crianca Ficticia Nova Souza"] * 40)
    svc.casar_nomes(db, escola_id, linhas)
    quarenta = contagem["n"]
    assert all(l.correspondencia["status"] == "nao_encontrado" for l in linhas)
    # 40 linhas da mesma criança (40 livros) custam o mesmo que uma: a busca dos
    # parecidos é por nome. Antes: 40 x (2 ratios x 300 ativos).
    # (O motor de identidade ainda compara cada linha com a própria sala: poucas.)
    assert quarenta <= uma + 40 * 30, (uma, quarenta)


def _alternativas_de_referencia(db, escola_id, nome):
    """A regra de sempre, sem atalho: todos os ativos, ``_similaridade`` completa."""
    from app.services import identidade_aluno as ida

    ctx = ida.carregar_contexto(db, escola_id)
    alvo = svc.chave_nome(nome)
    ativos = [a for a in ctx.alunos.values() if a.status == "ativo"]
    pares = sorted(((a, svc._similaridade(alvo, svc.chave_nome(a.nome))) for a in ativos),
                   key=lambda par: (-par[1], par[0].id))
    return [(a.id, round(nota * 100, 1)) for a, nota in pares[:5]
            if nota >= svc.LIMIAR_ALTERNATIVA]


def test_alternativas_oferecidas_sao_as_mesmas_da_regra_completa(db, escola_completa):
    escola_id = escola_completa["escola"].id
    _povoar(db, escola_id, 120)
    nomes = ["Crianca Ficticia 0007 Souzza", "Criança Fictícia Nova Lima",
             "Ficticia Crianca 0042 Costa", "Zuleica Inventada Ramos",
             "Ana Beatris Souza", "Joao Pedro Barboza"]
    linhas = [svc.LinhaImportacao(numero=i, nome=n, dados={"turma_relatorio": "9º Ano Z"})
              for i, n in enumerate(nomes, start=1)]
    svc.casar_nomes(db, escola_id, linhas)
    conferidas = 0
    for linha in linhas:
        corr = linha.correspondencia
        if corr["status"] not in ("nao_encontrado", "bloqueado"):
            continue
        conferidas += 1
        obtidas = [(alt["aluno_id"], alt["similaridade"]) for alt in corr["alternativas"]]
        assert obtidas == _alternativas_de_referencia(db, escola_id, linha.nome), linha.nome
    assert conferidas >= 3


def test_previa_nao_segura_conexao_durante_o_parse(db, escola_completa, cliente,
                                                   monkeypatch):
    escola_id = escola_completa["escola"].id
    sessoes = []
    fabrica = app.dependency_overrides[get_db]

    def _get_db_espiao():
        gen = fabrica()
        sessao = next(gen)
        sessoes.append(sessao)
        try:
            yield sessao
        finally:
            gen.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, _get_db_espiao)
    original = svc.analisar_texto
    visto = {}

    def espiao(texto, plataforma=None):
        visto["transacao_aberta"] = any(s.in_transaction() for s in sessoes)
        return original(texto, plataforma)

    monkeypatch.setattr(svc, "analisar_texto", espiao)
    texto = "Nome;Título do livro;Nível\n" + "".join(
        f"Menino Ficticio {i % 30:04d} Souza;Livro Inventado {i};AA\n" for i in range(60))
    r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/analisar",
                     files={"arquivo": ("leituras.csv", texto.encode(), "text/csv")})
    assert r.status_code == 200, r.text[:300]
    assert visto == {"transacao_aberta": False}


def test_texto_acima_do_teto_de_linhas_e_recusado_com_mensagem(cliente, escola_completa,
                                                               monkeypatch):
    escola_id = escola_completa["escola"].id
    chamado = []
    monkeypatch.setattr(svc, "analisar_texto", lambda *a, **k: chamado.append(1))
    texto = "Nome do aluno\tAtividades finalizadas\n" + "Menino Ficticio Souza\t1\n" * 20_001
    for envio in ({"files": {"arquivo": ("relatorio.txt", texto.encode(), "text/plain")}},
                  {"files": {"texto": (None, texto)}}):
        r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/analisar", **envio)
        assert r.status_code == 413, r.text[:300]
        assert "20.000 linhas" in r.json()["detail"]
    assert chamado == []
