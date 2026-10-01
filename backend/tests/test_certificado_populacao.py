"""Certificado só sai para quem está na população ATIVA da escola.

Descoberto na véspera da entrega dos certificados da EMEI / EMEF João Thimóteo do
Rosário: ``GET /escolas/{id}/certificados/{aluno_id}`` não olhava
``aluno.status``. A única guarda era ``nota_geral > 0`` — e três das cinco crianças
TRANSFERIDAS daquela escola tinham nota (60,68, 36,72 e 38,49), então o endpoint
emitiria um documento oficial, com brasão, em nome de quem já saiu.

O ranking, os relatórios e o próprio seletor da tela de Relatórios já filtram
``status == "ativo"``; só esta rota aceitava um id direto. É gap de endpoint, não
de interface — mas um documento oficial é justamente o lugar onde não se pode
depender de a tela ter filtrado antes.

A saída, quando a escola decidir que a criança deve receber mesmo assim, é
explícita e auditada: Alunos › Reativar, e emitir em seguida.
"""
from datetime import date

from app.models import Aluno, Matricula, Nota, Turma

API = "/api/v1"


def _com_nota(db, escola, turma, nome, status, *, geral=72.5):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, da_lista_piloto=True)
    a.data_nascimento = date(2017, 5, 5)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=turma.ano_letivo,
                nota_geral=geral, nota_elefante=geral, nota_matific=geral,
                aferido_leitura=True, aferido_matematica=True, posicao=1))
    db.commit()
    return a


def _turma(db, escola):
    return db.execute(
        Turma.__table__.select().where(Turma.escola_id == escola.id)
    ).first() and db.query(Turma).filter(Turma.escola_id == escola.id).first()


def test_aluno_ativo_com_desempenho_recebe_certificado(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "ANA ATIVA DA SILVA", "ativo")

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"


def test_transferido_nao_recebe_certificado(cliente, db, escola_completa):
    """O caso real: criança com nota, mas que saiu da escola."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "MYRELLA QUE SAIU", "transferido", geral=60.68)

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert r.status_code == 409, r.text
    assert "MYRELLA QUE SAIU" in r.text
    assert "transferido" in r.text
    assert "Reativar" in r.text, "a mensagem diz qual é o caminho"


def test_transferido_tambem_nao_recebe_o_modelo_de_plataforma(cliente, db,
                                                              escola_completa):
    """A arte do Elefante/Matific passa pelo MESMO endpoint — a guarda vale para
    os três botões da tela, não só para o certificado geral."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "YARA QUE SAIU", "transferido")

    for modelo in ("elefante", "matific"):
        r = cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo={modelo}")
        assert r.status_code == 409, (modelo, r.text)


