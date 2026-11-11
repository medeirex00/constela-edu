"""A prévia da Lista Piloto SÓ LÊ — e continua dando os números da confirmação.

REV-IMP-2 (sobre IMPORTACAO-10): para a prévia (``/matriculas/analisar``) contar
"novos × a atualizar × em revisão" como a confirmação, ``_simular_lista_piloto``
rodava a confirmação DE VERDADE dentro de um SAVEPOINT e a desfazia: INSERT de
turmas, INSERT/UPDATE de fichas e matrículas e a auditoria, uma ou mais idas ao
banco por criança (300 crianças ≈ 300 escritas), consumo das sequências e travas
de linha e do índice único de turmas — a prévia esperava quem estivesse gravando a
mesma turma e a confirmação esperava a prévia.

Agora a prévia passa pelas MESMAS decisões (``_resolver_turmas`` e
``_persistir_linhas`` com ``simular=True``: ``matriculas.resolver_linha``, as
disputas do lote, a linha seguinte vendo as anteriores) sobre fichas e turmas FORA
da sessão — nenhum comando de escrita, e o número de consultas não cresce com o
tamanho da lista. Dados fictícios.
"""
from datetime import date

import pytest
from sqlalchemy import event

from app.models import Aluno, IdentidadeExterna, Matricula, Turma
from tests.test_aud_imp_lista_piloto_previa import _contagens, _post
from tests.test_lista_piloto_identidade import _aluno, _planilha

ESCRITAS = ("INSERT", "UPDATE", "DELETE", "SAVEPOINT", "RELEASE", "ROLLBACK")


class _Comandos:
    """Os comandos SQL que o motor manda ao banco enquanto o bloco roda."""

    def __init__(self, engine):
        self.engine, self.lista = engine, []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._antes)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._antes)

    def _antes(self, _conn, _cursor, comando, *_args):
        self.lista.append(" ".join(comando.split()).split(" ", 1)[0].upper())

    @property
    def escritas(self) -> list[str]:
        return [c for c in self.lista if c in ESCRITAS]


def _lista(n_turmas: int, por_turma: int, prefixo: str = "CRIANCA FICTICIA") -> bytes:
    letras = "HIJKLMNOPQ"
    return _planilha(*(
        (f"{1 + t % 5}º ANO {letras[t // 5]}",
         [_aluno(f"{prefixo} T{t:02d} N{k:02d} DE TESTE", numero=k + 1,
                 ra=f"{900000000 + 1000 * t + k}-0", nasc=date(2018, 1, 1 + k % 28))
          for k in range(por_turma)])
        for t in range(n_turmas)))


def _previa_medida(cliente, db, eid, conteudo):
    with _Comandos(db.get_bind()) as comandos:
        previa = _post(cliente, eid, "analisar", conteudo)
    return previa, comandos


def test_previa_de_300_criancas_nao_escreve_e_consulta_o_mesmo_que_a_de_5(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    antes = _contagens(db, eid)
    pequena, c_pequena = _previa_medida(cliente, db, eid, _lista(1, 5))
    grande, c_grande = _previa_medida(cliente, db, eid, _lista(10, 30))
    assert (pequena["alunos_novos"], grande["alunos_novos"]) == (5, 300)
    assert c_grande.escritas == [], (
        f"a prévia de 300 crianças mandou {len(c_grande.escritas)} comando(s) de "
        f"escrita ({sorted(set(c_grande.escritas))}) em {len(c_grande.lista)} comandos")
    assert c_pequena.escritas == []
    assert len(c_grande.lista) == len(c_pequena.lista), (
        f"5 crianças: {len(c_pequena.lista)} comandos; 300: {len(c_grande.lista)}")
    assert _contagens(db, eid) == antes

    # Reenvio (as 300 já cadastradas): continua só lendo, no mesmo número de idas.
    _post(cliente, eid, "confirmar", _lista(10, 30))
    reenvio, c_reenvio = _previa_medida(cliente, db, eid, _lista(10, 30))
    assert (reenvio["alunos_novos"], reenvio["alunos_atualizar"],
            reenvio["alunos_em_revisao"]) == (0, 300, 0)
    assert c_reenvio.escritas == []
    assert len(c_reenvio.lista) == len(c_pequena.lista)


def _ficha(db, eid, turma, nome, **campos) -> Aluno:
    aluno = Aluno(escola_id=eid, nome=nome, **campos)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=2026))
    return aluno


