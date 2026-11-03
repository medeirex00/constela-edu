/**
 * PÓDIO dos 3 primeiros de um ranking (identidade visual v2, referência "Ranking").
 *
 * Cartões com medalha de fita, avatar, nome, turma, o número que ORDENA a aba em
 * destaque (com a unidade real: "340 pontos", "85,0 nota geral") e mais métricas
 * reais do mesmo item. Nada é calculado aqui: a tela entrega os textos já
 * formatados, tirados dos campos que a API devolveu.
 *
 * Regras que o pódio NÃO quebra:
 *   - a posição é `item.posicao` da API, nunca o índice da lista. Só sobem ao pódio
 *     as posições 1, 2 e 3 em sequência a partir do 1º (`itensDoPodio`): com filtro de
 *     turma a gestão recebe a posição da ESCOLA INTEIRA (7º, 12º...) e não há pódio a
 *     celebrar ali — a tabela mostra a posição real;
 *   - sem link: o link para a ficha fica só na tabela (um link por aluno na tela);
 *   - sem render duplo: no estreito os cartões empilham na ordem 1, 2, 3 (a ordem do
 *     DOM); do `md` em diante o 1º vai para o centro só por CSS (`order`);
 *   - a medalha é desenho (aria-hidden); quem lê a tela ouve "1º lugar" em texto.
 */
import { Avatar, Chip } from "./ui";

export interface MetricaPodio {
  /** Rótulo curto, em minúsculas (ex.: "livros", "tempo"). */
  rotulo: string;
  valor: string;
}

export interface ItemPodio {
  chave: string | number;
  /** Posição carimbada pela API (1, 2 ou 3). */
  posicao: number;
  nome: string;
  turma?: string | null;
  /** Chave estável da cor do avatar (o id do aluno). */
  avatar?: string | number | null;
  /** O número que ordena a aba, com a unidade real. */
  destaque: { valor: string; unidade: string };
  /** Até 3 métricas reais do mesmo item. */
  metricas: MetricaPodio[];
}

/**
 * Os itens que estão DE FATO no pódio: as posições 1, 2 e 3 em sequência, a partir
 * do começo da lista. Lista que não começa no 1º (posições da escola inteira num
 * recorte) não tem pódio.
 */
export function itensDoPodio<T extends { posicao: number }>(lista: readonly T[]): T[] {
  const podio: T[] = [];
  for (const item of lista.slice(0, 3)) {
    if (item.posicao !== podio.length + 1) break;
    podio.push(item);
  }
  return podio;
}

const COR_MEDALHA: Record<1 | 2 | 3, { fundo: string; texto: string }> = {
  1: { fundo: "#F5B942", texto: "#5B3B00" },
  2: { fundo: "#CBD5E9", texto: "#2B3350" },
  3: { fundo: "#E0955A", texto: "#4A2306" },
};

/** Medalha com fita (mesmo desenho da `Medalha` do ui.tsx), com o "º" num <tspan>:
 *  o texto "1º" da tabela continua sendo o único na tela. */
function MedalhaPodio({ posicao, tamanho }: { posicao: 1 | 2 | 3; tamanho: number }) {
  const cor = COR_MEDALHA[posicao];
  return (
    <svg aria-hidden width={tamanho} height={Math.round(tamanho * 1.35)} viewBox="0 0 44 60" className="shrink-0">
      <path d="M8 0 h10 l6 18 h-10 z" fill="#5A4AD4" />
      <path d="M36 0 h-10 l-6 18 h10 z" fill="#6C5CE7" />
      <g transform="translate(0 16)">
        <circle cx="22" cy="22" r="21" fill={cor.fundo} />
        <circle cx="22" cy="22" r="16.5" fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="2" />
        <text
          x="22"
          y="23"
          textAnchor="middle"
          dominantBaseline="middle"
          fontFamily="Poppins, Inter, sans-serif"
          fontWeight="700"
          fontSize="15"
          fill={cor.texto}
        >
          {posicao}
          <tspan fontSize="10" dy="-4">º</tspan>
        </text>
      </g>
    </svg>
  );
}

