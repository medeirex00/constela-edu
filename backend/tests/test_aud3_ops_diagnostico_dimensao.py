"""S_G_SCRIPTS-1 — ``scripts/diagnostico_dimensao_zero.py`` conta como o MOTOR.

O script (uso documentado: produção, só leitura) mede quantas crianças pontuadas têm uma
dimensão aferida e a outra ausente. Ele contava com regras próprias:

* a população era toda matrícula ativa do ano, com as Fases (Educação Infantil), que o
  motor tira da premiação antes de qualquer conta;
* "aferido em Matemática" era ter QUALQUER retrato do Matific, de qualquer ano; o motor só
  afere pelo retrato DO ANO letivo (``scoring.snapshots_matific_do_ano``);
* "aferido em Leitura" era ter retrato do Elefante; o motor também afere pelas leituras
  itemizadas sem retrato (``dificuldade_livro.insumos_elefante``);
* a dimensão de um módulo que a rede não contratou contava como "ausente".

Resultado: os "candidatos ao bug" saíam a menos (Matific do ano anterior virava
"completo") ou a mais (leitura itemizada virava "Leitura 0"), e o total não batia com o
ranking. Aqui o script tem de dar os mesmos números que ``Nota.detalhes['dimensoes']``
do motor. Dados INVENTADOS, datas fixas no ano da escola.
"""
import contextlib
import io
import sys
from datetime import datetime

from sqlalchemy import select

from app.models import (
    Aluno, Escola, Importacao, Leitura, Livro, Matricula, ModuloRede, Nota, Rede,
    SnapshotElefante, SnapshotMatific, Turma,
)
from app.services import scoring
from scripts import diagnostico_dimensao_zero as diag
from tests._ano_letivo import ANO_DAS_DATAS_FIXAS

ANO = ANO_DAS_DATAS_FIXAS
NO_ANO = datetime(ANO, 6, 10, 12, 0)
ANO_ANTERIOR = datetime(ANO - 1, 11, 20, 12, 0)


def _escola(db, *, rede_id=None):
    esc = Escola(nome="EMEF Fictícia Diagnóstico", ano_letivo_ativo=ANO, rede_id=rede_id)
    db.add(esc)
    db.flush()
    t3 = Turma(escola_id=esc.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=ANO)
    fase = Turma(escola_id=esc.id, nome="1ª Fase A", ano_escolar="1ª Fase", ano_letivo=ANO)
    db.add_all([t3, fase])
    db.flush()
    imp_m = Importacao(escola_id=esc.id, plataforma="matific", tipo="texto")
    imp_e = Importacao(escola_id=esc.id, plataforma="elefante", tipo="texto")
    db.add_all([imp_m, imp_e])
    db.flush()
    return esc, t3, fase, imp_m, imp_e


def _crianca(db, esc, turma, nome):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=ANO))
    return a


def _matific(db, esc, imp, aluno, quando):
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=20, estrelas=40,
                           pontuacao_media=70.0))


def _elefante(db, esc, imp, aluno):
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                            data_referencia=NO_ANO, livros_unicos=5,
                            livros_por_nivel={"C": 5}))


def _povoar(db, esc, t3, fase, imp_m, imp_e):
    """Ana: Elefante + Matific SÓ do ano anterior (o motor não a afere em Matemática).
    Beto: as duas no ano. Caio: Fase, sem plataforma (fora da população pontuada).
    Dani: só Elefante. Eva: Matific do ano + UMA leitura itemizada, sem retrato do
    Elefante (o motor a afere em Leitura). Gil: Fase com as duas plataformas (fora)."""
    ana = _crianca(db, esc, t3, "Ana Inventada Diagnostico")
    beto = _crianca(db, esc, t3, "Beto Inventado Diagnostico")
    caio = _crianca(db, esc, fase, "Caio Inventado Diagnostico")
    dani = _crianca(db, esc, t3, "Dani Inventada Diagnostico")
    eva = _crianca(db, esc, t3, "Eva Inventada Diagnostico")
    gil = _crianca(db, esc, fase, "Gil Inventado Diagnostico")
    _matific(db, esc, imp_m, ana, ANO_ANTERIOR)
    for a in (beto, eva, gil):
        _matific(db, esc, imp_m, a, NO_ANO)
    for a in (ana, beto, dani, gil):
        _elefante(db, esc, imp_e, a)
    livro = Livro(escola_id=esc.id, titulo="Livro Inventado do Diagnóstico", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=eva.id, livro_id=livro.id, data=NO_ANO))
    db.commit()
    return {"ana": ana, "beto": beto, "caio": caio, "dani": dani, "eva": eva, "gil": gil}


def _rodar_script(db, esc):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        r = diag._diagnostico_escola(db, esc.id, esc.nome, esc.ano_letivo_ativo, 10)
    return r, saida.getvalue()


def _contagem_do_motor(db, esc):
    """As mesmas categorias do script, lidas do que o motor gravou para as crianças
    que ele pontua (as Fases ficam sem Nota do ano)."""
    scoring.recalcular_escola(db, esc.id)
    notas = db.execute(select(Nota).where(Nota.escola_id == esc.id,
                                          Nota.ano_letivo == ANO)).scalars().all()
    c = {"total": 0, "ambas": 0, "so_contratado": 0, "so_matific": 0, "so_elefante": 0,
         "nenhuma": 0}
    for n in notas:
        dims = n.detalhes["dimensoes"]
        le, ma = dims["leitura"]["aferido"], dims["matematica"]["aferido"]
        c["total"] += 1
        if le and ma:
            c["ambas"] += 1
        elif ma:
            c["so_matific"] += 1
        elif le:
            c["so_elefante"] += 1
        else:
            c["nenhuma"] += 1
    return c


