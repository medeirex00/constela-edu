"""Robô legado de avaliações DESLIGADO por padrão e "evolução da rede" rotulada.

Achado 4 (auditoria de 20/10/2026): o robô de ``fontes_avaliacao`` grava números
sem prévia e roda embutido no agendador do sync — ligar o agendador o ligaria
junto. Agora só roda com ``AVALIACOES_ROBO_HABILITADO=true``.

Achado 9: a "evolução da rede (média por edição)" é uma média simples das
escolas calculada pelo Constela, que pode misturar números da importação oficial
(com prévia) e da manual/robô. A saída agora rotula a origem e separa por fonte.
"""
from datetime import timedelta

from app.core.config import Settings, settings
from app.models import (Escola, FonteAvaliacao, ImportacaoIndicador, Rede,
                        ResultadoAvaliacao)
from app.services import avaliacoes as svc

_PLANILHA = "\n".join(";".join(linha) for linha in [
    ["CO_ESCOLA", "IDEB_2023"], ["35012345", "6,1"]]).encode("utf-8")


def _fonte_vencida(db):
    rede = Rede(nome="Rede Teste", status="ativa")
    db.add(rede)
    db.flush()
    db.add(Escola(nome="EM Teste A", ano_letivo_ativo=2026, status="ativa",
                  rede_id=rede.id, codigo_inep="35012345"))
    av = svc.obter_avaliacao(db, "ideb")
    f = FonteAvaliacao(avaliacao_id=av.id, nome="IDEB teste",
                       url="https://download.inep.gov.br/ideb/x.csv", edicao=2023,
                       indicador="ideb", unidade="indice", cadencia="mensal", ativo=True,
                       mapeamento={"linha_dados": 1, "col_inep": 0, "col_valor": 1,
                                   "etapa_fixa": "anos_iniciais"},
                       proxima_coleta=svc._agora() - timedelta(days=1))
    db.add(f)
    db.commit()
    return f


def _robo(monkeypatch, valor):
    """Liga/desliga o robô pela FONTE ÚNICA (``settings``). ``setenv`` depois do
    import não chega lá — era assim que os testes do robô ligado passavam a ver
    o robô desligado e o caminho "ligado" deixou de ser exercitado."""
    monkeypatch.setattr(settings, "AVALIACOES_ROBO_HABILITADO", valor)


def test_robo_desligado_por_padrao_nao_coleta_nem_grava(db, monkeypatch):
    _robo(monkeypatch, Settings.model_fields["AVALIACOES_ROBO_HABILITADO"].default)
    f = _fonte_vencida(db)
    assert svc.robo_habilitado() is False
    baixou = []
    assert svc.coletar_pendentes(db, baixador=lambda url: baixou.append(url) or _PLANILHA) == 0
    assert baixou == []                                  # nem baixa
    assert db.query(ResultadoAvaliacao).count() == 0
    db.refresh(f)
    assert f.ultima_coleta is None and f.proxima_coleta is not None   # agenda intacta


def test_robo_so_roda_quando_ligado_explicitamente(db, monkeypatch):
    _robo(monkeypatch, "true")
    _fonte_vencida(db)
    assert svc.coletar_pendentes(db, baixador=lambda url: _PLANILHA) == 1
    assert db.query(ResultadoAvaliacao).count() == 1


def test_valores_aceitos_da_configuracao(monkeypatch):
    for valor, esperado in (("true", True), ("1", True), ("sim", True), (" SIM ", True),
                            ("false", False), ("", False), ("0", False),
                            ("talvez", False)):
        _robo(monkeypatch, valor)
        assert svc.robo_habilitado() is esperado, valor


def test_valor_do_ambiente_chega_ao_robo_e_valor_estranho_nao_derruba_o_boot(monkeypatch):
    """O caminho real: variável de ambiente → Settings (montado no boot) → robô.
    Com o campo bool, "sim" (que a lista de "ligado" aceita), "talvez" e o valor
    vazio levantavam ValidationError ao montar o Settings — a API não subia."""
    for valor, esperado in (("sim", True), ("true", True), ("talvez", False),
                            ("", False)):
        monkeypatch.setenv("AVALIACOES_ROBO_HABILITADO", valor)
        lido = Settings(_env_file=None).AVALIACOES_ROBO_HABILITADO   # não levanta
        _robo(monkeypatch, lido)
        assert svc.robo_habilitado() is esperado, valor