const GRADE_METRICAS: Record<number, string> = { 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3" };

function CartaoPodio({ item, ordem }: { item: ItemPodio; ordem: string }) {
  const primeiro = item.posicao === 1;
  const medalha = (item.posicao >= 1 && item.posicao <= 3 ? item.posicao : 3) as 1 | 2 | 3;
  const metricas = item.metricas.slice(0, 3);
  return (
    <li
      className={`relative flex min-w-0 flex-col items-center rounded-cartao border px-4 text-center ${ordem} ${
        primeiro
          ? "border-ouro-200 bg-ouro-50 pb-6 pt-4 shadow-cartao md:pb-8 md:pt-5 dark:border-ouro-400/30 dark:bg-ouro-400/10"
          : "border-zinc-200/80 bg-white pb-5 pt-3 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900"
      }`}
    >
      <span className="sr-only">{item.posicao}º lugar: </span>
      <MedalhaPodio posicao={medalha} tamanho={primeiro ? 44 : 36} />
      <Avatar nome={item.nome} chave={item.avatar ?? item.nome} tamanho={primeiro ? "xl" : "lg"} className="mt-1 shadow-cartao" />
      <p
        className={`mt-3 line-clamp-2 max-w-full break-words font-semibold leading-snug text-zinc-900 dark:text-white ${
          primeiro ? "text-base sm:text-[17px]" : "text-[15px]"
        }`}
      >
        {item.nome}
      </p>
      {item.turma && <Chip className="mt-2">{item.turma}</Chip>}
      <p className="mt-4 flex flex-wrap items-baseline justify-center gap-x-1.5 tabular-nums">
        <span
          className={`font-bold leading-none tracking-tight text-zinc-900 dark:text-white ${
            primeiro ? "text-[34px]" : "text-[28px]"
          }`}
        >
          {item.destaque.valor}
        </span>
        <span className="text-sm font-semibold text-zinc-500 dark:text-zinc-400">{item.destaque.unidade}</span>
      </p>
      {metricas.length > 0 && (
        <dl
          className={`mt-4 grid w-full divide-x divide-zinc-200/80 rounded-2xl px-1 py-2.5 dark:divide-zinc-700 ${
            GRADE_METRICAS[metricas.length]
          } ${primeiro ? "bg-white/80 dark:bg-zinc-900/60" : "bg-zinc-50 dark:bg-zinc-800/50"}`}
        >
          {metricas.map((m) => (
            <div key={m.rotulo} className="flex min-w-0 flex-col-reverse items-center gap-0.5 px-2">
              <dt className="truncate text-[11px] font-medium text-zinc-500 dark:text-zinc-400" title={m.rotulo}>{m.rotulo}</dt>
              <dd className="truncate text-sm font-semibold tabular-nums text-zinc-800 dark:text-zinc-100" title={m.valor}>{m.valor}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

/** Pódio em cartões. Recebe só os itens do pódio (use `itensDoPodio`). */
export function PodioRanking({ itens, rotulo = "Pódio: os três primeiros" }: { itens: ItemPodio[]; rotulo?: string }) {
  if (itens.length === 0) return null;
  const tres = itens.length >= 3;
  const grade = tres
    ? "md:grid-cols-3"
    : itens.length === 2
      ? "md:mx-auto md:max-w-2xl md:grid-cols-2"
      : "md:mx-auto md:max-w-sm";
  // Com três, o 1º vai ao centro (2º à esquerda, 3º à direita) só no visual.
  const ordem = (posicao: number) =>
    !tres ? "" : posicao === 1 ? "md:order-2" : posicao === 2 ? "md:order-1" : "md:order-3";
  return (
    <section aria-label={rotulo}>
      <ol className={`grid grid-cols-1 items-end gap-4 ${grade}`}>
        {itens.slice(0, 3).map((item) => (
          <CartaoPodio key={item.chave} item={item} ordem={ordem(item.posicao)} />
        ))}
      </ol>
    </section>
  );
}

export default PodioRanking;
