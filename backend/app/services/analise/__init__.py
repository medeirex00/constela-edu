"""Análise educacional integrada — SÓ LEITURA (``/redes/{id}/analise/...`` e
``/escolas/{id}/analise``).

O que este pacote faz: junta, numa forma ÚNICA e normalizada, o que já existe em dois
lugares que não conversavam —

* os indicadores OFICIAIS (ICA, SARESP, IEE, Ideb e Saeb), lidos pelas consultas
  oficiais de ``services/indicadores`` (``consulta``, ``consulta_saresp``,
  ``consulta_ideb`` e ``consulta_ideb_rede``) — este pacote não relê as tabelas: só
  normaliza a SAÍDA delas (os mesmos números, as mesmas ausências, as mesmas metas e as
  mesmas comparações) — em ``indicadores``;
* o engajamento nas plataformas (Elefante Letrado e Matific) por escola × série num
  período, pelas funções de ``relatorios_periodo`` (a mesma regra do Relatório por
  Período e das premiações), agregado SEM nome nem id de aluno e com supressão de
  células pequenas — em ``plataformas``;
* a RELAÇÃO entre os dois (associação de postos de Spearman por escola), só quando os
  critérios de ``docs/analise/METODOLOGIA.md`` são cumpridos — em ``relacao``;
* a visão de UMA escola — em ``escola``.

Regras que valem para todo o pacote (contrato da análise):

* nada é gravado: nenhuma escrita, nenhuma migração, nem a linha do catálogo;
* AUSÊNCIA ≠ ZERO: sem número, ``valor`` nulo + motivo (nunca 0, nunca interpolado);
* OFICIAL × ESTIMATIVA: só número com importação oficial é oficial; a "Estimativa
  Constela" fica à parte, rotulada, e NUNCA entra numa série oficial; o Ideb e o Saeb
  gravados antes, sem o registro do arquivo oficial, aparecem marcados
  (``proveniencia = "sem_registro"``), como na consulta oficial; nem um nem outro entra
  nos destaques ou na relação;
* nenhuma resposta traz nome ou id de aluno;
* escalas e populações diferentes não são tratadas como comparáveis (SARESP × Saeb ×
  ICA; rede municipal × rede pública/estadual; 2º ano amostral).
"""

from datetime import date

# Supressão: célula (escola × série) com menos alunos que isto não mostra métrica.
K_MINIMO = 5
# Relação: mínimo de escolas com os dois valores para calcular o coeficiente.
N_MINIMO = 8
# Faixa de anos aceita nas datas do período e na edição da avaliação. Fora dela o pedido
# não tem sentido para uma rede de hoje — e a conta nem existe: ``datetime`` não representa
# o ano 0 nem o 10000, e a borda do período menos a tolerância de 1 h estoura no ano 1.
ANO_MINIMO = 2000
ANO_MAXIMO = 2100


class AnaliseInvalida(Exception):
    """Pedido que não se sustenta (filtro inexistente, combinação sem sentido). O
    ``status`` é o código HTTP que a rota devolve (400, 404 ou 422)."""

    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


def validar_anos(*, inicio: date | None = None, fim: date | None = None,
                 edicao: int | None = None) -> None:
    """Recusa (422) a data do período ou a edição fora de ``ANO_MINIMO``–``ANO_MAXIMO`` —
    chamada ANTES de medir qualquer escola (antes, o ano 0 ou o 10000 virava erro 500
    depois de a rota já ter medido a rede inteira)."""
    for rotulo, valor, ano in (("data inicial", inicio, inicio.year if inicio else None),
                               ("data final", fim, fim.year if fim else None),
                               ("edição", edicao, edicao)):
        if ano is not None and not ANO_MINIMO <= ano <= ANO_MAXIMO:
            mostrado = valor.isoformat() if isinstance(valor, date) else valor
            raise AnaliseInvalida(f"A {rotulo} ({mostrado}) está fora da faixa aceita: anos de "
                                  f"{ANO_MINIMO} a {ANO_MAXIMO}.", 422)
