"""Scripts do OPERADOR com a saída redirecionada no Windows (cp1252).

O DEFEITO (prova da revisão e97, roteiro da senha derivada): no Windows, com a
saída num arquivo ou num pipe, o Python escreve em cp1252, e o ``→`` da linha
``alvos: --aplicar → N`` do ``scripts/senhas_derivadas.py`` derrubava o
diagnóstico com ``UnicodeEncodeError`` (rc=1), justamente na linha que dá o
número do ``--esperado``. ``PYTHONIOENCODING=cp1252`` reproduz esse fluxo em
qualquer sistema (inclusive no Linux do CI), e a saída aqui vai SEMPRE para um
pipe, como no ``> diag.txt`` do operador.

O que este arquivo prova:

1. o ambiente reproduz o defeito (controle) e, com o conserto neutralizado, o
   ``senhas_derivadas.py`` quebra na linha do ``→`` (a prova invertida);
2. com o conserto, os scripts rodam DE VERDADE num subprocesso, contra um SQLite
   descartável (nunca o banco de desenvolvimento), e a saída inteira chega em
   UTF-8 — stdout e stderr na mesma codificação (o ``2>&1`` não mistura);
3. a catraca: TODO script de ``backend/scripts`` chama ``forcar_saida_utf8()``
   como primeira instrução da função de entrada. Script novo entra coberto ou
   reprova aqui.
"""
from __future__ import annotations

import ast
import io
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import pwd_context
from app.models import Escola, Usuario
from scripts import _saida
from tests._infra_comum import ambiente

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
AJUDANTE = "forcar_saida_utf8"
# Todos os .py de backend/scripts menos os módulos de apoio (prefixo "_").
DO_OPERADOR = sorted(p for p in SCRIPTS.glob("*.py") if not p.name.startswith("_"))

# Fora de cp1252 de propósito: a escola sai no resumo do diagnóstico e o @ na
# prévia do link — o conserto não pode depender de o texto "caber" em cp1252.
ESCOLA_SINT = "ESCOLA SAIDA SINT Ω"
USERNAME_SINT = "ProfSintΩ"

_hash_rapido = pwd_context.handler("bcrypt").using(rounds=4).hash


# ---------------------------------------------------------------------------
# O ajudante, unidade
# ---------------------------------------------------------------------------
def _console_cp1252() -> tuple[io.BytesIO, io.TextIOWrapper]:
    bruto = io.BytesIO()
    return bruto, io.TextIOWrapper(bruto, encoding="cp1252", newline="")  # errors="strict"


def test_ajudante_troca_cp1252_por_utf8_em_stdout_e_stderr(monkeypatch):
    b_out, out = _console_cp1252()
    b_err, err = _console_cp1252()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    with pytest.raises(UnicodeEncodeError):      # o defeito, antes do ajudante
        print("alvos: --aplicar → 3", file=out)
    _saida.forcar_saida_utf8()
    print("alvos: --aplicar → 3; ≥ ≠ ê Ω", file=out)
    print("RECUSADO — ≥", file=err)
    out.flush(); err.flush()
    monkeypatch.undo()
    assert (out.encoding, out.errors) == ("utf-8", "replace")
    assert (err.encoding, err.errors) == ("utf-8", "replace")
    assert b_out.getvalue().decode("utf-8").endswith("alvos: --aplicar → 3; ≥ ≠ ê Ω\n")
    assert b_err.getvalue().decode("utf-8") == "RECUSADO — ≥\n"


def test_ajudante_nao_mexe_em_fluxo_utf8_nem_em_fluxo_sem_reconfigure(monkeypatch):
    bruto = io.BytesIO()
    ja_utf8 = io.TextIOWrapper(bruto, encoding="utf-8", newline="")   # ex.: o console
    monkeypatch.setattr(sys, "stdout", ja_utf8)
    monkeypatch.setattr(sys, "stderr", io.StringIO())                 # sem reconfigure
    _saida.forcar_saida_utf8()
    assert (ja_utf8.encoding, ja_utf8.errors) == ("utf-8", "strict")  # intocado
    monkeypatch.setattr(sys, "stdout", None)                          # pythonw: sem console
    _saida.forcar_saida_utf8()                                        # não quebra


