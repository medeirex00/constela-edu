"""Mundo SINTÉTICO da matriz de autorização (``test_rbac_matriz.py`` e
``test_rbac_bordas.py``). Não começa com ``test_``: o pytest não o coleta.

Nenhum dado real. Os nomes carregam MARCADORES impossíveis de confundir, então a
simples presença de um marcador no corpo da resposta (JSON, CSV, XLSX descompactado,
texto do PDF) prova o vazamento:

    REDE A (Secretaria sec_a; sec_prom = conta promovida do admin da escola X)
      ESCOLA X  — coord_x, admin_x, prof_t (titular da turma T)
         turma T  (prof_t)  -> "CRIANCA XT UM", "CRIANCA XT DOIS"
         turma T2 (prof_t2) -> "VAZAT2 CRIANCA UM"            (proibido ao prof_t)
      ESCOLA X2 — "VAZAX2 CRIANCA UM"                         (proibido a X)
    REDE B
      ESCOLA Y  — tudo com "VAZAY" (alunos, professor, usuários, revisão,
                  importação, alerta, log, conversa de IA, aviso, meta)

O banco do mundo é montado UMA vez por módulo (SQLite em memória) e cada chamada
recebe uma CÓPIA nova (``Banco``, via ``sqlite3.backup``): o que uma chamada escreve
não contamina a seguinte, e o retrato antes/depois permite ver escrita entre escolas.

Isolamento: conexões para fora do loopback e subprocessos são recusados, os
conectores reais (Elefante/Matific) viram falsos, e as pastas de arquivos da API
(UPLOADS_DIR/EXPORTS_DIR) apontam para uma pasta temporária — nada sai da máquina
nem suja o repositório. Ao fim do módulo tudo volta como estava (também os
``dependency_overrides`` do app).
"""
from __future__ import annotations

import io
import socket
import sqlite3
import subprocess
import zipfile
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import criar_token, hash_senha
from app.main import app
from app.models import (Aluno, Configuracao, ConversaIA, DispositivoMovel, Escola,
                        EventoAluno, IdentidadeExterna, Importacao, Leitura, Livro,
                        Matricula, MensagemIA, MetaRede, NivelDificuldade, Notificacao,
                        Professor, Rede, RevisaoIdentidade, SincronizacaoAlerta,
                        SincronizacaoExecucao, SincronizacaoLog, SnapshotElefante,
                        SnapshotMatific, Turma, Usuario)
from app.services import provisionamento, scoring

SENHA = "Sint3tica-Sonda-2026!"
# Dados RECENTES (este mês, este bimestre): os rankings/premiações por período não
# podem sair vazios, senão a checagem de vazamento deles não prova nada.
AGORA = datetime.now().replace(microsecond=0)
# Os seis perfis que a matriz chama (tokens emitidos no mundo).
PERFIS = ("global", "sec_a", "sec_prom", "coord_x", "admin_x", "prof_t")
# Token do painel público da escola X (o único painel ativo do mundo).
TOKEN_PAINEL_X = "tokXsint0001"

# ----------------------------------------------------------------------------- rede
_LOOP = ("127.0.0.1", "::1", "localhost", "testserver")
_conectar_original = socket.socket.connect
_criar_conexao_original = socket.create_connection


def _criar_conexao(endereco, *a, **k):
    if endereco[0] not in _LOOP:
        raise OSError(f"matriz RBAC: rede externa bloqueada ({endereco[0]})")
    return _criar_conexao_original(endereco, *a, **k)


def _so_loopback(self, endereco):
    host = endereco[0] if isinstance(endereco, tuple) else str(endereco)
    if host not in _LOOP:
        raise OSError(f"matriz RBAC: rede externa bloqueada ({host})")
    return _conectar_original(self, endereco)


def _sem_subprocesso(*a, **k):
    raise OSError("matriz RBAC: subprocesso bloqueado")


