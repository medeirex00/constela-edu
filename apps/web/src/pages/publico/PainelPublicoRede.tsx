/**
 * Vitrine PÚBLICA da Secretaria (sem login) — as MELHORES ESCOLAS da rede em
 * leitura e matemática, no tema "noite Constela" (mesmo do painel da escola),
 * mas com TOP 5 ESCOLAS (não top 3 alunos). Só agregado por escola: nunca
 * expõe nome de criança. Decisão de produto do dono.
 */
import { BookOpen, Calculator } from "lucide-react";
import { useEffect } from "react";
import type { LucideIcon } from "lucide-react";
import { useParams } from "react-router-dom";

import { FundoConstela, MEDALHAS, OURO } from "../../components/FundoConstela";
import { useApi } from "../../hooks/useApi";
import { ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";

interface TopEscola { nome: string; valor: number }
interface PainelPublico { rede_nome: string; top_leitura: TopEscola[]; top_matematica: TopEscola[] }

const FONTE = "Poppins, Inter, sans-serif";

/** Uma linha de escola no ranking (pódio para top 3, barra relativa ao 1º). */
function LinhaEscola({ pos, escola, topo }: { pos: number; escola: TopEscola; topo: number }) {
  const medalha = MEDALHAS[pos];
  const top3 = pos <= 3;
  const largura = Math.max(8, (escola.valor / topo) * 100);
  return (
    <div
      className={`relative flex items-center gap-3 overflow-hidden rounded-2xl px-4 py-3 ring-1 ring-inset sm:gap-4 sm:px-5 ${
        top3 ? "bg-white/[0.09] ring-white/15" : "bg-white/[0.04] ring-white/[0.07]"}`}
      style={top3 ? { boxShadow: `inset 4px 0 0 0 ${medalha?.cor ?? OURO}` } : undefined}
    >
      <span aria-hidden className="absolute inset-y-0 left-0 -z-10 rounded-2xl opacity-[0.10]"
        style={{ width: `${largura}%`, background: medalha?.cor ?? "#6B7DE4" }} />
      <span className="flex w-9 shrink-0 items-center justify-center text-2xl sm:w-11">
        {medalha ? <span aria-label={`${pos}º lugar`}>{medalha.emoji}</span>
          : <span className="font-bold tabular-nums text-white/45">{pos}º</span>}
      </span>
      <span className="flex-1 truncate text-[clamp(1rem,1.7vw,1.4rem)] font-semibold text-white"
        style={{ fontFamily: FONTE }}>
        {escola.nome}
      </span>
      <span className="w-16 shrink-0 text-right text-[clamp(1.05rem,1.7vw,1.5rem)] font-bold tabular-nums text-white sm:w-24"
        style={top3 ? { color: medalha?.cor } : undefined}>
        {nota(escola.valor)}
      </span>
    </div>
  );
}

/** Coluna de uma matéria (Leitura/Matemática) com as 5 melhores escolas. */
function Coluna({ titulo, icone: Icone, escolas }: {
  titulo: string; icone: LucideIcon; escolas: TopEscola[];
}) {
  const topo = Math.max(...escolas.map((e) => e.valor), 0) || 1;
  return (
    <div className="flex-1 rounded-3xl bg-white/[0.05] p-5 ring-1 ring-inset ring-white/10 sm:p-6">
      <h2 className="mb-4 flex items-center justify-center gap-2.5 text-[clamp(1.2rem,2.4vw,1.9rem)] font-extrabold text-white"
        style={{ fontFamily: FONTE }}>
        <Icone className="h-7 w-7 shrink-0" style={{ color: OURO }} strokeWidth={2.3} /> {titulo}
      </h2>
      {escolas.length === 0 ? (
        <p className="py-10 text-center text-white/40">Sem dados ainda.</p>
      ) : (
        <ol className="space-y-2.5">
          {escolas.slice(0, 5).map((e, i) => (
            <LinhaEscola key={e.nome} pos={i + 1} escola={e} topo={topo} />
          ))}
        </ol>
      )}
    </div>
  );
}

function Moldura({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-[#0F1626] px-6 text-center text-white/70"
      style={{ minHeight: "100dvh" }}>
      <FundoConstela cor="#5B6EE1" />
      <div className="relative">{children}</div>
    </div>
  );
}

export default function PainelPublicoRede() {
  const { token } = useParams<{ token: string }>();
  const { dados, erro, carregando, recarregar } = useApi<PainelPublico>(
    token ? `/publico/rede/${token}` : null);

  // Telão: revalida a cada 60s (pega quando a vitrine é desligada e some).
  useEffect(() => {
    const t = window.setInterval(recarregar, 60_000);
    return () => window.clearInterval(t);
  }, [recarregar]);

  if (carregando && !dados) {
    return <Moldura><p className="flex items-center gap-3 text-lg">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-white/80" />
      Carregando a vitrine...
    </p></Moldura>;
  }
  if (erro || !dados) {
    // Transitório (rede/servidor) mostra "reconectando"; 404 = desativada.
    const transitorio = !(erro instanceof ApiError)
      || erro.status === 0 || erro.status === 408 || erro.status >= 500;
    return <Moldura><p className="text-xl">
      {transitorio ? "Reconectando à vitrine..." : "Vitrine não encontrada ou desativada."}
    </p></Moldura>;
  }

  return (
    <div className="relative min-h-screen bg-[#0F1626] px-4 py-10 text-white" style={{ minHeight: "100dvh" }}>
      <FundoConstela cor="#5B6EE1" />
      <div className="relative mx-auto max-w-5xl">
        <header className="mb-8 text-center">
          <div className="mb-3 flex items-center justify-center gap-2.5">
            <img src="/simbolo-escuro.svg" alt="Constela Edu" width={40} height={40} className="h-9 w-9" />
          </div>
          <p className="text-sm font-semibold uppercase tracking-[0.28em] text-amber-300">
            Secretaria de Educação
          </p>
          <h1 className="mt-1 text-[clamp(1.8rem,4vw,3rem)] font-extrabold text-white" style={{ fontFamily: FONTE }}>
            {dados.rede_nome}
          </h1>
          <p className="mt-2 text-white/50">As escolas em destaque da nossa rede</p>
        </header>

        <div className="flex flex-col gap-6 md:flex-row">
          <Coluna titulo="Leitura" icone={BookOpen} escolas={dados.top_leitura} />
          <Coluna titulo="Matemática" icone={Calculator} escolas={dados.top_matematica} />
        </div>

        <footer className="mt-10 flex items-center justify-center gap-2 text-center text-xs text-white/40">
          <img src="/simbolo-escuro.svg" alt="" aria-hidden width={16} height={16} className="h-4 w-4 opacity-70" />
          <span style={{ fontFamily: FONTE }}>
            constela<span className="text-amber-300">edu</span>
          </span>
          <span>· celebrando o esforço de cada escola · sem dados individuais de estudantes</span>
        </footer>
      </div>
    </div>
  );
}
