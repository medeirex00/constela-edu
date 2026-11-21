"""Desempenho das telas da Secretaria — o NÚMERO de consultas ao banco (em produção a API fica a
~195 ms do banco por consulta), sem mudar nenhum número.

* o painel da rede e os destaques leem os cartões das escolas em poucas consultas, as mesmas
  para qualquer número de escolas (antes: 22 e 21);
* a análise da escola só com as avaliações (``com_plataformas=False``, a ficha e a comparação
  da Secretaria) é a análise completa sem o bloco das plataformas;
* as leituras repetidas dos indicadores oficiais saem do banco uma vez dentro de
  ``leituras_da_requisicao`` e são as mesmas da consulta direta; fora dele, nada muda;
* dentro dele, também as linhas de ``indicadores_referencia`` (6 consultas viraram 1) e os
  ``resultados_avaliacao`` sem turma (3 viraram 1): o catálogo da rede e a análise só das
  avaliações caem para tetos menores, os mesmos para qualquer número de escolas, com a MESMA
  resposta da consulta direta;
* ``exigir_rede`` não lê a rede da própria Secretaria.

Dados INVENTADOS (``test_analise_base``; decisão D13).
"""
import pytest
from sqlalchemy import event

from app.services import rede as svc_rede
from app.services.analise import escola as svc_escola
from app.services.indicadores import leituras_da_requisicao as leituras
from tests.test_analise_base import HOJE, mundo_indicadores, mundo_plataformas, nova_escola


class _Contador:
    def __init__(self, db):
        self.engine, self.n = db.get_bind(), 0

    def _conta(self, *_a, **_k):
        self.n += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._conta)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._conta)


def _consultas(db, funcao) -> int:
    db.expire_all()
    with _Contador(db) as c:
        funcao()
    return c.n


def test_painel_e_destaques_com_o_mesmo_numero_de_consultas_para_qualquer_rede(db):
    base = mundo_plataformas(db)
    rede = base["rede"]
    rid = rede.id                       # (lido antes: o expire_all do teste o recarregaria)
    antes = {s: (_consultas(db, lambda s=s: svc_rede.dashboard_rede(db, rid, secretaria=s)),
                 _consultas(db, lambda s=s: svc_rede.destaques_rede(db, rid, secretaria=s)))
             for s in (True, False)}
    for i in range(5):
        nova_escola(db, rede, f"EMEF Fictícia Extra {i}", f"359901{70 + i}")
    db.commit()
    depois = {s: (_consultas(db, lambda s=s: svc_rede.dashboard_rede(db, rid, secretaria=s)),
                  _consultas(db, lambda s=s: svc_rede.destaques_rede(db, rid, secretaria=s)))
              for s in (True, False)}
    print(f"\npainel e destaques: {antes} -> com mais 5 escolas {depois} consultas")
    assert antes == depois
    # escolas, módulos e as DUAS leituras dos cartões (o painel junta as notas pendentes)
    assert all(painel <= 4 and destaques <= 4 for painel, destaques in depois.values())


def test_analise_so_das_avaliacoes_e_a_completa_sem_as_plataformas(db):
    base = mundo_plataformas(db)
    for escola in base["escolas"].values():
        for escopo in (True, False):
            completa = svc_escola.analise_da_escola(db, escola, hoje=HOJE, escopo_rede=escopo)
            n_completa = _consultas(db, lambda e=escola, x=escopo: svc_escola.analise_da_escola(
                db, e, hoje=HOJE, escopo_rede=x))
            n_so = _consultas(db, lambda e=escola, x=escopo: svc_escola.analise_da_escola(
                db, e, hoje=HOJE, escopo_rede=x, com_plataformas=False))
            so = svc_escola.analise_da_escola(db, escola, hoje=HOJE, escopo_rede=escopo,
                                              com_plataformas=False)
            assert so == {**completa, "plataformas": None}
            assert n_so < n_completa                     # a escola não é medida


