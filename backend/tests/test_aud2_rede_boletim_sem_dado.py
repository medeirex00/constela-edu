"""G_ANALISE-6 — o Boletim da Rede não imprime "0,0" na média de uma plataforma
CONTRATADA quando a escola não tem nenhum aluno com nota dela.

``_cartoes_da_rede`` manda ``media_matific`` / ``media_elefante`` = 0,0 quando
``alunos_com_nota_<plataforma>`` = 0 — a ausência só fica marcada pelo contador. O
Boletim (tabela HTML e a reserva fpdf/CSV) imprimia ``_fmt_nota(0.0)`` = "0,0", lido
como nota zero numa reunião. Agora sai "sem dado" (o "—" do Boletim é a matéria
escondida para proteger as crianças, outro motivo).

Não é o RELATORIOS-3 (módulo NÃO contratado: a coluna nem existe). Aqui a rede
contratou as duas plataformas e cada escola usa só uma.

Rede, escolas e crianças FICTÍCIAS.
"""
from datetime import datetime

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import rede as svc_rede
from app.services import relatorios as svc_relatorios
from app.services import scoring
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

QUANDO = datetime(2026, 9, 30, 3, 0)
SO_LEITURA, SO_MATIFIC = "EMEF Inventada Lambda", "EMEF Inventada Mu"


def _imp(db, escola):
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed", status="concluida")
    db.add(imp)
    db.flush()
    return imp


def _rede_com_uma_plataforma_por_escola(db):
    rede = nova_rede(db, nome="Rede Inventada Duas Plataformas", codigo="3599992")
    lam = nova_escola(db, rede, SO_LEITURA, None)
    imp = _imp(db, lam)
    for i, a in enumerate(turma_com_alunos(db, lam, "3º Ano", 6)):
        db.add(SnapshotElefante(escola_id=lam.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=QUANDO, livros_unicos=5 + i,
                                tempo_leitura_min=50, questoes_tentativas=0,
                                questoes_acertos=0, livros_por_nivel={}))
    mu = nova_escola(db, rede, SO_MATIFIC, None)
    imp = _imp(db, mu)
    for i, a in enumerate(turma_com_alunos(db, mu, "3º Ano", 6)):
        db.add(SnapshotMatific(escola_id=mu.id, aluno_id=a.id, importacao_id=imp.id,
                               data_referencia=QUANDO, atividades=10 + i, estrelas=30 + i,
                               pontuacao_media=0.0))
    db.commit()
    scoring.recalcular_escola(db, lam.id)
    scoring.recalcular_escola(db, mu.id)
    return rede


def test_tabela_do_boletim_diz_sem_dado_na_plataforma_que_a_escola_nao_usa(db):
    rede = _rede_com_uma_plataforma_por_escola(db)
    dados = svc_rede.dashboard_rede(db, rede.id)
    cabecalho, linhas = svc_relatorios.linhas_boletim_rede(dados)
    assert cabecalho[5:] == ["Matific", "Elefante", "Geral"]
    por_nome = {linha[1]: linha for linha in linhas}
    lam, mu = por_nome[SO_LEITURA], por_nome[SO_MATIFIC]
    # Antes: Matific "0,0" na Lambda e Elefante "0,0" na Mu.
    assert lam[5] == "sem dado" and lam[6] not in ("sem dado", "0,0")
    assert mu[6] == "sem dado" and mu[5] not in ("sem dado", "0,0")
    # A Geral é só da plataforma com dado (a média das dimensões disponíveis).
    assert lam[7] == lam[6] and mu[7] == mu[5]

    html = svc_relatorios._shell_boletim_rede(rede.nome, dados)
    ranking = html.split("Ranking das escolas", 1)[1].split("</table>", 1)[0]
    for nome, linha in ((SO_LEITURA, lam), (SO_MATIFIC, mu)):
        celulas = ranking.split(nome, 1)[1].split("</tr>", 1)[0]
        assert "<td>0,0</td>" not in celulas
        assert "<td>sem dado</td>" in celulas
        assert f"<td>{linha[7]}</td>" in celulas


def test_cartao_sem_nota_nenhuma_nao_tem_geral_zero():
    """A escola comparada (tem retrato de quem concorre) ainda sem nenhuma nota
    calculada: as médias e a geral saem "sem dado"; a matéria escondida da Secretaria
    continua "—"; o cartão montado fora do painel, sem os contadores, segue com o
    número, como antes."""
    base = {"posicao": 1, "nome": "EM Inventada Nu", "total_alunos": 10, "adocao": 80.0,
            "pontuacao_geral": 1000.0, "media_matific": 0.0, "media_elefante": 0.0,
            "media_geral": 0.0}
    sem_nota = {**base, "alunos_com_nota_matific": 0, "alunos_com_nota_elefante": 0}
    escondida = {**base, "nome": "EM Inventada Xi", "media_elefante": None,
                 "alunos_com_nota_matific": 4, "alunos_com_nota_elefante": 2,
                 "media_matific": 50.0, "media_geral": 50.0}
    _, linhas = svc_relatorios.linhas_boletim_rede({"escolas": [sem_nota, escondida, base]})
    assert linhas[0][5:] == ["sem dado", "sem dado", "sem dado"]
    assert linhas[1][5:] == ["50,0", "—", "50,0"]
    assert linhas[2][5:] == ["0,0", "0,0", "0,0"]


def test_quadro_da_media_da_rede_sem_nenhuma_nota_diz_sem_dado():
    dados = {"totais": {"escolas": 1, "alunos": 10, "adocao": 80.0, "media_geral": 0.0},
             "escolas": [{"posicao": 1, "nome": "EM Inventada Nu", "total_alunos": 10,
                          "adocao": 80.0, "pontuacao_geral": 1000.0, "media_matific": 0.0,
                          "media_elefante": 0.0, "media_geral": 0.0,
                          "alunos_com_nota_matific": 0, "alunos_com_nota_elefante": 0}]}
    html = svc_relatorios._shell_boletim_rede("Rede Inventada", dados)
    rotulo = '<div class="r">média das notas do Constela (0–100)</div>'
    assert f'<div class="n">sem dado</div>{rotulo}' in html
    assert f'<div class="n">0,0</div>{rotulo}' not in html
