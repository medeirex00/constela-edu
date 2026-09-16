"""MATRIZ DE AUTORIZAÇÃO do catálogo: ninguém na escola renivela nem renomeia livro.

O nível de um livro é a régua que decide quanto uma leitura vale. Se a escola
puder mexer nele — por qualquer caminho — ela ajusta a própria nota. A regra do
dono é curta:

    admin de escola, coordenador, professor e Secretaria NÃO alteram
    ``Livro.nivel_codigo`` nem ``Livro.titulo`` por NENHUMA rota.
    Só o Admin Global faz manutenção de catálogo.

Este arquivo prova isso em duas camadas:

1. MATRIZ VIVA (parte 1): cada caminho plausível é exercido com cada perfil e o
   livro é conferido no banco depois — CRUD do catálogo, ``/importacoes/confirmar``
   com linha FORJADA, restauração de backup, ajuste manual de snapshot/faixas e
   fusão de alunos. Rota nova que esqueça a trava reprova aqui.
2. INVENTÁRIO ESTÁTICO (parte 2): varredura do código (AST) atrás de QUALQUER
   escrita em ``Livro.nivel_codigo``/``Livro.titulo`` — atribuição, ``setattr``,
   ``update(Livro)`` e o próprio ``Livro(titulo=…, nivel_codigo=…)``. Só os
   módulos declarados abaixo podem conter uma — um sítio novo reprova o teste e
   obriga quem escreve a passar por aqui e declarar o papel. É a mesma mecânica
   de ``tests/test_legado_nota_geral.py``. O que o AST não alcança (escrita
   DINÂMICA, ``modelo(**campos)``) está declarado à mão e tem catraca de
   chamador.
"""
import ast
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Leitura, Livro, LogAuditoria, Rede, Usuario
from app.services import dificuldade_livro

API = "/api/v1"
RAIZ_BACKEND = pathlib.Path(__file__).resolve().parents[1]

TITULO = "Laerte, o Gato Inerte"
NIVEL = "D"                 # nível EM USO na escola (diferente do oficial de propósito)
NIVEL_OFICIAL = "B"         # o do catálogo do Elefante para esse título
PERFIS = ("admin", "coordenador", "professor", "secretaria")


def _login(email: str) -> TestClient:
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


def _cliente_do_perfil(db, escola, perfil: str) -> TestClient:
    """Cliente autenticado no perfil pedido. ``secretaria`` = usuário com rede
    vinculada (é assim que o produto a define — ver ``core.deps._e_secretaria``)."""
    if perfil == "admin":
        return _login("admin@teste.local")
    extra = {}
    if perfil == "secretaria":
        rede = Rede(nome="Rede Teste", status="ativa")
        db.add(rede)
        db.flush()
        escola.rede_id = rede.id
        extra = {"rede_id": rede.id, "cargo": "coordenador"}
    db.add(Usuario(escola_id=escola.id, nome=perfil, email=f"{perfil}@autz.local",
                   senha_hash=hash_senha("s3nh4"), cargo=extra.pop("cargo", perfil), **extra))
    db.commit()
    return _login(f"{perfil}@autz.local")


@pytest.fixture()
def livro(db, escola_completa) -> Livro:
    linha = Livro(escola_id=escola_completa["escola"].id, titulo=TITULO, nivel_codigo=NIVEL)
    db.add(linha)
    db.commit()
    return linha


def _intacto(db, livro_id: int) -> None:
    """O livro do banco continua com o título e o nível originais."""
    db.expire_all()
    atual = db.get(Livro, livro_id)
    assert atual is not None, "o livro não podia ter sido excluído"
    assert (atual.titulo, atual.nivel_codigo) == (TITULO, NIVEL)


# ===========================================================================
# 1) MATRIZ VIVA — caminho a caminho, perfil a perfil
# ===========================================================================

