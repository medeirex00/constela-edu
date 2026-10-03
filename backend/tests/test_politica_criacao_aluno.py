"""A sincronização não matricula ninguém: a política de fonte de verdade.

A sync entrega as linhas da plataforma ao MESMO pipeline do upload manual, e
esse pipeline cria a ficha da criança quando não acha candidato. Numa escola
cuja matrícula vem da Lista Piloto isso está errado na raiz, e o preço é alto:
um nome truncado pelo relatório ("ANNA E"), uma criança de outra unidade, ou um
RA divergente que VETA o candidato certo viram ficha ativa, sem RA e sem
nascimento, já pesando no ranking e na régua da escola. E não existe desfazer.

O que estes testes travam:
  * o DEFAULT é o comportamento de antes — escola sem política cria, como sempre;
  * com ``bloquear``, a sync não cria Aluno, nem Matrícula, nem IdentidadeExterna;
  * a linha bloqueada NÃO se perde: vira pendência de identidade com nome,
    plataforma, id externo, turma e motivo, e continua resolvível;
  * o upload manual e o cadastro pela tela seguem intactos;
  * casamento seguro continua associando — a política não torna tudo pendência.

Os nomes dos casos vêm da escola 11 (Debora Pilon), onde o dry-run real mostrou
7 criações: 5 pelo Elefante e 2 pelo Matific — estas com o nome TRUNCADO das
mesmas crianças, ou seja duplicidade nascendo dentro da própria execução.
"""
import pytest
from sqlalchemy import func, select

from app.models import (Aluno, Configuracao, IdentidadeExterna, Matricula,
                        RevisaoIdentidade, Turma)
from app.routers.importacoes import _confirmar_sem_commit
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import politica_sync

# As 5 que o Elefante criaria e as 2 que o Matific criaria (truncadas).
CINCO_ELEFANTE = ["ANA LUIZA SILVA DOS SANTOS", "ANNA ELOAH DE SOUZA MORAIS LEITE",
                  "ANTONHY BORGES DOS SANTOS", "ENZO LUCAS ALVES PRADO",
                  "MIGUEL BORGES DOS SANTOS"]
DUAS_MATIFIC = ["ANNA E", "ENZO L"]


def _usuario(db, escola_completa):
    return escola_completa["admin"]


def _confirmar(db, escola_completa, linhas, *, plataforma="elefante",
               permitir_criar_aluno=True, formato="resumo"):
    """Chama o NÚCLEO do /confirmar com os mesmos parâmetros da sincronização."""
    corpo = ImportacaoConfirm(
        plataforma=plataforma, formato=formato, tipo="texto",
        linhas=linhas, recalcular=False, sincronizar_turma=True,
        permitir_criar_turma=False,
        permitir_criar_aluno=permitir_criar_aluno)
    return _confirmar_sem_commit(dados=corpo, escola_id=escola_completa["escola"].id,
                                 usuario=_usuario(db, escola_completa), db=db)


def _linha(nome, turma, *, sid="9001", plataforma="elefante"):
    campo = "elefante_student_id" if plataforma == "elefante" else "matific_uuid"
    return LinhaConfirmacao(nome=nome, dados={
        campo: sid, "turma_relatorio": turma,
        "livros_unicos": 3, "tempo_leitura_min": 10,
        "atividades": 5, "estrelas": 12})


def _conta(db, modelo, **filtros):
    q = select(func.count()).select_from(modelo.__table__)
    for campo, valor in filtros.items():
        q = q.where(getattr(modelo, campo) == valor)
    return db.execute(q).scalar()


@pytest.fixture()
def cena(db, escola_completa):
    """Escola com a turma "3º Ano A" cadastrada — a turma do relatório EXISTE,
    que é justamente o caso em que hoje a ficha nasce."""
    return {"escola": escola_completa["escola"], "turma": escola_completa["turma"],
            "rotulo": escola_completa["turma"].nome}


# ---------------------------------------------------------------------------
# A política em si
# ---------------------------------------------------------------------------
def test_escola_sem_politica_permite_criar(db, escola_completa):
    """TESTE I — default = comportamento atual. Nada muda para quem não configurou."""
    eid = escola_completa["escola"].id
    assert politica_sync.obter(db, eid) == {"criar_aluno": "permitir"}
    assert politica_sync.pode_criar_aluno(db, eid) is True
    assert db.scalar(select(Configuracao).where(
        Configuracao.escola_id == eid,
        Configuracao.namespace == politica_sync.NAMESPACE)) is None


