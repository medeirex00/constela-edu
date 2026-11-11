/**
 * 🏆 Ranking da Rede (Secretaria) — todas as escolas, em 4 visões da MESMA base.
 *
 * Regra que rege a tela: a comparação entre escolas é PER CAPITA. Uma escola
 * GRANDE não sobe só por ter mais alunos — o critério principal da LEITURA é
 * "livros ÷ alunos". A pontuação (índice 0–1000) é esse mesmo indicador
 * normalizado na régua da REDE (melhor escola = 1000), então a ordem e a nota
 * nunca se contradizem, e a Secretaria consegue responder "por que essa escola
 * está nessa posição?" — os indicadores REAIS ficam ao lado da pontuação.
 *
 * A ORDEM e a POSIÇÃO vêm do backend (`/redes/{id}/ranking?metrica=`, a régua
 * de `rede.ranking_escolas`: métrica → adoção DAQUELA dimensão → nome); a tela
 * só exibe. Antes ela reordenava o `/dashboard` no navegador com desempate
 * próprio (adoção geral + `localeCompare`) — uma segunda ordem que podia
 * divergir da do backend num empate. O `/dashboard` (o mesmo do Panorama)
 * continua servindo os módulos e a régua do "Como funciona". Só dados por
 * ESCOLA, nunca PII de criança.
 *
 * FRESCOR: `/redes/{id}/ranking/frescor` diz de quando é o dado de cada escola.
 * Comparar a escola que coletou ontem com a que está parada há três semanas é
 * comparar retratos de épocas diferentes — a tela avisa, por escola.
 *
 * PERÍODO (`periodoDoRanking`): os alunos são os matriculados no ano letivo ativo, mas o
 * contador do Elefante é VITALÍCIO (o retrato mais recente de cada aluno, sem corte de ano —
 * `rede._totais_plataforma_por_escola`); só o Matific é cortado no ano letivo
 * (`_matific_no_ano_ativo`). A tela diz isso por extenso, como a tela das plataformas, em vez
 * de chamar o índice inteiro de "ano letivo".
 *
 * Identidade visual v2: abas segmentadas violeta, tabela em cartão com medalhas de
 * fita no top 3 e a métrica que ordena em destaque, "Exportar lista (CSV)" no
 * cabeçalho e o explicador "Como funciona o ranking?" numa janela (o texto e as
 * fórmulas são os mesmos de antes). Sem pódio de escolas: os valores da tabela
 * já são o destaque, e repeti-los em cartões duplicaria cada número na tela.
 *
 * DIFERENÇA ENTRE ESCOLAS (a equidade do índice, que morava no Panorama antigo da
 * Secretaria): embaixo da tabela, a distância entre a escola de maior e a de menor índice
 * e quantas ficam abaixo do índice médio — os números do `/dashboard`, calculados pelo
 * backend sobre as MESMAS escolas comparadas do ranking. É pontuação do Constela (selo),
 * não avaliação oficial; o uso das plataformas por escola fica em Escolas (`/rede/escolas`) e os
 * resultados oficiais, em Avaliações externas e na ficha de cada escola.
 *
 * Celular (< 640 px): a tabela perde a largura mínima e fica "# | Escola | métrica da
 * aba" (as colunas de contexto já saíam com `ocultarAte`); a métrica que ordena fica
 * presa à direita se ainda faltar largura (`TabelaRolavel` avisa em texto). Os botões
 * do cabeçalho viram uma coluna de mesma largura e as abas, uma grade 2 × 2.
 */
import {
  AlertTriangle, BookOpen, Calculator, CalendarClock, HelpCircle, ListOrdered, Scale, Trophy, Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  ACOES_CELULAR,
  AbasRanking,
  AcoesRanking,
  PosicaoRanking,
  tabelaRanking,
} from "../../components/RankingUi";
import { dataDoDia, type EstadoFrescor, type Frescor } from "../../components/SeloFrescor";
import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Botao, Card, Carregando, Erro, IconePastel, Medalha, Modal, PageHeader, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { rotuloDasPlataformas } from "../../hooks/useModulos";
import { usePerfil } from "../../hooks/usePerfil";
import { api } from "../../lib/api";
import { nomeArquivoCsv, type TabelaCsv } from "../../lib/csvRanking";
import { nota, numero, tempoLeitura } from "../../lib/formato";
import { SeloNatureza } from "../analise/comum";
import type { EstadoDaVisaoEscola } from "../VisaoEscola";
import { AvisoAnosLetivos, EnvolucroRede, anosLetivosMistos, type DashboardRede, type EscolaCartao } from "./comum";

type ChaveAba = "geral" | "leitura" | "matematica" | "engajamento";

/** Uma coluna da tabela: como extrair, formatar e alinhar o valor. `destaque`
 *  marca a métrica PRINCIPAL da aba (a que ordena o ranking). */
interface Coluna {
  rotulo: string;
  curto?: string;                       // cabeçalho abreviado no mobile
  valor: (e: EscolaCartao) => string;
  destaque?: boolean;
  /** Em telas pequenas a coluna some (a principal e o nome nunca somem). */
  ocultarAte?: "sm" | "md" | "lg";
  dica?: string;
}

interface Aba {
  chave: ChaveAba;
  /** Módulo exigido; ausente = vale para qualquer plano. */
  modulo?: string;
  rotulo: string;
  icone: typeof Trophy;
  /** Métrica que ORDENA o ranking desta aba (`?metrica=` do backend, que
   *  devolve a ordem e a posição prontas). */
  metrica: string;
  /** Dimensões cujo frescor importa para esta aba. */
  dimensoes: ("leitura" | "matematica")[];
  colunas: Coluna[];
  /** Texto da aba no "Como funciona"; função quando cita as plataformas (segue os módulos). */
  explicacao: string | ((modulos: string[]) => string);
}

// Formatadores DEFENSIVOS: um indicador AUSENTE (`undefined`: bundle do PWA mais
// novo/velho que a API) vira 0 em vez de derrubar a tabela inteira. `null` é outra
// coisa: o número foi ESCONDIDO da Secretaria (grupo pequeno) e vira "—", nunca 0.
const num = (v: number | null | undefined) => Number(v ?? 0);
const pontos = (v: number | null | undefined) => (v === null ? "—" : numero(Math.round(num(v))));
const dec = (v: number | null | undefined) => (v === null ? "—" : nota(num(v)));
const inteiro = (v: number | null | undefined) => (v === null ? "—" : numero(num(v)));
const horas = (v: number | null | undefined) => (v === null ? "—" : tempoLeitura(num(v)));
/** Número de quem concorre (1º–5º); só se a API não manda o campo (antiga) cai no total.
 *  `null` (escondido da Secretaria) continua null — não vira o total da escola. */
