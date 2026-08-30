"""O CONJUNTO da medição é o dos MATRICULADOS — em todas as camadas.

Varredura "ausência não é zero" (Bloco A). O irmão do zero-por-ausência é a
POPULAÇÃO ERRADA: a média sai de um conjunto que não é o conjunto pontuado.

``notas`` **não** é apagada quando o aluno perde a matrícula — o recálculo só
grava por cima das linhas do conjunto pontuado (``scoring.recalcular_escola``),
nunca deleta. Então a nota órfã de quem foi DESVINCULADO (excluir uma turma
antiga com ``com_alunos=true`` quando o aluno tem matrícula em outro ano; sair
da escola) sobrevive com ``Aluno.status == "ativo"`` e continuava entrando:

  * na média por dimensão da escola (``rede._medias_por_plataforma``,
    ``rankings._desempenho_da_escola``, ``evolucao._lado_escola``);
  * no denominador ``alunos_com_nota_*`` — que é o PESO das médias da rede
    (``rede._ponderada``);
  * no ``com_dados`` do Alcance, que podia passar de 100%.

``_totais_plataforma_por_escola`` já fechava esse furo com a matrícula (o mesmo
sintoma ``ativos_elefante > total_alunos``); as MÉDIAS não. Estes testes travam
as três camadas na mesma régua.
"""
from sqlalchemy import delete

from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Nota,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.routers.rankings import montar_dashboard
from app.services import evolucao as svc_evolucao
from app.services import rede as svc_rede

ANO = 2026


def _rede(db, nome="Rede Conjunto"):
    r = Rede(nome=nome, status="ativa")
    db.add(r)
    db.flush()
    return r


def _escola(db, rede_id, nome, alunos, *, notas_ele=None, notas_mat=None):
    """Escola com `alunos` matriculados ativos.

    ``notas_ele``/``notas_mat``: nota por aluno (None = SEM snapshot daquela
    plataforma). A Nota é gravada para todos, como o motor faz.
    Devolve ``(escola, turma, [aluno_id...])``.
    """
    esc = Escola(nome=nome, ano_letivo_ativo=ANO, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano", ano_letivo=ANO,
                  status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    notas_ele = notas_ele or [None] * alunos
    notas_mat = notas_mat or [None] * alunos
    ids = []
    for i in range(alunos):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        ids.append(a.id)
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ANO))
        ne, nm = notas_ele[i], notas_mat[i]
        if ne is not None:
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=5, tempo_leitura_min=60))
        if nm is not None:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   atividades=20, estrelas=100))
        db.add(Nota(escola_id=esc.id, aluno_id=a.id, ano_letivo=ANO,
                    nota_elefante=ne or 0.0, nota_matific=nm or 0.0,
                    # A rede lê as colunas institucionais; seedando Nota direto
                    # (sem recalcular_escola) elas nasceriam 0.0. Espelhamos o
                    # valor local para que a rede veja o número que o teste quer.
                    nota_elefante_institucional=ne or 0.0,
                    nota_matific_institucional=nm or 0.0,
                    nota_geral=((ne or 0.0) + (nm or 0.0)) / 2, posicao=i + 1,
                    aferido_leitura=ne is not None,
                    aferido_matematica=nm is not None))
    return esc, turma, ids


def _desvincular(db, aluno_ids):
    """Tira a matrícula do ano ativo SEM tocar em Aluno/Nota/snapshot — o estado
    real deixado por ``_excluir_turmas(com_alunos=True)`` e por quem sai da
    escola: o aluno continua ``ativo`` e a linha de ``notas`` continua no banco.
    """
    db.execute(delete(Matricula).where(Matricula.aluno_id.in_(aluno_ids),
                                       Matricula.ano_letivo == ANO))
    db.commit()


def _cartao(db, rede_id, nome):
    return next(c for c in svc_rede._kpis_da_rede(db, rede_id) if c["nome"] == nome)