def _cenario_nome_completo_e_mudanca_de_sala(db, escola_completa):
    """A ficha abreviada ganha o nome completo na 1ª linha; a 2ª (outra sala, mesmo
    nome, sem prova) só a reconhece pelo nome NOVO — vai para a revisão."""
    eid = escola_completa["escola"].id
    _ficha(db, eid, escola_completa["turma"], "MARIA E SILVA")
    db.commit()
    return _planilha(
        ("3º ANO A", [_aluno("MARIA EDUARDA SILVA", numero=1)]),
        ("4º ANO B", [_aluno("MARIA EDUARDA SILVA", numero=1),
                      _aluno("CRIANCA FICTICIA NOVA", numero=2)]))


def _cenario_mesma_crianca_em_duas_abas(db, escola_completa):
    """A ficha NOVA da 1ª aba é a mesma criança (RA) da 2ª: cria uma, sem contar a
    2ª como atualizada."""
    return _planilha(
        ("5º ANO C", [_aluno("CRIANCA FICTICIA REPETIDA", numero=1, ra="111222333-4")]),
        ("5º ANO D", [_aluno("CRIANCA FICTICIA REPETIDA", numero=7, ra="111222333-4")]))


def _cenario_status_e_turma_arquivada(db, escola_completa):
    """Transferida (não reativa), excluída com RA (reativa), excluída cuja conta vale
    noutra escola (retida, D10), turma arquivada (não aplicada) e divergência de
    nascimento (preserva) — os mesmos números e nada gravado."""
    from app.models import Escola
    eid = escola_completa["escola"].id
    turma = escola_completa["turma"]
    _ficha(db, eid, turma, "CRIANCA TRANSFERIDA FICTICIA", status="transferido")
    _ficha(db, eid, turma, "CRIANCA EXCLUIDA FICTICIA", status="excluido",
           ficha={"ra": "555666777-8"})
    retida = _ficha(db, eid, turma, "CRIANCA RETIDA FICTICIA", status="excluido",
                    ficha={"ra": "999888777-6"})
    _ficha(db, eid, turma, "CRIANCA NASCIMENTO FICTICIA", data_nascimento=date(2017, 3, 3),
           ficha={"ra": "444333222-1"})
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    t_outra = Turma(escola_id=outra.id, nome="3º Ano A", ano_escolar="3º Ano",
                    ano_letivo=2026)
    db.add(t_outra)
    db.flush()
    la = Aluno(escola_id=outra.id, nome="CRIANCA DE LA FICTICIA")
    db.add(la)
    db.flush()
    db.add(IdentidadeExterna(escola_id=outra.id, aluno_id=la.id, plataforma="matific",
                             id_externo="uuid-fict-d10"))
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=retida.id, plataforma="matific",
                             id_externo="uuid-fict-d10"))
    db.add(Turma(escola_id=eid, nome="2º Ano B", ano_escolar="2º Ano", ano_letivo=2026,
                 status="arquivada"))
    db.commit()
    return _planilha(
        ("3º ANO A", [_aluno("CRIANCA TRANSFERIDA FICTICIA", numero=1),
                      _aluno("CRIANCA EXCLUIDA FICTICIA", numero=2, ra="555666777-8"),
                      _aluno("CRIANCA RETIDA FICTICIA", numero=3, ra="999888777-6"),
                      _aluno("CRIANCA NASCIMENTO FICTICIA", numero=4, ra="444333222-1",
                             nasc=date(2017, 4, 4))]),
        ("2º ANO B", [_aluno("CRIANCA NA TURMA ARQUIVADA", numero=1)]))


@pytest.mark.parametrize("cenario, esperado", [
    (_cenario_nome_completo_e_mudanca_de_sala, (1, 1, 1)),
    (_cenario_mesma_crianca_em_duas_abas, (1, 0, 0)),
    (_cenario_status_e_turma_arquivada, (0, 3, 0)),
])
def test_previa_so_lendo_da_os_numeros_da_confirmacao(cliente, db, escola_completa,
                                                     cenario, esperado):
    """(novos, a atualizar, em revisão) da prévia = os da confirmação = ``esperado``."""
    eid = escola_completa["escola"].id
    conteudo = cenario(db, escola_completa)
    antes = _contagens(db, eid)
    previa, comandos = _previa_medida(cliente, db, eid, conteudo)
    assert comandos.escritas == [], sorted(set(comandos.escritas))
    assert _contagens(db, eid) == antes, "a prévia gravou alguma coisa"
    res = _post(cliente, eid, "confirmar", conteudo)
    assert (previa["alunos_novos"], previa["alunos_atualizar"],
            previa["alunos_em_revisao"]) == (res["alunos_criados"],
                                             res["alunos_atualizados"],
                                             res["alunos_em_revisao"]), (previa, res)
    assert (res["alunos_criados"], res["alunos_atualizados"],
            res["alunos_em_revisao"]) == esperado, res
