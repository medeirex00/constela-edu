"""MATRIZ de autorização: TODAS as rotas da API × seis perfis contra recursos de
outra escola e de outra rede. Nada pode vazar, nada de fora pode ser escrito, ninguém
sobe de papel.

Perfis: Admin Global, Secretaria (sec_a), Secretaria promovida de uma escola
(sec_prom, cargo admin), coordenação (coord_x), administração (admin_x) e professor
(prof_t) da escola X. O mundo e os marcadores de vazamento estão em
``tests/_rbac_mundo.py``. Cada rota é chamada por cada perfil em cenários:

  alheia_Y     escola Y / rede B no caminho, ids internos de Y        -> nega, nada vaza
  irma_X2      escola X2 (mesma rede) para coord/admin/prof           -> nega
  interno_Y    escola PRÓPRIA no caminho, ids internos (caminho, corpo e query) de Y
               -> nada de Y vaza e nada de Y é escrito
  turma_T2     prof_t com a escola X e ids da turma T2                -> nada de T2 vaza
  propria      ids próprios; prof_t não vê T2; a Secretaria não vê nome de criança (LGPD)
  propria_livre  o mesmo sem os filtros opcionais da query (listas "cheias")
  corpo_Y      caminho 100% próprio, só o corpo/query com ids de Y
  sem_login    sem token                                              -> 401

O banco é restaurado antes de CADA chamada; depois dela compara-se o banco inteiro:
linha de Y alterada = escrita entre escolas; conta com is_global/cargo/rede/escola
alterados por quem não é global = escalada. Resposta 5xx também reprova.

CATRACA: toda rota do app precisa de uma entrada no inventário abaixo
(``DA_EQUIPE``, ``ABERTAS``, ``POR_TOKEN_PUBLICO`` ou ``FORA_DA_MATRIZ``). Rota nova
sem entrada reprova o ``test_matriz`` dela e o ``test_inventario_cobre_todas_as_rotas``
— quem cria a rota decide, de propósito, como ela é conferida. Se o corpo genérico não
passar da validação (400/422 para todos), acrescente um corpo válido em ``_ajustes``.

``SONDA_RBAC_SAIDA=<arquivo.jsonl>`` (opcional) grava cada chamada da matriz, para
análise. Sem ela, nada é gravado.
"""
from __future__ import annotations

import json
import os
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from tests._rbac_mundo import TOKEN_PAINEL_X, Banco, isolar_rbac, mundo, texto_da_resposta

SAIDA = os.environ.get("SONDA_RBAC_SAIDA")          # JSONL com TODAS as chamadas (opcional)

# ------------------------------------------------------------------- o inventário
# Rotas que a matriz NÃO chama, cada uma com o motivo e onde ela é conferida.
FORA_DA_MATRIZ = {
    "POST /auth/login": "o próprio login (senha, limite de tentativas): test_auth*, "
                        "test_rate_limit*",
    "GET /metrics": "fora do OpenAPI, protegida por chave própria: test_metrics_protecao",
    "GET /quest/conquistas": "rota do ALUNO do Quest (token de aluno): test_quest_*, "
                             "e test_rbac_bordas (token da equipe não abre)",
    "GET /quest/perfil": "rota do ALUNO do Quest: test_quest_*, test_rbac_bordas",
    "GET /quest/perfil/aparencia": "rota do ALUNO do Quest: test_quest_*",
    "PATCH /quest/perfil/avatar": "rota do ALUNO do Quest: test_quest_*",
    "GET /quest/perfil/cores": "rota do ALUNO do Quest: test_quest_*",
    "PATCH /quest/perfil/nome": "rota do ALUNO do Quest: test_quest_*",
    "GET /quest/perfil/personagens": "rota do ALUNO do Quest: test_quest_*",
    "PATCH /quest/perfil/preferencias": "rota do ALUNO do Quest: test_quest_*",
}

# Abertas SEM login (saúde, redefinição de senha por link, entrada do aluno no Quest): a
# matriz chama com os perfis (nada pode vazar), mas não exige 401 sem token.
ABERTAS = frozenset({
    "GET /api/health",
    "GET /api/health/live",
    "GET /api/health/ready",
    "POST /auth/redefinir-senha",
    "GET /auth/redefinir-senha/{token}",
    "POST /quest/auth/entrar",
    "POST /quest/auth/entrar-qr",
    "POST /quest/auth/quem",
})

# Por TOKEN público (painel da escola, vitrine da rede): token inexistente = 404 e o
# token da escola X não abre criança de outra escola.
POR_TOKEN_PUBLICO = frozenset({
    "GET /publico/rede/{token}",
    "GET /publico/{token}/alunos/{aluno_id}",
    "GET /publico/{token}/painel",
})