const premiavel = (v: number | null | undefined, total: number | null) => (v === undefined ? total : v);

/** O critério da coluna "Nível" (os cortes de `faixaEngajamento`), por extenso: no `title`
 *  do cabeçalho e no fim da explicação da aba Engajamento. */
const CRITERIO_NIVEL = "Nível (resumo da adoção): Alta a partir de 80%, Média de 40% a 79,9%, Baixa abaixo de 40%.";

/** Quem conta a "Participação" da tela Escolas, pelos MÓDULOS CONTRATADOS: ler é do
 *  Elefante, fazer atividade é do Matific. */
function quemParticipa(modulos: string[]): string {
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  if (leitura && !matematica) return "quem leu";
  if (matematica && !leitura) return "quem fez atividade";
  return "quem leu ou fez atividade";
}

const ABAS: Aba[] = [
  {
    chave: "geral",
    rotulo: "Geral",
    icone: Trophy,
    metrica: "indice_geral",
    dimensoes: ["leitura", "matematica"],
    explicacao:
      "Média das pontuações de Leitura e Matemática. Cada uma já é proporcional ao "
      + "tamanho da escola, então escolas grandes e pequenas competem em pé de igualdade.",
    colunas: [
      { rotulo: "Alunos", valor: (e) => inteiro(e.total_alunos), ocultarAte: "sm" },
      { rotulo: "Leitura", valor: (e) => pontos(e.pontuacao_leitura), ocultarAte: "sm" },
      { rotulo: "Matemática", curto: "Matem.", valor: (e) => pontos(e.pontuacao_matematica), ocultarAte: "sm" },
      { rotulo: "Índice Geral", curto: "Geral", valor: (e) => pontos(e.pontuacao_geral), destaque: true,
        dica: "0 a 1000 — a melhor escola da rede marca 1000." },
    ],
  },
  {
    chave: "leitura",
    modulo: "leitura",
    rotulo: "Leitura",
    icone: BookOpen,
    metrica: "livros_aluno",
    dimensoes: ["leitura"],
    explicacao:
      "Ordenado por LIVROS POR ALUNO (livros lidos, acumulado desde o início da conta no "
      + "Elefante, ÷ alunos do 1º ao 5º ano) — o indicador "
      + "principal da leitura. Assim uma escola de 100 alunos que lê 20.000 livros "
      + "(200/aluno) fica acima de uma de 200 alunos com 35.000 livros (175/aluno).",
    colunas: [
      { rotulo: "Alunos (1º–5º)", curto: "Alunos", valor: (e) => inteiro(alunosPc(e)), ocultarAte: "sm",
        dica: "Alunos do 1º ao 5º ano — as turmas de Fase (Educação Infantil) não concorrem." },
      // O contador do Elefante é vitalício: livros e horas são o acumulado da conta, não do ano.
      { rotulo: "Livros lidos", curto: "Livros",
        valor: (e) => inteiro(premiavel((e as CartaoRanqueado).livros_premiaveis, e.livros)), ocultarAte: "sm",
        dica: "Livros lidos pelos alunos do 1º ao 5º ano, acumulado desde o início da conta no Elefante." },
      // Mesma população das duas colunas acima (só quem concorre): com o total,
      // as horas da Educação Infantil entravam na linha da escola.
      { rotulo: "Horas lidas", curto: "Horas",
        valor: (e) => horas(premiavel((e as CartaoRanqueado).tempo_premiaveis_min, e.tempo_leitura_min)), ocultarAte: "lg",
        dica: "Horas lidas pelos alunos do 1º ao 5º ano, acumulado desde o início da conta no Elefante." },
      { rotulo: "Livros/aluno", valor: (e) => dec(e.livros_por_matricula), destaque: true,
        dica: "Livros lidos (acumulado desde o início da conta no Elefante) ÷ alunos do 1º ao 5º ano. "
          + "É o critério que ordena este ranking." },
      { rotulo: "Pontuação", curto: "Pts", valor: (e) => pontos(e.pontuacao_leitura), ocultarAte: "md" },
    ],
  },
  {
    chave: "matematica",
    modulo: "matematica",
    rotulo: "Matemática",
    icone: Calculator,
    metrica: "estrelas_aluno",
    dimensoes: ["matematica"],
    explicacao:
      "Ordenado por ESTRELAS POR ALUNO (estrelas ÷ alunos do 1º ao 5º ano), o equivalente "
      + "proporcional da matemática. Atividades e estrelas totais aparecem ao lado "
      + "como contexto — mas não decidem a posição.",
    colunas: [
      { rotulo: "Alunos (1º–5º)", curto: "Alunos", valor: (e) => inteiro(alunosPc(e)), ocultarAte: "sm",
        dica: "Alunos do 1º ao 5º ano — as turmas de Fase (Educação Infantil) não concorrem." },
      { rotulo: "Atividades", curto: "Ativ.",
        valor: (e) => inteiro(premiavel((e as CartaoRanqueado).atividades_premiaveis, e.atividades)), ocultarAte: "sm",
        dica: "O Matific informa atividades finalizadas (não questões)." },
      { rotulo: "Estrelas", valor: (e) => inteiro(premiavel((e as CartaoRanqueado).estrelas_premiaveis, e.estrelas)), ocultarAte: "lg" },
      { rotulo: "Estrelas/aluno", curto: "Estr./aluno", valor: (e) => dec(e.estrelas_por_matricula), destaque: true,
        dica: "Estrelas ÷ alunos do 1º ao 5º ano. É o critério que ordena este ranking." },
      { rotulo: "Pontuação", curto: "Pts", valor: (e) => pontos(e.pontuacao_matematica), ocultarAte: "md" },
    ],
  },
  {
    chave: "engajamento",
    rotulo: "Engajamento",
    icone: Users,
    metrica: "engajamento",
    dimensoes: ["leitura", "matematica"],
    // "Adoção", não "Participação": a Participação da tela Escolas é outra conta (só quem
    // leu ou fez atividade no período, sobre os alunos com conta), e o mesmo nome com números
    // diferentes nas duas telas fazia um deles parecer errado.
    explicacao: (modulos) =>
      "Mostra QUANTOS alunos usam as plataformas — é adoção, não desempenho. "
      + "Ordenado por ADOÇÃO (alunos com dado de alguma plataforma, mesmo sem leitura ou "
      + "atividade, ÷ todos os alunos da escola, Fases incluídas). Não é a “Participação” da tela "
      + `Escolas, que conta só ${quemParticipa(modulos)} no período. `
      + "Uma escola pode ter desempenho alto e adoção baixa: são "
      + `coisas diferentes, e cada uma pede uma ação diferente. ${CRITERIO_NIVEL}`,
    colunas: [
      { rotulo: "Alunos", valor: (e) => inteiro(e.total_alunos), ocultarAte: "sm" },
      { rotulo: "Com dados", valor: (e) => inteiro(e.alunos_com_dados), ocultarAte: "sm",
        dica: "Alunos com dado real de alguma plataforma (não é contagem de notas)." },
      { rotulo: "Adoção (alguma plataforma)", curto: "Adoção", valor: (e) => `${dec(e.adocao)}%`, destaque: true,
        dica: "Alunos com dado de alguma plataforma (mesmo sem leitura ou atividade) ÷ alunos da escola." },
      { rotulo: "Adoção Elefante", curto: "Elef.", valor: (e) => `${dec(e.adocao_elefante)}%`, ocultarAte: "md",
        dica: "Alunos com dado do Elefante ÷ alunos da escola." },
      { rotulo: "Adoção Matific", curto: "Matific", valor: (e) => `${dec(e.adocao_matific)}%`, ocultarAte: "md",
        dica: "Alunos com dado do Matific ÷ alunos da escola." },
      // O per capita é só de quem concorre, e "Alunos" ao lado é o total com as
      // Fases: o rótulo diz qual é o denominador para a conta não parecer errada.
      { rotulo: "Livros/aluno (1º–5º)", curto: "Livros/aluno", valor: (e) => dec(e.livros_por_matricula),
        ocultarAte: "lg",
        dica: "Livros lidos (acumulado desde o início da conta no Elefante) ÷ alunos do 1º ao 5º ano — "
          + "não o total de alunos ao lado, que inclui as Fases." },
    ],
  },
];

