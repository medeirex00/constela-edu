import { useApp } from "../context/AppContext";
import type { Escola } from "../lib/types";

/** Monta o retorno dos hooks de módulo a partir de uma lista já resolvida. */
function deLista(lista: string[]) {
  const tem = (chave: string) => lista.includes(chave);
  return {
    modulos: lista,
    leitura: tem("leitura"),
    matematica: tem("matematica"),
    tem,
    /** Só um módulo contratado — a interface simplifica (sem comparativos). */
    unico: lista.length === 1,
  };
}

/**
 * MÓDULOS CONTRATADOS pela rede do usuário (modelo SaaS).
 *
 * Fonte única de "esta rede tem este produto?", no mesmo molde do `usePerfil`:
 * derivação pura do contexto, sem fetch (os módulos chegam em `/auth/me`).
 *
 * Regras herdadas do backend (`app/services/modulos.py`):
 *  - ausência de configuração = módulo LIGADO (rede existente não muda);
 *  - escola sem rede = todos os módulos;
 *  - admin global vê o catálogo inteiro (ele administra todas as redes).
 *
 * NÃO confundir com "tem dados": módulo contratado sem importação continua
 * aparecendo, com estado vazio. Módulo NÃO contratado não aparece de forma
 * alguma — nem como zero.
 *
 * Tela de UMA escola que consulta rota com contrato da escola (classificação
 * por matéria, colunas por matéria): use `useModulosDaEscola`.
 */
export function useModulos() {
  const { usuario } = useApp();
  // Sessão ainda carregando ou payload antigo (bundle novo × API antiga): assume
  // tudo ligado, que é o comportamento pré-SaaS — some conteúdo é pior que
  // mostrar o que a pessoa já via.
  const lista = usuario?.modulos?.length ? usuario.modulos : ["leitura", "matematica"];
  return deLista(lista);
}

/** Escola do seletor (`GET /escolas`) com o contrato da rede DELA. O campo é
 *  novo e opcional: fica aqui, e não em `@constela/core`, até o tipo comum ser
 *  revisto no fim da transição da nota geral (plano de retirada, item 12). */
type EscolaComContrato = Escola & { modulos?: string[] | null };

/**
 * MÓDULOS que valem na ESCOLA ABERTA — o plano do usuário E o contrato da rede
 * daquela escola.
 *
 * Por que existe: `useModulos` diz o que vale para o USUÁRIO, e o Admin Global
 * recebe o catálogo inteiro. Numa escola cuja rede não contratou Matemática, a
 * tela oferecia Matemática (Top 5 do painel, aba Desempenho, coluna da turma) e
 * `/ranking?dimensao=matematica` respondia 403 — "ninguém é não aferido num
 * produto que a rede não comprou" (spec §3.5). O backend decide pelo contrato
 * DA ESCOLA (`_exigir_dimensao`); esta tela passa a decidir pelo mesmo.
 *
 * Fonte: `modulos` de cada escola em `GET /escolas` (o seletor do topo, já no
 * contexto — sem fetch). Para quem não é global o resultado é o mesmo de
 * `useModulos` (a escola é da rede dele). Sem escola aberta, ou com a API
 * anterior ao campo, cai no `useModulos` — o comportamento de antes.
 */
export function useModulosDaEscola() {
  const { usuario, escolaAtual } = useApp();
  const doUsuario = useModulos();
  const daEscola = (escolaAtual as EscolaComContrato | null)?.modulos;
  if (!usuario || !daEscola?.length) return doUsuario;
  return deLista(daEscola.filter((chave) => doUsuario.tem(chave)));
}