# Rotas da EQUIPE (exigem login): os seis perfis em todos os cenários.
DA_EQUIPE = frozenset({
    "GET /auth/me",
    "GET /avaliacoes",
    "POST /avaliacoes/analisar",
    "GET /avaliacoes/fontes",
    "POST /avaliacoes/fontes",
    "DELETE /avaliacoes/fontes/{fonte_id}",
    "PUT /avaliacoes/fontes/{fonte_id}",
    "POST /avaliacoes/fontes/{fonte_id}/coletar",
    "POST /avaliacoes/importar",
    "POST /avaliacoes/importar-preset",
    "GET /avaliacoes/presets-import",
    "DELETE /avaliacoes/resultados",
    "GET /escolas",
    "POST /escolas",
    "PATCH /escolas/{escola_id}",
    "GET /escolas/{escola_id}/alunos",
    "POST /escolas/{escola_id}/alunos",
    "POST /escolas/{escola_id}/alunos/acoes",
    "GET /escolas/{escola_id}/alunos/duplicados",
    "POST /escolas/{escola_id}/alunos/duplicados/corrigir",
    "POST /escolas/{escola_id}/alunos/excluir-permanente",
    "POST /escolas/{escola_id}/alunos/fundir",
    "GET /escolas/{escola_id}/alunos/fundir/previa",
    "PATCH /escolas/{escola_id}/alunos/{aluno_id}",
    "GET /escolas/{escola_id}/alunos/{aluno_id}/espelho",
    "GET /escolas/{escola_id}/alunos/{aluno_id}/evolucao",
    "GET /escolas/{escola_id}/alunos/{aluno_id}/evolucao-leitura",
    "GET /escolas/{escola_id}/alunos/{aluno_id}/leituras",
    "GET /escolas/{escola_id}/alunos/{aluno_id}/linha-do-tempo",
    "GET /escolas/{escola_id}/alunos/{aluno_id}/perfil",
    "GET /escolas/{escola_id}/analise",
    "GET /escolas/{escola_id}/aparencia",
    "PUT /escolas/{escola_id}/aparencia",
    "DELETE /escolas/{escola_id}/aparencia/logo",
    "POST /escolas/{escola_id}/aparencia/logo",
    "POST /escolas/{escola_id}/assistente",
    "GET /escolas/{escola_id}/assistente/config",
    "PUT /escolas/{escola_id}/assistente/config",
    "POST /escolas/{escola_id}/assistente/config/testar",
    "GET /escolas/{escola_id}/assistente/conversas",
    "GET /escolas/{escola_id}/assistente/conversas/{conversa_id}",
    "GET /escolas/{escola_id}/assistente/status",
    "GET /escolas/{escola_id}/atividade-semanal",
    "GET /escolas/{escola_id}/backup",
    "POST /escolas/{escola_id}/certificados/lote",
    "POST /escolas/{escola_id}/certificados/lote/previa",
    "GET /escolas/{escola_id}/certificados/{aluno_id}",
    "GET /escolas/{escola_id}/comparar",
    "GET /escolas/{escola_id}/configuracoes/dificuldade",
    "PUT /escolas/{escola_id}/configuracoes/dificuldade",
    "GET /escolas/{escola_id}/configuracoes/dificuldade-livro",
    "GET /escolas/{escola_id}/configuracoes/elefante-extra",
    "PUT /escolas/{escola_id}/configuracoes/elefante-extra",
    "POST /escolas/{escola_id}/configuracoes/niveis",
    "POST /escolas/{escola_id}/configuracoes/niveis/padrao",
    "DELETE /escolas/{escola_id}/configuracoes/niveis/{nivel_id}",
    "PUT /escolas/{escola_id}/configuracoes/niveis/{nivel_id}",
    "GET /escolas/{escola_id}/configuracoes/perfil-scoring",
    "PUT /escolas/{escola_id}/configuracoes/perfil-scoring",
    "GET /escolas/{escola_id}/configuracoes/pesos/{namespace}",
    "PUT /escolas/{escola_id}/configuracoes/pesos/{namespace}",
    "GET /escolas/{escola_id}/configuracoes/pontuacao-turma",
    "PUT /escolas/{escola_id}/configuracoes/pontuacao-turma",
    "GET /escolas/{escola_id}/configuracoes/pontuacao/exemplo/elefante",
    "GET /escolas/{escola_id}/configuracoes/pontuacao/exemplo/matific",
    "GET /escolas/{escola_id}/configuracoes/pontuacao/regra",
    "GET /escolas/{escola_id}/configuracoes/referencias",
    "PUT /escolas/{escola_id}/configuracoes/referencias",
    "GET /escolas/{escola_id}/configuracoes/sincronizacao",
    "PUT /escolas/{escola_id}/configuracoes/sincronizacao",
    "GET /escolas/{escola_id}/dashboard",
    "POST /escolas/{escola_id}/dispositivos",
    "POST /escolas/{escola_id}/dispositivos/remover",
    "GET /escolas/{escola_id}/elefante",
    "PUT /escolas/{escola_id}/elefante/{aluno_id}",
    "PUT /escolas/{escola_id}/elefante/{aluno_id}/niveis",
    "GET /escolas/{escola_id}/gamificacao/alunos/{aluno_id}",
    "GET /escolas/{escola_id}/gamificacao/biblioteca",
    "GET /escolas/{escola_id}/gamificacao/conquistas/definicoes",
    "PUT /escolas/{escola_id}/gamificacao/conquistas/definicoes",
    "GET /escolas/{escola_id}/gamificacao/mural",
    "GET /escolas/{escola_id}/gamificacao/ranking-xp",
    "GET /escolas/{escola_id}/importacoes",
    "POST /escolas/{escola_id}/importacoes/analisar",
    "POST /escolas/{escola_id}/importacoes/confirmar",
    "GET /escolas/{escola_id}/importacoes/contagem-revisoes",
    "GET /escolas/{escola_id}/importacoes/identidades/{plataforma}/aluno/{aluno_id}",
    "POST /escolas/{escola_id}/importacoes/identidades/{plataforma}/efetiva",
    "POST /escolas/{escola_id}/importacoes/identidades/{plataforma}/reativar",
    "POST /escolas/{escola_id}/importacoes/matriculas/analisar",
    "POST /escolas/{escola_id}/importacoes/matriculas/confirmar",
    "POST /escolas/{escola_id}/importacoes/recalcular",
    "GET /escolas/{escola_id}/importacoes/revisoes",
    "POST /escolas/{escola_id}/importacoes/revisoes/{revisao_id}/descartar",
    "POST /escolas/{escola_id}/importacoes/revisoes/{revisao_id}/resolver",
    "GET /escolas/{escola_id}/indicadores",
    "GET /escolas/{escola_id}/insights",
    "POST /escolas/{escola_id}/leituras/restaurar-historico",
    "GET /escolas/{escola_id}/livros",
    "POST /escolas/{escola_id}/livros",
    "DELETE /escolas/{escola_id}/livros/{livro_id}",
    "PATCH /escolas/{escola_id}/livros/{livro_id}",
    "GET /escolas/{escola_id}/matific",
    "PUT /escolas/{escola_id}/matific/{aluno_id}",
    "GET /escolas/{escola_id}/nao-aferidos",
    "GET /escolas/{escola_id}/notificacoes",
    "GET /escolas/{escola_id}/painel-publico",
    "PUT /escolas/{escola_id}/painel-publico",
    "POST /escolas/{escola_id}/painel-publico/novo-token",
    "GET /escolas/{escola_id}/painel-publico/qr",
    "GET /escolas/{escola_id}/pesquisa",
    "GET /escolas/{escola_id}/premiacoes",
    "GET /escolas/{escola_id}/professores",
    "POST /escolas/{escola_id}/professores",
    "POST /escolas/{escola_id}/professores/completo",
    "GET /escolas/{escola_id}/professores/duplicados",
    "POST /escolas/{escola_id}/professores/duplicados/corrigir",
    "POST /escolas/{escola_id}/professores/padronizar-usuarios",
    "DELETE /escolas/{escola_id}/professores/{professor_id}",
    "PATCH /escolas/{escola_id}/professores/{professor_id}",
    "POST /escolas/{escola_id}/quest/alunos/{aluno_id}/cartao",
    "GET /escolas/{escola_id}/quest/turmas/{turma_id}/acessos",
    "POST /escolas/{escola_id}/quest/turmas/{turma_id}/cartoes",
    "GET /escolas/{escola_id}/ranking",
    "GET /escolas/{escola_id}/ranking-evolucao",
    "GET /escolas/{escola_id}/ranking/cartaz",
    "GET /escolas/{escola_id}/ranking/frescor",
    "GET /escolas/{escola_id}/ranking/leitura",
    "GET /escolas/{escola_id}/ranking/leitura/turnos",
    "GET /escolas/{escola_id}/ranking/matematica",
    "GET /escolas/{escola_id}/ranking/turmas",
    "POST /escolas/{escola_id}/recalcular",
    "GET /escolas/{escola_id}/relatorios/periodo",
    "GET /escolas/{escola_id}/relatorios/periodo.pdf",
    "GET /escolas/{escola_id}/relatorios/{tipo}",
    "POST /escolas/{escola_id}/restaurar",
    "GET /escolas/{escola_id}/resumo-escola",
    "POST /escolas/{escola_id}/simulador",
    "GET /escolas/{escola_id}/sincronizacao",
    "POST /escolas/{escola_id}/sync/agora",
    "GET /escolas/{escola_id}/sync/alertas",
    "POST /escolas/{escola_id}/sync/alertas/{alerta_id}/resolver",
    "PUT /escolas/{escola_id}/sync/config/{plataforma}",
    "DELETE /escolas/{escola_id}/sync/credenciais/{plataforma}",
    "PUT /escolas/{escola_id}/sync/credenciais/{plataforma}",
    "POST /escolas/{escola_id}/sync/credenciais/{plataforma}/testar",
    "POST /escolas/{escola_id}/sync/elefante/diagnostico",
    "DELETE /escolas/{escola_id}/sync/escola-externa/{plataforma}",
    "GET /escolas/{escola_id}/sync/escola-externa/{plataforma}",
    "PUT /escolas/{escola_id}/sync/escola-externa/{plataforma}",
    "GET /escolas/{escola_id}/sync/execucoes/{execucao_id}",
    "GET /escolas/{escola_id}/sync/historico",
    "GET /escolas/{escola_id}/sync/logs",
    "GET /escolas/{escola_id}/sync/matific/placar-ao-vivo",
    "GET /escolas/{escola_id}/sync/onboarding",
    "GET /escolas/{escola_id}/sync/status",
    "GET /escolas/{escola_id}/turmas",
    "POST /escolas/{escola_id}/turmas",
    "GET /escolas/{escola_id}/turmas/duplicadas",
    "POST /escolas/{escola_id}/turmas/duplicadas/corrigir",
    "POST /escolas/{escola_id}/turmas/excluir",
    "DELETE /escolas/{escola_id}/turmas/{turma_id}",
    "PUT /escolas/{escola_id}/turmas/{turma_id}",
    "GET /escolas/{escola_id}/turmas/{turma_id}/alunos",
    "GET /escolas/{escola_id}/turmas/{turma_id}/resumo",
    "GET /escolas/{escola_id}/usuarios",
    "POST /escolas/{escola_id}/usuarios",
    "DELETE /escolas/{escola_id}/usuarios/{usuario_id}",
    "PATCH /escolas/{escola_id}/usuarios/{usuario_id}",
    "DELETE /escolas/{escola_id}/usuarios/{usuario_id}/permanente",
    "POST /escolas/{escola_id}/usuarios/{usuario_id}/redefinir-senha",
    "GET /escolas/{escola_id}/usuarios/{usuario_id}/turmas",
    "PUT /escolas/{escola_id}/usuarios/{usuario_id}/turmas",
    "GET /escolas/{escola_id}/visao-geral",
    "GET /notificacoes",
    "GET /notificacoes/contador",
    "POST /notificacoes/marcar-lidas",
    "POST /presenca/heartbeat",
    "GET /presenca/sessoes",
    "GET /redes",
    "POST /redes",
    "PATCH /redes/escolas/{escola_id}",
    "GET /redes/gerenciar",
    "GET /redes/panorama-global",
    "PATCH /redes/{rede_id}",
    "GET /redes/{rede_id}/analise/diagnostico",
    "GET /redes/{rede_id}/analise/indicadores",
    "GET /redes/{rede_id}/analise/indicadores/{chave}",
    "GET /redes/{rede_id}/analise/plataformas",
    "GET /redes/{rede_id}/analise/plataformas/evolucao",
    "GET /redes/{rede_id}/analise/relacao",
    "GET /redes/{rede_id}/avaliacoes/correlacao",
    "GET /redes/{rede_id}/avaliacoes/opcoes",
    "GET /redes/{rede_id}/boletim",
    "POST /redes/{rede_id}/casar-inep",
    "GET /redes/{rede_id}/dashboard",
    "GET /redes/{rede_id}/destaques",
    "PUT /redes/{rede_id}/escolas",
    "POST /redes/{rede_id}/geocodificar",
    "GET /redes/{rede_id}/indicadores/ica",
    "POST /redes/{rede_id}/indicadores/ica/aplicar",
    "POST /redes/{rede_id}/indicadores/ica/previa",
    "GET /redes/{rede_id}/indicadores/ideb",
    "POST /redes/{rede_id}/indicadores/ideb/aplicar",
    "GET /redes/{rede_id}/indicadores/ideb/importacoes",
    "POST /redes/{rede_id}/indicadores/ideb/importacoes/{importacao_id}/desfazer",
    "POST /redes/{rede_id}/indicadores/ideb/previa",
    "GET /redes/{rede_id}/indicadores/importacoes",
    "POST /redes/{rede_id}/indicadores/importacoes/{importacao_id}/desfazer",
    "POST /redes/{rede_id}/indicadores/saeb/aplicar",
    "GET /redes/{rede_id}/indicadores/saeb/importacoes",
    "POST /redes/{rede_id}/indicadores/saeb/importacoes/{importacao_id}/desfazer",
    "POST /redes/{rede_id}/indicadores/saeb/previa",
    "GET /redes/{rede_id}/indicadores/saresp",
    "POST /redes/{rede_id}/indicadores/saresp/aplicar",
    "GET /redes/{rede_id}/indicadores/saresp/importacoes",
    "POST /redes/{rede_id}/indicadores/saresp/importacoes/{importacao_id}/desfazer",
    "POST /redes/{rede_id}/indicadores/saresp/previa",
    "GET /redes/{rede_id}/metas",
    "PUT /redes/{rede_id}/metas",
    "DELETE /redes/{rede_id}/metas/{metrica}",
    "GET /redes/{rede_id}/modulos",
    "PUT /redes/{rede_id}/modulos",
    "GET /redes/{rede_id}/publico",
    "PUT /redes/{rede_id}/publico",
    "GET /redes/{rede_id}/ranking",
    "GET /redes/{rede_id}/ranking/frescor",
    "PUT /redes/{rede_id}/usuarios",
    "GET /sistema/diagnostico",
    "GET /sync/dashboard",
})