@pytest.fixture(scope="module", autouse=True)
def isolar_rbac(tmp_path_factory):
    """Rede, subprocessos, conectores reais e pastas de arquivos isolados durante o
    módulo; ``dependency_overrides`` do app restaurados no fim."""
    overrides_antes = dict(app.dependency_overrides)
    mp = pytest.MonkeyPatch()
    mp.setattr(socket.socket, "connect", _so_loopback)
    mp.setattr(socket, "create_connection", _criar_conexao)
    mp.setattr(subprocess, "Popen", _sem_subprocesso)
    pasta = tmp_path_factory.mktemp("rbac_arquivos")
    mp.setattr(settings, "UPLOADS_DIR", pasta / "uploads")
    mp.setattr(settings, "EXPORTS_DIR", pasta / "exports")
    from app.sync import aovivo, connectors, diagnostico_elefante, service
    from app.sync.interfaces import ResultadoValidacao

    class _ConectorFalso:
        def __init__(self, plataforma):
            self.plataforma = plataforma

        async def testar_credenciais(self, cred, ctx):
            return ResultadoValidacao(ok=False, mensagem="matriz", codigo="matriz")

    mp.setattr(connectors, "obter", lambda p: _ConectorFalso(p))
    mp.setattr(service, "disparar_em_thread", lambda _id: None)
    mp.setattr(aovivo, "placar_matific", lambda *a, **k: {"matriz": True})
    mp.setattr(diagnostico_elefante, "executar", lambda *a, **k: {"matriz": True})
    from app.services import geocodificacao
    app.dependency_overrides[geocodificacao.get_geocoder] = lambda: (lambda *a, **k: None)
    try:
        yield
    finally:
        mp.undo()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides_antes)


