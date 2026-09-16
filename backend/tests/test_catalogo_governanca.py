"""Governança do catálogo de livros do Elefante Letrado.

Regras do dono:
  * o catálogo é OFICIAL e somente leitura para a escola (professor, coordenador,
    admin da escola) e para a Secretaria — só o Admin Global cria, corrige nível
    ou título e exclui;
  * a correção vale para as PRÓXIMAS leituras: cada ``Leitura`` guarda o nível
    congelado do momento em que foi registrada, então o histórico e as notas
    gravadas não mudam — e nada de "recálculo pendente" genérico;
  * aplicar ao HISTÓRICO é ação explícita do Admin Global
    (``aplicar_ao_historico``), auditada com de/para e contagem, que reescreve o
    nível congelado daquele livro e recalcula a escola;
  * o id oficial do livro é a identidade: POST resolve o catálogo, a listagem
    mostra nível oficial, vínculo e divergência;
  * o script de vínculo é dry-run por padrão e nunca muda o nível efetivo.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Leitura, Livro, LogAuditoria, Nota, Rede, Usuario
from app.services import dificuldade_livro, scoring

API = "/api/v1"


def _login(email: str) -> TestClient:
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


def _usuario(db, escola, email: str, cargo: str, **extra) -> TestClient:
    db.add(Usuario(escola_id=escola.id, nome=email.split("@")[0], email=email,
                   senha_hash=hash_senha("s3nh4"), cargo=cargo, **extra))
    db.commit()
    return _login(email)


def _livro(db, escola, titulo: str = "O Mapa Perdido", nivel: str = "D", **extra) -> Livro:
    livro = Livro(escola_id=escola.id, titulo=titulo, nivel_codigo=nivel, **extra)
    db.add(livro)
    db.commit()
    return livro


def _oficial(titulo: str, nivel: str):
    meta = dificuldade_livro.catalogo().buscar(titulo, nivel)
    assert meta is not None and meta.nivel == nivel, (titulo, nivel)
    return meta


# --- Matriz de permissão -----------------------------------------------------------

@pytest.mark.parametrize("perfil", ["professor", "coordenador", "admin", "secretaria"])
def test_escola_e_secretaria_so_leem_o_catalogo(db, escola_completa, perfil):
    escola = escola_completa["escola"]
    livro = _livro(db, escola)
    if perfil == "secretaria":
        rede = Rede(nome="Rede Teste", status="ativa")
        db.add(rede)
        db.flush()
        escola.rede_id = rede.id
        cliente = _usuario(db, escola, "sec@catalogo.local", "coordenador", rede_id=rede.id)
    elif perfil == "admin":
        cliente = _login("admin@teste.local")
    else:
        cliente = _usuario(db, escola, f"{perfil}@catalogo.local", perfil)
    base = f"{API}/escolas/{escola.id}/livros"

    # LER continua liberado para quem já lia.
    assert cliente.get(base).status_code == 200

    respostas = [
        cliente.post(base, json={"titulo": "Livro Novo", "nivel_codigo": "D"}),
        cliente.patch(f"{base}/{livro.id}",
                      json={"nivel_codigo": "E", "motivo": "correção de nível"}),
        cliente.delete(f"{base}/{livro.id}"),
    ]
    for resposta in respostas:
        assert resposta.status_code == 403, resposta.text
    if perfil != "secretaria":
        assert all("somente leitura" in r.json()["detail"] for r in respostas)

    db.expire_all()
    assert db.get(Livro, livro.id).nivel_codigo == "D"
    assert db.execute(select(Livro).where(Livro.titulo == "Livro Novo")).first() is None


def test_admin_global_cria_corrige_e_exclui(cliente_global, escola_completa):
    base = f"{API}/escolas/{escola_completa['escola'].id}/livros"
    criado = cliente_global.post(base, json={"titulo": "O Mapa Perdido", "nivel_codigo": "d"})
    assert criado.status_code == 201, criado.text
    assert criado.json()["editavel"] is True

    alterado = cliente_global.patch(f"{base}/{criado.json()['id']}", json={"autor": "Rita Campos"})
    assert alterado.status_code == 200, alterado.text
    assert alterado.json()["autor"] == "Rita Campos"

    excluido = cliente_global.delete(f"{base}/{criado.json()['id']}")
    assert excluido.status_code == 200, excluido.text


# --- PATCH ----------------------------------------------------------------------------

def test_patch_vale_para_as_proximas_leituras_e_preserva_o_historico(
        cliente_global, db, escola_completa):
    """A correção NÃO reescreve o passado.

    Antes, a resposta dizia "recalculo_pendente" — um genérico que prometia que a
    nota mudaria no próximo recálculo. Com o NÍVEL CONGELADO na ``Leitura``, a
    leitura já registrada vale o nível do dia em que foi lida: o recálculo não
    muda nada dela. A resposta passa a dizer exatamente isso."""
    escola = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    livro = _livro(db, escola, "O Mapa Perdido", "D")
    for aluno in alunos[:2]:
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                       nivel_codigo="D"))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    ids = [a.id for a in alunos]

    def notas():
        db.expire_all()
        return {n.aluno_id: (n.nota_elefante, n.nota_geral)
                for n in db.execute(select(Nota).where(Nota.aluno_id.in_(ids))).scalars()}

    antes = notas()
    assert antes, "o recálculo inicial deveria gravar notas"

    url = f"{API}/escolas/{escola.id}/livros/{livro.id}"
    resposta = cliente_global.patch(url, json={
        "nivel_codigo": "Z", "motivo": "nível conferido no catálogo oficial"})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["nivel_codigo"] == "Z"
    assert corpo["vale_para_proximas_leituras"] is True
    assert corpo["historico_preservado"] is True
    assert corpo["leituras_atualizadas"] == 0
    assert corpo["leituras_sem_nivel_congelado"] == 0
    assert "PRÓXIMAS leituras" in corpo["aviso_correcao"]
    assert "recálculo" not in corpo["aviso_correcao"].lower()
    assert corpo["origem_nivel"] == "admin_global"
    assert corpo["atualizado_em"] is not None
    assert "recalculo_pendente" not in corpo         # o genérico saiu do contrato

    # O NÍVEL CONGELADO das leituras ficou intacto.
    db.expire_all()
    assert [l.nivel_codigo for l in db.execute(
        select(Leitura).where(Leitura.livro_id == livro.id)).scalars()] == ["D", "D"]

    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "livro.atualizado")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log.detalhes["de"] == {"nivel_codigo": "D"}
    assert log.detalhes["para"] == {"nivel_codigo": "Z"}
    assert log.detalhes["motivo"] == "nível conferido no catálogo oficial"
    assert log.detalhes["aplicar_ao_historico"] is False

    # Nem mesmo um recálculo explícito da escola muda o passado.
    assert cliente_global.post(f"{API}/escolas/{escola.id}/recalcular").status_code == 200
    assert notas() == antes

    # Título também vale daqui para a frente; um metadado sem efeito na nota, não.
    assert cliente_global.patch(
        url, json={"titulo": "O Mapa Perdido II"}).json()["vale_para_proximas_leituras"] is True
    sem_efeito = cliente_global.patch(url, json={"autor": "Rita"}).json()
    assert sem_efeito["vale_para_proximas_leituras"] is False
    assert sem_efeito["aviso_correcao"] is None
    assert notas() == antes


def test_leitura_antiga_sem_nivel_congelado_e_a_unica_ressalva(cliente_global, db,
                                                               escola_completa):
    """Leitura anterior ao congelamento (nível nulo) cai no nível ATUAL do livro.

    É a única coisa que a correção ainda move — e a resposta diz o número, em vez
    de prometer um "recálculo pendente" que valeria para tudo."""
    escola = escola_completa["escola"]
    livro = _livro(db, escola, "O Mapa Perdido", "D")
    db.add(Leitura(escola_id=escola.id, aluno_id=escola_completa["alunos"][0].id,
                   livro_id=livro.id))                      # legado: nivel_codigo nulo
    db.commit()

    corpo = cliente_global.patch(f"{API}/escolas/{escola.id}/livros/{livro.id}",
                                 json={"nivel_codigo": "Z", "motivo": "conferido"}).json()
    assert corpo["leituras_sem_nivel_congelado"] == 1
    assert corpo["historico_preservado"] is True
    assert "anteriores ao congelamento" in corpo["aviso_correcao"]


def test_aplicar_ao_historico_e_explicito_auditado_e_recalcula(cliente_global, db,
                                                               escola_completa, monkeypatch):
    """Retroagir é uma DECISÃO, não um efeito colateral: só com o campo explícito
    do Admin Global, com motivo, auditoria de/para e recálculo da escola."""
    escola = escola_completa["escola"]
    livro = _livro(db, escola, "O Mapa Perdido", "D")
    for aluno in escola_completa["alunos"][:2]:
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                       nivel_codigo="D"))
    db.commit()
    url = f"{API}/escolas/{escola.id}/livros/{livro.id}"

    recalculos: list[int] = []
    original = scoring.recalcular_escola
    monkeypatch.setattr(scoring, "recalcular_escola",
                        lambda sessao, eid, *a, **k: (recalculos.append(eid),
                                                      original(sessao, eid, *a, **k))[1])

    # Sem o campo, a correção não toca no histórico nem recalcula.
    assert cliente_global.patch(url, json={"nivel_codigo": "Z", "motivo": "conferido"}
                                ).json()["leituras_atualizadas"] == 0
    db.expire_all()
    assert all(l.nivel_codigo == "D" for l in db.execute(
        select(Leitura).where(Leitura.livro_id == livro.id)).scalars())
    assert recalculos == []

    # Aplicar ao histórico exige motivo…
    sem_motivo = cliente_global.patch(url, json={"aplicar_ao_historico": True})
    assert sem_motivo.status_code == 400
    assert "motivo" in sem_motivo.json()["detail"]

    # …e então reescreve o nível congelado daquele livro.
    corpo = cliente_global.patch(url, json={"aplicar_ao_historico": True,
                                            "motivo": "renivelamento aprovado pelo dono"}).json()
    assert corpo["leituras_atualizadas"] == 2
    assert corpo["historico_preservado"] is False
    assert "HISTÓRICO" in corpo["aviso_correcao"]
    assert recalculos == [escola.id]                       # a escola FOI recalculada

    db.expire_all()
    congelados = db.execute(select(Leitura).where(Leitura.livro_id == livro.id)).scalars().all()
    assert [l.nivel_codigo for l in congelados] == ["Z", "Z"]
    assert all(l.catalogo_versao for l in congelados)

    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.historico_renivelado")).scalars().one()
    assert log.detalhes["de"] == {"D": 2}
    assert log.detalhes["para"] == "Z"
    assert log.detalhes["leituras_atualizadas"] == 2
    assert log.detalhes["motivo"] == "renivelamento aprovado pelo dono"


def test_retroagir_sem_nada_a_reescrever_nao_diz_que_recalculou(cliente_global, db,
                                                                escola_completa, monkeypatch):
    """Pedido retroativo que não encontrou leitura fora do nível vigente.

    O recálculo só roda quando alguma leitura muda — então a mensagem não pode
    dizer "a escola foi recalculada". Diz o que aconteceu: nada."""
    escola = escola_completa["escola"]
    livro = _livro(db, escola, "O Mapa Perdido", "D")          # sem leitura nenhuma
    recalculos: list[int] = []
    monkeypatch.setattr(scoring, "recalcular_escola",
                        lambda sessao, eid, *a, **k: recalculos.append(eid))

    corpo = cliente_global.patch(
        f"{API}/escolas/{escola.id}/livros/{livro.id}",
        json={"aplicar_ao_historico": True, "motivo": "retroagir por segurança"}).json()
    assert corpo["leituras_atualizadas"] == 0
    assert corpo["historico_preservado"] is True               # o FATO: nada reescrito
    assert "não mudou nada" in corpo["aviso_correcao"]
    assert "recalculada" not in corpo["aviso_correcao"]
    assert recalculos == []

    # O pedido em si fica auditado, mesmo sem efeito.
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.historico_renivelado")).scalars().one()
    assert log.detalhes["leituras_atualizadas"] == 0


def test_corrigir_e_retroagir_na_MESMA_chamada_usa_o_nivel_novo(cliente_global, db,
                                                                escola_completa):
    """O uso natural: “o nível estava errado, corrija e vale para o que já passou”.

    Numa só chamada, o histórico tem de receber o nível NOVO (o da correção), não
    o antigo — e a leitura anterior ao congelamento (nível nulo) entra no de/para
    com o nome que ela tem: nunca esteve num nível, seguia o do livro."""
    escola = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    livro = _livro(db, escola, "O Mapa Perdido", "D")
    db.add(Leitura(escola_id=escola.id, aluno_id=alunos[0].id, livro_id=livro.id,
                   nivel_codigo="D"))
    db.add(Leitura(escola_id=escola.id, aluno_id=alunos[1].id, livro_id=livro.id))  # legado
    db.commit()

    corpo = cliente_global.patch(
        f"{API}/escolas/{escola.id}/livros/{livro.id}",
        json={"nivel_codigo": "G", "aplicar_ao_historico": True,
              "motivo": "nível errado desde a importação"}).json()
    assert corpo["nivel_codigo"] == "G"
    assert corpo["leituras_atualizadas"] == 2
    assert corpo["historico_preservado"] is False
    # Depois de retroagir não sobra leitura “sem nível congelado”, e a tela não
    # tem por que oferecer recálculo: o servidor já recalculou.
    assert corpo["leituras_sem_nivel_congelado"] == 0

    db.expire_all()
    assert sorted(l.nivel_codigo for l in db.execute(
        select(Leitura).where(Leitura.livro_id == livro.id)).scalars()) == ["G", "G"]
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.historico_renivelado")).scalars().one()
    assert log.detalhes["de"] == {"D": 1, "sem_nivel_congelado": 1}
    assert log.detalhes["para"] == "G"


def test_patch_valida_vocabulario_nulos_duplicidade_e_motivo(cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    livro = _livro(db, escola, "O Mapa Perdido", "D")
    _livro(db, escola, "A Casa Amarela", "E")
    url = f"{API}/escolas/{escola.id}/livros/{livro.id}"

    assert cliente_global.patch(url, json={"nivel_codigo": "ZZ", "motivo": "correção"}).status_code == 400
    assert cliente_global.patch(url, json={"titulo": None}).status_code == 422
    assert cliente_global.patch(url, json={"nivel_codigo": None}).status_code == 422
    assert cliente_global.patch(url, json={"titulo": "   "}).status_code == 422
    assert cliente_global.patch(url, json={"titulo": "a casa amarela"}).status_code == 409

    sem_motivo = cliente_global.patch(url, json={"nivel_codigo": "E"})
    assert sem_motivo.status_code == 400
    assert "motivo" in sem_motivo.json()["detail"]
    assert cliente_global.patch(url, json={"nivel_codigo": "E", "motivo": "ok"}).status_code == 400

    # Reenviar o MESMO nível não é mudança: não exige motivo nem avisa nada.
    igual = cliente_global.patch(url, json={"nivel_codigo": "d"})
    assert igual.status_code == 200, igual.text
    assert igual.json()["vale_para_proximas_leituras"] is False
    assert igual.json()["historico_preservado"] is True

    db.expire_all()
    atual = db.get(Livro, livro.id)
    assert (atual.titulo, atual.nivel_codigo) == ("O Mapa Perdido", "D")


# --- POST -----------------------------------------------------------------------------

def test_post_resolve_o_catalogo_oficial_e_respeita_homonimos(cliente_global, escola_completa):
    base = f"{API}/escolas/{escola_completa['escola'].id}/livros"

    cade_b = cliente_global.post(base, json={"titulo": "Cadê?", "nivel_codigo": "b"})
    assert cade_b.status_code == 201, cade_b.text
    meta_b = _oficial("Cadê?", "B")
    corpo = cade_b.json()
    assert (corpo["elefante_id"], corpo["word_count"], corpo["nivel_fonte"]) == (
        meta_b.id, meta_b.word_count, "B")
    assert corpo["origem_nivel"] == "fonte"
    assert corpo["no_catalogo"] is True and corpo["divergente"] is False

    # Homônimo OFICIAL em outro nível é outro livro — não é duplicata.
    cade_bb = cliente_global.post(base, json={"titulo": "Cadê?", "nivel_codigo": "BB"})
    assert cade_bb.status_code == 201, cade_bb.text
    assert cade_bb.json()["elefante_id"] == _oficial("Cadê?", "BB").id
    # O mesmo título no mesmo nível é duplicata.
    assert cliente_global.post(base, json={"titulo": "cadê?", "nivel_codigo": "B"}).status_code == 409

    # Nível diferente do oficial: vale como correção deliberada do Admin Global.
    laerte = cliente_global.post(base, json={"titulo": "Laerte, o Gato Inerte", "nivel_codigo": "D"})
    assert laerte.status_code == 201, laerte.text
    assert laerte.json()["origem_nivel"] == "admin_global"
    assert laerte.json()["nivel_oficial"] == "B"
    assert laerte.json()["divergente"] is True

    fora = cliente_global.post(base, json={"titulo": "Livro Só da Escola", "nivel_codigo": "K"})
    assert fora.status_code == 201, fora.text
    assert fora.json()["elefante_id"] is None and fora.json()["no_catalogo"] is False
    assert fora.json()["divergente"] is False

    assert cliente_global.post(base, json={"titulo": "Outro", "nivel_codigo": "ZZ"}).status_code == 400
    assert cliente_global.post(base, json={"titulo": "   ", "nivel_codigo": "D"}).status_code == 422


# --- GET ------------------------------------------------------------------------------

def test_listagem_mostra_governanca_e_filtra_divergentes(cliente, cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    meta = _oficial("Laerte, o Gato Inerte", "B")
    divergente = _livro(db, escola, "Laerte, o Gato Inerte", "D", elefante_id=meta.id,
                        nivel_fonte="B", origem_nivel="admin_global")
    _livro(db, escola, "O Mapa Perdido", "D")
    base = f"{API}/escolas/{escola.id}/livros"

    da_escola = cliente.get(base).json()
    assert da_escola["total"] == 2
    assert all(item["editavel"] is False for item in da_escola["itens"])
    item = next(i for i in da_escola["itens"] if i["id"] == divergente.id)
    assert item["no_catalogo"] is True and item["divergente"] is True
    assert item["nivel_oficial"] == "B" and item["word_count"] == meta.word_count
    assert item["origem_nivel"] == "admin_global"

    so_divergentes = cliente_global.get(base, params={"divergentes": "true"}).json()
    assert so_divergentes["total"] == 1
    assert so_divergentes["itens"][0]["id"] == divergente.id
    assert so_divergentes["itens"][0]["editavel"] is True


def test_nivel_do_relatorio_nunca_aparece_como_nivel_oficial(cliente_global, db,
                                                             escola_completa):
    """A última alavanca que sobraria para a escola: a COLUNA.

    Livro fora do catálogo não tem nível oficial. Quem grava o ``nivel_fonte``
    dele é o relatório — que a escola monta. Se a resposta chamasse esse número
    de "nível oficial", a escola plantaria na tela do Admin Global exatamente o
    nível que quer ver, e pediria a "correção". O campo oficial fica nulo; o
    número do relatório continua visível, com o nome certo, e a divergência
    continua sinalizada."""
    escola = escola_completa["escola"]
    fora = _livro(db, escola, "Livro Só da Escola", "D", nivel_fonte="Z")
    base = f"{API}/escolas/{escola.id}/livros"

    item = next(i for i in cliente_global.get(base).json()["itens"] if i["id"] == fora.id)
    assert item["no_catalogo"] is False
    assert item["nivel_oficial"] is None, "o nível do relatório não é oficial"
    assert item["nivel_fonte"] == "Z"
    assert item["divergente"] is True          # o sinal continua lá, sem a mentira
    assert cliente_global.get(base, params={"divergentes": "true"}).json()["total"] == 1

    # E o livro do CATÁLOGO continua com o nível oficial de verdade.
    meta = _oficial("Laerte, o Gato Inerte", "B")
    catalogado = _livro(db, escola, "Laerte, o Gato Inerte", "D", elefante_id=meta.id)
    item = next(i for i in cliente_global.get(base).json()["itens"] if i["id"] == catalogado.id)
    assert item["nivel_oficial"] == "B"


# --- Script de vínculo ----------------------------------------------------------------

def test_script_de_vinculo_e_dry_run_e_nunca_muda_o_nivel(db, escola_completa):
    from scripts import vincular_livros_catalogo as script

    escola = escola_completa["escola"]
    laerte = _livro(db, escola, "Laerte, o Gato Inerte", "F")   # vinculável, divergente
    cade = _livro(db, escola, "Cadê?", "C")                     # ambíguo (B e BB)
    local = _livro(db, escola, "Livro Só da Escola", "D")       # fora do catálogo
    meta = _oficial("Laerte, o Gato Inerte", "B")

    relatorio = script.analisar_escola(db, escola.id, escola.nome)
    assert [livro.id for livro, _ in relatorio.vinculaveis] == [laerte.id]
    assert [livro.id for livro, _ in relatorio.ambiguos] == [cade.id]
    assert [livro.id for livro in relatorio.fora_do_catalogo] == [local.id]
    assert [(livro.id, nivel) for livro, nivel in relatorio.divergencias] == [(laerte.id, "B")]
    db.expire_all()
    assert db.get(Livro, laerte.id).elefante_id is None          # dry-run não grava

    relatorio = script.analisar_escola(db, escola.id, escola.nome)
    assert script.aplicar(db, relatorio) == 1
    db.expire_all()
    vinculado = db.get(Livro, laerte.id)
    assert (vinculado.elefante_id, vinculado.word_count, vinculado.nivel_fonte) == (
        meta.id, meta.word_count, "B")
    assert vinculado.nivel_codigo == "F"                          # nível efetivo intocado
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.vinculado_catalogo")).scalars().all()
    assert len(logs) == 1 and logs[0].detalhes["qtd"] == 1       # auditoria agregada


# --- Origem do nível ------------------------------------------------------------------

def test_origem_do_nivel_nasce_legado_e_so_o_caminho_governado_carimba(
        cliente_global, db, escola_completa):
    """``origem_nivel`` default = ``legado``. Livro criado FORA dos caminhos
    governados (restauração de um backup anterior a esta governança, script,
    correção manual antiga) não pode sair carimbado como vindo da fonte oficial:
    a reconciliação seguinte auditaria ``origem_anterior='fonte'`` e o rastro da
    alteração local se perderia. Quem tem aval grava o valor explicitamente."""
    escola = escola_completa["escola"]
    solto = _livro(db, escola, "Livro Restaurado De Backup", "D")

    db.expire_all()
    assert db.get(Livro, solto.id).origem_nivel == "legado"

    base = f"{API}/escolas/{escola.id}/livros"
    item = next(i for i in cliente_global.get(base).json()["itens"] if i["id"] == solto.id)
    assert item["origem_nivel"] == "legado" and item["no_catalogo"] is False

    # Caminhos GOVERNADOS carimbam explicitamente (não dependem do default).
    do_catalogo = cliente_global.post(base, json={"titulo": "Cadê?", "nivel_codigo": "B"})
    assert do_catalogo.status_code == 201, do_catalogo.text
    assert do_catalogo.json()["origem_nivel"] == "fonte"
    corrigido = cliente_global.patch(f"{base}/{solto.id}",
                                     json={"nivel_codigo": "E", "motivo": "conferido"})
    assert corrigido.status_code == 200, corrigido.text
    assert corrigido.json()["origem_nivel"] == "admin_global"