def test_leituras_da_requisicao_sao_as_da_consulta_direta(db):
    base = mundo_indicadores(db)
    codigo = base["imps"]["ica"].codigo_territorio_alvo
    direto = (leituras.avaliacao(db, "saresp"), leituras.avaliacao(db, "nao_existe"),
              sorted(i.id for i in leituras.aplicadas_do_territorio(db, codigo, ("seduc_iee",))),
              sorted(e.id for e in leituras.escolas_da_rede(db, base["rede"].id)))
    with leituras.leituras_da_requisicao(db):
        with _Contador(db) as c:
            lote = (leituras.avaliacao(db, "saresp"), leituras.avaliacao(db, "nao_existe"),
                    sorted(i.id for i in leituras.aplicadas_do_territorio(db, codigo,
                                                                         ("seduc_iee",))),
                    sorted(e.id for e in leituras.escolas_da_rede(db, base["rede"].id)))
            for _ in range(3):                           # repetidas: da memória
                leituras.avaliacao(db, "ideb")
                leituras.aplicadas_do_territorio(db, codigo, ("inep_ideb_escolas",))
                leituras.escolas_da_rede(db, base["rede"].id)
        assert c.n == 3                                  # catálogo, importações, escolas
    assert lote == direto
    with _Contador(db) as c:                             # fora do bloco: consulta direta
        leituras.avaliacao(db, "saresp")
        leituras.avaliacao(db, "saresp")
    assert c.n == 2


def _sem_ids_de_objeto(valor):
    """A resposta comparável (as funções devolvem dicts e listas; nada de objeto ORM)."""
    import json
    return json.loads(json.dumps(valor, sort_keys=True, default=str))


def _linhas_que_ficam_de_fora(db, base):
    """Linhas que NENHUMA consulta de indicador lê — cada uma com a mesma chave (escola,
    edição, indicador, etapa) de um número que aparece e com um valor diferente. A consulta
    direta as tira no SQL; a leitura única as lê num superconjunto e as tira em Python: se um
    desses filtros sumir, o número muda e a equivalência quebra."""
    from app.models import IndicadorReferencia, ResultadoAvaliacao
    from app.services import avaliacoes as svc_avaliacoes
    from tests.test_analise_base import INEPS, MUN, resultado

    imps, alfa = base["imps"], base["escolas"]["alfa"]

    def referencia(avaliacao, imp, **campos):
        padrao = {"abrangencia": "municipio", "codigo_territorio": MUN, "codigo_inep": "",
                  "rede_ensino": "municipal", "localizacao": "total", "etapa": "",
                  "componente": "", "casas_decimais": 1, "unidade": "indice"}
        db.add(IndicadorReferencia(avaliacao_id=svc_avaliacoes.obter_avaliacao(db, avaliacao).id,
                                   importacao_id=imp.id, **{**padrao, **campos}))

    # Zona urbana (só "total" entra): o ICA e o SARESP do município, a participação da escola
    # no SARESP e a meta da escola no Ideb.
    referencia("ica", imps["ica"], edicao=2025, indicador="percentual_alfabetizado",
               localizacao="urbana", valor=11.0, casas_decimais=0, unidade="percentual")
    referencia("saresp", imps["saresp"], edicao=2025, indicador="proficiencia", etapa="5_ano",
               componente="lp", localizacao="urbana", valor=111.1, unidade="escala_saresp")
    referencia("saresp", imps["iee"], edicao=2025, indicador="participacao", abrangencia="escola",
               codigo_inep=INEPS["alfa"], etapa="5_ano", localizacao="urbana", valor=12.5,
               unidade="percentual")
    referencia("ideb", imps["ideb_escolas"], edicao=2021, indicador="meta", abrangencia="escola",
               codigo_inep=INEPS["alfa"], etapa="anos_iniciais", localizacao="urbana", valor=2.2)
    # A rede ESTADUAL no mesmo INEP (o Ideb da escola é só o da rede municipal).
    referencia("ideb", imps["ideb_escolas"], edicao=2019, indicador="meta", abrangencia="escola",
               codigo_inep=INEPS["alfa"], etapa="anos_iniciais", rede_ensino="estadual", valor=1.1)
    # Resultados de UMA TURMA (só os sem turma entram), no SARESP, no Ideb e no Saeb.
    for avaliacao, edicao, indicador, etapa, componente, valor, imp, unidade in (
            ("saresp", 2025, "proficiencia", "5_ano", "portugues", 999.9, imps["iee"],
             "escala_saresp"),
            ("ideb", 2023, "ideb", "anos_iniciais", None, 9.9, imps["ideb_escolas"], "indice"),
            ("saeb", 2023, "proficiencia", "5_ano", "portugues", 333.3, imps["ideb_escolas"],
             "escala_saeb")):
        db.add(ResultadoAvaliacao(
            avaliacao_id=svc_avaliacoes.obter_avaliacao(db, avaliacao).id, edicao=edicao,
            rede_id=alfa.rede_id, escola_id=alfa.id, etapa=etapa, componente=componente,
            turma="A", indicador=indicador, valor=valor, unidade=unidade, importacao_id=imp.id))
    # O Ideb da escola é o geral (sem componente): um com componente fica de fora.
    resultado(db, "ideb", alfa, edicao=2021, indicador="ideb", etapa="anos_iniciais",
              componente="LP", valor=8.8, imp=imps["ideb_escolas"], unidade="indice")
    db.flush()