# ---------------------------------------------------------------------------- mundo
def _construir(s) -> dict:
    ids: dict = {}
    ra, rb = Rede(nome="REDE A SINT"), Rede(nome="REDE B VAZAY", token_publico="tokredeVAZAYsint01")
    s.add_all([ra, rb]); s.flush()
    ids.update(rA=ra.id, rB=rb.id)
    for k, nome, rede in (("X", "ESCOLA X SINT", ra.id), ("X2", "ESCOLA VAZAX2 SINT", ra.id),
                          ("Y", "ESCOLA VAZAY SINT", rb.id)):
        e = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede, cidade="Cidade Sint")
        s.add(e); s.flush()
        provisionamento.semear_config_inicial(s, e.id)
        ids["e" + k] = e.id
    s.add(MetaRede(rede_id=rb.id, metrica="media_geral", alvo=70.0, descricao="META VAZAY"))
    s.add(MetaRede(rede_id=ra.id, metrica="media_geral", alvo=60.0, descricao="meta a"))

    hs = hash_senha(SENHA)

    def usuario(ap, escola, cargo, nome=None, **kw):
        u = Usuario(escola_id=escola, nome=nome or ap.upper(), email=f"{ap}@sint.local",
                    senha_hash=hs, cargo=cargo, **kw)
        s.add(u); s.flush()
        ids["u_" + ap] = u.id
        return u

    usuario("global", ids["eX"], "admin", nome="GLOBAL SINT", is_global=True)
    usuario("sec_a", None, "coordenador", nome="SECRETARIA A SINT", rede_id=ra.id)
    # Conta PROMOVIDA a Secretaria a partir do admin da escola X: guarda cargo e escola_id.
    usuario("sec_prom", ids["eX"], "admin", nome="SECRETARIA PROMOVIDA SINT", rede_id=ra.id)
    usuario("coord_x", ids["eX"], "coordenador", nome="COORD X SINT")
    usuario("admin_x", ids["eX"], "admin", nome="ADMIN X SINT")
    usuario("prof_t", ids["eX"], "professor", nome="PROF T SINT")
    usuario("prof_t2", ids["eX"], "professor", nome="PROF T2 SINT")
    usuario("coord_x2", ids["eX2"], "coordenador", nome="COORD VAZAX2 SINT")
    usuario("prof_x2", ids["eX2"], "professor", nome="PROF VAZAX2 SINT")
    usuario("coord_y", ids["eY"], "coordenador", nome="COORD VAZAY SINT")
    usuario("admin_y", ids["eY"], "admin", nome="ADMIN VAZAY SINT")
    usuario("prof_y", ids["eY"], "professor", nome="PROF VAZAY SINT")

    profs = {}
    for k, esc, nome, email in (("T", "X", "PROF T SINT", "prof_t@sint.local"),
                                ("T2", "X", "PROF T2 SINT", "prof_t2@sint.local"),
                                ("X2", "X2", "PROF VAZAX2 SINT", "prof_x2@sint.local"),
                                ("Y", "Y", "PROF VAZAY SINT", "prof_y@sint.local")):
        p = Professor(escola_id=ids["e" + esc], nome=nome, email=email)
        s.add(p); s.flush()
        profs[k] = p
        ids["p" + k] = p.id

    turmas = {}
    for k, esc, nome in (("T", "X", "4º Ano A"), ("T2", "X", "4º Ano B"),
                         ("X2", "X2", "4º Ano A"), ("Y", "Y", "4º Ano A")):
        t = Turma(escola_id=ids["e" + esc], nome=nome, ano_escolar="4º Ano", ano_letivo=2026,
                  professor_id=profs[k].id, turno="manha")
        s.add(t); s.flush()
        turmas[k] = t
        ids["t" + k] = t.id

    livros = {}
    for esc in ("X", "X2", "Y"):
        lv = Livro(escola_id=ids["e" + esc], titulo=f"LIVRO {'VAZA' + esc if esc != 'X' else 'X'} SINT",
                   nivel_codigo="D")
        s.add(lv); s.flush()
        livros[esc] = lv
        ids["l" + esc] = lv.id

    imps = {}
    for esc, arq in (("X", "arq_x.pdf"), ("X2", "VAZAX2_ARQ.pdf"), ("Y", "VAZAY_ARQ.pdf")):
        im = Importacao(escola_id=ids["e" + esc], plataforma="elefante", tipo="pdf",
                        arquivo_original=arq, qtd_alunos=1, status="concluida",
                        created_at=AGORA - timedelta(days=3))
        s.add(im); s.flush()
        imps[esc] = im
        ids["imp" + esc] = im.id

    alunos = {}
    for k, esc, tk, nome in (("T_1", "X", "T", "CRIANCA XT UM"), ("T_2", "X", "T", "CRIANCA XT DOIS"),
                             ("T2_1", "X", "T2", "VAZAT2 CRIANCA UM"),
                             ("X2_1", "X2", "X2", "VAZAX2 CRIANCA UM"),
                             ("Y_1", "Y", "Y", "VAZAY CRIANCA UM"), ("Y_2", "Y", "Y", "VAZAY CRIANCA DOIS")):
        eid = ids["e" + esc]
        a = Aluno(escola_id=eid, nome=nome, data_nascimento=date(2017, 3, 1),
                  observacoes=f"OBS {nome}", da_lista_piloto=True)
        s.add(a); s.flush()
        alunos[k] = a
        ids["a" + k] = a.id
        s.add(Matricula(escola_id=eid, aluno_id=a.id, turma_id=turmas[tk].id, ano_letivo=2026))
        # Retrato ANTIGO (base) + retrato RECENTE: evolução e premiação têm crescimento.
        s.add(SnapshotElefante(escola_id=eid, aluno_id=a.id, importacao_id=imps[esc].id,
                               data_referencia=AGORA - timedelta(days=40), livros_unicos=1,
                               tempo_leitura_min=10, questoes_tentativas=2, questoes_acertos=1,
                               livros_por_nivel={"D": 1}))
        s.add(SnapshotMatific(escola_id=eid, aluno_id=a.id, importacao_id=imps[esc].id,
                              data_referencia=AGORA - timedelta(days=40), atividades=2,
                              estrelas=3, pontuacao_media=60.0))
        s.add(SnapshotElefante(escola_id=eid, aluno_id=a.id, importacao_id=imps[esc].id,
                               data_referencia=AGORA - timedelta(minutes=30), livros_unicos=3,
                               tempo_leitura_min=40, questoes_tentativas=10, questoes_acertos=7,
                               livros_por_nivel={"D": 3}))
        s.add(SnapshotMatific(escola_id=eid, aluno_id=a.id, importacao_id=imps[esc].id,
                              data_referencia=AGORA - timedelta(minutes=30), atividades=12,
                              estrelas=20, pontuacao_media=80.0))
        s.add(Leitura(escola_id=eid, aluno_id=a.id, livro_id=livros[esc].id,
                      data=AGORA - timedelta(minutes=30), tempo_leitura_min=10, nivel_codigo="D"))
        s.add(EventoAluno(escola_id=eid, aluno_id=a.id, importacao_id=imps[esc].id,
                          plataforma="elefante", tipo_evento="leitura",
                          ocorrido_em=AGORA - timedelta(minutes=30),
                          chave_natural=f"rbac-{k}", conteudo_titulo=livros[esc].titulo,
                          nivel_codigo="D", livro_id=livros[esc].id))
        s.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="elefante",
                                id_externo=f"ext-{k}"))
    for esc, marca in (("X", "x"), ("X2", "VAZAX2"), ("Y", "VAZAY")):
        eid = ids["e" + esc]
        rv = RevisaoIdentidade(escola_id=eid, chave=f"k-{esc}", chave_identidade=f"ki-{esc}",
                               plataforma="elefante", formato="resumo",
                               nome_recebido=f"{marca} REVISAO NOME", turma_informada="4A",
                               motivo="sem_candidato", importacao_id=imps[esc].id,
                               candidatos=[{"aluno_id": alunos[{'X': 'T_1', 'X2': 'X2_1', 'Y': 'Y_1'}[esc]].id,
                                            "nome": f"{marca} CANDIDATO"}],
                               linhas=[{"nome": f"{marca} LINHA"}])
        s.add(rv); s.flush()
        ids["rev" + esc] = rv.id
        ex = SincronizacaoExecucao(escola_id=eid, plataforma="elefante", origem="manual",
                                   status="falha", erro_resumo=f"{marca} ERRO EXEC",
                                   created_at=AGORA - timedelta(days=1))
        s.add(ex); s.flush()
        ids["exe" + esc] = ex.id
        s.add(SincronizacaoLog(execucao_id=ex.id, escola_id=eid, etapa="coleta", nivel="error",
                               mensagem=f"{marca} LOG MSG"))
        al = SincronizacaoAlerta(escola_id=eid, plataforma="elefante", tipo="falha",
                                 severidade="critico", mensagem=f"{marca} ALERTA MSG",
                                 execucao_id=ex.id)
        s.add(al); s.flush()
        ids["ale" + esc] = al.id
        s.add(Notificacao(escopo="escola", escola_id=eid, tipo="aluno_sem_leitura",
                          severidade="aviso", titulo=f"{marca} AVISO ESCOLA",
                          aluno_id=alunos[{'X': 'T2_1', 'X2': 'X2_1', 'Y': 'Y_1'}[esc]].id))
        nv = s.query(NivelDificuldade).filter_by(escola_id=eid).first()
        ids["niv" + esc] = nv.id if nv else 1
    s.add(Notificacao(escopo="rede", rede_id=rb.id, tipo="rede", severidade="info",
                      titulo="VAZAY AVISO REDE"))
    # Aviso nominal da criança de T2 (escola X): o professor da T não pode ver.
    s.add(Notificacao(escopo="escola", escola_id=ids["eX"], tipo="aluno_sem_leitura",
                      severidade="aviso", titulo="VAZAT2 CRIANCA UM sem leitura",
                      aluno_id=alunos["T2_1"].id))
    for ap, esc, marca in (("coord_x", "X", "conversa x"), ("prof_t2", "X", "VAZAT2 CONVERSA"),
                           ("coord_y", "Y", "VAZAY CONVERSA"), ("coord_x2", "X2", "VAZAX2 CONVERSA")):
        cv = ConversaIA(escola_id=ids["e" + esc], usuario_id=ids["u_" + ap], titulo=marca)
        s.add(cv); s.flush()
        s.add(MensagemIA(conversa_id=cv.id, papel="usuario", conteudo=f"{marca} PERGUNTA"))
        ids["conv_" + ap] = cv.id
    for ap, esc in (("prof_t2", "X"), ("coord_y", "Y"), ("coord_x2", "X2")):
        s.add(DispositivoMovel(escola_id=ids["e" + esc], usuario_id=ids["u_" + ap],
                               token_push=f"ExponentPushToken[{ap}VAZA]", plataforma="android"))
    # Painel público da X ativo (para o perfil público por token).
    s.add(Configuracao(escola_id=ids["eX"], namespace="painel_publico", chave="valores",
                       valor={"ativo": True, "token": TOKEN_PAINEL_X, "slides": ["ranking"],
                              "intervalo_s": 15, "max_posicoes": 10, "anonimizar": False}))
    s.commit()
    for esc in ("X", "X2", "Y"):
        scoring.recalcular_escola(s, ids["e" + esc])
    s.commit()
    return ids


