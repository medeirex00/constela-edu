/**
 * Painel Público (PRD §104–§128): acessível por URL sem login, pensado para
 * telão/TV da escola. Carrossel de slides configurável, atualização
 * automática dos dados e modo tela cheia.
 */
import { Expand, Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useApi } from "../../hooks/useApi";
import { nota } from "../../lib/formato";

interface ItemRanking {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  nota_geral?: number;
  nota_evolucao?: number;
}

interface Destaque {
  aluno_id: number;
  nome: string;
  turma: string;
  nota_evolucao: number;
}

interface DadosPainel {
  escola: { nome: string; cor_primaria: string };
  slides: string[];
  intervalo_s: number;
  ranking: ItemRanking[];
  evolucao: ItemRanking[];
  destaques: { dia: Destaque | null; semana: Destaque | null; mes: Destaque | null };
  mural: { icone: string; texto: string }[];
}

const TITULOS: Record<string, string> = {
  ranking: "🏆 Ranking Geral",
  evolucao: "📈 Quem mais cresceu (30 dias)",
  destaques: "🌟 Destaques",
  mural: "📣 Mural da escola",
};

function TabelaPublica({ itens, campo, token }: { itens: ItemRanking[]; campo: "nota_geral" | "nota_evolucao"; token: string }) {
  return (
    <div className="mx-auto w-full max-w-3xl">
      {itens.length === 0 ? (
        <p className="py-16 text-center text-xl text-zinc-400">Ainda sem dados.</p>
      ) : (
        <ol className="space-y-2">
          {itens.map((item) => (
            <li
              key={item.aluno_id}
              className={`flex items-center gap-4 rounded-xl px-5 py-3 ${
                item.posicao === 1
                  ? "bg-amber-400/15 text-amber-100"
                  : item.posicao <= 3
                    ? "bg-white/10"
                    : "bg-white/5"
              }`}
            >
              <span className="w-12 text-2xl font-bold tabular-nums">{item.posicao}º</span>
              <Link
                to={`/p/${token}/alunos/${item.aluno_id}`}
                className="flex-1 truncate text-xl font-semibold hover:underline"
              >
                {item.nome}
              </Link>
              <span className="hidden text-base text-zinc-300 sm:block">{item.turma}</span>
              <span className="text-2xl font-bold tabular-nums">
                {nota(item[campo] ?? 0)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function CartaoDestaquePublico({ titulo, destaque }: { titulo: string; destaque: Destaque | null }) {
  return (
    <div className="rounded-2xl bg-white/10 p-6 text-center">
      <p className="text-lg text-zinc-300">{titulo}</p>
      {destaque ? (
        <>
          <p className="mt-3 text-3xl font-bold">{destaque.nome}</p>
          <p className="mt-1 text-zinc-300">{destaque.turma}</p>
          <p className="mt-2 text-xl tabular-nums text-emerald-300">
            evolução {nota(destaque.nota_evolucao)}
          </p>
        </>
      ) : (
        <p className="mt-6 text-zinc-400">Sem destaque no período.</p>
      )}
    </div>
  );
}

export default function PainelPublico() {
  const { token = "" } = useParams();
  // Cliente compartilhado: usa a base configurada (VITE_API_URL) — um fetch
  // relativo funcionaria só em dev (proxy do Vite); na Vercel o rewrite do SPA
  // devolveria HTML no lugar do JSON e o painel quebrava.
  const { dados, erro, recarregar } = useApi<DadosPainel>(
    token ? `/publico/${token}/painel` : null,
  );
  const [slideAtivo, setSlideAtivo] = useState(0);
  const [pausado, setPausado] = useState(false);
  const raiz = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Dados sempre frescos no telão: recarrega a cada 60s (o hook cuida do
    // cancelamento e do timeout de cada busca).
    const atualizador = window.setInterval(recarregar, 60_000);
    return () => window.clearInterval(atualizador);
  }, [recarregar]);

  useEffect(() => {
    if (!dados || pausado || dados.slides.length <= 1) return;
    const timer = window.setInterval(
      () => setSlideAtivo((atual) => (atual + 1) % dados.slides.length),
      Math.max(4, dados.intervalo_s) * 1000,
    );
    return () => window.clearInterval(timer);
  }, [dados, pausado]);

  if (erro) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-300">
        <p className="text-xl">Painel não encontrado ou desativado.</p>
      </div>
    );
  }
  if (!dados) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-400">
        Carregando painel...
      </div>
    );
  }

  const slide = dados.slides[slideAtivo % dados.slides.length];
  const cor = dados.escola.cor_primaria;

  return (
    <div ref={raiz} className="flex min-h-screen flex-col bg-zinc-950 text-white">
      <header
        className="flex items-center justify-between px-6 py-4"
        style={{ background: `linear-gradient(90deg, ${cor}, transparent)` }}
      >
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{dados.escola.nome}</h1>
          <p className="text-sm text-white/70">Painel de conquistas e rankings</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label={pausado ? "Retomar carrossel" : "Pausar carrossel"}
            className="rounded-lg bg-white/10 p-2 hover:bg-white/20"
            onClick={() => setPausado((atual) => !atual)}
          >
            {pausado ? <Play size={18} /> : <Pause size={18} />}
          </button>
          <button
            aria-label="Modo TV (tela cheia)"
            className="rounded-lg bg-white/10 p-2 hover:bg-white/20"
            onClick={() => {
              if (document.fullscreenElement) document.exitFullscreen();
              else raiz.current?.requestFullscreen();
            }}
          >
            <Expand size={18} />
          </button>
        </div>
      </header>

      <main className="flex flex-1 flex-col justify-center px-4 py-8">
        <h2 className="mb-8 text-center text-3xl font-bold">{TITULOS[slide]}</h2>

        {slide === "ranking" && <TabelaPublica itens={dados.ranking} campo="nota_geral" token={token} />}
        {slide === "evolucao" && <TabelaPublica itens={dados.evolucao} campo="nota_evolucao" token={token} />}
        {slide === "destaques" && (
          <div className="mx-auto grid w-full max-w-4xl gap-4 sm:grid-cols-3">
            <CartaoDestaquePublico titulo="Aluno do Dia" destaque={dados.destaques.dia} />
            <CartaoDestaquePublico titulo="Aluno da Semana" destaque={dados.destaques.semana} />
            <CartaoDestaquePublico titulo="Aluno do Mês" destaque={dados.destaques.mes} />
          </div>
        )}
        {slide === "mural" && (
          <ul className="mx-auto w-full max-w-2xl space-y-2">
            {dados.mural.length === 0 ? (
              <p className="py-16 text-center text-xl text-zinc-400">Nada no mural ainda.</p>
            ) : (
              dados.mural.map((evento, indice) => (
                <li key={indice} className="flex items-center gap-3 rounded-xl bg-white/5 px-5 py-3 text-lg">
                  <span className="text-2xl">{evento.icone}</span>
                  {evento.texto}
                </li>
              ))
            )}
          </ul>
        )}
      </main>

      {dados.slides.length > 1 && (
        <footer className="flex justify-center gap-2 pb-5">
          {dados.slides.map((nomeSlide, indice) => (
            <button
              key={nomeSlide}
              aria-label={`Ir para o slide ${TITULOS[nomeSlide]}`}
              className={`h-2.5 rounded-full transition-all ${
                indice === slideAtivo % dados.slides.length ? "w-8 bg-white" : "w-2.5 bg-white/30"
              }`}
              onClick={() => setSlideAtivo(indice)}
            />
          ))}
        </footer>
      )}
    </div>
  );
}
