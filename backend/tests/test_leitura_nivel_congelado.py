"""NÍVEL CONGELADO da leitura: corrigir o catálogo não reescreve o passado.

Contrato desta rodada:

* toda Leitura criada na importação/sincronização nasce com
  ``nivel_codigo`` = o nível EFETIVO do livro NAQUELE momento (o OFICIAL do
  catálogo quando houve casamento — mesmo que o relatório da escola informe
  outro; a correção do Admin Global quando ela existe; o nível da linha já
  validado só para livro FORA do catálogo) e ``catalogo_versao`` = o mesmo
  carimbo de versão que a nota grava;
* a distribuição por nível do aluno lê
  ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)`` — leitura ANTIGA
  (nível nulo, anterior a esta versão) continua valendo pelo nível ATUAL do
  livro, e leitura congelada não muda quando o livro é renivelado;
* ``EventoAluno.nivel_codigo`` NÃO muda de semântica: segue sendo o nível da
  FONTE no instante do evento — coerente com o congelado porque vem da mesma
  resolução, mas quem PONTUA lê a leitura, não o evento.
"""
from sqlalchemy import select

from app.models import EventoAluno, Leitura, Livro, Nota, SnapshotElefante
from app.services import dificuldade_livro
from app.services import importacao as svc

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


def _leituras(db, aluno_id: int) -> list[Leitura]:
    db.expire_all()
    return db.execute(select(Leitura).where(Leitura.aluno_id == aluno_id)
                      .order_by(Leitura.id)).scalars().all()


def _distribuicao(db, aluno_id: int) -> dict:
    """``livros_por_nivel`` do snapshot MAIS RECENTE (cada importação grava um)."""
    db.expire_all()
    snap = db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == aluno_id)
                      .order_by(SnapshotElefante.id.desc())).scalars().first()
    assert snap is not None
    return dict(snap.livros_por_nivel or {})


def _livro(db, escola_id: int, titulo: str) -> Livro:
    db.expire_all()
    return db.execute(select(Livro).where(Livro.escola_id == escola_id,
                                          Livro.titulo == titulo)).scalars().one()


def test_leitura_importada_carimba_nivel_congelado_e_versao_do_catalogo(
        cliente, db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    meta = _oficial("Laerte, o Gato Inerte", "B")

    _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-10T10:00:00"}])

    leitura = _leituras(db, ana.id)[0]
    assert leitura.nivel_codigo == meta.nivel == "B"
    assert leitura.catalogo_versao == dificuldade_livro.versao_catalogo()["versao"]
    assert leitura.catalogo_versao  # o catálogo oficial está presente no repositório
    # Evento (espelho da fonte) nasce coerente com o congelado — mesma resolução.
    evento = db.execute(select(EventoAluno).where(
        EventoAluno.aluno_id == ana.id)).scalars().one()
    assert evento.nivel_codigo == leitura.nivel_codigo
    assert _distribuicao(db, ana.id) == {"B": 1}


def test_nivel_congelado_e_o_oficial_quando_o_relatorio_diverge_do_catalogo(
        cliente, db, escola_completa):
    """Relatório diz K, catálogo diz B: congela o OFICIAL (a escola controla o
    relatório — ele nunca é autoritativo)."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _oficial("Laerte, o Gato Inerte", "B")

    resultado = _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "K", "data": "2026-06-10T10:00:00"}])

    assert any("vale o oficial" in aviso for aviso in resultado["avisos"])
    leitura = _leituras(db, ana.id)[0]
    assert leitura.nivel_codigo == "B"            # não "K", o que o relatório mandou
    assert _livro(db, escola.id, "Laerte, o Gato Inerte").nivel_codigo == "B"
    assert _distribuicao(db, ana.id) == {"B": 1}


def test_fora_do_catalogo_congela_o_nivel_em_USO_e_nao_o_do_relatorio(
        cliente, db, escola_completa):
    """Livro que não está no catálogo oficial: a importação não renivela o livro
    da escola (governança), então o congelado é o nível EFETIVO em uso — uma
    planilha adulterada não consegue congelar um nível forjado."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    db.add(Livro(escola_id=escola.id, titulo="Livro Só Da Escola", nivel_codigo="D",
                 origem_nivel="legado"))
    db.commit()

    _importar(cliente, escola.id, ana, [
        {"livro": "Livro Só Da Escola", "nivel": "Z", "data": "2026-06-10T10:00:00"}])

    livro = _livro(db, escola.id, "Livro Só Da Escola")
    assert livro.nivel_codigo == "D" and livro.nivel_fonte == "Z"   # nível em uso preservado
    leitura = _leituras(db, ana.id)[0]
    assert leitura.nivel_codigo == "D"
    assert leitura.catalogo_versao == dificuldade_livro.versao_catalogo()["versao"]
    assert _distribuicao(db, ana.id) == {"D": 1}


