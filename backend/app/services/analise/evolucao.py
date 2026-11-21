"""Evolução das plataformas no ano letivo, por BIMESTRE
(``GET /redes/{id}/analise/plataformas/evolucao``) — só leitura.

COMO (sem regra nova): cada bimestre é UM período da rota de plataformas —
``plataformas.plataformas_da_rede`` com o preset oficial ``bimestre_1..4`` (o calendário
oficial de ``services/bimestres``, pelo serviço de períodos) —, então os números de cada
bimestre são EXATAMENTE os que a aba de plataformas mostra quando se escolhe aquele
bimestre: a mesma coorte, a mesma cobertura (coleta parcial, sem coleta), a mesma regra de
cada métrica e a mesma supressão k = 5 (decidida pelas contagens, igual em todos os
bimestres). Os bimestres são medidos JUNTOS (``plataformas_da_rede_por_periodo``): as
leituras do banco são as mesmas para um ou quatro bimestres. Este módulo só escolhe os
bimestres e recorta os campos da série.

* ``so_escola`` (a ficha da escola): mede SÓ a escola pedida, com a supressão da rede
  inteira (os números dela são os mesmos da evolução da rede); a rede não é medida e o
  bloco ``rede`` de cada bimestre sai nulo.

* Só os bimestres que JÁ COMEÇARAM (o início ≤ hoje); o que contém hoje vem marcado
  ``em_andamento`` (os números dele são parciais, até hoje).
* O ano é o ano letivo de referência da rede: o mais comum entre as escolas EM USO (ativas
  e com aluno na coorte — ``indicadores.ano_letivo_da_rede``; escola fechada ou só
  cadastrada, parada no ano antigo, não decide). Na ficha (``so_escola``), o ano letivo da
  própria escola. Quando ele não é o do calendário de hoje (a virada de ano antes de a
  escola trocar o ano letivo), as datas de cada bimestre continuam as do ano letivo: o
  preset numerado do serviço de períodos é do ano letivo de cada escola, como na aba de
  plataformas.
* Escolas em ordem alfabética (nunca ranking); ausência ≠ zero: sem número, o campo é nulo
  e vem o motivo do serviço; escola suprimida não mostra nada.

Nenhuma resposta traz ``aluno_id``, nome de aluno ou turma.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Rede
from app.services import bimestres
from app.services import relatorios_periodo as rp
from app.services.analise import K_MINIMO, AnaliseInvalida
from app.services.analise import plataformas as plat_svc
from app.services.analise.indicadores import ano_letivo_da_rede

CAMPOS_REDE = {"elefante": ("participacao_pct", "livros_por_aluno", "minutos_por_aluno"),
               "matific": ("participacao_pct", "atividades_por_aluno")}
CAMPOS_ESCOLA = {"elefante": ("participacao_pct", "livros_por_aluno"),
                 "matific": ("participacao_pct", "atividades_por_aluno")}

LIMITACOES_BIMESTRE = [
    ("Cada bimestre é medido como um período à parte, com as mesmas regras do uso no "
     "período: a participação é a fração dos alunos medidos que usaram a plataforma NO "
     "bimestre; livros e atividades por aluno somam só o que aconteceu nele."),
    ("Bimestres têm tamanhos diferentes e o que está em andamento só vai até hoje: compare a "
     "participação com tranquilidade; livros e atividades por aluno crescem com o número de "
     "dias do bimestre."),
    ("A proteção das crianças (k = 5) é decidida pelo número de alunos, igual em todos os "
     "bimestres; já a cobertura muda: a escola sem coleta num bimestre aparece sem dado "
     "naquele bimestre (sem dado não é zero)."),
]


def _bloco(dados: dict | None, campos: tuple[str, ...], *, suprimido: bool = False,
           texto_supressao: str | None = None) -> dict:
    """Os campos da série, com o motivo quando não há número (ausência ≠ zero)."""
    if suprimido or dados is None:
        return {**{c: None for c in campos}, "motivo_sem_dado": plat_svc.SUPRIMIDO,
                "texto_sem_dado": texto_supressao or plat_svc.TEXTO_SUPRESSAO,
                "coleta_parcial": False, "metricas_protegidas": []}
    return {**{c: dados.get(c) for c in campos},
            "motivo_sem_dado": dados.get("motivo_sem_dado"),
            "texto_sem_dado": dados.get("texto_sem_dado"),
            "coleta_parcial": bool(dados.get("coleta_parcial")),
            "metricas_protegidas": [m for m in (dados.get("metricas_protegidas") or [])
                                    if m in campos]}


def _bloco_da_rede(dados: dict) -> dict | None:
    mods, rede = dados["modulos"], dados["rede"]
    if rede is None:
        return None                                     # só a escola: a rede não foi medida
    parciais = dados["cobertura"]["escolas_coleta_parcial"]
    bloco_rede = {}
    for p, campos in CAMPOS_REDE.items():
        bloco_rede[p] = (None if not mods[p] else
                         _bloco(rede.get(p), campos, suprimido=rede["suprimido"],
                                texto_supressao=rede["texto_supressao"]))
    bloco_rede["escolas_com_dado"] = {p: (rede["escolas_com_dado"][p] if mods[p] else None)
                                      for p in CAMPOS_REDE}
    bloco_rede["escolas_parciais"] = {p: (len(parciais.get(p, [])) if mods[p] else None)
                                      for p in CAMPOS_REDE}
    bloco_rede["suprimido"] = rede["suprimido"]
    return bloco_rede


def _bimestre_json(numero: int, janela: rp.Janela, dados: dict, hoje: date) -> dict:
    mods = dados["modulos"]
    inicio, fim = janela.inicio.date(), janela.fim.date()
    escolas = []
    for e in dados["escolas"]:                      # já em ordem alfabética
        item = {"id": e["escola_id"], "nome": e["nome"], "cobertura": e["cobertura"],
                "suprimido": e["suprimido"]}
        for p, campos in CAMPOS_ESCOLA.items():
            item[p] = (None if not mods[p] else
                       _bloco(e.get(p), campos, suprimido=e["suprimido"],
                              texto_supressao=e["texto_supressao"]))
        escolas.append(item)
    return {"numero": numero, "rotulo": janela.rotulo, "inicio": inicio.isoformat(),
            "fim": fim.isoformat(), "em_andamento": inicio <= hoje <= fim,
            "rede": _bloco_da_rede(dados), "escolas": escolas}


def evolucao(db: Session, rede: Rede, *, serie: int | None = None,
             escola_id: int | None = None, hoje: date, k: int = K_MINIMO,
             so_escola: bool = False) -> dict:
    # Os filtros são validados ANTES (também quando nenhum bimestre começou ainda).
    plat_svc._validar_serie(serie)
    # As escolas e os módulos da rede numa consulta só (os mesmos de escolas_da_rede e
    # modulos_da_rede).
    escolas, contratados = plat_svc.escolas_e_modulos(db, rede.id)
    if escola_id is not None and escola_id not in {e.id for e in escolas}:
        raise AnaliseInvalida("Escola não encontrada nesta rede.", 404)
    if so_escola and escola_id is None:
        raise AnaliseInvalida("Para medir só a escola, informe a escola (escola_id).", 422)
    if so_escola:                                        # a ficha: o ano da escola
        ano = next(e.ano_letivo_ativo for e in escolas if e.id == escola_id)
    else:
        ano = ano_letivo_da_rede(db, escolas) or hoje.year
    modulos = {p: m in contratados for p, m in plat_svc.PLATAFORMA_MODULO.items()}
    pedidos = []
    for numero in bimestres.BIMESTRES:
        # As datas do bimestre DO ANO LETIVO, pelo serviço oficial de períodos (o preset
        # numerado é do ano letivo pedido, também na virada do ano civil).
        janela = rp.resolver_janela(f"bimestre_{numero}", ano, hoje=hoje)
        if janela.inicio is None or janela.inicio.date() > hoje:
            continue                                     # ainda não começou
        pedidos.append((numero, janela, plat_svc.Periodo(f"bimestre_{numero}")))
    saida_bimestres, limitacoes = [], None
    if pedidos:
        respostas = plat_svc.plataformas_da_rede_por_periodo(
            db, rede, [p for _, _, p in pedidos], serie=serie, escola_id=escola_id, hoje=hoje,
            k=k, so_escola=so_escola, escolas=escolas, mods=contratados)
        for (numero, janela, _), dados in zip(pedidos, respostas):
            limitacoes = dados["limitacoes"]
            saida_bimestres.append(_bimestre_json(numero, janela, dados, hoje))
    extras = list(LIMITACOES_BIMESTRE)
    if not bimestres.ano_com_calendario(ano):
        extras.append(bimestres.aviso_sem_calendario(ano))
    if not saida_bimestres:
        extras.append(f"Nenhum bimestre do ano letivo {ano} começou ainda.")
    return {
        "ano_letivo": ano,
        "k_minimo": k,
        "filtros": {"serie": serie, "escola_id": escola_id,
                    **({"so_escola": True} if so_escola else {})},
        "modulos": modulos,
        "calendario_oficial": bimestres.ano_com_calendario(ano),
        "bimestres": saida_bimestres,
        "limitacoes": extras + list(limitacoes if limitacoes is not None
                                    else plat_svc.LIMITACOES),
    }