def _id_rota(rota: APIRoute, metodo: str) -> str:
    return f"{metodo} {rota.path_format.replace('/api/v1', '')}"


_ROTAS = [(r, m) for r in app.routes if isinstance(r, APIRoute)
          for m in sorted(r.methods - {"HEAD"})]


def _categoria(rota_id: str) -> str | None:
    if rota_id in FORA_DA_MATRIZ:
        return "fora"
    if rota_id in POR_TOKEN_PUBLICO:
        return "token"
    if rota_id in ABERTAS:
        return "aberta"
    if rota_id in DA_EQUIPE:
        return "equipe"
    return None


def _divergencias(rotas) -> tuple[list[str], list[str], list[str]]:
    """(rotas do app sem entrada, entradas sem rota no app, rotas em duas categorias)."""
    do_app = {_id_rota(r, m) for r, m in rotas}
    grupos = [set(FORA_DA_MATRIZ), set(ABERTAS), set(POR_TOKEN_PUBLICO), set(DA_EQUIPE)]
    inventario = set().union(*grupos)
    repetidas = sorted(r for r in inventario if sum(r in g for g in grupos) > 1)
    return sorted(do_app - inventario), sorted(inventario - do_app), repetidas


def test_inventario_cobre_todas_as_rotas():
    """A catraca: o inventário é exatamente o conjunto de rotas do app, sem rota nova
    esquecida, sem entrada de rota que já não existe e sem rota em duas categorias."""
    novas, sumidas, repetidas = _divergencias(_ROTAS)
    assert not novas, (
        "Rota nova sem entrada na matriz RBAC (tests/test_rbac_matriz.py): "
        f"{novas}. Ponha cada uma em DA_EQUIPE (exige login), ABERTAS, POR_TOKEN_PUBLICO "
        "ou FORA_DA_MATRIZ (com o motivo).")
    assert not sumidas, f"Entradas da matriz RBAC sem rota no app (remova-as): {sumidas}"
    assert not repetidas, f"Rotas em mais de uma categoria da matriz RBAC: {repetidas}"
    assert len(_ROTAS) > 200            # o leitor das rotas achou o app inteiro


