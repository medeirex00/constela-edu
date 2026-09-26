"""Uma só semântica de RA, o cabeçalho real da rede, e a fusão manual com rede.

Três fragilidades descobertas na investigação da duplicidade da Alice Fossenati
(escola 17, set/2026), corrigidas juntas porque são a mesma família de problema:
o sistema tinha MAIS DE UMA definição do que é "o mesmo RA", lia mal o cabeçalho
do modelo oficial, e deixava a porta destrutiva sem a rede que a porta automática
tem.

1. ``alunos_dedup._conflito_forte`` comparava o RA CRU (só ``.strip()``), enquanto
   todo o resto do sistema compara por ``ra_util``. Resultado: duas fichas da
   mesma criança com o RA digitado "123.269.537-3" num lado e "1232695373" no
   outro eram declaradas "crianças provadamente diferentes" e a duplicata REAL
   ficava invisível na tela de fusão — o oposto do que o veto existe para fazer.

2. O cabeçalho ``DT. NASC.`` do modelo oficial da rede normaliza para "dt nasc",
   que não estava entre os sinônimos. A importação saía SEM nascimento para a
   escola inteira, em silêncio, perdendo o corroborador e o veto de identidade
   mais fortes do motor.

3. ``POST /alunos/fundir`` não consultava conflito de identidade nenhum, embora a
   fusão em LOTE recompute os candidatos e barre esses pares. E a tela mostra só
   nome e turma: quem digitava "FUNDIR" não via nascimento nem RA.

O que estes testes NÃO travam, de propósito: que um RA de 9 dígitos e um de 10
sejam a mesma pessoa. O décimo caractere é o dígito verificador do RA paulista,
mas nada no repositório diz isso, e transformar 9 em 10 sem prova juntaria
crianças. O estado "RA incompleto" continua distinto — e o teste 4 trava isso.
"""
import io
from datetime import date

import openpyxl
from sqlalchemy import select

from app.models import Aluno, Matricula, Turma
from app.services import matching
from app.services.alunos_dedup import _conflito_forte, plano_deduplicacao
from app.services.identidade_aluno import identidade_do_aluno, ra_forte
from app.services.lista_piloto import _COLUNAS, analisar_matriculas, ra_util

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ANO = 2026
CONFIRMA_CONFLITO = "FUNDIR MESMO COM CONFLITO"


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

def _ficha(nome, *, ra=None, nasc=None, chamada=None):
    a = Aluno(escola_id=1, nome=nome, numero_chamada=chamada,
              ficha={"ra": ra} if ra is not None else {})
    a.data_nascimento = nasc
    return a


