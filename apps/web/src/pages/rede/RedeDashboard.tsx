/**
 * Painel da Rede (`/rede`, área administrativa da Secretaria e do admin global) e o
 * Panorama de UMA rede que o admin global abre na Visão Global.
 *
 * Painel da Rede (modo "secretaria"), de cima para baixo: o PROGRESSO das metas (a
 * conclusão) ao lado do cadastro delas; a Vitrine pública ao lado do cartão "Comparar as
 * escolas" (só links: Comparar escolas e Ranking da Rede — a lista "Ranking das escolas" que
 * havia aqui duplicava o Ranking da Rede); o mapa ao lado dos alertas de uso das plataformas
 * (a regra do painel: sem alunos, sem dado, adoção baixa, índice baixo — por onde a escola
 * também se abre); o boletim no cabeçalho. Os resultados por escola moram nas telas da
 * Secretaria (Avaliações externas, Elefante e Matific, Comparar escolas, Escolas em
 * acompanhamento) — este painel só aponta para elas.
 *
 * Panorama da rede (modo "analise"): só o admin global, ao abrir uma rede na Visão Global
 * (a Secretaria tem o Panorama da Rede próprio, `secretaria/PanoramaSecretaria`). O que ele
 * tinha para a Secretaria continua para ela noutro lugar: volume e Leitura/Matemática em
 * Elefante e Matific; Top 5, Comparativo e a Equidade ("Diferença entre escolas") no Ranking
 * da Rede; metas e as escolas com alerta de uso, aqui no Painel da Rede (e no boletim).
 *
 * As METAS (progresso + cadastro, `MetasDaRede`) e a VITRINE PÚBLICA (`VitrinePublica`)
 * moram em `./comum` — o Panorama da Rede também as mostra (DESENHO3 §2) sem arrastar o mapa —
 * e são reexportadas daqui. O antigo "Panorama Geral da <escola>" (escola escolhida no
 * contexto) saiu: a escola da rede tem a ficha própria (`/rede/escolas/:id`).
 *
 * Mapa geográfico com Leaflet + OpenStreetMap — sem chave de API, sem enviar dados de
 * criança a terceiros. Só dados AGREGADOS por escola saem do backend; o isolamento por
 * rede é garantido no servidor (`exigir_rede`), esta tela apenas exibe.
 *
 * Identidade visual v2 (docs/design/IDENTIDADE-VISUAL-V2.md): KPIs principais em
 * StatCard com tom, a faixa secundária num cartão só, medalhas 1/2/3 (no lugar dos
 * emojis), Leitura = violeta e Matemática = teal. Nenhuma variação "▲ %" aparece:
 * o `/dashboard` da rede não tem série temporal (seria número inventado).
 *
 * ATENÇÃO (testes estruturais): os títulos "Comparativo entre escolas" e "Equidade da
 * rede" são filhos DIRETOS do cartão (o `closest("div")` do título tem de conter a
 * tabela/números); o do Top 5 fica num cabeçalho que é filho direto do cartão; o StatCard
 * "Melhor escola" fica direto na grade dos KPIs. Ícones novos entram DENTRO do h2 (span
 * sem texto) para não mudar isso.
 */
import "leaflet/dist/leaflet.css";

import L from "leaflet";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Building2,
  Calculator,
  ChevronDown,
  ChevronLeft,
  FileDown,
  GitCompareArrows,
  Globe,
  GraduationCap,
  ListOrdered,
  MapPin,
  Scale,
  Settings2,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import { Link, useNavigate } from "react-router-dom";

import { SeloFrescorDaRede } from "../../components/SeloFrescor";
import {
  Botao,
  Card,
  Carregando,
  Erro,
  IconePastel,
  Medalha,
  Mensagem,
  PageHeader,
  RotuloSecao,
  Skeleton,
  StatCard,
  Vazio,
  classesTabela,
  estiloInput,
  type TomPastel,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { rotuloDasPlataformas, useModulos } from "../../hooks/useModulos";
import { apiDownload } from "../../lib/api";
import { corPorIndice } from "../../lib/cores";
import { nota, numero, tempoLeitura } from "../../lib/formato";
import { SeloNatureza } from "../analise/comum";
import type { EstadoDaVisaoEscola } from "../VisaoEscola";
import {
  AvisoTotaisParciais,
  EnvolucroRede,
  INICIO_GLOBAL,
  MEDALHAS,
  MetasDaRede,
  ProgressoMetas,
  TituloCartao,
  ValorProtegido,
  VitrinePublica,
  type DashboardRede,
  type EscolaCartao,
  type MetaProgresso,
} from "./comum";

// Re-export para compatibilidade dos consumidores que já importavam daqui (e as metas e a
// vitrine, que o Panorama da Rede também mostra — ele as importa de `./comum`, sem o mapa).
export { EnvolucroRede, MEDALHAS, MetasDaRede, VitrinePublica };
export type { DashboardRede, EscolaCartao };

/** A escola entra nas COMPARAÇÕES entre escolas (Top 5, Comparativo, posição e
 *  índice das listas)? Quem decide é o backend: `comparada` no cartão do
 *  `/dashboard` é a MESMA régua do Ranking da Rede, da equidade e do índice da
 *  rede — algum aluno que concorre (1º–5º ano) tem dado.
 *
 *  `alunos_com_dados > 0` não serve: é COBERTURA e conta a Educação Infantil.
 *  Com ele, a escola em que só a Fase usa a plataforma entrava no Comparativo
 *  com índice 0, logo acima do cartão de Equidade que já a deixava de fora, e
 *  no Top 5 "Engajamento" com uma posição que o ranking completo não tem.
 *
 *  Sem a marca (bundle servido pelo cache do PWA contra uma API anterior), cai
 *  em `dimensoes_pontuadas`, que é exatamente o que o backend testa; sem os dois,
 *  na regra antiga, para o painel não esvaziar. */
function escolaComparada(e: EscolaCartao & { comparada?: boolean }): boolean {
  if (typeof e.comparada === "boolean") return e.comparada;
  if (Array.isArray(e.dimensoes_pontuadas)) return e.dimensoes_pontuadas.length > 0;
  return e.alunos_com_dados > 0;
}

// Cor da escola FORA da comparação (sem aluno do 1º–5º ano com dado): neutra.
// Pintada pela faixa do índice, o 0 dela sairia vermelho, como "pior escola".
const COR_FORA_DA_COMPARACAO = "#8A8EA9"; // zinc-400 da v2 (3,2:1 sobre o branco)

/** Os textos que mandam o usuário a outra tela usam o nome (e, dentro de um acordeão, o
 *  caminho) que ELE vê no menu (Layout.tsx) — não "Dashboard" nem "aba Secretaria". O
 *  Panorama de uma rede (modo "analise") só o admin global abre, na Visão Global (o
 *  `INICIO_GLOBAL` de `./comum`); no menu dele o Painel da Rede fica no acordeão "Redes e
 *  municípios". */
const CAMINHO_PAINEL_GLOBAL = "Redes e municípios › Painel da Rede";

/** Os sinais POR ESCOLA das avaliações externas e das plataformas (outra regra, outras
 *  fontes que a do painel) moram em "Escolas em acompanhamento" — link da rede MOSTRADA, só
 *  para quem lê essa rede (a Secretaria dela ou o admin global — RotaRede); o global leva a
 *  rede junto (`rede=`), porque a página dele abre na rede escolhida. */
function linkAcompanhamento(
  usuario: { is_global?: boolean; rede_id?: number | null } | null | undefined, redeId: number,
): string | null {
  if (usuario?.is_global) return `/rede/acompanhamento?rede=${redeId}`;
  return usuario?.rede_id === redeId ? "/rede/acompanhamento" : null;
}

/** Destino de um atalho para outra tela da rede: o global leva a rede mostrada junto. */
function comRede(caminho: string, redeId: number, global: boolean): string {
  return global ? `${caminho}?rede=${redeId}` : caminho;
}

/** DE QUANDO são os dados das plataformas que entram no índice do Constela (e na regra dos
 *  alertas): o contador do Elefante é vitalício — livros acumulados desde o início da conta
 *  de cada aluno —; o Matific é cortado no ano letivo. Só cita o que a rede contratou (o
 *  mesmo cuidado de `rotuloDasPlataformas`). */
function periodoDasPlataformas(modulos: string[]): string {
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  const elefante = "Elefante: livros acumulados desde o início da conta de cada aluno";
  const matific = "Matific: no ano letivo";
  if (leitura && !matematica) return elefante;
  if (matematica && !leitura) return matific;
  return `${elefante}; ${matific}`;
}

/** Título (h1) de "/rede": o nome da trilha do topo e do menu da Secretaria. */
const TITULO_PAINEL = "Painel da Rede";

/** Classes da grade de KPIs conforme a quantidade (classes estáticas para o Tailwind).
 *  Duas por linha já no celular (como no tablet): uma por linha, os quatro cartões
 *  de ~170 px com o lado direito vazio tomavam quase duas telas de rolagem. O espaço
 *  entre eles é 12 px no celular (`gap-3 sm:gap-5`) e os 20 px de sempre do `sm` para cima. */
const GRADE_KPIS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-2 lg:grid-cols-3",
  4: "grid-cols-2 lg:grid-cols-4",
};