def test_renivelar_o_livro_depois_nao_muda_a_distribuicao_na_reimportacao(
        cliente, db, escola_completa):
    """Admin Global renivela o livro DEPOIS da leitura: a reimportação recalcula
    o snapshot derivado e a leitura antiga continua no nível em que foi lida."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    linha = [{"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-10T10:00:00"}]
    _importar(cliente, escola.id, ana, linha)
    assert _distribuicao(db, ana.id) == {"B": 1}

    livro = _livro(db, escola.id, "Laerte, o Gato Inerte")
    livro.nivel_codigo = "K"                 # correção deliberada do Admin Global,
    livro.origem_nivel = "admin_global"      # PRESERVADA pela reconciliação da sync
    db.commit()

    _importar(cliente, escola.id, ana, linha)          # releitura não pontua (§35)

    assert _leituras(db, ana.id)[0].nivel_codigo == "B"
    assert _livro(db, escola.id, "Laerte, o Gato Inerte").nivel_codigo == "K"
    # Sem o congelamento isto teria virado {"K": 1} sozinho.
    assert _distribuicao(db, ana.id) == {"B": 1}


def test_leitura_antiga_sem_nivel_continua_valendo_pelo_nivel_do_livro(
        cliente, db, escola_completa):
    """Leitura anterior a esta versão (``nivel_codigo`` nulo, sem backfill): o
    fallback é o nível ATUAL do livro — e ele segue vivo se o livro mudar."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    antigo = Livro(escola_id=escola.id, titulo="Livro Antigo Da Escola",
                   nivel_codigo="D", origem_nivel="legado")
    db.add(antigo)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=antigo.id))
    db.commit()
    assert _leituras(db, ana.id)[0].nivel_codigo is None

    _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-10T10:00:00"}])
    assert _distribuicao(db, ana.id) == {"D": 1, "B": 1}

    antigo = _livro(db, escola.id, "Livro Antigo Da Escola")
    antigo.nivel_codigo = "E"
    db.commit()

    _importar(cliente, escola.id, ana, [
        {"livro": "O Circo", "nivel": "B", "data": "2026-06-11T10:00:00"}])

    # A leitura antiga (nível nulo) acompanha o livro; as congeladas, não.
    assert _distribuicao(db, ana.id) == {"E": 1, "B": 2}