/** Linha do `/redes/{id}/ranking`: o cartão da escola + a posição do backend
 *  + o numerador e o denominador do PER CAPITA (só quem concorre: 1º ao 5º ano;
 *  as Fases não concorrem). Opcionais: servidor anterior não os manda. */
type CartaoRanqueado = EscolaCartao & {
  posicao: number;
  alunos_premiaveis?: number;
  livros_premiaveis?: number;
  tempo_premiaveis_min?: number;
  estrelas_premiaveis?: number;
  atividades_premiaveis?: number;
};
/** A lista da aba junto com a URL que a produziu (ver `ConteudoRankingDaRede`). */
interface RespostaRanking {
  url: string;
  itens: CartaoRanqueado[];
}
/** Denominador do per capita (quem concorre), com o total como reserva. */
const alunosPc = (e: EscolaCartao) => premiavel((e as CartaoRanqueado).alunos_premiaveis, e.total_alunos);

/** Forma de `GET /redes/{id}/ranking/frescor`. */
interface FrescorRede {
  limite_dias: number;
  hoje: string;
  escolas: (Frescor & { escola_id: number; nome: string })[];
}

const GRAVIDADE: EstadoFrescor[] = ["sem_dados", "desatualizado", "parcial", "em_dia"];

/** O pior estado entre as dimensões da aba (e a data dele) — sem conta de data
 *  aqui: estado, data e dias vêm prontos do backend.
 *
 *  `sem_dados` só vale quando NENHUMA dimensão da aba tem dado. Ele vem antes de
 *  `desatualizado` na gravidade, mas não é um atraso: na aba Geral, a escola que
 *  só usa o Elefante (Matific contratado e sem retrato) tem a Matemática
 *  `sem_dados`, e escolhê-la escondia a Leitura parada há semanas — sem selo e
 *  fora do aviso, o caso que o recurso existe para mostrar. A ausência de uma
 *  dimensão já aparece na marca "só leitura"/"só matemática". */
function frescorDaAba(f: Frescor | undefined, dimensoes: Aba["dimensoes"]):
  { estado: EstadoFrescor; data: string | null } | null {
  if (!f) return null;
  const blocos = dimensoes
    .map((d) => f.dimensoes?.[d])
    .filter((b): b is NonNullable<typeof b> => Boolean(b?.contratada && b.estado));
  if (blocos.length === 0) return null;
  const comDado = blocos.filter((b) => b.estado !== "sem_dados");
  const candidatos = comDado.length > 0 ? comDado : blocos;
  const pior = candidatos.reduce((a, b) =>
    (GRAVIDADE.indexOf(b.estado!) < GRAVIDADE.indexOf(a.estado!) ? b : a));
  return { estado: pior.estado!, data: pior.dado_mais_recente_em };
}

function atrasada(f: { estado: EstadoFrescor } | null): boolean {
  return f != null && (f.estado === "desatualizado" || f.estado === "parcial");
}

/** Aviso do topo: quais escolas do ranking estão com dado além do limite. */
function AvisoFrescorRede({ frescor, aba, ids }: {
  frescor: FrescorRede | null; aba: Aba; ids: Set<number>;
}) {
  if (!frescor) return null;
  const lista = frescor.escolas
    .filter((e) => ids.has(e.escola_id))
    .map((e) => ({ nome: e.nome, f: frescorDaAba(e, aba.dimensoes) }))
    .filter((e) => atrasada(e.f));
  if (lista.length === 0) return null;
  return (
    <p
      role="status"
      className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
    >
      <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0" />
      <span>
        {lista.length} escola(s) deste ranking com dado de mais de {frescor.limite_dias} dias
        (ou coleta parcial) — a posição delas reflete um retrato antigo:{" "}
        {lista.map((e) => `${e.nome} (dados de ${dataDoDia(e.f!.data)})`).join("; ")}.
      </span>
    </p>
  );
}

/** Fundo OPACO da célula presa na linha do 1º lugar (ouro-50/50 e ouro-400/5 já
 *  compostos sobre o cartão): a faixa dourada não se interrompe na coluna presa. */
const FUNDO_PRESA_PRIMEIRO = "max-sm:bg-[#fffcf3] dark:max-sm:bg-[#252439]";
/** Teto pedido ao /ranking (o mesmo `le` do backend). */
const LIMITE_RANKING = 200;

const OCULTAR: Record<NonNullable<Coluna["ocultarAte"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
};