# --- Camada REDE (cartão da escola no painel da Secretaria) ------------------

def test_nota_orfa_nao_entra_na_media_da_dimensao(db):
    """8 alunos com 80,0 e 2 desvinculados com 20,0.

    ANTES: media_elefante = 68,0 (a média dos 10, incluindo quem saiu).
    AGORA: 80,0 — a média dos 8 que continuam matriculados.
    """
    r = _rede(db)
    _esc, _turma, ids = _escola(db, r.id, "Escola P", 10,
                                notas_ele=[80.0] * 8 + [20.0, 20.0])
    db.commit()
    assert _cartao(db, r.id, "Escola P")["media_elefante"] == 68.0  # todos dentro

    _desvincular(db, ids[8:])

    c = _cartao(db, r.id, "Escola P")
    assert c["media_elefante"] == 80.0            # e NÃO 68,0
    assert c["alunos_com_nota_elefante"] == 8     # e NÃO 10
    assert c["total_alunos"] == 8


def test_denominador_da_dimensao_nunca_passa_do_total_de_alunos(db):
    """``alunos_com_nota_* > total_alunos`` é a assinatura do furo — o mesmo
    sintoma que ``ativos_elefante > total_alunos`` já denunciava nos totais."""
    r = _rede(db)
    _esc, _turma, ids = _escola(db, r.id, "Escola Q", 6,
                                notas_ele=[70.0] * 6, notas_mat=[60.0] * 6)
    db.commit()
    _desvincular(db, ids[4:])

    c = _cartao(db, r.id, "Escola Q")
    assert c["total_alunos"] == 4
    assert c["alunos_com_nota_elefante"] <= c["total_alunos"]
    assert c["alunos_com_nota_matific"] <= c["total_alunos"]
    # ...e continua batendo com as outras contagens do MESMO cartão, que já
    # exigiam matrícula (a divergência entre elas era o defeito).
    assert c["alunos_com_nota_elefante"] == c["ativos_elefante"] == 4
    assert c["alunos_com_dados"] == 4


def test_media_ponderada_da_rede_usa_o_peso_certo_depois_do_corte(db):
    """O peso das médias da rede é ``alunos_com_nota_*``. Com a nota órfã dentro,
    a escola pesava por alunos que já não são dela."""
    r = _rede(db)
    _e1, _t1, ids1 = _escola(db, r.id, "Escola R1", 10, notas_ele=[90.0] * 10)
    _escola(db, r.id, "Escola R2", 10, notas_ele=[50.0] * 10)
    db.commit()
    _desvincular(db, ids1[2:])                    # R1 fica com 2 alunos

    dados = svc_rede.dashboard_rede(db, r.id)
    # 2 alunos a 90 + 10 a 50 = (180 + 500) / 12 = 56,7 (antes: 10 e 10 → 70,0)
    assert dados["totais"]["media_elefante"] == 56.7


# --- Camada ESCOLA (dashboard do diretor / do professor) ---------------------

def test_dashboard_da_escola_ignora_nota_sem_matricula(db):
    r = _rede(db)
    esc, _turma, ids = _escola(db, r.id, "Escola S", 10,
                               notas_ele=[80.0] * 8 + [20.0, 20.0])
    db.commit()
    _desvincular(db, ids[8:])

    painel = montar_dashboard(db, esc.id)
    assert painel.media_leitura == 80.0           # e NÃO 68,0
    assert painel.alunos_com_dado_leitura == 8
    assert painel.total_alunos == 8
    # Alcance é `com_dados / total_alunos`: com o numerador contando gente que o
    # denominador já não conta, ele passava de 100%.
    assert painel.alcance == 100.0
    assert painel.nao_aferidos == 0