def test_catraca_pega_rota_nova_sem_entrada():
    """A catraca funciona: uma rota que o app ganhasse sem entrada no inventário seria
    apontada pelo teste do inventário e reprovaria o próprio ``test_matriz``."""
    nova = APIRoute("/api/v1/escolas/{escola_id}/rota-nova-sem-entrada",
                    endpoint=lambda escola_id: None, methods=["POST"])
    novas, sumidas, _ = _divergencias([*_ROTAS, (nova, "POST")])
    assert novas == ["POST /escolas/{escola_id}/rota-nova-sem-entrada"]
    assert not sumidas
    assert _categoria("POST /escolas/{escola_id}/rota-nova-sem-entrada") is None


# ------------------------------------------------------------------- alvos e perfis
def _alvo(ids: dict, esc: str) -> dict:
    """ids internos de uma escola-alvo ('Y', 'X2', 'X', 'T2')."""
    if esc == "T2":
        return dict(escola=ids["eX"], rede=ids["rA"], aluno=ids["aT2_1"], turma=ids["tT2"],
                    professor=ids["pT2"], usuario=ids["u_prof_t2"], livro=ids["lX"],
                    revisao=ids["revX"], execucao=ids["exeX"], alerta=ids["aleX"],
                    conversa=ids["conv_prof_t2"], nivel=ids["nivX"],
                    token_push="ExponentPushToken[prof_t2VAZA]", importacao=ids["impX"])
    if esc == "X":
        return dict(escola=ids["eX"], rede=ids["rA"], aluno=ids["aT_1"], turma=ids["tT"],
                    professor=ids["pT"], usuario=ids["u_prof_t"], livro=ids["lX"],
                    revisao=ids["revX"], execucao=ids["exeX"], alerta=ids["aleX"],
                    conversa=ids["conv_coord_x"], nivel=ids["nivX"],
                    token_push="ExponentPushToken[nao-existe]", importacao=ids["impX"])
    rede = ids["rB"] if esc == "Y" else ids["rA"]
    return dict(escola=ids["e" + esc], rede=rede, aluno=ids["a%s_1" % esc], turma=ids["t" + esc],
                professor=ids["p" + esc], usuario=ids["u_coord_" + esc.lower()],
                livro=ids["l" + esc], revisao=ids["rev" + esc], execucao=ids["exe" + esc],
                alerta=ids["ale" + esc], conversa=ids["conv_coord_" + esc.lower()],
                nivel=ids["niv" + esc], importacao=ids["imp" + esc],
                token_push=f"ExponentPushToken[coord_{esc.lower()}VAZA]")


