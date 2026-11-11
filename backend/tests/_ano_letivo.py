"""O ano letivo das escolas de teste — fonte ÚNICA (TESTES-1, PERIODOS-9).

O produto mede o ano letivo pela janela civil do DADO: ``matific_destaque.
janela_ano_letivo`` (o contador do ano do Matific em ``scoring.snapshots_matific_do_ano``,
ranking, painel público, frescor) e a retenção de queda do sync comparam
``[ano-01-01 00:00, ano-12-31 23:59:59]`` com o instante GRAVADO (``models.base.agora``,
UTC naive). Então a escola de teste tem de estar no ano dos dados do teste:

* ``ANO`` — o ano de HOJE, para o teste que grava retratos e leituras "agora" (o default
  das colunas, ou a importação, a coleta e o recálculo que ele exercita). Com 2026 escrito
  no código, a partir de 01/01/2027 00:00 UTC (31/12 às 21h em Brasília, a hora do runner
  do CI) esses dados caíam fora do ano da escola: Matemática zerada, painel público
  vazio, retenção de queda desligada — mais de cem testes vermelhos sem nenhuma mudança
  de código. É o ano de ``agora()``, em UTC, e não o de ``hoje_br()``: nas três últimas
  horas de 31/12 em Brasília o UTC já virou o ano e o retrato gravado nessa hora cai na
  janela do ano NOVO (a borda em UTC é a decisão pendente do dono "contar pelo horário de
  Brasília", TESTES-6). Calculado na importação: só uma sessão que atravesse a meia-noite
  UTC de 31/12 veria dados no ano seguinte ao da escola.
* ``ANO_DAS_DATAS_FIXAS`` — 2026, o ano do mundo de datas fixas em que a maior parte da
  suíte foi escrita (Listas Piloto "de 2026", retratos de março e de setembro, relógios
  presos em 20/10/2026). É o ano da ``escola_completa`` do conftest; esses testes valem em
  qualquer ano porque a escola e os dados concordam.

O teste que grava "agora" sobre a ``escola_completa`` pede o ano de hoje: no módulo
inteiro, importando a fixture :func:`escola_no_ano_de_hoje`; num teste só, com
``@no_ano_de_hoje``. A fixture própria de um módulo usa ``ANO`` direto. Quem estende a
``escola_completa`` (outra turma, outra matrícula) usa o ano dela,
``escola.ano_letivo_ativo``, e não um número.
"""
import pytest

from app.models.base import agora

ANO: int = agora().year

ANO_DAS_DATAS_FIXAS = 2026


@pytest.fixture(name="ano_letivo_da_escola")
def escola_no_ano_de_hoje() -> int:
    """A ``escola_completa`` (e quem a estende) no ano de HOJE: para o módulo cujos testes
    gravam os retratos e as leituras "agora". Uso: ``from tests._ano_letivo import
    escola_no_ano_de_hoje  # noqa: F401 — fixture``."""
    return ANO


#: O mesmo para UM teste, num módulo de datas fixas: ``@no_ano_de_hoje``.
no_ano_de_hoje = pytest.mark.parametrize("ano_letivo_da_escola", [ANO], ids=["ano_de_hoje"])
