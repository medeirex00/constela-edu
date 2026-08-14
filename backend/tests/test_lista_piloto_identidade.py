"""P0 — a LISTA PILOTO não pode mais abrir uma segunda ficha para quem já existe.

4ª (e última) causa raiz das duplicatas: ``_persistir_linhas`` era um SEGUNDO
motor de identidade. Tinha índices próprios (RA, nome EXATO + turma_id, e um
"abreviado posicional" contra um pool restrito a cadastros de upload) e, quando
os três falhavam, fazia ``Aluno(...)`` direto — sem passar por
``matching.classificar_linha``, sem conhecer identidades externas e sem o
conceito de REVISAR. Bastava variação de grafia sem RA, ou mudança de sala, para
a mesma criança virar duas fichas, caladamente.

Agora a Lista Piloto usa a MESMA porta de identidade dos outros fluxos
(``matriculas.resolver_linha`` → ``services.matching``), com três desfechos:
reusar (seguro), revisar (inseguro/ambíguo: não cria e não altera) e criar
(ninguém plausível). IDENTIDADE e MATRÍCULA seguem separadas: mudar de turma não
faz de ninguém uma pessoa nova, e reconhecer quem é não reativa ninguém.
"""
import io
import shutil
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (Aluno, Escola, IdentidadeExterna, Matricula, Turma,
                        Usuario)
from app.routers import importacoes as imp
from app.services import lista_piloto

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]
ANO = 2026


# --- construção da planilha real (uma aba por turma) ------------------------

def _aluno(nome, *, numero=None, ra="", nasc=None):
    """Uma linha de aluno na ordem de COLUNAS. `numero`/`ra`/`nasc` vazios
    reproduzem a planilha real incompleta — que é justamente onde o casamento
    fica difícil."""
    return [numero, "", ra, nome, nasc, "MAE", "RUA X, 1", "BAIRRO",
            "", "", "", "", "F", "PARDA", "NÃO"]


def _planilha(*turmas) -> bytes:
    """turmas = (nome_da_turma, [linhas de aluno]) — uma aba por turma."""
    wb = openpyxl.Workbook()
    for i, (nome_turma, alunos) in enumerate(turmas):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = nome_turma[:31]
        ws.append([None, None, None, "PREFEITURA MUNICIPAL DE CARAGUATATUBA"])
        ws.append(["Escola:", None, "EMEF TESTE", None, None, None, None,
                   "Lista Piloto:", ANO])
        ws.append([])
        ws.append(["Professor:", None, "PAULA", None, "Ano:", nome_turma,
                   "Turno:       TARDE", None, "N.º da Classe (SED):",
                   300396600 + i])
        ws.append([])
        ws.append(COLUNAS)
        for linha in alunos:
            ws.append(linha)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _confirmar(cliente, escola_id, conteudo):
    r = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/matriculas/confirmar",
        files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def _plataforma(cliente, escola_id, plataforma, linhas, **flags):
    """Import de plataforma pelo MESMO endpoint que a tela e a sync usam."""
    corpo = {"plataforma": plataforma, "formato": "resumo", "tipo": "pdf",
             "linhas": linhas, **flags}
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


# --- contadores -------------------------------------------------------------

def _alunos(db, escola_id, prefixo=None):
    consulta = select(Aluno).where(Aluno.escola_id == escola_id)
    if prefixo:
        consulta = consulta.where(Aluno.nome.like(f"{prefixo}%"))
    db.expire_all()
    return db.execute(consulta.order_by(Aluno.id)).scalars().all()


def _conta(db, escola_id, prefixo=None) -> int:
    return len(_alunos(db, escola_id, prefixo))


def _matriculas(db, aluno_id):
    db.expire_all()
    return db.execute(select(Matricula).where(
        Matricula.aluno_id == aluno_id, Matricula.ano_letivo == ANO)).scalars().all()


def _turma_de(db, aluno_id) -> str:
    mats = _matriculas(db, aluno_id)
    assert len(mats) == 1, f"esperava 1 matrícula, achei {len(mats)}"
    return db.get(Turma, mats[0].turma_id).nome