def _planilha(rotulo_nasc, linhas, turma="3º Ano A"):
    """Uma aba, com o rótulo da coluna de nascimento sob teste."""
    colunas = ["N.º", "RM", "RA", "Nome", rotulo_nasc, "Responsável",
               "Endereço", "Bairro", "Telefone", "SEXO"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = turma[:31]
    ws.append([None, None, None, "PREFEITURA MUNICIPAL DE CARAGUATATUBA"])
    ws.append(["Escola:", None, "EMEF TESTE", None, None, None, None,
               "Lista Piloto:", ANO])
    ws.append([])
    ws.append(["Professor:", None, "PAULA", None, "Ano:", turma,
               "Turno:       TARDE", None, "N.º da Classe (SED):", 300396600])
    ws.append([])
    ws.append(colunas)
    for linha in linhas:
        ws.append(linha)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _linha(nome, *, numero=None, ra="", nasc=None):
    return [numero, "", ra, nome, nasc, "MAE", "RUA X, 1", "BAIRRO", "", "F"]


def _confirmar(cliente, escola_id, conteudo):
    r = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/matriculas/confirmar",
        files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def _aluno(db, escola_id, nome) -> Aluno:
    db.expire_all()
    return db.execute(select(Aluno).where(
        Aluno.escola_id == escola_id, Aluno.nome == nome)).scalar_one()


# ---------------------------------------------------------------------------
# 1–4. UMA SÓ SEMÂNTICA DE RA
# ---------------------------------------------------------------------------

def test_1_ra_pontuado_e_nao_pontuado_sao_o_mesmo():
    """A regra oficial ignora pontuação. Antes, o veto da deduplicação lia o
    texto cru e declarava 'crianças diferentes' para o MESMO RA."""
    assert ra_util("123.269.537-3") == ra_util("1232695373") == "1232695373"
    a = _ficha("MARIA SILVA", ra="123.269.537-3")
    b = _ficha("MARIA SILVA", ra="1232695373")
    assert _conflito_forte(a, b) is False
    assert matching.conflito_identidade(
        identidade_do_aluno(a), identidade_do_aluno(b)) is False


def test_2_ra_com_caixa_diferente_e_o_mesmo():
    """O verificador pode ser a letra X, e a planilha alterna maiúscula e
    minúscula. Caixa não é identidade."""
    assert ra_util("121.545.238-X") == ra_util("121545238x") == "121545238x"
    a, b = _ficha("JOAO LIMA", ra="121.545.238-X"), _ficha("JOAO LIMA", ra="121545238x")
    assert _conflito_forte(a, b) is False


def test_3_ra_realmente_diferente_continua_vetando():
    """O afrouxamento é só de FORMA. Dígitos diferentes seguem sendo prova."""
    a, b = _ficha("ANA COSTA", ra="123.111.111-1"), _ficha("ANA COSTA", ra="123.222.222-2")
    assert _conflito_forte(a, b) is True
    assert matching.conflito_identidade(
        identidade_do_aluno(a), identidade_do_aluno(b)) is True


def test_4_ra_incompleto_continua_sendo_estado_distinto():
    """9 dígitos × 10 dígitos: NÃO são unificados.

    O décimo caractere é o dígito verificador do RA paulista, mas nada no
    repositório declara isso, e truncá-lo juntaria identidades sem prova. Este
    é exatamente o caso da Alice (2285 × 2297) e ele DEVE continuar vetado."""
    assert ra_util("123269537") == "123269537"
    assert ra_util("123.269.537-3") == "1232695373"
    assert ra_util("123269537") != ra_util("123.269.537-3")
    a, b = _ficha("ALICE F", ra="123269537"), _ficha("ALICE F", ra="123.269.537-3")
    assert _conflito_forte(a, b) is True


def test_4b_placeholder_de_ra_nao_prova_nada():
    """'0', 'S/RA' e afins são preenchimento de secretaria, não identidade.
    ra_util os anula, então não podem vetar uma fusão legítima."""
    for p1, p2 in [("0", "00"), ("S/RA", "SRA"), ("N/A", "0")]:
        a, b = _ficha("LUCAS DIAS", ra=p1), _ficha("LUCAS DIAS", ra=p2)
        assert ra_util(p1) == ra_util(p2) == ""
        assert _conflito_forte(a, b) is False, (p1, p2)


def test_4c_a_deduplicacao_usa_a_mesma_regra_do_motor():
    """O objetivo da correção: não existir mais um cenário em que o motor de
    identidade diz 'mesmo RA' e a deduplicação diz 'RA diferente'."""
    casos = ["123.269.537-3", "1232695373", "123269537", "121.545.238-X",
             "121545238x", "0", "", "111.111.111-1"]
    for x in casos:
        for y in casos:
            a, b = _ficha("N N", ra=x), _ficha("N N", ra=y)
            dedup_veta_por_ra = bool(ra_util(x) and ra_util(y) and ra_util(x) != ra_util(y))
            assert _conflito_forte(a, b) is dedup_veta_por_ra, (x, y)
            ia, ib = identidade_do_aluno(a), identidade_do_aluno(b)
            assert matching.conflito_identidade(ia, ib) is dedup_veta_por_ra, (x, y)


# ---------------------------------------------------------------------------
# 5–6. O CABEÇALHO REAL DA REDE
# ---------------------------------------------------------------------------

def test_5_dt_nasc_do_modelo_oficial_e_reconhecido(cliente, db, escola_completa):
    """'DT. NASC.' é o rótulo do modelo oficial. Sem ele a escola inteira era
    importada sem nascimento, sem nenhum aviso."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("PEDRO ALVES ROCHA", numero=1, ra="111.100.001-0",
               nasc=date(2017, 5, 9)),
    ]))
    assert _aluno(db, escola_id, "PEDRO ALVES ROCHA").data_nascimento == date(2017, 5, 9)


def test_6_todos_os_rotulos_antigos_continuam_valendo(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    rotulos = ["Data de Nasc.", "Data de Nascimento", "Nascimento", "Data Nasc",
               "DT. NASC."]
    for i, rotulo in enumerate(rotulos):
        nome = f"CRIANCA NUMERO {i}"
        _confirmar(cliente, escola_id, _planilha(rotulo, [
            _linha(nome, numero=i + 1, ra=f"222.100.00{i}-0", nasc=date(2018, 3, i + 1)),
        ], turma=f"1º Ano {chr(65 + i)}"))
        assert _aluno(db, escola_id, nome).data_nascimento == date(2018, 3, i + 1), rotulo


def test_6b_o_alias_novo_nao_rouba_outra_coluna():
    """'dt nasc' não pode engolir um cabeçalho de outro campo."""
    assert "dt nasc" in _COLUNAS["nascimento"]
    outros = [s for campo, sins in _COLUNAS.items() if campo != "nascimento"
              for s in sins]
    assert not any("dt nasc" == s or "dt nasc".startswith(s + " ") for s in outros)


# ---------------------------------------------------------------------------
# 7–8. NASCIMENTO NÃO É SOBRESCRITO, MAS A DIVERGÊNCIA APARECE
# ---------------------------------------------------------------------------

def test_7_planilha_sem_data_nao_apaga_a_data_da_ficha(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("SOFIA MENDES LIMA", numero=1, ra="333.100.001-0", nasc=date(2017, 2, 2)),
    ]))
    _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("SOFIA MENDES LIMA", numero=1, ra="333.100.001-0"),   # sem data
    ]))
    assert _aluno(db, escola_id, "SOFIA MENDES LIMA").data_nascimento == date(2017, 2, 2)


def test_8_data_divergente_nao_sobrescreve_e_gera_aviso(cliente, db, escola_completa):
    """O caso da Alice: a MESMA criança com duas datas. O sistema não escolhe —
    preserva a que está na ficha e avisa, nominalmente."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("HELENA PIRES SOUZA", numero=1, ra="444.100.001-0", nasc=date(2020, 7, 31)),
    ]))
    corpo = _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("HELENA PIRES SOUZA", numero=1, ra="444.100.001-0", nasc=date(2020, 7, 21)),
    ]))

    assert _aluno(db, escola_id, "HELENA PIRES SOUZA").data_nascimento == date(2020, 7, 31)
    avisos = [a for a in corpo["avisos"] if "HELENA PIRES SOUZA" in a]
    assert len(avisos) == 1, corpo["avisos"]
    assert "2020-07-31" in avisos[0] and "2020-07-21" in avisos[0]