@pytest.mark.parametrize("perfil", PERFIS)
def test_crud_do_catalogo_e_negado_a_escola_e_a_secretaria(db, escola_completa, livro, perfil):
    escola = escola_completa["escola"]
    cliente = _cliente_do_perfil(db, escola, perfil)
    base = f"{API}/escolas/{escola.id}/livros"

    tentativas = [
        cliente.post(base, json={"titulo": "Livro Plantado", "nivel_codigo": "Z"}),
        cliente.patch(f"{base}/{livro.id}", json={"nivel_codigo": "Z", "motivo": "quero mais pontos"}),
        cliente.patch(f"{base}/{livro.id}", json={"titulo": "Outro Título"}),
        cliente.patch(f"{base}/{livro.id}", json={"aplicar_ao_historico": True,
                                                  "motivo": "quero mudar o passado"}),
        cliente.delete(f"{base}/{livro.id}"),
    ]
    for resposta in tentativas:
        assert resposta.status_code == 403, resposta.text

    _intacto(db, livro.id)
    assert db.execute(select(Livro).where(Livro.titulo == "Livro Plantado")).first() is None


def _forjada(aluno, titulo: str, nivel: str, **extra) -> dict:
    """Corpo de ``/importacoes/confirmar`` com o nível que a escola quiser."""
    return {"plataforma": "elefante", "formato": "leituras", "tipo": "texto",
            "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                        "dados": {"livro": titulo, "nivel": nivel,
                                  "data": "2026-07-01T09:00:00", **extra}}]}


@pytest.mark.parametrize("perfil", PERFIS)
def test_importacao_com_linha_forjada_nao_renivela_nem_renomeia(db, escola_completa,
                                                                livro, perfil):
    """``/importacoes/confirmar`` é a porta LEGÍTIMA da escola — e é por ela que
    um relatório forjado tentaria renivelar o acervo.

    Professor e Secretaria não passam nem da porta. Admin e coordenador passam
    (é o trabalho deles), mas a reconciliação do acervo
    (``routers.importacoes._AcervoEscola``) nunca aceita o nível da linha para um
    livro que já existe: o nível que fica é o do CATÁLOGO OFICIAL (aqui “Laerte,
    o Gato Inerte” é B) — nunca o Z inventado no relatório. O ``elefante_id``
    forjado é descartado e o título nunca é reescrito."""
    escola = escola_completa["escola"]
    cliente = _cliente_do_perfil(db, escola, perfil)
    ana = escola_completa["alunos"][0]

    resposta = cliente.post(f"{API}/escolas/{escola.id}/importacoes/confirmar",
                            json=_forjada(ana, TITULO, "Z", elefante_id=999999))
    if perfil in ("professor", "secretaria"):
        assert resposta.status_code == 403, resposta.text
        _intacto(db, livro.id)
        return
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    atual = db.get(Livro, livro.id)
    assert atual.titulo == TITULO, "o título NUNCA é reescrito por importação"
    assert atual.nivel_codigo != "Z", "o nível do relatório não pode virar o nível do livro"
    # O que fica é o OFICIAL, e o vínculo é com o id oficial — não com o forjado.
    oficial = dificuldade_livro.catalogo().buscar(TITULO, NIVEL_OFICIAL)
    assert oficial is not None and oficial.nivel == NIVEL_OFICIAL, "premissa do teste"
    assert atual.nivel_codigo == NIVEL_OFICIAL
    assert atual.origem_nivel == "fonte"
    assert atual.elefante_id == oficial.id
    assert atual.elefante_id != 999999, "o id forjado no relatório é descartado"
    restaurado = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.nivel_oficial_restaurado")).scalars().one()
    assert (restaurado.detalhes["de"], restaurado.detalhes["para"]) == (NIVEL, NIVEL_OFICIAL)


