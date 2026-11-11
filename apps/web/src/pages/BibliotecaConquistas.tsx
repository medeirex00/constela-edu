/**
 * Biblioteca de Conquistas — o catálogo completo do Constela Edu.
 *
 * Lista TODAS as conquistas (inclusive as que ninguém desbloqueou e as
 * desativadas), com filtros, ordenações, painel de estatísticas e um
 * modal de detalhes com critérios claros de desbloqueio.
 *
 * Identidade visual v2 (docs/design/IDENTIDADE-VISUAL-V2.md): indicadores em
 * cartões com ícone pastel e número grande; a grade de medalhas com o emoji da
 * conquista num quadrado pastel na cor da raridade, selos de raridade e de
 * plataforma, XP em pílula âmbar e a barra do quanto da escola já desbloqueou
 * (`pct_desbloqueio`, dado real da API — só agregados, sem nome de aluno).
 * Filtros e ordenação são só apresentação, no cliente; a "Ordem padrão" é o
 * campo `ordem` do backend.
 */
import { ArrowLeft, Gem, Library, Medal, RotateCcw, Sparkles, Star, Trophy, Unlock } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  BadgeRaridade,
  ChipPlataforma,
  NOME_PLATAFORMA,
  PilulaXp,
  QuadradoEmoji,
  plural,
} from "../components/ConquistasUi";
import { MolduraPilula, estiloSelectPilula } from "../components/SeletorPilula";
import {
  BarraProgresso,
  Botao,
  Card,
  Erro,
  IconePastel,
  Modal,
  PageHeader,
  PosicaoBolinha,
  Skeleton,
  StatCard,
  Vazio,
} from "../components/ui";
import type { TomPastel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { numero } from "../lib/formato";
import { podeAbrirRota } from "../lib/rotasGuardadas";

// O selo de raridade e os nomes das plataformas moram em components/ConquistasUi;
// continuam exportados daqui para quem já os importava desta página.
export { BadgeRaridade, NOME_PLATAFORMA };

export interface ConquistaCatalogo {
  codigo: string;
  nome: string;
  icone: string;
  descricao: string;
  objetivo: string;
  indicador: string;
  limite: number;
  plataforma: string;
  xp: number;
  raridade: string;
  ordem: number;
  ativa: boolean;
  criada_em: string;
  unidade: string;
  criterio: string;
  desbloqueios: number;
  pct_desbloqueio: number;
}

interface Estatisticas {
  total: number;
  ativas: number;
  alunos: number;
  total_desbloqueios: number;
  pct_medio_conclusao: number;
  mais_rara: ResumoConquista | null;
  mais_comum: ResumoConquista | null;
  maior_xp: ResumoConquista | null;
  ranking_desbloqueios: ResumoConquista[];
}

interface ResumoConquista {
  codigo: string;
  nome: string;
  icone: string;
  xp: number;
  desbloqueios: number;
  pct_desbloqueio: number;
}

interface Biblioteca {
  conquistas: ConquistaCatalogo[];
  estatisticas: Estatisticas;
  raridades: Record<string, string>;
  indicadores: Record<string, string>;
}

/** "2026-09-01" (ou com hora) → "01/09/2026", sem passar por `Date` (fuso). */
function dataBr(iso: string): string {
  const [ano, mes, dia] = (iso ?? "").split("T")[0].split("-");
  return dia && mes && ano ? `${dia}/${mes}/${ano}` : iso;
}

/** "12,5%" — o percentual já vem calculado pelo backend (só formatação). */
function pct(valor: number): string {
  return `${valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

const ORDENACOES = [
  { valor: "padrao", rotulo: "Ordem padrão" },
  { valor: "alfabetica", rotulo: "Ordem alfabética" },
  { valor: "mais_raras", rotulo: "Mais raras primeiro" },
  { valor: "mais_comuns", rotulo: "Mais comuns primeiro" },
  { valor: "maior_xp", rotulo: "Maior XP" },
  { valor: "menor_xp", rotulo: "Menor XP" },
];

/** Cartão de indicador com o NOME de uma conquista (texto, não número). */
function CartaoConquistaDestaque({ rotulo, icone, tom, conquista, detalhe }: {
  rotulo: string; icone: LucideIcon; tom: TomPastel;
  conquista: ResumoConquista | null; detalhe: (c: ResumoConquista) => string;
}) {
  return (
    <Card className="flex flex-col p-5">
      <IconePastel icone={icone} tom={tom} />
      {conquista ? (
        <p className="mt-4 flex min-w-0 items-center gap-2 text-lg font-bold leading-tight text-zinc-900 dark:text-white">
          <span aria-hidden className="text-2xl leading-none">{conquista.icone}</span>
          <span className="truncate" title={conquista.nome}>{conquista.nome}</span>
        </p>
      ) : (
        <p className="mt-4 text-lg font-bold leading-tight text-zinc-500 dark:text-zinc-400">Nenhuma ativa</p>
      )}
      <p className="mt-2 text-sm font-medium text-zinc-700 dark:text-zinc-200">{rotulo}</p>
      {conquista && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{detalhe(conquista)}</p>}
    </Card>
  );
}

function EsqueletoIndicadores() {
  return (
    <div aria-hidden className="grid grid-cols-2 gap-3 sm:gap-5 xl:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <Card key={i} className="p-5">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <Skeleton className="mt-4 h-7 w-1/2" />
          <Skeleton className="mt-2 h-3.5 w-2/3" />
        </Card>
      ))}
    </div>
  );
}

function EsqueletoCatalogo() {
  return (
    <div aria-hidden className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }, (_, i) => (
        <Card key={i} className="p-5">
          <div className="flex items-start gap-4">
            <Skeleton className="h-14 w-14 rounded-2xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
            </div>
          </div>
          <Skeleton className="mt-5 h-2 w-full rounded-full" />
        </Card>
      ))}
    </div>
  );
}

export default function BibliotecaConquistas() {
  const { escolaId } = useApp();
  const { dados, erro, carregando, recarregar } = useApi<Biblioteca>(
    escolaId ? `/escolas/${escolaId}/gamificacao/biblioteca` : null,
  );
  // "Conquistas e Mural" (/conquistas) é tela da gestão (RotaGestao). A professora
  // chega aqui pelo próprio menu (Reconhecimento › Biblioteca de Conquistas): o
  // link de volta a mandaria, sem aviso, para a Visão geral — para ela, não aparece.
  const perfil = usePerfil();
  const { tem } = useModulos();
  const abreConquistas = podeAbrirRota("/conquistas", perfil, tem);
  const [plataforma, setPlataforma] = useState("");
  const [categoria, setCategoria] = useState("");
  const [raridade, setRaridade] = useState("");
  const [ordenacao, setOrdenacao] = useState("padrao");
  const [detalhe, setDetalhe] = useState<ConquistaCatalogo | null>(null);

  const visiveis = useMemo(() => {
    if (!dados) return [];
    let lista = dados.conquistas.filter(
      (c) =>
        (!plataforma || c.plataforma === plataforma) &&
        (!categoria || c.indicador === categoria) &&
        (!raridade || c.raridade === raridade),
    );
    const porOrdenacao: Record<string, (a: ConquistaCatalogo, b: ConquistaCatalogo) => number> = {
      padrao: (a, b) => a.ordem - b.ordem,
      alfabetica: (a, b) => a.nome.localeCompare(b.nome, "pt-BR"),
      mais_raras: (a, b) => a.pct_desbloqueio - b.pct_desbloqueio,
      mais_comuns: (a, b) => b.pct_desbloqueio - a.pct_desbloqueio,
      maior_xp: (a, b) => b.xp - a.xp,
      menor_xp: (a, b) => a.xp - b.xp,
    };
    lista = [...lista].sort(porOrdenacao[ordenacao] ?? porOrdenacao.padrao);
    return lista;
  }, [dados, plataforma, categoria, raridade, ordenacao]);

  const estatisticas = dados?.estatisticas;
  const filtrando = Boolean(plataforma || categoria || raridade);
  // Sem escola o hook não busca; com escola e sem resposta ainda, é carregamento.
  const aguardando = carregando || (escolaId != null && !dados && !erro);

  function limparFiltros() {
    setPlataforma("");
    setCategoria("");
    setRaridade("");
  }

  return (
    <div className="space-y-6">
      <div>
        {abreConquistas && (
          <Link
            to="/conquistas"
            className="mb-3 inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            <ArrowLeft size={15} aria-hidden /> Conquistas e Mural
          </Link>
        )}
        <PageHeader
          titulo="Biblioteca de Conquistas"
          descricao="Todas as medalhas do Constela Edu, com critérios claros de desbloqueio. Clique em uma conquista para ver os detalhes."
        />
      </div>

      {/* --- Painel de estatísticas --- */}
      {aguardando ? (
        <EsqueletoIndicadores />
      ) : estatisticas ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-5 xl:grid-cols-4 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2">
          <StatCard
            icone={<Medal size={20} aria-hidden />} tom="violeta"
            rotulo="Conquistas" valor={numero(estatisticas.total)}
            detalhe={`${plural(estatisticas.ativas, "ativa", "ativas")}`}
          />
          <StatCard
            icone={<Unlock size={20} aria-hidden />} tom="teal"
            rotulo="Desbloqueios" valor={numero(estatisticas.total_desbloqueios)}
            detalhe={`conclusão média ${pct(estatisticas.pct_medio_conclusao)} · ${plural(estatisticas.alunos, "aluno", "alunos")} na escola`}
          />
          <CartaoConquistaDestaque
            rotulo="Mais rara" icone={Gem} tom="rosa" conquista={estatisticas.mais_rara}
            detalhe={(c) => `${plural(c.desbloqueios, "aluno", "alunos")} · ${pct(c.pct_desbloqueio)}`}
          />
          <CartaoConquistaDestaque
            rotulo="Maior XP" icone={Star} tom="ambar" conquista={estatisticas.maior_xp}
            detalhe={(c) => `+${numero(c.xp)} XP`}
          />
        </div>
      ) : null}

      {estatisticas && estatisticas.ranking_desbloqueios.length > 0 && (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
            <IconePastel icone={Trophy} tom="ambar" tamanho="sm" />
            <h2 className="text-[15px] font-semibold text-zinc-900 dark:text-white">Mais desbloqueadas</h2>
            {estatisticas.mais_comum && (
              <span className="ml-auto text-xs text-zinc-500 dark:text-zinc-400">
                mais comum: <span aria-hidden>{estatisticas.mais_comum.icone} </span>{estatisticas.mais_comum.nome}
              </span>
            )}
          </div>
          <ol className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {estatisticas.ranking_desbloqueios.map((item, indice) => (
              <li key={item.codigo} className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1.5 px-5 py-3 text-sm sm:grid-cols-[auto_auto_minmax(0,1fr)_minmax(0,14rem)]">
                <span aria-hidden className="inline-flex"><PosicaoBolinha posicao={indice + 1} /></span>
                <span className="sr-only">{indice + 1}º</span>
                <QuadradoEmoji emoji={item.icone} tamanho="sm" />
                <span className="min-w-0 truncate font-semibold text-zinc-900 dark:text-white" title={item.nome}>{item.nome}</span>
                <span className="col-span-3 flex items-center gap-3 sm:col-span-1">
                  <BarraProgresso valor={item.pct_desbloqueio} tom="ambar" />
                  <span className="shrink-0 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                    {plural(item.desbloqueios, "aluno", "alunos")} · {pct(item.pct_desbloqueio)}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {/* --- Filtros --- */}
      <Card className="flex flex-wrap items-center gap-3 p-3 sm:p-4">
        <MolduraPilula icone={Library}>
          <select aria-label="Filtrar por plataforma" className={estiloSelectPilula} value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
            <option value="">Todas as plataformas</option>
            {/* Módulo fora do plano da rede não aparece nem como filtro (o servidor
                já não manda as conquistas dele). */}
            {tem("leitura") && <option value="elefante">Elefante Letrado</option>}
            {tem("matematica") && <option value="matific">Matific</option>}
            <option value="geral">Geral</option>
          </select>
        </MolduraPilula>
        <MolduraPilula icone={Sparkles}>
          <select aria-label="Filtrar por categoria" className={estiloSelectPilula} value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            <option value="">Todas as categorias</option>
            {Object.entries(dados?.indicadores ?? {}).map(([chave, rotulo]) => (
              <option key={chave} value={chave}>{rotulo}</option>
            ))}
          </select>
        </MolduraPilula>
        <MolduraPilula icone={Gem}>
          <select aria-label="Filtrar por raridade" className={estiloSelectPilula} value={raridade} onChange={(e) => setRaridade(e.target.value)}>
            <option value="">Todas as raridades</option>
            {Object.entries(dados?.raridades ?? {}).map(([chave, rotulo]) => (
              <option key={chave} value={chave}>{rotulo}</option>
            ))}
          </select>
        </MolduraPilula>
        <MolduraPilula icone={Trophy}>
          <select aria-label="Ordenar" className={estiloSelectPilula} value={ordenacao} onChange={(e) => setOrdenacao(e.target.value)}>
            {ORDENACOES.map((o) => (
              <option key={o.valor} value={o.valor}>{o.rotulo}</option>
            ))}
          </select>
        </MolduraPilula>
        {filtrando && (
          <Botao variante="fantasma" tamanho="sm" onClick={limparFiltros}>
            <RotateCcw size={13} aria-hidden /> Limpar filtros
          </Botao>
        )}
        {dados && (
          <p role="status" className="ml-auto text-sm font-medium text-zinc-500 dark:text-zinc-400">
            {plural(visiveis.length, "conquista", "conquistas")}
          </p>
        )}
      </Card>

      {/* --- Catálogo --- */}
      {aguardando ? (
        <EsqueletoCatalogo />
      ) : erro ? (
        <Card className="p-6">
          <Erro descricao={erro.message} aoTentar={recarregar} />
        </Card>
      ) : visiveis.length === 0 ? (
        <Card className="p-6">
          <Vazio
            icone={Medal}
            titulo={filtrando ? "Nenhuma conquista com esses filtros" : "Nenhuma conquista cadastrada"}
            descricao={filtrando ? "Ajuste os filtros acima." : undefined}
            acao={filtrando ? <Botao variante="secundario" onClick={limparFiltros}>Limpar filtros</Botao> : undefined}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {visiveis.map((conquista) => (
            <button
              key={conquista.codigo}
              type="button"
              aria-haspopup="dialog"
              className={`card group flex flex-col p-5 text-left transition-shadow hover:shadow-flutuante ${
                conquista.ativa ? "" : "bg-zinc-50 dark:bg-zinc-900/60"
              }`}
              onClick={() => setDetalhe(conquista)}
            >
              <div className="flex items-start gap-4">
                <QuadradoEmoji
                  emoji={conquista.icone} raridade={conquista.ativa ? conquista.raridade : "comum"} tamanho="lg"
                  className={conquista.ativa ? "transition-transform group-hover:scale-105 motion-reduce:transition-none" : "grayscale"}
                />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold leading-snug text-zinc-900 dark:text-white">{conquista.nome}</p>
                  <p className="mt-0.5 line-clamp-2 text-sm text-zinc-500 dark:text-zinc-400">{conquista.descricao}</p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-1.5">
                <BadgeRaridade raridade={conquista.raridade} rotulo={dados?.raridades[conquista.raridade]} />
                <ChipPlataforma plataforma={conquista.plataforma} />
                <PilulaXp>+{numero(conquista.xp)} XP</PilulaXp>
                {!conquista.ativa && (
                  <span className="inline-flex items-center rounded-full bg-zinc-200 px-2.5 py-0.5 text-xs font-semibold text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200">
                    Desativada
                  </span>
                )}
              </div>
              <div className="mt-auto pt-4">
                <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
                  <span className="text-zinc-500 dark:text-zinc-400">Já desbloquearam</span>
                  <span className="font-semibold tabular-nums text-zinc-700 dark:text-zinc-200">
                    {plural(conquista.desbloqueios, "aluno", "alunos")} · {pct(conquista.pct_desbloqueio)}
                  </span>
                </div>
                <BarraProgresso
                  valor={conquista.pct_desbloqueio}
                  tom={conquista.plataforma === "matific" ? "teal" : conquista.plataforma === "elefante" ? "violeta" : "ambar"}
                />
              </div>
            </button>
          ))}
        </div>
      )}

      {/* --- Modal de detalhes --- */}
      <Modal
        titulo={detalhe ? detalhe.nome : ""}
        aberto={detalhe !== null}
        aoFechar={() => setDetalhe(null)}
      >
        {detalhe && (
          <div className="space-y-4 text-sm">
            <div className="flex items-start gap-4">
              <QuadradoEmoji emoji={detalhe.icone} raridade={detalhe.raridade} tamanho="xl" />
              <div className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <BadgeRaridade raridade={detalhe.raridade} rotulo={dados?.raridades[detalhe.raridade]} />
                  <ChipPlataforma plataforma={detalhe.plataforma} />
                  <PilulaXp>+{numero(detalhe.xp)} XP</PilulaXp>
                  {!detalhe.ativa && (
                    <span className="inline-flex items-center rounded-full bg-zinc-200 px-2.5 py-0.5 text-xs font-semibold text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200">
                      Desativada
                    </span>
                  )}
                </div>
                {detalhe.descricao && <p className="text-zinc-600 dark:text-zinc-300">{detalhe.descricao}</p>}
              </div>
            </div>
            {detalhe.objetivo && (
              <p className="flex items-start gap-2 text-zinc-600 dark:text-zinc-300">
                <Sparkles size={14} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
                <span><span className="font-semibold text-zinc-800 dark:text-zinc-100">Objetivo:</span> {detalhe.objetivo}</span>
              </p>
            )}
            <div className="rounded-2xl bg-indigo-50 p-4 ring-1 ring-indigo-100 dark:bg-indigo-500/10 dark:ring-indigo-500/20">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-indigo-700 dark:text-indigo-300">
                Critério de desbloqueio
              </p>
              <p className="mt-1 text-[15px] font-semibold text-indigo-900 dark:text-indigo-100">{detalhe.criterio}</p>
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
                <span className="text-zinc-500 dark:text-zinc-400">Quanto da escola já desbloqueou</span>
                <span className="font-semibold tabular-nums text-zinc-700 dark:text-zinc-200">{pct(detalhe.pct_desbloqueio)}</span>
              </div>
              <BarraProgresso valor={detalhe.pct_desbloqueio} tom="ambar" />
            </div>
            <dl className="divide-y divide-zinc-100 rounded-2xl border border-zinc-100 dark:divide-zinc-800 dark:border-zinc-800">
              {[
                ["Alunos que já desbloquearam", `${detalhe.desbloqueios} (${pct(detalhe.pct_desbloqueio)} da escola)`],
                ["Criada em", dataBr(detalhe.criada_em)],
                ["Situação", detalhe.ativa ? "Ativa" : "Desativada"],
              ].map(([rotulo, valor]) => (
                <div key={rotulo} className="flex justify-between gap-4 px-4 py-2.5">
                  <dt className="text-zinc-500 dark:text-zinc-400">{rotulo}</dt>
                  <dd className="text-right font-semibold text-zinc-800 dark:text-zinc-100">{valor}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </Modal>
    </div>
  );
}
