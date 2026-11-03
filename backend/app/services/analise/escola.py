"""A análise de UMA escola (``GET /escolas/{id}/analise``) — só leitura.

Quem lê é quem lê os indicadores oficiais da escola (a mesma regra de
``escola_com_indicadores_legiveis``): o admin global, a Secretaria da rede da escola e o
coordenador (ou o admin) da PRÓPRIA escola. O professor, não.

O que a escola vê:

* os indicadores OFICIAIS dela (SARESP, IEE, Ideb e Saeb, todas as etapas ×
  componentes), na forma única da análise, com a REDE MUNICIPAL como referência — e só
  ela: nenhuma outra escola aparece (nada de ranking, nem implícito); o ICA só como
  indicador da rede;
* as plataformas da escola por série (a mesma conta da rota da rede, medindo só esta
  escola; a supressão é a da rede para quem lê a rede — Secretaria e global — e a decidida
  dentro da escola para o coordenador e o admin dela);
* o que NÃO dá para comparar, e por quê (``comparacoes_indisponiveis``).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Escola, Rede
from app.services.analise import indicadores as ind_svc
from app.services.analise import validar_anos
from app.services.analise import plataformas as plat_svc
from app.services.avaliacoes import normalizar_inep
from app.services.indicadores import consulta_escola
from app.services.indicadores.leituras_da_requisicao import leituras_da_requisicao


def analise_da_escola(db: Session, escola: Escola, *, preset: str = "ano_letivo",
                      inicio: date | None = None, fim: date | None = None,
                      hoje: date, escopo_rede: bool = True,
                      com_plataformas: bool = True) -> dict:
    """``com_plataformas=False`` (a ficha e a comparação da Secretaria, que mostram só as
    avaliações externas e leem as plataformas pela rota da rede): ``plataformas`` sai nulo e
    a escola não é medida. As leituras repetidas dos indicadores saem do banco uma vez só
    (``leituras_da_requisicao``)."""
    with leituras_da_requisicao(db):
        return _analise(db, escola, preset=preset, inicio=inicio, fim=fim, hoje=hoje,
                        escopo_rede=escopo_rede, com_plataformas=com_plataformas)


def _analise(db: Session, escola: Escola, *, preset: str, inicio: date | None,
             fim: date | None, hoje: date, escopo_rede: bool, com_plataformas: bool) -> dict:
    inep = normalizar_inep(escola.codigo_inep)
    rede = db.get(Rede, escola.rede_id) if escola.rede_id is not None else None
    if com_plataformas:
        plataformas = plat_svc.plataformas_da_escola(db, escola, preset=preset, inicio=inicio,
                                                     fim=fim, hoje=hoje, escopo_rede=escopo_rede)
    else:
        # Sem medir: o período pedido continua validado como na análise completa (o erro é o
        # mesmo, sem consulta ao banco).
        validar_anos(inicio=inicio, fim=fim)
        plat_svc._janela(preset, escola.ano_letivo_ativo, inicio, fim, hoje)
        plataformas = None
    indisponiveis = [{"tema": "ica", "texto": "O ICA é da rede: não existe por escola."}]
    indicadores, fontes = [], {}
    if rede is None:
        indisponiveis.append({"tema": "sem_rede", "texto": consulta_escola.AVISOS["sem_rede"]})
    else:
        indicadores, fontes = ind_svc.indicadores_da_escola(ind_svc.Leituras(db, rede), escola)
        edicoes = sorted({p["edicao"] for item in indicadores for s in item["series"]
                          if s["abrangencia"] == "escola" for p in s["pontos"]
                          if ind_svc.e_oficial(p)})
        ano = escola.ano_letivo_ativo
        if ano not in edicoes:
            ate = f"vão até {edicoes[-1]}" if edicoes else "ainda não foram importados"
            texto = (f"Relação com as plataformas: período sem sobreposição — as plataformas "
                     f"têm dados do ano letivo {ano} e os resultados oficiais desta escola "
                     f"{ate}. Só se relacionam números do MESMO ano letivo.")
        else:
            texto = ("A relação entre avaliação e plataformas é medida entre as escolas da "
                     "rede (na análise da rede): uma escola sozinha não forma uma associação.")
        indisponiveis.append({"tema": "relacao", "texto": texto})
    if not inep:
        indisponiveis.append({"tema": "cadastro",
                              "texto": ("A escola está sem código INEP no cadastro: os "
                                        "números oficiais dela não podem ser casados.")})
    indisponiveis.append({"tema": "ranking",
                          "texto": ("Esta análise não compara a escola com as outras nem as "
                                    "ordena: as outras escolas não aparecem.")})
    return {
        "escola": {"id": escola.id, "nome": escola.nome, "codigo_inep": inep,
                   "status": escola.status, "pendencia": None if inep else "sem_codigo_inep",
                   "ano_letivo": escola.ano_letivo_ativo},
        "rede": {"id": rede.id, "nome": rede.nome} if rede is not None else None,
        "indicadores": indicadores,
        "plataformas": plataformas,
        "comparacoes_indisponiveis": indisponiveis,
        "fontes": fontes,
    }
