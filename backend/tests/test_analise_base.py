"""Fábricas dos testes da ANÁLISE EDUCACIONAL — dados INVENTADOS (decisão D13: nenhum
número oficial real, nenhum nome real; o município, os INEPs, as escolas, as crianças, as
datas e todos os valores são fictícios).

Os números oficiais entram direto nas tabelas que as importações oficiais gravam
(``importacoes_indicador``, ``indicadores_referencia`` e ``resultados_avaliacao``), no
formato que os pipelines produzem; a análise os lê pelas consultas oficiais. As
plataformas entram como a sincronização grava (retratos, leituras, livros).

Dois mundos:

* ``mundo_indicadores`` — uma rede com ICA, SARESP/IEE 2025, Ideb 2019–2023, Saeb e as
  estimativas à parte; escolas com e sem número, sem INEP, com TPS = 0;
* ``mundo_plataformas`` — por cima dele, turmas, crianças e coletas de 2026 (Elefante e
  Matific), com células pequenas para a supressão.
"""
from datetime import date, datetime

from app.models import (Aluno, Escola, Importacao, ImportacaoIndicador, IndicadorReferencia,
                        Leitura, Livro, Matricula, Rede, ResultadoAvaliacao, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.services import avaliacoes as svc_avaliacoes

MUN = "3599901"                 # IBGE INVENTADO (7 dígitos, UF 35)
MUN_VIZINHO = "3599902"
CODMUN = "9991"                 # CODMUN da SEDUC INVENTADO
UF = "35"
QUANDO_ARQUIVO = datetime(2026, 1, 12, 9, 0)
QUANDO_APLICADO = datetime(2026, 1, 13, 10, 0)
# "Hoje" dos testes: 5 dias depois da última coleta do mundo das plataformas (30/09) — a
# coleta está EM DIA (a tolerância é de 7 dias); a coleta parada tem teste próprio.
HOJE = date(2026, 10, 5)
PREFIXO_CRIANCA = "Criança Fictícia"

NOMES = {"alfa": "EMEF Fictícia Alfa", "beta": "EMEF Fictícia Beta",
         "delta": "EMEF Fictícia Delta", "gama": "EMEF Fictícia Gama",
         "ebano": "EMEF Ébano Fictícia"}
INEPS = {"alfa": "35990101", "beta": "35990102", "delta": "35990104", "gama": None,
         "ebano": "35990105"}


# --- Cadastro ------------------------------------------------------------------------

def nova_rede(db, nome="Rede Fictícia do Litoral", codigo=MUN, codmun=CODMUN) -> Rede:
    rede = Rede(nome=nome, uf="SP", codigo_ibge=codigo, codigo_municipio_estadual=codmun,
                status="ativa")
    db.add(rede)
    db.flush()
    return rede


def nova_escola(db, rede, nome, inep, ano=2026) -> Escola:
    escola = Escola(nome=nome, ano_letivo_ativo=ano, rede_id=rede.id if rede else None,
                    codigo_inep=inep)
    db.add(escola)
    db.flush()
    return escola


# --- Indicadores oficiais ---------------------------------------------------------------

def importacao(db, avaliacao, parser, edicao, *, resumo=None, alvo=MUN,
               nome="arquivo_ficticio.csv") -> ImportacaoIndicador:
    imp = ImportacaoIndicador(
        avaliacao_id=svc_avaliacoes.obter_avaliacao(db, avaliacao).id, parser=parser,
        parser_versao="1", fonte_nome="Fonte fictícia de teste", arquivo_nome=nome,
        arquivo_sha256="0" * 64, arquivo_bytes=1234, edicao_arquivo=edicao,
        codigo_territorio_alvo=alvo, status="aplicada", resumo=resumo or {},
        arquivo_data=QUANDO_ARQUIVO, aplicado_em=QUANDO_APLICADO, created_at=QUANDO_APLICADO,
        citacao="Dados fictícios de teste", licenca="—", modo="upload")
    db.add(imp)
    db.flush()
    return imp


def ref(db, avaliacao, imp, *, edicao, indicador, abrangencia="municipio", codigo=MUN,
        rede_ensino="municipal", valor=None, casas=None, motivo=None, etapa="",
        componente="", codigo_inep="", unidade="indice", operador=None,
        valor_detalhado=None, casas_detalhe=None, detalhe_imp=None) -> IndicadorReferencia:
    linha = IndicadorReferencia(
        avaliacao_id=svc_avaliacoes.obter_avaliacao(db, avaliacao).id, edicao=edicao,
        indicador=indicador, abrangencia=abrangencia, codigo_territorio=codigo,
        codigo_inep=codigo_inep, rede_ensino=rede_ensino, localizacao="total", etapa=etapa,
        componente=componente, valor=valor, casas_decimais=casas,
        motivo_ausencia=motivo if valor is None else None, unidade=unidade, operador=operador,
        valor_detalhado=valor_detalhado, casas_decimais_detalhe=casas_detalhe,
        detalhe_importacao_id=detalhe_imp.id if detalhe_imp else None,
        importacao_id=imp.id if imp else None)
    db.add(linha)
    db.flush()
    return linha


def resultado(db, avaliacao, escola, *, edicao, indicador, etapa, componente, valor=None,
              motivo=None, imp=None, unidade="escala_saresp") -> ResultadoAvaliacao:
    r = ResultadoAvaliacao(
        avaliacao_id=svc_avaliacoes.obter_avaliacao(db, avaliacao).id, edicao=edicao,
        rede_id=escola.rede_id, escola_id=escola.id, codigo_inep=None, etapa=etapa,
        componente=componente, indicador=indicador, valor=valor, unidade=unidade,
        motivo_ausencia=motivo if valor is None else None,
        fonte=None if imp else "Planilha fictícia — cálculo manual",
        importacao_id=imp.id if imp else None)
    db.add(r)
    db.flush()
    return r


def saresp_oficial(db, imp_iee, escola, edicao, *, lp5=None, mt5=None, lp2=None, mt2=None,
                   tps=1, iee=None, meta=None, icm=None, codigo=MUN):
    """O que o IEE grava para uma escola casada: a proficiência (as 4 células, com
    ``nao_divulgado`` na que falta), a participação, o TPS e o IEE/meta/ICM."""
    for etapa, comp, valor in (("5_ano", "portugues", lp5), ("5_ano", "matematica", mt5),
                               ("2_ano", "portugues", lp2), ("2_ano", "matematica", mt2)):
        resultado(db, "saresp", escola, edicao=edicao, indicador="proficiencia", etapa=etapa,
                  componente=comp, valor=valor, motivo="nao_divulgado", imp=imp_iee)
    inep = escola.codigo_inep
    for etapa in ("2_ano", "5_ano"):
        ref(db, "saresp", imp_iee, edicao=edicao, indicador="participacao",
            abrangencia="escola", codigo=codigo, codigo_inep=inep, etapa=etapa, valor=91.5,
            casas=1, unidade="percentual")
    ref(db, "saresp", imp_iee, edicao=edicao, indicador="tps", abrangencia="escola",
        codigo=codigo, codigo_inep=inep, valor=float(tps), casas=0, unidade="binario")
    for indicador, valor, casas in (("iee", iee, 2), ("meta", meta, 2), ("icm", icm, 0)):
        ref(db, "iee", imp_iee, edicao=edicao, indicador=indicador, abrangencia="escola",
            codigo=codigo, codigo_inep=inep, valor=None if valor is None else float(valor),
            casas=casas,
            motivo="nao_divulgado", unidade="binario" if indicador == "icm" else "indice")


def mundo_indicadores(db) -> dict:
    """A rede fictícia com os indicadores oficiais e as estimativas à parte."""
    rede = nova_rede(db)
    escolas = {k: nova_escola(db, rede, NOMES[k], INEPS[k]) for k in NOMES}

    # ICA (rede): 2023 participação baixa; 2024 empate com a meta (inconclusivo);
    # 2025 abaixo da meta; metas até 2026. SP e Brasil na rede pública (contexto).
    imp_ica = importacao(db, "ica", "inep_ica_municipios", 2025,
                         resumo={"territorios": {MUN: "Município Fictício"}})
    ref(db, "ica", imp_ica, edicao=2023, indicador="percentual_alfabetizado",
        motivo="participacao_baixa", unidade="percentual")
    ref(db, "ica", imp_ica, edicao=2024, indicador="percentual_alfabetizado", valor=55.0,
        casas=0, unidade="percentual")
    ref(db, "ica", imp_ica, edicao=2025, indicador="percentual_alfabetizado", valor=58.0,
        casas=0, unidade="percentual", valor_detalhado=58.37, casas_detalhe=2,
        detalhe_imp=imp_ica)
    for ed, meta in ((2024, 55.0), (2025, 60.0), (2026, 63.0)):
        ref(db, "ica", imp_ica, edicao=ed, indicador="meta", valor=meta, casas=0,
            unidade="percentual")
    ref(db, "ica", imp_ica, edicao=2025, indicador="percentual_alfabetizado",
        abrangencia="uf", codigo=UF, rede_ensino="publica", valor=61.0, casas=0,
        unidade="percentual")
    ref(db, "ica", imp_ica, edicao=2025, indicador="percentual_alfabetizado",
        abrangencia="brasil", codigo="BR", rede_ensino="publica", valor=57.0, casas=0,
        unidade="percentual")

    # SARESP 2025 (rede) e o IEE 2025 por escola (proficiência oficial + TPS + IEE).
    imp_mun = importacao(db, "saresp", "seduc_saresp_municipio", 2025,
                         resumo={"territorios": {MUN: "MUNICIPIO FICTICIO"}})
    for etapa, comp, valor in (("5_ano", "lp", 201.4), ("5_ano", "mt", 212.8),
                               ("2_ano", "lp", 150.2), ("2_ano", "mt", 160.9)):
        ref(db, "saresp", imp_mun, edicao=2025, indicador="proficiencia", etapa=etapa,
            componente=comp, valor=valor, casas=1, unidade="escala_saresp")
    ref(db, "saresp", imp_mun, edicao=2025, indicador="proficiencia", etapa="5_ano",
        componente="lp", abrangencia="uf", codigo=UF, valor=205.0, casas=1,
        unidade="escala_saresp")
    ref(db, "saresp", imp_mun, edicao=2025, indicador="proficiencia", etapa="5_ano",
        componente="lp", rede_ensino="estadual", valor=199.9, casas=1, unidade="escala_saresp")
    imp_iee = importacao(db, "iee", "seduc_iee", 2025, nome="iee_ficticio_2025-2026.csv")
    saresp_oficial(db, imp_iee, escolas["alfa"], 2025, lp5=210.3, mt5=220.1, lp2=155.5,
                   mt2=None, iee=5.12, meta=5.46, icm=0)
    saresp_oficial(db, imp_iee, escolas["beta"], 2025, lp5=190.7, mt5=199.0, tps=0,
                   iee=4.80, meta=4.50, icm=1)
    saresp_oficial(db, imp_iee, escolas["ebano"], 2025, lp5=205.5, mt5=208.4, iee=5.00,
                   meta=5.00, icm=1)
    # Delta: só a ESTIMATIVA (sem registro oficial) — nunca entra na série oficial.
    resultado(db, "saresp", escolas["delta"], edicao=2025, indicador="proficiencia",
              etapa="5_ano", componente="portugues", valor=233.3, imp=None)
    resultado(db, "crianca_alfabetizada", escolas["alfa"], edicao=2025,
              indicador="percentual", etapa="2_ano", componente=None, valor=61.0, imp=None,
              unidade="percentual")

    # Ideb da rede: metas do 1º ciclo só até 2021; 2023 sem meta. Brasil nas municipais.
    imp_terr = importacao(db, "ideb", "inep_ideb_municipios", 2023,
                          resumo={"territorios": {MUN: "MUNICIPIO FICTICIO"}})
    for ed, valor, meta in ((2019, 5.8, 5.8), (2021, 5.4, 6.0), (2023, 6.1, None)):
        ref(db, "ideb", imp_terr, edicao=ed, indicador="ideb", etapa="anos_iniciais",
            valor=valor, casas=1)
        if meta is not None:
            ref(db, "ideb", imp_terr, edicao=ed, indicador="meta", etapa="anos_iniciais",
                valor=meta, casas=1)
    ref(db, "ideb", imp_terr, edicao=2023, indicador="ideb", etapa="anos_iniciais",
        abrangencia="brasil", codigo="BR", valor=5.9, casas=1)
    # Saeb do 5º ano da rede (planilha, localização Total).
    imp_saeb = importacao(db, "saeb", "inep_saeb_planilha", 2021)
    for ed, lp, mt in ((2019, 215.25, 225.5), (2021, 210.0, 219.75)):
        for comp, valor in (("lp", lp), ("mt", mt)):
            ref(db, "saeb", imp_saeb, edicao=ed, indicador="proficiencia", etapa="5_ano",
                componente=comp, valor=valor, casas=2, unidade="escala_saeb")
    # Ideb e Saeb por escola (o arquivo do Ideb por escola): Alfa e Beta casadas; Delta
    # só com um número do 1 clique (sem registro oficial) em 2023.
    casadas = [{"escola_id": escolas[k].id, "codigo_inep": INEPS[k]}
               for k in ("alfa", "beta", "delta", "ebano")]
    imp_ideb = importacao(db, "ideb", "inep_ideb_escolas", 2023,
                          resumo={"edicoes": [2019, 2021, 2023], "anos_meta": [2019, 2021],
                                  "escolas_casadas": casadas})
    for k, serie_ideb in (("alfa", {2019: 5.9, 2021: 5.5, 2023: 6.3}),
                          ("beta", {2019: 5.1, 2021: None, 2023: 5.6})):
        for ed, valor in serie_ideb.items():
            resultado(db, "ideb", escolas[k], edicao=ed, indicador="ideb",
                      etapa="anos_iniciais", componente=None, valor=valor,
                      motivo="nao_divulgado", imp=imp_ideb, unidade="indice")
        for ed, meta in ((2019, 5.9), (2021, 6.1)):
            ref(db, "ideb", imp_ideb, edicao=ed, indicador="meta", abrangencia="escola",
                codigo_inep=INEPS[k], etapa="anos_iniciais", valor=meta, casas=1)
    for comp, valor in (("portugues", 218.31), ("matematica", 230.07)):
        resultado(db, "saeb", escolas["alfa"], edicao=2023, indicador="proficiencia",
                  etapa="5_ano", componente=comp, valor=valor, imp=imp_ideb,
                  unidade="escala_saeb")
    resultado(db, "ideb", escolas["delta"], edicao=2023, indicador="ideb",
              etapa="anos_iniciais", componente=None, valor=7.7, imp=None, unidade="indice")
    db.commit()
    return {"rede": rede, "escolas": escolas,
            "imps": {"ica": imp_ica, "saresp": imp_mun, "iee": imp_iee, "ideb_rede": imp_terr,
                     "saeb": imp_saeb, "ideb_escolas": imp_ideb}}


# --- Plataformas ------------------------------------------------------------------------

_contador = {"aluno": 0, "imp": 0}


def turma_com_alunos(db, escola, ano_escolar: str, n: int, *, nome_turma=None,
                     ano=2026) -> list[Aluno]:
    turma = Turma(escola_id=escola.id, nome=nome_turma or f"{ano_escolar} A",
                  ano_escolar=ano_escolar, ano_letivo=ano)
    db.add(turma)
    db.flush()
    alunos = []
    for _ in range(n):
        _contador["aluno"] += 1
        a = Aluno(escola_id=escola.id, nome=f"{PREFIXO_CRIANCA} {_contador['aluno']:04d}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ano))
        alunos.append(a)
    db.flush()
    return alunos


def livros(db, escola, quantos, nivel="K") -> list[Livro]:
    saida = []
    for i in range(quantos):
        livro = Livro(escola_id=escola.id, titulo=f"Livro Fictício {escola.id}-{nivel}-{i}",
                      nivel_codigo=nivel)
        db.add(livro)
        saida.append(livro)
    db.flush()
    return saida


def ler(db, escola, aluno, livros_lidos, quando, minutos=10):
    for livro in livros_lidos:
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id, data=quando,
                       tempo_leitura_min=minutos, nivel_codigo=livro.nivel_codigo))
    db.flush()


