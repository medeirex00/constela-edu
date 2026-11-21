"""Varredura ESTÁTICA das rotas: a que cita o Matific passa pela trava de módulo.

Toda rota cujo código cita o Matific (``SnapshotMatific``, o placar ao vivo
``aovivo`` ou a plataforma ``"matific"``) tem de olhar o contrato da rede: a
dependência ``exigir_modulo_da_escola`` no decorador ou o uso de
``services/modulos`` (no corpo da rota ou numa função que ela chama
diretamente). Rota nova que entregue o Matific sem isso quebra este teste, em
vez de só o front esconder o módulo (achado e97/autorização 1).

Limite declarado: olha o código da PRÓPRIA rota (e, para achar a trava, um nível
de chamadas). Rota que só delega a um serviço que lê o Matific não é detectada
aqui; as superfícies mistas conhecidas têm teste de comportamento em
``test_modulos_trava_api_mista.py``.
"""
import inspect
import re
import types

from fastapi.routing import APIRoute

from app.main import app

_CITA_MATIFIC = re.compile(r"SnapshotMatific|\baovivo\b|[\"']matific[\"']")
_TRAVA = re.compile(r"svc_modulos\.|modulos_da_escola|plataformas_fora_do_plano|"
                    r"_exigir_dimensao|exigir_plataforma|plataforma_contratada")

# Rotas que citam o Matific SEM a trava, de propósito. Cada uma diz por quê; rota
# nova que cair aqui precisa da trava ou de uma justificativa revisada.
# (O GET /sync/status saiu daqui em 28/10: passou a ler o contrato da rede na
# própria consulta da escola — o alerta 'desatualizada' do módulo fora do plano.)
_SEM_TRAVA_DE_PROPOSITO = {
    "app.routers.sistema.simular":
        "aluno HIPOTÉTICO digitado pela gestão: nenhum dado de criança sai",
    "app.sync.router.salvar_credenciais":
        "risco residual declarado: salvar/testar credencial com o módulo desligado",
    "app.sync.router.remover_credenciais":
        "remover a credencial tem de seguir possível com o módulo desligado",
    "app.routers.admin.restaurar_backup":
        "só descarta o cache do ao vivo do Matific da escola restaurada (G_LGPD-8), "
        "rota do Admin Global: nenhum dado do Matific sai na resposta",
}


def _nome(fn) -> str:
    return f"{fn.__module__}.{fn.__name__}"


def _dependencias(dependant, acc: set) -> set:
    for dep in dependant.dependencies:
        acc.add(getattr(dep.call, "__qualname__", repr(dep.call)))
        _dependencias(dep, acc)
    return acc


def _chamadas_diretas(fn, fonte: str) -> list:
    """Funções que ``fn`` chama pelo nome: ``modulo.funcao(`` (módulo importado)
    e ``funcao(`` do próprio módulo."""
    globais = fn.__globals__
    achadas = []
    for nome_mod, nome_fn in re.findall(r"\b(\w+)\.(\w+)\(", fonte):
        mod = globais.get(nome_mod)
        if isinstance(mod, types.ModuleType):
            alvo = getattr(mod, nome_fn, None)
            if inspect.isfunction(alvo):
                achadas.append(alvo)
    for nome_fn in re.findall(r"(?<![.\w])(\w+)\(", fonte):
        alvo = globais.get(nome_fn)
        if (inspect.isfunction(alvo) and alvo is not fn
                and alvo.__module__ == fn.__module__):
            achadas.append(alvo)
    return achadas


def _tem_trava(fn, dependencias: set) -> bool:
    if any("exigir_modulo_da_escola" in nome for nome in dependencias):
        return True
    fonte = inspect.getsource(fn)
    if _TRAVA.search(fonte):
        return True
    for chamada in _chamadas_diretas(fn, fonte):
        try:
            if _TRAVA.search(inspect.getsource(chamada)):
                return True
        except (OSError, TypeError):
            continue
    return False


def _rotas_que_citam_o_matific() -> dict[str, bool]:
    """``{módulo.função: tem_trava}`` das rotas que citam o Matific."""
    saida: dict[str, bool] = {}
    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue
        fn = rota.endpoint
        if not _CITA_MATIFIC.search(inspect.getsource(fn)):
            continue
        saida[_nome(fn)] = (saida.get(_nome(fn), False)
                            or _tem_trava(fn, _dependencias(rota.dependant, set())))
    return saida


def test_toda_rota_que_cita_o_matific_tem_a_trava_de_modulo():
    rotas = _rotas_que_citam_o_matific()
    sem_trava = {nome for nome, trava in rotas.items()
                 if not trava and nome not in _SEM_TRAVA_DE_PROPOSITO}
    assert not sem_trava, (
        "Rota que cita o Matific sem a trava de módulo contratado (use "
        "exigir_modulo_da_escola no decorador ou services/modulos na resposta): "
        f"{sorted(sem_trava)}")


def test_a_varredura_nao_e_vazia_e_a_lista_de_excecoes_esta_em_dia():
    rotas = _rotas_que_citam_o_matific()
    # As rotas de plataforma conhecidas são achadas, e com a trava.
    for conhecida in ("app.sync.router.matific_placar_ao_vivo",
                      "app.routers.plataformas.modulo_matific",
                      "app.routers.rankings.ranking_matematica",
                      "app.routers.academico.perfil_aluno",
                      "app.routers.importacoes.confirmar"):
        assert rotas.get(conhecida) is True, conhecida
    # Exceção que não cita mais o Matific (ou ganhou a trava) sai da lista.
    for nome in _SEM_TRAVA_DE_PROPOSITO:
        assert rotas.get(nome) is False, f"exceção desatualizada: {nome}"


def test_o_detector_acusa_rota_sem_trava_e_aceita_a_trava_delegada():
    def _rota_sem_trava(db):
        return db.query("SnapshotMatific").all()

    def _rota_com_trava(db, escola):
        _ajudante_com_trava(db, escola)
        return db.query("SnapshotMatific").all()

    assert _CITA_MATIFIC.search(inspect.getsource(_rota_sem_trava))
    assert not _tem_trava(_rota_sem_trava, set())
    assert _tem_trava(_rota_sem_trava,
                      {"exigir_modulo_da_escola.<locals>.dependencia"})
    assert _tem_trava(_rota_com_trava, set())


def _ajudante_com_trava(db, escola):
    from app.services import modulos as svc_modulos
    svc_modulos.exigir(svc_modulos.modulos_da_escola(db, escola), "matematica")