def test_definir_e_ler_a_politica(db, escola_completa):
    eid = escola_completa["escola"].id
    assert politica_sync.definir(db, eid, "bloquear") == {"criar_aluno": "bloquear"}
    db.commit()
    assert politica_sync.pode_criar_aluno(db, eid) is False
    politica_sync.definir(db, eid, "permitir")
    db.commit()
    assert politica_sync.pode_criar_aluno(db, eid) is True
    with pytest.raises(ValueError, match="Modo inválido"):
        politica_sync.definir(db, eid, "talvez")


def test_valor_corrompido_cai_no_padrao(db, escola_completa):
    """Configuração ilegível não pode, sozinha, mudar o comportamento da escola."""
    eid = escola_completa["escola"].id
    db.add(Configuracao(escola_id=eid, namespace=politica_sync.NAMESPACE,
                        chave=politica_sync.CHAVE, valor={"criar_aluno": "???"}))
    db.commit()
    assert politica_sync.pode_criar_aluno(db, eid) is True


# ---------------------------------------------------------------------------
# A trava no pipeline
# ---------------------------------------------------------------------------
def test_a_permitir_criar_mantem_o_comportamento_antigo(db, escola_completa, cena):
    """TESTE A — ALLOW_CREATE + sem correspondência → cria, como sempre."""
    antes = _conta(db, Aluno)
    _confirmar(db, escola_completa, [_linha("ANA LUIZA SILVA DOS SANTOS", cena["rotulo"])],
               permitir_criar_aluno=True)
    db.commit()
    assert _conta(db, Aluno) == antes + 1
    nova = db.execute(select(Aluno).where(
        Aluno.nome == "ANA LUIZA SILVA DOS SANTOS")).scalars().first()
    assert nova is not None and nova.da_lista_piloto is False


def test_b_c_d_bloquear_nao_cria_aluno_matricula_nem_identidade(db, escola_completa, cena):
    """TESTES B, C e D — nada nasce: nem ficha, nem matrícula, nem identidade."""
    antes = (_conta(db, Aluno), _conta(db, Matricula), _conta(db, IdentidadeExterna))
    _confirmar(db, escola_completa, [_linha("ANA LUIZA SILVA DOS SANTOS", cena["rotulo"],
                                            sid="7777")],
               permitir_criar_aluno=False)
    db.commit()
    assert (_conta(db, Aluno), _conta(db, Matricula),
            _conta(db, IdentidadeExterna)) == antes
    assert db.execute(select(Aluno).where(
        Aluno.nome == "ANA LUIZA SILVA DOS SANTOS")).scalars().first() is None
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "7777")).scalars().first() is None


def test_e_a_linha_bloqueada_vira_pendencia_auditavel(db, escola_completa, cena):
    """TESTE E — bloquear NÃO é descartar: a linha fica resolvível, com tudo.

    Sem isto a trava seria pior que o problema: a criança desapareceria do
    radar em vez de nascer com ficha errada."""
    _confirmar(db, escola_completa, [_linha("MIGUEL BORGES DOS SANTOS", cena["rotulo"],
                                            sid="5150")],
               permitir_criar_aluno=False)
    db.commit()
    rev = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert len(rev) == 1
    r = rev[0]
    assert r.status == "pendente"
    assert r.motivo == "criacao_bloqueada_por_politica"
    assert r.nome_recebido == "MIGUEL BORGES DOS SANTOS"
    assert r.plataforma == "elefante"
    assert r.id_externo == "5150"                  # o id externo NÃO se perde
    assert cena["rotulo"] in (r.turma_informada or "")


def test_f_correspondencia_segura_continua_associando(db, escola_completa, cena):
    """TESTE F — a política não transforma tudo em pendência: nome idêntico na
    sala segue casando normalmente."""
    aluno = escola_completa["alunos"][0]            # "Ana Beatriz Souza"
    _confirmar(db, escola_completa, [_linha(aluno.nome, cena["rotulo"], sid="4242")],
               permitir_criar_aluno=False)
    db.commit()
    assert db.scalar(select(func.count()).select_from(RevisaoIdentidade.__table__)) == 0
    ident = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "4242")).scalars().first()
    assert ident is not None and ident.aluno_id == aluno.id
    assert ident.status == "efetiva"


