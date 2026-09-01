"""Bug de dados em produção: aluno com atividade REAL numa plataforma aparece com a
dimensão em 0,0 no ranking (HELOISA: Matific 0 / Leitura 99,94; TAUFIK: Matific 96,61 /
Leitura 0).

CAUSA RAIZ (provada com o código real): o nome do export da plataforma é um SUBCONJUNTO
do nome da Lista Piloto — "HELOISA FIDELIX" ⊂ "HELOISA DE SOUZA FIDELIX". Com 1 ÚNICO
candidato na turma, o subconjunto ia a REVISAR (guard-rail antigo "dono ausente") →
``_resolver_aluno`` devolvia ``None`` → o laço de import descartava a linha → NENHUM
SnapshotMatific/SnapshotElefante era criado → a dimensão ficava 0 no ranking.

CORREÇÃO CIRÚRGICA (só no pipeline de dados; NÃO toca fórmula/pesos/A3/P90/ranking):
o export de PLATAFORMA só contém alunos MATRICULADOS, então casar é ATRIBUIR a linha ao
seu dono no roster, não criar identidade. Logo, com 1 único candidato PARCIAL na turma,
``classificar_linha(..., permitir_subconjunto_unico=True)`` VINCULA. A segurança do
matching fica INTACTA: 2+ candidatos e variação de grafia insegura (SOUZA/SOUSA,
BRUNO/BRUNA) continuam em REVISAR — nunca funde crianças diferentes.

Três semânticas do zero, todas cobertas aqui:
  1) tem atividade mas não foi importada  → 0 é BUG  (corrigido: testes 1/3/7);
  2) tem só uma plataforma, a outra AUSENTE → 0 é LEGÍTIMO (teste 6/8);
  3) não deveria estar na plataforma      → sem snapshot, 0 (teste 6).
"""
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import (
    Aluno, Escola, IdentidadeExterna, Matricula, Nota, SnapshotElefante,
    SnapshotMatific, Turma, Usuario,
)
from app.routers.importacoes import _resolver_aluno, confirmar
from app.schemas import ImportacaoConfirm, LinhaConfirmacao
from app.services import provisionamento, scoring


# ---------------------------------------------------------------------------
# Helpers — mesmo padrão de test_import_casamento_roster.py
# ---------------------------------------------------------------------------
def _linha(nome, turma_nome, dados=None):
    return SimpleNamespace(nome=nome, aluno_id=None, criar_em_turma_id=None,
                           criar_em_turma_nome=turma_nome, numero_chamada=None,
                           dados=dados or {})


def _conta_alunos(db, escola_id):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == escola_id)).scalar_one()


def _cenario(db, extras=()):
    """Escola com a turma '5º Ano B' e a HELOISA da Lista Piloto (nome completo).
    ``extras`` matricula homônimos adicionais para os testes de ambiguidade."""
    esc = Escola(nome="EMEF Piloto", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    adm = Usuario(escola_id=esc.id, nome="Admin", email="a@a.local",
                  senha_hash=hash_senha("x"), cargo="admin")
    db.add(adm)
    provisionamento.semear_config_inicial(db, esc.id)
    turma = Turma(escola_id=esc.id, nome="5º Ano B", ano_escolar="5º Ano",
                  ano_letivo=2026, turno="manha", status="ativa")
    db.add(turma)
    db.flush()

    def matricular(nome):
        a = Aluno(escola_id=esc.id, nome=nome, status="ativo", da_lista_piloto=True)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        return a

    heloisa = matricular("HELOISA DE SOUZA FIDELIX")
    for nome in extras:
        matricular(nome)
    db.commit()
    return esc, turma, heloisa, adm


# ---------------------------------------------------------------------------
# 1) O CASO HELOISA — subconjunto de nome, 1 candidato → o dado CHEGA
# ---------------------------------------------------------------------------
def test_heloisa_subconjunto_unico_vincula_e_nao_descarta(db):
    esc, turma, heloisa, _ = _cenario(db)
    antes = _conta_alunos(db, esc.id)

    # Matific manda "HELOISA FIDELIX" (larga "DE SOUZA") → ANTES ia a revisão e o
    # dado sumia; AGORA vincula ao único candidato da turma.
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("HELOISA FIDELIX", "5 ANO B",
                               dados={"matific_uuid": "u-heloisa"}),
                        [], {}, {})
    assert r is not None and r.id == heloisa.id       # ATRIBUÍDO ao dono
    assert _conta_alunos(db, esc.id) == antes          # não criou duplicata