def test_ajudante_so_usa_biblioteca_padrao():
    """O portão ``exigir_ci_verde.py`` roda como arquivo, sem nada instalado
    (runner do GitHub, container): o ajudante não pode puxar dependência."""
    arvore = ast.parse((SCRIPTS / "_saida.py").read_text(encoding="utf-8"))
    modulos = {a.name.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.Import)
               for a in n.names}
    modulos |= {n.module.split(".")[0] for n in ast.walk(arvore)
                if isinstance(n, ast.ImportFrom) and n.module}
    assert modulos <= set(sys.stdlib_module_names) | {"__future__"}, modulos


# ---------------------------------------------------------------------------
# A catraca: todo script de backend/scripts
# ---------------------------------------------------------------------------
def _funcao_de_entrada(arvore: ast.Module) -> ast.FunctionDef | None:
    """A função do módulo que o bloco ``if __name__ == "__main__":`` chama."""
    defs = {n.name: n for n in arvore.body if isinstance(n, ast.FunctionDef)}
    for no in arvore.body:
        if isinstance(no, ast.If) and "__main__" in ast.unparse(no.test):
            for sub in ast.walk(no):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id in defs):
                    return defs[sub.func.id]
    return None


def _problemas(fonte: str) -> list[str]:
    arvore = ast.parse(fonte)
    problemas = []
    f = _funcao_de_entrada(arvore)
    if f is None:
        problemas.append("sem bloco __main__ que chame uma função do módulo")
    else:
        corpo = f.body
        if (isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant)
                and isinstance(corpo[0].value.value, str)):
            corpo = corpo[1:]                                    # pula a docstring
        primeira = corpo[0] if corpo else None
        if not (isinstance(primeira, ast.Expr) and isinstance(primeira.value, ast.Call)
                and isinstance(primeira.value.func, ast.Name)
                and primeira.value.func.id == AJUDANTE):
            problemas.append(f"{f.name}() não começa por {AJUDANTE}()")
    if not any(isinstance(n, ast.ImportFrom) and n.module in ("scripts._saida", "_saida")
               and any(a.name == AJUDANTE for a in n.names) for n in ast.walk(arvore)):
        problemas.append(f"não importa {AJUDANTE} de scripts._saida")
    # Reconfigurar por conta própria (ainda mais no IMPORT, como antes em três
    # scripts) mexe na saída de quem só importou o módulo — e diverge da regra.
    for n in ast.walk(arvore):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "reconfigure"):
            problemas.append(f"linha {n.lineno}: reconfigure próprio — use {AJUDANTE}()")
    return problemas


def test_catraca_todo_script_forca_utf8_na_entrada():
    assert len(DO_OPERADOR) >= 19, [p.name for p in DO_OPERADOR]   # a varredura enxerga
    achados = {p.name: _problemas(p.read_text(encoding="utf-8")) for p in DO_OPERADOR}
    achados = {nome: lista for nome, lista in achados.items() if lista}
    assert not achados, (
        "Script do operador sem a saída em UTF-8 (no Windows, com a saída "
        f"redirecionada, um '→' derruba a execução): {achados}. A primeira "
        f"instrução da função de entrada tem de ser {AJUDANTE}() "
        "(from scripts._saida import forcar_saida_utf8).")


def test_a_catraca_pega_script_sem_o_ajudante():
    """Se a varredura não pegasse nada, passaria para sempre."""
    sem = ("import sys\n"
           "sys.stdout.reconfigure(encoding='utf-8')\n"
           "def main():\n"
           "    print('alvos → 1')\n"
           "if __name__ == '__main__':\n"
           "    raise SystemExit(main())\n")
    problemas = _problemas(sem)
    assert any("main() não começa" in p for p in problemas)
    assert any("não importa" in p for p in problemas)
    assert any("reconfigure próprio" in p for p in problemas)
    assert _problemas("def main():\n    print(1)\n") == [
        "sem bloco __main__ que chame uma função do módulo",
        f"não importa {AJUDANTE} de scripts._saida"]
    com = ('"""doc"""\n'
           "from scripts._saida import forcar_saida_utf8\n"
           "def principal(argv):\n"
           '    """doc da função"""\n'
           "    forcar_saida_utf8()\n"
           "    print('alvos → 1')\n"
           "if __name__ == '__main__':\n"
           "    sys.exit(principal(sys.argv[1:]))\n")
    assert _problemas(com) == []