# ---------------------------------------------------------------------------
# A) A MESMA Lista Piloto importada 5 vezes
# ---------------------------------------------------------------------------

def test_a_mesma_lista_cinco_vezes_da_um_aluno_cada(cliente, db, escola_completa):
    """Idempotência com os três graus de identificação que a planilha real tem:
    com RA, sem RA (só nascimento) e sem RA nem nascimento (só nome + chamada)."""
    escola_id = escola_completa["escola"].id
    conteudo = _planilha(("1º Ano A", [
        _aluno("AGATHA VITORIA MOURA DA SILVA", numero=1, ra="123.100.026-0",
               nasc=date(2019, 9, 18)),
        _aluno("ALICE DE ALMEIDA LEAL", numero=2, nasc=date(2019, 5, 2)),
        _aluno("BRENO CASTRO LIMA", numero=3),
    ]))

    for volta in range(5):
        corpo = _confirmar(cliente, escola_id, conteudo)
        assert corpo["alunos_criados"] == (3 if volta == 0 else 0), f"volta {volta}"
        assert corpo["alunos_em_revisao"] == 0, f"volta {volta}"
        assert corpo["alunos_fora_lista"] == 0, f"volta {volta}"

    nomes = [a.nome for a in _alunos(db, escola_id)]
    for esperado in ["AGATHA VITORIA MOURA DA SILVA", "ALICE DE ALMEIDA LEAL",
                     "BRENO CASTRO LIMA"]:
        assert nomes.count(esperado) == 1, f"{esperado} virou {nomes.count(esperado)} fichas"
    for aluno in _alunos(db, escola_id, prefixo=None):
        assert len(_matriculas(db, aluno.id)) <= 1, "matrícula duplicada"