def test_leitura_da_sync_pela_api_congela_o_nivel_oficial_do_id(cliente, db, escola_completa):
    """RECONFERÊNCIA: a sincronização automática do Elefante não tem um caminho
    próprio de gravação — ela monta a ``Analise`` e entrega ao MESMO ``confirmar``.
    Aqui o payload da API vem com o ``bookId`` oficial e um ``levelName`` errado:
    o que congela é o nível do CATÁLOGO, e o livro fica vinculado pelo id."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    meta = _oficial("Laerte, o Gato Inerte", "B")

    analise = svc.analisar_elefante_api({
        "courseSchoolDescriptors": {"courseName": "3º Ano A", "schoolName": "ESCOLA TESTE"},
        "leituras": [{"studentName": ana.nome, "bookTitle": "Laerte, o Gato Inerte",
                      "bookId": meta.id, "levelName": "K",
                      "lastReadWhen": "10/06/2026 10:00", "totalTimeSpent": 600}],
    })
    assert analise.formato == "leituras" and len(analise.linhas) == 1
    resposta = cliente.post(CONFIRMAR.format(eid=escola.id), json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": l.nome, "aluno_id": ana.id, "dados": l.dados}
                   for l in analise.linhas]})
    assert resposta.status_code == 200, resposta.text

    leitura = _leituras(db, ana.id)[0]
    assert leitura.nivel_codigo == meta.nivel == "B"      # não o "K" da API
    assert leitura.catalogo_versao == dificuldade_livro.versao_catalogo()["versao"]
    livro = _livro(db, escola.id, "Laerte, o Gato Inerte")
    assert livro.elefante_id == meta.id and livro.nivel_codigo == "B"
    assert _distribuicao(db, ana.id) == {"B": 1}


def test_versao_congelada_na_leitura_e_o_mesmo_carimbo_gravado_na_nota(
        cliente, db, escola_completa):
    """RECONFERÊNCIA do "mesmo carimbo da nota": a versão gravada na leitura tem
    de ser IDÊNTICA à que o motor carimba em
    ``Nota.detalhes.elefante.dificuldade.catalogo`` no recálculo da mesma
    importação — senão a auditoria não consegue casar nota e leitura."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _importar(cliente, escola.id, ana, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-10T10:00:00"}])

    db.expire_all()
    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)
                      .order_by(Nota.id.desc())).scalars().first()
    assert nota is not None
    carimbo = nota.detalhes["elefante"]["dificuldade"]["catalogo"]["versao"]
    assert carimbo
    assert _leituras(db, ana.id)[0].catalogo_versao == carimbo


def test_sem_arquivo_de_catalogo_a_versao_fica_nula_e_o_nivel_ainda_congela(
        cliente, db, escola_completa, monkeypatch):
    """RECONFERÊNCIA do contrato da coluna: sem catálogo em disco a versão é
    nula (a coluna é nula por contrato) e isso NÃO pode impedir o congelamento
    do nível nem derrubar a importação."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    db.add(Livro(escola_id=escola.id, titulo="Livro Só Da Escola", nivel_codigo="D",
                 origem_nivel="legado"))
    db.commit()
    monkeypatch.setattr(dificuldade_livro, "versao_catalogo",
                        lambda: {"versao": None, "n_livros": 0})

    _importar(cliente, escola.id, ana, [
        {"livro": "Livro Só Da Escola", "nivel": "D", "data": "2026-06-10T10:00:00"}])

    leitura = _leituras(db, ana.id)[0]
    assert leitura.catalogo_versao is None
    assert leitura.nivel_codigo == "D"
    assert _distribuicao(db, ana.id) == {"D": 1}


def test_quem_le_depois_da_correcao_do_admin_congela_o_nivel_corrigido(
        cliente, db, escola_completa):
    """RECONFERÊNCIA do caso (b): com ``origem_nivel='admin_global'`` a correção
    deliberada é o que PONTUA. Duas crianças, o MESMO livro, níveis congelados
    diferentes — cada leitura guarda o nível que valia quando ela aconteceu, e o
    relatório (que continua dizendo "B") não desfaz a correção."""
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    linha = [{"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-10T10:00:00"}]
    _importar(cliente, escola.id, ana, linha)

    livro = _livro(db, escola.id, "Laerte, o Gato Inerte")
    livro.nivel_codigo = "K"                 # correção deliberada do Admin Global
    livro.origem_nivel = "admin_global"
    db.commit()

    _importar(cliente, escola.id, joao, [
        {"livro": "Laerte, o Gato Inerte", "nivel": "B", "data": "2026-06-12T10:00:00"}])

    assert _livro(db, escola.id, "Laerte, o Gato Inerte").nivel_codigo == "K"  # preservada
    assert _leituras(db, ana.id)[0].nivel_codigo == "B"    # leu antes da correção
    assert _leituras(db, joao.id)[0].nivel_codigo == "K"   # leu depois
    assert _distribuicao(db, ana.id) == {"B": 1}
    assert _distribuicao(db, joao.id) == {"K": 1}
