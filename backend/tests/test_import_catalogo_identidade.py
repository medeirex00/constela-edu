"""Identidade OFICIAL do livro na importação/sincronização do Elefante.

O id do livro no catálogo oficial é a identidade principal; o título é fallback.
Ordem de casamento: id da linha → id do catálogo por título+nível → (título,
nível) da escola → título único sem conflito de nível. Homônimos oficiais são
livros distintos; o nível oficial prevalece sobre alteração local sem aval do
Admin Global; a correção do Admin Global é preservada e a divergência auditada.
"""
import pytest
from sqlalchemy import func, select

from app.models import EventoAluno, Leitura, Livro, LogAuditoria
from app.services import dificuldade_livro

CONFIRMAR = "/api/v1/escolas/{eid}/importacoes/confirmar"


def _importar(cliente, escola_id: int, aluno, livros: list[dict]) -> dict:
    linhas = [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": dados} for dados in livros]
    resposta = cliente.post(CONFIRMAR.format(eid=escola_id), json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto", "linhas": linhas})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _oficial(titulo: str, nivel: str):
    meta = dificuldade_livro.catalogo().buscar(titulo, nivel)
    assert meta is not None and meta.nivel == nivel, (titulo, nivel)
    return meta


def _livros(db, escola_id: int) -> list[Livro]:
    db.expire_all()
    return db.execute(select(Livro).where(Livro.escola_id == escola_id)
                      .order_by(Livro.id)).scalars().all()


def _logs(db, acao: str) -> list[LogAuditoria]:
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)
                      .order_by(LogAuditoria.id)).scalars().all()


