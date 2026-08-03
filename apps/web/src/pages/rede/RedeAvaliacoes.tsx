/**
 * Avaliações externas da rede (Secretaria): cruzar indicadores oficiais (SAEB/
 * IDEB/...) com o engajamento nas plataformas + importar os arquivos oficiais.
 *
 * Duas partes: (1) CORRELAÇÃO/EVOLUÇÃO — dispersão engajamento × avaliação por
 * escola, correlação de Pearson e a evolução histórica, SEM afirmar causalidade;
 * (2) IMPORTAÇÃO — upload do arquivo oficial → mapear colunas → conferir → gravar
 * (casa por código INEP). Só dados agregados por escola.
 */
import {
  AlertTriangle,
  Bot,
  Clock,
  FileUp,
  Info,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  PageHeader,
  Vazio,
  estiloInput,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useAncora } from "../../hooks/useAncora";
import { useApi } from "../../hooks/useApi";
import { ApiError, api, apiUpload } from "../../lib/api";
import { nota } from "../../lib/formato";

interface SerieOpcao {
  avaliacao: string; nome: string; tipo: string; indicador: string;
  etapa: string | null; componente: string | null; edicoes: number[];
}
interface PontoCorr { escola_id: number; nome: string; x: number; y: number }
interface EvolPonto { edicao: number; media_valor: number; escolas: number }
interface Correlacao {
  nome: string; tipo: string; indicador: string; etapa: string | null;
  componente: string | null; edicao: number; metrica: string;
  pontos: PontoCorr[]; n: number; pearson: number | null; evolucao: EvolPonto[];
}
interface CatalogoItem { chave: string; nome: string; tipo: string; descricao: string | null }
interface Analise { linhas_lidas: number; n_colunas: number; primeiras_linhas: string[][] }
interface Mapeamento {
  linha_dados: number; col_inep: number; col_valor: number;
  col_etapa?: number | null; col_componente?: number | null; col_turma?: number | null;
  etapa_fixa?: string | null; componente_fixo?: string | null;
}
interface Fonte {
  id: number; avaliacao: string; avaliacao_nome: string | null; nome: string;
  url: string; edicao: number; indicador: string; unidade: string;
  cadencia: string; ativo: boolean; mapeamento: Mapeamento;
  ultima_coleta: string | null; proxima_coleta: string | null;
  ultimo_status: string; ultimo_erro: string | null;
  ultimo_resumo: Record<string, unknown> | null;
}

const METRICAS: Record<string, string> = {
  media_geral: "Média geral (engajamento)",
  adocao: "Adoção (%)",
};
const rotuloSerie = (s: SerieOpcao) =>
  [s.nome, s.indicador, s.etapa, s.componente].filter(Boolean).join(" · ");

// --- Gráficos SVG (sem dependência externa) ---------------------------------

function Dispersao({ pontos, rotuloX, rotuloY }: {
  pontos: PontoCorr[]; rotuloX: string; rotuloY: string;
}) {
  const W = 460, H = 300, m = { l: 44, r: 16, t: 12, b: 36 };
  if (pontos.length === 0) {
    return <p className="py-10 text-center text-sm text-zinc-500">Sem escolas com os dois dados.</p>;
  }
  const xs = pontos.map((p) => p.x), ys = pontos.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const px = (x: number) => m.l + (maxX === minX ? 0.5 : (x - minX) / (maxX - minX)) * (W - m.l - m.r);
  const py = (y: number) => H - m.b - (maxY === minY ? 0.5 : (y - minY) / (maxY - minY)) * (H - m.t - m.b);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Dispersão engajamento × avaliação">
      <line x1={m.l} y1={H - m.b} x2={W - m.r} y2={H - m.b} stroke="currentColor" className="text-zinc-300 dark:text-zinc-700" />
      <line x1={m.l} y1={m.t} x2={m.l} y2={H - m.b} stroke="currentColor" className="text-zinc-300 dark:text-zinc-700" />
      {pontos.map((p) => (
        <g key={p.escola_id}>
          <circle cx={px(p.x)} cy={py(p.y)} r={5} className="fill-indigo-500/80" />
          <title>{p.nome}: engajamento {nota(p.x)} · avaliação {p.y}</title>
        </g>
      ))}
      <text x={(W) / 2} y={H - 6} textAnchor="middle" className="fill-zinc-500 text-[11px]">{rotuloX} →</text>
      <text x={12} y={H / 2} textAnchor="middle" transform={`rotate(-90 12 ${H / 2})`} className="fill-zinc-500 text-[11px]">{rotuloY} →</text>
      <text x={m.l} y={H - m.b + 14} className="fill-zinc-400 text-[10px]">{nota(minX)}</text>
      <text x={W - m.r} y={H - m.b + 14} textAnchor="end" className="fill-zinc-400 text-[10px]">{nota(maxX)}</text>
      <text x={m.l - 6} y={H - m.b} textAnchor="end" className="fill-zinc-400 text-[10px]">{minY}</text>
      <text x={m.l - 6} y={m.t + 8} textAnchor="end" className="fill-zinc-400 text-[10px]">{maxY}</text>
    </svg>
  );
}

