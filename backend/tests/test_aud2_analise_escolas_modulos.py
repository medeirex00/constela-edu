"""GET /escolas traz os MÓDULOS do plano de cada escola (resíduo do RELATORIOS-5).

O admin global recebe em /auth/me o catálogo inteiro de módulos (ele administra todas as
redes). Ao abrir uma escola de uma rede com um módulo só, a tela de Relatórios oferecia o
que a rede não contratou e o backend respondia 403. A tela precisa saber o plano da ESCOLA
selecionada: cada item de /escolas leva ``modulos`` (os da rede dela; escola sem rede, todos).

O que estes testes sustentam:

* rede só com a Leitura → ``["leitura"]``; rede sem linha de contrato e escola avulsa →
  todos os módulos;
* o plano vem na MESMA consulta das escolas: o número de consultas da lista não cresce com
  o número de escolas nem de redes.

Dados INVENTADOS.
"""
from sqlalchemy import event

from app.models import Escola, ModuloRede, Rede
from app.services import modulos as svc_modulos

API = "/api/v1"


def _rede(db, nome, codigo, desligados=()):
    rede = Rede(nome=nome, codigo_ibge=codigo)
    db.add(rede)
    db.flush()
    for m in desligados:
        db.add(ModuloRede(rede_id=rede.id, modulo=m, ativo=False))
    return rede


def test_cada_escola_traz_o_plano_da_rede_dela(db, cliente_global, escola_completa):
    so_leitura = _rede(db, "Rede Fictícia Só Leitura", "3599981", desligados=("matematica",))
    completa = _rede(db, "Rede Fictícia Completa", "3599982")
    db.add_all([Escola(nome="EMEF Fictícia Só Leitura", ano_letivo_ativo=2026,
                       rede_id=so_leitura.id),
                Escola(nome="EMEF Fictícia Completa", ano_letivo_ativo=2026,
                       rede_id=completa.id)])
    db.commit()
    r = cliente_global.get(f"{API}/escolas")
    assert r.status_code == 200, r.text
    por_nome = {e["nome"]: e.get("modulos") for e in r.json()}
    todos = list(svc_modulos.TODOS)
    assert por_nome["EMEF Fictícia Só Leitura"] == ["leitura"]
    assert por_nome["EMEF Fictícia Completa"] == todos
    assert por_nome[escola_completa["escola"].nome] == todos            # escola sem rede


def test_o_plano_nao_custa_consulta_por_escola(db, cliente_global, escola_completa):
    def consultas() -> int:
        n = [0]

        def _conta(*_a, **_k):
            n[0] += 1
        motor = db.get_bind()
        event.listen(motor, "before_cursor_execute", _conta)
        try:
            assert cliente_global.get(f"{API}/escolas").status_code == 200
        finally:
            event.remove(motor, "before_cursor_execute", _conta)
        return n[0]

    antes = consultas()
    for i in range(4):
        rede = _rede(db, f"Rede Fictícia Plano {i}", f"35999{90 + i}", desligados=("leitura",))
        db.add(Escola(nome=f"EMEF Fictícia Plano {i}", ano_letivo_ativo=2026, rede_id=rede.id))
    db.commit()
    assert consultas() == antes
