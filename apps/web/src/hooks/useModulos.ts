import { useApp } from "../context/AppContext";

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
 */
export function useModulos() {
  const { usuario } = useApp();
  // Sessão ainda carregando ou payload antigo (bundle novo × API antiga): assume
  // tudo ligado, que é o comportamento pré-SaaS — some conteúdo é pior que
  // mostrar o que a pessoa já via.
  const lista = usuario?.modulos?.length ? usuario.modulos : ["leitura", "matematica"];
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