/** Posição com medalha (1º–3º) ou bolinha numerada (demais). */
function Posicao({ posicao }: { posicao: number }) {
  if (posicao >= 1 && posicao <= 3) {
    return <Medalha posicao={posicao as 1 | 2 | 3} semFita tamanho={30} />;
  }
  return (
    <span className="inline-grid h-7 w-7 place-items-center rounded-full bg-zinc-100 text-xs font-bold tabular-nums text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
      {posicao}º
    </span>
  );
}

/** Indicador compacto (faixa secundária e cartões de plataforma). */
function KpiCompacto({ rotulo, valor, detalhe, titulo, className = "" }: {
  rotulo: string; valor: string; detalhe?: string; titulo?: string; className?: string;
}) {
  return (
    <div className={`min-w-0 rounded-2xl bg-zinc-50 p-3.5 dark:bg-zinc-800/50 ${className}`} title={titulo}>
      <p className="break-words text-2xl font-bold leading-none tracking-tight text-zinc-900 tabular-nums dark:text-white">{valor}</p>
      <p className="mt-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-300">{rotulo}</p>
      {detalhe && <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{detalhe}</p>}
    </div>
  );
}

/** Chips de critério (botões com aria-pressed — os testes os procuram como "button").
 *  No celular cada chip tem 40 px de altura (alvo de toque); do `sm` para cima, os
 *  28 px de sempre. */
