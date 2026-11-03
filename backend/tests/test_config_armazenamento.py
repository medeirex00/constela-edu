"""Armazenamento: base configurável e diagnóstico de persistência.

Sem volume no Railway, UPLOADS_DIR/EXPORTS_DIR ficam no disco do contêiner e
somem a cada deploy. A base passa a ser configurável (DADOS_DIR; o volume do
Railway, se nada for declarado) sem mudar os nomes das pastas, e o diagnóstico
protegido diz se elas estão no volume.
"""
from pathlib import Path

import pytest

from app.core import armazenamento
from app.core.config import PROJECT_ROOT, Settings

_VARIAVEIS = ("UPLOADS_DIR", "EXPORTS_DIR", "DADOS_DIR", "RAILWAY_VOLUME_MOUNT_PATH",
              "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_ENVIRONMENT",
              "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")


@pytest.fixture
def ambiente_limpo(monkeypatch):
    for nome in _VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)
    return monkeypatch


def test_sem_nada_declarado_mantem_as_pastas_de_sempre(ambiente_limpo):
    s = Settings()
    assert s.UPLOADS_DIR == PROJECT_ROOT / "uploads"
    assert s.EXPORTS_DIR == PROJECT_ROOT / "exports"


def test_dados_dir_vira_a_base_das_duas_pastas(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path / "dados"))
    s = Settings()
    assert s.UPLOADS_DIR == tmp_path / "dados" / "uploads"
    assert s.EXPORTS_DIR == tmp_path / "dados" / "exports"


def test_volume_do_railway_so_vale_sem_dados_dir(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "vol"))
    assert Settings().UPLOADS_DIR == tmp_path / "vol" / "uploads"
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path / "dados"))
    assert Settings().UPLOADS_DIR == tmp_path / "dados" / "uploads"


def test_pasta_explicita_vence_tudo(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path / "dados"))
    ambiente_limpo.setenv("UPLOADS_DIR", str(tmp_path / "meus-uploads"))
    s = Settings()
    assert s.UPLOADS_DIR == tmp_path / "meus-uploads"
    assert s.EXPORTS_DIR == tmp_path / "dados" / "exports"


def test_diagnostico_no_volume_e_persistente(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("RAILWAY_SERVICE_ID", "servico-de-teste")
    ambiente_limpo.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path))
    d = armazenamento.diagnostico(Settings())
    assert d["persistente"] is True and d["volume"] == str(tmp_path)
    assert d["pastas"]["uploads"]["no_volume"] and d["pastas"]["exports"]["no_volume"]
    assert d["pastas"]["uploads"]["gravavel"] is True     # pode ser criada
    assert not d["avisos"]


def test_diagnostico_fora_do_volume_avisa(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("RAILWAY_SERVICE_ID", "servico-de-teste")
    ambiente_limpo.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "vol"))
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path / "dados"))   # volume no lugar errado
    d = armazenamento.diagnostico(Settings())
    assert d["persistente"] is False
    assert any("somem a cada deploy" in a for a in d["avisos"])


def test_diagnostico_no_railway_sem_volume_nao_e_persistente(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("RAILWAY_SERVICE_ID", "servico-de-teste")
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path))
    d = armazenamento.diagnostico(Settings())
    assert d["persistente"] is False and d["volume"] is None and d["no_railway"]


def test_diagnostico_fora_do_railway_e_desconhecido(ambiente_limpo, tmp_path):
    ambiente_limpo.setenv("DADOS_DIR", str(tmp_path))
    d = armazenamento.diagnostico(Settings())
    assert d["persistente"] is None and not d["no_railway"]


def test_gravavel_sobe_ate_a_pasta_existente(tmp_path):
    assert armazenamento._gravavel(tmp_path / "a" / "b" / "c") is True
    arquivo = tmp_path / "arquivo"
    arquivo.write_text("x", encoding="utf-8")
    assert armazenamento._gravavel(Path(arquivo) / "sub") is False   # pai não é pasta
