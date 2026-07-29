"""Pontos extras por livro lido NA ESCOLA: a janela de horário vem do TURNO da
turma (Manhã 07–13h, Tarde 13–18h, seg–sex). Integral/Noite não recebem bônus."""
from datetime import date, datetime, time, timedelta

from app.models import Aluno, Leitura, Livro, Turma
from app.services import scoring

API = "/api/v1"


def _segunda_e_sabado() -> tuple[date, date]:
    d = date(2026, 7, 6)
    while d.weekday() != 0:          # 0 = segunda-feira
        d += timedelta(days=1)
    return d, d + timedelta(days=5)  # (segunda, sábado)


def test_bonus_conta_so_leituras_dentro_da_janela_do_turno(db, escola_completa):
    escola = escola_completa["escola"]
    turma = Turma(escola_id=escola.id, nome="3º Ano M", ano_escolar="3º Ano",
                  ano_letivo=2026, turno="manha")
    db.add(turma)
    db.flush()
    aluno = Aluno(escola_id=escola.id, nome="Zé Manhã")
    db.add(aluno)
    db.flush()

    seg, sab = _segunda_e_sabado()
    momentos = [
        datetime.combine(seg, time(8, 0)),    # dentro (manhã)
        datetime.combine(seg, time(12, 59)),  # dentro (< 13h)
        datetime.combine(seg, time(13, 0)),   # FORA da manhã (13h já é tarde)
        datetime.combine(seg, time(14, 0)),   # FORA da manhã
        datetime.combine(sab, time(9, 0)),    # FORA (fim de semana)
    ]
    for i, quando in enumerate(momentos):
        lv = Livro(escola_id=escola.id, titulo=f"Livro {i}", nivel_codigo="AA")
        db.add(lv)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=lv.id, data=quando))
    db.commit()

    # Manhã: 2 livros na janela × 1.5 = 3.0
    assert scoring._bonus_leitura_na_escola(db, escola.id, {aluno.id: "manha"}, 1.5) == {aluno.id: 3.0}
    # Tarde (13h e 14h caem na janela): 2 livros × 1.0
    assert scoring._bonus_leitura_na_escola(db, escola.id, {aluno.id: "tarde"}, 1.0) == {aluno.id: 2.0}
    # Integral/Noite não têm janela → sem bônus
    assert scoring._bonus_leitura_na_escola(db, escola.id, {aluno.id: "integral"}, 1.0) == {}
    # Desligado (pontos 0) → sem bônus
    assert scoring._bonus_leitura_na_escola(db, escola.id, {aluno.id: "manha"}, 0.0) == {}


def test_config_elefante_extra_liga_e_desliga(cliente, escola_completa):
    escola = escola_completa["escola"]
    base = f"{API}/escolas/{escola.id}/configuracoes/elefante-extra"

    # Padrão: desligado (sem row → default do obter_config).
    assert cliente.get(base).json() == {"ativo": False, "pontos_por_livro": 0.0}

    # Liga (recalcula ao salvar; sem leituras é no-op).
    r = cliente.put(base, json={"ativo": True, "pontos_por_livro": 2})
    assert r.status_code == 200, r.text
    assert r.json() == {"ativo": True, "pontos_por_livro": 2.0}
    assert cliente.get(base).json()["ativo"] is True

    # Desliga — a flag muda, mas as leituras NÃO são apagadas (só deixa de somar).
    assert cliente.put(base, json={"ativo": False, "pontos_por_livro": 2}).json()["ativo"] is False