@pytest.mark.parametrize("perfil", ("admin", "coordenador"))
def test_livro_fora_do_catalogo_nao_muda_de_nivel_por_relatorio(db, escola_completa, perfil):
    """O caso em que a escola teria a última palavra — e não tem.

    Livro que NÃO existe no catálogo oficial não tem nível oficial a restaurar.
    Aí a tentação seria aceitar o nível do relatório; se isso acontecesse, a
    escola renivelaria o acervo inteiro por planilha. O nível em uso é
    PRESERVADO: só o ``nivel_fonte`` registra o que a linha informou, e a
    divergência vai para a auditoria."""
    escola = escola_completa["escola"]
    fora = Livro(escola_id=escola.id, titulo="O Mapa Perdido", nivel_codigo="D")
    db.add(fora)
    db.commit()
    assert dificuldade_livro.catalogo().buscar(fora.titulo, "D") is None, "premissa do teste"

    cliente = _cliente_do_perfil(db, escola, perfil)
    resposta = cliente.post(f"{API}/escolas/{escola.id}/importacoes/confirmar",
                            json=_forjada(escola_completa["alunos"][0], fora.titulo, "Z"))
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    atual = db.get(Livro, fora.id)
    assert (atual.titulo, atual.nivel_codigo) == ("O Mapa Perdido", "D")
    assert atual.nivel_fonte == "Z" and atual.origem_nivel != "fonte"
    divergencia = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.nivel_divergente")).scalars().one()
    assert divergencia.detalhes["no_catalogo"] is False
    assert divergencia.detalhes["nivel_efetivo"] == "D"
    # E a leitura nasce com o nível CONGELADO do livro — o D preservado, não o Z.
    assert db.execute(select(Leitura.nivel_codigo).where(
        Leitura.livro_id == fora.id)).scalar_one() == "D"


def test_correcao_do_admin_global_resiste_ao_relatorio_da_escola(cliente_global, db,
                                                                 escola_completa, livro):
    """A escola não desfaz a decisão do Admin Global importando um relatório.

    Depois da correção, ``origem_nivel='admin_global'`` e a reconciliação
    PRESERVA o nível — nem o do relatório, nem o do catálogo, voltam sozinhos."""
    escola = escola_completa["escola"]
    corrigido = cliente_global.patch(f"{API}/escolas/{escola.id}/livros/{livro.id}",
                                     json={"nivel_codigo": "F", "motivo": "conferido no oficial"})
    assert corrigido.status_code == 200, corrigido.text

    cliente = _cliente_do_perfil(db, escola, "admin")
    resposta = cliente.post(f"{API}/escolas/{escola.id}/importacoes/confirmar",
                            json=_forjada(escola_completa["alunos"][0], TITULO, "Z"))
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    atual = db.get(Livro, livro.id)
    assert (atual.titulo, atual.nivel_codigo) == (TITULO, "F")
    assert atual.origem_nivel == "admin_global"


@pytest.mark.parametrize("perfil", PERFIS)
def test_restauracao_de_backup_e_exclusiva_do_admin_global(db, escola_completa, livro, perfil):
    """Um backup carrega o catálogo inteiro: restaurá-lo é reescrever níveis e
    títulos de uma vez. A rota é do Admin Global (``routers/admin.py``)."""
    escola = escola_completa["escola"]
    cliente = _cliente_do_perfil(db, escola, perfil)
    plantado = {"tabelas": {"livros": [{"id": livro.id, "escola_id": escola.id,
                                        "titulo": "Título Plantado", "nivel_codigo": "Z"}]}}
    import json as _json

    resposta = cliente.post(
        f"{API}/escolas/{escola.id}/restaurar",
        files={"arquivo": ("backup.json", _json.dumps(plantado).encode("utf-8"),
                           "application/json")})
    assert resposta.status_code == 403, resposta.text
    _intacto(db, livro.id)


@pytest.mark.parametrize("perfil", ("admin", "coordenador"))
def test_ajuste_manual_do_elefante_nao_toca_no_catalogo(db, escola_completa, livro, perfil):
    """O ajuste manual de snapshot/faixas é sobre o ALUNO. Mesmo quando é
    permitido (escola sem dado vindo da plataforma), ele não muda livro nenhum."""
    escola = escola_completa["escola"]
    cliente = _cliente_do_perfil(db, escola, perfil)
    ana = escola_completa["alunos"][0]

    snapshot = cliente.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}",
                           json={"tempo_leitura_min": 30, "questoes_tentativas": 4,
                                 "questoes_acertos": 2, "livros_por_nivel": {"Z": 40},
                                 "motivo": "dados informados pela professora"})
    assert snapshot.status_code == 200, snapshot.text
    faixas = cliente.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}/niveis",
                         json={"faixas": {"nivel_2": 9},
                               "motivo": "dados informados pela professora"})
    assert faixas.status_code == 200, faixas.text
    _intacto(db, livro.id)


