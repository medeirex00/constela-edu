"""Snapshots manuais do Elefante/Matific: validação, governança e histórico.

  * chaves só do vocabulário oficial (AA…Z, Z+, A+) ou faixas da escola (400);
  * contagens inteiras de 0 a 10.000 (422); livros únicos < soma (400);
  * motivo obrigatório com pelo menos 5 caracteres (422);
  * integração do Elefante ATIVA: só o Admin Global ajusta (403 para a escola);
  * e — a trava que a escola NÃO desliga — EVIDÊNCIA HISTÓRICA de dado do
    Elefante vindo da plataforma também fecha o ajuste manual: apagar a
    credencial e desligar a agenda não reabre a edição;
  * média do Matific na edição manual até 5;
  * reimportar o mesmo período do Matific não empilha snapshot no mesmo fim.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (EventoAluno, Importacao, Leitura, Livro, LogAuditoria,
                        PlataformaCredencial, SincronizacaoConfig, SincronizacaoExecucao,
                        SnapshotElefante, SnapshotMatific, Usuario)
from app.services.audit import registrar

API = "/api/v1"
BASE = {"tempo_leitura_min": 30, "questoes_tentativas": 4, "questoes_acertos": 2,
        "motivo": "correção do relatório"}
MOTIVO = "dados informados pela professora"


def _put(cliente, escola_id: int, aluno_id: int, corpo: dict):
    return cliente.put(f"{API}/escolas/{escola_id}/elefante/{aluno_id}", json=corpo)


def _faixas(cliente, escola_id: int, aluno_id: int, corpo: dict):
    return cliente.put(f"{API}/escolas/{escola_id}/elefante/{aluno_id}/niveis", json=corpo)


def _coordenador(db, escola) -> TestClient:
    db.add(Usuario(escola_id=escola.id, nome="Coord", email="coord@snap.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login",
                            data={"username": "coord@snap.local", "password": "s3nh4"})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


def _ultimo_snapshot(db, aluno_id: int) -> SnapshotElefante | None:
    db.expire_all()
    return db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == aluno_id)
                      .order_by(SnapshotElefante.id.desc())).scalars().first()


# --- Elefante: PUT /elefante/{aluno_id} ------------------------------------------------

def test_snapshot_manual_aceita_so_vocabulario_oficial_ou_faixas(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    recusado = _put(cliente, escola.id, ana.id, {**BASE, "livros_por_nivel": {"ZZ": 2}})
    assert recusado.status_code == 400, recusado.text
    assert "desconhecida" in recusado.json()["detail"]
    assert _ultimo_snapshot(db, ana.id) is None                   # nada gravado

    aceito = _put(cliente, escola.id, ana.id,
                  {**BASE, "livros_por_nivel": {"d": 1, "Z+": 1, "pre_leitor": 2}})
    assert aceito.status_code == 200, aceito.text
    snap = _ultimo_snapshot(db, ana.id)
    assert snap.livros_por_nivel == {"D": 1, "Z+": 1, "pre_leitor": 2}
    assert snap.livros_unicos == 4


def test_snapshot_manual_contagens_inteiras_de_0_a_10000(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    for invalido in ({"D": -1}, {"D": 10001}, {"D": 1.5}, {"D": "muitos"}):
        resposta = _put(cliente, escola.id, ana.id, {**BASE, "livros_por_nivel": invalido})
        assert resposta.status_code == 422, (invalido, resposta.text)
    assert _put(cliente, escola.id, ana.id,
                {**BASE, "livros_unicos": -1, "livros_por_nivel": {}}).status_code == 422
    assert _ultimo_snapshot(db, ana.id) is None


def test_livros_unicos_menor_que_a_soma_das_contagens_e_recusado(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    menor = _put(cliente, escola.id, ana.id, {**BASE, "livros_unicos": 2, "livros_por_nivel": {"D": 3}})
    assert menor.status_code == 400, menor.text
    assert _ultimo_snapshot(db, ana.id) is None

    maior = _put(cliente, escola.id, ana.id, {**BASE, "livros_unicos": 5, "livros_por_nivel": {"D": 3}})
    assert maior.status_code == 200, maior.text
    assert maior.json()["livros_unicos"] == 5


def test_motivo_obrigatorio_com_pelo_menos_5_caracteres(cliente, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    sem_motivo = {k: v for k, v in BASE.items() if k != "motivo"}
    assert _put(cliente, escola.id, ana.id, sem_motivo).status_code == 422
    for motivo in (None, "", "ok", "     "):
        assert _put(cliente, escola.id, ana.id, {**BASE, "motivo": motivo}).status_code == 422
        assert _faixas(cliente, escola.id, ana.id,
                       {"faixas": {"pre_leitor": 1}, "motivo": motivo}).status_code == 422
    assert _faixas(cliente, escola.id, ana.id, {"faixas": {"pre_leitor": 1}}).status_code == 422


# --- Elefante: PUT /elefante/{aluno_id}/niveis -----------------------------------------

def test_faixas_validam_chaves_e_contagens_e_auditam_o_de(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    assert _put(cliente, escola.id, ana.id, {**BASE, "livros_por_nivel": {"D": 1}}).status_code == 200

    assert _faixas(cliente, escola.id, ana.id,
                   {"faixas": {"pre_leitor": -2}, "motivo": MOTIVO}).status_code == 422
    assert _faixas(cliente, escola.id, ana.id,
                   {"faixas": {"nivel_99": 1}, "motivo": MOTIVO}).status_code == 400

    ok = _faixas(cliente, escola.id, ana.id, {"faixas": {"pre_leitor": 3, "e": 1}, "motivo": MOTIVO})
    assert ok.status_code == 200, ok.text
    assert _ultimo_snapshot(db, ana.id).livros_por_nivel == {"pre_leitor": 3, "E": 1}
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "elefante.niveis_informados")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log.detalhes["de"] == {"livros_unicos": 1, "livros_por_nivel": {"D": 1}}
    assert log.detalhes["faixas"] == {"pre_leitor": 3, "E": 1}
    assert log.detalhes["motivo"] == MOTIVO


# --- Governança: integração ativa -------------------------------------------------------

def test_integracao_ativa_bloqueia_a_escola_e_libera_o_admin_global(cliente, cliente_global, db,
                                                                   escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    coordenador = _coordenador(db, escola)
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}
    faixas = {"faixas": {"pre_leitor": 2}, "motivo": MOTIVO}

    # Sem integração: o ajuste manual é da escola (é a única fonte do dado).
    assert _put(coordenador, escola.id, ana.id, corpo).status_code == 200

    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    for perfil in (coordenador, cliente):
        bloqueado = _put(perfil, escola.id, ana.id, corpo)
        assert bloqueado.status_code == 403, bloqueado.text
        assert "integração" in bloqueado.json()["detail"]
        assert _faixas(perfil, escola.id, ana.id, faixas).status_code == 403

    assert _put(cliente_global, escola.id, ana.id, corpo).status_code == 200
    assert _faixas(cliente_global, escola.id, ana.id, faixas).status_code == 200


def test_agenda_ligada_conta_como_integracao_e_credencial_invalida_nao(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    coordenador = _coordenador(db, escola)
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}

    agenda = SincronizacaoConfig(escola_id=escola.id, plataforma="elefante", ativo=True,
                                 cadencia="diaria")
    db.add(agenda)
    # A integração de OUTRA plataforma não governa o Elefante.
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="matific",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    assert _put(coordenador, escola.id, ana.id, corpo).status_code == 403

    agenda.ativo = False
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="invalida"))
    db.commit()
    assert _put(coordenador, escola.id, ana.id, corpo).status_code == 200


# --- Governança: EVIDÊNCIA HISTÓRICA (a trava que a escola não desliga) -------------------

def test_desligar_a_integracao_nao_reabre_o_ajuste_manual(cliente, cliente_global, db,
                                                          escola_completa):
    """A trava não pode depender de configuração que a própria escola desliga.

    Antes, o gatilho era só "integração ATIVA" — e a escola apaga a credencial e
    desliga a agenda em dois cliques, reabrindo a edição do dado oficial. Agora o
    gatilho é a EVIDÊNCIA HISTÓRICA: o log de auditoria da conexão
    (``sync.credencial_salva``), que nunca é apagado."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}

    credencial = PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                      segredo_cifrado="cifrado-de-teste", status="valida")
    db.add(credencial)
    agenda = SincronizacaoConfig(escola_id=escola.id, plataforma="elefante",
                                 ativo=True, cadencia="diaria")
    db.add(agenda)
    # A MARCA que o caminho real deixa ao conectar (``sync/router.salvar_credenciais``).
    registrar(db, "sync.credencial_salva", escola_id=escola.id,
              detalhes={"plataforma": "elefante"})
    db.commit()
    assert _put(cliente, escola.id, ana.id, corpo).status_code == 403

    # A escola desliga tudo o que ela controla…
    db.delete(credencial)
    agenda.ativo = False
    db.commit()

    # …e continua sem poder reescrever o dado oficial à mão.
    bloqueado = _put(cliente, escola.id, ana.id, corpo)
    assert bloqueado.status_code == 403, bloqueado.text
    assert "integração" in bloqueado.json()["detail"]
    assert _faixas(cliente, escola.id, ana.id,
                   {"faixas": {"pre_leitor": 2}, "motivo": MOTIVO}).status_code == 403
    # O Admin Global continua fazendo manutenção.
    assert _put(cliente_global, escola.id, ana.id, corpo).status_code == 200