def test_dashboard_da_escola_bate_com_o_cartao_da_rede(db):
    """A MESMA escola tem de exibir o MESMO número nas duas telas — a régua é
    única. Sem o corte por matrícula elas divergiam de novo."""
    r = _rede(db)
    esc, _turma, ids = _escola(db, r.id, "Escola T", 12,
                               notas_ele=[75.0] * 9 + [10.0] * 3,
                               notas_mat=[60.0] * 9 + [10.0] * 3)
    db.commit()
    _desvincular(db, ids[9:])

    painel = montar_dashboard(db, esc.id)
    c = _cartao(db, r.id, "Escola T")
    assert painel.media_leitura == c["media_elefante"] == 75.0
    assert painel.media_matematica == c["media_matific"] == 60.0
    assert painel.media_geral == c["media_geral"]
    assert painel.total_alunos == c["total_alunos"] == 9


# --- Camada COMPARADOR (lado "escola") ---------------------------------------

def test_lado_escola_do_comparador_usa_o_mesmo_conjunto(db):
    r = _rede(db)
    esc, _turma, ids = _escola(db, r.id, "Escola U", 10,
                               notas_ele=[80.0] * 8 + [20.0, 20.0])
    db.commit()
    _desvincular(db, ids[8:])

    lado = svc_evolucao._lado_escola(db, esc.id)
    assert lado["total_alunos"] == 8
    assert lado["dimensoes"]["leitura"]["nota"] == 80.0      # e NÃO 68,0
    assert lado["dimensoes"]["leitura"]["n_aferidos"] == 8
    assert lado["notas"]["elefante"] == 80.0


# --- RÉGUA do índice da rede: sai só da coorte da dimensão -------------------

def test_regua_do_indice_sai_so_da_coorte_da_dimensao(db):
    """No painel GLOBAL a coorte mistura redes com contratos diferentes.

    Uma rede que NÃO assinou a Leitura (mas tem dado antigo do Elefante em
    banco) não pode definir ``melhor_leitura`` — ela não aparece em ranking de
    leitura nenhum, e ainda assim rebaixava o índice de quem assinou.
    """
    from app.services import modulos

    dentro = {"nome": "Assinou leitura", "modulos": ["leitura", "matematica"],
              "ativos_elefante": 10, "ativos_matific": 0,
              "livros_por_matricula": 5.0, "estrelas_por_matricula": 0.0}
    fora = {"nome": "Nao assinou leitura", "modulos": ["matematica"],
            "ativos_elefante": 10, "ativos_matific": 10,
            "livros_por_matricula": 20.0, "estrelas_por_matricula": 100.0}
    cartoes = [dentro, fora]
    svc_rede._pontuar_por_percapita(cartoes)

    # A régua é 5,0 (o melhor DENTRO da coorte de leitura), não 20,0.
    assert dentro["pontuacao_leitura"] == 1000.0   # antes: 5/20 → 250,0
    assert fora["pontuacao_leitura"] == 0.0        # segue fora da dimensão
    assert fora["dimensoes_pontuadas"] == ["matematica"]
    assert modulos.TODOS  # o fallback "sem 'modulos' = tudo contratado" segue


def test_regua_dentro_de_uma_rede_nao_muda(db):
    """Dentro de UMA rede o contrato é o mesmo para todas as escolas e quem não
    tem dado tem per capita 0 — a régua é idêntica antes e depois do corte.
    Nenhum número do painel municipal se move."""
    r = _rede(db)
    _escola(db, r.id, "Le muito", 10, notas_ele=[80.0] * 10)
    _escola(db, r.id, "So matematica", 10, notas_mat=[80.0] * 10)
    db.commit()

    cartoes = {c["nome"]: c for c in svc_rede._kpis_da_rede(db, r.id)}
    assert cartoes["Le muito"]["pontuacao_leitura"] == 1000.0
    # A escola sem Elefante não entra na coorte de leitura (per capita 0) e não
    # rebaixa nem é rebaixada: só a dimensão que ela tem é pontuada.
    assert cartoes["So matematica"]["dimensoes_pontuadas"] == ["matematica"]
    assert cartoes["So matematica"]["pontuacao_matematica"] == 1000.0