function Evolucao({ pontos }: { pontos: EvolPonto[] }) {
  const W = 460, H = 150, m = { l: 40, r: 16, t: 12, b: 26 };
  if (pontos.length < 2) {
    return <p className="py-6 text-center text-sm text-zinc-500">
      Só uma edição importada — a evolução aparece quando houver duas ou mais.</p>;
  }
  const es = pontos.map((p) => p.edicao), vs = pontos.map((p) => p.media_valor);
  const minE = Math.min(...es), maxE = Math.max(...es);
  const minV = Math.min(...vs), maxV = Math.max(...vs);
  const px = (e: number) => m.l + (maxE === minE ? 0.5 : (e - minE) / (maxE - minE)) * (W - m.l - m.r);
  const py = (v: number) => H - m.b - (maxV === minV ? 0.5 : (v - minV) / (maxV - minV)) * (H - m.t - m.b);
  const d = pontos.map((p, i) => `${i ? "L" : "M"}${px(p.edicao)},${py(p.media_valor)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Evolução histórica">
      <path d={d} fill="none" className="stroke-emerald-500" strokeWidth={2} />
      {pontos.map((p) => (
        <g key={p.edicao}>
          <circle cx={px(p.edicao)} cy={py(p.media_valor)} r={4} className="fill-emerald-500" />
          <text x={px(p.edicao)} y={H - 8} textAnchor="middle" className="fill-zinc-500 text-[10px]">{p.edicao}</text>
          <text x={px(p.edicao)} y={py(p.media_valor) - 8} textAnchor="middle" className="fill-zinc-500 text-[10px]">{p.media_valor}</text>
        </g>
      ))}
    </svg>
  );
}

function forcaPearson(r: number): string {
  const a = Math.abs(r);
  const nivel = a >= 0.7 ? "forte" : a >= 0.4 ? "moderada" : a >= 0.2 ? "fraca" : "desprezível";
  return `${nivel} ${r >= 0 ? "positiva" : "negativa"}`;
}

// --- Correlação --------------------------------------------------------------

function Correlacao({ redeId, opcoes, podeImportar, aoRemover }: {
  redeId: number; opcoes: SerieOpcao[]; podeImportar: boolean; aoRemover: () => void;
}) {
  const [idx, setIdx] = useState(0);
  const [edicao, setEdicao] = useState<number | null>(null);
  const [metrica, setMetrica] = useState("media_geral");
  const [removendo, setRemovendo] = useState(false);
  const [msgRemover, setMsgRemover] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const serie = opcoes[idx];
  const ed = edicao ?? serie?.edicoes[0] ?? null;

  const url = serie && ed != null
    ? `/redes/${redeId}/avaliacoes/correlacao?avaliacao=${serie.avaliacao}`
      + `&indicador=${encodeURIComponent(serie.indicador)}&edicao=${ed}&metrica=${metrica}`
      + (serie.etapa ? `&etapa=${encodeURIComponent(serie.etapa)}` : "")
      + (serie.componente ? `&componente=${encodeURIComponent(serie.componente)}` : "")
    : null;
  const { dados, carregando, erro } = useApi<Correlacao>(url);
  // Item "Evolução da Rede" do menu da Secretaria aponta para /rede/avaliacoes#evolucao.
  useAncora(dados);

  async function removerSerie() {
    if (!serie || ed == null) return;
    if (!window.confirm(
      `Remover os resultados de “${rotuloSerie(serie)} · edição ${ed}”? `
      + "Apaga só ESTA série (não afeta outras edições, etapas nem componentes). "
      + "Use para desfazer uma importação errada.")) return;
    setRemovendo(true); setMsgRemover(null);
    try {
      // Identifica a série EXATA (com etapa/componente) — não apaga as irmãs.
      const qs = new URLSearchParams({
        avaliacao: serie.avaliacao, edicao: String(ed), indicador: serie.indicador,
      });
      if (serie.etapa) qs.set("etapa", serie.etapa);
      if (serie.componente) qs.set("componente", serie.componente);
      const r = await api<{ removidos: number }>(
        `/avaliacoes/resultados?${qs.toString()}`, { method: "DELETE" });
      setMsgRemover({ tipo: "ok", texto: `${r.removidos} resultado(s) removido(s) da edição ${ed}.` });
      setEdicao(null);
      aoRemover();
    } catch (e) {
      setMsgRemover({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível remover." });
    } finally { setRemovendo(false); }
  }

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-end gap-3">
        <Campo rotulo="Avaliação / indicador">
          <select className={estiloInput} value={idx}
                  onChange={(e) => { setIdx(Number(e.target.value)); setEdicao(null); }}>
            {opcoes.map((s, i) => <option key={i} value={i}>{rotuloSerie(s)}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Edição">
          <select className={estiloInput} value={ed ?? ""} onChange={(e) => setEdicao(Number(e.target.value))}>
            {serie?.edicoes.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Engajamento">
          <select className={estiloInput} value={metrica} onChange={(e) => setMetrica(e.target.value)}>
            {Object.entries(METRICAS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Campo>
        {podeImportar && serie && ed != null && (
          <button onClick={removerSerie} disabled={removendo}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-500/30 dark:hover:bg-red-500/10"
                  title="Remover os resultados desta edição (desfazer importação errada)">
            <Trash2 size={14} /> {removendo ? "Removendo..." : `Remover edição ${ed}`}
          </button>
        )}
      </div>
      {msgRemover && <Mensagem tipo={msgRemover.tipo}>{msgRemover.texto}</Mensagem>}

      {erro && !dados && <Mensagem tipo="erro">{erro.message}</Mensagem>}
      {carregando && !dados ? <Carregando /> : dados && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <h3 className="mb-1 text-sm font-semibold">Dispersão por escola</h3>
              <p className="mb-2 text-xs text-zinc-500">
                Cada ponto é uma escola: {METRICAS[dados.metrica]} (horizontal) × {dados.nome} (vertical).
              </p>
              <Dispersao pontos={dados.pontos} rotuloX={METRICAS[dados.metrica]} rotuloY={dados.nome} />
            </div>
            <div id="evolucao" className="scroll-mt-24">
              <h3 className="mb-1 text-sm font-semibold">Evolução da rede (média por edição)</h3>
              <p className="mb-2 text-xs text-zinc-500">Média das escolas em {dados.nome}.</p>
              <Evolucao pontos={dados.evolucao} />
            </div>
          </div>

          <div className="rounded-lg bg-zinc-50 p-3 text-sm dark:bg-zinc-800/50">
            {dados.pearson != null ? (
              <p>
                Correlação (Pearson) entre engajamento e {dados.nome}:{" "}
                <b className="tabular-nums">{dados.pearson}</b>{" "}
                <span className="text-zinc-500">— {forcaPearson(dados.pearson)}, com {dados.n} escola(s)</span>.
              </p>
            ) : (
              <p className="text-zinc-500">
                Dados insuficientes para calcular a correlação (precisa de ao menos 3 escolas
                com os dois dados e alguma variação).
              </p>
            )}
            <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>
                <b>Correlação não é causalidade.</b> O gráfico mostra que os indicadores caminham
                juntos — não que o uso das plataformas causou o resultado oficial (ou o contrário).
                As avaliações oficiais têm defasagem (bienais/anuais) e medem só o nível da escola.
              </span>
            </p>
          </div>
        </>
      )}
    </Card>
  );
}

// --- Importação --------------------------------------------------------------

const PRESETS: Record<string, { indicador: string; unidade: string }> = {
  ideb: { indicador: "ideb", unidade: "indice" },
  saeb: { indicador: "proficiencia", unidade: "escala_saeb" },
  saresp: { indicador: "proficiencia", unidade: "escala_saresp" },
  crianca_alfabetizada: { indicador: "proficiencia", unidade: "pontos" },
};

function ImportarAvaliacao({ catalogo, aoImportar, ehGlobal, aoSalvarFonte }: {
  catalogo: CatalogoItem[]; aoImportar: () => void;
  ehGlobal: boolean; aoSalvarFonte?: () => void;
}) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [analise, setAnalise] = useState<Analise | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // Robô (só admin global): salvar o MESMO mapeamento como fonte de coleta.
  const [urlFonte, setUrlFonte] = useState("");
  const [cadencia, setCadencia] = useState("mensal");
  const [salvandoFonte, setSalvandoFonte] = useState(false);
  const [msgFonte, setMsgFonte] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  const [avaliacao, setAvaliacao] = useState("ideb");
  const [edicao, setEdicao] = useState(new Date().getFullYear() - 1);
  const [linhaDados, setLinhaDados] = useState(1);
  const [colInep, setColInep] = useState(0);
  const [colValor, setColValor] = useState(1);
  const [colEtapa, setColEtapa] = useState<number | "">("");
  const [colComp, setColComp] = useState<number | "">("");
  const [etapaFixa, setEtapaFixa] = useState("");
  const [compFixo, setCompFixo] = useState("");
  const preset = PRESETS[avaliacao] ?? { indicador: "", unidade: "" };
  const [indicador, setIndicador] = useState(preset.indicador);
  const [unidade, setUnidade] = useState(preset.unidade);

  const cols = analise ? Array.from({ length: analise.n_colunas }, (_, i) => i) : [];

  async function analisar(f: File) {
    setOcupado(true); setMsg(null); setAnalise(null);
    try {
      const fd = new FormData(); fd.append("arquivo", f);
      const a = await apiUpload<Analise>("/avaliacoes/analisar", fd);
      setAnalise(a);
      setArquivo(f);
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível ler o arquivo." });
    } finally { setOcupado(false); }
  }

  function trocarAvaliacao(chave: string) {
    setAvaliacao(chave);
    const p = PRESETS[chave] ?? { indicador: "", unidade: "" };
    setIndicador(p.indicador); setUnidade(p.unidade);
  }

  async function importar() {
    if (!arquivo) return;
    setOcupado(true); setMsg(null);
    try {
      const fd = new FormData();
      fd.append("arquivo", arquivo);
      fd.append("avaliacao", avaliacao);
      fd.append("edicao", String(edicao));
      fd.append("indicador", indicador.trim());
      fd.append("unidade", unidade.trim());
      fd.append("linha_dados", String(linhaDados));
      fd.append("col_inep", String(colInep));
      fd.append("col_valor", String(colValor));
      if (colEtapa !== "") fd.append("col_etapa", String(colEtapa));
      if (colComp !== "") fd.append("col_componente", String(colComp));
      if (etapaFixa.trim()) fd.append("etapa_fixa", etapaFixa.trim());
      if (compFixo.trim()) fd.append("componente_fixo", compFixo.trim());
      const r = await apiUpload<{ casados: number; inseridos: number; atualizados: number; nao_casados: number; ignorados: number }>(
        "/avaliacoes/importar", fd);
      setMsg({
        tipo: r.casados > 0 ? "ok" : "erro",
        texto: `${r.casados} escola(s) casada(s) por INEP — ${r.inseridos} nova(s), ${r.atualizados} atualizada(s)`
          + `; ${r.nao_casados} sem escola, ${r.ignorados} linha(s) ignorada(s).`,
      });
      aoImportar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha ao importar." });
    } finally { setOcupado(false); }
  }

  async function salvarFonte() {
    setSalvandoFonte(true); setMsgFonte(null);
    try {
      const mapeamento: Mapeamento = {
        linha_dados: linhaDados, col_inep: colInep, col_valor: colValor,
        col_etapa: colEtapa === "" ? null : Number(colEtapa),
        col_componente: colComp === "" ? null : Number(colComp),
        etapa_fixa: etapaFixa.trim() || null,
        componente_fixo: compFixo.trim() || null,
      };
      await api<Fonte>("/avaliacoes/fontes", {
        method: "POST",
        body: JSON.stringify({
          avaliacao, nome: `${catalogo.find((c) => c.chave === avaliacao)?.nome ?? avaliacao} ${edicao}`,
          url: urlFonte.trim(), edicao, indicador: indicador.trim(), unidade: unidade.trim(),
          cadencia, mapeamento,
        }),
      });
      setMsgFonte({ tipo: "ok", texto: "Fonte salva. O robô passa a baixar e importar sozinho." });
      setUrlFonte("");
      aoSalvarFonte?.();
    } catch (e) {
      setMsgFonte({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha ao salvar a fonte." });
    } finally { setSalvandoFonte(false); }
  }

  return (
    <Card className="space-y-4 p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <FileUp size={16} className="text-indigo-600" /> Importar resultado oficial
      </h2>
      <p className="text-xs text-zinc-500">
        Suba o arquivo oficial (XLSX, CSV ou o ZIP) do INEP/SEDUC. O sistema mostra as primeiras linhas;
        você escolhe a linha onde começam os dados e qual coluna é o código INEP e o valor.
        O casamento com as escolas é pelo <b>código INEP</b>.
      </p>

      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-zinc-300 px-4 py-2 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800">
        <Upload size={15} /> {arquivo ? arquivo.name : "Escolher arquivo..."}
        <input type="file" accept=".xlsx,.xls,.csv,.zip" className="hidden"
               onChange={(e) => { const f = e.target.files?.[0]; if (f) analisar(f); }} />
      </label>

      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}

      {analise && (
        <>
          <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-zinc-100 dark:bg-zinc-800">
                  {cols.map((c) => <th key={c} className="px-2 py-1 font-mono text-zinc-500">col {c}</th>)}
                </tr>
              </thead>
              <tbody>
                {analise.primeiras_linhas.slice(0, 8).map((linha, i) => (
                  <tr key={i} className={i + 1 === linhaDados ? "bg-indigo-50 dark:bg-indigo-500/10" : ""}>
                    {cols.map((c) => (
                      <td key={c} className="whitespace-nowrap border-t border-zinc-100 px-2 py-1 dark:border-zinc-800/60">
                        {linha[c] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-zinc-500">
            A linha destacada é a <b>primeira linha de dados</b> (índice {linhaDados}). Ajuste abaixo.
          </p>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Campo rotulo="Avaliação">
              <select className={estiloInput} value={avaliacao} onChange={(e) => trocarAvaliacao(e.target.value)}>
                {catalogo.map((a) => <option key={a.chave} value={a.chave}>{a.nome}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Edição (ano)">
              <input type="number" className={estiloInput} value={edicao} onChange={(e) => setEdicao(Number(e.target.value))} />
            </Campo>
            <Campo rotulo="Indicador">
              <input className={estiloInput} value={indicador} onChange={(e) => setIndicador(e.target.value)} />
            </Campo>
            <Campo rotulo="Unidade">
              <input className={estiloInput} value={unidade} onChange={(e) => setUnidade(e.target.value)} />
            </Campo>
            <Campo rotulo="1ª linha de dados (índice)">
              <input type="number" min={0} className={estiloInput} value={linhaDados} onChange={(e) => setLinhaDados(Number(e.target.value))} />
            </Campo>
            <Campo rotulo="Coluna do código INEP">
              <select className={estiloInput} value={colInep} onChange={(e) => setColInep(Number(e.target.value))}>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Coluna do valor">
              <select className={estiloInput} value={colValor} onChange={(e) => setColValor(Number(e.target.value))}>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Etapa (fixa, opcional)">
              <input className={estiloInput} value={etapaFixa} placeholder="ex.: anos_iniciais" onChange={(e) => setEtapaFixa(e.target.value)} />
            </Campo>
            <Campo rotulo="Coluna da etapa (opcional)">
              <select className={estiloInput} value={colEtapa} onChange={(e) => setColEtapa(e.target.value === "" ? "" : Number(e.target.value))}>
                <option value="">— nenhuma —</option>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Componente (fixo, opcional)">
              <input className={estiloInput} value={compFixo} placeholder="ex.: matematica" onChange={(e) => setCompFixo(e.target.value)} />
            </Campo>
            <Campo rotulo="Coluna do componente (opcional)">
              <select className={estiloInput} value={colComp} onChange={(e) => setColComp(e.target.value === "" ? "" : Number(e.target.value))}>
                <option value="">— nenhuma —</option>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
          </div>

          <div className="flex justify-end">
            <Botao onClick={importar} disabled={ocupado || !indicador.trim() || !unidade.trim()}>
              <FileUp size={15} /> {ocupado ? "Importando..." : "Importar resultados"}
            </Botao>
          </div>

          {ehGlobal && (
            <div className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-500/30 dark:bg-indigo-500/10">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-indigo-800 dark:text-indigo-300">
                <Bot size={16} /> Automatizar (montar o robô com este mapeamento)
              </h3>
              <p className="text-xs text-zinc-600 dark:text-zinc-400">
                Guarde o endereço <b>fixo</b> do arquivo oficial (a URL de download do INEP/SEDUC).
                O sistema passa a baixar dessa URL e importar sozinho, com o <b>mesmo mapeamento</b>{" "}
                que você conferiu acima — sem ninguém subir arquivo de novo.
              </p>
              <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>Não funciona para o INEP (bloqueia downloads de servidor) — a importação que você
                acabou de fazer acima é o caminho certo. Guarde a URL só para quando isso for possível.</span>
              </p>
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-[280px] flex-1">
                  <Campo rotulo="URL do arquivo oficial">
                    <input className={estiloInput} value={urlFonte} placeholder="https://download.inep.gov.br/..."
                           onChange={(e) => setUrlFonte(e.target.value)} />
                  </Campo>
                </div>
                <Campo rotulo="Cadência">
                  <select className={estiloInput} value={cadencia} onChange={(e) => setCadencia(e.target.value)}>
                    <option value="mensal">Mensal (verifica sozinho)</option>
                    <option value="manual">Manual (só quando eu clicar)</option>
                  </select>
                </Campo>
                <Botao variante="neutro" onClick={salvarFonte}
                       disabled={salvandoFonte || !urlFonte.trim() || !indicador.trim() || !unidade.trim()}>
                  <Bot size={15} /> {salvandoFonte ? "Salvando..." : "Salvar fonte automática"}
                </Botao>
              </div>
              {msgFonte && <Mensagem tipo={msgFonte.tipo}>{msgFonte.texto}</Mensagem>}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// --- Fontes automáticas (o robô) — só admin global --------------------------

const _STATUS_TOM: Record<string, "ok" | "alerta" | "neutro"> = {
  ok: "ok", erro: "alerta", nunca: "neutro",
};

function quando(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function FontesAutomaticas({ fontes, carregando, erro, recarregar }: {
  fontes: Fonte[] | null; carregando: boolean;
  erro: { message: string } | null; recarregar: () => void;
}) {
  const [ocupada, setOcupada] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  async function acao(fn: () => Promise<unknown>, id: number, okTxt: string) {
    setOcupada(id); setMsg(null);
    try {
      await fn();
      setMsg({ tipo: "ok", texto: okTxt });
      recarregar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha na operação." });
    } finally { setOcupada(null); }
  }

  const coletar = (f: Fonte) => acao(
    () => api<Fonte>(`/avaliacoes/fontes/${f.id}/coletar`, { method: "POST" }), f.id,
    "Coleta disparada — veja o status atualizado abaixo.");
  const alternar = (f: Fonte) => acao(
    () => api<Fonte>(`/avaliacoes/fontes/${f.id}?ativo=${!f.ativo}`, { method: "PUT" }), f.id,
    f.ativo ? "Fonte pausada." : "Fonte reativada.");
  const excluir = (f: Fonte) => {
    if (!window.confirm(`Remover a fonte "${f.nome}"? Os resultados já importados permanecem.`)) return;
    acao(() => api(`/avaliacoes/fontes/${f.id}`, { method: "DELETE" }), f.id, "Fonte removida.");
  };

  return (
    <Card className="space-y-4 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Bot size={16} className="text-indigo-600" /> Coleta automática (robô)
        </h2>
        <button onClick={recarregar} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                title="Atualizar" aria-label="Atualizar">
          <RefreshCw size={15} />
        </button>
      </div>
      <p className="text-xs text-zinc-500">
        As fontes que o sistema tentaria baixar e importar sozinho (por URL fixa, casando por INEP).
      </p>
      <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <span>
          Uma fonte do INEP aqui vai ficar com <b>erro</b> (“Connection reset by peer”): os portais
          oficiais bloqueiam downloads de servidor. Pode <b>apagar (🗑)</b> a que deu erro — para
          IDEB/SAEB, o caminho é <b>“Importar resultado oficial”</b> acima.
        </span>
      </p>

      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
      {erro && !fontes && <Mensagem tipo="erro">Não foi possível carregar as fontes: {erro.message}</Mensagem>}
      {/* Refetch que falha (blip de rede) NÃO limpa a lista — surfaça o erro mesmo assim. */}
      {erro && fontes && <Mensagem tipo="erro">Não foi possível atualizar a lista: {erro.message}</Mensagem>}

      {carregando && !fontes ? <Carregando /> : fontes && fontes.length === 0 ? (
        <p className="flex items-center gap-2 py-4 text-sm text-zinc-500">
          <Info size={16} /> Nenhuma fonte automática cadastrada ainda.
        </p>
      ) : fontes && (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {fontes.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-[200px] flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {f.nome}
                  <Badge tom={_STATUS_TOM[f.ultimo_status] ?? "neutro"}>{f.ultimo_status}</Badge>
                  {!f.ativo && <Badge tom="neutro">pausada</Badge>}
                </p>
                <p className="truncate text-xs text-zinc-500" title={f.url}>{f.url}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-400">
                  <span className="inline-flex items-center gap-1">
                    <Clock size={12} /> última: {quando(f.ultima_coleta)}
                  </span>
                  <span>cadência: {f.cadencia}</span>
                  {f.cadencia === "mensal" && f.ativo && <span>próxima: {quando(f.proxima_coleta)}</span>}
                  {f.ultimo_status === "erro" && f.ultimo_erro && (
                    <span className="text-amber-600 dark:text-amber-400">{f.ultimo_erro}</span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <Botao variante="neutro" onClick={() => coletar(f)} disabled={ocupada === f.id}>
                  <RefreshCw size={14} /> Coletar agora
                </Botao>
                <button onClick={() => alternar(f)} disabled={ocupada === f.id}
                        className="rounded-lg border border-zinc-200 p-2 text-zinc-500 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                        title={f.ativo ? "Pausar" : "Reativar"} aria-label={f.ativo ? "Pausar" : "Reativar"}>
                  {f.ativo ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <button onClick={() => excluir(f)} disabled={ocupada === f.id}
                        className="rounded-lg border border-zinc-200 p-2 text-red-500 hover:bg-red-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-red-500/10"
                        title="Remover" aria-label="Remover">
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --- Importar oficial em 1 CLIQUE (mapeamento já conhecido) ------------------
// O gestor escolhe a base (IDEB/SAEB) e sobe o arquivo oficial do INEP; o sistema
// aplica o mapeamento sozinho (SAEB traz Matemática e Português numa leitura só).
// O download continua manual (o INEP bloqueia servidor) — o resto é 1 clique.

interface PresetImport { chave: string; rotulo: string; avaliacao: string; dica: string }
interface RespPreset {
  rotulo: string; edicao: number;
  series: { componente: string | null; casados: number; inseridos: number; atualizados: number }[];
}

function ImportarUmClique({ aoImportar }: { aoImportar: () => void }) {
  const { dados: presets } = useApi<PresetImport[]>("/avaliacoes/presets-import");
  const [idx, setIdx] = useState(0);
  const [edicao, setEdicao] = useState(new Date().getFullYear() - 2);
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const preset = presets?.[idx];

  async function importar(f: File) {
    if (!preset) return;
    setOcupado(true); setMsg(null);
    try {
      const fd = new FormData();
      fd.append("arquivo", f);
      fd.append("preset", preset.chave);
      fd.append("edicao", String(edicao));
      const r = await apiUpload<RespPreset>("/avaliacoes/importar-preset", fd);
      const casadas = r.series.reduce((m, s) => Math.max(m, s.casados), 0);
      const detalhe = r.series
        .map((s) => `${s.componente ?? "resultado"}: ${s.casados}`).join(" · ");
      setMsg({
        tipo: casadas > 0 ? "ok" : "erro",
        texto: `${r.rotulo} (${r.edicao}) importado — ${detalhe} escola(s) casada(s) por INEP.`,
      });
      aoImportar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha ao importar." });
    } finally { setOcupado(false); }
  }

  return (
    <Card className="space-y-4 p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <FileUp size={16} className="text-indigo-600" /> Importar oficial em 1 clique
      </h2>
      <p className="text-xs text-zinc-500">
        Escolha a base e suba o arquivo — o sistema <b>já sabe ler as colunas</b> e casa por código
        INEP, sem você mapear nada. O <b>SAEB</b> traz Matemática e Português de uma vez; o
        <b> IDEB/SAEB</b> saem do próprio arquivo do INEP e a <b>SARESP</b> do arquivo que o Constela prepara.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Campo rotulo="Base oficial">
          <select className={estiloInput} value={idx}
                  onChange={(e) => { setIdx(Number(e.target.value)); setMsg(null); }}>
            {(presets ?? []).map((p, i) => <option key={p.chave} value={i}>{p.rotulo}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Edição (ano)">
          <input type="number" className={`${estiloInput} w-28`} value={edicao}
                 onChange={(e) => setEdicao(Number(e.target.value))} />
        </Campo>
        <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-500 ${ocupado || !preset ? "pointer-events-none opacity-50" : ""}`}>
          <Upload size={15} /> {ocupado ? "Importando..." : "Escolher arquivo e importar"}
          <input type="file" accept=".xlsx,.xls,.csv,.zip" className="hidden"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) importar(f); e.target.value = ""; }} />
        </label>
      </div>
      {preset?.dica && (
        <p className="flex items-start gap-1.5 rounded-lg bg-indigo-50 p-2.5 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300">
          <Info size={14} className="mt-0.5 shrink-0" /> {preset.dica}
        </p>
      )}
      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
    </Card>
  );
}