@pytest.mark.parametrize("perfil", PERFIS)
def test_fusao_de_alunos_nao_toca_no_catalogo(db, escola_completa, livro, perfil):
    """A fusão move leituras entre cadastros — e só isso. O livro (e o nível
    congelado que a leitura carrega) atravessa a operação intacto."""
    escola = escola_completa["escola"]
    cliente = _cliente_do_perfil(db, escola, perfil)
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]
    db.add(Leitura(escola_id=escola.id, aluno_id=remover.id, livro_id=livro.id,
                   nivel_codigo=NIVEL))
    db.commit()

    resposta = cliente.post(f"{API}/escolas/{escola.id}/alunos/fundir",
                            json={"manter_id": manter.id, "remover_id": remover.id,
                                  "confirmacao": "FUNDIR"})
    if perfil in ("professor", "secretaria"):
        assert resposta.status_code == 403, resposta.text
    else:
        assert resposta.status_code == 200, resposta.text
        db.expire_all()
        movida = db.execute(select(Leitura).where(Leitura.livro_id == livro.id)).scalars().one()
        assert (movida.aluno_id, movida.nivel_codigo) == (manter.id, NIVEL)
    _intacto(db, livro.id)


def test_admin_global_continua_fazendo_manutencao(cliente_global, db, escola_completa, livro):
    """A trava é sobre a ESCOLA, não sobre o catálogo: o Admin Global corrige."""
    base = f"{API}/escolas/{escola_completa['escola'].id}/livros"
    corrigido = cliente_global.patch(f"{base}/{livro.id}",
                                     json={"nivel_codigo": "E", "motivo": "conferido no oficial"})
    assert corrigido.status_code == 200, corrigido.text
    db.expire_all()
    assert db.get(Livro, livro.id).nivel_codigo == "E"


# ===========================================================================
# 2) INVENTÁRIO ESTÁTICO — quem pode escrever nesses dois campos
# ===========================================================================
#
# `ocorrencias` conta os sítios de ESCRITA encontrados pela varredura (ver
# `_escritas_no_arquivo`); `papel` diz por que aquele módulo tem esse direito.
ESCRITORES_PERMITIDOS: dict[str, dict] = {
    "app/routers/plataformas.py": {
        "ocorrencias": 2, "papel": "CRUD do catálogo — só Admin Global",
        "porque": ("o PATCH de `/livros/{id}` aplica as mudanças com "
                   "`setattr(livro, campo, valor)` e o POST cadastra o livro com "
                   "`Livro(titulo=…, nivel_codigo=…)`. As duas rotas dependem de "
                   "`_admin_global_do_catalogo`, e cada correção exige motivo e "
                   "vai para o log de auditoria."),
    },
    "app/routers/importacoes.py": {
        "ocorrencias": 2, "papel": "reconciliação com o catálogo OFICIAL",
        "porque": ("`_AcervoEscola._conciliar` devolve o livro ao nível do "
                   "CATÁLOGO OFICIAL (`nivel_ref` vem de `meta`, a entrada do "
                   "catálogo). Nunca grava o nível que veio no relatório, e "
                   "preserva a correção do Admin Global (`origem_nivel` = "
                   "`admin_global`). O título nunca é reescrito. A segunda é o "
                   "`Livro(...)` do livro que ainda não existia no acervo."),
    },
    "scripts/seed.py": {
        "ocorrencias": 1, "papel": "semente de demonstração — fora da API",
        "porque": ("o seed monta uma base de exemplo do zero, rodando na linha de "
                   "comando de quem já tem o banco na mão. Não é caminho de "
                   "usuário: nenhuma rota o chama."),
    },
}

# Escrita DINÂMICA — invisível para a varredura, declarada à mão.
# `services.backup.restaurar` materializa qualquer modelo com `modelo(**campos)`:
# não há `Livro`, `titulo` nem `nivel_codigo` escritos no arquivo, então o AST não
# tem o que ver. A trava desse caminho é de ROTA (Admin Global) e está provada na
# matriz viva (`test_restauracao_de_backup_e_exclusiva_do_admin_global`); aqui
# fechamos o resto: a função só pode ter ESSE chamador.
ESCRITOR_DINAMICO = ("app/services/backup.py", "restaurar")
CHAMADOR_UNICO_DA_RESTAURACAO = "app/routers/admin.py"