def test_g_pendencia_bloqueada_continua_resolvivel(db, escola_completa, cena):
    """TESTE G — a pendência não é um beco sem saída: o gestor resolve pela
    rota oficial, apontando a ficha certa."""
    aluno = escola_completa["alunos"][1]
    _confirmar(db, escola_completa, [_linha("ANTONHY BORGES DOS SANTOS", cena["rotulo"],
                                            sid="3131")],
               permitir_criar_aluno=False)
    db.commit()
    rev = db.execute(select(RevisaoIdentidade)).scalars().one()

    from app.routers.importacoes import resolver_revisao
    from app.schemas.importacao import ResolverRevisaoIn
    resolver_revisao(revisao_id=rev.id,
                     corpo=ResolverRevisaoIn(aluno_id=aluno.id),
                     escola_id=escola_completa["escola"].id,
                     usuario=escola_completa["admin"], db=db)
    db.expire_all()
    rev = db.get(RevisaoIdentidade, rev.id)
    assert rev.status == "resolvida"
    assert rev.aluno_escolhido_id == aluno.id
    ident = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "3131")).scalars().first()
    assert ident is not None and ident.aluno_id == aluno.id


def test_h_cadastro_manual_pela_tela_continua_funcionando(cliente, db, escola_completa):
    """TESTE H — a trava é do pipeline de sincronização. O gestor cadastrando
    uma criança na tela de Alunos não é afetado."""
    politica_sync.definir(db, escola_completa["escola"].id, "bloquear")
    db.commit()
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_completa['escola'].id}/alunos",
        json={"nome": "CRIANCA NOVA DA SECRETARIA",
              "turma_id": escola_completa["turma"].id})
    assert resposta.status_code in (200, 201), resposta.text
    assert db.execute(select(Aluno).where(
        Aluno.nome == "CRIANCA NOVA DA SECRETARIA")).scalars().first() is not None


def test_upload_manual_nao_e_afetado_pela_politica(db, escola_completa, cena):
    """O corpo do upload manual não manda a flag, então ela fica True — a
    política vale para a SYNC, que a envia explicitamente."""
    politica_sync.definir(db, escola_completa["escola"].id, "bloquear")
    db.commit()
    antes = _conta(db, Aluno)
    corpo = ImportacaoConfirm(          # igual ao que a tela envia
        plataforma="elefante", formato="resumo", tipo="texto",
        linhas=[_linha("ENZO LUCAS ALVES PRADO", cena["rotulo"], sid="8080")],
        recalcular=False)
    assert corpo.permitir_criar_aluno is True
    _confirmar_sem_commit(dados=corpo, escola_id=escola_completa["escola"].id,
                          usuario=escola_completa["admin"], db=db)
    db.commit()
    assert _conta(db, Aluno) == antes + 1


# ---------------------------------------------------------------------------
# Os 7 casos reais da escola 11
# ---------------------------------------------------------------------------
def test_k_elefante_nao_cria_as_cinco_fichas(db, escola_completa, cena):
    """TESTE K — as 5 do Elefante: zero criação, 5 pendências."""
    linhas = [_linha(nome, cena["rotulo"], sid=str(6000 + i))
              for i, nome in enumerate(CINCO_ELEFANTE)]
    antes = _conta(db, Aluno)
    _confirmar(db, escola_completa, linhas, permitir_criar_aluno=False)
    db.commit()
    assert _conta(db, Aluno) == antes
    for nome in CINCO_ELEFANTE:
        assert db.execute(select(Aluno).where(Aluno.nome == nome)).scalars().first() is None
    pend = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert len(pend) == 5
    assert {r.motivo for r in pend} == {"criacao_bloqueada_por_politica"}
    assert {r.nome_recebido for r in pend} == set(CINCO_ELEFANTE)


def test_j_matific_nao_cria_os_nomes_truncados(db, escola_completa, cena):
    """TESTE J — "ANNA E" e "ENZO L" são truncamentos das mesmas crianças: o
    sync criaria duplicidade dentro da própria execução."""
    linhas = [_linha(nome, cena["rotulo"], sid="u-%d" % i, plataforma="matific")
              for i, nome in enumerate(DUAS_MATIFIC)]
    antes = _conta(db, Aluno)
    _confirmar(db, escola_completa, linhas, plataforma="matific",
               permitir_criar_aluno=False)
    db.commit()
    assert _conta(db, Aluno) == antes
    for nome in DUAS_MATIFIC:
        assert db.execute(select(Aluno).where(Aluno.nome == nome)).scalars().first() is None
    pend = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert len(pend) == 2 and {r.plataforma for r in pend} == {"matific"}


