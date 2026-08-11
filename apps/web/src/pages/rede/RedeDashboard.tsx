/**
 * Painel da Rede / Secretaria de Educação (perfil municipal).
 *
 * Visão consolidada de TODAS as escolas da rede + mapa geográfico (Leaflet +
 * OpenStreetMap — sem chave de API, sem enviar dados de criança a terceiros).
 * Só dados AGREGADOS por escola saem do backend; o isolamento por rede é
 * garantido no servidor (`exigir_rede`), esta tela apenas exibe.
 */
import "leaflet/dist/leaflet.css";

import L from "leaflet";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  Building2,
  Calculator,
  ChevronLeft,
  FileDown,
  Globe,
  GraduationCap,
  LineChart,
  MapPin,
  Scale,
  Settings2,
  Star,
  Target,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { Botao, Card, Carregando, Mensagem, PageHeader, SecaoRecolhivel, StatCard, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, apiDownload } from "../../lib/api";
import { corPorMedia } from "../../lib/cores";
import { nota, numero, tempoLeitura } from "../../lib/formato";
import {
  EnvolucroRede,
  MEDALHAS,
  type DashboardRede,
  type EscolaCartao,
} from "./comum";

// Re-export para compatibilidade dos consumidores que já importavam daqui.
export { EnvolucroRede, MEDALHAS };
export type { DashboardRede, EscolaCartao };