def test_importacao_do_elefante_fecha_o_ajuste_manual_da_escola(cliente, db, escola_completa):
    """Dado do Elefante que chegou pela plataforma (importação/sincronização) é,
    sozinho, evidência suficiente — sem nenhuma credencial cadastrada."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}

    assert _put(cliente, escola.id, ana.id, corpo).status_code == 200   # antes: liberado

    importado = cliente.post(
        f"{API}/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "resumo", "tipo": "texto",
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                          "dados": {"livros_por_nivel": {"pre_leitor": 2}}}]})
    assert importado.status_code == 200, importado.text

    depois = _put(cliente, escola.id, ana.id, corpo)
    assert depois.status_code == 403, depois.text


def test_ajuste_manual_da_escola_nao_vira_evidencia_contra_ela(cliente, db, escola_completa):
    """A importação ``tipo="manual"`` é o registro do PRÓPRIO ajuste da escola —
    contá-la como evidência trancaria a porta no primeiro uso."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}
    for _ in range(3):
        assert _put(cliente, escola.id, ana.id, corpo).status_code == 200
    manuais = db.execute(select(Importacao).where(Importacao.plataforma == "elefante",
                                                  Importacao.tipo == "manual")).scalars().all()
    assert len(manuais) == 3


@pytest.mark.parametrize("marca", ["auditoria", "auditoria_importacao", "importacao",
                                   "evento", "leitura", "sincronizacao"])