@pytest.mark.parametrize("com_linhas_de_fora", [False, True])
def test_indicadores_dentro_da_leitura_unica_sao_os_da_consulta_direta(db, com_linhas_de_fora):
    """ICA, SARESP, Ideb da rede, o catálogo, cada indicador (série e escolas) e a análise de
    cada escola: dentro de ``leituras_da_requisicao`` (as referências e os resultados lidos
    uma vez, filtrados em Python) a MESMA resposta da consulta direta, campo a campo. Com
    ``com_linhas_de_fora``, o banco tem também as linhas que cada filtro tira (turma, zona
    urbana, rede estadual, componente) — a equivalência depende de cada filtro."""
    from app.services.analise import indicadores as svc_ind
    from app.services.indicadores import consulta, consulta_ideb, consulta_saresp

    base = mundo_plataformas(db)
    nova_escola(db, base["rede"], "EMEF Fictícia Sem Inep", None)
    if com_linhas_de_fora:
        _linhas_que_ficam_de_fora(db, base)
    db.commit()
    rede = base["rede"]
    chamadas = [lambda: consulta.ica_da_rede(db, rede),
                lambda: consulta_saresp.saresp_da_rede(db, rede),
                lambda: consulta_ideb.ideb_da_rede(db, rede),
                lambda: svc_ind.catalogo(db, rede)]
    chamadas += [lambda ch=ch, v=v: svc_ind.detalhe(db, rede, ch, visao=v)
                 for ch in svc_ind.ORDEM for v in ("serie", "escolas")]
    chamadas += [lambda e=e: svc_escola.analise_da_escola(db, e, hoje=HOJE, com_plataformas=False)
                 for e in base["escolas"].values()]
    for i, chamada in enumerate(chamadas):
        db.expire_all()
        try:
            direto = _sem_ids_de_objeto(chamada())
        except Exception as erro:                   # o mesmo erro nos dois caminhos
            direto = ("erro", type(erro).__name__, str(erro))
        db.expire_all()
        with leituras.leituras_da_requisicao(db):
            try:
                lote = _sem_ids_de_objeto(chamada())
            except Exception as erro:
                lote = ("erro", type(erro).__name__, str(erro))
        assert lote == direto, i


def test_catalogo_e_analise_so_das_avaliacoes_em_poucas_consultas(db):
    """Os tetos (antes: o catálogo em 17 consultas e a análise só das avaliações em 15, nesta
    rede), os mesmos com mais escolas."""
    from app.models import Rede
    from app.services.analise import indicadores as svc_ind

    base = mundo_plataformas(db)
    rid = base["rede"].id
    alfa_id = base["escolas"]["alfa"].id

    def contar():
        def catalogo():
            with leituras.leituras_da_requisicao(db):
                svc_ind.catalogo(db, db.get(Rede, rid))
        n_catalogo = _consultas(db, catalogo)
        from app.models import Escola
        n_escola = _consultas(db, lambda: svc_escola.analise_da_escola(
            db, db.get(Escola, alfa_id), hoje=HOJE, com_plataformas=False))
        return n_catalogo, n_escola

    antes = contar()
    for i in range(5):
        nova_escola(db, base["rede"], f"EMEF Fictícia Mais {i}", f"359903{10 + i}")
    db.commit()
    depois = contar()
    print(f"\ncatálogo e análise só das avaliações: {antes} -> com mais 5 escolas {depois}")
    assert antes == depois
    n_catalogo, n_escola = depois
    # a rede, as escolas, o catálogo das avaliações, as referências, as importações do
    # município, os resultados e as estimativas (o catálogo); a escola e a rede (a análise)
    assert n_catalogo <= 7
    assert n_escola <= 7