function iconeEscola(cartao: EscolaCartao): L.DivIcon {
  const cor = corPorMedia(cartao.media_geral);
  return L.divIcon({
    className: "",
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${cor};
      border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

/** Ajusta o zoom para enquadrar todas as escolas com coordenada. */
function AjustarLimites({ pontos }: { pontos: [number, number][] }) {
  const mapa = useMap();
  useEffect(() => {
    if (pontos.length === 1) mapa.setView(pontos[0], 14);
    else if (pontos.length > 1) mapa.fitBounds(pontos, { padding: [40, 40] });
  }, [mapa, pontos]);
  return null;
}

function MapaRede({ escolas, aoAbrir }: { escolas: EscolaCartao[]; aoAbrir: (id: number) => void }) {
  const comCoord = escolas.filter((e) => e.latitude != null && e.longitude != null);
  const pontos = comCoord.map(
    (e) => [e.latitude as number, e.longitude as number] as [number, number],
  );

  if (comCoord.length === 0) {
    return (
      <Card className="flex h-[420px] flex-col items-center justify-center p-6 text-center">
        <MapPin className="mb-3 h-8 w-8 text-zinc-400" />
        <p className="text-sm font-medium">Nenhuma escola tem localização cadastrada ainda.</p>
        <p className="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
          Assim que as coordenadas (latitude/longitude) forem preenchidas — por geocodificação em
          lote ou manualmente — as escolas aparecem no mapa.
        </p>
      </Card>
    );
  }

  return (
    <div className="h-[420px] overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
      <MapContainer center={pontos[0]} zoom={12} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <AjustarLimites pontos={pontos} />
        {comCoord.map((escola) => (
          <Marker
            key={escola.escola_id}
            position={[escola.latitude as number, escola.longitude as number]}
            icon={iconeEscola(escola)}
          >
            <Popup>
              <div className="space-y-1">
                <p className="text-sm font-semibold">{escola.nome}</p>
                <p className="text-xs text-zinc-500">
                  {escola.total_alunos} alunos · {escola.total_turmas} turmas
                </p>
                <p className="text-xs">
                  Média geral <b>{nota(escola.media_geral)}</b> · adoção {nota(escola.adocao)}%
                </p>
                <button
                  className="mt-1 text-xs font-semibold text-indigo-600 hover:underline"
                  onClick={() => aoAbrir(escola.escola_id)}
                >
                  Abrir escola →
                </button>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}

function LinhaEscola({ escola, aoAbrir }: { escola: EscolaCartao; aoAbrir: (id: number) => void }) {
  return (
    <button
      onClick={() => aoAbrir(escola.escola_id)}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
    >
      <span className="w-6 text-center text-sm font-bold tabular-nums text-zinc-400">{escola.posicao ?? "–"}</span>
      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: corPorMedia(escola.media_geral) }} />
      <span className="flex-1 truncate text-sm font-medium">
        {escola.nome}
        {escola.precisa_atencao && <AlertTriangle size={13} className="ml-1 inline text-amber-500" />}
      </span>
      <span className="hidden text-xs text-zinc-500 sm:block">{escola.total_alunos} al.</span>
      <span className="w-14 text-right text-sm font-bold tabular-nums">{nota(escola.media_geral)}</span>
    </button>
  );
}

// Critérios do "Top 5 escolas" — a SEDUC alterna e o ranking reordena (dados já
// vêm por escola no payload, então reordena no cliente, sem nova chamada).
// O padrão é o ÍNDICE GERAL (0–1000), que é proporcional ao tamanho da escola;
// `indice` só diz como formatar (inteiro 0–1000 vs. decimal 0–100).
const METRICAS_TOP: {
  chave: keyof EscolaCartao; rotulo: string; sufixo?: string; indice?: boolean;
}[] = [
  { chave: "pontuacao_geral", rotulo: "Índice Geral", indice: true },
  { chave: "pontuacao_leitura", rotulo: "Leitura", indice: true },
  { chave: "pontuacao_matematica", rotulo: "Matemática", indice: true },
  { chave: "adocao", rotulo: "Engajamento", sufixo: "%" },
  // Per capita (÷ matrícula): comparação JUSTA entre escolas de tamanhos diferentes
  // — a escola pequena com muita leitura por aluno sobe, não some sob o volume bruto.
  { chave: "livros_por_matricula", rotulo: "Livros/aluno" },
  { chave: "estrelas_por_matricula", rotulo: "Estrelas/aluno" },
];

// Critérios da comparação entre REDES (Admin Global). O cartão de REDE não tem
// os índices per capita (que são por ESCOLA, normalizados dentro de cada rede),
// então esta lista é própria — usar METRICAS_TOP aqui renderizaria `undefined`.
const METRICAS_REDE: { chave: keyof RedeCartao; rotulo: string; sufixo?: string }[] = [
  { chave: "media_geral", rotulo: "Geral" },
  { chave: "media_elefante", rotulo: "Leitura" },
  { chave: "media_matific", rotulo: "Matemática" },
  { chave: "adocao", rotulo: "Engajamento", sufixo: "%" },
];

/** RESUMO do Ranking da Rede: as 5 melhores escolas por ÍNDICE GERAL (0–1000,
 *  proporcional ao tamanho da escola) + atalho para o ranking completo. O
 *  seletor de critério continua disponível para uma espiada rápida por
 *  dimensão; o detalhamento (indicadores reais por aba) vive em /rede/ranking. */
function TopEscolas({ escolas, aoAbrir }: { escolas: EscolaCartao[]; aoAbrir: (id: number) => void }) {
  const navegar = useNavigate();
  const [metrica, setMetrica] = useState(0);
  const m = METRICAS_TOP[metrica];
  // Indicador AUSENTE não pode derrubar o painel: um bundle servido pelo cache do
  // PWA pode ser mais novo/velho que a API (já causou a regressão do Dashboard).
  const val = (e: EscolaCartao) => Number(e[m.chave] ?? 0);
  const top = useMemo(
    () => [...escolas]
      .filter((e) => e.alunos_com_dados > 0)
      .sort((a, b) => val(b) - val(a)
        || b.adocao - a.adocao
        || a.nome.localeCompare(b.nome, "pt-BR"))
      .slice(0, 5),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `val` deriva de m.chave
    [escolas, m.chave],
  );
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Trophy size={16} className="text-amber-500" /> Top 5 escolas da rede
        </h2>
        <div className="flex flex-wrap gap-1">
          {METRICAS_TOP.map((opt, i) => (
            <button
              key={opt.rotulo}
              type="button"
              onClick={() => setMetrica(i)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                i === metrica
                  ? "bg-indigo-600 text-white"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              }`}
            >
              {opt.rotulo}
            </button>
          ))}
        </div>
      </div>
      {top.length === 0 ? (
        <p className="py-4 text-center text-sm text-zinc-500">Sem dados ainda.</p>
      ) : (
        <>
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-[11px] uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th scope="col" className="px-2 py-1.5 font-medium">Pos.</th>
                <th scope="col" className="px-2 py-1.5 font-medium">Escola</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">{m.rotulo}</th>
              </tr>
            </thead>
            <tbody>
              {top.map((e, i) => (
                <tr key={e.escola_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-2 py-2 text-center">
                    {MEDALHAS[i] ?? <span className="text-xs font-bold text-zinc-400">{i + 1}º</span>}
                  </td>
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      onClick={() => aoAbrir(e.escola_id)}
                      className="truncate text-left font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                    >
                      {e.nome}
                    </button>
                  </td>
                  <td className="px-2 py-2 text-right text-base font-bold text-indigo-700 tabular-nums dark:text-indigo-300">
                    {m.indice ? numero(Math.round(val(e))) : nota(val(e))}
                    {m.sufixo ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            onClick={() => navegar("/rede/ranking")}
            className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300"
          >
            Ver ranking completo <span aria-hidden>→</span>
          </button>
        </>
      )}
    </Card>
  );
}

// Seção consolidada de UMA plataforma (Elefante ou Matific): KPIs da rede +
// as escolas que mais produzem naquela plataforma. Só agregado, sem PII.
function SecaoPlataforma({
  titulo, icone, kpis, escolas, campoTop, rotuloTop, formatoTop, aoAbrir,
}: {
  titulo: string;
  icone: ReactNode;
  kpis: { rotulo: string; valor: string }[];
  escolas: EscolaCartao[];
  campoTop: keyof EscolaCartao;
  rotuloTop: string;
  formatoTop: (v: number) => string;
  aoAbrir: (id: number) => void;
}) {
  const top = useMemo(
    () => [...escolas]
      .filter((e) => (e[campoTop] as number) > 0)
      .sort((a, b) => (b[campoTop] as number) - (a[campoTop] as number))
      .slice(0, 3),
    [escolas, campoTop],
  );
  return (
    <Card className="p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">{icone} {titulo}</h2>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {kpis.map((k) => (
          <div key={k.rotulo} className="rounded-lg bg-zinc-50 p-2 dark:bg-zinc-800/40">
            <p className="text-lg font-bold tabular-nums">{k.valor}</p>
            <p className="text-[11px] uppercase tracking-wide text-zinc-500">{k.rotulo}</p>
          </div>
        ))}
      </div>
      <p className="mb-1 text-xs font-medium text-zinc-500">Escolas com mais {rotuloTop}</p>
      {top.length === 0 ? (
        <p className="py-2 text-sm text-zinc-500">Sem dados ainda.</p>
      ) : (
        <ol className="space-y-0.5">
          {top.map((e, i) => (
            <li key={e.escola_id}>
              <button
                type="button"
                onClick={() => aoAbrir(e.escola_id)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
              >
                <span className="w-5 text-center">{MEDALHAS[i]}</span>
                <span className="flex-1 truncate font-medium">{e.nome}</span>
                <span className="font-bold tabular-nums">{formatoTop(e[campoTop] as number)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function ComparativoRede({ escolas, aoAbrir }: { escolas: EscolaCartao[]; aoAbrir: (id: number) => void }) {
  const linhas = useMemo(
    () => [...escolas].filter((e) => e.alunos_com_dados > 0).sort((a, b) => b.media_geral - a.media_geral),
    [escolas],
  );
  if (linhas.length === 0) return null;
  return (
    <Card className="p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <BarChart3 size={16} className="text-indigo-600" /> Comparativo entre escolas
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead>
            <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              <th className="px-3 py-2 font-medium">Escola</th>
              <th className="px-3 py-2 text-right font-medium">Geral</th>
              <th className="px-3 py-2 text-right font-medium">Leitura</th>
              <th className="px-3 py-2 text-right font-medium">Matific</th>
              <th className="px-3 py-2 text-right font-medium">Engaj.</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((e) => (
              <tr key={e.escola_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => aoAbrir(e.escola_id)}
                    className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                  >
                    {e.nome}
                  </button>
                </td>
                <td className="px-3 py-2 text-right font-semibold">{nota(e.media_geral)}</td>
                <td className="px-3 py-2 text-right">{nota(e.media_elefante)}</td>
                <td className="px-3 py-2 text-right">{nota(e.media_matific)}</td>
                <td className="px-3 py-2 text-right">{nota(e.adocao)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

interface MetaProgresso {
  id: number;
  metrica: string;
  rotulo: string;
  sufixo: string;
  alvo: number;
  atual: number;
  progresso: number;
  atingida: boolean;
  descricao: string | null;
  escolas_atingiram: number | null;
  escolas_total: number | null;
}

const METRICAS_META_UI = [
  { metrica: "media_geral", rotulo: "Média geral da rede" },
  { metrica: "media_elefante", rotulo: "Leitura (Elefante Letrado)" },
  { metrica: "media_matific", rotulo: "Matemática (Matific)" },
  { metrica: "adocao", rotulo: "Engajamento (adoção %)" },
  { metrica: "livros", rotulo: "Livros lidos na rede" },
  { metrica: "atividades", rotulo: "Atividades Matific na rede" },
];

/** Metas da rede com PROGRESSO real (aba Dashboard). Sem meta = convite. */
function MetasRede({ redeId }: { redeId: number }) {
  const { dados: metas } = useApi<MetaProgresso[]>(`/redes/${redeId}/metas`);
  return (
    <Card className="p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Target size={16} className="text-indigo-600" /> Metas da rede
      </h2>
      {!metas || metas.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Nenhuma meta definida ainda. Defina as metas da rede na aba <b>Secretaria</b> —
          o progresso (dado real, sem número fictício) aparece aqui.
        </p>
      ) : (
        <div className="space-y-3.5">
          {metas.map((m) => (
            <div key={m.id}>
              <div className="mb-1 flex items-center justify-between gap-2 text-sm">
                <span className="min-w-0 truncate font-medium">
                  {m.descricao || m.rotulo}
                  {m.atingida && (
                    <span className="ml-1.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">✓ atingida</span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-zinc-500">
                  {nota(m.atual)}{m.sufixo} / {nota(m.alvo)}{m.sufixo}
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                <div
                  className={`h-full rounded-full transition-all ${m.atingida ? "bg-emerald-500" : "bg-indigo-500"}`}
                  style={{ width: `${m.progresso}%` }}
                />
              </div>
              <div className="mt-0.5 flex justify-between text-xs text-zinc-400">
                <span className="tabular-nums">{nota(m.progresso)}%</span>
                {m.escolas_total != null && (
                  <span>{m.escolas_atingiram} de {m.escolas_total} escolas atingiram</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Cadastro de metas da rede (aba Secretaria) — definir alvo por indicador. */
function GestaoMetas({ redeId }: { redeId: number }) {
  const { dados: metas, recarregar } = useApi<MetaProgresso[]>(`/redes/${redeId}/metas`);
  const [metrica, setMetrica] = useState("media_geral");
  const [alvo, setAlvo] = useState("");
  const [salvando, setSalvando] = useState(false);

  async function salvar() {
    const valor = Number(alvo);
    if (!valor || valor <= 0) return;
    setSalvando(true);
    try {
      await api(`/redes/${redeId}/metas`, {
        method: "PUT",
        body: JSON.stringify({ metrica, alvo: valor }),
      });
      setAlvo("");
      recarregar();
    } finally {
      setSalvando(false);
    }
  }
  async function remover(met: string) {
    await api(`/redes/${redeId}/metas/${met}`, { method: "DELETE" });
    recarregar();
  }

  return (
    <Card className="p-4">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Target size={16} className="text-indigo-600" /> Metas da rede
      </h2>
      <p className="mb-3 text-xs text-zinc-500">
        Defina o alvo de cada indicador. O progresso é calculado com o dado real e aparece no Dashboard.
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <select
          aria-label="Indicador da meta"
          value={metrica}
          onChange={(e) => setMetrica(e.target.value)}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        >
          {METRICAS_META_UI.map((o) => (
            <option key={o.metrica} value={o.metrica}>{o.rotulo}</option>
          ))}
        </select>
        <input
          type="number"
          min="0"
          step="0.1"
          value={alvo}
          onChange={(e) => setAlvo(e.target.value)}
          placeholder="alvo"
          aria-label="Valor-alvo da meta"
          className="w-28 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <Botao onClick={salvar} disabled={salvando || !alvo}>Salvar meta</Botao>
      </div>
      {metas && metas.length > 0 && (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
          {metas.map((m) => (
            <li key={m.id} className="flex items-center gap-3 py-2 text-sm">
              <span className="flex-1 truncate">{m.rotulo}</span>
              <span className="tabular-nums font-semibold">{nota(m.alvo)}{m.sufixo}</span>
              <button
                type="button"
                onClick={() => remover(m.metrica)}
                className="text-xs text-red-500 hover:underline"
              >
                remover
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function VitrinePublica({ redeId }: { redeId: number }) {
  const { dados, recarregar } = useApi<{ ativo: boolean; token: string | null; url: string | null }>(
    `/redes/${redeId}/publico`);
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);

  async function alternar(ativo: boolean) {
    setOcupado(true);
    try {
      await api(`/redes/${redeId}/publico`, { method: "PUT", body: JSON.stringify({ ativo }) });
      recarregar();
    } finally {
      setOcupado(false);
    }
  }
  async function copiar() {
    if (!dados?.url) return;
    try {
      await navigator.clipboard.writeText(dados.url);
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 1500);
    } catch { /* clipboard indisponível: o link fica visível para copiar à mão */ }
  }

  return (
    <Card className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 text-sm">
      <span className="flex items-center gap-2 font-semibold">
        <Globe size={16} className="text-indigo-600" /> Vitrine pública
      </span>
      {dados?.ativo ? (
        <>
          <span className="text-zinc-500">Link aberto (sem login) com as melhores escolas:</span>
          <code className="rounded bg-zinc-100 px-2 py-1 text-xs dark:bg-zinc-800">{dados.url}</code>
          <Botao variante="neutro" onClick={copiar}>{copiado ? "Copiado!" : "Copiar link"}</Botao>
          <Botao variante="neutro" onClick={() => alternar(false)} disabled={ocupado}>Desligar</Botao>
        </>
      ) : (
        <>
          <span className="text-zinc-500">
            Publique um link aberto com as 5 melhores escolas em leitura e matemática — sem nome de criança.
          </span>
          <Botao onClick={() => alternar(true)} disabled={ocupado}>Ligar vitrine pública</Botao>
        </>
      )}
    </Card>
  );
}

function PainelRede({ redeId, modo }: { redeId: number; modo: "analise" | "secretaria" }) {
  const { usuario, selecionarEscola } = useApp();
  const navegar = useNavigate();
  const { dados, erro, carregando } = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const [filtro, setFiltro] = useState("");
  const [baixando, setBaixando] = useState(false);
  const [boletimErro, setBoletimErro] = useState("");

  async function baixarBoletim() {
    setBaixando(true);
    setBoletimErro("");
    try {
      await apiDownload(`/redes/${redeId}/boletim`);
    } catch (e) {
      setBoletimErro(e instanceof Error ? e.message : "Não foi possível gerar o boletim.");
    } finally {
      setBaixando(false);
    }
  }

  const abrirEscola = (escolaId: number) => {
    selecionarEscola(escolaId); // troca a escola ativa (o backend autoriza: é da rede)
    // No Dashboard (análise), trocar a escola já muda o CONTEXTO: o próprio
    // Dashboard passa a mostrar o panorama daquela escola (sem sair da tela). Na
    // aba Secretaria (admin), abre a Visão da Escola.
    if (modo === "secretaria") navegar("/escola");
  };

  const escolasFiltradas = useMemo(() => {
    const q = filtro.trim().toLowerCase();
    const lista = dados?.escolas ?? [];
    return q ? lista.filter((e) => e.nome.toLowerCase().includes(q)) : lista;
  }, [dados, filtro]);

  if (carregando && !dados) return <Carregando texto="Carregando a rede..." />;
  if (erro && !dados) return <Vazio titulo="Não foi possível carregar a rede" descricao={erro.message} />;
  if (!dados) return null;

  const t = dados.totais;
  // MÓDULOS CONTRATADOS pela rede exibida (vem do payload — o admin global pode
  // estar vendo uma rede diferente da dele, então não uso o hook do usuário).
  const mods = dados.modulos ?? ["leitura", "matematica"];
  const temLeitura = mods.includes("leitura");
  const temMatematica = mods.includes("matematica");
  const eq = dados.equidade;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo={modo === "secretaria" ? "Secretaria de Educação" : "Panorama Geral da Rede Municipal"}
        descricao={modo === "secretaria"
          ? "Área administrativa da rede: gestão de escolas, avaliações externas, boletim e vitrine pública."
          : "Acompanhe o desempenho, o engajamento e a evolução das escolas da rede."}
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            {/* O seletor de contexto (Toda a Rede ↔ escola) agora é ÚNICO e vive
                na barra superior — nada de seletor duplicado aqui. */}
            {modo === "secretaria" && (
              <>
                <Botao variante="neutro" onClick={() => navegar("/rede/avaliacoes")}>
                  <LineChart size={15} /> Avaliações externas
                </Botao>
                <Botao variante="neutro" onClick={baixarBoletim} disabled={baixando}>
                  <FileDown size={15} /> {baixando ? "Gerando..." : "Baixar boletim (PDF)"}
                </Botao>
                {usuario?.is_global && (
                  <Botao variante="neutro" onClick={() => navegar("/rede/gerenciar")}>
                    <Settings2 size={15} /> Gerenciar redes
                  </Botao>
                )}
              </>
            )}
          </div>
        }
      />
      {boletimErro && <Mensagem tipo="erro">{boletimErro}</Mensagem>}

      {/* --- ANÁLISE (aba Dashboard): panorama estratégico da rede inteira. --- */}
      {modo === "analise" && (
      <>
      {/* Visão geral da rede — indicadores consolidados de TODAS as escolas. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Building2 size={16} />} rotulo="Escolas" valor={numero(t.escolas)} detalhe={`${t.escolas_ativas} ativas`} />
        <StatCard icone={<Users size={16} />} rotulo="Alunos" valor={numero(t.alunos)} detalhe={`${numero(t.turmas)} turmas`} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Professores" valor={numero(t.professores)} detalhe="na rede" />
        <StatCard
          icone={<Trophy size={16} className="text-amber-500" />}
          rotulo="Melhor escola"
          valor={t.melhor_escola ? nota(t.melhor_escola.media_geral) : "–"}
          detalhe={t.melhor_escola?.nome ?? "sem dados"}
        />
        <StatCard icone={<BookOpen size={16} />} rotulo="Livros lidos" valor={numero(t.livros)} detalhe={`${nota(t.livros_por_aluno)} por aluno`} />
        <StatCard icone={<Star size={16} />} rotulo="Atividades Matific" valor={numero(t.atividades)} detalhe={`${numero(t.estrelas)} estrelas`} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Adoção" valor={`${nota(t.adocao)}%`} detalhe="alunos com dados" />
        <StatCard
          icone={<TrendingUp size={16} />}
          rotulo="Média geral"
          valor={nota(t.media_geral)}
          detalhe={`Matific ${nota(t.media_matific)} · Elefante ${nota(t.media_elefante)}`}
        />
      </div>

      {/* Escolas em atenção — a lista de AÇÃO da secretaria (o que priorizar). */}
      {dados.atencao.length > 0 && (
        <SecaoRecolhivel
          className="border-amber-200 dark:border-amber-500/30"
          icone={<AlertTriangle size={16} className="text-amber-500" />}
          titulo={
            <>
              Escolas que precisam de atenção
              <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                {dados.atencao.length}
              </span>
            </>
          }
        >
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {dados.atencao.map((escola) => (
              <li key={escola.escola_id} className="flex items-center gap-3 py-2">
                <button
                  onClick={() => abrirEscola(escola.escola_id)}
                  className="min-w-0 flex-1 text-left text-sm font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                >
                  {escola.nome}
                </button>
                <span className="text-xs text-amber-700 dark:text-amber-400">{escola.motivo_atencao}</span>
              </li>
            ))}
          </ul>
        </SecaoRecolhivel>
      )}

      {/* Top escolas — a SEDUC escolhe o critério (geral/leitura/matemática/engajamento). */}
      <TopEscolas escolas={dados.escolas} aoAbrir={abrirEscola} />

      {/* Panorama por plataforma — só dos MÓDULOS CONTRATADOS pela rede. O que
          não faz parte do plano não aparece (nem zerado); com um módulo só, o
          card ocupa a largura inteira em vez de deixar buraco. */}
      <div className={`grid gap-6 ${temLeitura && temMatematica ? "lg:grid-cols-2" : ""}`}>
        {temLeitura && <SecaoPlataforma
          titulo="Leitura — Elefante Letrado"
          icone={<BookOpen size={16} className="text-emerald-600" />}
          kpis={[
            { rotulo: "Livros lidos", valor: numero(t.livros) },
            { rotulo: "Por aluno", valor: nota(t.livros_por_aluno) },
            { rotulo: "Alunos ativos", valor: numero(t.ativos_elefante) },
            { rotulo: "Tempo", valor: tempoLeitura(t.tempo_leitura_min) },
          ]}
          escolas={dados.escolas}
          campoTop="livros"
          rotuloTop="livros lidos"
          formatoTop={(v) => `${numero(v)} livros`}
          aoAbrir={abrirEscola}
        />}
        {temMatematica && <SecaoPlataforma
          titulo="Matemática — Matific"
          icone={<Calculator size={16} className="text-indigo-600" />}
          kpis={[
            { rotulo: "Estrelas", valor: numero(t.estrelas) },
            { rotulo: "Atividades", valor: numero(t.atividades) },
            { rotulo: "Alunos ativos", valor: numero(t.ativos_matific) },
            { rotulo: "Média", valor: nota(t.media_matific) },
          ]}
          escolas={dados.escolas}
          campoTop="estrelas"
          rotuloTop="estrelas"
          formatoTop={(v) => `${numero(v)} ⭐`}
          aoAbrir={abrirEscola}
        />}
      </div>

      {/* Comparativo entre escolas (tabela por indicador). */}
      <ComparativoRede escolas={dados.escolas} aoAbrir={abrirEscola} />

      {/* Equidade: quão distante está a melhor da pior escola. */}
      <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-sm">
        <span className="flex items-center gap-2 font-semibold">
          <Scale size={16} className="text-indigo-600" /> Equidade da rede
        </span>
        <span className="text-zinc-600 dark:text-zinc-300">
          Diferença entre a melhor e a pior escola:{" "}
          <b className="tabular-nums">{nota(eq.gap_media)}</b> pontos
          <span className="text-zinc-400"> ({nota(eq.escola_menor_media)} → {nota(eq.escola_maior_media)})</span>
        </span>
        <span className="text-zinc-600 dark:text-zinc-300">
          <b className="tabular-nums">{eq.escolas_abaixo_da_media}</b> escola(s) abaixo da média da rede
        </span>
      </Card>

      {/* Metas da rede — progresso REAL (alvo cadastrado na aba Secretaria). */}
      <MetasRede redeId={redeId} />
      </>
      )}

      {/* --- SECRETARIA (aba Secretaria): funções administrativas + mapa/navegação. --- */}
      {modo === "secretaria" && (
      <>
      {/* Cadastro de metas da rede (o progresso aparece no Dashboard). */}
      <GestaoMetas redeId={redeId} />

      <VitrinePublica redeId={redeId} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <MapPin size={16} className="text-indigo-600" /> Distribuição geográfica
          </h2>
          <MapaRede escolas={escolasFiltradas} aoAbrir={abrirEscola} />
        </div>

        <Card className="flex flex-col p-4">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Trophy size={16} className="text-amber-500" /> Ranking das escolas
          </h2>
          <input
            className="mb-2 w-full rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            placeholder="Filtrar escola..."
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
          />
          <div className="-mx-1 max-h-[340px] flex-1 space-y-0.5 overflow-y-auto">
            {escolasFiltradas.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-zinc-500">Nenhuma escola.</p>
            ) : (
              escolasFiltradas.map((escola) => (
                <LinhaEscola key={escola.escola_id} escola={escola} aoAbrir={abrirEscola} />
              ))
            )}
          </div>
        </Card>
      </div>
      </>
      )}
    </div>
  );
}

/** Resolve a rede visível do usuário (sua rede, ou a 1ª que o admin global vê) e
 *  entrega o redeId; trata carregamento e o caso "sem rede". Compartilhado pela
 *  aba Dashboard (panorama) e pela aba Secretaria (administrativo). */
/** Panorama ANALÍTICO da rede — renderizado DENTRO da aba Dashboard para os
 *  perfis de rede (SEDUC/Admin Global). Não é uma tela separada: é o conteúdo
 *  do Dashboard quando o usuário é de rede. */
export function PanoramaRede() {
  return <EnvolucroRede>{(redeId) => <PainelRede redeId={redeId} modo="analise" />}</EnvolucroRede>;
}

/** Panorama de UMA escola da rede, no contexto da Secretaria — mostrado no
 *  Dashboard quando o seletor do topo aponta para uma escola específica. Usa o
 *  cartão AGREGADO da escola (mesmos números do painel da rede): só totais por
 *  escola, NUNCA PII individual de criança. O título vira "Panorama Geral da
 *  <Escola>" e há o atalho de volta para "Toda a Rede Municipal". */
export function PanoramaEscolaDaRede({ escolaId }: { escolaId: number }) {
  return (
    <EnvolucroRede>
      {(redeId) => <ConteudoEscolaDaRede redeId={redeId} escolaId={escolaId} />}
    </EnvolucroRede>
  );
}

function ConteudoEscolaDaRede({ redeId, escolaId }: { redeId: number; escolaId: number }) {
  const { dados, erro, carregando } = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const { selecionarEscola } = useApp();
  const voltar = () => selecionarEscola(null);

  if (carregando && !dados) return <Carregando texto="Carregando a escola..." />;
  if (erro && !dados) return <Vazio titulo="Não foi possível carregar" descricao={erro.message} />;
  if (!dados) return null;

  const e = dados.escolas.find((x) => x.escola_id === escolaId);
  if (!e) {
    // Escola fora da rede/contexto inválido: oferece voltar ao consolidado.
    return (
      <div className="space-y-4">
        <VoltarRede aoVoltar={voltar} />
        <Vazio titulo="Escola não encontrada nesta rede"
               descricao="Selecione 'Toda a Rede Municipal' ou outra escola no seletor do topo." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <VoltarRede aoVoltar={voltar} />
      <PageHeader
        titulo={`Panorama Geral da ${e.nome}`}
        descricao="Indicadores desta escola no ano letivo atual. Selecione 'Toda a Rede Municipal' no topo para o consolidado."
      />

      {e.precisa_atencao && e.motivo_atencao && (
        <Card className="flex items-center gap-2 border-amber-200 p-3 text-sm dark:border-amber-500/30">
          <AlertTriangle size={16} className="shrink-0 text-amber-500" />
          <span className="text-amber-700 dark:text-amber-300">{e.motivo_atencao}</span>
        </Card>
      )}

      {/* Indicadores principais da ESCOLA (agregados, sem PII). */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Users size={16} />} rotulo="Alunos" valor={numero(e.total_alunos)} detalhe={`${numero(e.total_turmas)} turmas`} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Professores" valor={numero(e.total_professores)} detalhe="nesta escola" />
        <StatCard icone={<TrendingUp size={16} />} rotulo="Média geral" valor={nota(e.media_geral)} detalhe={`Matific ${nota(e.media_matific)} · Elefante ${nota(e.media_elefante)}`} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Adoção" valor={`${nota(e.adocao)}%`} detalhe="alunos com dados" />
      </div>

      {/* Plataformas — só os KPIs da escola (sem ranking entre escolas aqui). */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <BookOpen size={16} className="text-emerald-600" /> Leitura — Elefante Letrado
          </h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <KpiEscola rotulo="Livros lidos" valor={numero(e.livros)} />
            <KpiEscola rotulo="Por aluno" valor={nota(e.livros_por_aluno)} />
            <KpiEscola rotulo="Alunos ativos" valor={numero(e.ativos_elefante)} />
            <KpiEscola rotulo="Tempo" valor={tempoLeitura(e.tempo_leitura_min)} />
          </div>
        </Card>
        <Card className="p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Calculator size={16} className="text-indigo-600" /> Matemática — Matific
          </h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <KpiEscola rotulo="Estrelas" valor={numero(e.estrelas)} />
            <KpiEscola rotulo="Atividades" valor={numero(e.atividades)} />
            <KpiEscola rotulo="Alunos ativos" valor={numero(e.ativos_matific)} />
            <KpiEscola rotulo="Média" valor={nota(e.media_matific)} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function VoltarRede({ aoVoltar }: { aoVoltar: () => void }) {
  return (
    <button
      type="button"
      onClick={aoVoltar}
      className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
    >
      <ChevronLeft size={16} /> Toda a Rede Municipal
    </button>
  );
}

function KpiEscola({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="rounded-lg bg-zinc-50 p-2 dark:bg-zinc-800/40">
      <p className="text-lg font-bold tabular-nums">{valor}</p>
      <p className="text-[11px] uppercase tracking-wide text-zinc-500">{rotulo}</p>
    </div>
  );
}

/** Aba SECRETARIA (/rede) — administrativo (avaliações, boletim, gerenciar redes,
 *  vitrine pública, mapa). O panorama de análise vive no Dashboard, não aqui. */
export default function RedeDashboard() {
  return <EnvolucroRede>{(redeId) => <PainelRede redeId={redeId} modo="secretaria" />}</EnvolucroRede>;
}

/* O Ranking da Rede (tabela completa por aba) vive em `./RankingRede.tsx` — uma
 * ÚNICA implementação, usada tanto pela rota dedicada /rede/ranking quanto pelo
 * atalho antigo /ranking (Rankings.tsx). Aqui ficou só o RESUMO (Top 5). */

/* ========================================================================== */
/* Admin Global — visão consolidada de TODAS as redes (uma camada acima da     */
/* Secretaria). Só agregado por rede/escola, sem PII.                          */
/* ========================================================================== */

interface RedeCartao {
  rede_id: number;
  nome: string;
  uf: string | null;
  status: string;
  escolas: number;
  alunos: number;
  turmas: number;
  professores: number;
  alunos_com_dados: number;
  adocao: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  livros: number;
  atividades: number;
  estrelas: number;
  escolas_em_atencao: number;
  posicao?: number;
}

interface DashboardGlobal {
  totais: {
    redes: number;
    escolas: number;
    alunos: number;
    turmas: number;
    professores: number;
    livros: number;
    atividades: number;
    estrelas: number;
    media_geral: number;
    media_matific: number;
    media_elefante: number;
    escolas_em_atencao: number;
  };
  redes: RedeCartao[];
  top_escolas: (EscolaCartao & { rede_id: number; rede_nome: string })[];
}

function ConteudoGlobal({ aoAbrirRede }: { aoAbrirRede: (id: number) => void }) {
  const { dados, erro, carregando } = useApi<DashboardGlobal>("/redes/panorama-global");
  const { selecionarEscola } = useApp();
  const navegar = useNavigate();
  const [metrica, setMetrica] = useState(0);
  const m = METRICAS_REDE[metrica];
  const redesRanked = useMemo(
    () => [...(dados?.redes ?? [])]
      .sort((a, b) => Number(b[m.chave] ?? 0) - Number(a[m.chave] ?? 0)),
    [dados, m.chave],
  );
  if (carregando && !dados) return <Carregando texto="Carregando as redes..." />;
  if (erro && !dados) return <Vazio titulo="Não foi possível carregar" descricao={erro.message} />;
  if (!dados) return null;
  const t = dados.totais;
  const abrirEscola = (id: number) => { selecionarEscola(id); navegar("/escola"); };

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Panorama Global — Todas as Redes"
        descricao="Visão consolidada de todas as redes às quais você tem acesso. Selecione uma rede para aprofundar."
        acoes={
          <select
            aria-label="Selecionar rede"
            className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-medium dark:border-zinc-700 dark:bg-zinc-900"
            value=""
            onChange={(e) => { const id = Number(e.target.value); if (id) aoAbrirRede(id); }}
          >
            <option value="">🌎 Todas as redes</option>
            {[...dados.redes].sort((a, b) => a.nome.localeCompare(b.nome)).map((r) => (
              <option key={r.rede_id} value={r.rede_id}>{r.nome}</option>
            ))}
          </select>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Globe size={16} />} rotulo="Redes" valor={numero(t.redes)} detalhe={`${numero(t.escolas)} escolas`} />
        <StatCard icone={<Users size={16} />} rotulo="Alunos" valor={numero(t.alunos)} detalhe={`${numero(t.turmas)} turmas`} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Professores" valor={numero(t.professores)} detalhe="em todas as redes" />
        <StatCard icone={<TrendingUp size={16} />} rotulo="Média geral" valor={nota(t.media_geral)} detalhe={`Matific ${nota(t.media_matific)} · Elefante ${nota(t.media_elefante)}`} />
        <StatCard icone={<BookOpen size={16} />} rotulo="Livros lidos" valor={numero(t.livros)} detalhe="em todas as redes" />
        <StatCard icone={<Star size={16} />} rotulo="Atividades Matific" valor={numero(t.atividades)} detalhe={`${numero(t.estrelas)} estrelas`} />
        <StatCard icone={<Building2 size={16} />} rotulo="Escolas" valor={numero(t.escolas)} detalhe="na rede toda" />
        <StatCard icone={<AlertTriangle size={16} className="text-amber-500" />} rotulo="Escolas em atenção" valor={numero(t.escolas_em_atencao)} detalhe="precisam de acompanhamento" />
      </div>

      {/* Comparação / ranking entre redes por indicador. */}
      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <BarChart3 size={16} className="text-indigo-600" /> Comparação entre redes
          </h2>
          <div className="flex flex-wrap gap-1">
            {METRICAS_REDE.map((opt, i) => (
              <button
                key={opt.rotulo}
                type="button"
                onClick={() => setMetrica(i)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  i === metrica
                    ? "bg-indigo-600 text-white"
                    : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                }`}
              >
                {opt.rotulo}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-3 py-2 font-medium">#</th>
                <th className="px-3 py-2 font-medium">Rede</th>
                <th className="px-3 py-2 text-right font-medium">Escolas</th>
                <th className="px-3 py-2 text-right font-medium">Alunos</th>
                <th className="px-3 py-2 text-right font-medium">{m.rotulo}</th>
                <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Leitura</th>
                <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Matific</th>
                <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Engaj.</th>
              </tr>
            </thead>
            <tbody>
              {redesRanked.map((r, i) => (
                <tr key={r.rede_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-3 py-2 text-center">
                    {MEDALHAS[i] ?? <span className="text-xs font-bold text-zinc-400">{i + 1}</span>}
                  </td>
                  <td className="px-3 py-2">
                    <button type="button" onClick={() => aoAbrirRede(r.rede_id)}
                            className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                      {r.nome}{r.uf ? ` · ${r.uf}` : ""}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right">{numero(r.escolas)}</td>
                  <td className="px-3 py-2 text-right">{numero(r.alunos)}</td>
                  <td className="px-3 py-2 text-right font-semibold">{nota(Number(r[m.chave] ?? 0))}{m.sufixo ?? ""}</td>
                  <td className="hidden px-3 py-2 text-right md:table-cell">{nota(r.media_elefante)}</td>
                  <td className="hidden px-3 py-2 text-right md:table-cell">{nota(r.media_matific)}</td>
                  <td className="hidden px-3 py-2 text-right sm:table-cell">{nota(r.adocao)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Melhores escolas de TODAS as redes (com o nome da rede). */}
      <Card className="p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Trophy size={16} className="text-amber-500" /> Top escolas de todas as redes
        </h2>
        {dados.top_escolas.length === 0 ? (
          <p className="py-4 text-center text-sm text-zinc-500">Sem dados ainda.</p>
        ) : (
          <ol className="space-y-0.5">
            {dados.top_escolas.map((e, i) => (
              <li key={`${e.rede_id}-${e.escola_id}`}>
                <button
                  type="button"
                  onClick={() => abrirEscola(e.escola_id)}
                  className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                >
                  <span className="w-6 text-center text-base">
                    {MEDALHAS[i] ?? <span className="text-xs font-bold text-zinc-400">{i + 1}</span>}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {e.nome}
                    <span className="ml-1.5 text-xs font-normal text-zinc-400">· {e.rede_nome}</span>
                  </span>
                  <span className="text-sm font-bold tabular-nums">{nota(e.media_geral)}</span>
                </button>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

/** Dashboard do ADMIN GLOBAL: consolidação de TODAS as redes, com drill-down
 *  para uma rede (o panorama daquela rede) e de volta. */
export function PanoramaGlobal() {
  const [redeSel, setRedeSel] = useState<number | null>(null);
  if (redeSel != null) {
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => setRedeSel(null)}
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-indigo-600 dark:hover:text-indigo-400"
        >
          <ChevronLeft size={16} /> Voltar para todas as redes
        </button>
        <PainelRede redeId={redeSel} modo="analise" />
      </div>
    );
  }
  return <ConteudoGlobal aoAbrirRede={setRedeSel} />;
}