/** Faixa qualitativa da adoção — leitura rápida, sem inventar métrica (critério em `CRITERIO_NIVEL`). */
function faixaEngajamento(adocao: number): { rotulo: string; classe: string } {
  if (adocao >= 80) return { rotulo: "Alta", classe: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" };
  if (adocao >= 40) return { rotulo: "Média", classe: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" };
  return { rotulo: "Baixa", classe: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300" };
}

/** Bloco de fórmula — monoespaçado, para a conta ficar visível e conferível. */
function Formula({ children }: { children: React.ReactNode }) {
  return (
    <p className="my-1.5 overflow-x-auto rounded-md bg-white/70 px-2.5 py-1.5 font-mono text-[12px] leading-relaxed text-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-100">
      {children}
    </p>
  );
}

/**
 * "Como funciona o ranking?" — transparência TOTAL do cálculo.
 *
 * Mostra a fórmula REAL do código (backend `rede._indice_da_rede`, que compõe
 * `scoring.normalizar`), não uma descrição aproximada:
 *     normalizar(v, ref) = min(100, v / ref × 100)   →   ×10 (escala 0–1000)
 *     ⇒ pontuação = min(1000, (indicador ÷ melhor da rede) × 1000)
 * O exemplo é calculado com o "melhor da rede" REAL dos dados carregados, então
 * a Secretaria consegue conferir a conta contra a própria tabela.
 */
function ComoFunciona({ aba, escolas, modulos, aberto, aoFechar }: {
  aba: Aba; escolas: EscolaCartao[]; modulos: string[]; aberto: boolean; aoFechar: () => void;
}) {
  const temLeitura = modulos.includes("leitura");
  const temMatematica = modulos.includes("matematica");
  const melhorLeitura = Math.max(0, ...escolas.map((e) => num(e.livros_por_matricula)));
  const melhorMat = Math.max(0, ...escolas.map((e) => num(e.estrelas_por_matricula)));
  // Exemplo do enunciado: 35.000 livros / 200 alunos e 40.000 estrelas / 200 alunos.
  const exLivrosAluno = 35000 / 200;                       // = 175
  const exEstrelasAluno = 40000 / 200;                     // = 200
  const ptsEx = (v: number, melhor: number) =>
    (melhor > 0 ? Math.min(1000, (v / melhor) * 1000) : 0);

  return (
    <Modal titulo="Como funciona o ranking da rede" aberto={aberto} aoFechar={aoFechar} largura="max-w-3xl">
        <div className="space-y-3 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 text-sm text-zinc-700 dark:border-indigo-500/20 dark:bg-indigo-500/5 dark:text-zinc-200">
          <p className="rounded-md bg-white/60 p-2 text-xs dark:bg-zinc-900/50">
            O sistema mostra <b>duas medidas diferentes</b>, e vale não confundir:<br />
            <b>① Índice da rede (0–1000)</b> — ordena este ranking. Compara as escolas
            entre si, proporcionalmente ao tamanho de cada uma.<br />
            {/* O Panorama da Rede não mostra mais essas médias: elas ficam nos totais da tela
                das plataformas (o nome segue os módulos, como no menu) e na Visão da Escola. */}
            <b>② Notas de desempenho (0–100)</b> — as médias de Leitura/Matemática da tela
            {" "}{rotuloDasPlataformas(modulos)} (nos totais, na linha “Média das notas”) e da
            Visão da Escola. Medem <b>quão bem vão os alunos que usam</b> a plataforma.
          </p>

          <p className="pt-1 font-semibold text-indigo-700 dark:text-indigo-300">
            ① Índice da rede (0–1000) — ordena o ranking
          </p>
          <p>
            O ranking compara desempenho <b>proporcional ao tamanho da escola</b>, para que
            uma escola grande não fique à frente só por ter mais alunos. Toda pontuação vai
            de <b>0 a 1000</b>, em que <b>1000 é a melhor escola da rede</b> naquele indicador.
          </p>

          {temLeitura && <div>
            <p className="font-semibold">📚 Leitura (Elefante Letrado)</p>
            <p className="mt-1">1. Primeiro, o indicador proporcional:</p>
            <Formula>Livros por aluno = Total de livros lidos ÷ Nº de alunos da escola (1º ao 5º ano)</Formula>
            <p>2. Depois, a comparação com a melhor escola da rede:</p>
            <Formula>
              Pontuação de Leitura = mín(1000 ; Livros por aluno ÷ Melhor da rede × 1000)
            </Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              “Melhor da rede” é o maior valor de livros por aluno entre as escolas
              {melhorLeitura > 0 && <> — hoje <b>{dec(melhorLeitura)} livros/aluno</b></>}.
              Quem tem esse valor marca 1000; metade dele marca 500. Os livros são o
              <b> acumulado desde o início da conta</b> de cada aluno no Elefante (o contador da
              plataforma não zera na virada do ano).
            </p>
          </div>}

          {temMatematica && <div>
            <p className="font-semibold">🔢 Matemática (Matific)</p>
            <p className="mt-1">Mesma lógica, com o indicador da plataforma:</p>
            <Formula>Estrelas por aluno = Total de estrelas ÷ Nº de alunos da escola (1º ao 5º ano)</Formula>
            <Formula>
              Pontuação de Matemática = mín(1000 ; Estrelas por aluno ÷ Melhor da rede × 1000)
            </Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              O Matific informa <b>atividades finalizadas</b> e <b>estrelas</b> — não
              “questões”. As atividades aparecem como contexto; quem decide a posição são as
              estrelas por aluno
              {melhorMat > 0 && <> (melhor da rede hoje: <b>{dec(melhorMat)}/aluno</b>)</>}.
              Estrelas e atividades são as do <b>ano letivo</b>.
            </p>
          </div>}

          <div>
            <p className="font-semibold">🏆 Índice Geral</p>
            <Formula>Índice Geral = (Pontuação de Leitura + Pontuação de Matemática) ÷ 2</Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              Se a escola <b>não tem dados de uma das plataformas</b>, a média considera
              <b> apenas a dimensão disponível</b> — assim ela não é penalizada com um zero
              que não reflete desempenho. Nesses casos a tabela mostra a marca
              “só leitura” ou “só matemática” ao lado do nome.
            </p>
          </div>

          <p className="border-t border-indigo-200/60 pt-2.5 font-semibold text-indigo-700 dark:border-indigo-500/20 dark:text-indigo-300">
            ② Notas de desempenho (0–100) — as médias das plataformas
          </p>
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            Estas notas medem <b>o desempenho de quem usa</b> a plataforma. Aluno sem dado
            NÃO entra como zero — ele simplesmente não é contado (quantos usam é a
            <b> adoção</b>, mostrada à parte).
          </p>
          {/* R e k valem para as DUAS plataformas: fora do bloco da Leitura, para a rede só com
              o Matific não ler "a mesma normalização" sem a definição na tela. */}
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            <b>R</b> = referência da escola (o <b>percentil 90</b> dos alunos que usam —
            escola pequena usa o maior valor). <b>k</b> = a <b>mediana</b>, que dá
            “retornos decrescentes” ao volume: dobrar a quantidade não dobra a nota.
          </p>

          {temLeitura && <div>
            <p className="font-semibold">📚 Nota de Leitura (0–100)</p>
            <p className="mt-1">Cada indicador do Elefante vira 0–100 comparando o aluno com os colegas da própria escola:</p>
            <Formula>
              volume (livros, tempo, tentativas): mín(100 ; [v ÷ (v+k)] ÷ [R ÷ (R+k)] × 100)
            </Formula>
            <Formula>qualidade (acertos, dificuldade): mín(100 ; v ÷ R × 100)</Formula>
            <p className="mt-1.5">Os indicadores entram com os pesos configurados:</p>
            <Formula>
              Nota do aluno = 35%·livros + 30%·dificuldade + 30%·questões + 5%·tempo
            </Formula>
            <Formula>questões = 30%·tentativas + 70%·acertos</Formula>
            <Formula>Nota de Leitura da escola = média das notas dos alunos COM dado do Elefante</Formula>
          </div>}

          {temMatematica && <div>
            <p className="font-semibold">🔢 Nota de Matemática (0–100)</p>
            <p className="mt-1">
              A mesma normalização acima (R = percentil 90 da escola; k = mediana no volume), com os indicadores do Matific:
            </p>
            <Formula>
              Nota do aluno = 40%·atividades + 35%·pontuação média + 25%·estrelas
            </Formula>
            <Formula>Nota de Matemática da escola = média das notas dos alunos COM dado do Matific</Formula>
          </div>}

          <div>
            <p className="font-semibold">🏆 Média Geral (0–100)</p>
            <Formula>Média Geral = (Nota de Leitura + Nota de Matemática) ÷ 2</Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              Com <b>uma só</b> plataforma, a média usa <b>a dimensão disponível</b> — a
              ausência não vira zero. Ex.: Leitura 75 e Matemática sem dados ⇒ Geral = <b>75</b>
              (e não 37,5).{!temMatematica && <> Esta rede contratou <b>apenas a Leitura</b>,
              então a Geral é a própria nota de Leitura.</>}
              {!temLeitura && <> Esta rede contratou <b>apenas a Matemática</b>, então a Geral
              é a própria nota de Matemática.</>}
            </p>
          </div>

          <div>
            <p className="font-semibold">📊 Exemplo prático (notas 0–100)</p>
            <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
              Escola com <b>200 alunos</b>:
            </p>
            <Formula>150 alunos usam o Elefante, média deles 78 → Nota de Leitura = 78</Formula>
            <Formula>160 alunos usam o Matific, média deles 82 → Nota de Matemática = 82</Formula>
            <Formula>Média Geral = (78 + 82) ÷ 2 = 80</Formula>
            <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
              E a <b>adoção</b>, separada do desempenho:
            </p>
            <Formula>Adoção Elefante = 150 ÷ 200 = 75%   ·   Adoção Matific = 160 ÷ 200 = 80%</Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              Leitura: <b>80 é desempenho</b>; <b>75%/80% é adoção</b>. Os 50 alunos
              que ainda não usam o Elefante não derrubam a nota — aparecem na adoção, que é
              onde a ação da Secretaria muda (ampliar uso ≠ melhorar desempenho).
            </p>
          </div>

          <div>
            <p className="font-semibold">📊 Exemplo prático (índice 0–1000)</p>
            <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
              Uma escola com <b>200 alunos</b>, <b>35.000 livros</b> e <b>40.000 estrelas</b>,
              usando a régua atual desta rede:
            </p>
            <Formula>
              Leitura: 35.000 ÷ 200 = {dec(exLivrosAluno)} livros/aluno
              {melhorLeitura > 0
                ? <> → {dec(exLivrosAluno)} ÷ {dec(melhorLeitura)} × 1000 = <b>{pontos(ptsEx(exLivrosAluno, melhorLeitura))} pontos</b></>
                : <> → sem outras escolas para comparar ainda</>}
            </Formula>
            <Formula>
              Matemática: 40.000 ÷ 200 = {dec(exEstrelasAluno)} estrelas/aluno
              {melhorMat > 0
                ? <> → {dec(exEstrelasAluno)} ÷ {dec(melhorMat)} × 1000 = <b>{pontos(ptsEx(exEstrelasAluno, melhorMat))} pontos</b></>
                : <> → sem outras escolas para comparar ainda</>}
            </Formula>
            {melhorLeitura > 0 && melhorMat > 0 && (
              <Formula>
                Índice Geral = ({pontos(ptsEx(exLivrosAluno, melhorLeitura))} + {pontos(ptsEx(exEstrelasAluno, melhorMat))}) ÷ 2
                = <b>{pontos((ptsEx(exLivrosAluno, melhorLeitura) + ptsEx(exEstrelasAluno, melhorMat)) / 2)} pontos</b>
              </Formula>
            )}
          </div>

          <p className="border-t border-indigo-200/60 pt-2 text-xs text-zinc-600 dark:border-indigo-500/20 dark:text-zinc-400">
            <b>Aba aberta ({aba.rotulo}):</b> {typeof aba.explicacao === "function" ? aba.explicacao(modulos) : aba.explicacao}
          </p>
        </div>
        <div className="mt-5 flex justify-end">
          <Botao variante="secundario" onClick={aoFechar}>Fechar</Botao>
        </div>
    </Modal>
  );
}

/** As plataformas que calculam a pontuação, pelos MÓDULOS CONTRATADOS da rede mostrada: numa
 *  rede com um módulo só, citar as duas nomearia um produto que ela não tem. */
function plataformasDoRanking(modulos: string[]): string {
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  if (leitura && !matematica) return "o Elefante Letrado";
  if (matematica && !leitura) return "o Matific";
  return "o Elefante e o Matific";
}

/** De QUAL ano letivo são os alunos: o corrente, ou — na virada do ano, com as escolas em anos
 *  diferentes (`anosLetivosMistos`) — o de cada escola (cada uma é medida no ano dela). */
function alunosDoAno(anosMistos: boolean): string {
  return anosMistos ? "alunos do ano letivo de cada escola" : "alunos do ano letivo corrente";
}

/** DE QUANDO são os números da pontuação, pelos MÓDULOS CONTRATADOS (as mesmas palavras da tela
 *  das plataformas): os alunos são os do ano letivo corrente, mas o contador do Elefante é
 *  vitalício e só o Matific é cortado no ano letivo. Chamar tudo de "ano letivo" punha os livros
 *  de anos anteriores na conta da escola sem dizer. `anosMistos`: as escolas estão em anos
 *  letivos diferentes ("o ano letivo corrente" seria um só). */
function periodoDoRanking(modulos: string[], anosMistos = false): string {
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  const elefante = "Elefante: acumulado desde o início da conta";
  const matific = "Matific: no ano letivo";
  const plataformas = leitura && !matematica ? elefante
    : matematica && !leitura ? matific
    : `${elefante}; ${matific}`;
  return `${alunosDoAno(anosMistos)} (${plataformas})`;
}

/** A escola entra na comparação? A marca `comparada` do backend (a mesma régua do ranking e
 *  da equidade); sem ela (API anterior), `dimensoes_pontuadas`, que é o que o backend testa. */
function comparada(e: EscolaCartao): boolean {
  if (typeof e.comparada === "boolean") return e.comparada;
  if (Array.isArray(e.dimensoes_pontuadas)) return e.dimensoes_pontuadas.length > 0;
  return e.alunos_com_dados > 0;
}

/**
 * "Diferença entre escolas — calculado pelo Constela": a EQUIDADE do índice (0–1000, per
 * capita — o único número comparável entre escolas; a média 0–100 é régua interna de cada
 * escola). Conclusão numa frase, o porquê embaixo. Sem o campo (API anterior), nada; com
 * menos de duas escolas comparadas, diz que não há diferença a medir (nunca um 0 solto).
 */
function DiferencaEntreEscolas({ equidade, escolasComparadas, modulos, anosMistos }: {
  equidade: DashboardRede["equidade"] | null | undefined;
  escolasComparadas: number;
  modulos: string[];
  anosMistos: boolean;
}) {
  if (equidade?.gap_indice == null) return null;
  return (
    <Card className="p-5 sm:p-6">
      <div className="space-y-2" data-testid="diferenca-entre-escolas">
        {/* O selo fica AO LADO do título (o nome do h2 continua só "Diferença entre escolas"). */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            <IconePastel icone={Scale} tom="azul" tamanho="sm" />
            Diferença entre escolas
          </h2>
          <SeloNatureza natureza="calculado" />
        </div>
        {escolasComparadas < 2 ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Com menos de duas escolas comparadas, não há diferença a medir.
          </p>
        ) : (
          <>
            <p className="text-sm text-zinc-700 dark:text-zinc-200">
              Entre a escola de maior e a de menor índice há{" "}
              <b className="tabular-nums text-zinc-900 dark:text-white">{numero(Math.round(equidade.gap_indice))}</b>{" "}
              pontos de índice{" "}
              <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
                ({numero(Math.round(equidade.escola_menor_indice ?? 0))} → {numero(Math.round(equidade.escola_maior_indice ?? 0))} de 1000)
              </span>
              ;{" "}
              <b className="tabular-nums text-zinc-900 dark:text-white">{equidade.escolas_abaixo_do_indice_medio ?? 0}</b>{" "}
              escola(s) abaixo do índice médio da rede.
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Quanto menor a diferença, mais parecidas as escolas estão nesta pontuação. Medida no Índice Geral (a
              pontuação do Constela, de 0 a 1000), em qualquer aba — não uma avaliação oficial. Período:{" "}
              {periodoDoRanking(modulos, anosMistos)}.
            </p>
          </>
        )}
      </div>
    </Card>
  );
}

function ConteudoRankingDaRede({ redeId }: { redeId: number }) {
  const { dados, erro, carregando, recarregar } = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const { selecionarEscola } = useApp();
  const { global } = usePerfil();
  const navegar = useNavigate();
  const { pathname, search } = useLocation();
  const [abaIdx, setAbaIdx] = useState(0);
  const [explicando, setExplicando] = useState(false);

  // MÓDULOS CONTRATADOS: aba, coluna e explicação de produto não contratado não
  // existem para esta rede (≠ "sem dados", que existe e mostra vazio).
  const mods = dados?.modulos ?? ["leitura", "matematica"];
  const abas = useMemo(
    () => ABAS.filter((a) => !a.modulo || mods.includes(a.modulo)),
    [mods.join("|")],
  );
  const aba = abas[Math.min(abaIdx, abas.length - 1)] ?? ABAS[0];

  // A ORDEM e a POSIÇÃO são as do backend (só escolas com dados entram).
  //
  // A resposta (e a falha) carregam a URL que as gerou, e só valem para a aba
  // que as pediu. O `useApi` não zera `dados` ao mudar de URL nem ao falhar:
  // ao trocar de Geral para Leitura, a ordem e as medalhas do índice geral
  // ficavam sob o cabeçalho "livros por aluno" enquanto a busca corria — e, se
  // ela falhasse, para sempre e sem erro nenhum na tela.
  const urlRanking = `/redes/${redeId}/ranking?metrica=${aba.metrica}&limite=${LIMITE_RANKING}`;
  const [urlComFalha, setUrlComFalha] = useState<string | null>(null);
  const { dados: respostaRanking, erro: erroRankingBruto, recarregar: recarregarRanking } = useApi<RespostaRanking>(
    (sinal) => api<CartaoRanqueado[]>(urlRanking, { signal: sinal })
      .then((itens) => ({ url: urlRanking, itens })),
    { chave: [urlRanking], aoErro: () => setUrlComFalha(urlRanking) },
  );
  const ranking = respostaRanking?.url === urlRanking ? respostaRanking.itens : null;
  const erroRanking = urlComFalha === urlRanking ? erroRankingBruto : null;
  const { dados: frescor } = useApi<FrescorRede>(
    `/redes/${redeId}/ranking/frescor`, { cacheMs: 60_000, tentativas: 0 });
  const frescorPorEscola = useMemo(
    () => new Map((frescor?.escolas ?? []).map((e) => [e.escola_id, e])),
    [frescor],
  );
  const ranked = ranking ?? [];
  const naOrdem = new Set(ranked.map((e) => e.escola_id));
  // Quem ficou fora da ordem só é nomeado com a ordem DESTA aba carregada e abaixo do
  // teto pedido (no teto, quem falta pode ser só o corte).
  const podeNomear = ranking !== null && ranked.length < LIMITE_RANKING;
  const cartaoPorId = new Map((dados?.escolas ?? []).map((e) => [e.escola_id, e]));
  const dimensaoDaAba = aba.dimensoes.length === 1 ? aba.dimensoes[0] : null;
  // Secretaria: fora da ordem por PROTEÇÃO — na aba de uma matéria, a escola com essa
  // matéria escondida; em qualquer aba, a que ficou sem matéria visível (comparada =
  // false). Outra matéria escondida não explica a ausência numa aba.
  const foraDoRanking = podeNomear
    ? (dados?.ocultas ?? []).filter((o) => !naOrdem.has(o.escola_id) && (
      (dimensaoDaAba !== null && o.oculto?.[dimensaoDaAba] != null)
      || cartaoPorId.get(o.escola_id)?.comparada === false))
    : [];
  // Fora da COMPARAÇÃO (o critério do backend, igual nas quatro abas: nenhum aluno do
  // 1º ao 5º ano com dado das plataformas contratadas — `comparada` do cartão). Antes
  // sumia em silêncio: o cabeçalho dizia "2 escola(s)" sobre uma lista de uma. Quem
  // tem dado só de outra matéria continua na ordem (com 0), e não entra aqui.
  const protegidas = new Set(foraDoRanking.map((o) => o.escola_id));
  const foraDaComparacao = podeNomear && ranked.length > 0
    ? (dados?.escolas ?? []).filter((e) => e.comparada === false
      && !naOrdem.has(e.escola_id) && !protegidas.has(e.escola_id))
    : [];

  if (carregando && !dados) return <Carregando texto="Carregando o ranking da rede..." />;
  if (erro && !dados) {
    return <Erro titulo="Não foi possível carregar o ranking" descricao={erro.message} aoTentar={recarregar} />;
  }
  if (!dados) return null;

  // Na virada do ano, escolas em anos letivos diferentes: cada uma é medida no ano dela. A tela
  // avisa, marca o ano de cada escola e não fala de "o ano letivo corrente", como se fosse um só.
  const anosMistos = anosLetivosMistos(dados);
  const comAno = anosMistos !== null;

  // O "Voltar" da Visão da Escola traz de volta a este ranking (com o `?rede=` do global).
  const abrir = (id: number) => {
    selecionarEscola(id);
    const estado: EstadoDaVisaoEscola = { voltar: { caminho: pathname + search, texto: "Voltar ao Ranking da Rede" } };
    navegar("/escola", { state: estado });
  };
  const destaque = aba.colunas.find((c) => c.destaque);

  // Exportar: a tabela desta aba, na ordem do backend (só agregados por escola).
  const csv: TabelaCsv | null = !ranking || ranked.length === 0 ? null : {
    nomeArquivo: nomeArquivoCsv(`ranking-da-rede-${aba.rotulo}`),
    cabecalho: ["Posição", "Escola", ...(comAno ? ["Ano letivo"] : []), ...aba.colunas.map((c) => c.rotulo)],
    linhas: ranked.map((e) => [e.posicao, e.nome, ...(comAno ? [e.ano_letivo ?? ""] : []),
      ...aba.colunas.map((c) => c.valor(e))]),
  };

  return (
    <div className="space-y-5">
      <PageHeader
        titulo="🏆 Ranking da Rede"
        descricao={`${dados.escolas.length} escola(s) • ${periodoDoRanking(mods, comAno)} • comparação proporcional ao tamanho da escola`}
        acoes={(
          // `contents`: do sm em diante os botões continuam filhos diretos da caixa de
          // ações (o mesmo layout de antes); no celular viram uma coluna de mesma largura.
          <div className={`contents ${ACOES_CELULAR}`}>
            <Botao variante="secundario" onClick={() => setExplicando(true)}>
              <HelpCircle size={16} aria-hidden /> Como funciona o ranking?
            </Botao>
            <AcoesRanking csv={csv} />
          </div>
        )}
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <AbasRanking
          itens={abas.map((opt) => ({ valor: opt.chave, rotulo: opt.rotulo, icone: opt.icone }))}
          valor={aba.chave}
          aoMudar={(chave) => setAbaIdx(Math.max(0, abas.findIndex((a) => a.chave === chave)))}
          rotulo="Categoria do ranking"
          celular="grade"
        />
        {destaque && (
          <p className="inline-flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <ListOrdered size={14} aria-hidden className="shrink-0 text-indigo-600 dark:text-indigo-300" />
            Ordem desta aba: <span className="font-semibold text-zinc-700 dark:text-zinc-200">{destaque.rotulo}</span>
          </p>
        )}
      </div>
      <ComoFunciona aba={aba} escolas={dados.escolas ?? []} modulos={mods}
                    aberto={explicando} aoFechar={() => setExplicando(false)} />

      <AvisoFrescorRede frescor={frescor} aba={aba}
                        ids={new Set(ranked.map((e) => e.escola_id))} />

      {/* Escolas em anos letivos diferentes (a virada do ano): o ano de cada uma vai na linha dela. */}
      <AvisoAnosLetivos anos={anosMistos} />

      <Card className="overflow-hidden">
        {/* Falha da ORDEM fica dentro do cartão: cabeçalho, abas e explicador
            (que vêm do /dashboard) continuam de pé — sem inventar uma ordem
            local no lugar da do backend. `ranking` só existe para a aba atual,
            então a falha dela aparece mesmo que outra aba já tenha carregado. */}
        {erroRanking && !ranking ? (
          <Erro titulo="Não foi possível carregar o ranking" descricao={erroRanking.message} aoTentar={recarregarRanking} />
        ) : !ranking ? (
          <Carregando texto="Carregando o ranking da rede..." />
        ) : ranked.length === 0 ? (
          <Vazio
            icone={Trophy}
            titulo="Sem dados ainda"
            descricao={`Nenhuma escola da rede tem dados das plataformas para os ${alunosDoAno(comAno)}.`}
          />
        ) : (
          <TabelaRolavel rotulo={`Ranking das escolas por ${aba.rotulo}: tabela completa`}>
            <table className="w-full text-sm tabular-nums sm:min-w-[560px]">
              <caption className="sr-only">
                Ranking das escolas da rede por {aba.rotulo}
              </caption>
              <thead className="border-b border-zinc-100 bg-zinc-50/70 dark:border-zinc-800 dark:bg-zinc-800/30">
                <tr className="text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                  <th scope="col" className="px-4 py-3">#</th>
                  <th scope="col" className="px-4 py-3">Escola</th>
                  {aba.colunas.map((c) => (
                    <th
                      key={c.rotulo}
                      scope="col"
                      title={c.dica}
                      className={`whitespace-nowrap px-4 py-3 text-right ${
                        c.ocultarAte ? OCULTAR[c.ocultarAte] : ""
                      } ${c.destaque ? `text-indigo-700 dark:text-indigo-300 ${tabelaRanking.thPresa}` : ""}`}
                    >
                      <span className="sm:hidden">{c.curto ?? c.rotulo}</span>
                      <span className="hidden sm:inline">{c.rotulo}</span>
                    </th>
                  ))}
                  {aba.chave === "engajamento" && (
                    <th scope="col" title={CRITERIO_NIVEL} className={`px-4 py-3 text-right ${OCULTAR.sm}`}>Nível</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {ranked.map((e) => {
                  const faixa = faixaEngajamento(num(e.adocao));
                  const f = frescorDaAba(frescorPorEscola.get(e.escola_id), aba.dimensoes);
                  return (
                    <tr
                      key={e.escola_id}
                      className={`border-t border-zinc-100 transition-colors first:border-t-0 hover:bg-zinc-50/80 dark:border-zinc-800 dark:hover:bg-zinc-800/40 ${
                        e.posicao === 1 ? "bg-ouro-50/50 dark:bg-ouro-400/5" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        {e.posicao >= 1 && e.posicao <= 3
                          ? <Medalha posicao={e.posicao as 1 | 2 | 3} tamanho={26} />
                          : <PosicaoRanking posicao={e.posicao} />}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => abrir(e.escola_id)}
                          className="text-left font-semibold text-zinc-900 hover:text-indigo-700 hover:underline dark:text-zinc-100 dark:hover:text-indigo-300"
                        >
                          {e.nome}
                        </button>
                        <span className="mt-1 flex flex-wrap items-center gap-1.5 empty:hidden">
                          {comAno && e.ano_letivo != null && (
                            <span
                              className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-semibold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
                              title="As escolas da rede estão em anos letivos diferentes; esta é medida neste ano."
                            >
                              ano letivo {e.ano_letivo}
                            </span>
                          )}
                          {e.dimensoes_pontuadas?.length === 1 && (
                            <span
                              className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
                              title="A escola só tem dados de uma plataforma; o índice geral considera apenas ela."
                            >
                              só {e.dimensoes_pontuadas[0] === "leitura" ? "leitura" : "matemática"}
                            </span>
                          )}
                          {atrasada(f) && (
                            <span
                              className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
                              title={`O dado desta escola passou de ${frescor?.limite_dias ?? 7} dias (ou a última coleta foi parcial).`}
                            >
                              dados de {dataDoDia(f!.data)}
                            </span>
                          )}
                          {/* Em dia também diz a data: a posição é a do retrato daquele dia. */}
                          {f && !atrasada(f) && f.estado !== "sem_dados" && f.data && (
                            <span className="inline-flex items-center gap-1 text-[11px] text-zinc-500 dark:text-zinc-400"
                                  title="Data do retrato mais recente desta escola usado no ranking.">
                              <CalendarClock size={12} aria-hidden className="shrink-0" />
                              <span>dados de {dataDoDia(f.data)}</span>
                            </span>
                          )}
                        </span>
                      </td>
                      {aba.colunas.map((c) => (
                        <td
                          key={c.rotulo}
                          className={`px-4 py-3 text-right ${c.ocultarAte ? OCULTAR[c.ocultarAte] : ""} ${
                            c.destaque
                              ? `text-base font-bold text-indigo-700 dark:text-indigo-300 ${tabelaRanking.tdPresa} ${
                                e.posicao === 1 ? FUNDO_PRESA_PRIMEIRO : ""
                              }`
                              : "text-zinc-600 dark:text-zinc-300"
                          }`}
                        >
                          {c.valor(e)}
                        </td>
                      ))}
                      {aba.chave === "engajamento" && (
                        <td className={`px-4 py-3 text-right ${OCULTAR.sm}`}>
                          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${faixa.classe}`}>
                            {faixa.rotulo}
                          </span>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>

      {/* Secretaria: a escola com 1 ou 2 alunos com dado na matéria desta aba sai da
          ordem (sem posição): diz quem e por quê, em vez de sumir em silêncio. */}
      {foraDoRanking.length > 0 && (
        <p className="flex items-start gap-1.5 rounded-xl bg-ouro-50 px-3 py-2 text-xs text-ouro-800 dark:bg-ouro-400/10 dark:text-ouro-200">
          <span aria-hidden>ⓘ</span>
          <span>
            Fora deste ranking para proteger as crianças (menos de 3 alunos com dado na matéria, ou só 1 ou 2
            com resultado acima de zero):{" "}
            {foraDoRanking.map((o) => o.nome).join(", ")}.
          </span>
        </p>
      )}

      {foraDaComparacao.length > 0 && (
        <p className="px-1 text-xs text-zinc-600 dark:text-zinc-300">
          Fora da comparação (nenhum aluno do 1º ao 5º ano com dado das plataformas contratadas,
          entre os {alunosDoAno(comAno)}):{" "}
          {foraDaComparacao.map((e) => e.nome).join(", ")}.
        </p>
      )}

      <DiferencaEntreEscolas equidade={dados.equidade} modulos={mods} anosMistos={comAno}
                             escolasComparadas={(dados.escolas ?? []).filter(comparada).length} />

      <p className="px-1 text-xs text-zinc-500 dark:text-zinc-400">
        Clique em uma escola para ver o panorama detalhado dela. Os dados são agregados
        por escola — o ranking da rede nunca expõe informação individual de aluno.
      </p>
      <p className="px-1 text-xs text-zinc-500 dark:text-zinc-400" data-testid="ranking-outra-medida">
        O ranking ordena pela pontuação do Constela, calculada com {plataformasDoRanking(mods)}. O uso das plataformas,
        escola por escola, fica em{" "}
        <Link to={global ? `/rede/escolas?rede=${redeId}` : "/rede/escolas"}
              className="font-semibold text-indigo-600 hover:underline dark:text-indigo-300">
          Escolas
        </Link>; os resultados das avaliações externas, em{" "}
        <Link to={global ? `/rede/avaliacoes-externas?rede=${redeId}` : "/rede/avaliacoes-externas"}
              className="font-semibold text-indigo-600 hover:underline dark:text-indigo-300">
          Avaliações externas
        </Link>{" "}e na ficha de cada escola.
      </p>
    </div>
  );
}

/** Página dedicada do Ranking da Rede (Secretaria e Admin Global). */
export default function RankingDaRede() {
  return <EnvolucroRede titulo="Ranking da Rede">{(redeId) => <ConteudoRankingDaRede redeId={redeId} />}</EnvolucroRede>;
}
