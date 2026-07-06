/**
 * 🏅 Biblioteca de Conquistas — o catálogo completo do Constela Edu.
 *
 * Lista TODAS as conquistas (inclusive as que ninguém desbloqueou e as
 * desativadas), com filtros, ordenações, painel de estatísticas e um
 * modal de detalhes com critérios claros de desbloqueio.
 */
import { ArrowLeft, Medal, Sparkles, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Card, Carregando, Modal, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { numero } from "../lib/formato";

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

export const NOME_PLATAFORMA: Record<string, string> = {
  elefante: "Elefante Letrado",
  matific: "Matific",
  geral: "Geral",
};

export function BadgeRaridade({ raridade, rotulo }: { raridade: string; rotulo?: string }) {
  const estilos: Record<string, string> = {
    comum: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
    rara: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
    epica: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
    lendaria: "bg-fuchsia-50 text-fuchsia-700 dark:bg-fuchsia-500/10 dark:text-fuchsia-300",
  };
  const nomes: Record<string, string> = {
    comum: "Comum", rara: "Rara", epica: "Épica", lendaria: "Lendária",
  };
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${estilos[raridade] ?? estilos.comum}`}>
      {rotulo ?? nomes[raridade] ?? raridade}
    </span>
  );
}

function dataBr(iso: string): string {
  const [ano, mes, dia] = iso.split("-");
  return dia && mes && ano ? `${dia}/${mes}/${ano}` : iso;
}

const ORDENACOES = [
  { valor: "padrao", rotulo: "Ordem padrão" },
  { valor: "alfabetica", rotulo: "Ordem alfabética" },
  { valor: "mais_raras", rotulo: "Mais raras primeiro" },
  { valor: "mais_comuns", rotulo: "Mais comuns primeiro" },
  { valor: "maior_xp", rotulo: "Maior XP" },
  { valor: "menor_xp", rotulo: "Menor XP" },
];

export default function BibliotecaConquistas() {
  const { escolaId } = useApp();
  const [dados, setDados] = useState<Biblioteca | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [plataforma, setPlataforma] = useState("");
  const [categoria, setCategoria] = useState("");
  const [raridade, setRaridade] = useState("");
  const [ordenacao, setOrdenacao] = useState("padrao");
  const [detalhe, setDetalhe] = useState<ConquistaCatalogo | null>(null);

  useEffect(() => {
    if (!escolaId) return;
    setCarregando(true);
    api<Biblioteca>(`/escolas/${escolaId}/gamificacao/biblioteca`)
      .then(setDados)
      .catch(() => setDados(null))
      .finally(() => setCarregando(false));
  }, [escolaId]);

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

  const estiloFiltro =
    "rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";

  const estatisticas = dados?.estatisticas;

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/conquistas"
          className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
        >
          <ArrowLeft size={15} /> Conquistas e Mural
        </Link>
        <PageHeader
          titulo="🏅 Biblioteca de Conquistas"
          descricao="Todas as medalhas do Constela Edu, com critérios claros de desbloqueio. Clique em uma conquista para ver os detalhes."
        />
      </div>

      {/* --- Painel de estatísticas --- */}
      {estatisticas && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Card className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Conquistas</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{estatisticas.total}</p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{estatisticas.ativas} ativas</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Desbloqueios</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{numero(estatisticas.total_desbloqueios)}</p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              conclusão média {estatisticas.pct_medio_conclusao}%
            </p>
          </Card>
          <Card className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Mais rara</p>
            {estatisticas.mais_rara ? (
              <>
                <p className="mt-1 truncate text-sm font-semibold">
                  {estatisticas.mais_rara.icone} {estatisticas.mais_rara.nome}
                </p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {estatisticas.mais_rara.desbloqueios} aluno(s) · {estatisticas.mais_rara.pct_desbloqueio}%
                </p>
              </>
            ) : (
              <p className="mt-1 text-sm text-zinc-400">—</p>
            )}
          </Card>
          <Card className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Maior XP</p>
            {estatisticas.maior_xp ? (
              <>
                <p className="mt-1 truncate text-sm font-semibold">
                  {estatisticas.maior_xp.icone} {estatisticas.maior_xp.nome}
                </p>
                <p className="text-xs text-amber-600 dark:text-amber-400">+{numero(estatisticas.maior_xp.xp)} XP</p>
              </>
            ) : (
              <p className="mt-1 text-sm text-zinc-400">—</p>
            )}
          </Card>
        </div>
      )}

      {estatisticas && estatisticas.ranking_desbloqueios.length > 0 && (
        <Card>
          <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <Trophy size={15} className="text-amber-500" />
            <h3 className="text-sm font-semibold">Mais desbloqueadas</h3>
            {estatisticas.mais_comum && (
              <span className="ml-auto text-xs text-zinc-500 dark:text-zinc-400">
                mais comum: {estatisticas.mais_comum.icone} {estatisticas.mais_comum.nome}
              </span>
            )}
          </div>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {estatisticas.ranking_desbloqueios.map((item, indice) => (
              <li key={item.codigo} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className="w-6 text-zinc-400">{indice + 1}º</span>
                <span className="text-lg leading-none">{item.icone}</span>
                <span className="font-medium">{item.nome}</span>
                <span className="ml-auto tabular-nums text-zinc-500 dark:text-zinc-400">
                  {item.desbloqueios} aluno(s) · {item.pct_desbloqueio}%
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* --- Filtros --- */}
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Filtrar por plataforma" className={estiloFiltro} value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
          <option value="">Todas as plataformas</option>
          <option value="elefante">Elefante Letrado</option>
          <option value="matific">Matific</option>
          <option value="geral">Geral</option>
        </select>
        <select aria-label="Filtrar por categoria" className={estiloFiltro} value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          <option value="">Todas as categorias</option>
          {Object.entries(dados?.indicadores ?? {}).map(([chave, rotulo]) => (
            <option key={chave} value={chave}>{rotulo}</option>
          ))}
        </select>
        <select aria-label="Filtrar por raridade" className={estiloFiltro} value={raridade} onChange={(e) => setRaridade(e.target.value)}>
          <option value="">Todas as raridades</option>
          {Object.entries(dados?.raridades ?? {}).map(([chave, rotulo]) => (
            <option key={chave} value={chave}>{rotulo}</option>
          ))}
        </select>
        <select aria-label="Ordenar" className={estiloFiltro} value={ordenacao} onChange={(e) => setOrdenacao(e.target.value)}>
          {ORDENACOES.map((o) => (
            <option key={o.valor} value={o.valor}>{o.rotulo}</option>
          ))}
        </select>
      </div>

      {/* --- Catálogo --- */}
      {carregando ? (
        <Carregando />
      ) : visiveis.length === 0 ? (
        <Vazio titulo="Nenhuma conquista com esses filtros" descricao="Ajuste os filtros acima." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visiveis.map((conquista) => (
            <button
              key={conquista.codigo}
              className={`card p-4 text-left transition-shadow hover:shadow-md ${conquista.ativa ? "" : "opacity-50"}`}
              onClick={() => setDetalhe(conquista)}
            >
              <div className="flex items-start gap-3">
                <span className="text-3xl leading-none">{conquista.icone}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate font-semibold">{conquista.nome}</p>
                    <BadgeRaridade raridade={conquista.raridade} rotulo={dados?.raridades[conquista.raridade]} />
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">{conquista.descricao}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-semibold text-amber-600 dark:text-amber-400">+{numero(conquista.xp)} XP</span>
                    <span className="text-zinc-400">·</span>
                    <span className="text-zinc-500 dark:text-zinc-400">{NOME_PLATAFORMA[conquista.plataforma] ?? conquista.plataforma}</span>
                    <span className="ml-auto tabular-nums text-zinc-500 dark:text-zinc-400">
                      <Medal size={12} className="mr-0.5 inline" />
                      {conquista.desbloqueios} ({conquista.pct_desbloqueio}%)
                    </span>
                  </div>
                  {!conquista.ativa && <Badge tom="alerta">desativada</Badge>}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* --- Modal de detalhes --- */}
      <Modal
        titulo={detalhe ? `${detalhe.icone} ${detalhe.nome}` : ""}
        aberto={detalhe !== null}
        aoFechar={() => setDetalhe(null)}
      >
        {detalhe && (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <BadgeRaridade raridade={detalhe.raridade} rotulo={dados?.raridades[detalhe.raridade]} />
              <Badge tom="destaque">{NOME_PLATAFORMA[detalhe.plataforma] ?? detalhe.plataforma}</Badge>
              <span className="font-semibold text-amber-600 dark:text-amber-400">+{numero(detalhe.xp)} XP</span>
              {!detalhe.ativa && <Badge tom="alerta">desativada</Badge>}
            </div>
            {detalhe.descricao && <p className="text-zinc-600 dark:text-zinc-300">{detalhe.descricao}</p>}
            {detalhe.objetivo && (
              <p className="flex items-start gap-2 text-zinc-500 dark:text-zinc-400">
                <Sparkles size={14} className="mt-0.5 shrink-0 text-indigo-500" />
                <span><span className="font-medium text-zinc-700 dark:text-zinc-200">Objetivo:</span> {detalhe.objetivo}</span>
              </p>
            )}
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 dark:border-indigo-500/20 dark:bg-indigo-500/10">
              <p className="text-xs font-medium uppercase tracking-wide text-indigo-700 dark:text-indigo-300">
                Critério de desbloqueio
              </p>
              <p className="mt-1 font-medium text-indigo-900 dark:text-indigo-100">{detalhe.criterio}</p>
            </div>
            <dl className="space-y-1.5">
              {[
                ["Alunos que já desbloquearam", `${detalhe.desbloqueios} (${detalhe.pct_desbloqueio}% da escola)`],
                ["Criada em", dataBr(detalhe.criada_em)],
                ["Situação", detalhe.ativa ? "Ativa" : "Desativada"],
              ].map(([rotulo, valor]) => (
                <div key={rotulo} className="flex justify-between gap-4">
                  <dt className="text-zinc-500 dark:text-zinc-400">{rotulo}</dt>
                  <dd className="text-right font-medium">{valor}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </Modal>
    </div>
  );
}