def test_import_casa_pelo_id_oficial_mesmo_com_titulo_diferente(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    meta = _oficial("Cadê?", "B")
    local = Livro(escola_id=escola.id, titulo="Cade (cópia local)", nivel_codigo="B",
                  elefante_id=meta.id)
    db.add(local)
    db.commit()

    _importar(cliente, escola.id, ana, [
        {"livro": "Cadê?", "nivel": "B", "elefante_id": meta.id, "data": "2026-06-10T10:00:00"}])

    assert [l.id for l in _livros(db, escola.id)] == [local.id]    # nenhum livro novo
    leituras = db.execute(select(Leitura).where(Leitura.aluno_id == ana.id)).scalars().all()
    assert [l.livro_id for l in leituras] == [local.id]


def test_homonimos_oficiais_viram_livros_distintos_e_as_leituras_contam(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    linhas = [
        {"livro": "Cadê?", "nivel": "B", "data": "2026-06-10T10:00:00"},
        {"livro": "Cadê?", "nivel": "BB", "data": "2026-06-11T10:00:00"},
        {"livro": "Chapeuzinho Vermelho", "nivel": "I", "data": "2026-06-12T10:00:00"},
        {"livro": "Chapeuzinho Vermelho", "nivel": "K", "data": "2026-06-13T10:00:00"},
    ]
    _importar(cliente, escola.id, ana, linhas)

    livros = _livros(db, escola.id)
    esperado = {(t, n, _oficial(t, n).id, _oficial(t, n).word_count)
                for t, n in [("Cadê?", "B"), ("Cadê?", "BB"),
                             ("Chapeuzinho Vermelho", "I"), ("Chapeuzinho Vermelho", "K")]}
    assert {(l.titulo, l.nivel_codigo, l.elefante_id, l.word_count) for l in livros} == esperado
    assert all(l.origem_nivel == "fonte" and l.nivel_fonte == l.nivel_codigo for l in livros)
    contar = select(func.count()).select_from(Leitura).where(Leitura.aluno_id == ana.id)
    assert db.execute(contar).scalar_one() == 4                  # as quatro leituras contam

    # A linha do tempo usa a MESMA resolução: cada evento aponta o próprio livro.
    eventos = db.execute(select(EventoAluno).where(EventoAluno.aluno_id == ana.id)).scalars().all()
    assert {(e.livro_id, e.nivel_codigo) for e in eventos} == {(l.id, l.nivel_codigo) for l in livros}

    # Reimportar o mesmo relatório não duplica livro nem leitura.
    _importar(cliente, escola.id, ana, linhas)
    assert len(_livros(db, escola.id)) == 4
    assert db.execute(contar).scalar_one() == 4


def test_homonimo_legado_nao_e_renivelado_pelo_outro_nivel(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    legado = Livro(escola_id=escola.id, titulo="Cadê?", nivel_codigo="B", origem_nivel="legado")
    db.add(legado)
    db.commit()

    _importar(cliente, escola.id, ana, [{"livro": "Cadê?", "nivel": "BB", "data": "2026-06-10T10:00:00"}])

    livros = _livros(db, escola.id)
    assert len(livros) == 2
    antigo = next(l for l in livros if l.id == legado.id)
    assert (antigo.nivel_codigo, antigo.elefante_id) == ("B", None)
    novo = next(l for l in livros if l.id != legado.id)
    assert (novo.nivel_codigo, novo.elefante_id) == ("BB", _oficial("Cadê?", "BB").id)
    assert _logs(db, "livro.nivel_oficial_restaurado") == []


def test_nivel_legado_alterado_pela_escola_volta_ao_oficial_com_auditoria(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    meta = _oficial("Laerte, o Gato Inerte", "B")
    legado = Livro(escola_id=escola.id, titulo="Laerte, o Gato Inerte", nivel_codigo="F",
                   origem_nivel="legado")
    db.add(legado)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=joao.id, livro_id=legado.id))
    db.commit()

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-11T09:00:00"}])

    livros = _livros(db, escola.id)
    assert [l.id for l in livros] == [legado.id]                 # mesmo livro, nada duplicado
    livro = livros[0]
    assert (livro.nivel_codigo, livro.nivel_fonte, livro.origem_nivel) == ("B", "B", "fonte")
    assert (livro.elefante_id, livro.word_count) == (meta.id, meta.word_count)
    assert livro.atualizado_em is not None
    # histórico preservado: a leitura antiga do João e a nova da Ana no MESMO livro
    pares = set(db.execute(select(Leitura.aluno_id, Leitura.livro_id)).all())
    assert pares == {(joao.id, legado.id), (ana.id, legado.id)}

    restaurados = _logs(db, "livro.nivel_oficial_restaurado")
    assert len(restaurados) == 1
    assert restaurados[0].entidade_id == legado.id
    assert (restaurados[0].detalhes["de"], restaurados[0].detalhes["para"]) == ("F", "B")
    vinculos = _logs(db, "livro.vinculado_catalogo")
    assert len(vinculos) == 1                                     # agregada por importação
    assert vinculos[0].detalhes["livros"] == [{"livro_id": legado.id, "elefante_id": meta.id}]
    assert any("nível oficial" in a for a in resultado["avisos"])


def test_nivel_do_admin_global_e_preservado_com_auditoria_de_divergencia(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    meta = _oficial("Laerte, o Gato Inerte", "B")
    corrigido = Livro(escola_id=escola.id, titulo="Laerte, o Gato Inerte", nivel_codigo="D",
                      origem_nivel="admin_global")
    db.add(corrigido)
    db.commit()
    linha = {"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-11T09:00:00"}

    _importar(cliente, escola.id, ana, [linha])

    livro = _livros(db, escola.id)[0]
    assert (livro.nivel_codigo, livro.origem_nivel) == ("D", "admin_global")   # preservado
    assert (livro.nivel_fonte, livro.elefante_id) == ("B", meta.id)
    divergencias = _logs(db, "livro.nivel_divergente")
    assert len(divergencias) == 1
    assert divergencias[0].detalhes["nivel_efetivo"] == "D"
    assert divergencias[0].detalhes["nivel_fonte"] == {"de": None, "para": "B"}
    assert _logs(db, "livro.nivel_oficial_restaurado") == []

    # A próxima sincronização, com a mesma fonte, não reaudita a mesma divergência.
    _importar(cliente, escola.id, joao, [linha])
    assert len(_logs(db, "livro.nivel_divergente")) == 1


def test_planilha_com_nivel_diferente_do_oficial_usa_o_oficial(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    meta = _oficial("Laerte, o Gato Inerte", "B")

    resultado = _importar(cliente, escola.id, ana, [{"livro": "Laerte, o Gato Inerte", "nivel": "M"}])

    livros = _livros(db, escola.id)
    assert len(livros) == 1
    assert (livros[0].nivel_codigo, livros[0].nivel_fonte, livros[0].origem_nivel) == ("B", "B", "fonte")
    assert livros[0].elefante_id == meta.id
    assert any("vale o oficial" in a for a in resultado["avisos"])
    assert db.execute(select(func.count()).select_from(Leitura)
                      .where(Leitura.aluno_id == ana.id)).scalar_one() == 1


def test_codigo_de_nivel_desconhecido_ignora_a_linha(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Livro Inventado", "nivel": "ZZ", "data": "2026-06-12T08:00:00"},
        {"livro": "Outro Livro Local", "nivel": "K", "data": "2026-06-12T09:00:00"},
    ])

    assert any("ZZ" in a and "ignorada" in a for a in resultado["avisos"])
    assert [l.titulo for l in _livros(db, escola.id)] == ["Outro Livro Local"]
    assert db.execute(select(func.count()).select_from(Leitura)
                      .where(Leitura.aluno_id == ana.id)).scalar_one() == 1
    eventos = db.execute(select(EventoAluno.conteudo_titulo)
                         .where(EventoAluno.aluno_id == ana.id)).scalars().all()
    assert eventos == ["Outro Livro Local"]


def test_id_da_linha_que_contradiz_o_catalogo_e_ignorado_com_auditoria(cliente, db, escola_completa):
    """Um id cuja entrada no catálogo tem OUTRO título não é o mesmo livro:
    descartado, a linha casa por título+nível e o descarte é auditado."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    laerte = _oficial("Laerte, o Gato Inerte", "B")
    outro = _oficial("Cadê?", "BB")                     # título e nível diferentes

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "elefante_id": outro.id,
         "data": "2026-06-11T09:00:00"}])

    livros = _livros(db, escola.id)
    assert [(l.titulo, l.nivel_codigo, l.elefante_id) for l in livros] == [
        ("Laerte, o Gato Inerte", "B", laerte.id)]
    assert any("não batem com o catálogo oficial" in a for a in resultado["avisos"])
    inconsistentes = _logs(db, "livro.id_oficial_inconsistente")
    assert len(inconsistentes) == 1
    assert inconsistentes[0].detalhes["ids"] == [
        {"elefante_id": outro.id, "titulo_linha": "Laerte, o Gato Inerte",
         "motivo": "titulo_diferente"}]


def test_linha_sem_casamento_nao_troca_o_nivel_fonte_de_livro_vinculado(cliente, db, escola_completa):
    """Livro já vinculado ao catálogo: uma planilha com o nível de um homônimo
    (sem casamento no catálogo) não rebaixa o ``nivel_fonte`` para o nível dela."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    meta_b = _oficial("Cadê?", "B")
    corrigido = Livro(escola_id=escola.id, titulo="Cadê?", nivel_codigo="C",
                      elefante_id=meta_b.id, nivel_fonte="B", origem_nivel="admin_global")
    db.add(corrigido)
    db.commit()

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Cadê?", "nivel": "C", "data": "2026-06-10T10:00:00"}])

    livros = _livros(db, escola.id)
    assert [l.id for l in livros] == [corrigido.id]
    assert (livros[0].nivel_codigo, livros[0].nivel_fonte, livros[0].origem_nivel) == (
        "C", "B", "admin_global")
    assert _logs(db, "livro.nivel_divergente") == []           # a fonte não mudou
    assert any("vale o oficial" in a for a in resultado["avisos"])
    assert db.execute(select(func.count()).select_from(Leitura)
                      .where(Leitura.aluno_id == ana.id)).scalar_one() == 1


def test_parser_da_api_mapeia_book_id_so_quando_inteiro_valido():
    from app.services.importacao import analisar_elefante_api

    base = {"nome": "Ana Beatriz Souza", "levelName": "B", "lastReadWhen": "2026-06-26T08:59:43"}
    payload = {"courseSchoolDescriptors": {"courseName": "5 ANO B"}, "leituras": [
        {**base, "bookTitle": "Cadê?", "bookId": 2356},
        {**base, "bookTitle": "Texto", "bookId": "4799"},
        {**base, "bookTitle": "Fração", "bookId": 12.5},
        {**base, "bookTitle": "Booleano", "bookId": True},
        {**base, "bookTitle": "Lixo", "bookId": "abc"},
        {**base, "bookTitle": "Sem id"},
    ]}
    analise = analisar_elefante_api(payload)
    ids = {linha.dados["livro"]: linha.dados.get("elefante_id") for linha in analise.linhas}
    assert ids == {"Cadê?": 2356, "Texto": 4799, "Fração": None, "Booleano": None,
                   "Lixo": None, "Sem id": None}


# ---------------------------------------------------------------------------
# A escola NÃO renivela o acervo pela importação (fora do catálogo oficial)
# ---------------------------------------------------------------------------

def test_planilha_nao_renivela_livro_fora_do_catalogo(cliente, db, escola_completa):
    """Livro que NÃO está no catálogo oficial: o nível informado pelo relatório
    fica registrado como divergência, mas o nível EM USO (o que pontua para a
    escola inteira) não muda — e o aviso não pode dizer "voltou ao nível
    oficial", porque não existe nível oficial para este livro."""
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    titulo = "Livro Local Sem Catalogo XYZ"
    assert dificuldade_livro.catalogo().buscar(titulo, "C") is None
    local = Livro(escola_id=escola.id, titulo=titulo, nivel_codigo="C",
                  nivel_fonte="C", origem_nivel="fonte")
    db.add(local)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=joao.id, livro_id=local.id))
    db.commit()

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": titulo, "nivel": "Z", "data": "2026-06-10T10:00:00"}])

    livros = _livros(db, escola.id)
    assert [l.id for l in livros] == [local.id]            # nada duplicado
    livro = livros[0]
    assert livro.nivel_codigo == "C"                       # o nível em uso NÃO mudou
    assert (livro.nivel_fonte, livro.elefante_id) == ("Z", None)
    assert _logs(db, "livro.nivel_oficial_restaurado") == []
    divergencias = _logs(db, "livro.nivel_divergente")
    assert len(divergencias) == 1
    assert divergencias[0].entidade_id == local.id
    assert divergencias[0].detalhes["no_catalogo"] is False
    assert divergencias[0].detalhes["nivel_efetivo"] == "C"
    assert divergencias[0].detalhes["nivel_relatorio"] == {"de": "C", "para": "Z"}
    assert not any("nível oficial" in a for a in resultado["avisos"])
    assert any("nível informado pelo relatório" in a and "preservado" in a
               for a in resultado["avisos"])
    # a leitura da Ana entra no MESMO livro, no nível que já valia
    assert db.execute(select(func.count()).select_from(Leitura)).scalar_one() == 2

    # Reimportar a mesma planilha não reaudita a divergência já registrada.
    _importar(cliente, escola.id, joao, [{"livro": titulo, "nivel": "Z"}])
    assert len(_logs(db, "livro.nivel_divergente")) == 1


def test_livro_novo_fora_do_catalogo_nasce_como_alteracao_local(cliente, db, escola_completa):
    """Livro criado pela importação SEM casamento no catálogo tem o nível que a
    escola informou: nasce ``legado``, não ``fonte`` (que significa "veio da
    fonte oficial") — senão a trilha some na primeira reconciliação."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    fora = "Livro Local Sem Catalogo XYZ"
    meta = _oficial("Cadê?", "B")

    _importar(cliente, escola.id, ana, [
        {"livro": fora, "nivel": "K", "data": "2026-06-10T10:00:00"},
        {"livro": "Cadê?", "nivel": "B", "data": "2026-06-11T10:00:00"}])

    por_titulo = {l.titulo: l for l in _livros(db, escola.id)}
    novo = por_titulo[fora]
    assert (novo.nivel_codigo, novo.nivel_fonte, novo.origem_nivel) == ("K", "K", "legado")
    assert (novo.elefante_id, novo.word_count) == (None, None)
    # o livro DO catálogo, esse sim, nasce carimbado como vindo da fonte oficial
    do_catalogo = por_titulo["Cadê?"]
    assert (do_catalogo.origem_nivel, do_catalogo.elefante_id) == ("fonte", meta.id)


# ---------------------------------------------------------------------------
# O id da linha só vale com casamento de TÍTULO no catálogo oficial
# ---------------------------------------------------------------------------

def test_id_de_outro_livro_do_mesmo_nivel_nao_troca_a_identidade(cliente, db, escola_completa):
    """Id oficial de OUTRO título, no MESMO nível da linha: não identifica este
    livro. Aceitá-lo trocava ``elefante_id`` e ``word_count`` — ou seja, o valor
    do livro para todos os alunos."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    laerte = _oficial("Laerte, o Gato Inerte", "B")
    outro_b = _oficial("Cadê?", "B")                    # mesmo nível, outro título
    assert laerte.id != outro_b.id and laerte.word_count != outro_b.word_count
    local = Livro(escola_id=escola.id, titulo="Laerte, o Gato Inerte",
                  nivel_codigo="B", origem_nivel="legado")
    db.add(local)
    db.commit()

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "elefante_id": outro_b.id,
         "data": "2026-06-10T10:00:00"}])

    livros = _livros(db, escola.id)
    assert [l.id for l in livros] == [local.id]
    assert (livros[0].elefante_id, livros[0].word_count) == (laerte.id, laerte.word_count)
    descartes = _logs(db, "livro.id_oficial_inconsistente")
    assert len(descartes) == 1
    assert descartes[0].detalhes["ids"] == [
        {"elefante_id": outro_b.id, "titulo_linha": "Laerte, o Gato Inerte",
         "motivo": "titulo_diferente"}]
    assert any("não batem com o catálogo oficial" in a for a in resultado["avisos"])