# ---------------------------------------------------------------------------
# Os scripts de verdade, num subprocesso com a saída em pipe (cp1252)
# ---------------------------------------------------------------------------
@pytest.fixture()
def banco_sint(tmp_path):
    """SQLite DESCARTÁVEL com contas sintéticas: um admin global e um professor
    com a senha derivada do @ (``@ + 123``), nunca usado."""
    arquivo = tmp_path / "saida_utf8.db"
    engine = create_engine(f"sqlite:///{arquivo.as_posix()}")
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    with Sessao() as db:
        esc = Escola(nome=ESCOLA_SINT, ano_letivo_ativo=2026)
        db.add(esc)
        db.flush()
        globa = Usuario(escola_id=None, nome="Global Saida Sint", username="GlobalSaidaSint",
                        email="global.saida@sint.local", cargo="admin", is_global=True,
                        senha_hash=_hash_rapido("frase-longa-do-global-91"))
        prof = Usuario(escola_id=esc.id, nome="Prof Saida Sint", username=USERNAME_SINT,
                       email="prof.saida@sint.local", cargo="professor",
                       senha_hash=_hash_rapido(USERNAME_SINT.lower() + "123"))
        db.add_all([globa, prof])
        db.commit()
        ids = {"global": globa.id, "prof": prof.id, "escola": esc.id}
    engine.dispose()
    return f"sqlite:///{arquivo.as_posix()}", Sessao, ids


def _retrato(Sessao) -> dict:
    with Sessao() as db:
        return {u.id: (u.senha_hash, u.token_version or 0, u.status)
                for u in db.execute(select(Usuario)).scalars()}


