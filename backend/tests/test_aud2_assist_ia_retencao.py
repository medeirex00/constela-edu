"""IA_RETENCAO_DIAS inválido (0 ou negativo) não apaga as conversas (G_SCRIPTS-8).

`purgar_conversas_ia_expiradas` calculava o corte como "agora - dias": com 0
apagava TODAS as conversas do assistente (inclusive a de 1 minuto atrás), no
boot e no `python -m scripts.purgar_ia`; com valor negativo, o corte ia para o
futuro. Nas variáveis RETENCAO_* vizinhas, 0 quer dizer "desligado" — a
armadilha é concreta. O prazo padrão (90 dias) não muda; só o valor inválido
deixa de apagar: a purga recusa, o boot de produção recusa e o de dev avisa.
Dados fictícios.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core import database
from app.core.config import Settings, avisos_de_configuracao, settings
from app.models import ConversaIA, MensagemIA
from app.services import assistente

_PG = "postgresql+psycopg://app@127.0.0.1:55432/config_retencao_ia_test"


def _conversas_recentes(db, escola_completa) -> None:
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    agora = datetime.now(timezone.utc)
    for titulo, idade in (("De 1 minuto", timedelta(minutes=1)),
                          ("De 1 hora", timedelta(hours=1))):
        conversa = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo=titulo,
                              created_at=agora - idade)
        db.add(conversa)
        db.flush()
        db.add(MensagemIA(conversa_id=conversa.id, papel="usuario", conteudo="oi"))
    db.commit()


def _total(db) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(ConversaIA)).scalar()


@pytest.mark.parametrize("dias", [0, -1, -30])
def test_purga_com_dias_invalido_recusa_e_nao_apaga(db, escola_completa, dias):
    _conversas_recentes(db, escola_completa)
    with pytest.raises(ValueError, match="IA_RETENCAO_DIAS"):
        assistente.purgar_conversas_ia_expiradas(db, dias=dias)
    assert _total(db) == 2


def test_purga_com_a_variavel_em_zero_nao_apaga(db, escola_completa, monkeypatch):
    _conversas_recentes(db, escola_completa)
    monkeypatch.setattr(settings, "IA_RETENCAO_DIAS", 0)
    with pytest.raises(ValueError, match="IA_RETENCAO_DIAS"):
        assistente.purgar_conversas_ia_expiradas(db)
    assert _total(db) == 2


def test_boot_com_a_variavel_em_zero_nao_apaga_e_segue(db, escola_completa, monkeypatch,
                                                       caplog):
    _conversas_recentes(db, escola_completa)
    monkeypatch.setattr(settings, "IA_RETENCAO_DIAS", 0)
    with caplog.at_level(logging.WARNING, logger="constela"):
        database._purgar_retencao_ia(db.get_bind())          # nunca derruba o boot
    assert _total(db) == 2
    assert "Purga de retenção de IA falhou no boot" in caplog.text


def test_prazo_valido_continua_apagando_so_o_vencido(db, escola_completa):
    _conversas_recentes(db, escola_completa)
    assert assistente.purgar_conversas_ia_expiradas(db, dias=1) == 0
    assert _total(db) == 2


def _settings(env: str, **extra) -> Settings:
    return Settings(_env_file=None, ENV=env, DATABASE_URL=_PG,
                    SECRET_KEY=f"sk-{secrets.token_urlsafe(40)}",
                    DATA_ENCRYPTION_KEY=f"dek-{secrets.token_urlsafe(40)}", **extra)


@pytest.fixture()
def sem_variaveis_do_processo(monkeypatch):
    for nome in ("ENV", "DATABASE_URL", "SECRET_KEY", "DATA_ENCRYPTION_KEY",
                 "DATA_ENCRYPTION_KEYS_ANTERIORES", "CHAVE_CIFRA_LEGADA_ANTERIOR",
                 "CORS_ORIGINS", "DOCS_HABILITADOS", "ADMIN_GLOBAL_EMAIL",
                 "METRICS_PUBLICO", "IA_RETENCAO_DIAS"):
        monkeypatch.delenv(nome, raising=False)


@pytest.mark.parametrize("dias", [0, -5])
def test_producao_recusa_o_boot_com_retencao_invalida(sem_variaveis_do_processo, dias):
    with pytest.raises(RuntimeError) as erro:
        _settings("producao", IA_RETENCAO_DIAS=dias)
    assert "IA_RETENCAO_DIAS" in str(erro.value)


def test_dev_avisa_da_retencao_invalida_e_o_padrao_nao_avisa(sem_variaveis_do_processo):
    avisos = avisos_de_configuracao(_settings("dev", IA_RETENCAO_DIAS=0))
    assert [a for a in avisos if "IA_RETENCAO_DIAS" in a], avisos
    padrao = _settings("producao")
    assert padrao.IA_RETENCAO_DIAS == 90 and padrao.riscos_de_producao() == []


def test_o_comando_de_purga_recusa_o_prazo_invalido_sem_traceback(monkeypatch, capsys):
    """G_SCRIPTS-8 (opcional): ``python -m scripts.purgar_ia`` com IA_RETENCAO_DIAS
    inválido diz o que corrigir e sai com código 2 — antes terminava com o traceback
    do ValueError no log do cron. Nada é apagado (a purga recusa antes do banco)."""
    from scripts import purgar_ia

    fechadas = []

    class _Sessao:
        def close(self):
            fechadas.append(True)

    monkeypatch.setattr(purgar_ia, "SessionLocal", _Sessao)
    monkeypatch.setattr(settings, "IA_RETENCAO_DIAS", 0)
    with pytest.raises(SystemExit) as saida:
        purgar_ia.main()
    assert saida.value.code == 2
    erro = capsys.readouterr().err
    assert "nada foi apagado" in erro and "IA_RETENCAO_DIAS" in erro
    assert fechadas == [True]