def test_id_de_outro_livro_com_nivel_forjado_nao_renivela(cliente, db, escola_completa):
    """A linha forja o nível de um homônimo E manda o id de outro livro nesse
    nível: o id é descartado e vale o nível do CATÁLOGO para este título."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    laerte = _oficial("Laerte, o Gato Inerte", "B")
    outro = _oficial("Cadê?", "BB")
    local = Livro(escola_id=escola.id, titulo="Laerte, o Gato Inerte",
                  nivel_codigo="F", origem_nivel="legado")
    db.add(local)
    db.commit()

    _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "BB", "elefante_id": outro.id,
         "data": "2026-06-10T10:00:00"}])

    livros = _livros(db, escola.id)
    assert [l.id for l in livros] == [local.id]
    assert livros[0].nivel_codigo == "B"                 # o oficial, não o forjado
    assert livros[0].elefante_id == laerte.id
    assert _logs(db, "livro.id_oficial_inconsistente")[0].detalhes["ids"][0]["motivo"] == (
        "titulo_diferente")


def test_id_fora_do_catalogo_nao_vincula_e_nao_duplica_o_livro(cliente, db, escola_completa):
    """Id ausente do catálogo (ex.: id do REGISTRO de leitura da API, não do
    livro) não vira identidade: vinculá-lo fazia o ``bookId`` verdadeiro, na sync
    seguinte, criar um SEGUNDO livro com o mesmo título — as leituras do mesmo
    livro se dividiriam em dois registros e o dedup de releitura (§35) furaria."""
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    meta = _oficial("Laerte, o Gato Inerte", "B")
    desconhecido = 987654
    assert dificuldade_livro.catalogo().por_id.get(desconhecido) is None

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "elefante_id": desconhecido,
         "data": "2026-06-10T10:00:00"}])

    livros = _livros(db, escola.id)
    assert len(livros) == 1
    assert livros[0].elefante_id == meta.id              # nunca o id desconhecido
    assert _logs(db, "livro.id_oficial_inconsistente")[0].detalhes["ids"] == [
        {"elefante_id": desconhecido, "titulo_linha": "Laerte, o Gato Inerte",
         "motivo": "fora_do_catalogo"}]
    assert any("não batem com o catálogo oficial" in a for a in resultado["avisos"])

    # A sync seguinte, com o bookId VERDADEIRO, casa no MESMO livro.
    _importar(cliente, escola.id, joao, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "elefante_id": meta.id,
         "data": "2026-06-11T10:00:00"}])
    assert [l.id for l in _livros(db, escola.id)] == [livros[0].id]


# ---------------------------------------------------------------------------
# O parser do PDF aceita o vocabulário oficial inteiro (AA…Z, Z+ e A+)
# ---------------------------------------------------------------------------

def _pagina_estudante_com_tiers():
    from app.services.perfis_pdf import Pagina, Palavra

    def P(texto: str, x0: float, topo: float) -> Palavra:
        return Palavra(texto=texto, x0=x0, x1=x0 + 30.0, topo=topo)

    return [Pagina(numero=1, palavras=[
        P("Relatório", 40, 30), P("de", 92, 30), P("Performance", 106, 30),
        P("do", 172, 30), P("Estudante", 186, 30),
        P("01/02/2026", 40, 50), P("-", 100, 50), P("06/07/2026", 110, 50),
        P("ANA", 40, 70), P("BEATRIZ", 80, 70), P("SOUZA", 130, 70),
        P("9", 40, 85), P("ANO", 48, 85), P("Z", 70, 85), P("-", 80, 85),
        P("ESCOLA", 88, 85), P("MODELO", 130, 85),
        P("Q", 40, 100),
        P("Leituras", 15.7, 140), P("Concluídas", 58.0, 140),
        P("Tempo", 305.6, 140), P("de", 340.0, 140), P("Leitura", 354.0, 140),
        P("2", 15.7, 155), P("1:00:00", 305.6, 155),
        P("Histórico", 15.7, 200), P("de", 66.0, 200), P("Livros", 80.0, 200),
        P("Lidos", 115.0, 200),
        P("Tempo", 330.0, 230), P("de", 330.0, 242),
        P("Titulo", 15.7, 254), P("do", 47.0, 254), P("Livro", 62.0, 254),
        P("Nível", 180.0, 254), P("Gênero", 230.0, 254), P("Textual", 268.0, 254),
        P("Leitura", 330.0, 254), P("Data/Hora", 400.0, 254),
        # livro no tier Z+ e livro no tier A+ (24 livros do catálogo estão neles)
        P("O", 15.7, 280), P("Livro", 25.0, 280), P("Denso", 70.0, 280),
        P("Z+", 180.0, 280), P("Fantasia", 230.0, 280),
        P("0:30:00", 330.0, 280), P("01/07/2026", 400.0, 280),
        P("A", 15.7, 310), P("Cartilha", 25.0, 310),
        P("A+", 180.0, 310), P("Humor", 230.0, 310),
        P("0:30:00", 330.0, 310), P("02/07/2026", 400.0, 310),
    ])]


def test_pdf_do_estudante_le_os_niveis_oficiais_z_mais_e_a_mais():
    """O vocabulário oficial inclui Z+ e A+; o parser posicional recusava os dois
    (regex ``[A-Z]{1,2}``). O nível sumia da linha e um livro novo fora do
    catálogo era ignorado por "veio sem nível" — a leitura se perdia."""
    from app.services.perfis_pdf import PerfilElefanteEstudante

    analise = PerfilElefanteEstudante().analisar(_pagina_estudante_com_tiers())

    niveis = {l.dados.get("livro"): l.dados.get("nivel") for l in analise.linhas}
    assert niveis == {"O Livro Denso": "Z+", "A Cartilha": "A+"}
    assert [a for l in analise.linhas for a in l.avisos] == []


def test_codigo_de_nivel_do_pdf_segue_o_vocabulario_oficial():
    from app.services import perfis_pdf

    assert perfis_pdf._codigo_nivel("Z+") == "Z+"
    assert perfis_pdf._codigo_nivel("a+") == "A+"
    assert perfis_pdf._codigo_nivel("Z +") == "Z+"      # '+' em token separado
    assert perfis_pdf._codigo_nivel(" cc ") == "CC"
    for invalido in ("ZZ", "XY", "N5", "+", "Nível"):
        with pytest.raises(ValueError):
            perfis_pdf._codigo_nivel(invalido)