def test_heloisa_vincula_uuid_para_convergir(db):
    """Ao casar o subconjunto, o UUID do Matific é VINCULADO → a próxima sync casa
    direto por UUID (convergência), sem redepender do nome parcial."""
    esc, turma, heloisa, _ = _cenario(db)
    _resolver_aluno(db, esc.id, 2026,
                    _linha("HELOISA FIDELIX", "5 ANO B",
                           dados={"matific_uuid": "u-heloisa"}), [], {}, {})
    db.flush()
    vinc = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == esc.id,
        IdentidadeExterna.plataforma == "matific",
        IdentidadeExterna.id_externo == "u-heloisa")).scalars().first()
    assert vinc is not None and vinc.aluno_id == heloisa.id


# ---------------------------------------------------------------------------
# 3) REVERSO (TAUFIK): a mesma correção vale para a LEITURA (Elefante, sem UUID)
# ---------------------------------------------------------------------------
def test_reverso_elefante_subconjunto_unico_vincula(db):
    esc, turma, heloisa, _ = _cenario(db)
    antes = _conta_alunos(db, esc.id)
    # Elefante manda o subconjunto (sem UUID de plataforma) → vincula ao único dono.
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("HELOISA FIDELIX", "5 ANO B"), [], {}, {})
    assert r is not None and r.id == heloisa.id
    assert _conta_alunos(db, esc.id) == antes


# ---------------------------------------------------------------------------
# 5) SEGURANÇA: um aluno de uma plataforma NÃO é atribuído à criança errada
# ---------------------------------------------------------------------------
def test_subconjunto_com_dois_candidatos_nao_funde(db):
    """DOIS 'HELOISA … FIDELIX' na turma → o subconjunto "HELOISA FIDELIX" é AMBÍGUO
    → NÃO atribui às cegas (vai a revisão). O guard-rail 'nunca fundir crianças
    diferentes' continua valendo — a correção só age com candidato ÚNICO."""
    esc, turma, heloisa, _ = _cenario(db, extras=("HELOISA CRISTINA FIDELIX",))
    antes = _conta_alunos(db, esc.id)
    avisos: list[str] = []
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("HELOISA FIDELIX", "5 ANO B",
                               dados={"matific_uuid": "u-x"}), avisos, {}, {})
    assert r is None                                   # não atribui nem cria
    assert _conta_alunos(db, esc.id) == antes
    assert avisos                                      # sinaliza revisão


def test_variacao_de_sobrenome_unico_continua_em_revisao(db):
    """Guard-rail preservado: variação de grafia no SOBRENOME (FIDELIX/FIDELIS) com 1
    candidato NÃO é subconjunto → continua em REVISAR (pode ser outra criança). A
    correção do subconjunto NÃO afrouxa isto."""
    esc, turma, heloisa, _ = _cenario(db)
    antes = _conta_alunos(db, esc.id)
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("HELOISA DE SOUZA FIDELIS", "5 ANO B"), [], {}, {})
    assert r is None                                   # segue para o gestor decidir
    assert _conta_alunos(db, esc.id) == antes


def test_aluno_de_fora_do_roster_nao_rouba_candidato_existente(db):
    """Um nome que NÃO subconjunta ninguém não é colado no aluno existente — vira novo
    (ou revisão), nunca 'rouba' a HELOISA."""
    esc, turma, heloisa, _ = _cenario(db)
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("MARIANA COSTA LIMA", "5 ANO B"), [], {}, {})
    assert r is not None and r.id != heloisa.id and r.nome == "MARIANA COSTA LIMA"