def test_l_kemily_continua_virando_revisao_e_nao_ficha_nova(db, escola_completa, cena):
    """TESTE L — o caso que motivou tudo: nome ABREVIADO da plataforma contra o
    nome oficial completo. Já era revisão antes da política (candidato único,
    correspondência insegura) e tem de continuar sendo — a trava não pode
    transformar o caso dela em criação nem em associação arbitrária."""
    oficial = escola_completa["alunos"][2]
    oficial.nome = "KEMILY DA SILVA FERNANDES CARDOSO"
    oficial.da_lista_piloto = True
    db.commit()

    _confirmar(db, escola_completa,
               [_linha("KEMILY DA SILVA FERNANDES", cena["rotulo"], sid="4427532")],
               permitir_criar_aluno=False)
    db.commit()
    rev = db.execute(select(RevisaoIdentidade)).scalars().one()
    assert rev.motivo == "correspondencia_insegura"      # NÃO a trava: o motivo real
    assert rev.id_externo == "4427532"
    assert [c.get("aluno_id") for c in (rev.candidatos or [])] == [oficial.id]
    assert db.execute(select(Aluno).where(
        Aluno.nome == "KEMILY DA SILVA FERNANDES")).scalars().first() is None
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "4427532")).scalars().first() is None


# ---------------------------------------------------------------------------
# A sync consulta a política (integração do orquestrador)
# ---------------------------------------------------------------------------
def test_o_orquestrador_envia_a_flag_que_a_politica_manda(db, escola_completa,
                                                          monkeypatch):
    """A política só serve se a sincronização a consultar. Captura o
    ``ImportacaoConfirm`` que o orquestrador monta e confere a flag."""
    from app.sync import orchestrator
    from app.sync.interfaces import ArquivoObtido, Contexto

    capturado = {}

    def fake_confirmar(*, dados, escola_id, usuario, db):
        capturado["permitir_criar_aluno"] = dados.permitir_criar_aluno
        capturado["permitir_criar_turma"] = dados.permitir_criar_turma

        class R:
            qtd_alunos = 0
            qtd_erros = 0
            avisos: list = []
            ignorados: list = []
            importacao_id = None
            qtd_revisoes = 0
        return R()

    monkeypatch.setattr(orchestrator.imp, "confirmar", fake_confirmar)
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario",
                        lambda *a, **k: "tok")
    monkeypatch.setattr(orchestrator, "_parsear", lambda arq: (
        type("A", (), {"linhas": [type("L", (), {
            "nome": "ANA LUIZA SILVA DOS SANTOS",
            "dados": {"turma_relatorio": escola_completa["turma"].nome}})()],
            "plataforma": "elefante", "formato": "resumo",
            "turma_detectada": escola_completa["turma"].nome,
            "professor_detectado": "", "escola_detectada": ""})(), "texto"))

    arquivo = ArquivoObtido(conteudo=b"{}", nome_arquivo="x.json",
                            plataforma="elefante", formato_hint="resumo")
    ctx = Contexto(escola_id=escola_completa["escola"].id, execucao_id=None,
                   log=lambda *a: None, timeout_s=60, cancelado=lambda: False)

    orchestrator.aplicar_arquivo(db, escola_completa["escola"], arquivo,
                                 usuario_id=escola_completa["admin"].id,
                                 recalcular=False, contexto=ctx)
    assert capturado["permitir_criar_aluno"] is True     # sem política: como antes
    assert capturado["permitir_criar_turma"] is False

    politica_sync.definir(db, escola_completa["escola"].id, "bloquear")
    db.commit()
    orchestrator.aplicar_arquivo(db, escola_completa["escola"], arquivo,
                                 usuario_id=escola_completa["admin"].id,
                                 recalcular=False, contexto=ctx)
    assert capturado["permitir_criar_aluno"] is False    # com política: travado


# ---------------------------------------------------------------------------
# A rota de governança
# ---------------------------------------------------------------------------
def test_rota_le_grava_e_exige_admin_global(cliente, cliente_global, db,
                                            escola_completa):
    url = f"/api/v1/escolas/{escola_completa['escola'].id}/configuracoes/sincronizacao"

    assert cliente.get(url).json() == {"criar_aluno": "permitir"}
    # o admin da escola NÃO administra a fonte de verdade da matrícula
    assert cliente.put(url, json={"criar_aluno": "bloquear"}).status_code == 403

    ok = cliente_global.put(url, json={"criar_aluno": "bloquear",
                                       "motivo": "matricula vem da Lista Piloto"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"criar_aluno": "bloquear"}
    assert cliente.get(url).json() == {"criar_aluno": "bloquear"}

    assert cliente_global.put(url, json={"criar_aluno": "talvez"}).status_code == 422

    from app.models import LogAuditoria
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "sincronizacao.politica_alterada")).scalars().first()
    assert log is not None
    assert log.detalhes["de"] == {"criar_aluno": "permitir"}
    assert log.detalhes["para"] == {"criar_aluno": "bloquear"}
    assert log.detalhes["motivo"] == "matricula vem da Lista Piloto"