def test_demais_situacoes_inativas_tambem_sao_recusadas(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    for i, status in enumerate(("fora_lista_piloto", "arquivado", "excluido")):
        a = _com_nota(db, escola, turma, f"CRIANCA INATIVA {i}", status)
        r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
        assert r.status_code == 409, (status, r.text)


def test_reativar_remove_o_bloqueio_de_populacao(cliente, db, escola_completa):
    """A saída documentada funciona: depois de reativar, a guarda de POPULAÇÃO
    sai do caminho.

    O 200 não vem neste cenário de teste, e não é defeito: "Reativar" recalcula a
    escola, e aqui a criança não tem snapshot real de plataforma nenhum — a nota
    sintética é recomputada para zero e a guarda de MÉRITO (``nota_geral > 0``,
    pré-existente) assume. Em produção, onde o aluno tem dados, o 200 vem. O que
    este teste trava é que o 409 de população deixa de aparecer."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "VOLTOU PARA A ESCOLA", "transferido")
    assert cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}").status_code == 409

    r = cliente.post(f"{API}/escolas/{escola.id}/alunos/acoes",
                     json={"aluno_ids": [a.id], "acao": "reativar"})
    assert r.status_code == 200, r.text

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert r.status_code != 409, "a guarda de população não pode mais barrar"
    assert r.status_code == 422, "sobra só a guarda de desempenho, que é a antiga"


def test_sem_nota_calculada_continua_recusando(cliente, db, escola_completa):
    """A guarda antiga não foi afrouxada: ativo mas com ``nota_geral <= 0`` segue
    sem certificado geral (um brasão afirmando 0,0 é constrangedor)."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "SEM DADO AINDA", "ativo", geral=0.0)
    db.execute(Nota.__table__.update().where(Nota.aluno_id == a.id)
               .values(aferido_leitura=False, aferido_matematica=False,
                       nota_geral=0.0, nota_elefante=0.0, nota_matific=0.0))
    db.commit()

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert r.status_code == 422, r.text


def test_a_populacao_do_certificado_e_a_do_ranking(cliente, db, escola_completa):
    """O invariante que importa na véspera: todo aluno que o ranking mostra
    consegue certificado, e nenhum que ele esconde consegue."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    ativos = [_com_nota(db, escola, turma, f"ATIVO {i}", "ativo") for i in range(3)]
    fora = [_com_nota(db, escola, turma, "SAIU DA ESCOLA", "transferido"),
            _com_nota(db, escola, turma, "ARQUIVADO AQUI", "arquivado")]

    r = cliente.get(f"{API}/escolas/{escola.id}/ranking")
    assert r.status_code == 200, r.text
    no_ranking = {x["aluno_id"] for x in r.json()}

    for a in ativos:
        assert a.id in no_ranking, f"{a.nome} deveria estar no ranking"
        assert cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}").status_code == 200
    for a in fora:
        assert a.id not in no_ranking, f"{a.nome} não deveria estar no ranking"
        assert cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}").status_code == 409


# ---------------------------------------------------------------------------
# A arte da plataforma: mesma guarda, e o bimestre deixa de ser o relógio
# ---------------------------------------------------------------------------

def test_arte_da_plataforma_nao_tem_guarda_de_merito_e_isso_e_deliberado(
        cliente, db, escola_completa):
    """Caracteriza o contrato que eu quase quebrei na véspera.

    A arte do Elefante/Matific não imprime nota nem posição — é documento de
    PARTICIPAÇÃO na plataforma, não de mérito. Por isso ela sai para quem ainda
    não tem nota calculada, enquanto o certificado geral (que imprime nota e
    posição) recusa o MESMO aluno com 422. ``test_certificado_plataforma`` já
    travava isso com um aluno sem nenhuma ``Nota``; aqui fica escrito POR QUE os
    dois documentos divergem de propósito, para o próximo que achar que é bug.

    O que vale para os três botões é a guarda de POPULAÇÃO (acima): aluno que não
    está ativo não recebe documento oficial nenhum."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "SEM NENHUM DADO", "ativo", geral=0.0)
    db.execute(Nota.__table__.update().where(Nota.aluno_id == a.id)
               .values(aferido_leitura=False, aferido_matematica=False,
                       nota_geral=0.0, nota_elefante=0.0, nota_matific=0.0))
    db.commit()

    assert cliente.get(
        f"{API}/escolas/{escola.id}/certificados/{a.id}").status_code == 422
    for modelo in ("elefante", "matific"):
        r = cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo={modelo}")
        assert r.status_code == 200, (modelo, r.status_code)


def test_bimestre_explicito_manda_no_que_e_impresso():
    """O defeito que a véspera da entrega revelou: o número vinha do MÊS DO
    RELÓGIO. Emitir em 30/09 imprimia 3; em 01/10, a MESMA criança com os MESMOS
    dados receberia 4. Agora quem emite fixa o número."""
    from app.services.relatorios import _certificado_plataforma_html

    html3 = _certificado_plataforma_html("EMEF X", "ANA", "elefante", bimestre=3)
    html4 = _certificado_plataforma_html("EMEF X", "ANA", "elefante", bimestre=4)
    assert '<div class="campo bimestre">3</div>' in html3
    assert '<div class="campo bimestre">4</div>' in html4


def test_sem_bimestre_o_padrao_continua_sendo_o_mes(monkeypatch):
    """O padrão NÃO mudou — é o que garante que nenhum certificado já combinado
    saia diferente. O que mudou é poder fixar o número."""
    from app.services import relatorios as svc

    assert svc._bimestre_por_mes(9) == 3, "setembro = 3º bimestre"
    assert svc._bimestre_por_mes(10) == 4, "outubro = 4º bimestre (a virada)"
    html = svc._certificado_plataforma_html("EMEF X", "ANA", "matific")
    esperado = svc._bimestre_por_mes(svc.agora_br().month)
    assert f'<div class="campo bimestre">{esperado}</div>' in html


def test_o_bimestre_chega_ao_pdf_pelo_endpoint(cliente, db, escola_completa):
    """O parâmetro atravessa rota → serviço → HTML. Sem isso o seletor da tela
    seria decorativo."""
    from unittest.mock import patch

    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "COM DADO PARA A ARTE", "ativo")

    with patch("app.services.relatorios.gerar_certificado_plataforma",
               return_value=b"%PDF-fake") as gerar:
        r = cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo=matific&bimestre=3")
        assert r.status_code == 200, r.text
        assert gerar.call_args.kwargs.get("bimestre") == 3


def test_bimestre_fora_da_faixa_e_recusado(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = _turma(db, escola)
    a = _com_nota(db, escola, turma, "FAIXA DO BIMESTRE", "ativo")
    for b in (0, 5, 99):
        r = cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo=elefante&bimestre={b}")
        assert r.status_code == 422, (b, r.status_code)
