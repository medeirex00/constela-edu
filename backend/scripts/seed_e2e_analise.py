"""Seed do E2E da ANÁLISE EDUCACIONAL (Playwright) — dados 100% INVENTADOS.

Cria, num SQLite DESCARTÁVEL, o mundo que o teste ponta a ponta percorre
(``apps/web/e2e-analise/analise.spec.ts``, config ``apps/web/playwright.analise.config.ts``):

* os indicadores oficiais SINTÉTICOS de ``tests/test_analise_base.mundo_indicadores``
  (as MESMAS fábricas dos testes do backend — decisão D13: nenhum número, nome, INEP ou
  IBGE real): uma rede com IBGE inventado, 5 escolas (4 com INEP inventado e a "Gama"
  sem INEP), ICA da rede (2023 participação baixa, 2024 = meta, 2025 abaixo da meta),
  SARESP 2025 da rede e por escola com IEE/TPS (Beta com TPS = 0), Ideb 2019–2023 da
  rede e por escola, Saeb da rede (planilha) e da Alfa, e a "Estimativa Constela" (mais
  números sem registro oficial) à parte;
* as plataformas no ANO CORRENTE (o ano letivo ativo das escolas passa a ser o ano de
  hoje em Brasília): turmas de 2º e 5º ano em todas as escolas, crianças fictícias,
  leituras e retratos do Elefante e retratos do Matific. A Beta fica SEM coleta do
  Elefante (ausência ≠ zero) e a Ébano tem um 3º ano com 3 crianças (célula suprimida,
  com a supressão complementar do 5º ano);
* quatro contas com senhas de TESTE vindas do ambiente (nunca padrão no código):
    - global@analise-e2e.local      admin global          E2E_ANALISE_SENHA_GLOBAL
    - secretaria@analise-e2e.local  Secretaria (coordenador + rede_id)
                                                          E2E_ANALISE_SENHA_SECRETARIA
    - coord@analise-e2e.local       coordenador da Alfa   E2E_ANALISE_SENHA_COORD
    - prof@analise-e2e.local        professor da Alfa     E2E_ANALISE_SENHA_PROF

Relação com plataformas, por construção: NÃO calculável. As avaliações vão até 2025 e as
plataformas são do ano corrente (``periodo_sem_sobreposicao``) — e, mesmo no mesmo ano,
a rede tem menos de 8 escolas (``N_MINIMO``). A tela mostra os motivos e o "lado a lado".

SEGURANÇA DO BANCO: o script APAGA o arquivo do ``DATABASE_URL`` antes de recriar o
schema pelas migrações do Alembic. Por isso só aceita ``sqlite:///<caminho absoluto>.db``
DENTRO de ``E2E_ANALISE_PASTA`` (pasta descartável escolhida por quem roda) e recusa
qualquer outro destino (PostgreSQL, ``:memory:``, caminho relativo, fora da pasta,
atalho/junção, variável ausente).

Uso:
    python scripts/seed_e2e_analise.py                 # só semeia
    python scripts/seed_e2e_analise.py --servir 8010   # semeia e sobe a API em 127.0.0.1

Com ``--servir``, o MESMO processo sobe o uvicorn importando ``app.main`` com
``app.core.automacao.iniciar_verificacao`` neutralizado (o boot não chama geo-IP nem abre
o Chromium) e com as conexões de saída limitadas ao loopback (nada sai da máquina).
NUNCA rode em produção: as senhas são conhecidas por definição.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from scripts._saida import forcar_saida_utf8  # noqa: E402

# Única pasta onde este script aceita APAGAR e recriar um banco: a que quem roda
# escolhe, de propósito, em E2E_ANALISE_PASTA (caminho absoluto; a config do
# Playwright cria uma pasta própria no diretório temporário do sistema). Sem ela,
# o script recusa — nunca há pasta padrão no código.
RAIZ_PERMITIDA = os.environ.get("E2E_ANALISE_PASTA", "").strip()

SENHAS_ENV = {
    "global": "E2E_ANALISE_SENHA_GLOBAL",
    "secretaria": "E2E_ANALISE_SENHA_SECRETARIA",
    "coord": "E2E_ANALISE_SENHA_COORD",
    "prof": "E2E_ANALISE_SENHA_PROF",
}
EMAILS = {
    "global": "global@analise-e2e.local",
    "secretaria": "secretaria@analise-e2e.local",
    "coord": "coord@analise-e2e.local",
    "prof": "prof@analise-e2e.local",
}


def _recusar(motivo: str) -> None:
    sys.stderr.write(f"seed_e2e_analise: RECUSADO — {motivo}\n")
    raise SystemExit(2)


def _dentro(filho: str, pai: str) -> bool:
    f, p = os.path.normcase(filho), os.path.normcase(pai)
    return f == p or f.startswith(p.rstrip("\\/") + os.sep)


def caminho_do_banco(url: str) -> Path:
    """O arquivo SQLite do ``url`` — só se estiver DENTRO de ``RAIZ_PERMITIDA``."""
    prefixo = "sqlite:///"
    if not url.startswith(prefixo):
        _recusar("DATABASE_URL precisa ser sqlite:///<caminho absoluto>.db "
                 f"(recebido: {url.split(':', 1)[0] or 'vazio'})")
    bruto = url[len(prefixo):]
    if not bruto or bruto.startswith(":memory:") or "?" in bruto or "#" in bruto:
        _recusar("DATABASE_URL precisa apontar para um ARQUIVO .db, sem parâmetros")
    arquivo = Path(bruto)
    if not arquivo.is_absolute():
        _recusar(f"caminho relativo não é aceito: {bruto}")
    if arquivo.suffix.lower() != ".db":
        _recusar(f"o arquivo precisa terminar em .db: {arquivo.name}")
    if not RAIZ_PERMITIDA or not os.path.isabs(RAIZ_PERMITIDA):
        _recusar("defina E2E_ANALISE_PASTA com o caminho ABSOLUTO da pasta descartável "
                 "onde o banco pode ser apagado e recriado")
    raiz = os.path.realpath(RAIZ_PERMITIDA)
    if not os.path.isdir(raiz):
        _recusar(f"a pasta permitida não existe: {RAIZ_PERMITIDA}")
    pai = os.path.realpath(str(arquivo.parent))
    if not _dentro(pai, raiz):
        _recusar(f"o banco precisa ficar dentro de {RAIZ_PERMITIDA} (recebido: {arquivo})")
    alvo = Path(pai) / arquivo.name
    if alvo.is_symlink() or (alvo.exists() and not alvo.is_file()):
        _recusar(f"o alvo não é um arquivo comum: {alvo}")
    return alvo


def senhas_de_teste() -> dict[str, str]:
    faltando = [v for v in SENHAS_ENV.values() if len(os.environ.get(v, "")) < 8]
    if faltando:
        _recusar("defina as senhas de TESTE (8+ caracteres) no ambiente: " + ", ".join(faltando))
    return {perfil: os.environ[var] for perfil, var in SENHAS_ENV.items()}


def apagar_banco(alvo: Path) -> None:
    for sufixo in ("", "-wal", "-shm", "-journal"):
        try:
            Path(str(alvo) + sufixo).unlink()
        except FileNotFoundError:
            pass


# --- Plataformas no ano corrente --------------------------------------------------------

# (escola, série → nº de crianças). Todas as células com ≥ 5 crianças ficam visíveis; o 3º
# ano da Ébano (3) é suprimido e puxa a supressão complementar do 5º ano dela (5).
TURMAS = {
    "alfa": {"2º Ano": 6, "5º Ano": 7},
    "beta": {"2º Ano": 5, "5º Ano": 8},
    "delta": {"2º Ano": 6, "5º Ano": 6},
    "ebano": {"2º Ano": 7, "3º Ano": 3, "5º Ano": 5},
    "gama": {"2º Ano": 5, "5º Ano": 6},
}
SEM_ELEFANTE = {"beta"}                     # sem coleta nenhuma do Elefante
NIVEIS = {"alfa": ("K", "L"), "beta": ("J", "K"), "delta": ("L", "M"),
          "ebano": ("K", "M"), "gama": ("J", "L")}


def semear(db, senhas: dict[str, str]) -> dict:
    from datetime import date, datetime, time, timedelta

    from app.core.security import hash_senha
    from app.core.tempo import hoje_br
    from app.models import Usuario
    from tests import test_analise_base as fab

    base = fab.mundo_indicadores(db)
    rede, escolas = base["rede"], base["escolas"]

    hoje = hoje_br()
    ano = hoje.year
    inicio_coleta = date(ano, 1, 2)
    ultima_coleta = max(date(ano, 1, 3), hoje - timedelta(days=1))
    dia_leitura = inicio_coleta + (ultima_coleta - inicio_coleta) / 2

    def quando(d: date, h: int, m: int = 0) -> datetime:
        return datetime.combine(d, time(h, m))

    for escola in escolas.values():
        escola.ano_letivo_ativo = ano
    db.flush()

    criancas = 0
    for chave, series in TURMAS.items():
        escola = escolas[chave]
        nivel_a, nivel_b = NIVEIS[chave]
        estante = fab.livros(db, escola, 4, nivel_a) + fab.livros(db, escola, 3, nivel_b)
        for ano_escolar, n in series.items():
            alunos = fab.turma_com_alunos(db, escola, ano_escolar, n, ano=ano)
            criancas += n
            for i, aluno in enumerate(alunos):
                # Elefante: 0 a 3 livros novos no ano (quem não leu conta no recorte).
                if chave not in SEM_ELEFANTE:
                    lidos = estante[(i * 2) % 4:(i * 2) % 4 + (i % 4)]
                    fab.ler(db, escola, aluno, lidos, quando(dia_leitura, 14), minutos=10 + i)
                    fab.retrato_elefante(db, escola, aluno, quando(inicio_coleta, 3, 10),
                                         tentativas=10, acertos=5)
                    fab.retrato_elefante(db, escola, aluno, quando(ultima_coleta, 3, 10),
                                         tentativas=20 + i, acertos=12 + (i % 5))
                # Matific: a última criança de cada turma fica sem retrato (ausência ≠ 0).
                if i < n - 1:
                    fab.retrato_matific(db, escola, aluno, quando(inicio_coleta, 3, 20),
                                        atividades=2, estrelas=5)
                    fab.retrato_matific(db, escola, aluno, quando(ultima_coleta, 3, 20),
                                        atividades=6 + i, estrelas=15 + 2 * i)

    alfa = escolas["alfa"]
    contas = {
        "global": {"nome": "Admin Global E2E (fictício)", "cargo": "admin", "is_global": True,
                   "escola_id": alfa.id},
        "secretaria": {"nome": "Secretaria E2E (fictícia)", "cargo": "coordenador",
                       "rede_id": rede.id},
        "coord": {"nome": "Coordenação E2E (fictícia)", "cargo": "coordenador",
                  "escola_id": alfa.id},
        "prof": {"nome": "Professor E2E (fictício)", "cargo": "professor",
                 "escola_id": alfa.id},
    }
    for perfil, campos in contas.items():
        db.add(Usuario(email=EMAILS[perfil], senha_hash=hash_senha(senhas[perfil]), **campos))
    db.commit()
    return {"rede": rede.nome, "escolas": len(escolas), "criancas": criancas, "ano": ano}


# --- Servidor (opcional) ----------------------------------------------------------------

def _so_loopback() -> None:
    """Conexões de SAÍDA só para o loopback (o E2E não usa rede externa)."""
    import ipaddress
    import socket

    bloqueios = {"n": 0}
    original, original_ex = socket.socket.connect, socket.socket.connect_ex

    def permitido(endereco) -> bool:
        if not isinstance(endereco, tuple):          # AF_UNIX e afins
            return True
        host = str(endereco[0]).split("%", 1)[0]
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def conferir(endereco) -> None:
        if not permitido(endereco):
            bloqueios["n"] += 1
            sys.stderr.write(f"seed_e2e_analise: conexão externa BLOQUEADA ({endereco[0]})\n")
            raise ConnectionRefusedError("E2E da análise: rede externa bloqueada")

    def connect(self, endereco):
        conferir(endereco)
        return original(self, endereco)

    def connect_ex(self, endereco):
        conferir(endereco)
        return original_ex(self, endereco)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def servir(porta: int) -> None:
    _so_loopback()
    import app.core.automacao as automacao

    automacao.iniciar_verificacao = lambda: None   # sem geo-IP e sem Chromium no boot
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=porta, log_level="warning")


def main() -> None:
    forcar_saida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--servir", type=int, metavar="PORTA",
                        help="depois de semear, sobe a API em 127.0.0.1:PORTA")
    args = parser.parse_args()

    if os.environ.get("ENV", "dev").lower() in ("producao", "production", "prod"):
        _recusar("ENV de produção")
    alvo = caminho_do_banco(os.environ.get("DATABASE_URL", ""))
    senhas = senhas_de_teste()
    # O engine nasce no import de app.core.database: apagar ANTES de importá-lo.
    apagar_banco(alvo)

    from app.core.database import SessionLocal, engine
    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine)
    db = SessionLocal()
    try:
        resumo = semear(db, senhas)
    finally:
        db.close()
    print(f"Seed E2E da análise pronto em {alvo.name}: {resumo['rede']}, "
          f"{resumo['escolas']} escolas, {resumo['criancas']} crianças fictícias "
          f"(ano letivo {resumo['ano']}), 4 contas de teste.", flush=True)

    if args.servir:
        servir(args.servir)


if __name__ == "__main__":
    main()