function ChipsCriterio({ opcoes, atual, aoEscolher, rotulo }: {
  opcoes: { rotulo: string }[]; atual: number; aoEscolher: (i: number) => void; rotulo: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5 max-sm:gap-2" role="group" aria-label={rotulo}>
      {opcoes.map((opt, i) => (
        <button
          key={opt.rotulo}
          type="button"
          aria-pressed={i === atual}
          onClick={() => aoEscolher(i)}
          className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors max-sm:min-h-10 ${
            i === atual
              ? "bg-indigo-600 text-white shadow-pilula"
              : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
          }`}
        >
          {opt.rotulo}
        </button>
      ))}
    </div>
  );
}

function iconeEscola(cartao: EscolaCartao): L.DivIcon {
  // Pinta pelo ÍNDICE (0–1000, per capita) — o mesmo número que ordena o
  // ranking. Pela média 0–100 (régua interna de cada escola), o mapa contradizia
  // a lista: a escola que mais lê por aluno aparecia vermelha em 1º lugar.
  const cor = escolaComparada(cartao) ? corPorIndice(cartao.pontuacao_geral ?? 0) : COR_FORA_DA_COMPARACAO;
  return L.divIcon({
    className: "",
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${cor};
      border:3px solid #fff;box-shadow:0 2px 8px rgba(23,25,59,.35)"></div>`,
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
      <div className="flex h-[420px] flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-300 bg-zinc-50/60 p-6 text-center dark:border-zinc-700 dark:bg-zinc-800/30">
        <span aria-hidden className="mb-4 grid h-14 w-14 place-items-center rounded-full bg-indigo-50 text-indigo-500 dark:bg-indigo-500/15 dark:text-indigo-300">
          <MapPin size={24} />
        </span>
        <p className="text-[15px] font-semibold text-zinc-800 dark:text-zinc-100">
          Nenhuma escola tem localização cadastrada ainda.
        </p>
        <p className="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
          Assim que as coordenadas (latitude/longitude) forem preenchidas — por geocodificação em
          lote ou manualmente — as escolas aparecem no mapa.
        </p>
      </div>
    );
  }

  return (
    <div className="h-[420px] overflow-hidden rounded-2xl border border-zinc-200 dark:border-zinc-800">
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
                  {escolaComparada(escola)
                    ? <>Índice <b>{numero(Math.round(escola.pontuacao_geral ?? 0))}</b>/1000</>
                    : "Fora da comparação"} · adoção {nota(escola.adocao)}%
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

/** A LEGENDA do mapa: o que a cor do marcador mede e as faixas, cada uma com a bolinha da
 *  cor (a cor nunca é o único código). As cores saem de `corPorIndice` — a mesma função do
 *  marcador —, e o vermelho começa no corte do alerta ao lado (300, `INDICE_BAIXO`). */
function LegendaMapa({ modulos }: { modulos: string[] }) {
  const faixas: { cor: string; texto: string }[] = [
    { cor: corPorIndice(660), texto: "verde: 660 ou mais" },
    { cor: corPorIndice(300), texto: "âmbar: de 300 a 659" },
    { cor: corPorIndice(0), texto: "vermelho: abaixo de 300" },
    { cor: COR_FORA_DA_COMPARACAO, texto: "cinza: fora da comparação (sem aluno do 1º ao 5º ano com dado)" },
  ];
  return (
    <div className="mt-3 space-y-2 text-xs text-zinc-600 dark:text-zinc-400" data-testid="legenda-mapa">
      <div className="flex flex-wrap items-center gap-2">
        <SeloNatureza natureza="calculado" />
        <span className="min-w-0 flex-1">
          Cor do marcador = índice do Constela da escola (0 a 1000; 1000 = melhor escola da rede), pelos dados das
          plataformas ({periodoDasPlataformas(modulos)}).
        </span>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {faixas.map((f) => (
          <li key={f.texto} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: f.cor }} />
            {f.texto}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Um atalho do cartão "Comparar as escolas": o destino, o que ele mostra e de quem é a medida. */
function AtalhoComparacao({ para, icone, titulo, texto }: {
  para: string; icone: LucideIcon; titulo: string; texto: string;
}) {
  return (
    <li>
      <Link
        to={para}
        className="group flex items-start gap-3 rounded-2xl border border-zinc-200/80 p-3.5 transition-colors hover:border-indigo-300 hover:bg-indigo-50/40 dark:border-zinc-800 dark:hover:border-indigo-500/40 dark:hover:bg-indigo-500/5"
      >
        <IconePastel icone={icone} tom="violeta" tamanho="sm" />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900 group-hover:text-indigo-700 dark:text-zinc-50 dark:group-hover:text-indigo-300">
            {titulo} <ArrowRight size={14} aria-hidden className="shrink-0" />
          </span>
          <span className="mt-0.5 block text-xs text-zinc-600 dark:text-zinc-400">{texto}</span>
        </span>
      </Link>
    </li>
  );
}

/** COMPARAR AS ESCOLAS — no lugar da lista "Ranking das escolas" (posição + índice), que
 *  repetia o Ranking da Rede dentro do painel administrativo. Cada comparação tem UM lugar:
 *  os resultados oficiais e o uso das plataformas, escola por escola, em Comparar escolas; a
 *  pontuação do Constela (outra medida), no Ranking da Rede. Os links levam a rede mostrada
 *  junto quando quem lê é o admin global. */
function CompararAsEscolas({ redeId, global, modulos }: { redeId: number; global: boolean; modulos: string[] }) {
  // O uso das plataformas nomeia só o que a rede contratou (o mesmo cuidado do menu).
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  const usoDe = leitura && !matematica ? "do Elefante Letrado" : matematica && !leitura ? "do Matific" : "do Elefante e do Matific";
  return (
    <Card className="flex min-w-0 flex-col p-5 sm:p-6">
      <TituloCartao icone={GitCompareArrows} className="mb-1">Comparar as escolas</TituloCartao>
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        As comparações entre as escolas ficam nas telas próprias, cada uma com a sua medida.
      </p>
      <ul className="space-y-2.5" data-testid="comparar-as-escolas">
        <AtalhoComparacao
          para={comRede("/rede/escolas", redeId, global)} icone={GitCompareArrows} titulo="Escolas"
          texto={`Todas as escolas, o uso ${usoDe} lado a lado e a ficha de cada uma, em ordem alfabética.`} />
        <AtalhoComparacao
          para={comRede("/rede/ranking", redeId, global)} icone={ListOrdered} titulo="Ranking da Rede"
          texto={`A pontuação do Constela, calculada a partir das plataformas (${periodoDasPlataformas(modulos)}), com a diferença entre as escolas.`} />
      </ul>
    </Card>
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

// Critérios da comparação entre REDES (Admin Global). Lista própria porque o
// cartão de REDE tem um subconjunto diferente de campos — usar METRICAS_TOP aqui
// renderizaria `undefined` (ex.: adocao_elefante não existe por rede).
const METRICAS_REDE: {
  chave: keyof RedeCartao; rotulo: string; sufixo?: string; indice?: boolean;
}[] = [
  // O padrão é o ÍNDICE per capita (comparável entre redes de tamanhos
  // diferentes). As médias 0–100 seguem disponíveis, mas são régua interna de
  // cada escola — ordenar redes por elas premiava homogeneidade, não nível.
  { chave: "pontuacao_geral", rotulo: "Índice Geral", indice: true },
  { chave: "livros_por_matricula", rotulo: "Livros/aluno" },
  { chave: "adocao", rotulo: "Engajamento", sufixo: "%" },
  { chave: "media_geral", rotulo: "Média interna" },
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
  // Entrada = a do Ranking da Rede (`escolaComparada`), em TODOS os critérios,
  // inclusive Engajamento: é o resumo dele, e o atalho leva para lá.
  // `null` (≠ ausente) = o critério está escondido da Secretaria nesta escola (grupo
  // pequeno): a escola sai do Top 5 desse critério, como no ranking — nunca com 0.
  const top = useMemo(
    () => [...escolas]
      .filter((e) => escolaComparada(e) && e[m.chave] !== null)
      .sort((a, b) => val(b) - val(a)
        || b.adocao - a.adocao
        || a.nome.localeCompare(b.nome, "pt-BR"))
      .slice(0, 5),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `val` deriva de m.chave
    [escolas, m.chave],
  );
  return (
    <Card className="flex flex-col p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          <IconePastel icone={Trophy} tom="ambar" tamanho="sm" />
          Top 5 escolas da rede
        </h2>
        <ChipsCriterio opcoes={METRICAS_TOP} atual={metrica} aoEscolher={setMetrica} rotulo="Critério do Top 5" />
      </div>
      {top.length === 0 ? (
        <Vazio icone={Trophy} titulo="Sem dados ainda."
               descricao="Quando as escolas tiverem dado das plataformas, as cinco melhores aparecem aqui." />
      ) : (
        <>
          <div className={classesTabela.moldura}>
            <table className={`${classesTabela.tabela} tabular-nums`}>
              <thead>
                <tr>
                  <th scope="col" className={`${classesTabela.th} w-16`}>Pos.</th>
                  <th scope="col" className={classesTabela.th}>Escola</th>
                  <th scope="col" className={`${classesTabela.th} text-right`}>{m.rotulo}</th>
                </tr>
              </thead>
              <tbody>
                {top.map((e, i) => (
                  <tr key={e.escola_id} className={classesTabela.tr}>
                    <td className="px-4 py-2.5"><Posicao posicao={i + 1} /></td>
                    <td className="px-4 py-2.5">
                      <button
                        type="button"
                        onClick={() => aoAbrir(e.escola_id)}
                        className="flex min-w-0 items-center gap-3 text-left font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
                      >
                        <IconePastel icone={Building2} tom="violeta" tamanho="sm" className="hidden sm:grid" />
                        {/* Até duas linhas (com o nome inteiro no title): com `truncate` numa
                            célula de tabela o nome não encolhia e empurrava a coluna do
                            índice — o número do ranking — para fora do cartão. */}
                        <span className="line-clamp-2 min-w-0 break-words" title={e.nome}>{e.nome}</span>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right text-lg font-bold text-indigo-700 tabular-nums dark:text-indigo-300">
                      {m.indice ? numero(Math.round(val(e))) : nota(val(e))}
                      {m.sufixo ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            type="button"
            onClick={() => navegar("/rede/ranking")}
            className="mt-4 inline-flex items-center gap-1.5 self-start rounded-lg text-sm font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-300 dark:hover:text-indigo-200"
          >
            Ver ranking completo <ArrowRight size={15} aria-hidden />
          </button>
        </>
      )}
    </Card>
  );
}

/** Escolas com alerta pela REGRA DO PAINEL (`motivo_atencao` do `/dashboard`: sem alunos,
 *  sem dado das plataformas, adoção baixa, índice baixo frente à rede), no padrão "destaques".
 *  No Painel da Rede o cartão se chama "Escolas com alerta de uso das plataformas" e diz a
 *  regra e a natureza (calculado pelo Constela, não avaliação oficial) — para não se
 *  confundir com "Escolas em acompanhamento", que lê os sinais das avaliações externas; no
 *  Panorama de uma rede (admin global) mantém o título de sempre.
 *
 *  RECOLHÍVEL, como antes da v2 (era uma SecaoRecolhivel; o recolher saiu sem decisão
 *  registrada e voltou). Não usa a SecaoRecolhivel porque o título dela é só um botão:
 *  aqui o cartão continua com o seu h2 (padrão de acordeão: o botão DENTRO do título),
 *  e o selo com a contagem fica colado ao texto — antes ele ia para a ponta direita
 *  quando o título quebrava em duas linhas.
 *
 *  `acompanhamento`: o link de "Escolas em acompanhamento", numa linha no pé do cartão. A
 *  regra do cartão (os motivos vêm do painel da rede: dados, cobertura) não muda; os sinais
 *  das avaliações externas são outra leitura, com outra fonte — ficam lá. */
function AtencaoRede({ escolas, aoAbrir, acompanhamento, titulo = "Escolas que precisam de atenção", explicacao }: {
  escolas: EscolaCartao[];
  aoAbrir: (id: number) => void;
  acompanhamento?: string | null;
  titulo?: string;
  /** A regra do cartão, em uma frase (no topo do conteúdo). */
  explicacao?: ReactNode;
}) {
  const [aberto, setAberto] = useState(true);
  const idConteudo = useId();
  return (
    <Card className={`p-5 sm:p-6 ${aberto ? "" : "self-start"}`}>
      <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
        <button
          type="button"
          onClick={() => setAberto((a) => !a)}
          aria-expanded={aberto}
          aria-controls={idConteudo}
          className="-m-1 flex w-[calc(100%+0.5rem)] items-center gap-3 rounded-xl p-1 text-left transition-colors hover:text-indigo-600 dark:hover:text-indigo-300"
        >
          <IconePastel icone={AlertTriangle} tom="ambar" tamanho="sm" />
          <span className="min-w-0 flex-1">
            {titulo}
            {escolas.length > 0 && (
              <>
                {" "}
                {/* ouro-50 (não 100): ouro-700 sobre ouro-100 dava 4,39:1 (< 4,5:1); sobre ouro-50, 4,72:1. */}
                <span className="ml-0.5 inline-block rounded-full bg-ouro-50 px-2 py-0.5 align-[0.1em] text-xs font-semibold leading-none text-ouro-700 tabular-nums dark:bg-ouro-400/15 dark:text-ouro-300">
                  {escolas.length}
                </span>
              </>
            )}
          </span>
          <ChevronDown
            size={16}
            aria-hidden
            className={`shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`}
          />
        </button>
      </h2>
      <div id={idConteudo} hidden={!aberto} className="mt-4">
        {explicacao && (
          // Selo em cima e a regra na largura do cartão (lado a lado, a frase longa virava uma
          // coluna estreita).
          <div className="mb-3 flex flex-col items-start gap-1.5 text-xs text-zinc-600 dark:text-zinc-400"
               data-testid="regra-alerta-uso">
            {explicacao}
          </div>
        )}
        {escolas.length === 0 ? (
          // Neutro e preso à regra DESTE cartão: o verde de "tudo certo" e a palavra
          // "acompanhamento" contradiziam "Escolas em acompanhamento" (outra regra, outras fontes).
          // Sem a regra escrita acima (o Panorama de uma rede do admin global), ela vai aqui.
          <p className="rounded-2xl bg-zinc-50 p-4 text-sm text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300"
             data-testid="alerta-vazio">
            {explicacao
              ? "Nenhuma escola com alerta pela regra deste cartão agora."
              : "Nenhuma escola sem alunos, sem dado das plataformas, com adoção abaixo de 40% ou com índice do Constela abaixo de 300 agora."}
          </p>
        ) : (
          <ul className="space-y-1">
            {escolas.map((escola) => (
              <li key={escola.escola_id} className="flex items-start gap-3 rounded-xl px-1 py-2">
                <IconePastel icone={Building2} tom="ambar" tamanho="sm" className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => aoAbrir(escola.escola_id)}
                    className="text-left text-sm font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
                  >
                    {escola.nome}
                  </button>
                  <p className="text-xs text-ouro-700 dark:text-ouro-300">{escola.motivo_atencao}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
        {acompanhamento && (
          <p className="mt-4 border-t border-zinc-100 pt-3 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            Os sinais das avaliações externas e das plataformas, escola por escola, ficam em{" "}
            <Link to={acompanhamento}
                  className="font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-300 dark:hover:text-indigo-200">
              Escolas em acompanhamento
            </Link>.
          </p>
        )}
      </div>
    </Card>
  );
}

// Seção consolidada de UMA plataforma (Elefante ou Matific): KPIs da rede +
// as escolas que mais produzem naquela plataforma. Só agregado, sem PII.
function SecaoPlataforma({
  titulo, icone, tom, kpis, escolas, campoTop, rotuloTop, formatoTop, aoAbrir,
}: {
  titulo: string;
  icone: LucideIcon;
  tom: TomPastel;
  kpis: { rotulo: string; valor: string; titulo?: string }[];
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
    <Card className="min-w-0 p-5 sm:p-6">
      <TituloCartao icone={icone} tom={tom} className="mb-4">{titulo}</TituloCartao>
      <div className="mb-5 grid grid-cols-1 gap-3 min-[400px]:grid-cols-2">
        {kpis.map((k) => <KpiCompacto key={k.rotulo} rotulo={k.rotulo} valor={k.valor} titulo={k.titulo} />)}
      </div>
      <RotuloSecao className="mb-2">Escolas com mais {rotuloTop}</RotuloSecao>
      {top.length === 0 ? (
        <p className="py-2 text-sm text-zinc-500 dark:text-zinc-400">Sem dados ainda.</p>
      ) : (
        <ol className="space-y-1">
          {top.map((e, i) => (
            <li key={e.escola_id}>
              <button
                type="button"
                onClick={() => aoAbrir(e.escola_id)}
                className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
              >
                <Posicao posicao={i + 1} />
                <span className="min-w-0 flex-1 truncate font-medium text-zinc-800 dark:text-zinc-100" title={e.nome}>{e.nome}</span>
                <span className="font-bold tabular-nums text-zinc-900 dark:text-white">{formatoTop(e[campoTop] as number)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function ComparativoRede({ escolas, aoAbrir, modulos }: {
  escolas: EscolaCartao[]; aoAbrir: (id: number) => void; modulos: string[];
}) {
  // Ordena pelo ÍNDICE per capita — a única métrica comparável entre escolas de
  // tamanhos diferentes. As médias 0–100 seguem na tabela, mas rotuladas como o
  // que são: desempenho INTERNO de cada escola (régua = os próprios alunos dela).
  // Só as escolas COMPARADAS: as mesmas que a Equidade, logo abaixo, mede.
  // Só as médias dos MÓDULOS CONTRATADOS: a coluna de um módulo fora do plano mostrava
  // 0,0 em todas as escolas (lido como nota zero) — o mesmo corte do Boletim da Rede.
  const temLeitura = modulos.includes("leitura");
  const temMatematica = modulos.includes("matematica");
  const colunas0a100 = ["Geral", ...(temLeitura ? ["Leitura"] : []), ...(temMatematica ? ["Matific"] : [])];
  const linhas = useMemo(
    () => [...escolas]
      .filter(escolaComparada)
      .sort((a, b) => Number(b.pontuacao_geral ?? 0) - Number(a.pontuacao_geral ?? 0)),
    [escolas],
  );
  if (linhas.length === 0) return null;
  const th = classesTabela.th;
  return (
    <Card className="p-5 sm:p-6">
      <TituloCartao icone={BarChart3} className="mb-4">Comparativo entre escolas</TituloCartao>
      <div className={classesTabela.moldura}>
        <table className={`${classesTabela.tabela} tabular-nums`}>
          <thead>
            <tr>
              <th scope="col" className={th}>Escola</th>
              <th scope="col" className={`${th} text-right`} title="Desempenho por aluno na régua da rede — 1000 é a melhor escola">
                Índice
              </th>
              <th scope="col" className={`${th} text-right`}>Geral</th>
              {temLeitura && <th scope="col" className={`${th} text-right`}>Leitura</th>}
              {temMatematica && <th scope="col" className={`${th} text-right`}>Matific</th>}
              <th scope="col" className={`${th} text-right`}>Engaj.</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((e) => (
              <tr key={e.escola_id} className={classesTabela.tr}>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => aoAbrir(e.escola_id)}
                    className="text-left font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
                  >
                    {e.nome}
                  </button>
                </td>
                <td className="px-4 py-3 text-right text-base font-bold text-indigo-700 dark:text-indigo-300">
                  {numero(Math.round(e.pontuacao_geral ?? 0))}
                </td>
                <td className="px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">{nota(e.media_geral)}</td>
                {temLeitura && (
                  <td className="px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">
                    {e.oculto?.leitura && !e.oculto.leitura.parcial
                      ? <ValorProtegido bloco={e.oculto.leitura} /> : nota(e.media_elefante)}
                  </td>
                )}
                {temMatematica && (
                  <td className="px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">
                    {e.oculto?.matematica && !e.oculto.matematica.parcial
                      ? <ValorProtegido bloco={e.oculto.matematica} /> : nota(e.media_matific)}
                  </td>
                )}
                <td className="px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">{nota(e.adocao)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
        <b>Índice</b> (0–1000): desempenho por aluno na régua da rede — 1000 é a melhor
        escola do município. É o número comparável entre escolas e o que ordena esta tabela.
        <b> {colunas0a100.join(" · ")}</b> (0–100): desempenho interno de cada escola,
        calculado contra os próprios alunos dela — bom para acompanhar a escola no tempo,
        não para compará-la com outra.
      </p>
    </Card>
  );
}

/** O progresso no Panorama de UMA rede (modo "analise": só o admin global, na Visão
 *  Global). O convite manda ao Painel da Rede pelo caminho do menu dele. */
function MetasRede({ redeId }: { redeId: number }) {
  const leitura = useApi<MetaProgresso[]>(`/redes/${redeId}/metas`);
  return (
    <ProgressoMetas
      leitura={leitura}
      titulo="Metas da rede"
      semMeta={<>
        Nenhuma meta definida ainda. Defina as metas da rede em <b>{CAMINHO_PAINEL_GLOBAL}</b>, no menu — o
        progresso (dado real, sem número fictício) aparece aqui.
      </>}
    />
  );
}

function PainelRede({ redeId, modo }: { redeId: number; modo: "analise" | "secretaria" }) {
  const { usuario, selecionarEscola } = useApp();
  const navegar = useNavigate();
  const { dados, erro, carregando, recarregar } = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const global = Boolean(usuario?.is_global);
  const { modulos: modulosDoUsuario } = useModulos();
  // O nome da tela das plataformas segue os módulos CONTRATADOS pela rede mostrada (o do
  // payload; antes de ele chegar, os da conta) — o mesmo nome do item do menu.
  const nomePlataformas = rotuloDasPlataformas(dados?.modulos ?? modulosDoUsuario);
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
    // No Panorama de uma rede (admin global, na Visão Global), trocar a escola só muda o
    // CONTEXTO (o seletor de escola do menu lateral), sem sair da tela — como antes. No
    // Painel da Rede, abre a Visão da Escola.
    if (modo === "secretaria") navegar("/escola");
  };

  const linkDescricao = "font-medium text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300";
  // O cabeçalho (h1) aparece em TODOS os estados — carregando e erro também.
  const cabecalho = (
    <PageHeader
      // "/rede" se chama "Painel da Rede" no menu da Secretaria e na trilha do topo
      // (antes o h1 dizia "Secretaria de Educação": três nomes para a mesma tela).
      titulo={modo === "secretaria" ? TITULO_PAINEL : "Panorama Geral da Rede Municipal"}
      descricao={modo === "secretaria"
        ? (
          <>
            Área administrativa da rede: metas, vitrine pública, boletim e mapa das escolas. Os resultados das escolas
            ficam em{" "}
            <Link to={comRede("/rede/avaliacoes-externas", redeId, global)} className={linkDescricao}>Avaliações externas</Link>,
            {" "}em{" "}
            <Link to={comRede("/rede/plataformas", redeId, global)} className={linkDescricao}>{nomePlataformas}</Link>
            {" "}e em{" "}
            <Link to={comRede("/rede/escolas", redeId, global)} className={linkDescricao}>Escolas</Link>.
          </>
        )
        : "Acompanhe o desempenho, o engajamento e a evolução das escolas da rede."}
      acoes={modo === "secretaria" ? (
        <>
          {/* O seletor de contexto (Toda a Rede ↔ escola) é ÚNICO e vive no cartão do
              rodapé do menu lateral — nada de seletor duplicado aqui. Os resultados (antes
              "Análise educacional", hoje telas próprias da Secretaria) entram pelos links
              da descrição e pelo menu; aqui fica só o que é desta área. */}
          <Botao variante="secundario" onClick={baixarBoletim} disabled={baixando}>
            <FileDown size={15} aria-hidden /> {baixando ? "Gerando..." : "Baixar boletim (PDF)"}
          </Botao>
          {usuario?.is_global && (
            <Botao onClick={() => navegar("/rede/gerenciar")}>
              <Settings2 size={15} aria-hidden /> Gerenciar redes
            </Botao>
          )}
        </>
      ) : undefined}
    />
  );

  // Carregando: só o esqueleto (o título entra junto com os números — as telas e os
  // testes leem o título como "o painel chegou").
  if (carregando && !dados) {
    return (
      <div className="space-y-6">
        <span className="sr-only">Carregando a rede...</span>
        <Skeleton className="h-9 w-80 max-w-full" />
        <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4" aria-hidden>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36 rounded-cartao" />)}
        </div>
        <Skeleton className="h-64 rounded-cartao" />
      </div>
    );
  }
  if (erro && !dados) {
    return (
      <div className="space-y-6">
        {cabecalho}
        <Card><Erro titulo="Não foi possível carregar a rede" descricao={erro.message} aoTentar={recarregar} /></Card>
      </div>
    );
  }
  if (!dados) return null;

  const t = dados.totais;
  // MÓDULOS CONTRATADOS pela rede exibida (vem do payload — o admin global pode
  // estar vendo uma rede diferente da dele, então não uso o hook do usuário).
  const mods = dados.modulos ?? ["leitura", "matematica"];
  const temLeitura = mods.includes("leitura");
  const temMatematica = mods.includes("matematica");
  const eq = dados.equidade;
  const kpisPrincipais = 2 + (temLeitura ? 1 : 0) + (temMatematica ? 1 : 0);

  return (
    <div className="space-y-6">
      {cabecalho}
      {boletimErro && <Mensagem tipo="erro">{boletimErro}</Mensagem>}

      {/* --- ANÁLISE (aba Dashboard): panorama estratégico da rede inteira. --- */}
      {modo === "analise" && (
      <>
      {/* DE QUANDO são os números abaixo: cada escola tem o seu último retrato
          (`/redes/{id}/ranking/frescor`); só os módulos contratados. */}
      <div className="-mt-3">
        <SeloFrescorDaRede redeId={redeId}
                           dimensoes={[...(temLeitura ? ["leitura" as const] : []),
                                       ...(temMatematica ? ["matematica" as const] : [])]} />
      </div>

      {/* Indicadores PRINCIPAIS (os quatro da referência); o que não foi contratado
          não aparece, nem zerado. Nenhuma pílula de variação: não há série. */}
      <div className={`grid gap-3 sm:gap-5 ${GRADE_KPIS[kpisPrincipais]}`}>
        <StatCard
          icone={<Trophy size={20} />}
          tom="ambar"
          rotulo="Melhor escola"
          valor={t.melhor_escola ? numero(Math.round(t.melhor_escola.pontuacao_geral ?? 0)) : "–"}
          detalhe={t.melhor_escola?.nome ?? "sem dados"}
        />
        <StatCard icone={<Users size={20} />} tom="azul" rotulo="Alunos" valor={numero(t.alunos)} detalhe={`${numero(t.turmas)} turmas`} />
        {temLeitura && (
          <StatCard icone={<BookOpen size={20} />} tom="violeta" rotulo="Livros lidos" valor={numero(t.livros)} detalhe={`${nota(t.livros_por_aluno)} por aluno`} />
        )}
        {temMatematica && (
          <StatCard icone={<Calculator size={20} />} tom="teal" rotulo="Atividades Matific" valor={numero(t.atividades)} detalhe={`${numero(t.estrelas)} estrelas`} />
        )}
      </div>

      {/* Secretaria: escolas com 1 ou 2 alunos com dado numa matéria ficam fora dos totais
          dela (para proteger as crianças) — o painel diz isso junto dos números. */}
      <AvisoTotaisParciais totais={t} />

      {/* Faixa secundária: os demais indicadores consolidados, com menos peso visual. */}
      <Card className="grid grid-cols-2 gap-3 p-4 sm:p-5 lg:grid-cols-4">
        <KpiCompacto rotulo="Escolas" valor={numero(t.escolas)} detalhe={`${t.escolas_ativas} ativas`} />
        <KpiCompacto rotulo="Professores" valor={numero(t.professores)} detalhe="na rede" />
        <KpiCompacto rotulo="Adoção" valor={`${nota(t.adocao)}%`} detalhe="alunos com dados" />
        <KpiCompacto
          rotulo="Média geral"
          valor={nota(t.media_geral)}
          detalhe={[...(temMatematica ? [`Matific ${nota(t.media_matific)}`] : []),
                    ...(temLeitura ? [`Elefante ${nota(t.media_elefante)}`] : [])].join(" · ") || undefined}
          titulo="Média interna (0–100): cada escola é medida contra os próprios alunos"
        />
      </Card>

      {/* Top escolas (a SEDUC escolhe o critério) e a lista de AÇÃO (o que priorizar).
          3:2 (não 2:1): com um terço, o cartão de atenção ficava estreito demais (título
          e nomes quebrando palavra a palavra). Os dois cartões têm a altura da linha. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col [&>*]:flex-1">
          <TopEscolas escolas={dados.escolas} aoAbrir={abrirEscola} />
        </div>
        <AtencaoRede escolas={dados.atencao} aoAbrir={abrirEscola} acompanhamento={linkAcompanhamento(usuario, redeId)} />
      </div>

      {/* Panorama por plataforma — só dos MÓDULOS CONTRATADOS pela rede. O que
          não faz parte do plano não aparece (nem zerado); com um módulo só, o
          card ocupa a largura inteira em vez de deixar buraco. */}
      <div className={`grid gap-6 ${temLeitura && temMatematica ? "lg:grid-cols-2" : ""}`}>
        {temLeitura && <SecaoPlataforma
          titulo="Leitura — Elefante Letrado"
          icone={BookOpen}
          tom="violeta"
          kpis={[
            { rotulo: "Livros lidos", valor: numero(t.livros) },
            { rotulo: "Por aluno", valor: nota(t.livros_por_aluno) },
            { rotulo: "Alunos com dados", valor: numero(t.ativos_elefante),
              titulo: "Alunos com retrato do Elefante Letrado (inclui quem ainda não leu)" },
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
          icone={Calculator}
          tom="teal"
          kpis={[
            { rotulo: "Estrelas", valor: numero(t.estrelas) },
            { rotulo: "Atividades", valor: numero(t.atividades) },
            { rotulo: "Alunos com dados", valor: numero(t.ativos_matific),
              titulo: "Alunos com retrato do Matific (inclui quem ainda não fez atividade)" },
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
      <ComparativoRede escolas={dados.escolas} aoAbrir={abrirEscola} modulos={mods} />

      {/* Equidade e Metas com a altura da linha (antes sobrava um vão embaixo do menor). */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Equidade: quão distante está a melhor da pior escola — medida no ÍNDICE
            per capita, o único número comparável entre escolas. Na média 0–100 ela
            respondia à dispersão INTERNA de cada escola, não à distância real. */}
        <Card className="p-5 sm:p-6">
          <h2 className="mb-4 flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            <IconePastel icone={Scale} tom="azul" tamanho="sm" />
            Equidade da rede
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">Diferença entre a melhor e a pior escola</p>
          <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
            <b className="text-[32px] font-bold leading-none tracking-tight text-zinc-900 tabular-nums dark:text-white">
              {numero(Math.round(eq.gap_indice ?? 0))}
            </b>
            <span className="text-sm text-zinc-600 dark:text-zinc-300">pontos de índice</span>
            <span className="text-sm text-zinc-500 tabular-nums dark:text-zinc-400">
              ({numero(Math.round(eq.escola_menor_indice ?? 0))} → {numero(Math.round(eq.escola_maior_indice ?? 0))} de 1000)
            </span>
          </p>
          <p className="mt-4 rounded-2xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300">
            <b className="tabular-nums text-zinc-900 dark:text-white">{eq.escolas_abaixo_do_indice_medio ?? 0}</b> escola(s) abaixo do índice médio da rede
          </p>
        </Card>

        {/* Metas da rede — progresso REAL (alvo cadastrado no painel /rede). */}
        <MetasRede redeId={redeId} />
      </div>
      </>
      )}

      {/* --- PAINEL DA REDE (/rede): funções administrativas + mapa/navegação. --- */}
      {modo === "secretaria" && (
      <>
      {/* Metas: o PROGRESSO (a conclusão, que antes só aparecia no Panorama antigo) ao
          lado do cadastro, com uma leitura só — salvar uma meta atualiza os dois. */}
      <MetasDaRede redeId={redeId} />

      {/* Vitrine e "Comparar as escolas" (só links) com a altura da linha. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <VitrinePublica redeId={redeId} />
        <CompararAsEscolas redeId={redeId} global={global} modulos={mods} />
      </div>

      {/* Mapa e os alertas de uso das plataformas em metades. A lista "Ranking das
          escolas" que ficava aqui (posição + índice) repetia o Ranking da Rede: saiu. A
          escola se abre pelo mapa, pelos alertas ou pelo seletor do menu lateral. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="min-w-0 p-5 sm:p-6">
          <TituloCartao icone={MapPin} className="mb-4">Distribuição geográfica</TituloCartao>
          <MapaRede escolas={dados.escolas} aoAbrir={abrirEscola} />
          {/* Sem a legenda, a cor era o único código (e o vermelho não batia com o alerta ao
              lado). Só com marcador no mapa. */}
          {dados.escolas.some((e) => e.latitude != null && e.longitude != null) && <LegendaMapa modulos={mods} />}
        </Card>
        <AtencaoRede
          escolas={dados.atencao}
          aoAbrir={abrirEscola}
          titulo="Escolas com alerta de uso das plataformas"
          explicacao={(
            <>
              <SeloNatureza natureza="calculado" />
              <span className="min-w-0 flex-1">
                Regra do painel, com os dados das plataformas ({periodoDasPlataformas(mods)}): escola sem alunos, sem
                dado, com adoção abaixo de 40% ou com índice abaixo de 300 (de 0 a 1000; 1000 = melhor escola da rede). Não é
                avaliação oficial.
              </span>
            </>
          )}
          acompanhamento={linkAcompanhamento(usuario, redeId)}
        />
      </div>
      </>
      )}
    </div>
  );
}

/** Panorama ANALÍTICO de UMA rede — o que o admin global vê ao abrir uma rede na Visão
 *  Global (`PanoramaGlobal`). Deixou de ser a página inicial da Secretaria, que tem o
 *  Panorama da Rede próprio (`secretaria/PanoramaSecretaria`, conclusão primeiro): o que
 *  este painel mostrava a ela continua noutro lugar (ver o comentário do topo). */
export function PanoramaDaRede({ redeId }: { redeId: number }) {
  return <PainelRede redeId={redeId} modo="analise" />;
}

/** Painel da Rede (/rede) — administrativo: metas (progresso e cadastro), vitrine pública,
 *  boletim, mapa, alertas de uso e os atalhos para comparar as escolas. */
export default function RedeDashboard() {
  return (
    <EnvolucroRede titulo={TITULO_PAINEL}
                   descricao="Área administrativa da rede: metas, vitrine pública, boletim e mapa das escolas.">
      {(redeId) => <PainelRede redeId={redeId} modo="secretaria" />}
    </EnvolucroRede>
  );
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
  // Comparação ENTRE REDES: per capita + índice 0–1000 na coorte "todas as
  // redes" (mesmo motor das escolas, outro escopo).
  livros_por_matricula: number;
  estrelas_por_matricula: number;
  pontuacao_geral: number;
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
  const { dados, erro, carregando, recarregar } = useApi<DashboardGlobal>("/redes/panorama-global");
  const { selecionarEscola } = useApp();
  const navegar = useNavigate();
  const [metrica, setMetrica] = useState(0);
  const m = METRICAS_REDE[metrica];
  const redesRanked = useMemo(
    () => [...(dados?.redes ?? [])]
      .sort((a, b) => Number(b[m.chave] ?? 0) - Number(a[m.chave] ?? 0)),
    [dados, m.chave],
  );
  const cabecalho = (acoes?: ReactNode) => (
    <PageHeader
      titulo="Panorama Global — Todas as Redes"
      descricao="Visão consolidada de todas as redes às quais você tem acesso. Selecione uma rede para aprofundar."
      acoes={acoes}
    />
  );
  // Carregando: sem o título (ele entra junto com os números).
  if (carregando && !dados) return <Carregando texto="Carregando as redes..." />;
  if (erro && !dados) {
    return (
      <div className="space-y-6">
        {cabecalho()}
        <Card><Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} /></Card>
      </div>
    );
  }
  if (!dados) return null;
  const t = dados.totais;
  // A Visão da Escola volta para cá, com o nome do menu do global ("/" = Visão Global) — sem a
  // origem ela voltava ao Painel da Rede, que abre a rede da conta (ou a primeira da lista).
  const abrirEscola = (id: number) => {
    selecionarEscola(id);
    const volta: EstadoDaVisaoEscola = { voltar: { caminho: "/", texto: `Voltar para a ${INICIO_GLOBAL}` } };
    navegar("/escola", { state: volta });
  };
  // O cabeçalho padrão da tabela com padding lateral menor (8 colunas num cartão).
  const thNum = classesTabela.th.replace("px-4", "px-3");

  return (
    <div className="space-y-6">
      {cabecalho(
        <select
          aria-label="Selecionar rede"
          className={`${estiloInput} w-auto font-medium`}
          value=""
          onChange={(e) => { const id = Number(e.target.value); if (id) aoAbrirRede(id); }}
        >
          <option value="">🌎 Todas as redes</option>
          {[...dados.redes].sort((a, b) => a.nome.localeCompare(b.nome)).map((r) => (
            <option key={r.rede_id} value={r.rede_id}>{r.nome}</option>
          ))}
        </select>,
      )}

      {/* Quatro indicadores principais; "Escolas" aparece UMA vez só. */}
      <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4">
        <StatCard icone={<Globe size={20} />} tom="violeta" rotulo="Redes" valor={numero(t.redes)} detalhe="com acesso" />
        <StatCard
          icone={<Building2 size={20} />}
          tom="ambar"
          rotulo="Escolas"
          valor={numero(t.escolas)}
          detalhe={`${numero(t.escolas_em_atencao)} em atenção`}
        />
        <StatCard icone={<Users size={20} />} tom="azul" rotulo="Alunos" valor={numero(t.alunos)} detalhe={`${numero(t.turmas)} turmas`} />
        <StatCard icone={<GraduationCap size={20} />} tom="rosa" rotulo="Professores" valor={numero(t.professores)} detalhe="em todas as redes" />
      </div>

      {/* No celular, duas por linha e a "Média geral" (detalhe mais longo) na linha toda;
          do `sm` para cima, as três lado a lado de sempre. */}
      <Card className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 sm:p-5">
        <KpiCompacto rotulo="Livros lidos" valor={numero(t.livros)} detalhe="em todas as redes" />
        <KpiCompacto rotulo="Atividades Matific" valor={numero(t.atividades)} detalhe={`${numero(t.estrelas)} estrelas`} />
        <KpiCompacto
          className="col-span-2 sm:col-span-1"
          rotulo="Média geral"
          valor={nota(t.media_geral)}
          detalhe={`Matific ${nota(t.media_matific)} · Elefante ${nota(t.media_elefante)}`}
          titulo="Média interna (0–100): cada escola é medida contra os próprios alunos"
        />
      </Card>

      {/* Comparação / ranking entre redes por indicador. */}
      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            <IconePastel icone={BarChart3} tom="violeta" tamanho="sm" />
            Comparação entre redes
          </h2>
          <ChipsCriterio opcoes={METRICAS_REDE} atual={metrica} aoEscolher={setMetrica} rotulo="Critério da comparação" />
        </div>
        {redesRanked.length === 0 ? (
          // Sem rede nenhuma: antes ficava só a linha de cabeçalho da tabela, muda.
          <Vazio
            icone={BarChart3}
            titulo="Nenhuma rede para comparar ainda."
            descricao="Quando houver redes cadastradas, elas aparecem aqui lado a lado."
            acao={(
              <Botao onClick={() => navegar("/rede/gerenciar")}>
                <Settings2 size={15} aria-hidden /> Gerenciar redes
              </Botao>
            )}
          />
        ) : (
        <div className={classesTabela.moldura}>
          {/* Colunas de número com padding menor e o nome da rede com largura mínima
              (" · UF" sem quebra): em tela estreita o nome quebrava uma palavra por linha
              e a última coluna saía do cartão. Se ainda assim não couber, a moldura rola. */}
          <table className={`${classesTabela.tabela} tabular-nums`}>
            <thead>
              <tr>
                <th scope="col" className={`${thNum} w-14`}>#</th>
                <th scope="col" className={thNum}>Rede</th>
                <th scope="col" className={`${thNum} text-right`}>Escolas</th>
                <th scope="col" className={`${thNum} text-right`}>Alunos</th>
                <th scope="col" className={`${thNum} text-right`}>{m.rotulo}</th>
                <th scope="col" className={`${thNum} text-right`}>Leitura</th>
                <th scope="col" className={`${thNum} text-right`}>Matific</th>
                <th scope="col" className={`${thNum} text-right`}>Engaj.</th>
              </tr>
            </thead>
            <tbody>
              {redesRanked.map((r, i) => (
                <tr key={r.rede_id} className={classesTabela.tr}>
                  <td className="px-3 py-2.5"><Posicao posicao={i + 1} /></td>
                  <td className="px-3 py-2.5">
                    <button type="button" onClick={() => aoAbrirRede(r.rede_id)}
                            className="min-w-[8rem] text-left font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300">
                      {r.nome}{r.uf && <span className="whitespace-nowrap"> · {r.uf}</span>}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">{numero(r.escolas)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">{numero(r.alunos)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right text-base font-bold text-indigo-700 dark:text-indigo-300">
                    {m.indice ? numero(Math.round(Number(r[m.chave] ?? 0))) : nota(Number(r[m.chave] ?? 0))}
                    {m.sufixo ?? ""}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">{nota(r.media_elefante)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">{nota(r.media_matific)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">{nota(r.adocao)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </Card>

      {/* Melhores escolas de TODAS as redes (com o nome da rede). Uma coluna só, com a
          nota na ponta direita do cartão (como antes da v2): em duas colunas a nota ficava
          solta no meio do cartão e o nome truncava com metade do cartão vazia. */}
      <Card className="p-5 sm:p-6">
        <TituloCartao icone={Trophy} tom="ambar" className="mb-4">Top escolas de todas as redes</TituloCartao>
        {dados.top_escolas.length === 0 ? (
          <Vazio icone={Trophy} titulo="Sem dados ainda."
                 descricao="Quando as escolas tiverem dado das plataformas, as melhores aparecem aqui." />
        ) : (
          <ol className="space-y-1">
            {dados.top_escolas.map((e, i) => (
              <li key={`${e.rede_id}-${e.escola_id}`}>
                <button
                  type="button"
                  onClick={() => abrirEscola(e.escola_id)}
                  className="flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                >
                  <Posicao posicao={i + 1} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-zinc-800 dark:text-zinc-100" title={e.nome}>{e.nome}</span>
                    <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400" title={e.rede_nome}>{e.rede_nome}</span>
                  </span>
                  {/* Índice de escopo GLOBAL: o índice DE REDE de cada escola foi
                      normalizado contra a melhor da própria rede, então comparar
                      escolas de redes diferentes por ele seria inválido. */}
                  <span className="shrink-0 text-base font-bold tabular-nums text-indigo-700 dark:text-indigo-300" title="Índice entre todas as redes (0–1000)">
                    {numero(Math.round(e.pontuacao_geral_global ?? 0))}
                  </span>
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
      <div className="space-y-4">
        <button
          type="button"
          onClick={() => setRedeSel(null)}
          className="inline-flex items-center gap-1 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm font-semibold text-indigo-600 shadow-cartao transition-colors hover:border-indigo-200 hover:text-indigo-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-indigo-300"
        >
          <ChevronLeft size={16} aria-hidden /> Voltar para todas as redes
        </button>
        <PanoramaDaRede redeId={redeSel} />
      </div>
    );
  }
  return <ConteudoGlobal aoAbrirRede={setRedeSel} />;
}