# Quem é "de fora" em cada cenário (para a checagem de escrita).
def _ids_proibidos(ids: dict, esc: str) -> dict:
    if esc == "Y":
        return {"escola": {ids["eY"]}, "rede": {ids["rB"]},
                "aluno": {ids["aY_1"], ids["aY_2"]}, "turma": {ids["tY"]},
                "usuario": {ids["u_coord_y"], ids["u_admin_y"], ids["u_prof_y"]},
                "professor": {ids["pY"]}}
    if esc == "X2":
        return {"escola": {ids["eX2"]}, "rede": set(), "aluno": {ids["aX2_1"]},
                "turma": {ids["tX2"]}, "usuario": {ids["u_coord_x2"], ids["u_prof_x2"]},
                "professor": {ids["pX2"]}}
    if esc == "Xtoda":
        return {"escola": {ids["eX"]}, "rede": set(),
                "aluno": {ids["aT_1"], ids["aT_2"], ids["aT2_1"]}, "turma": {ids["tT"], ids["tT2"]},
                "usuario": {ids["u_coord_x"], ids["u_admin_x"], ids["u_prof_t"], ids["u_prof_t2"]},
                "professor": {ids["pT"], ids["pT2"]}}
    if esc == "T2":
        return {"escola": set(), "rede": set(), "aluno": {ids["aT2_1"]},
                "turma": {ids["tT2"]}, "usuario": {ids["u_prof_t2"]}, "professor": {ids["pT2"]}}
    return {k: set() for k in ("escola", "rede", "aluno", "turma", "usuario", "professor")}


# Nome de criança (de qualquer escola) — a Secretaria nunca vê (LGPD).
_PII_SEC = ("CRIANCA XT", "T2 CRIANCA", "X2 CRIANCA", "VAZAY")


def _cenarios():
    """(perfil, rótulo, alvo_do_caminho, alvo_interno, marcadores_proibidos, caminho_alheio)"""
    c = []
    for p in ("sec_a", "coord_x", "admin_x", "prof_t"):
        c.append((p, "alheia_Y", "Y", "Y", ("VAZAY",), True))
    for p in ("coord_x", "admin_x", "prof_t"):
        c.append((p, "irma_X2", "X2", "X2", ("VAZAX2",), True))
    for p in ("global", "sec_a", "coord_x", "admin_x", "prof_t"):
        c.append((p, "interno_Y", "X", "Y", ("VAZAY",), False))
    c.append(("prof_t", "turma_T2", "X", "T2", ("VAZAT2",), False))
    c.append(("prof_t", "propria", "X", "X", ("VAZAT2", "VAZAY", "VAZAX2"), False))
    c.append(("coord_x", "propria", "X", "X", ("VAZAY", "VAZAX2"), False))
    c.append(("admin_x", "propria", "X", "X", ("VAZAY", "VAZAX2"), False))
    c.append(("sec_a", "propria", "X", "X", _PII_SEC, False))
    c.append(("global", "propria", "X", "X", (), False))
    # Sem os filtros opcionais da query (listas "cheias" da escola).
    c.append(("prof_t", "propria_livre", "X", "X", ("VAZAT2", "VAZAY", "VAZAX2"), False))
    c.append(("sec_a", "propria_livre", "X", "X", _PII_SEC, False))
    c.append(("coord_x", "propria_livre", "X", "X", ("VAZAY", "VAZAX2"), False))
    c.append((None, "sem_login", "X", "X", _PII_SEC, True))
    c.append(("sec_prom", "alheia_Y", "Y", "Y", ("VAZAY",), True))
    c.append(("sec_prom", "interno_Y", "X", "Y", ("VAZAY",), False))
    c.append(("sec_prom", "propria", "X", "X", _PII_SEC, False))
    c.append(("sec_prom", "propria_livre", "X", "X", _PII_SEC, False))
    # Caminho 100% próprio (escola e ids internos de X); SÓ o corpo/query com ids de Y.
    for p in ("global", "coord_x", "admin_x"):
        c.append((p, "corpo_Y", "X", "X>Y", ("VAZAY",), False))
    c.append(("prof_t", "corpo_T2", "X", "X>T2", ("VAZAT2",), False))
    return c


# --------------------------------------------------------------- geração de pedido
_POR_NOME = {
    "aluno_id": "aluno", "aluno_ids": "aluno", "manter_id": "aluno", "remover_id": "aluno",
    "aluno_origem_id": "aluno", "turma_id": "turma", "turma_ids": "turma",
    "turma_origem_id": "turma", "criar_em_turma_id": "turma", "professor_id": "professor",
    "usuario_id": "usuario", "usuario_ids": "usuario", "livro_id": "livro",
    "revisao_id": "revisao", "execucao_id": "execucao", "alerta_id": "alerta",
    "conversa_id": "conversa", "nivel_id": "nivel", "escola_id": "escola",
    "escola_ids": "escola", "rede_id": "rede", "token_push": "token_push",
    "importacao_id": "importacao",
}
_VALORES = {
    "confirmacao": "EXCLUIR", "senha": "Zq8!vT3#pL6@wR1x", "email": "sonda.nova@escola-sint.com.br",
    "nome": "NOME SONDA", "plataforma": "elefante", "motivo": "sonda de autorizacao",
    "id_externo_efetivo": "ext-Y_1", "id_externo": "ext-Y_1", "acao": "transferir",
    "cargo": "professor", "pergunta": "quem le mais?", "codigo": "ABC123",
    "provedor": "local", "metrica": "media_geral", "data_referencia": "2026-05-19",
    "cor_primaria": "#112233", "hora_local": "03:00", "usuario": "sonda", "modo": "auto",
    "indicador": "livros_unicos", "raridade": "comum",
}

_P = "/api/v1/escolas/{escola_id}"