CAMPOS_DO_CATALOGO = {"nivel_codigo", "titulo"}


def _usa_o_modelo_livro(arvore: ast.AST) -> bool:
    """O módulo menciona o modelo ``Livro`` (import ou uso direto)?"""
    return any(isinstance(no, ast.Name) and no.id == "Livro" for no in ast.walk(arvore)) or any(
        isinstance(no, ast.alias) and no.name == "Livro" for no in ast.walk(arvore))


def _escritas_no_arquivo(arvore: ast.AST) -> list[tuple[int, str]]:
    """Escritas em ``nivel_codigo``/``titulo`` de um objeto que É (ou pode ser) um
    ``Livro``.

    Quatro formas, as mesmas que o ORM permite:
      * ``<algo>.nivel_codigo = …`` / ``<algo>.titulo = …``;
      * ``setattr(<algo que se chama livro>, …)``;
      * ``update(Livro).values(…)`` (UPDATE em lote);
      * ``Livro(titulo=…, nivel_codigo=…)`` — o livro JÁ NASCE com um nível, e
        plantar um livro num nível qualquer vale tanto quanto renivelar um.

    "É ou pode ser um Livro" = o módulo usa o modelo ``Livro`` **ou** a expressão
    do objeto menciona "livro" (o parâmetro recebido de fora). Assim um helper
    novo em qualquer camada é pego, sem falso positivo em `aula.titulo` de um
    módulo que nada tem a ver com o acervo.

    O que a varredura NÃO vê: escrita dinâmica sobre um modelo escolhido em
    tempo de execução (``modelo(**campos)``, ``setattr(objeto, coluna, valor)``),
    porque nem o nome do modelo nem o do campo aparecem no arquivo. O único
    caminho assim no produto está declarado em ``ESCRITOR_DINAMICO`` e tem
    catraca própria (``test_a_escrita_dinamica_do_backup_tem_um_chamador_so``)."""
    usa_livro = _usa_o_modelo_livro(arvore)
    achados: list[tuple[int, str]] = []
    for no in ast.walk(arvore):
        alvos: list[ast.expr] = []
        if isinstance(no, ast.Assign):
            alvos = list(no.targets)
        elif isinstance(no, (ast.AugAssign, ast.AnnAssign)):
            alvos = [no.target]
        for alvo in alvos:
            if isinstance(alvo, ast.Attribute) and alvo.attr in CAMPOS_DO_CATALOGO:
                texto = ast.unparse(alvo)
                if usa_livro or "livro" in texto.lower():
                    achados.append((no.lineno, texto))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name):
            if no.func.id == "setattr" and no.args:
                objeto = ast.unparse(no.args[0]).lower()
                campo = no.args[1] if len(no.args) > 1 else None
                literal = (isinstance(campo, ast.Constant)
                           and campo.value in CAMPOS_DO_CATALOGO)
                if "livro" in objeto or literal:
                    achados.append((no.lineno, ast.unparse(no)[:80]))
            if no.func.id == "update" and no.args and ast.unparse(no.args[0]) == "Livro":
                achados.append((no.lineno, ast.unparse(no)[:80]))
            if no.func.id == "Livro" and any(
                    palavra.arg in CAMPOS_DO_CATALOGO for palavra in no.keywords):
                achados.append((no.lineno, ast.unparse(no)[:80]))
    return achados


def _inventario() -> dict[str, list[tuple[int, str]]]:
    encontrado: dict[str, list[tuple[int, str]]] = {}
    for base in ("app", "scripts"):
        for arquivo in sorted((RAIZ_BACKEND / base).rglob("*.py")):
            try:
                arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            achados = _escritas_no_arquivo(arvore)
            if achados:
                encontrado[arquivo.relative_to(RAIZ_BACKEND).as_posix()] = achados
    return encontrado