# ---------------------------------------------------------------------------
# FRONTEIRA DE SEGURANÇA: o opt-in é EXCLUSIVO do import de plataforma
# ---------------------------------------------------------------------------
def test_classificar_linha_subconjunto_so_vincula_com_opt_in_de_plataforma():
    """O MESMO subconjunto único: REVISAR por padrão (criação de roster/Lista Piloto,
    conservador) e só VINCULADO com o opt-in de plataforma. E com 2+ candidatos NEM o
    opt-in vincula — o guard-rail 'nunca fundir crianças diferentes' fica intacto."""
    from app.services import matching
    linha = matching.Identidade(nome="HELOISA FIDELIX")
    roster = [matching.Identidade(id=1, nome="HELOISA DE SOUZA FIDELIX")]
    # padrão (Lista Piloto): subconjunto NÃO auto-vincula
    assert matching.classificar_linha(linha, roster).status == matching.REVISAR
    # opt-in (plataforma): candidato único subconjunto vincula
    r = matching.classificar_linha(linha, roster, permitir_subconjunto_unico=True)
    assert r.status == matching.VINCULADO and r.aluno_id == 1
    # 2+ candidatos: nem com o opt-in (ambiguidade continua em revisão)
    roster2 = roster + [matching.Identidade(id=2, nome="HELOISA CRISTINA FIDELIX")]
    assert matching.classificar_linha(
        linha, roster2, permitir_subconjunto_unico=True).status == matching.REVISAR


def test_subconjunto_vinculado_fica_auditado_como_parcial(db):
    """Todo vínculo por subconjunto entra no log (`aluno.vinculado_auto`) com
    correspondencia='parcial' — é a LISTA que o dono valida/reverte
    (scripts/diagnostico_dimensao_zero.py --subconjunto)."""
    from app.models import LogAuditoria
    esc, turma, heloisa, _ = _cenario(db)
    _resolver_aluno(db, esc.id, 2026,
                    _linha("HELOISA FIDELIX", "5 ANO B",
                           dados={"matific_uuid": "u-heloisa"}), [], {}, {})
    db.flush()
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.vinculado_auto",
        LogAuditoria.entidade_id == heloisa.id)).scalars().first()
    assert log is not None and log.detalhes.get("correspondencia") == "parcial"


# ---------------------------------------------------------------------------
# PREVIEW == CONFIRMAÇÃO (requisito do dono): mesmo roster nos dois lados
# ---------------------------------------------------------------------------
def test_preview_igual_confirmacao_com_homonimo_arquivado(db):
    """A prévia e a confirmação têm de dar o MESMO resultado. Um homônimo/parcial
    ARQUIVADO na turma entra no roster do confirmar (`status != "excluido"`); antes a
    prévia filtrava só `ativo` e NÃO o via → prévia via 1 candidato ("vinculado",
    pré-selecionado) e o confirmar via 2 (revisão). Agora os dois montam o MESMO roster
    (mesmo filtro + mesma Identidade) → AMBOS vão a REVISÃO. Trava o requisito 4."""
    from app.models import Matricula as _Matricula
    from app.services.importacao import LinhaImportacao, _prever_pelo_motor
    esc, turma, heloisa, _ = _cenario(db)                 # HELOISA DE SOUZA FIDELIX (ativo)
    arq = Aluno(escola_id=esc.id, nome="HELOISA FIDELIX SANTOS", status="arquivado")
    db.add(arq)
    db.flush()
    db.add(_Matricula(escola_id=esc.id, aluno_id=arq.id, turma_id=turma.id, ano_letivo=2026))
    db.commit()

    # "HELOISA FIDELIX" é subconjunto dos DOIS → 2 candidatos no roster completo.
    # CONFIRMAÇÃO: não vincula (revisão).
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("HELOISA FIDELIX", "5 ANO B",
                               dados={"matific_uuid": "u-x"}), [], {}, {})
    assert r is None
    # PRÉVIA: a mesma linha → "revisar" (o roster da prévia agora inclui o arquivado),
    # NUNCA "vinculado" pré-selecionado só na prévia.
    linha = LinhaImportacao(numero=1, nome="HELOISA FIDELIX",
                            dados={"turma_relatorio": "5 ANO B"},
                            correspondencia={"status": "nao_encontrado"})
    _prever_pelo_motor(db, esc.id, [linha])
    assert linha.correspondencia["status"] == "revisar"