def test_diagnostico_conta_a_populacao_e_o_aferido_do_motor(db):
    esc, t3, fase, imp_m, imp_e = _escola(db)
    _povoar(db, esc, t3, fase, imp_m, imp_e)

    r, texto = _rodar_script(db, esc)

    # Fases fora: só as 4 do 3º ano; Ana (Matific de outro ano) e Dani são "Matific
    # ausente"; Eva (leitura itemizada) tem as duas; ninguém é "Leitura ausente".
    assert r == {"total": 4, "ambas": 2, "so_contratado": 0, "so_matific": 0,
                 "so_elefante": 2, "nenhuma": 0}
    assert "Ana Inventada Diagnostico" in texto        # a lista mostra a criança do caso
    assert "Caio Inventado Diagnostico" not in texto and "Gil Inventado" not in texto
    # e é exatamente o que o motor grava
    assert r == _contagem_do_motor(db, esc)


def test_diagnostico_ignora_a_dimensao_que_a_rede_nao_contratou(db):
    """Rede só com Leitura: a Matemática não existe para a escola (o motor não afere
    ninguém nela e ninguém fica "sem Matemática"). Ter Elefante é estar completo; a
    criança de Matific de outro ano não vira candidata ao bug. Completo aqui não é ter
    "as duas" (REV3-OPS-1): conta em "so_contratado", não em "ambas"."""
    rede = Rede(nome="Rede Fictícia Só Leitura Diagnóstico", codigo_ibge="3599971")
    db.add(rede)
    db.flush()
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    esc, t3, fase, imp_m, imp_e = _escola(db, rede_id=rede.id)
    _povoar(db, esc, t3, fase, imp_m, imp_e)

    r, _texto = _rodar_script(db, esc)

    assert r["total"] == 4
    assert r["so_matific"] == 0 and r["so_elefante"] == 0     # nenhuma candidata
    assert r["so_contratado"] == 4 and r["nenhuma"] == 0      # Ana, Beto, Dani e Eva leem
    assert r["ambas"] == 0                                    # e nenhuma tem as duas


# REV3-OPS-1 — o bloco TOTAL de main() somava, na linha "AMBAS", as crianças da rede de
# um módulo só (aferidas no único módulo contratado). No uso documentado (todas as
# escolas, ou --rede), o TOTAL dizia que elas tinham as duas dimensões quando a outra
# nem existe na rede delas.

ROTULO_UM_MODULO = "aferido no único módulo contratado (rede de um módulo)"


def _rede_so_leitura(db, codigo_ibge):
    rede = Rede(nome=f"Rede Fictícia Só Leitura {codigo_ibge}", codigo_ibge=codigo_ibge)
    db.add(rede)
    db.flush()
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    return rede


def _rodar_main(db, monkeypatch, *argumentos):
    monkeypatch.setattr(diag, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(sys, "argv", ["diagnostico_dimensao_zero", *argumentos])
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        assert diag.main() == 0
    return saida.getvalue()


def _bloco_total(texto):
    """{rótulo: número} das linhas do bloco TOTAL (sem os pontinhos do alinhamento)."""
    bloco = texto.split("===== TOTAL =====", 1)[1]
    linhas = {}
    for linha in bloco.strip().splitlines():
        rotulo, _, valor = linha.strip().rpartition(" ")
        linhas[rotulo.rstrip(". ")] = int(valor)
    return linhas


def test_total_da_rede_de_um_modulo_nao_diz_ambas(db, monkeypatch):
    """Rede só com Leitura, rodada com --rede: as 4 crianças pontuadas leem, nenhuma
    tem as duas dimensões (a Matemática nem existe ali)."""
    rede = _rede_so_leitura(db, "3599973")
    esc, t3, fase, imp_m, imp_e = _escola(db, rede_id=rede.id)
    _povoar(db, esc, t3, fase, imp_m, imp_e)

    texto = _rodar_main(db, monkeypatch, "--rede", str(rede.id))
    total = _bloco_total(texto)

    assert total["AMBAS"] == 0
    assert total[ROTULO_UM_MODULO] == 4
    assert total["alunos"] == 4
    assert total["candidatos ao bug"] == 0
    # a linha da escola continua dizendo o mesmo que o total
    assert "aferido no módulo contratado ...... 4" in texto


def test_total_de_todas_as_escolas_separa_as_redes_de_um_modulo(db, monkeypatch):
    """Todas as escolas (sem filtro): uma escola com os dois módulos e uma de rede só
    com Leitura, com as mesmas crianças. "AMBAS" conta só a dos dois módulos (Beto e
    Eva); as 4 da rede de um módulo ficam na linha própria; as contas fecham."""
    _escola_dois, *resto_dois = _escola(db)
    _povoar(db, _escola_dois, *resto_dois)
    rede = _rede_so_leitura(db, "3599974")
    esc_um, *resto_um = _escola(db, rede_id=rede.id)
    _povoar(db, esc_um, *resto_um)

    total = _bloco_total(_rodar_main(db, monkeypatch))

    assert total["AMBAS"] == 2
    assert total[ROTULO_UM_MODULO] == 4
    assert total["SÓ Elefante (Mat. 0)"] == 2           # Ana e Dani, da escola dos dois
    assert total["SÓ Matific (Leit. 0)"] == 0
    assert total["nenhuma"] == 0
    assert total["candidatos ao bug"] == 2
    assert total["alunos"] == 8 == (
        total["AMBAS"] + total[ROTULO_UM_MODULO] + total["SÓ Elefante (Mat. 0)"]
        + total["SÓ Matific (Leit. 0)"] + total["nenhuma"])