def test_politica_nao_toca_em_dado_nenhum(cliente_global, db, escola_completa):
    """Trocar a política é declaração, não migração: nada já gravado muda."""
    from app.models import Leitura, Nota
    antes = (_conta(db, Aluno), _conta(db, Matricula), _conta(db, Leitura),
             _conta(db, Nota), _conta(db, Turma), _conta(db, IdentidadeExterna))
    r = cliente_global.put(
        f"/api/v1/escolas/{escola_completa['escola'].id}/configuracoes/sincronizacao",
        json={"criar_aluno": "bloquear"})
    assert r.status_code == 200
    db.expire_all()
    assert (_conta(db, Aluno), _conta(db, Matricula), _conta(db, Leitura),
            _conta(db, Nota), _conta(db, Turma),
            _conta(db, IdentidadeExterna)) == antes


# ---------------------------------------------------------------------------
# Os casos que a revisão adversarial cobrou
# ---------------------------------------------------------------------------
def test_homonimo_vetado_nao_vira_candidato_mas_e_nomeado_no_aviso(db, escola_completa,
                                                                   cena):
    """CRIAR também dispara quando o motor ACHOU alguém de nome igual e o VETOU
    (RA divergente prova outra criança). Com a trava, essa linha não pode:

      * virar ficha (é o que acontecia antes);
      * virar associação (juntaria crianças diferentes);
      * nem chegar ao gestor como "nenhum aluno corresponde" — senão a tela
        convida a criar o que pode ser a terceira ficha da mesma criança.

    Então: pendência SEM candidato (correto — não há candidato seguro) e o
    homônimo vetado NOMEADO no aviso e no log."""
    homonimo = escola_completa["alunos"][0]
    homonimo.ficha = {"ra": "111111111-1"}
    db.commit()

    linha = LinhaConfirmacao(nome=homonimo.nome, dados={
        "elefante_student_id": "2525", "turma_relatorio": cena["rotulo"],
        "ra": "999999999-9", "livros_unicos": 2})
    antes = _conta(db, Aluno)
    nucleo = _confirmar(db, escola_completa, [linha], permitir_criar_aluno=False)
    db.commit()

    assert _conta(db, Aluno) == antes                     # nada nasceu
    rev = db.execute(select(RevisaoIdentidade)).scalars().one()
    assert rev.motivo == "criacao_bloqueada_por_politica"
    assert rev.candidatos == []                           # nenhum candidato SEGURO
    texto = " ".join(nucleo.avisos or [])
    assert homonimo.nome in texto and "DESCARTADO" in texto
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "2525")).scalars().first() is None


def test_sem_turma_conserva_o_motivo_proprio_mesmo_com_a_trava(db, escola_completa):
    """A trava NÃO pode roubar o diagnóstico de quem já tinha o seu. Linha com
    turma fora do cadastro continua sendo “turma_nao_cadastrada” — motivo e
    categoria de auditoria preservados, trava ligada ou não."""
    linha = LinhaConfirmacao(nome="CRIANCA DE TURMA DESCONHECIDA", dados={
        "elefante_student_id": "1212", "turma_relatorio": "9 ANO Z NOTURNO"},
        criar_em_turma_nome="9 ANO Z NOTURNO")
    _confirmar(db, escola_completa, [linha], permitir_criar_aluno=False)
    db.commit()
    rev = db.execute(select(RevisaoIdentidade)).scalars().one()
    assert rev.motivo == "turma_nao_cadastrada"
    assert _conta(db, Turma, escola_id=escola_completa["escola"].id) == 1


def test_get_da_politica_exige_cargo_como_os_outros_gets(cliente, db,
                                                         escola_completa):
    """Convenção do próprio arquivo: todo GET de configuração pede cargo."""
    from app.core.security import hash_senha
    from app.models import Usuario
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Prof",
                   email="prof@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="professor"))
    db.commit()
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    tok = c.post("/api/v1/auth/login",
                 data={"username": "prof@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    url = f"/api/v1/escolas/{escola_completa['escola'].id}/configuracoes/sincronizacao"
    assert c.get(url).status_code == 403
    assert cliente.get(url).status_code == 200