def _importacao(db, escola, plataforma) -> Importacao:
    imp = Importacao(escola_id=escola.id, usuario_id=None, plataforma=plataforma, tipo="seed",
                     arquivo_original=None, qtd_alunos=0, qtd_erros=0, tempo_ms=0,
                     status="concluida")
    db.add(imp)
    db.flush()
    return imp


def retrato_elefante(db, escola, aluno, quando, *, tentativas=0, acertos=0):
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=_importacao(db, escola, "elefante").id,
                            data_referencia=quando, livros_unicos=0, tempo_leitura_min=0,
                            questoes_tentativas=tentativas, questoes_acertos=acertos,
                            livros_por_nivel={}))
    db.flush()


def retrato_matific(db, escola, aluno, quando, *, atividades, estrelas):
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=_importacao(db, escola, "matific").id,
                           data_referencia=quando, atividades=atividades, estrelas=estrelas,
                           pontuacao_media=0.0))
    db.flush()


def mundo_plataformas(db, base: dict | None = None) -> dict:
    """Por cima do mundo dos indicadores: crianças e coletas de 2026.

    * ALFA: 2º ano com 4 crianças (célula pequena: suprimida), 3º ano com 7 (visível), 5º
      ano com 6 (suprimida em COMPLEMENTO, a menor visível: 4 + 6 = 10 alcança a faixa de
      proteção de 2k) e uma 1ª Fase com 4 (fora do recorte 1º–5º). Elefante e Matific com
      coleta em 2026;
    * BETA: 5º ano com 8 crianças, Matific com coleta, Elefante SEM coleta nenhuma (as
      métricas do Elefante ficam nulas — nunca 0);
    * Gama, Delta e Ébano: sem turma (0 alunos no recorte).
    """
    base = base or mundo_indicadores(db)
    alfa, beta = base["escolas"]["alfa"], base["escolas"]["beta"]
    turmas = {"alfa_2": turma_com_alunos(db, alfa, "2º Ano", 4),
              "alfa_3": turma_com_alunos(db, alfa, "3º Ano", 7),
              "alfa_5": turma_com_alunos(db, alfa, "5º Ano", 6),
              "alfa_fase": turma_com_alunos(db, alfa, "1ª Fase", 4),
              "beta_5": turma_com_alunos(db, beta, "5º Ano", 8)}
    # Elefante na ALFA, 3º ano: 5 crianças leem 8 livros novos em 2026 (níveis K, M, L);
    # uma 6ª leu em 2025 (fora do período); questões: 10 tentativas e 9 acertos cada.
    k, m, l_ = livros(db, alfa, 4, "K"), livros(db, alfa, 2, "M"), livros(db, alfa, 1, "L")
    t3 = turmas["alfa_3"]
    maio = datetime(2026, 5, 10, 14, 0)
    ler(db, alfa, t3[0], k[:3], maio)
    ler(db, alfa, t3[1], m, maio)
    ler(db, alfa, t3[2], k[:1], maio)
    ler(db, alfa, t3[3], l_, maio)
    ler(db, alfa, t3[4], k[:1], maio)
    ler(db, alfa, t3[5], k[:2], datetime(2025, 11, 3, 9, 0))
    for a in t3:
        retrato_elefante(db, alfa, a, datetime(2026, 3, 1, 3, 10), tentativas=10, acertos=5)
        retrato_elefante(db, alfa, a, datetime(2026, 9, 30, 3, 10), tentativas=20, acertos=14)
    # Matific na ALFA, 3º ano: 6 de 7 crianças com retrato (10 atividades, 30 estrelas).
    for a in t3[:6]:
        retrato_matific(db, alfa, a, datetime(2026, 4, 1, 3, 20), atividades=4, estrelas=10)
        retrato_matific(db, alfa, a, datetime(2026, 9, 30, 3, 20), atividades=10, estrelas=30)
    # As células pequenas também têm dado (que não pode aparecer).
    for a in turmas["alfa_2"] + turmas["alfa_5"]:
        retrato_elefante(db, alfa, a, datetime(2026, 9, 30, 3, 10), tentativas=4, acertos=4)
        retrato_matific(db, alfa, a, datetime(2026, 9, 30, 3, 20), atividades=77, estrelas=99)
    ler(db, alfa, turmas["alfa_2"][0], livros(db, alfa, 3, "Z"), maio)
    # BETA: só Matific (5 atividades e 12 estrelas por criança).
    for a in turmas["beta_5"]:
        retrato_matific(db, beta, a, datetime(2026, 9, 30, 3, 20), atividades=5, estrelas=12)
    db.commit()
    return {**base, "turmas": turmas}