def test_cada_marca_historica_do_elefante_fecha_o_ajuste(cliente, db, escola_completa, marca):
    """Todas as marcas que a plataforma deixa valem como evidência — a escola não
    apaga nenhuma delas por dentro do produto."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}
    assert _put(cliente, escola.id, ana.id, corpo).status_code == 200

    if marca == "auditoria":
        registrar(db, "livro.vinculado_catalogo", escola_id=escola.id,
                  detalhes={"qtd": 1})
    elif marca == "auditoria_importacao":
        # A marca que TODA importação deixa (``routers.importacoes.confirmar``).
        registrar(db, "importacao.concluida", escola_id=escola.id,
                  detalhes={"plataforma": "elefante", "tipo": "texto", "alunos": 1})
    elif marca == "importacao":
        db.add(Importacao(escola_id=escola.id, plataforma="elefante", tipo="texto"))
    elif marca == "evento":
        db.add(EventoAluno(escola_id=escola.id, aluno_id=ana.id, plataforma="elefante",
                           tipo_evento="leitura", ocorrido_em=datetime(2026, 5, 2, 10),
                           chave_natural=f"marca-{marca}"))
    elif marca == "leitura":
        livro = Livro(escola_id=escola.id, titulo="O Mapa Perdido", nivel_codigo="D")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id))
    else:
        db.add(SincronizacaoExecucao(escola_id=escola.id, plataforma="elefante",
                                     origem="scheduler", status="concluida"))
    db.commit()

    bloqueado = _put(cliente, escola.id, ana.id, corpo)
    assert bloqueado.status_code == 403, (marca, bloqueado.text)


def test_apagar_as_tabelas_restauraveis_nao_reabre_o_ajuste(cliente, db, escola_completa):
    """A evidência sobrevive a uma TROCA DE BASE.

    ``Importacao``, ``Leitura`` e ``EventoAluno`` estão no backup
    (``services.backup.MODELOS``): restaurar um arquivo apaga as linhas atuais da
    escola e põe as do arquivo no lugar. ``LogAuditoria`` não está — e é por isso
    que a marca de auditoria vem primeiro. Aqui o pior caso é simulado direto no
    banco: some tudo o que uma restauração levaria e o ajuste continua fechado."""
    from sqlalchemy import delete

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = {**BASE, "livros_por_nivel": {"D": 1}}

    importado = cliente.post(
        f"{API}/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "leituras", "tipo": "texto",
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                          "dados": {"livro": "O Mapa Perdido", "nivel": "D",
                                    "data": "2026-07-01T09:00:00"}}]})
    assert importado.status_code == 200, importado.text
    assert _put(cliente, escola.id, ana.id, corpo).status_code == 403

    # Mesma ordem da restauração (filhos antes dos pais, ``reversed(MODELOS)``).
    for modelo in (EventoAluno, Leitura, SnapshotElefante, SnapshotMatific, Importacao):
        db.execute(delete(modelo).where(modelo.escola_id == escola.id))
    db.commit()
    assert db.execute(select(Importacao).where(Importacao.escola_id == escola.id)
                      ).first() is None

    depois = _put(cliente, escola.id, ana.id, corpo)
    assert depois.status_code == 403, depois.text
    assert "integração" in depois.json()["detail"]


def test_a_escola_nao_marca_uma_importacao_como_manual(cliente, db, escola_completa):
    """A porta de escape óbvia está fechada no schema.

    ``tipo="manual"`` é o que isenta o ajuste da própria escola de virar
    evidência. Se o ``/importacoes/confirmar`` aceitasse esse tipo, bastaria
    carimbar o relatório do Elefante como "manual" para importar sem deixar
    marca. O schema só aceita pdf|texto|xlsx (422)."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    recusado = cliente.post(
        f"{API}/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "resumo", "tipo": "manual",
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                          "dados": {"livros_por_nivel": {"pre_leitor": 2}}}]})
    assert recusado.status_code == 422, recusado.text
    assert db.execute(select(Importacao).where(Importacao.escola_id == escola.id,
                                               Importacao.tipo == "manual")).first() is None


