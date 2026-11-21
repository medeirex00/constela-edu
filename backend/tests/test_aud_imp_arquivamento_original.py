"""Arquivar o original na confirmação é MELHOR ESFORÇO (§15, ARMAZENAMENTO.md).

O ``/confirmar`` move o relatório de /temporarios para uploads/<plataforma>/. Um erro
de disco nesse passo (volume cheio, sem permissão, nome comprido demais para o
sistema de arquivos) não pode derrubar a importação com 500: os dados entram, o
original fica onde estava (o limpador de /temporarios o apaga) e o registro guarda só
o nome. O nome definitivo cabe num nome de arquivo do Linux (255 bytes), com a
extensão, e o registro cabe na coluna (500). Dados fictícios.
"""
import shutil
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.models import Importacao, SnapshotMatific

API = "/api/v1"


def _token(tmp_path, monkeypatch) -> tuple:
    uploads = tmp_path / "up"
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    (uploads / "temporarios").mkdir(parents=True)
    token = f"{uuid.uuid4().hex}.pdf"
    (uploads / "temporarios" / token).write_bytes(b"%PDF-1.4 relatorio ficticio")
    return uploads, token


def _confirmar(cliente, escola_completa, token, nome):
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    return cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "arquivo_token": token, "arquivo_nome": nome, "recalcular": False,
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"atividades": 12, "estrelas": 30}}]})


def test_disco_cheio_ao_arquivar_nao_derruba_a_importacao(cliente, db, escola_completa,
                                                          tmp_path, monkeypatch):
    uploads, token = _token(tmp_path, monkeypatch)

    def sem_espaco(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "move", sem_espaco)
    r = _confirmar(cliente, escola_completa, token, "Placar Ficticio.pdf")
    assert r.status_code == 200, r.text[:300]
    db.expire_all()
    imp = db.execute(select(Importacao)).scalars().one()
    assert db.execute(select(SnapshotMatific)).scalars().all(), "os dados não entraram"
    # Sem o arquivo arquivado, o registro não aponta para um caminho que não existe.
    assert imp.arquivo_original == "Placar Ficticio.pdf"
    assert (uploads / "temporarios" / token).exists()


def test_nome_longo_cabe_num_nome_de_arquivo_e_mantem_a_extensao(cliente, db,
                                                                 escola_completa,
                                                                 tmp_path, monkeypatch):
    uploads, token = _token(tmp_path, monkeypatch)
    # 150 letras, 100 delas acentuadas = 250 bytes em UTF-8, mais ".pdf"; o servidor
    # ainda prefixa "AAAAMMDD_HHMMSS_".
    nome = "Relatório individual " + "ção" * 50 + ".pdf"
    r = _confirmar(cliente, escola_completa, token, nome)
    assert r.status_code == 200, r.text[:300]
    db.expire_all()
    imp = db.execute(select(Importacao)).scalars().one()
    assert imp.arquivo_original.startswith("uploads/matific/")
    final = imp.arquivo_original.rsplit("/", 1)[-1]
    assert len(final.encode("utf-8")) <= 255, f"nome final de {len(final.encode())} bytes"
    assert final.endswith(".pdf")
    assert "Relatório individual ção" in final
    assert (uploads / "matific" / final).read_bytes() == b"%PDF-1.4 relatorio ficticio"
    assert not (uploads / "temporarios" / token).exists()


def test_nome_do_cliente_sem_arquivo_cabe_na_coluna(cliente, db, escola_completa):
    # Sem token (disco sem escrita na prévia), o registro guarda o nome que o
    # navegador mandou: cortado no tamanho da coluna (String(500)).
    r = _confirmar(cliente, escola_completa, None, "x" * 900 + ".pdf")
    assert r.status_code == 200, r.text[:300]
    db.expire_all()
    imp = db.execute(select(Importacao)).scalars().one()
    assert len(imp.arquivo_original) <= 500


def test_falha_no_meio_nao_deixa_o_original_orfao(cliente, db, escola_completa,
                                                   tmp_path, monkeypatch):
    """A importação que falha depois das recusas (aqui, um valor não numérico na 2ª
    linha: 400 no meio da gravação) desfaz o banco — e o original continua em
    /temporarios, não fica órfão em uploads/<plataforma>/ sem registro (com nomes de
    crianças, fora do limpador e da exclusão). O reenvio com o mesmo token arquiva."""
    uploads, token = _token(tmp_path, monkeypatch)
    eid = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    corpo = {
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "arquivo_token": token, "arquivo_nome": "Placar Ficticio.pdf",
        "data_referencia": "2026-08-14T12:00:00", "recalcular": False,
        "linhas": [
            {"nome": ana.nome, "aluno_id": ana.id, "dados": {"atividades": 5, "estrelas": 9}},
            {"nome": joao.nome, "aluno_id": joao.id, "dados": {"atividades": "abc"}},
        ]}
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json=corpo)
    assert r.status_code == 400, r.text
    db.expire_all()
    assert db.execute(select(Importacao)).scalars().all() == []
    orfaos = sorted(p.name for p in (uploads / "matific").glob("*")) if (
        uploads / "matific").exists() else []
    assert orfaos == [], f"original órfão em uploads/matific: {orfaos}"
    assert (uploads / "temporarios" / token).exists()

    corpo["linhas"][1]["dados"] = {"atividades": 3, "estrelas": 4}
    r2 = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json=corpo)
    assert r2.status_code == 200, r2.text
    db.expire_all()
    imp = db.execute(select(Importacao)).scalars().one()
    final = imp.arquivo_original.rsplit("/", 1)[-1]
    assert imp.arquivo_original.startswith("uploads/matific/")
    assert (uploads / "matific" / final).exists()
    assert not (uploads / "temporarios" / token).exists()


def test_falha_no_commit_nao_deixa_o_original_orfao(cliente, db, escola_completa,
                                                     tmp_path, monkeypatch):
    """O arquivo só sai de /temporarios depois que a importação está gravada: um erro
    no próprio commit (queda do banco, violação no fim da transação) também o deixa
    onde estava."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.main import app
    from app.routers import importacoes as rota

    uploads, token = _token(tmp_path, monkeypatch)
    commit_original = Session.commit
    nucleo_original = rota._confirmar_sem_commit
    importacao_gravada = []

    def nucleo_que_marca(**kw):
        nucleo = nucleo_original(**kw)
        importacao_gravada.append(nucleo.importacao_id)
        return nucleo

    def commit_que_cai(self):
        # Só o commit da importação (depois de o núcleo gravar a Importacao).
        if importacao_gravada:
            self.rollback()
            raise RuntimeError("banco caiu no commit (simulado)")
        return commit_original(self)

    monkeypatch.setattr(rota, "_confirmar_sem_commit", nucleo_que_marca)
    monkeypatch.setattr(Session, "commit", commit_que_cai)
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(cliente.headers)
    r = _confirmar(c, escola_completa, token, "Placar Ficticio.pdf")
    assert r.status_code == 500, r.text[:200]
    orfaos = sorted(p.name for p in (uploads / "matific").glob("*")) if (
        uploads / "matific").exists() else []
    assert orfaos == [], f"original órfão em uploads/matific: {orfaos}"
    assert (uploads / "temporarios" / token).exists()