def test_a2_renumeracao_da_chamada_nao_abre_ficha_nova(cliente, db, escola_completa):
    """Operação REAL da secretaria: alguém sai e a turma inteira é renumerada.

    O nº de chamada é posição na lista, não identidade — com o mesmo nome e o
    mesmo nascimento, chamada diferente é renumeração. Tratá-la como "outra
    criança" (o que o veto fazia antes) duplicaria a turma toda a cada lista
    nova; ninguém aqui tem RA, então é este o único caminho."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha(("4º Ano A", [
        _aluno("ANA CLARA MOTA", numero=1, nasc=date(2016, 2, 3)),
        _aluno("BRUNO TEIXEIRA REIS", numero=2, nasc=date(2016, 4, 5)),
        _aluno("CARLA MENDES DIAS", numero=3, nasc=date(2016, 6, 7)),
    ])))
    antes = _conta(db, escola_id)

    corpo = _confirmar(cliente, escola_id, _planilha(("4º Ano A", [
        _aluno("BRUNO TEIXEIRA REIS", numero=1, nasc=date(2016, 4, 5)),   # era 2
        _aluno("CARLA MENDES DIAS", numero=2, nasc=date(2016, 6, 7)),     # era 3
    ])))
    assert corpo["alunos_criados"] == 0
    assert corpo["alunos_fora_lista"] == 1          # só a Ana, que saiu mesmo
    assert _conta(db, escola_id) == antes


# ---------------------------------------------------------------------------
# B) e C) Lista Piloto → plataforma → Lista Piloto
# ---------------------------------------------------------------------------

def test_b_lista_elefante_lista_da_um_aluno(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    lista = _planilha(("1º Ano A", [
        _aluno("AGATHA VITORIA MOURA DA SILVA", numero=1, ra="123.100.026-0",
               nasc=date(2019, 9, 18))]))
    _confirmar(cliente, escola_id, lista)

    # Elefante escreve o nome abreviado e chama a sala pelo rótulo do relatório.
    _plataforma(cliente, escola_id, "elefante", [
        {"nome": "AGATHA V", "dados": {"livros_unicos": 4},
         "criar_em_turma_nome": "1 ANO A TARDE ANUAL (300396600)"}])

    _confirmar(cliente, escola_id, lista)
    assert _conta(db, escola_id, "AGATHA") == 1
    assert _alunos(db, escola_id, "AGATHA")[0].nome == "AGATHA VITORIA MOURA DA SILVA"


def test_c_lista_matific_lista_da_um_aluno(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    lista = _planilha(("1º Ano A", [
        _aluno("MARIA EDUARDA SILVA", numero=1, nasc=date(2015, 3, 1))]))
    _confirmar(cliente, escola_id, lista)

    _plataforma(cliente, escola_id, "matific", [
        {"nome": "MARIA E",
         "dados": {"atividades": 10, "estrelas": 5, "pontuacao_media": 70,
                   "matific_uuid": "uuid-maria"},
         "criar_em_turma_nome": "1 ANO A TARDE ANUAL (300396600)"}])

    _confirmar(cliente, escola_id, lista)
    marias = _alunos(db, escola_id, "MARIA")
    assert len(marias) == 1 and marias[0].nome == "MARIA EDUARDA SILVA"
    # O UUID ficou preso a UMA pessoa (identidade externa não se multiplica).
    assert db.execute(select(func.count()).select_from(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == escola_id)).scalar_one() == 1


# ---------------------------------------------------------------------------
# D) Variações de grafia do MESMO nome
# ---------------------------------------------------------------------------

def test_d_variacoes_de_nome_nao_duplicam_e_o_inseguro_vai_para_revisao(
        cliente, db, escola_completa):
    """Evidência suficiente (nome exato, caixa/acentos, abreviação posicional)
    → reusa. Evidência insuficiente (nome PARCIAL, sem nada que corrobore)
    → REVISÃO: não cria e não altera. Nenhum caminho gera ficha nova."""
    escola_id = escola_completa["escola"].id
    turma = "5º Ano C"
    _confirmar(cliente, escola_id, _planilha((turma, [
        _aluno("MARIA EDUARDA SILVA", numero=1, nasc=date(2015, 3, 1))])))
    original = _alunos(db, escola_id, "MARIA")[0]
    antes = _conta(db, escola_id)

    for variacao in ["Maria Eduarda Silva",      # caixa
                     "MARIA  EDUARDA   SILVA",   # espaços
                     "MARIA EDUARDA SILVA",      # idêntico
                     "Maria E. Silva"]:          # abreviação posicional
        corpo = _confirmar(cliente, escola_id, _planilha((turma, [
            _aluno(variacao, numero=1, nasc=date(2015, 3, 1))])))
        assert corpo["alunos_criados"] == 0, variacao
        assert _conta(db, escola_id) == antes, variacao
    # A abreviação casou, mas NÃO encurtou o cadastro: gravar "Maria E. Silva"
    # por cima degradaria a identidade e quebraria o casamento seguinte.
    db.expire_all()
    assert db.get(Aluno, original.id).nome == "MARIA EDUARDA SILVA"

    # INSEGURO: nome parcial, sem nº de chamada, sem nascimento, sem RA — nada
    # corrobora. Não cria (seria a 2ª ficha) e não altera (poderia ser outra
    # criança): fica para o gestor decidir.
    corpo = _confirmar(cliente, escola_id, _planilha((turma, [
        _aluno("MARIA EDUARDA")])))
    assert corpo["alunos_criados"] == 0
    assert corpo["alunos_em_revisao"] == 1
    assert any("Fundir duplicatas" in av for av in corpo["avisos"])
    assert _conta(db, escola_id) == antes
    db.expire_all()
    atual = db.get(Aluno, original.id)
    assert atual.nome == "MARIA EDUARDA SILVA"     # nada foi alterado
    # A linha em revisão PROTEGE o candidato da reconciliação: a lista disse que
    # alguém daquele grupo está na turma — marcá-lo "fora da lista" seria errado.
    assert atual.status == "ativo"
    assert corpo["alunos_fora_lista"] == 0


def test_d2_cadastro_disputado_por_duas_linhas_nao_e_entregue_a_primeira(
        cliente, db, escola_completa):
    """UNICIDADE 1:1 DO LOTE (herdeira da unicidade bipartida do motor antigo).

    O Elefante deixou o stub "AGATHA V" na sala. A Lista Piloto traz DUAS AGATHAs
    que ele abrevia: ele é de UMA delas, e nada no arquivo diz de qual. Resolvendo
    linha a linha, a PRIMEIRA do arquivo levaria o cadastro — e com ele os livros
    lidos da outra criança. Correspondência insegura → revisão, para as duas."""
    escola_id = escola_completa["escola"].id
    _plataforma(cliente, escola_id, "elefante", [
        {"nome": "AGATHA V", "dados": {"livros_unicos": 4},
         "criar_em_turma_nome": "1 ANO A TARDE ANUAL (300396600)"}])
    stub_id = _alunos(db, escola_id, "AGATHA")[0].id
    antes = _conta(db, escola_id)

    corpo = _confirmar(cliente, escola_id, _planilha(("1º Ano A", [
        _aluno("AGATHA VITORIA MOURA DA SILVA", numero=1),
        _aluno("AGATHA VALENTINA LIMA", numero=2),
    ])))
    assert corpo["alunos_criados"] == 0
    assert corpo["alunos_em_revisao"] == 2
    assert _conta(db, escola_id) == antes
    db.expire_all()
    assert db.get(Aluno, stub_id).nome == "AGATHA V"   # ninguém levou o cadastro


# ---------------------------------------------------------------------------
# E) Homônimos REAIS continuam duas pessoas
# ---------------------------------------------------------------------------

def test_e_homonimos_reais_continuam_duas_pessoas(cliente, db, escola_completa):
    """Duas crianças de mesmo nome na mesma sala, cada uma com o seu RA e o seu
    nº de chamada: são DUAS pessoas, hoje e em toda reimportação — e cada linha
    casa com a SUA (o veto de identidade impede roubar dados do homônimo)."""
    escola_id = escola_completa["escola"].id
    conteudo = _planilha(("6º Ano A", [
        _aluno("JOAO SILVA", numero=1, ra="111.111.111-1", nasc=date(2014, 1, 20)),
        _aluno("JOAO SILVA", numero=2, ra="222.222.222-2", nasc=date(2014, 9, 30)),
    ]))
    corpo = _confirmar(cliente, escola_id, conteudo)
    assert corpo["alunos_criados"] == 2
    assert _conta(db, escola_id, "JOAO SILVA") == 2

    # Reimportar mantém DOIS (e cada um casa com o seu, sem trocar de dono).
    corpo = _confirmar(cliente, escola_id, conteudo)
    assert corpo["alunos_criados"] == 0 and corpo["alunos_em_revisao"] == 0
    joaos = _alunos(db, escola_id, "JOAO SILVA")
    assert len(joaos) == 2
    assert {j.numero_chamada for j in joaos} == {1, 2}
    assert {(j.ficha or {}).get("ra") for j in joaos} == {"111.111.111-1",
                                                          "222.222.222-2"}
    assert {j.data_nascimento for j in joaos} == {date(2014, 1, 20), date(2014, 9, 30)}


def test_e2_homonimos_sem_ra_sao_colapsados_ANTES_pelo_parser(cliente, db,
                                                              escola_completa):
    """LIMITE CONHECIDO (pré-existente, do PARSER — fora da porta de identidade):
    duas linhas de mesmo nome na MESMA aba, sem RA, são colapsadas em UMA por
    ``lista_piloto.analisar_matriculas`` (chave = RA, senão nome normalizado)
    antes de a resolução de identidade ver qualquer coisa. O nº de chamada NÃO é
    usado nessa chave. O gestor é avisado, mas para cadastrar dois homônimos na
    mesma sala pela planilha é preciso RA (ver o teste acima).

    Registrado como teste para que o comportamento seja verdade documentada, e
    não surpresa — o motor de identidade em si separa por chamada (ver E3)."""
    escola_id = escola_completa["escola"].id
    conteudo = _planilha(("6º Ano B", [
        _aluno("PEDRO HENRIQUE COSTA", numero=1),
        _aluno("PEDRO HENRIQUE COSTA", numero=2),
    ]))
    corpo = _confirmar(cliente, escola_id, conteudo)
    assert corpo["alunos_criados"] == 1
    assert any("mais de uma vez" in av for av in corpo["avisos"])
    assert _conta(db, escola_id, "PEDRO HENRIQUE COSTA") == 1


def test_e3_numero_de_chamada_separa_homonimos_no_motor(db, escola_completa):
    """O que o parser colapsa, o MOTOR separa: alimentando ``_persistir_linhas``
    com as duas linhas (é o que chegaria de uma planilha com abas separadas ou de
    outra fonte), dois JOÃO SILVA de chamadas distintas viram duas pessoas — e
    reimportar não cria uma terceira nem funde as duas."""
    escola = escola_completa["escola"]
    turma, usuario = escola_completa["turma"], escola_completa["admin"]
    linhas = [(turma, lista_piloto.AlunoMatricula(nome="JOAO SILVA",
                                                  numero_chamada=n, ficha={}))
              for n in (1, 2)]

    estado = imp._carregar_estado(db, escola.id, ANO)
    resultado = imp._persistir_linhas(db, escola.id, ANO, usuario, linhas, estado)
    db.commit()
    assert resultado.criados == 2

    estado2 = imp._carregar_estado(db, escola.id, ANO)
    de_novo = imp._persistir_linhas(db, escola.id, ANO, usuario, linhas, estado2)
    db.commit()
    assert (de_novo.criados, de_novo.em_revisao) == (0, 0)
    joaos = _alunos(db, escola.id, "JOAO SILVA")
    assert len(joaos) == 2 and {j.numero_chamada for j in joaos} == {1, 2}


# ---------------------------------------------------------------------------
# F) "Fora da lista piloto" continua sendo identidade
# ---------------------------------------------------------------------------

def test_f_aluno_fora_da_lista_nao_gera_segunda_ficha(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    cheia = _planilha(("2º Ano A", [
        _aluno("ANA PILOTO UM", numero=1, ra="111.111.111-1", nasc=date(2017, 1, 1)),
        _aluno("BRUNO PILOTO DOIS", numero=2, nasc=date(2017, 2, 2)),
    ]))
    _confirmar(cliente, escola_id, cheia)
    bruno_id = [a.id for a in _alunos(db, escola_id, "BRUNO PILOTO")][0]
    antes = _conta(db, escola_id)

    # Bruno some da lista → "fora_lista_piloto" (continua cadastrado).
    reduzida = _planilha(("2º Ano A", [
        _aluno("ANA PILOTO UM", numero=1, ra="111.111.111-1", nasc=date(2017, 1, 1))]))
    assert _confirmar(cliente, escola_id, reduzida)["alunos_fora_lista"] == 1
    db.expire_all()
    assert db.get(Aluno, bruno_id).status == "fora_lista_piloto"

    # O Elefante importa o Bruno enquanto ele está fora: reconhece, não cria...
    _plataforma(cliente, escola_id, "elefante", [
        {"nome": "BRUNO PILOTO DOIS", "dados": {"livros_unicos": 2},
         "criar_em_turma_nome": "2 ANO A TARDE ANUAL (300396600)"}])
    assert _conta(db, escola_id) == antes
    db.expire_all()
    # ...e reconhecer NÃO reativa (identidade ≠ matrícula).
    assert db.get(Aluno, bruno_id).status == "fora_lista_piloto"

    # Bruno volta à lista: reativa o MESMO cadastro, sem criar outro.
    corpo = _confirmar(cliente, escola_id, cheia)
    assert corpo["alunos_criados"] == 0
    assert _conta(db, escola_id) == antes
    db.expire_all()
    assert db.get(Aluno, bruno_id).status == "ativo"


# ---------------------------------------------------------------------------
# G) Mudança de turma: muda a MATRÍCULA, não a pessoa
# ---------------------------------------------------------------------------

def test_g_mudanca_de_turma_move_a_matricula_sem_criar_identidade(
        cliente, db, escola_completa):
    """Com RA (identificador forte) e SEM RA (nome idêntico + nascimento como
    prova) — nos dois casos a criança é a mesma; o que muda é onde ela estuda."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha(("3º Ano B", [
        _aluno("MARIA EDUARDA SILVA", numero=1, ra="123.100.026-0",
               nasc=date(2015, 3, 1)),
        _aluno("PEDRO LUCAS SANTOS", numero=2, nasc=date(2015, 7, 9)),
    ])))
    ids = {a.nome: a.id for a in _alunos(db, escola_id)}
    antes = _conta(db, escola_id)

    corpo = _confirmar(cliente, escola_id, _planilha(("3º Ano C", [
        _aluno("MARIA EDUARDA SILVA", numero=7, ra="123.100.026-0",
               nasc=date(2015, 3, 1)),
        _aluno("PEDRO LUCAS SANTOS", numero=8, nasc=date(2015, 7, 9)),
    ])))
    assert corpo["alunos_criados"] == 0
    assert _conta(db, escola_id) == antes
    for nome in ["MARIA EDUARDA SILVA", "PEDRO LUCAS SANTOS"]:
        assert _turma_de(db, ids[nome]) == "3º Ano C", nome