def _ajustes(ids, metodo, caminho, kw, corpo_alvo):
    """Corpos VÁLIDOS para as rotas cujo corpo genérico cai em 400/422 — senão a
    checagem do id interno nem chega a rodar. ``corpo_alvo`` = ids do cenário."""
    j = kw.get("json")
    a = corpo_alvo
    proprio = ids["aT_1"]
    outro = a["aluno"] if a["aluno"] != proprio else ids["aT_2"]
    mc = (metodo, caminho)
    if mc == ("GET", _P + "/alunos/fundir/previa"):
        kw["params"].update(manter_id=proprio, remover_id=outro)
    elif mc == ("POST", _P + "/alunos/fundir"):
        kw["json"] = {"manter_id": proprio, "remover_id": outro, "confirmacao": "FUNDIR",
                      "confirmar_conflito": "FUNDIR MESMO COM CONFLITO"}
    elif mc == ("POST", _P + "/alunos/duplicados/corrigir"):
        kw["json"] = {"loser_ids": [outro], "confirmacao": "FUNDIR"}
    elif mc == ("GET", _P + "/ranking/turmas"):
        kw["params"]["dimensao"] = "leitura"
    elif mc == ("PUT", _P + "/painel-publico"):
        kw["json"] = {"ativo": True, "slides": ["ranking"], "intervalo_s": 15,
                      "max_posicoes": 10, "anonimizar": False, "confirmar_exposicao": True}
    elif mc == ("POST", _P + "/dispositivos"):
        kw["json"] = {"token_push": a["token_push"], "plataforma": "android"}
    elif mc == ("POST", _P + "/importacoes/revisoes/{revisao_id}/resolver"):
        kw["json"] = {"aluno_id": a["aluno"], "criar_em_turma_id": None}
    elif mc == ("POST", _P + "/importacoes/confirmar"):
        kw["json"] = {"plataforma": "elefante", "formato": "resumo", "tipo": "texto",
                      "arquivo_token": None, "linhas": [
                          {"nome": "NOME QUALQUER SONDA", "aluno_id": a["aluno"],
                           "dados": {"livros_unicos": 9, "tempo_leitura_min": 99,
                                     "questoes_tentativas": 9, "questoes_acertos": 9}},
                          {"nome": "NOVA SONDA", "criar_em_turma_id": a["turma"],
                           "dados": {"livros_unicos": 1}}]}
    elif mc == ("POST", _P + "/importacoes/identidades/{plataforma}/efetiva"):
        kw["json"] = {"aluno_id": a["aluno"], "id_externo_efetivo": "ext-T_1",
                      "aposentar": ["ext-Y_1"], "motivo": "sonda de autorizacao"}
    elif mc == ("POST", _P + "/importacoes/identidades/{plataforma}/reativar"):
        kw["json"] = {"aluno_id": proprio, "id_externo": "ext-Y_1", "motivo": "sonda autorizacao"}
    elif mc == ("PUT", _P + "/turmas/{turma_id}"):
        kw["json"] = {"nome": "4º Ano A", "ano_escolar": "4º Ano", "ano_letivo": 2026,
                      "professor_id": a["professor"], "turno": "manha"}
    elif mc == ("PATCH", "/api/v1/escolas/{escola_id}"):
        kw["json"] = {"nome": "ESCOLA X SINT", "cidade": "Cidade Sint"}
    elif mc == ("PUT", _P + "/gamificacao/conquistas/definicoes") and j:
        for c in j.get("conquistas", []):
            c.update(indicador="livros_unicos", plataforma="elefante", limite=3, xp=10,
                     codigo="sonda_cod", criada_em="2026-05-19T10:00:00")
    elif mc == ("PUT", _P + "/sync/escola-externa/{plataforma}"):
        kw["json"] = {"id_externo": "123", "nome": "Escola Externa Sint"}
    elif mc == ("POST", _P + "/usuarios"):
        kw["json"] = {"nome": "Nova Conta Sonda", "email": "nova.conta@escola-sint.com.br",
                      "senha": "Zq8!vT3#pL6@wR1x", "cargo": "professor"}
    elif mc in (("GET", _P + "/relatorios/periodo"), ("GET", _P + "/relatorios/periodo.pdf")):
        if "aluno_id" in kw["params"]:
            kw["params"]["escopo"] = "aluno"
            kw["params"].pop("turma_id", None)
    elif mc == ("GET", _P + "/comparar"):
        kw["params"].update(tipo_a="turma", id_a=a["turma"], tipo_b="aluno", id_b=a["aluno"])
    elif mc == ("POST", _P + "/assistente") and j:
        j["conversa_id"] = a["conversa"]
    return kw


def _amostra_do_padrao(padrao: str):
    m = re.fullmatch(r"\^\(([^)]*)\)\??\$", padrao)
    if m:
        return [x for x in m.group(1).split("|") if x][0]
    return {r"^#[0-9a-fA-F]{6}$": "#112233", r"^\d{2}:\d{2}$": "03:00",
            r"^\d{0,8}$": "35"}.get(padrao, "x")


class Gerador:
    """Valor de exemplo para um schema do OpenAPI; campos de id recebem os do alvo."""

    def __init__(self, spec, alvo):
        self.comps = spec.get("components", {}).get("schemas", {})
        self.alvo = alvo

    def _res(self, s):
        while "$ref" in s:
            s = self.comps[s["$ref"].split("/")[-1]]
        return s

    def valor(self, s, nome=None, prof=0):
        s = self._res(s or {})
        if prof > 6:
            return None
        if "anyOf" in s or "oneOf" in s:
            ops = [self._res(o) for o in s.get("anyOf", s.get("oneOf", []))]
            ops = [o for o in ops if o.get("type") != "null"] or ops
            return self.valor(ops[0], nome, prof)
        if "allOf" in s:
            return self.valor(s["allOf"][0], nome, prof)
        t = s.get("type")
        kind = _POR_NOME.get(nome or "")
        if kind and kind in self.alvo:
            v = self.alvo[kind]
            return [v] if t == "array" else v
        if "enum" in s:
            return s["enum"][0]
        if "const" in s:
            return s["const"]
        if t == "object" or "properties" in s:
            return {k: self.valor(v, k, prof + 1) for k, v in s.get("properties", {}).items()}
        if t == "array":
            return [self.valor(s.get("items", {}), (nome or "")[:-1] if nome else None, prof + 1)]
        if t == "string":
            if nome in _VALORES:
                return _VALORES[nome]
            if "pattern" in s:
                return _amostra_do_padrao(s["pattern"])
            fmt = s.get("format")
            if fmt == "email":
                return "sonda.nova@escola-sint.com.br"
            if fmt == "date":
                return "2026-05-19"
            if fmt == "date-time":
                return "2026-05-19T10:00:00"
            if fmt == "binary":
                return "arquivo"
            return "sonda" + ("x" * max(0, s.get("minLength", 0) - 5))
        if t == "integer":
            return max(1, s.get("minimum", 1))
        if t == "number":
            return 1.0
        if t == "boolean":
            return False
        return None


