"""REV2-COSTURA-3 / ALUNOS-4: o que os textos da conta aposentada dizem é o que acontece.

Aposentar uma conta não tira da ficha o que já veio dela: nem o retrato
(``SnapshotMatific``) nem a leitura guardam a conta de origem. A tela das Revisões
(``RevisoesIdentidade.tsx``), o schema ``DefinirIdentidadeEfetivaIn``, a rota
``/identidades/{plataforma}/efetiva`` e o cabeçalho de ``identidade_efetiva`` dizem:
o retrato atual só muda quando entrar uma coleta da conta que vale, e no Matific a
trava contra queda da coleta automática segura essa coleta se a aposentada tinha
números maiores. Antes, os textos prometiam que os números saíam "na próxima coleta
da conta que vale".

Se este teste mudar (a coluna da conta no retrato, decisão ALUNOS-4 do dono), os
textos mudam junto. Dados fictícios.
"""
from datetime import datetime

from app.models import IdentidadeExterna, SnapshotMatific
from app.models.plataformas import Importacao
from tests.test_sync_matific_queda import (  # noqa: F401  (fixture autouse do relógio)
    _aplicar, _atual, _placar, _relogio_em_outubro_de_2026)


def test_coleta_da_conta_que_vale_abaixo_da_aposentada_fica_retida(
        db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id, plataforma="matific",
                             id_externo="uuid-aposentada", status="aposentada",
                             aposentada_em=datetime(2026, 10, 2, 9, 0),
                             motivo_aposentadoria="conta duplicada (teste ficticio)"))
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id, plataforma="matific",
                             id_externo="uuid-ana"))
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="texto",
                     status="concluida")
    db.add(imp)
    db.flush()
    # o retrato que veio da conta aposentada, antes de ela ser aposentada
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 10, 1, 6, 0), atividades=100,
                           estrelas=300, pontuacao_media=3.0))
    db.commit()

    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=180, atividades=60),
                   monkeypatch)

    assert res["retidos_queda"] == 1
    atual = _atual(db, escola, ana)
    assert (atual.atividades, atual.estrelas) == (100, 300)    # o da aposentada ficou

    # acima dos números da aposentada, a coleta da que vale entra
    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=310, atividades=101),
                   monkeypatch)
    assert res["retidos_queda"] == 0
    assert _atual(db, escola, ana).atividades == 101