# ---------------------------------------------------------------------------
# 4 + 2/8) O ZERO LEGÍTIMO: ausência real permanece 0, sem fabricar valor
# ---------------------------------------------------------------------------
def _importar_matific(db, esc, adm, nome, dados):
    dados_conf = ImportacaoConfirm(
        plataforma="matific", formato="resumo", tipo="xlsx",
        linhas=[LinhaConfirmacao(nome=nome, dados=dados, aluno_id=None,
                                 criar_em_turma_nome="5º Ano B")],
        recalcular=True)
    confirmar(dados_conf, escola_id=esc.id, usuario=adm, db=db)


def test_ausencia_real_permanece_zero_sem_fabricar(db):
    """Aluno que NÃO está em nenhum export → sem snapshot → nota 0 nas duas dimensões.
    A correção não inventa dado para quem não tem atividade."""
    esc, turma, heloisa, adm = _cenario(db)
    # ninguém importado: recalcula do zero

    scoring.recalcular_escola(db, esc.id)
    db.commit()
    nota = db.execute(select(Nota).where(Nota.aluno_id == heloisa.id)).scalars().first()
    # sem snapshot → não aferido → 0 legítimo (não é bug, não vira erro)
    assert (nota is None) or (
        nota.nota_matific == 0 and nota.nota_elefante == 0
        and not nota.aferido_matematica and not nota.aferido_leitura)


def test_uma_dimensao_presente_outra_ausente_zero_legitimo(db):
    """HELOISA com Matific presente e Leitura AUSENTE: Matific aferido (>0 possível),
    Leitura NÃO aferida (0 legítimo, `—` na tela) — exatamente o retrato do bug
    invertido, mas agora com o Matific chegando pelo subconjunto."""
    esc, turma, heloisa, adm = _cenario(db)
    _importar_matific(db, esc, adm, "HELOISA FIDELIX",
                      {"atividades": 50, "estrelas": 30, "pontuacao_media": 80.0,
                       "matific_uuid": "u-heloisa", "turma_relatorio": "5 ANO B"})
    db.commit()
    # snapshot de Matific existe para a HELOISA (dado chegou); Elefante não existe
    smat = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == heloisa.id)).scalars().first()
    self_ele = db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == heloisa.id)).scalars().first()
    assert smat is not None                            # Matific chegou
    assert self_ele is None                            # Leitura genuinamente ausente
    nota = db.execute(select(Nota).where(Nota.aluno_id == heloisa.id)).scalars().first()
    assert nota is not None and nota.aferido_matematica is True
    assert nota.aferido_leitura is False               # 0 de leitura é LEGÍTIMO aqui


# ---------------------------------------------------------------------------
# 6) REGRESSÃO PONTA A PONTA: nota_matific vai de 0 (descartado) → valor real
# ---------------------------------------------------------------------------
def test_pipeline_ponta_a_ponta_nota_matific_de_zero_para_valor(db):
    """O antes/depois do bug: sem o import a HELOISA tem Matific 0; ao importar o
    export de Matific com o nome SUBCONJUNTO, o snapshot é criado, o recálculo roda e
    a nota de Matific passa a refletir a atividade real (>0). Nada de leitura é tocado
    (continua ausente/0), provando que só o pipeline de dados mudou."""
    esc, turma, heloisa, adm = _cenario(db)

    # ANTES: nenhum snapshot → Matific 0

    scoring.recalcular_escola(db, esc.id)
    db.commit()
    nota0 = db.execute(select(Nota).where(Nota.aluno_id == heloisa.id)).scalars().first()
    assert nota0 is None or nota0.nota_matific == 0

    # DEPOIS: importa Matific com o nome subconjunto → snapshot criado + recálculo
    _importar_matific(db, esc, adm, "HELOISA FIDELIX",
                      {"atividades": 50, "estrelas": 30, "pontuacao_media": 80.0,
                       "matific_uuid": "u-heloisa", "turma_relatorio": "5 ANO B"})
    db.commit()

    snap = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == heloisa.id)).scalars().first()
    assert snap is not None                            # o dado chegou ao snapshot
    nota1 = db.execute(select(Nota).where(Nota.aluno_id == heloisa.id)).scalars().first()
    assert nota1 is not None and nota1.nota_matific > 0   # 0 → valor real
    assert nota1.aferido_matematica is True