def _pedido(rota: APIRoute, metodo: str, spec, alvo_caminho: dict, alvo_interno: dict,
            preencher: bool = True, alvo_corpo: dict | None = None, ids: dict | None = None):
    """URL + kwargs do TestClient. Caminho: escola/rede do alvo_caminho, os demais
    ids do alvo_interno; corpo e query: ids do alvo_corpo."""
    op = spec["paths"][rota.path_format][metodo.lower()]
    url = rota.path_format
    alvo_corpo = alvo_corpo or alvo_interno
    fixos = {"namespace": "matific", "tipo": "alunos", "chave": "saeb",
             "metrica": "media_geral", "plataforma": "elefante", "token": TOKEN_PAINEL_X}
    for p in op.get("parameters", []):
        if p["in"] != "path":
            continue
        n = p["name"]
        if n == "escola_id":
            v = alvo_caminho["escola"]
        elif n == "rede_id":
            v = alvo_caminho["rede"]
        elif n in _POR_NOME and _POR_NOME[n] in alvo_interno:
            v = alvo_interno[_POR_NOME[n]]
        elif n in fixos:
            v = fixos[n]
        else:
            v = 1
        url = url.replace("{" + n + "}", str(v))
    ger = Gerador(spec, alvo_corpo)
    params = {}
    for p in op.get("parameters", []):
        if p["in"] != "query":
            continue
        n = p["name"]
        if n in ("q", "busca"):
            params[n] = "CRIAN"           # casa com o nome de TODAS as crianças do mundo
            continue
        if not preencher and not p.get("required"):
            continue
        if n in _POR_NOME and _POR_NOME[n] in alvo_corpo:
            params[n] = alvo_corpo[_POR_NOME[n]]
        elif n in ("id_a", "id_b"):
            params[n] = alvo_corpo["aluno"]
        elif n in ("tipo_a", "tipo_b"):
            params[n] = "aluno"
        elif n == "formato":
            params[n] = "csv"
        elif n == "confirmacao":
            params[n] = "coord_y@sint.local"
        elif n == "tipo":
            params[n] = "brasao"
        elif n == "indicador":
            params[n] = "saeb"
        elif p.get("required"):
            params[n] = ger.valor(p.get("schema", {}), n)
    kw = {"params": params}
    rb = op.get("requestBody")
    if rb:
        ct = next(iter(rb["content"]))
        sch = rb["content"][ct]["schema"]
        corpo = ger.valor(sch)
        if ct.startswith("multipart"):
            arquivos, dados = {}, {}
            props = ger._res(sch).get("properties", {})
            for k, v in (corpo or {}).items():
                ps = ger._res(props.get(k, {}))
                binario = ps.get("format") == "binary" or any(
                    ger._res(o).get("format") == "binary" for o in ps.get("anyOf", []))
                if binario:
                    arquivos[k] = ("sonda.csv", b"nome;turma\nCRIANCA SONDA;4A\n", "text/csv")
                elif v is not None:
                    dados[k] = str(v).lower() if isinstance(v, bool) else str(v)
            kw["files"] = arquivos or None
            kw["data"] = dados
        elif ct.startswith("application/json"):
            kw["json"] = corpo
        else:
            kw["data"] = corpo
    if ids is not None:
        kw = _ajustes(ids, metodo, rota.path_format, kw, alvo_corpo)
    return url, kw


# ---------------------------------------------------------- comparação do banco
_TABELAS_IGNORADAS = {"alembic_version"}
_COLS_VOLATEIS = {"ultimo_acesso", "visto_em", "updated_at"}


def _linhas_de_fora(antes: dict, depois: dict, proibidos: dict) -> list[str]:
    achados = []
    col_kind = {"escola_id": "escola", "rede_id": "rede", "aluno_id": "aluno",
                "aluno_escolhido_id": "aluno", "turma_id": "turma", "usuario_id": "usuario",
                "professor_id": "professor"}
    id_kind = {"escolas": "escola", "redes": "rede", "alunos": "aluno", "turmas": "turma",
               "usuarios": "usuario", "professores": "professor"}
    for tab, (cols, linhas_d) in depois.items():
        if tab in _TABELAS_IGNORADAS:
            continue
        linhas_a = antes.get(tab, (cols, []))[1]
        idx_vol = [i for i, c in enumerate(cols) if c in _COLS_VOLATEIS]

        def norm(lin):
            return tuple(None if i in idx_vol else v for i, v in enumerate(lin))
        a, d = {norm(x) for x in linhas_a}, {norm(x) for x in linhas_d}
        for tipo, conj in (("+", d - a), ("-", a - d)):
            for lin in conj:
                reg = dict(zip(cols, lin))
                hit = [c for c, k in col_kind.items() if reg.get(c) in proibidos.get(k, ())]
                if tab in id_kind and reg.get("id") in proibidos.get(id_kind[tab], ()):
                    hit.append("id")
                if hit:
                    achados.append(f"{tipo}{tab}{{{','.join(hit)}}}")
    for tab in antes:
        if tab not in depois and tab not in _TABELAS_IGNORADAS:
            achados.append(f"-tabela {tab}")
    return sorted(set(achados))


def _escaladas(antes: dict, depois: dict) -> list[str]:
    cols, la = antes["usuarios"]
    _, ld = depois["usuarios"]
    i = {c: n for n, c in enumerate(cols)}
    a = {r[i["id"]]: r for r in la}
    out = []
    for r in ld:
        uid = r[i["id"]]
        velho = a.get(uid)
        if velho is None:
            if r[i["is_global"]] or r[i["rede_id"]] is not None:
                out.append(f"nova conta {uid} global/rede")
            continue
        for c in ("is_global", "rede_id", "escola_id"):
            if velho[i[c]] != r[i[c]]:
                out.append(f"conta {uid} {c}: {velho[i[c]]}->{r[i[c]]}")
        if velho[i["cargo"]] != r[i["cargo"]] and r[i["cargo"]] in ("admin", "coordenador"):
            out.append(f"conta {uid} cargo: {velho[i['cargo']]}->{r[i['cargo']]}")
    return out