def test_inventario_de_quem_escreve_nivel_e_titulo_de_livro():
    """Catraca: um sítio NOVO de escrita em ``Livro.nivel_codigo``/``titulo``
    reprova até ser declarado aqui, com o papel.

    Não é burocracia: cada linha dessas é uma forma de renivelar o acervo — e
    renivelar o acervo é mexer na nota de todo mundo. Se o seu caminho novo é
    legítimo, some ao dicionário explicando quem pode chamá-lo."""
    encontrado = _inventario()

    novos = sorted(set(encontrado) - set(ESCRITORES_PERMITIDOS))
    assert not novos, (
        "Escrita NOVA em Livro.nivel_codigo/titulo fora dos módulos permitidos: "
        + "; ".join(f"{arq} {encontrado[arq]}" for arq in novos)
        + ". Só o Admin Global (CRUD do catálogo) e a reconciliação com o catálogo "
          "OFICIAL na importação podem renivelar um livro.")

    for arquivo, esperado in ESCRITORES_PERMITIDOS.items():
        achados = encontrado.get(arquivo, [])
        assert len(achados) == esperado["ocorrencias"], (
            f"{arquivo}: {len(achados)} escrita(s) em nível/título de livro, "
            f"esperadas {esperado['ocorrencias']} ({esperado['papel']}). "
            f"Encontradas: {achados}. Se a nova é legítima, atualize o inventário.")


def test_a_varredura_pega_uma_escrita_nova_plantada():
    """Mostra que a catraca da varredura fecha de verdade (se ela não pegasse
    nada, o inventário passaria para sempre)."""
    plantado = ast.parse(
        "from app.models import Livro\n"
        "def renivelar(db, livro, novo):\n"
        "    livro.nivel_codigo = novo\n"
        "    livro.titulo = 'outro'\n"
        "    db.execute(update(Livro).values(nivel_codigo=novo))\n"
        "    db.add(Livro(escola_id=1, titulo='Plantado', nivel_codigo=novo))\n")
    assert len(_escritas_no_arquivo(plantado)) == 4

    # …e que ela não acusa quem só LÊ o nível do livro.
    leitura = ast.parse(
        "from app.models import Livro\n"
        "def valor(regra, livro):\n"
        "    return regra.valor_livro(livro.nivel_codigo, livro.titulo)\n")
    assert _escritas_no_arquivo(leitura) == []


def test_a_escrita_dinamica_do_backup_tem_um_chamador_so():
    """O buraco que a varredura não enxerga, fechado pelo chamador.

    ``backup.restaurar`` recria o acervo inteiro com ``modelo(**campos)``: é a
    forma mais direta de reescrever nível e título de todos os livros de uma vez,
    e nenhum dos dois nomes aparece no arquivo — o AST não tem o que ver. A trava
    é de ROTA. Enquanto a função tiver UM chamador, e ele for o
    ``/restaurar`` exclusivo do Admin Global, o caminho está governado; um
    chamador novo (uma rota de escola, um job) reprova aqui."""
    arquivo, funcao = ESCRITOR_DINAMICO
    assert (RAIZ_BACKEND / arquivo).exists(), arquivo

    chamadores: dict[str, list[int]] = {}
    for base in ("app", "scripts"):
        for caminho in sorted((RAIZ_BACKEND / base).rglob("*.py")):
            relativo = caminho.relative_to(RAIZ_BACKEND).as_posix()
            if relativo == arquivo:
                continue                       # a definição, não uma chamada
            arvore = ast.parse(caminho.read_text(encoding="utf-8"))
            linhas = [no.lineno for no in ast.walk(arvore)
                      if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                      and no.func.attr == funcao
                      and "backup" in ast.unparse(no.func.value).lower()]
            if linhas:
                chamadores[relativo] = linhas

    assert set(chamadores) == {CHAMADOR_UNICO_DA_RESTAURACAO}, (
        f"`backup.{funcao}` reescreve o acervo inteiro e só pode ser chamada pela "
        f"rota exclusiva do Admin Global em {CHAMADOR_UNICO_DA_RESTAURACAO}. "
        f"Chamadores encontrados: {chamadores}.")
