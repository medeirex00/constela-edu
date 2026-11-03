/**
 * Moldura das telas PÚBLICAS de entrada (Login e Redefinir senha) na identidade v2:
 * painel marinho com o logotipo oficial (versão para fundo escuro), uma frase curta e
 * uma constelação discreta; ao lado, o cartão branco do formulário sobre a lavanda.
 *
 * No celular/tablet em pé o painel vira uma faixa no topo (logotipo + frase) e o
 * cartão vem logo abaixo. As estrelas piscam com a classe `painel-estrela` (CSS
 * plano de index.css, que de propósito NÃO desliga no telão); aqui, que é tela de
 * uso, `motion-reduce:!animate-none` as para em prefers-reduced-motion (o ! vence a
 * regra fora de @layer). Tela de entrada fica SEMPRE no tema escuro (lib/tema.ts): a
 * preferência claro/escuro só vale nas páginas internas; o painel é marinho.
 *
 * Só textos institucionais fixos: nenhum número, nenhum dado de escola.
 */
import { Award, FileBadge, Trophy } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { LogoHorizontal } from "./Logo";

const CEU: CSSProperties = {
  backgroundColor: "#17193B",
  backgroundImage: [
    "radial-gradient(110% 70% at 0% 0%, rgba(108, 92, 231, 0.38), transparent 58%)",
    "radial-gradient(80% 60% at 100% 100%, rgba(245, 185, 66, 0.13), transparent 62%)",
    "linear-gradient(160deg, #1F2250 0%, #17193B 48%, #0F1126 100%)",
  ].join(", "),
};

/** Estrelas soltas do fundo (posição em %, tamanho em px, atraso da cintilação). */
const ESTRELAS: { x: number; y: number; t: number; d: number; ambar?: boolean }[] = [
  { x: 12, y: 14, t: 2, d: 0 },
  { x: 78, y: 9, t: 3, d: 1.2 },
  { x: 64, y: 30, t: 2, d: 2.4, ambar: true },
  { x: 90, y: 46, t: 2, d: 0.6 },
  { x: 22, y: 58, t: 3, d: 1.8 },
  { x: 8, y: 86, t: 2, d: 3 },
  { x: 46, y: 92, t: 2, d: 0.9 },
  { x: 84, y: 80, t: 3, d: 2.1, ambar: true },
  { x: 36, y: 22, t: 1.5, d: 1.5 },
];

/** Uma constelação estilizada (o "C" da marca em pontos ligados), decorativa. */
function Constelacao({ className = "" }: { className?: string }) {
  const pontos: [number, number][] = [
    [150, 20], [92, 34], [52, 78], [44, 132], [70, 182], [124, 206], [176, 196],
  ];
  return (
    <svg aria-hidden viewBox="0 0 220 230" className={className} fill="none">
      <polyline
        points={pontos.map(([x, y]) => `${x},${y}`).join(" ")}
        stroke="rgba(201, 203, 227, 0.35)"
        strokeWidth="1.2"
        strokeDasharray="3 5"
      />
      {pontos.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i === 3 ? 4.5 : 3} fill={i === 3 ? "#F5B942" : "#E6E7F5"} />
      ))}
      <circle cx="118" cy="118" r="20" fill="#F5B942" opacity="0.9" />
    </svg>
  );
}

function Destaque({ icone: Icone, children }: { icone: typeof Trophy; children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-2xl bg-white/[0.06] px-4 py-3 ring-1 ring-inset ring-white/10">
      <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-indigo-500/25 text-indigo-200">
        <Icone size={18} strokeWidth={2} />
      </span>
      <span className="text-sm font-medium text-marinho-200">{children}</span>
    </li>
  );
}

export function MolduraEntrada({ children, rodape }: { children: ReactNode; rodape?: ReactNode }) {
  return (
    <div className="login-fade min-h-screen bg-zinc-50 dark:bg-zinc-950 lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      {/* Painel da marca: faixa no topo (estreito) ou coluna inteira (lg+). */}
      <section
        aria-label="Constela Edu"
        style={CEU}
        className="relative overflow-hidden px-6 pb-16 pt-8 text-white sm:px-10 lg:flex lg:min-h-screen lg:flex-col lg:justify-between lg:px-14 lg:py-12"
      >
        {ESTRELAS.map((e, i) => (
          <span
            key={i}
            aria-hidden
            className="painel-estrela absolute rounded-full motion-reduce:!animate-none"
            style={{
              left: `${e.x}%`,
              top: `${e.y}%`,
              width: e.t,
              height: e.t,
              background: e.ambar ? "#F5B942" : "#FFFFFF",
              animationDelay: `${e.d}s`,
            }}
          />
        ))}
        {/* A constelação nunca pode cobrir as pílulas de recursos (que terminam a
            440 px da borda esquerda: px-14 + max-w-sm). Até 1279 px o painel é
            estreito demais e ela fica escondida; de 1280 a 1319 px vai menor (w-60);
            a partir de 1320 px, no tamanho cheio. Nas duas faixas o ponto mais à
            esquerda do desenho fica além dos 440 px. */}
        <Constelacao className="pointer-events-none absolute -bottom-6 -right-6 hidden w-60 opacity-60 xl:block min-[1320px]:w-72" />

        <div className="relative">
          <LogoHorizontal altura={44} sobreEscuro />
        </div>

        <div className="relative mt-8 max-w-md lg:mt-0">
          <p className="text-[26px] font-bold leading-tight tracking-tight text-white sm:text-[30px] lg:text-[40px]">
            Leitura e matemática que viram{" "}
            <span className="text-ouro-400">reconhecimento</span>.
          </p>
          <p className="mt-4 hidden text-[15px] leading-relaxed text-marinho-200 lg:block">
            Rankings, premiações e certificados da sua escola, com os dados do Elefante
            Letrado e do Matific num lugar só.
          </p>
          <ul className="mt-8 hidden max-w-sm space-y-3 lg:block">
            <Destaque icone={Trophy}>Rankings por turma, série e escola</Destaque>
            <Destaque icone={Award}>Premiações por bimestre</Destaque>
            <Destaque icone={FileBadge}>Certificados prontos para imprimir</Destaque>
          </ul>
        </div>

        <span aria-hidden className="hidden lg:block" />
      </section>

      {/* Cartão do formulário sobre a lavanda (no estreito, sobe por cima da faixa). */}
      <div className="relative -mt-10 flex justify-center px-4 pb-10 sm:px-6 lg:mt-0 lg:items-center lg:px-10 lg:py-12">
        <main className="login-surgir w-full max-w-md">
          <div className="rounded-[28px] border border-zinc-200/80 bg-white p-7 shadow-flutuante dark:border-zinc-800 dark:bg-zinc-900 sm:p-10">
            {children}
          </div>
          {rodape}
          <p className="mt-6 text-center text-xs text-zinc-500 dark:text-zinc-400">
            Plataforma segura&nbsp;·&nbsp;LGPD&nbsp;·&nbsp;Dados protegidos
          </p>
        </main>
      </div>
    </div>
  );
}
