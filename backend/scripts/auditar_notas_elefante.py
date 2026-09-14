# -*- coding: utf-8 -*-
"""AUDITORIA READ-ONLY do pipeline Elefante → Nota. SÓ SELECT; nada é gravado
(a sessão termina em rollback). Recalcula a nota ESPERADA em memória com as
MESMAS funções do motor (sem commit) e compara com a Nota gravada; classifica os
zeros (corretos × suspeitos); checa duplicidades; compara as telas entre si.

Uso (a partir de backend/, com o venv da aplicação):

    DATABASE_URL=<url> python -m scripts.auditar_notas_elefante [--json saida.json] [--escola ID]

A URL do banco vem SÓ da variável de ambiente (nunca no código). Pode ser
apontado para produção: é seguro (read-only) — mas rode fora do horário de pico,
pois recalcula a escola inteira em memória.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if not os.environ.get("DATABASE_URL"):
    sys.exit("defina DATABASE_URL (a auditoria é read-only, mas precisa do banco).")

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Aluno, DificuldadeTurma, Escola, Importacao, Leitura, Livro, Matricula,
    NivelDificuldade, Nota, PontuacaoNivelTurma, ReferenciaNormalizacao,
    SnapshotElefante, Turma, Usuario,
)
from app.routers import rankings  # noqa: E402
from app.services import dificuldade_livro as dl  # noqa: E402
from app.services import evolucao, premiacoes, scoring  # noqa: E402
from app.services.provisionamento import NIVEIS_PADRAO  # noqa: E402

# Zero "correto" = não há o que pontuar (sem atividade / sem importação / inativo).
# Zero "suspeito" = há dado no banco e a nota não o reflete (pipeline a corrigir).
CLASSES_ZERO_CORRETO = {
    "1-sem_atividade(inativo)", "1-sem_atividade(snapshot_zerado)",
    "2-sem_importacao", "2-sem_importacao(sem_matricula)",
}


def norm(t):
    s = "".join(c for c in unicodedata.normalize("NFD", str(t or ""))
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().casefold()


def mask(nome, aid):
    """Sem PII na saída: iniciais + id."""
    ini = "".join(p[0] for p in str(nome or "").split() if p)[:3]
    return f"{ini}.#{aid}"


def _sem_niveis(snap) -> bool:
    return bool(snap and (snap.livros_unicos or 0) > 0
                and not any(int(v or 0) for v in (snap.livros_por_nivel or {}).values()))


def auditar_escola(db, escola, fake_admin, cat):
    eid, ano = escola.id, escola.ano_letivo_ativo
    R = {"escola_id": eid, "escola": escola.nome, "ano": ano}
    print("=" * 96)
    print(f"ESCOLA {eid} - {escola.nome} - ano letivo ativo {ano}")
    print("=" * 96)
    # ---------- A) contagens por etapa ----------
    alunos = db.execute(select(Aluno).where(Aluno.escola_id == eid)).scalars().all()
    mats = db.execute(select(Matricula, Turma).join(Turma, Matricula.turma_id == Turma.id)
                      .where(Matricula.escola_id == eid, Matricula.ano_letivo == ano)).all()
    mat_por_aluno = {m.aluno_id: t for m, t in mats}
    imps = db.execute(select(Importacao).where(Importacao.escola_id == eid)).scalars().all()
    livros = db.execute(select(Livro).where(Livro.escola_id == eid)).scalars().all()
    leituras = db.execute(select(Leitura).where(Leitura.escola_id == eid)).scalars().all()
    snaps = db.execute(select(SnapshotElefante).where(SnapshotElefante.escola_id == eid)).scalars().all()
    notas = {n.aluno_id: n for n in db.execute(
        select(Nota).where(Nota.escola_id == eid, Nota.ano_letivo == ano)).scalars()}
    notas_outros = db.execute(select(func.count()).select_from(Nota)
                              .where(Nota.escola_id == eid, Nota.ano_letivo != ano)).scalar()
    ids_atuais = set(db.execute(select(SnapshotElefante.id).where(
        SnapshotElefante.id.in_(scoring.ids_snapshots_atuais(SnapshotElefante, eid)))).scalars())
    snap_atual = {s.aluno_id: s for s in snaps if s.id in ids_atuais}
    leit_por_aluno = defaultdict(list)
    for l in leituras:
        leit_por_aluno[l.aluno_id].append(l)
    livro_por_id = {l.id: l for l in livros}
    ativos_matriculados = {a.id for a in alunos if a.status == "ativo" and a.id in mat_por_aluno}
    R["contagens"] = {
        "alunos": dict(Counter(a.status for a in alunos)), "matriculas_ano_ativo": len(mats),
        "importacoes": dict(Counter(f"{i.plataforma}/{i.tipo}" for i in imps)),
        "livros": len(livros),
        "livros_sem_nivel": sum(1 for l in livros if not (l.nivel_codigo or "").strip()),
        "leituras": len(leituras),
        "leituras_sem_livro": sum(1 for l in leituras if l.livro_id not in livro_por_id),
        "leituras_sem_data": sum(1 for l in leituras if l.data is None),
        "snapshots_elefante": len(snaps), "snapshots_atuais": len(snap_atual),
        "notas_ano_ativo": len(notas), "notas_outros_anos": notas_outros,
        "notas_sem_carimbo_institucional": sum(
            1 for n in notas.values()
            if not ((n.detalhes or {}).get("regua_institucional") or {}).get("versao_dificuldade")),
        "notas_institucional_zero_com_nota_positiva": sum(
            1 for n in notas.values()
            if (n.nota_elefante or 0) > 0 and not (getattr(n, "nota_elefante_institucional", 0) or 0)),
        # insumos que o motor v1 precisa e que faltam:
        "alunos_com_leituras_sem_snapshot_atual": sum(
            1 for aid in leit_por_aluno if aid not in snap_atual and aid in ativos_matriculados),
        "snapshots_atuais_sem_niveis": sum(1 for s in snap_atual.values() if _sem_niveis(s)),
        "snapshots_atuais_sem_niveis_e_sem_leituras": sum(
            1 for aid, s in snap_atual.items() if _sem_niveis(s) and not leit_por_aluno.get(aid)),
    }
    print("A) CONTAGENS:", json.dumps(R["contagens"], ensure_ascii=False, default=str))
    # ---------- B) duplicidades / integridade ----------
    dup_alunos = [g for g in Counter(norm(a.nome) for a in alunos if a.status != "excluido").items() if g[1] > 1]
    dup_livros_tn = [g for g in Counter((norm(l.titulo), (l.nivel_codigo or "").upper()) for l in livros).items() if g[1] > 1]
    dup_livros_t = [g for g in Counter(norm(l.titulo) for l in livros).items() if g[1] > 1]
    dup_leit_titulo = 0
    for aid, ls in leit_por_aluno.items():
        c = Counter(norm(livro_por_id[l.livro_id].titulo) for l in ls if l.livro_id in livro_por_id)
        dup_leit_titulo += sum(1 for v in c.values() if v > 1)
    dup_snaps = [g for g in Counter((s.aluno_id, s.data_referencia) for s in snaps).items() if g[1] > 1]
    fora_catalogo = [l for l in livros if cat.buscar(l.titulo, l.nivel_codigo) is None]
    ult = {}
    for s in snaps:
        if s.aluno_id not in ult or s.id > ult[s.aluno_id].id:
            ult[s.aluno_id] = s
    nao_ultimo = [(aid, snap_atual[aid].id, s.id) for aid, s in ult.items()
                  if aid in snap_atual and snap_atual[aid].id != s.id]
    R["integridade"] = {
        "alunos_duplicados_por_nome": len(dup_alunos),
        "livros_duplicados_titulo_nivel": len(dup_livros_tn),
        "livros_mesmo_titulo_niveis_diferentes": len(dup_livros_t),
        "leituras_mesmo_titulo_por_aluno": dup_leit_titulo,
        "snapshots_duplicados_aluno_data": len(dup_snaps),
        "ativos_matriculados_sem_nota": sorted(ativos_matriculados - set(notas)),
        "ativos_sem_matricula_ano_ativo": [a.id for a in alunos if a.status == "ativo" and a.id not in mat_por_aluno],
        "turmas_sem_serie_reconhecivel": sorted({t.id for _, t in mats if dl.serie_numero(t.ano_escolar) is None}),
        "livros_fora_do_catalogo": len(fora_catalogo),
        "notas_de_alunos_inativos_ou_sem_matricula": [aid for aid in notas if aid not in ativos_matriculados],
        "snapshots_atuais_de_inativos": [s.aluno_id for s in snap_atual.values() if s.aluno_id not in ativos_matriculados],
        "snapshot_atual_nao_e_o_ultimo_id": nao_ultimo[:10],
    }
    print("B) INTEGRIDADE:", json.dumps(R["integridade"], ensure_ascii=False, default=str))
    # ---------- C) nota ESPERADA em memória (mesmas funções do motor, sem commit) ----------
    ctx = scoring._carregar_contexto(db, eid)
    esperado = {}
    if ctx:
        _, _, matriculas, matific, elefante, pontos_dif = ctx
        personalizado = scoring._scoring_personalizado(db, eid)
        if personalizado:
            extra = scoring.obter_config(db, eid, "pesos.elefante_extra", "valores",
                                         {"ativo": False, "pontos_por_livro": 0.0})
            if extra.get("ativo") and float(extra.get("pontos_por_livro", 0) or 0) > 0:
                turno = {m.aluno_id: t.turno for m, t in matriculas}
                for aid, b in scoring._bonus_leitura_na_escola(
                        db, eid, turno, float(extra["pontos_por_livro"])).items():
                    pontos_dif[aid] = pontos_dif.get(aid, 0.0) + b
            refs, modo, k_vol = scoring._referencias(db, eid, matific, elefante, pontos_dif)
            p_m, p_e, p_q = (scoring.obter_pesos(db, eid, n)
                             for n in ("pesos.matific", "pesos.elefante", "pesos.questoes"))
            pct_m, pct_e, pct_q = (scoring.obter_pesos_brutos(db, eid, n)
                                   for n in ("pesos.matific", "pesos.elefante", "pesos.questoes"))
            p_geral = scoring.obter_pesos(db, eid, "pesos.geral")
        else:
            (pontos_dif, refs, k_vol, p_m, pct_m, p_e, pct_e, p_q, pct_q) = \
                scoring._insumos_institucionais(matriculas, matific, elefante, pontos_dif=pontos_dif)
            modo = "auto"
            p_geral = scoring._pesos_geral_institucional(db, eid)
        for m, t in matriculas:
            aid = m.aluno_id
            se = elefante.get(aid)
            sm = matific.get(aid)
            nm, _ = scoring.calcular_matific(sm, refs, p_m, pct_m, k_vol)
            ne, _, _ = scoring.calcular_elefante(se, pontos_dif[aid], refs, p_e, pct_e, p_q, pct_q, k_vol)
            dims = {n for n, tem in (("matific", sm is not None or nm > 0),
                                     ("elefante", se is not None or ne > 0)) if tem}
            pg = scoring.pesos_geral_do_aluno(p_geral, dims)
            ng = round(nm * pg.get("matific", 0) + ne * pg.get("elefante", 0), 2)
            esperado[aid] = {"nota_elefante": ne, "nota_geral": ng, "pontos_dif": pontos_dif[aid],
                             "aferido_leitura": "elefante" in dims, "serie": t.ano_escolar,
                             "turma_id": t.id}
        R["perfil"] = "personalizado" if personalizado else "institucional"
        R["modo_normalizacao"] = modo
        R["refs"] = refs
    # ---------- D) classificação dos zeros + tabela por aluno ----------
    tabela = []
    classes = Counter()
    divergentes = []
    por_turma = defaultdict(lambda: Counter())
    for a in alunos:
        n = notas.get(a.id)
        e = esperado.get(a.id)
        s = snap_atual.get(a.id)
        ls = leit_por_aluno.get(a.id, [])
        t = mat_por_aluno.get(a.id)
        det = ((n.detalhes or {}).get("dimensoes", {}).get("leitura", {}).get("dados", {}) if n else {})
        stored_pd = det.get("pontos_dificuldade")
        versao = det.get("versao_dificuldade")
        carimbo = ((n.detalhes or {}).get("regua_institucional") or {}).get("versao_dificuldade") if n else None
        zero = (n is None) or (not n.nota_elefante) or (not n.aferido_leitura)
        cls = None
        if zero:
            if a.status != "ativo":
                cls = "3-importado_sem_vinculo(status!=ativo)" if (s or ls) else "1-sem_atividade(inativo)"
            elif t is None:
                cls = "3-importado_sem_vinculo(sem_matricula_ano_ativo)" if (s or ls) else "2-sem_importacao(sem_matricula)"
            elif s is None and not ls:
                cls = "2-sem_importacao"
            elif s is not None and (s.livros_unicos or 0) == 0 and not ls:
                cls = "1-sem_atividade(snapshot_zerado)"
            elif ls and s is None:
                cls = "6-leitura_sem_snapshot"
            elif s is not None and (s.livros_unicos or 0) > 0 and e and e["nota_elefante"] > 0:
                cls = "4-nota_nao_recalculada"
            elif s is not None and (s.livros_unicos or 0) > 0:
                cls = "11-dados_presentes_mas_descartados"
            else:
                cls = "12-outro"
            classes[cls] += 1
        if t is not None:
            ct = por_turma[(t.id, t.nome)]
            ct["alunos"] += 1
            ct["ativos"] += a.status == "ativo"
            ct["com_snapshot"] += s is not None
            ct["com_leituras"] += bool(ls)
            ct["com_nota_positiva"] += bool(n and (n.nota_elefante or 0) > 0)
            if cls:
                ct["zeros_corretos" if cls in CLASSES_ZERO_CORRETO else "zeros_suspeitos"] += 1
        if n and e:
            d_e = abs((n.nota_elefante or 0) - e["nota_elefante"])
            d_g = abs((n.nota_geral or 0) - e["nota_geral"])
            d_p = abs(float(stored_pd or 0) - e["pontos_dif"])
            if d_e > 0.011 or d_g > 0.011 or d_p > 0.011:
                divergentes.append({"aluno": mask(a.nome, a.id),
                                    "gravada": (n.nota_elefante, n.nota_geral, stored_pd, versao),
                                    "esperada": (e["nota_elefante"], e["nota_geral"], e["pontos_dif"]),
                                    "motivo": ("nota gravada antes da v1 / sem carimbo (recalcular)"
                                               if versao != dl.VERSAO_VIGENTE or carimbo is None
                                               else "divergência com a v1 vigente")})
        tabela.append({"aluno": mask(a.nome, a.id), "status": a.status, "turma": t.nome if t else None,
                       "serie": t.ano_escolar if t else None,
                       "livros_snap": s.livros_unicos if s else None,
                       "niveis": s.livros_por_nivel if s else None,
                       "tempo": s.tempo_leitura_min if s else None,
                       "questoes": (s.questoes_tentativas, s.questoes_acertos) if s else None,
                       "snapshot_em": str(s.data_referencia)[:10] if s else None, "leituras": len(ls),
                       "nota_gravada": (n.nota_elefante if n else None),
                       "nota_institucional_gravada": (getattr(n, "nota_elefante_institucional", None) if n else None),
                       "aferido_gravado": (n.aferido_leitura if n else None), "versao_gravada": versao,
                       "carimbo_institucional": carimbo,
                       "nota_esperada": (e["nota_elefante"] if e else None),
                       "pontos_dif_esperado": (e["pontos_dif"] if e else None), "classe_zero": cls})
    R["classes_zero"] = dict(classes)
    R["zeros_corretos"] = sum(v for k, v in classes.items() if k in CLASSES_ZERO_CORRETO)
    R["zeros_suspeitos"] = sum(v for k, v in classes.items() if k not in CLASSES_ZERO_CORRETO)
    R["divergentes_gravada_vs_esperada"] = divergentes
    R["por_turma"] = {f"{tid}:{nome}": dict(c) for (tid, nome), c in sorted(por_turma.items())}
    R["tabela"] = tabela
    print("C/D) PERFIL:", R.get("perfil"), "| modo:", R.get("modo_normalizacao"),
          "| zeros corretos:", R["zeros_corretos"], "| zeros SUSPEITOS:", R["zeros_suspeitos"],
          "| classes:", dict(classes))
    print("   notas gravadas != esperadas:", len(divergentes),
          ("-> " + json.dumps(divergentes[:3], ensure_ascii=False, default=str)) if divergentes else "")
    print("   POR TURMA:")
    for chave, c in R["por_turma"].items():
        print(f"     {chave}: {dict(c)}")
    print("   %-12s %-6s %-8s %-5s %6s %5s %7s %7s %7s %5s %s" % (
        "aluno", "status", "serie", "snapL", "tempo", "leit", "nota", "esper", "pdif", "afer", "classe/versao"))
    for r in tabela:
        print("   %-12s %-6s %-8s %-5s %6s %5s %7s %7s %7s %5s %s" % (
            r["aluno"], r["status"][:6], (r["serie"] or "-")[:8], r["livros_snap"], r["tempo"], r["leituras"],
            r["nota_gravada"], r["nota_esperada"], r["pontos_dif_esperado"], r["aferido_gravado"],
            r["classe_zero"] or (r["versao_gravada"] or "")))
    # ---------- E) consistência entre telas (mesmo aluno, 'tudo') ----------
    incons = []
    if ctx:
        rk = {r["aluno_id"]: r for r in rankings.ranking_leitura(
            escola_id=eid, periodo="tudo", inicio=None, fim=None, turma_id=None, ano_escolar=None,
            db=db, usuario=fake_admin)}
        al_prem = premiacoes._alunos_ativos(db, eid, ano, None)
        _, prem_pontos, _ = premiacoes._leitura_no_periodo(db, eid, al_prem, None, None)
        regra = dl.regra_da_escola(db, eid)
        for aid, e in esperado.items():
            if not (leit_por_aluno.get(aid) or snap_atual.get(aid)):
                continue
            s = snap_atual.get(aid)
            t = mat_por_aluno.get(aid)
            perfil = scoring.distribuicao_niveis(
                db, eid, s.livros_por_nivel if s else {}, t.ano_escolar if t else "",
                aluno_id=aid, livros_unicos=(s.livros_unicos if s else 0))["pontos_dificuldade"]
            hist = round(sum(regra.valor_livro(livro_por_id[l.livro_id].nivel_codigo,
                                               livro_por_id[l.livro_id].titulo,
                                               t.ano_escolar if t else None, t.id if t else None)
                             for l in leit_por_aluno.get(aid, []) if l.livro_id in livro_por_id), 2)
            evo = round(sum(x["pontos"] for x in evolucao.evolucao_leitura(db, eid, aid, "mes")["series"]), 2)
            item = {"aluno": mask("", aid), "anual_pontos_dif": e["pontos_dif"],
                    "ranking_periodo_tudo": rk.get(aid, {}).get("pontos"),
                    "premiacao_tudo": round(prem_pontos.get(aid, 0.0), 2), "perfil_card": perfil,
                    "historico_itemizado": hist, "evolucao_soma": evo,
                    "livros_snap": s.livros_unicos if s else 0,
                    "leituras_itemizadas": len(leit_por_aluno.get(aid, []))}
            # 'tudo' = anual: ranking, premiação e perfil precisam bater com a nota anual.
            vals = [v for v in (item["ranking_periodo_tudo"], item["premiacao_tudo"], item["perfil_card"])
                    if v is not None]
            item["tudo_coerente"] = (max(vals + [e["pontos_dif"]]) - min(vals + [e["pontos_dif"]]) <= 0.02)
            # histórico/evolução só enxergam o ITEMIZADO — coincidem com o anual
            # quando não há snapshot além das leituras.
            item["itemizado_coerente"] = abs(hist - evo) <= 0.02
            if not (item["tudo_coerente"] and item["itemizado_coerente"]):
                incons.append(item)
        try:
            ev = evolucao.ranking_evolucao(db, eid, inicio=None, fim=None)
            R["mural_ok"] = f"ranking_evolucao ok ({len(ev)} itens)"
        except Exception as ex:  # noqa: BLE001
            R["mural_ok"] = f"ERRO: {ex!r}"
    R["inconsistencias_entre_telas"] = incons
    print("E) TELAS: inconsistências ('tudo' × anual × perfil / histórico × evolução):", len(incons),
          ("-> " + json.dumps(incons[:3], ensure_ascii=False)) if incons else "", "|", R.get("mural_ok"))
    # ---------- F) configuração ----------
    niv = db.execute(select(NivelDificuldade).where(NivelDificuldade.escola_id == eid)
                     .order_by(NivelDificuldade.ordem)).scalars().all()
    padrao = [(n.nome, n.codigo, list(n.codigos or []), float(n.pontos_padrao)) for n in niv]
    esperado_padrao = [(n, c, list(cs), p) for n, c, cs, p in NIVEIS_PADRAO]
    refn = db.execute(select(ReferenciaNormalizacao)
                      .where(ReferenciaNormalizacao.escola_id == eid)).scalar_one_or_none()
    R["config"] = {
        "perfil_scoring": scoring.obter_config(db, eid, scoring.PERFIL_SCORING_NS, "modo", "institucional"),
        "niveis_diferem_do_padrao": padrao != esperado_padrao,
        "dificuldade_turma": db.execute(select(func.count()).select_from(DificuldadeTurma)
                                        .where(DificuldadeTurma.escola_id == eid)).scalar(),
        "pontuacao_nivel_turma": db.execute(select(func.count()).select_from(PontuacaoNivelTurma)
                                            .where(PontuacaoNivelTurma.escola_id == eid)).scalar(),
        "referencias": (refn.modo, refn.valores_manuais) if refn else None,
        "elefante_extra": scoring.obter_config(db, eid, "pesos.elefante_extra", "valores", None),
        "pesos_elefante": scoring.obter_pesos_brutos(db, eid, "pesos.elefante"),
    }
    print("F) CONFIG:", json.dumps(R["config"], ensure_ascii=False, default=str))
    print()
    return R


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="ARQUIVO", help="grava o relatório completo em JSON")
    ap.add_argument("--escola", type=int, help="audita só esta escola (id)")
    args = ap.parse_args(argv)

    out = {"banco": os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0], "escolas": []}
    db = SessionLocal()
    fake_admin = Usuario(id=0, escola_id=None, nome="audit", email="audit@local", senha_hash="x",
                         cargo="admin", is_global=True)
    cat = dl.catalogo()
    print(f"BANCO: {out['banco']} | catálogo v1: {len(cat)} livros | versão vigente: {dl.VERSAO_VIGENTE}\n")
    try:
        consulta = select(Escola).order_by(Escola.id)
        if args.escola:
            consulta = consulta.where(Escola.id == args.escola)
        for escola in db.execute(consulta).scalars().all():
            out["escolas"].append(auditar_escola(db, escola, fake_admin, cat))
    finally:
        db.rollback()   # READ-ONLY: nada do que o motor tocou em memória é persistido
        db.close()
    # ---------- resumo global ----------
    print("=" * 96)
    print("RESUMO GLOBAL")
    for R in out["escolas"]:
        c = R["contagens"]
        print(f"  escola {R['escola_id']}: notas={c['notas_ano_ativo']} sem_carimbo={c['notas_sem_carimbo_institucional']} "
              f"inst_zero_c/nota>0={c['notas_institucional_zero_com_nota_positiva']} "
              f"zeros_corretos={R['zeros_corretos']} zeros_SUSPEITOS={R['zeros_suspeitos']} "
              f"divergentes={len(R['divergentes_gravada_vs_esperada'])} "
              f"leituras_sem_snapshot={c['alunos_com_leituras_sem_snapshot_atual']} "
              f"snapshots_sem_niveis={c['snapshots_atuais_sem_niveis']} "
              f"telas_inconsistentes={len(R['inconsistencias_entre_telas'])}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, default=str, indent=1)
        print(f"JSON: {args.json}")
    print("FIM (nada gravado).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