def test_leituras_em_lote_so_dentro_do_bloco_e_as_avaliacoes_por_escola_sao_as_das_consultas():
    import pytest

    from app.services.indicadores import ideb, seduc
    assert leituras.AVALIACOES_POR_ESCOLA == (seduc.AVALIACAO_SARESP, ideb.AVALIACAO_IDEB,
                                              ideb.AVALIACAO_SAEB)
    from sqlalchemy.orm import Session
    sessao = Session()
    with pytest.raises(RuntimeError):
        leituras.referencias(sessao, "3599901")
    with pytest.raises(RuntimeError):
        leituras.resultados_sem_turma(sessao, {1}, 1)
    assert leituras.ativa(sessao) is False
    sessao.close()


def test_rede_muito_grande_le_os_ramos_um_a_um_com_o_mesmo_resultado(db, monkeypatch):
    """Acima do teto de parâmetros por comando (o PostgreSQL aceita 65.535; cada valor de um
    IN é um), os ramos vão um a um, com o mesmo SQL: a resposta é a mesma."""
    base = mundo_plataformas(db)
    rid = base["rede"].id
    juntos = [svc_rede.dashboard_rede(db, rid, secretaria=s) for s in (True, False)]
    juntos += [svc_rede.destaques_rede(db, rid, secretaria=s) for s in (True, False)]
    monkeypatch.setattr(svc_rede, "_TETO_PARAMETROS", 0)
    um_a_um = [svc_rede.dashboard_rede(db, rid, secretaria=s) for s in (True, False)]
    um_a_um += [svc_rede.destaques_rede(db, rid, secretaria=s) for s in (True, False)]
    assert um_a_um == juntos


class _ContadorDeRedes(_Contador):
    """Conta só as consultas que leem a tabela ``redes``."""

    def _conta(self, _conn, _cursor, sql, *_a, **_k):
        if " redes" in sql.lower().replace('"', " "):
            self.n += 1


def test_exigir_rede_nao_le_a_rede_da_propria_secretaria(db):
    """A Secretaria da própria rede passa sem ler ``redes`` (a FK ``usuarios.rede_id`` já
    garante que a rede existe); o global e a conta de outra rede seguem lendo, com os
    mesmos 404 e 403 de sempre."""
    import pytest
    from fastapi import HTTPException

    from app.core.deps import exigir_rede
    from app.models import Rede, Usuario

    rede = Rede(nome="Rede Fictícia Leve")
    outra = Rede(nome="Rede Fictícia Outra")
    db.add_all([rede, outra])
    db.flush()
    secretaria = Usuario(nome="Sec", email="sec@leve.local", senha_hash="x", cargo="coordenador",
                         rede_id=rede.id)
    global_ = Usuario(nome="Glob", email="glob@leve.local", senha_hash="x", cargo="admin",
                      is_global=True, rede_id=rede.id)
    db.add_all([secretaria, global_])
    db.commit()
    rid, oid = rede.id, outra.id
    _ = (secretaria.rede_id, secretaria.is_global, global_.rede_id, global_.is_global)

    db.expire(rede)                                   # (sem isto o get sairia do mapa de identidade)
    with _ContadorDeRedes(db) as c:
        assert exigir_rede(rid, secretaria, db) == rid
    assert c.n == 0                                   # nenhuma leitura de ``redes``

    db.expire(rede)
    with _ContadorDeRedes(db) as c:                   # o global sempre confere a rede
        assert exigir_rede(rid, global_, db) == rid
    assert c.n == 1
    with pytest.raises(HTTPException) as e:
        exigir_rede(oid, secretaria, db)              # a rede de outra Secretaria: 403
    assert e.value.status_code == 403
    for quem in (secretaria, global_):                # rede inexistente: 404 para os dois
        with pytest.raises(HTTPException) as e:
            exigir_rede(999_999, quem, db)
        assert e.value.status_code == 404


def test_analise_so_das_avaliacoes_valida_o_periodo_como_a_completa(db):
    import pytest

    from app.services.analise import AnaliseInvalida
    base = mundo_plataformas(db)
    escola = next(iter(base["escolas"].values()))
    for pedido in ({"preset": "nao_existe"},
                   {"preset": "personalizado", "inicio": HOJE.replace(year=1800), "fim": HOJE}):
        with pytest.raises(AnaliseInvalida) as completa:
            svc_escola.analise_da_escola(db, escola, hoje=HOJE, **pedido)
        with pytest.raises(AnaliseInvalida) as so:
            svc_escola.analise_da_escola(db, escola, hoje=HOJE, com_plataformas=False, **pedido)
        assert (str(so.value), so.value.status) == (str(completa.value), completa.value.status)