def test_g2_homonimo_em_outra_turma_nao_e_absorvido_pela_mudanca_de_sala(
        cliente, db, escola_completa):
    """O reverso do G: mesmo nome em outra sala com nascimento DIFERENTE é outra
    criança — a regra de mudança de sala não pode engoli-la."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha(("7º Ano A", [
        _aluno("LUCAS ANDRADE PIRES", numero=1, nasc=date(2013, 5, 5))])))
    corpo = _confirmar(cliente, escola_id, _planilha(("7º Ano B", [
        _aluno("LUCAS ANDRADE PIRES", numero=1, nasc=date(2014, 11, 11))])))
    assert corpo["alunos_criados"] == 1
    assert _conta(db, escola_id, "LUCAS ANDRADE PIRES") == 2


# ---------------------------------------------------------------------------
# H) INTEGRAÇÃO ponta a ponta
# ---------------------------------------------------------------------------

def test_h_integracao_lista_elefante_matific_lista_elefante_sync(
        cliente, db, escola_completa):
    """Lista Piloto → Elefante → Matific → Lista Piloto → Elefante → sync.

    Cada fonte escreve o nome do seu jeito. Ao final: 1 aluno por criança, 1
    matrícula por criança e 1 identidade externa por (criança, plataforma).
    O último passo entra pelo MESMO caminho da sincronização automática
    (``sincronizar_turma=True``, ``permitir_criar_turma=False``), que é como o
    orquestrador chama ``confirmar``."""
    escola_id = escola_completa["escola"].id
    rotulo_turma = "1 ANO A TARDE ANUAL (300396600)"
    lista = _planilha(("1º Ano A", [
        _aluno("AGATHA VITORIA MOURA DA SILVA", numero=1, ra="123.100.026-0",
               nasc=date(2019, 9, 18)),
        _aluno("ABRAÃO LUÍS DIAS", numero=2, nasc=date(2019, 3, 4)),
        _aluno("MARIA EDUARDA SILVA", numero=3, nasc=date(2019, 6, 7)),
    ]))
    assert _confirmar(cliente, escola_id, lista)["alunos_criados"] == 3
    base = _conta(db, escola_id)

    # Elefante: abreviação e variação de grafia.
    _plataforma(cliente, escola_id, "elefante", [
        {"nome": "AGATHA V", "dados": {"livros_unicos": 3},
         "criar_em_turma_nome": rotulo_turma},
        {"nome": "ABRAAO LUIZ DIAS", "dados": {"livros_unicos": 5},
         "criar_em_turma_nome": rotulo_turma},
    ])
    # Matific: abreviação + UUID.
    _plataforma(cliente, escola_id, "matific", [
        {"nome": "MARIA E",
         "dados": {"atividades": 12, "estrelas": 30, "pontuacao_media": 80,
                   "matific_uuid": "uuid-maria"},
         "criar_em_turma_nome": rotulo_turma},
    ])
    # Lista Piloto de novo (renumerada, como a secretaria faz).
    _confirmar(cliente, escola_id, _planilha(("1º Ano A", [
        _aluno("MARIA EDUARDA SILVA", numero=1, nasc=date(2019, 6, 7)),
        _aluno("AGATHA VITORIA MOURA DA SILVA", numero=2, ra="123.100.026-0",
               nasc=date(2019, 9, 18)),
        _aluno("ABRAÃO LUÍS DIAS", numero=3, nasc=date(2019, 3, 4)),
    ])))
    # Elefante de novo.
    _plataforma(cliente, escola_id, "elefante", [
        {"nome": "AGATHA V", "dados": {"livros_unicos": 6},
         "criar_em_turma_nome": rotulo_turma},
    ])
    # Sincronização automática (mesmos flags do orquestrador).
    _plataforma(cliente, escola_id, "matific", [
        {"nome": "MARIA E",
         "dados": {"atividades": 20, "estrelas": 44, "pontuacao_media": 82,
                   "matific_uuid": "uuid-maria"},
         "criar_em_turma_nome": rotulo_turma}],
        sincronizar_turma=True, permitir_criar_turma=False)

    assert _conta(db, escola_id) == base, "alguém virou duas fichas no caminho"
    for nome in ["AGATHA VITORIA MOURA DA SILVA", "ABRAÃO LUÍS DIAS",
                 "MARIA EDUARDA SILVA"]:
        iguais = [a for a in _alunos(db, escola_id) if a.nome == nome]
        assert len(iguais) == 1, f"{nome}: {len(iguais)} fichas"
        assert len(_matriculas(db, iguais[0].id)) == 1, f"{nome}: matrícula duplicada"
    # Identidade externa: uma só, e apontando para a Maria (não para um clone).
    vinculos = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == escola_id)).scalars().all()
    assert len(vinculos) == 1
    assert db.get(Aluno, vinculos[0].aluno_id).nome == "MARIA EDUARDA SILVA"


# ---------------------------------------------------------------------------
# I) CONCORRÊNCIA REAL (dois workers, duas conexões, duas transações)
# ---------------------------------------------------------------------------

def _banco_de_arquivo(pasta):
    """Banco SQLite em ARQUIVO (não :memory:) para que cada thread abra a SUA
    conexão — sem isto não há corrida nenhuma para observar. WAL para leitor não
    bloquear escritor, como em Postgres."""
    engine = create_engine(f"sqlite:///{Path(pasta) / 'corrida.db'}",
                           connect_args={"check_same_thread": False})
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    s = Sessao()
    escola = Escola(nome="ESCOLA CORRIDA", ano_letivo_ativo=ANO)
    s.add(escola)
    s.flush()
    s.add(Turma(escola_id=escola.id, nome="1º Ano A", ano_escolar="1º Ano",
                ano_letivo=ANO))
    s.add(Usuario(escola_id=escola.id, nome="Admin", email="a@corrida.local",
                  senha_hash="x", cargo="admin"))
    s.commit()
    escola_id = escola.id
    s.close()
    return Sessao, escola_id


def _corrida(Sessao, escola_id, *, serializar: bool):
    """DOIS workers de verdade importando a MESMA linha da Lista Piloto, com o
    entrelaçamento forçado que a produção sofre: ambos LEEM o estado antes de
    qualquer um GRAVAR. ``serializar`` emula o ``pg_advisory_xact_lock`` do
    Postgres (exclusão mútua até o commit)."""
    trava = threading.Lock()
    leu = threading.Event()
    gravou = threading.Event()
    erros: list[str] = []

    parsed = lista_piloto.AlunoMatricula(
        nome="MARIA EDUARDA SILVA", numero_chamada=1,
        data_nascimento="2015-03-01", ficha={})

    def worker(indice: int):
        sessao = Sessao()
        try:
            if serializar:
                trava.acquire()
            try:
                turma = sessao.execute(select(Turma).where(
                    Turma.escola_id == escola_id)).scalars().first()
                usuario = sessao.execute(select(Usuario).where(
                    Usuario.escola_id == escola_id)).scalars().first()
                estado = imp._carregar_estado(sessao, escola_id, ANO)
                if not serializar:
                    # Sem trava: os dois leem "não existe" antes de qualquer
                    # gravação — exatamente a corrida real.
                    if indice == 0:
                        leu.set()
                        gravou.wait(timeout=5)
                    else:
                        leu.wait(timeout=5)
                imp._persistir_linhas(sessao, escola_id, ANO, usuario,
                                      [(turma, parsed)], estado)
                sessao.commit()
                if not serializar and indice == 1:
                    gravou.set()
            finally:
                if serializar:
                    trava.release()
        except Exception as exc:  # noqa: BLE001 — o teste RELATA a falha real
            erros.append(f"{type(exc).__name__}: {exc}")
            gravou.set()
            leu.set()
            sessao.rollback()
        finally:
            sessao.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
        time.sleep(0.01)          # dá ao worker 0 a chance de ler primeiro
    for t in threads:
        t.join(timeout=15)
        assert not t.is_alive(), "worker travou"

    conferencia = Sessao()
    total = conferencia.execute(select(func.count()).select_from(Aluno).where(
        Aluno.escola_id == escola_id)).scalar_one()
    conferencia.close()
    return total, erros


@pytest.fixture()
def pasta_corrida():
    """Diretório próprio (não depende do --basetemp do pytest)."""
    caminho = tempfile.mkdtemp(prefix="corrida_")
    yield caminho
    shutil.rmtree(caminho, ignore_errors=True)


def test_i_dois_workers_serializados_convergem_para_um_aluno(pasta_corrida):
    """PROVADO: com exclusão mútua de verdade (o que ``pg_advisory_xact_lock``
    dá em produção), dois workers concorrentes resolvendo a MESMA criança
    terminam com UM aluno — a resolução é idempotente sob serialização."""
    Sessao, escola_id = _banco_de_arquivo(pasta_corrida)
    total, erros = _corrida(Sessao, escola_id, serializar=True)
    assert erros == [], erros
    assert total == 1


def test_i2_sem_serializacao_o_banco_sozinho_nao_protege(pasta_corrida):
    """NÃO PROVADO por este banco: em SQLite ``bloquear_escola_para_importacao``
    é no-op, e nada no schema impede duas fichas (alunos NÃO têm unique por nome
    — dois homônimos reais são legítimos). Com os dois workers lendo o estado
    antes de qualquer gravação, o resultado é 2 fichas (ou um erro de banco).

    É por isso que a defesa real é a TRAVA POR ESCOLA no Postgres, adquirida
    ANTES de ler o estado (ver ``test_i3``): ela transforma esta corrida no
    cenário do teste anterior. Este teste existe para que a ausência de proteção
    fique explícita, e não escondida atrás de um SQLite que serializa sozinho."""
    Sessao, escola_id = _banco_de_arquivo(pasta_corrida)
    total, erros = _corrida(Sessao, escola_id, serializar=False)
    assert erros or total == 2, (
        f"esperava a corrida NÃO protegida (2 fichas ou erro), veio {total} sem erro")


def test_i3_a_trava_por_escola_e_adquirida_antes_de_ler_o_estado(
        cliente, db, escola_completa, monkeypatch):
    """A ordem é o que torna a trava útil: travar DEPOIS de ler o estado não
    impediria nada (os dois já teriam lido "não existe")."""
    ordem: list[str] = []
    trava_real = imp.bloquear_escola_para_importacao
    estado_real = imp._carregar_estado

    monkeypatch.setattr(imp, "bloquear_escola_para_importacao",
                        lambda s, eid: (ordem.append("trava"), trava_real(s, eid))[1])
    monkeypatch.setattr(imp, "_carregar_estado",
                        lambda s, eid, ano: (ordem.append("estado"),
                                             estado_real(s, eid, ano))[1])

    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha(("8º Ano A", [
        _aluno("NOVO ALUNO TRAVA", numero=1, nasc=date(2012, 1, 1))])))
    assert ordem == ["trava", "estado"]


@pytest.mark.parametrize("dialeto,esperado", [("postgresql", 1), ("sqlite", 0)])
def test_i4_trava_emite_advisory_lock_no_postgres(dialeto, esperado, monkeypatch):
    """A trava que o teste I1 emula existe de verdade — e só no Postgres."""
    from app.core import database as core_db

    executados: list[str] = []

    class _Dialeto:
        name = dialeto

    class _Bind:
        dialect = _Dialeto()

    class _Sessao:
        def get_bind(self):
            return _Bind()

        def execute(self, sql, params=None):
            executados.append(str(sql))

    core_db.bloquear_escola_para_importacao(_Sessao(), 7)
    assert len([s for s in executados if "pg_advisory_xact_lock" in s]) == esperado