def test_8b_data_igual_nao_gera_ruido(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    planilha = _planilha("DT. NASC.", [
        _linha("IGOR NUNES PRADO", numero=1, ra="555.100.001-0", nasc=date(2017, 8, 8)),
    ])
    _confirmar(cliente, escola_id, planilha)
    corpo = _confirmar(cliente, escola_id, planilha)
    assert [a for a in corpo["avisos"] if "IGOR NUNES PRADO" in a] == []


# ---------------------------------------------------------------------------
# 13–14. Achados da conferência adversarial
# ---------------------------------------------------------------------------

def test_13_cabecalho_dt_nasc_sem_coluna_ra_e_reconhecido(cliente, db, escola_completa):
    """Regressão do defeito que o alias criou: ``_linha_cabecalho`` tinha a
    PRÓPRIA lista de rótulos de nascimento. Com 'DT. NASC.' mapeado em
    ``_COLUNAS`` mas ausente lá, uma planilha sem coluna de RA era recusada
    INTEIRA — e o aviso dizia, erradamente, que faltava a coluna 'Nome'."""
    escola_id = escola_completa["escola"].id
    colunas = ["N.º", "Nome", "DT. NASC."]     # sem RA de propósito
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "5º Ano A"
    ws.append([None, None, None, "PREFEITURA MUNICIPAL DE CARAGUATATUBA"])
    ws.append(["Escola:", None, "EMEF TESTE", None, None, None, None,
               "Lista Piloto:", ANO])
    ws.append([])
    ws.append(["Professor:", None, "PAULA", None, "Ano:", "5º Ano A",
               "Turno:       TARDE", None, "N.º da Classe (SED):", 300396699])
    ws.append([])
    ws.append(colunas)
    ws.append([1, "MARIA CLARA LOPES", date(2016, 4, 5)])
    buffer = io.BytesIO()
    wb.save(buffer)

    corpo = _confirmar(cliente, escola_id, buffer.getvalue())
    assert corpo["alunos_criados"] == 1, corpo
    assert _aluno(db, escola_id, "MARIA CLARA LOPES").data_nascimento == date(2016, 4, 5)


def test_13b_o_detector_de_cabecalho_usa_a_mesma_lista_do_mapeador():
    """Fonte única: qualquer sinônimo novo de nascimento vale nos dois lugares."""
    from app.services.lista_piloto import _linha_cabecalho, _rotulo
    for rotulo in _COLUNAS["nascimento"]:
        assert _linha_cabecalho([["Nome", rotulo]]) == 0, rotulo
    # e o rótulo real, com pontuação, continua casando
    assert _linha_cabecalho([["Nome", "DT. NASC."]]) == 0
    assert _rotulo("DT. NASC.") in _COLUNAS["nascimento"]


def test_14_divergencia_de_nascimento_fica_no_log(cliente, db, escola_completa):
    """O aviso vive só na resposta da importação. Fechada a tela, o log é o
    que sobra para alguém conferir a divergência depois."""
    from app.models import LogAuditoria
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("BRUNA CAMPOS REIS", numero=1, ra="666.100.001-0", nasc=date(2019, 1, 10)),
    ]))
    _confirmar(cliente, escola_id, _planilha("DT. NASC.", [
        _linha("BRUNA CAMPOS REIS", numero=1, ra="666.100.001-0", nasc=date(2019, 10, 1)),
    ]))

    db.expire_all()
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.nascimento_divergente")).scalars().all()
    assert len(logs) == 1, [l.acao for l in logs]
    assert logs[0].detalhes["na_ficha"] == "2019-01-10"
    assert logs[0].detalhes["na_planilha"] == "2019-10-01"
    assert _aluno(db, escola_id, "BRUNA CAMPOS REIS").data_nascimento == date(2019, 1, 10)


def test_12b_o_parser_nao_inventa_data_para_a_alice():
    """A planilha oficial traz DUAS datas para a mesma criança. O importador lê
    as duas como estão; escolher é decisão humana, e o teste 8 garante o aviso."""
    conteudo = _planilha("DT. NASC.", [
        _linha("ALICE VITORIA FOSSENATI DE JESUS", numero=2, ra="123.269.537-3",
               nasc=date(2020, 7, 31)),
    ], turma="1ª Fase")
    an = analisar_matriculas(conteudo, "L.xlsx")
    alunos = [a for t in an.turmas for a in t.alunos]
    assert len(alunos) == 1
    assert alunos[0].data_nascimento == "2020-07-31"
    assert alunos[0].ficha["ra"] == "123.269.537-3"