def _engine_de(conn):
    eng = create_engine("sqlite://", creator=lambda: conn, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return eng


@pytest.fixture(scope="module")
def mundo(isolar_rbac):
    """O mundo montado uma vez por módulo: o banco-modelo, os ids e os tokens dos seis
    perfis."""
    modelo = sqlite3.connect(":memory:", check_same_thread=False)
    eng = _engine_de(modelo)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        ids = _construir(s)
        tokens = {}
        for ap in PERFIS:
            u = s.get(Usuario, ids["u_" + ap])
            tokens[ap] = criar_token(u.id, u.token_version or 0)
    finally:
        s.close()
    try:
        yield {"modelo": modelo, "ids": ids, "tokens": tokens}
    finally:
        app.dependency_overrides.pop(get_db, None)
        eng.dispose()
        modelo.close()


class Banco:
    """Cópia nova do mundo para UMA chamada (o app passa a usá-la em ``get_db``)."""

    def __init__(self, modelo):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        modelo.backup(self.conn)
        self.eng = _engine_de(self.conn)
        Sess = sessionmaker(bind=self.eng)

        def _get_db():
            s = Sess()
            try:
                yield s
            finally:
                s.close()
        app.dependency_overrides[get_db] = _get_db

    def retrato(self) -> dict:
        out = {}
        for (nome,) in self.conn.execute("select name from sqlite_master where type='table'"):
            cols = [r[1] for r in self.conn.execute(f'pragma table_info("{nome}")')]
            out[nome] = (cols, self.conn.execute(f'select * from "{nome}"').fetchall())
        return out

    def fechar(self):
        self.eng.dispose()
        self.conn.close()


def texto_da_resposta(resp) -> tuple[str, list[str]]:
    """Todo o texto legível da resposta, em MAIÚSCULAS (JSON/CSV/HTML, o XML de dentro de
    um XLSX, o texto de um PDF), e os problemas de leitura: um PDF que não se deixa ler
    é problema, senão a checagem de vazamento dele passaria sem ter lido nada."""
    bruto = resp.content or b""
    partes = [bruto.decode("utf-8", "ignore")]
    problemas: list[str] = []
    if bruto[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(bruto)) as z:
                for nome in z.namelist():
                    partes.append(z.read(nome).decode("utf-8", "ignore"))
        except zipfile.BadZipFile as exc:
            problemas.append(f"zip ilegível ({exc})")
    if bruto[:4] == b"%PDF":
        try:
            import pypdf
            leitor = pypdf.PdfReader(io.BytesIO(bruto))
            partes.extend((pg.extract_text() or "") for pg in leitor.pages)
        except Exception as exc:  # noqa: BLE001 — qualquer falha do leitor é "não li"
            problemas.append(f"pdf ilegível ({type(exc).__name__})")
    return "\n".join(partes).upper(), problemas