def test_ligar_o_agendador_nao_liga_o_robo(monkeypatch):
    """O ponto de entrada do agendador nem abre sessão de banco com o robô off."""
    from app.core import database
    from app.sync import scheduler

    _robo(monkeypatch, "false")

    def _nao_abra():
        raise AssertionError("o robô desligado não pode abrir sessão")

    monkeypatch.setattr(database, "SessionLocal", _nao_abra)
    scheduler._coletar_avaliacoes_pendentes()           # não levanta


# --------------------------------------------------------------------------
# Evolução da rede: rotulada como cálculo do Constela e separada por fonte
# --------------------------------------------------------------------------
def _escola(db, rede_id, nome, inep):
    e = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa", rede_id=rede_id,
               codigo_inep=inep)
    db.add(e)
    db.flush()
    return e


def test_evolucao_da_rede_e_rotulada_e_separada_por_fonte(db):
    rede = Rede(nome="Rede Evo", status="ativa")
    db.add(rede)
    db.flush()
    a = _escola(db, rede.id, "EM Evo A", "35000001")
    b = _escola(db, rede.id, "EM Evo B", "35000002")
    av = svc.obter_avaliacao(db, "saresp")
    imp = ImportacaoIndicador(
        avaliacao_id=av.id, parser="teste", parser_versao="1",
        fonte_nome="Fonte fictícia de teste", arquivo_nome="ficticio.csv",
        arquivo_sha256="0" * 64, arquivo_bytes=1, edicao_arquivo=2024,
        codigo_territorio_alvo="3500000", status="aplicada")
    db.add(imp)
    db.flush()
    # A: número da importação OFICIAL (com prévia); B: importação manual/robô.
    db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2024, rede_id=rede.id,
                              escola_id=a.id, codigo_inep="35000001", indicador="prof",
                              valor=200.0, unidade="pontos", importacao_id=imp.id))
    db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2024, rede_id=rede.id,
                              escola_id=b.id, codigo_inep="35000002", indicador="prof",
                              valor=100.0, unidade="pontos"))
    db.commit()

    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="saresp", indicador="prof",
                               edicao=2024)
    # O que já existia continua (nenhum dado válido removido)…
    assert corr["evolucao"] == [{"edicao": 2024, "media_valor": 150.0, "escolas": 2}]
    # …mas agora rotulado como cálculo do Constela, nunca como oficial…
    assert corr["evolucao_origem"] == "calculado_constela"
    assert "calculada pelo Constela" in corr["evolucao_rotulo"]
    assert "não é número oficial" in corr["evolucao_rotulo"]
    # …e separado por fonte.
    assert corr["evolucao_por_fonte"]["importacao_oficial"] == [
        {"edicao": 2024, "media_valor": 200.0, "escolas": 1}]
    assert corr["evolucao_por_fonte"]["sem_previa"] == [
        {"edicao": 2024, "media_valor": 100.0, "escolas": 1}]
    assert corr["serie_estimativa_constela"] is False


def test_serie_estimada_pelo_constela_e_marcada(db):
    rede = Rede(nome="Rede Est", status="ativa")
    db.add(rede)
    db.flush()
    e = _escola(db, rede.id, "EM Est", "35000003")
    av = svc.obter_avaliacao(db, "crianca_alfabetizada")
    db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2025, rede_id=rede.id,
                              escola_id=e.id, codigo_inep="35000003", etapa="2_ano",
                              indicador="taxa", valor=90.0, unidade="percentual"))
    db.commit()
    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="crianca_alfabetizada",
                               indicador="taxa", edicao=2025, etapa="2_ano")
    assert corr["serie_estimativa_constela"] is True