// --- Página ------------------------------------------------------------------

function Painel({ redeId, podeImportar, ehGlobal }: {
  redeId: number; podeImportar: boolean; ehGlobal: boolean;
}) {
  const { dados: opcoes, carregando, erro: erroOpcoes, recarregar } = useApi<SerieOpcao[]>(
    `/redes/${redeId}/avaliacoes/opcoes`);
  const { dados: catalogo } = useApi<CatalogoItem[]>("/avaliacoes");
  // Lista das fontes do robô: vive AQUI (não dentro de FontesAutomaticas) para que
  // salvar uma fonte no bloco de importação (componente irmão) a atualize.
  const fontesApi = useApi<Fonte[]>(ehGlobal ? "/avaliacoes/fontes" : null);

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Avaliações externas"
        descricao="Cruzar os indicadores oficiais (SAEB, IDEB, SARESP…) com o engajamento nas plataformas — evolução e correlação, por rede e escola."
      />

      {carregando && !opcoes ? (
        <Carregando texto="Carregando avaliações..." />
      ) : erroOpcoes && !opcoes ? (
        <Card className="p-4">
          <Mensagem tipo="erro">
            Não foi possível carregar as avaliações: {erroOpcoes.message}
          </Mensagem>
        </Card>
      ) : opcoes && opcoes.length > 0 ? (
        <Correlacao redeId={redeId} opcoes={opcoes} podeImportar={podeImportar} aoRemover={recarregar} />
      ) : (
        <Card className="p-6">
          <p className="flex items-center gap-2 text-sm text-zinc-500">
            <Info size={16} /> Ainda não há resultados de avaliação importados para esta rede.
            {podeImportar ? " Importe um arquivo oficial abaixo para começar." : ""}
          </p>
        </Card>
      )}

      {podeImportar && <ImportarUmClique aoImportar={recarregar} />}

      {podeImportar && catalogo && (
        <ImportarAvaliacao catalogo={catalogo} aoImportar={recarregar}
                           ehGlobal={ehGlobal} aoSalvarFonte={fontesApi.recarregar} />
      )}

      {ehGlobal && (
        <FontesAutomaticas fontes={fontesApi.dados} carregando={fontesApi.carregando}
                           erro={fontesApi.erro} recarregar={fontesApi.recarregar} />
      )}
    </div>
  );
}

export default function RedeAvaliacoes() {
  const { usuario } = useApp();
  const redeDoUsuario = usuario?.rede_id ?? null;
  const { dados: redes, carregando, erro: erroRedes } = useApi<{ id: number; nome: string }[]>(
    redeDoUsuario == null ? "/redes" : null);
  const redeId = redeDoUsuario ?? redes?.[0]?.id ?? null;
  const ehGlobal = Boolean(usuario?.is_global);
  const podeImportar = ehGlobal
    || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const conteudo = useMemo(() => {
    if (redeId == null) {
      if (carregando) return <Carregando texto="Carregando as redes..." />;
      if (erroRedes) return <Vazio titulo="Não foi possível carregar as redes"
                                   descricao={erroRedes.message} />;
      return <Vazio titulo="Nenhuma rede disponível"
                    descricao="Sua conta não está vinculada a uma rede/Secretaria." />;
    }
    return <Painel redeId={redeId} podeImportar={podeImportar} ehGlobal={ehGlobal} />;
  }, [redeId, carregando, erroRedes, podeImportar, ehGlobal]);

  return conteudo;
}