# --- Matific ------------------------------------------------------------------------------

def test_media_do_matific_na_edicao_manual_vai_ate_5(cliente, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    url = f"{API}/escolas/{escola.id}/matific/{ana.id}"
    corpo = {"atividades": 10, "estrelas": 20, "motivo": "correção manual"}
    assert cliente.put(url, json={**corpo, "pontuacao_media": 5.5}).status_code == 422
    assert cliente.put(url, json={**corpo, "pontuacao_media": 5}).status_code == 200


def test_media_ausente_preserva_a_do_snapshot_anterior(cliente, db, escola_completa):
    """Corrigir atividades/estrelas não pode obrigar a reescrever a MÉDIA.

    O formulário pré-carrega a média gravada e a reenvia. Num registro fora da
    escala atual (edição feita quando o limite era 100, ou base de demonstração)
    isso devolvia 422 e travava a correção — restando ao gestor digitar um valor
    ≤ 5, isto é, INVENTAR um número no lugar do medido. Sem o campo, o servidor
    preserva a média; informada, ela continua limitada a 0–5.
    """
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    url = f"{API}/escolas/{escola.id}/matific/{ana.id}"

    inicial = cliente.put(url, json={"atividades": 42, "estrelas": 15,
                                     "pontuacao_media": 4.4, "motivo": "carga inicial"})
    assert inicial.status_code == 200, inicial.text
    # Registro LEGADO fora da escala (só existe no banco: a API já não grava assim).
    legado = db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == ana.id)
                        .order_by(SnapshotMatific.id.desc())).scalars().first()
    legado.pontuacao_media = 87.5
    db.commit()

    resposta = cliente.put(url, json={"atividades": 45, "estrelas": 15,
                                      "motivo": "correção do relatório"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["atividades"] == 45
    assert resposta.json()["pontuacao_media"] == 87.5          # média medida preservada

    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "matific.editado")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log.detalhes["media_preservada"] is True
    assert log.detalhes["para"]["pontuacao_media"] == 87.5

    # Informar a média mantém o limite: ninguém grava média NOVA fora da escala.
    assert cliente.put(url, json={"atividades": 45, "estrelas": 15,
                                  "pontuacao_media": 5.5}).status_code == 422


def test_reimportar_periodo_do_matific_atualiza_o_snapshot_do_fim(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    corpo = {"plataforma": "matific", "formato": "resumo", "tipo": "pdf",
             "periodo_inicio": "2026-03-01", "periodo_fim": "2026-04-01",
             "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                         "dados": {"atividades": 50, "pontuacao_media": 4.1, "estrelas": 200}}]}
    url = f"{API}/escolas/{escola.id}/importacoes/confirmar"
    assert cliente.post(url, json=corpo).status_code == 200
    corpo["linhas"][0]["dados"]["estrelas"] = 210           # correção do relatório
    assert cliente.post(url, json=corpo).status_code == 200

    db.expire_all()
    fim = datetime(2026, 3, 31, 23, 59, 59)
    no_fim = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == ana.id,
        SnapshotMatific.data_referencia == fim)).scalars().all()
    assert len(no_fim) == 1                                   # sem duplicação silenciosa
    assert no_fim[0].estrelas == 210
    ultima = db.execute(select(Importacao).where(Importacao.plataforma == "matific")
                        .order_by(Importacao.id.desc())).scalars().first()
    assert no_fim[0].importacao_id == ultima.id               # rastreável à reimportação
    total = db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == ana.id)).scalars().all()
    assert len(total) == 2                                    # base da véspera + fim do período