def _rodar(argumentos: list[str], url: str, *, cwd: Path = BACKEND):
    """O comando do operador, com a saída num PIPE em cp1252 (o ``> diag.txt``
    do Windows). Saída em bytes: quem confere decodifica, estrito."""
    env = ambiente(url, producao=False)
    env.update(ENV="dev", PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    return subprocess.run([sys.executable, *argumentos], cwd=str(cwd), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)


def _texto(bruto: bytes) -> str:
    return bruto.decode("utf-8")      # estrito: cp1252 com acento quebraria aqui


def test_controle_o_ambiente_reproduz_o_defeito(tmp_path):
    p = _rodar(["-c", "print('alvos: --aplicar \\u2192 1')"],
               f"sqlite:///{(tmp_path / 'nao_aberto.db').as_posix()}")
    assert p.returncode != 0
    assert b"UnicodeEncodeError" in p.stderr


def test_prova_invertida_sem_o_conserto_o_diagnostico_quebra_no_alvos(banco_sint):
    """O defeito da revisão, de volta: com ``forcar_saida_utf8`` neutralizado,
    o diagnóstico morre na linha do ``→`` (e o operador fica sem o número do
    ``--esperado``)."""
    url, Sessao, _ = banco_sint
    neutralizado = ("import runpy, sys\n"
                    "import scripts._saida as s\n"
                    "s.forcar_saida_utf8 = lambda: None\n"
                    "sys.argv = ['senhas_derivadas']\n"
                    "runpy.run_module('scripts.senhas_derivadas', run_name='__main__')\n")
    p = _rodar(["-c", neutralizado], url)
    assert p.returncode != 0
    assert b"UnicodeEncodeError" in p.stderr
    assert b"alvos" not in p.stdout


def test_senhas_derivadas_diagnostico_em_pipe_cp1252(banco_sint):
    url, Sessao, ids = banco_sint
    antes = _retrato(Sessao)
    p = _rodar(["-m", "scripts.senhas_derivadas"], url)
    saida, erro = _texto(p.stdout), _texto(p.stderr)
    assert p.returncode == 0, erro
    assert "Traceback" not in erro and "UnicodeEncodeError" not in erro
    assert "contas com senha derivada do nome: 1 (1 nunca usadas" in saida
    assert f"escola {ids['escola']} ({ESCOLA_SINT}): 1 — " in saida
    assert "alvos: --aplicar → 1; --aplicar --so-nunca-usadas → 1" in saida
    assert "diagnóstico apenas — nada foi gravado" in saida
    assert _retrato(Sessao) == antes                       # diagnóstico não grava


def test_senhas_derivadas_contagens_em_pipe_cp1252(banco_sint):
    url, Sessao, _ = banco_sint
    p = _rodar(["-m", "scripts.senhas_derivadas", "--contagens"], url)
    saida = _texto(p.stdout)
    assert p.returncode == 0, _texto(p.stderr)
    assert "senhas derivadas do nome — só contagens" in saida
    assert "total: 1" in saida and "globais: 0" in saida
    assert ESCOLA_SINT not in saida and USERNAME_SINT not in saida   # só números


def test_link_redefinicao_previa_e_recusa_em_pipe_cp1252(banco_sint):
    url, Sessao, ids = banco_sint
    antes = _retrato(Sessao)
    p = _rodar(["-m", "scripts.link_redefinicao", "--usuario-id", str(ids["prof"]),
                "--por", str(ids["global"])], url)
    saida = _texto(p.stdout)
    assert p.returncode == 0, _texto(p.stderr)
    assert f"alvo: usuario_id={ids['prof']} @{USERNAME_SINT} cargo=professor" in saida
    assert "prévia — nada foi gravado" in saida
    # A recusa vai para o stderr — na MESMA codificação do stdout.
    r = _rodar(["-m", "scripts.link_redefinicao", "--usuario-id", str(ids["prof"]),
                "--por", str(ids["prof"])], url)
    assert r.returncode == 2
    assert _texto(r.stderr).startswith("RECUSADO — --por tem de ser uma conta de "
                                       "administração GLOBAL. Nada foi gravado.")
    assert _retrato(Sessao) == antes                       # nada gravado


def test_mensagem_de_erro_no_stderr_sai_em_utf8(tmp_path):
    """``--dias`` inválido: o ``SystemExit`` com ``≥`` vai para o stderr antes de
    qualquer consulta ao banco (o SQLite do teste nem chega a ser aberto)."""
    p = _rodar(["-m", "scripts.expurgar_retencao", "--dry-run", "--dias", "x→=1"],
               f"sqlite:///{(tmp_path / 'nao_aberto.db').as_posix()}")
    assert p.returncode == 1
    assert "--dias inválido: 'x→=1' (use categoria=N, N inteiro ≥ 0;" in _texto(p.stderr)


def test_ajuda_com_seta_em_pipe_cp1252(tmp_path):
    """A ajuda do ``auditar_notas_elefante`` é a docstring inteira, com ``→``."""
    p = _rodar(["-m", "scripts.auditar_notas_elefante", "--help"],
               f"sqlite:///{(tmp_path / 'nao_aberto.db').as_posix()}")
    assert p.returncode == 0, _texto(p.stderr)
    assert "→" in _texto(p.stdout)


@pytest.mark.parametrize("argumentos, codigo, trecho", [
    # o portão do deploy, exatamente como o deploy.yml o chama (da raiz do repo)
    (["backend/scripts/exigir_ci_verde.py", "a→b"], 1,
     "::error::Argumentos inesperados ('a→b'): deploy recusado."),
    # documentado como `python scripts/gerar_catalogo_elefante.py` (de backend/)
    (["backend/scripts/gerar_catalogo_elefante.py"], 2, "Gera/atualiza"),
])
def test_scripts_rodados_como_arquivo_importam_o_ajudante(tmp_path, argumentos, codigo, trecho):
    """Rodado como ARQUIVO, o ``sys.path[0]`` é a própria ``scripts/``: o import
    do ajudante não pode depender de ``backend/`` estar no caminho."""
    p = _rodar(argumentos, f"sqlite:///{(tmp_path / 'nao_aberto.db').as_posix()}",
               cwd=BACKEND.parent)
    assert p.returncode == codigo, _texto(p.stderr)
    assert "Traceback" not in _texto(p.stderr)
    assert trecho in _texto(p.stdout)