# Escritas "de fora" que são o PAPEL da rota (não vazamento):
#  * o Admin Global move escolas entre redes e designa a Secretaria (PUT /redes/...);
#  * o aparelho de push é upsert pelo token (segredo do celular): quem registra o token
#    passa a ser o dono dele — decisão documentada em routers/mobile.py.
_ESCRITA_ESPERADA = {
    ("PUT", "/api/v1/redes/{rede_id}/escolas"): {"global"},
    ("PUT", "/api/v1/redes/{rede_id}/usuarios"): {"global"},
    ("POST", "/api/v1/escolas/{escola_id}/dispositivos"): {"global", "coord_x", "admin_x", "prof_t"},
}


# --------------------------------------------------------------------- a matriz
def _publico(mundo, rota, metodo):
    """Rotas SEM login por token: o token da escola X não abre aluno de outra escola
    nem aluno fora do painel; token inexistente = 404."""
    ids = mundo["ids"]
    cli = TestClient(app, raise_server_exceptions=False)
    if "{aluno_id}" in rota.path_format:
        casos = [(TOKEN_PAINEL_X, ids["aY_1"]), (TOKEN_PAINEL_X, ids["aX2_1"]),
                 ("nao-existe", ids["aT_1"])]
    else:
        casos = [("nao-existe", None)]
    falhas = []
    for tok, aid in casos:
        url = rota.path_format.replace("{token}", tok)
        if aid is not None:
            url = url.replace("{aluno_id}", str(aid))
        banco = Banco(mundo["modelo"])
        try:
            r = cli.request(metodo, url)
        finally:
            banco.fechar()
        texto, _ = texto_da_resposta(r)
        if r.status_code != 404 or "VAZA" in texto:
            falhas.append(f"{url} -> {r.status_code} {texto[:120]}")
    assert not falhas, " | ".join(falhas)


@pytest.mark.parametrize("rota_metodo", _ROTAS, ids=[_id_rota(*x) for x in _ROTAS])
def test_matriz(mundo, rota_metodo):
    rota, metodo = rota_metodo
    categoria = _categoria(_id_rota(rota, metodo))
    assert categoria is not None, (
        f"{_id_rota(rota, metodo)}: rota sem entrada na matriz RBAC. Ponha-a em DA_EQUIPE, "
        "ABERTAS, POR_TOKEN_PUBLICO ou FORA_DA_MATRIZ (tests/test_rbac_matriz.py).")
    if categoria == "fora":
        pytest.skip(FORA_DA_MATRIZ[_id_rota(rota, metodo)])
    if categoria == "token":
        return _publico(mundo, rota, metodo)
    spec = app.openapi()
    ids = mundo["ids"]
    violacoes = []
    registros = []
    cli = TestClient(app, raise_server_exceptions=False)
    for perfil, rotulo, esc_cam, esc_int, marcas, caminho_alheio in _cenarios():
        if rotulo == "sem_login" and categoria == "aberta":
            continue
        alvo_cam = _alvo(ids, esc_cam)
        if ">" in esc_int:
            esc_int, esc_corpo = esc_int.split(">")
        else:
            esc_corpo = esc_int
        url, kw = _pedido(rota, metodo, spec, alvo_cam, _alvo(ids, esc_int),
                          preencher=not rotulo.endswith("_livre"),
                          alvo_corpo=_alvo(ids, esc_corpo), ids=ids)
        banco = Banco(mundo["modelo"])
        try:
            antes = banco.retrato()
            cab = {"Authorization": f"Bearer {mundo['tokens'][perfil]}"} if perfil else {}
            resp = cli.request(metodo, url, headers=cab, **kw)
            depois = banco.retrato()
        finally:
            banco.fechar()
        texto, ilegivel = texto_da_resposta(resp)
        vaza = [mk for mk in marcas if mk in texto]
        sem_escopo = "{escola_id}" not in rota.path_format and "{rede_id}" not in rota.path_format
        if perfil == "global" and sem_escopo:
            vaza = []          # listas globais do admin global: ver tudo é o papel dele
        escritas = _linhas_de_fora(antes, depois, _ids_proibidos(ids, esc_int if esc_int != "X" else "-"))
        if esc_corpo != esc_int:
            escritas += _linhas_de_fora(antes, depois, _ids_proibidos(ids, esc_corpo))
        if esc_cam != esc_int:
            escritas += _linhas_de_fora(antes, depois, _ids_proibidos(ids, esc_cam if esc_cam != "X" else "-"))
        if perfil in ("sec_a", "sec_prom"):
            # A Secretaria não escreve em escola nenhuma (nem da própria rede).
            escritas += _linhas_de_fora(antes, depois, _ids_proibidos(ids, "Xtoda"))
        escalada = [] if perfil == "global" else _escaladas(antes, depois)
        if SAIDA:
            registros.append({"rota": _id_rota(rota, metodo), "perfil": perfil,
                              "cenario": rotulo, "url": url, "status": resp.status_code,
                              "vaza": vaza, "escrita_de_fora": sorted(set(escritas)),
                              "escalada": escalada, "corpo": texto[:300]})
        if (metodo, rota.path_format) in _ESCRITA_ESPERADA and (
                perfil in _ESCRITA_ESPERADA[(metodo, rota.path_format)]):
            escritas = []
        prob = []
        if vaza:
            prob.append(f"vaza {vaza}")
        if ilegivel:
            prob.append(f"resposta não lida {ilegivel}")
        if escritas:
            prob.append(f"escreve fora {sorted(set(escritas))}")
        if escalada:
            prob.append(f"escalada {escalada}")
        if rotulo == "sem_login" and resp.status_code < 400:
            prob.append(f"sem login -> {resp.status_code}")
        if caminho_alheio and rotulo != "sem_login" and resp.status_code < 300 and not sem_escopo:
            prob.append(f"caminho alheio -> {resp.status_code}")
        if resp.status_code >= 500:
            prob.append(f"5xx {resp.status_code}")
        if prob:
            violacoes.append(f"[{perfil}/{rotulo}] {metodo} {url} -> {resp.status_code}: "
                             + "; ".join(prob))
    if SAIDA:
        with open(SAIDA, "a", encoding="utf-8", newline="\n") as fh:
            for reg in registros:
                fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
    assert not violacoes, "\n".join(violacoes)
