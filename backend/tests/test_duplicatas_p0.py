"""P0 — o sistema NÃO pode abrir uma segunda ficha para quem já existe.

Duas causas raiz fechadas aqui:

1. **REVISAR significa REVISAR.** O import só mandava para revisão quando havia
   2+ candidatos; um REVISAR de candidato ÚNICO (nome parcial/subconjunto) virava
   "baixa" e criava a ficha, contando com a fusão manual depois. Agora qualquer
   REVISAR bloqueia a criação.

2. **"Fora da lista" ≠ "não existe".** O roster de matching filtrava
   ``status == "ativo"``, então quem caísse da Lista Piloto (o que acontece
   sozinho a cada confirmação) sumia do matching e a importação seguinte da
   plataforma abria uma segunda ficha.

Homônimos reais continuam permitidos: a correção é contra duplicata da MESMA
pessoa, não contra duas pessoas de mesmo nome.
"""
import pytest

from app.models import Aluno, Matricula, Turma
from app.routers import importacoes as imp
from app.services import matching


@pytest.fixture()
def turma_com(db, escola_completa):
    """Fábrica: cria a turma e os alunos pedidos, devolvendo (escola, turma)."""
    escola = escola_completa["escola"]
    turma = Turma(escola_id=escola.id, nome="5ºB", ano_escolar="5º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()

    def criar(nome: str, status: str = "ativo", **campos) -> Aluno:
        a = Aluno(escola_id=escola.id, nome=nome, status=status, **campos)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.commit()
        return a

    return escola, turma, criar


def _casar(db, escola, turma, nome, **kw):
    return imp._casar_no_roster(db, escola.id, 2026, nome, turma, **kw)


def _total(db, escola):
    return db.query(Aluno).filter(Aluno.escola_id == escola.id).count()


# --- Causa 1: REVISAR de candidato ÚNICO não pode criar ---------------------

def test_1_revisar_com_um_candidato_nao_cria(db, turma_com):
    """O caso que gerava a fila de fusão manual: nome PARCIAL, 1 candidato só."""
    escola, turma, criar = turma_com
    criar("AGATHA EMANUELE DA SILVA OLIVEIRA")

    linha = matching.Identidade(nome="AGATHA EMANUELE OLIVEIRA")
    roster, _ = imp._roster_identidades(db, escola.id, 2026, turma.id)
    res = matching.classificar_linha(linha, roster)
    assert res.status == matching.REVISAR and len(res.candidatos) == 1, (
        "o cenário precisa ser REVISAR com UM candidato para o teste valer")

    aluno, confianca = _casar(db, escola, turma, "AGATHA EMANUELE OLIVEIRA")
    assert confianca == "media", "REVISAR de 1 candidato tem de ir para revisão"
    assert aluno is None


def test_2_revisar_com_dois_candidatos_nao_cria(db, turma_com):
    escola, turma, criar = turma_com
    criar("MARIA EDUARDA SILVA SANTOS")
    criar("MARIA EDUARDA SILVA COSTA")

    aluno, confianca = _casar(db, escola, turma, "MARIA EDUARDA SILVA")
    assert confianca == "media" and aluno is None


def test_3_nenhum_candidato_cria(db, turma_com):
    """A correção não pode travar o caso legítimo: ninguém parecido → cria."""
    escola, turma, criar = turma_com
    criar("MARIA EDUARDA SILVA")

    aluno, confianca = _casar(db, escola, turma, "RODRIGO ALVES PEREIRA")
    assert confianca == "baixa" and aluno is None  # baixa = pode criar


def test_4_correspondencia_exata_reutiliza(db, turma_com):
    escola, turma, criar = turma_com
    existente = criar("MARIA EDUARDA SILVA")

    aluno, confianca = _casar(db, escola, turma, "MARIA EDUARDA SILVA")
    assert confianca == "alta" and aluno is not None and aluno.id == existente.id


@pytest.mark.parametrize("variacao", [
    "maria eduarda silva",          # caixa
    "MARIA  EDUARDA   SILVA",       # espaços extras
    "  MARIA EDUARDA SILVA  ",      # espaços nas bordas
])
def test_5_correspondencia_normalizada_reutiliza(db, turma_com, variacao):
    escola, turma, criar = turma_com
    existente = criar("MARIA EDUARDA SILVA")

    aluno, confianca = _casar(db, escola, turma, variacao)
    assert confianca == "alta" and aluno is not None and aluno.id == existente.id


def test_5b_acentuacao_diferente_reutiliza(db, turma_com):
    escola, turma, criar = turma_com
    existente = criar("JOÃO PEDRO DA SILVA")

    aluno, confianca = _casar(db, escola, turma, "JOAO PEDRO DA SILVA")
    assert confianca == "alta" and aluno is not None and aluno.id == existente.id


def test_6_homonimos_reais_vao_para_revisao(db, turma_com):
    """Dois JOÃO SILVA na mesma turma são duas pessoas. O sistema NÃO pode
    escolher um deles às cegas — nem criar um terceiro."""
    escola, turma, criar = turma_com
    criar("JOÃO SILVA", numero_chamada=1)
    criar("JOÃO SILVA", numero_chamada=2)

    aluno, confianca = _casar(db, escola, turma, "JOÃO SILVA")
    assert confianca == "media" and aluno is None


def test_13_pessoas_diferentes_nao_sao_fundidas(db, turma_com):
    """A correção não pode virar fusão indevida: nomes parecidos de pessoas
    diferentes continuam sendo pessoas diferentes."""
    escola, turma, criar = turma_com
    criar("BRUNO SOUZA LIMA")

    aluno, confianca = _casar(db, escola, turma, "BRUNA SOUZA LIMA")
    assert aluno is None, "BRUNO e BRUNA não podem ser vinculados"
    assert confianca in ("baixa", "media")


# --- Causa 2: fora_lista_piloto / arquivado continuam sendo identidade ------

@pytest.mark.parametrize("status", ["fora_lista_piloto", "arquivado", "transferido"])
def test_7_aluno_fora_da_lista_nao_gera_duplicata(db, turma_com, status):
    """Exatamente o caso reproduzido na investigação: o aluno cai da Lista Piloto
    e a importação seguinte da plataforma abria uma 2ª ficha."""
    escola, turma, criar = turma_com
    existente = criar("ABRAÃO LUÍS DIAS", status=status)
    antes = _total(db, escola)

    # nome com pequena variação, como chega do Elefante
    aluno, confianca = _casar(db, escola, turma, "ABRAAO LUIZ DIAS")
    assert confianca in ("alta", "media"), (
        f"aluno com status={status} sumiu do roster e viraria duplicata")
    if confianca == "alta":
        assert aluno.id == existente.id
    assert _total(db, escola) == antes


def test_7b_resolver_identidade_nao_reativa_o_aluno(db, turma_com):
    """Identidade e matrícula são coisas separadas: reconhecer quem é NÃO pode
    reativar quem foi arquivado."""
    escola, turma, criar = turma_com
    existente = criar("ABRAÃO LUÍS DIAS", status="fora_lista_piloto")

    _casar(db, escola, turma, "ABRAÃO LUÍS DIAS")
    db.refresh(existente)
    assert existente.status == "fora_lista_piloto"


def test_7c_aluno_excluido_nao_e_candidato(db, turma_com):
    """O único status que continua fora da resolução: excluído de verdade."""
    escola, turma, criar = turma_com
    criar("CARLOS EDUARDO NUNES", status="excluido")

    roster, _ = imp._roster_identidades(db, escola.id, 2026, turma.id)
    assert roster == []


# --- CRUD manual: a última porta que criava sem perguntar -------------------

def test_11_crud_manual_recusa_aluno_ja_cadastrado(cliente, db, escola_completa):
    """O cadastro manual passou a usar a MESMA resolução de identidade."""
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    ja = escola_completa["alunos"][0]          # "Ana Beatriz Souza"
    antes = db.query(Aluno).filter(Aluno.escola_id == escola.id).count()

    r = cliente.post(f"/api/v1/escolas/{escola.id}/alunos",
                     json={"nome": ja.nome, "turma_id": turma.id})
    assert r.status_code == 409 and "já está cadastrado" in r.json()["detail"]
    assert db.query(Aluno).filter(Aluno.escola_id == escola.id).count() == antes


def test_11b_crud_manual_recusa_variacao_insegura(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    antes = db.query(Aluno).filter(Aluno.escola_id == escola.id).count()

    r = cliente.post(f"/api/v1/escolas/{escola.id}/alunos",
                     json={"nome": "Ana Beatriz", "turma_id": turma.id})
    assert r.status_code == 409
    assert db.query(Aluno).filter(Aluno.escola_id == escola.id).count() == antes


def test_11c_crud_manual_cria_aluno_realmente_novo(cliente, db, escola_completa):
    """A trava não pode impedir o cadastro legítimo."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/alunos",
                     json={"nome": "Rodrigo Alves Pereira", "turma_id": turma.id})
    assert r.status_code == 201


def test_11d_crud_manual_permite_homonimo_real_com_identidade_distinta(
        cliente, db, escola_completa):
    """Homônimo REAL continua cadastrável: nº de chamada distinto prova que é
    outra criança e o veto de identidade libera a criação."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ja = escola_completa["alunos"][0]
    ja.numero_chamada = 1
    db.commit()

    r = cliente.post(f"/api/v1/escolas/{escola.id}/alunos",
                     json={"nome": ja.nome, "turma_id": turma.id, "numero_chamada": 27})
    assert r.status_code == 201, r.text
    iguais = db.query(Aluno).filter(Aluno.escola_id == escola.id,
                                    Aluno.nome == ja.nome).count()
    assert iguais == 2, "dois homônimos reais são legítimos"


# --- Repetição, cross-source e convergência --------------------------------

def test_8_mesma_resolucao_cinco_vezes_nao_multiplica(db, turma_com):
    """Idempotência: a MESMA linha resolvida 5× sempre cai no mesmo aluno."""
    escola, turma, criar = turma_com
    existente = criar("MARIA EDUARDA SILVA")
    antes = _total(db, escola)

    for _ in range(5):
        aluno, confianca = _casar(db, escola, turma, "maria  eduarda   silva")
        assert confianca == "alta" and aluno.id == existente.id
    assert _total(db, escola) == antes


def test_9_cross_source_converge_para_um_aluno(db, turma_com):
    """Lista Piloto → Elefante → Matific → Elefante de novo: cada fonte escreve o
    nome do seu jeito e todas têm de cair na MESMA criança."""
    escola, turma, criar = turma_com
    piloto = criar("JOÃO PEDRO DA SILVA", da_lista_piloto=True)
    antes = _total(db, escola)

    for origem in ["JOAO PEDRO DA SILVA",        # Elefante (sem acento)
                   "João Pedro da Silva",        # Matific (caixa mista)
                   "JOÃO  PEDRO  DA  SILVA"]:    # Elefante de novo
        aluno, confianca = _casar(db, escola, turma, origem)
        assert confianca == "alta", f"“{origem}” não casou"
        assert aluno.id == piloto.id
    assert _total(db, escola) == antes


def test_12_identificador_externo_e_unico_por_escola_e_plataforma(db, turma_com):
    """O ID externo é identidade FORTE garantida pelo banco: o mesmo UUID não
    pode apontar para dois alunos."""
    from sqlalchemy.exc import IntegrityError

    from app.models import IdentidadeExterna
    escola, _turma, criar = turma_com
    a = criar("ALICE MARTINS")
    b = criar("BEATRIZ ROCHA")
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=a.id,
                             plataforma="matific", id_externo="uuid-123"))
    db.commit()

    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=b.id,
                             plataforma="matific", id_externo="uuid-123"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_10_resolucoes_intercaladas_convergem(db, turma_com):
    """Serialização: é o que a trava por escola garante em produção (Postgres,
    pg_advisory_xact_lock). Resolvida a 1ª, a 2ª JÁ enxerga o aluno e casa."""
    escola, turma, _criar = turma_com
    antes = _total(db, escola)

    # 1ª "requisição": ninguém plausível → cria.
    aluno, confianca = _casar(db, escola, turma, "TEREZA CRISTINA MOURA")
    assert confianca == "baixa" and aluno is None
    novo = Aluno(escola_id=escola.id, nome="TEREZA CRISTINA MOURA", status="ativo")
    db.add(novo)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=novo.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()

    # 2ª "requisição", agora serializada atrás da 1ª: tem de CASAR, não duplicar.
    aluno2, confianca2 = _casar(db, escola, turma, "TEREZA CRISTINA MOURA")
    assert confianca2 == "alta" and aluno2.id == novo.id
    assert _total(db, escola) == antes + 1
