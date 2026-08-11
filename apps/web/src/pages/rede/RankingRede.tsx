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
 * Reusa o payload agregado de `/redes/{id}/dashboard` (o mesmo do Panorama): só
 * dados por ESCOLA, nunca PII de criança.
 */
import { BookOpen, Calculator, HelpCircle, Trophy, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card, Carregando, PageHeader, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { nota, numero, tempoLeitura } from "../../lib/formato";
import { EnvolucroRede, MEDALHAS, type DashboardRede, type EscolaCartao } from "./comum";

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
  /** Métrica que ORDENA o ranking desta aba (desc). */
  ordenar: (e: EscolaCartao) => number;
  colunas: Coluna[];
  explicacao: string;
}

// Formatadores DEFENSIVOS: um indicador ausente (bundle do PWA mais novo/velho
// que a API) vira 0 em vez de derrubar a tabela inteira.
const num = (v: number | null | undefined) => Number(v ?? 0);
const pontos = (v: number | null | undefined) => numero(Math.round(num(v)));
const dec = (v: number | null | undefined) => nota(num(v));
const inteiro = (v: number | null | undefined) => numero(num(v));
const horas = (v: number | null | undefined) => tempoLeitura(num(v));

const ABAS: Aba[] = [
  {
    chave: "geral",
    rotulo: "Geral",
    icone: Trophy,
    ordenar: (e) => num(e.pontuacao_geral),
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
    ordenar: (e) => num(e.livros_por_matricula),
    explicacao:
      "Ordenado por LIVROS POR ALUNO (livros lidos ÷ alunos da escola) — o indicador "
      + "principal da leitura. Assim uma escola de 100 alunos que lê 20.000 livros "
      + "(200/aluno) fica acima de uma de 200 alunos com 35.000 livros (175/aluno).",
    colunas: [
      { rotulo: "Alunos", valor: (e) => inteiro(e.total_alunos), ocultarAte: "sm" },
      { rotulo: "Livros lidos", curto: "Livros", valor: (e) => inteiro(e.livros), ocultarAte: "sm" },
      { rotulo: "Horas lidas", curto: "Horas", valor: (e) => horas(e.tempo_leitura_min), ocultarAte: "lg" },
      { rotulo: "Livros/aluno", valor: (e) => dec(e.livros_por_matricula), destaque: true,
        dica: "Livros lidos ÷ alunos da escola. É o critério que ordena este ranking." },
      { rotulo: "Pontuação", curto: "Pts", valor: (e) => pontos(e.pontuacao_leitura), ocultarAte: "md" },
    ],
  },
  {
    chave: "matematica",
    modulo: "matematica",
    rotulo: "Matemática",
    icone: Calculator,
    ordenar: (e) => num(e.estrelas_por_matricula),
    explicacao:
      "Ordenado por ESTRELAS POR ALUNO (estrelas ÷ alunos da escola), o equivalente "
      + "proporcional da matemática. Atividades e estrelas totais aparecem ao lado "
      + "como contexto — mas não decidem a posição.",
    colunas: [
      { rotulo: "Alunos", valor: (e) => inteiro(e.total_alunos), ocultarAte: "sm" },
      { rotulo: "Atividades", curto: "Ativ.", valor: (e) => inteiro(e.atividades), ocultarAte: "sm",
        dica: "O Matific informa atividades finalizadas (não questões)." },
      { rotulo: "Estrelas", valor: (e) => inteiro(e.estrelas), ocultarAte: "lg" },
      { rotulo: "Estrelas/aluno", curto: "Estr./aluno", valor: (e) => dec(e.estrelas_por_matricula), destaque: true,
        dica: "Estrelas ÷ alunos da escola. É o critério que ordena este ranking." },
      { rotulo: "Pontuação", curto: "Pts", valor: (e) => pontos(e.pontuacao_matematica), ocultarAte: "md" },
    ],
  },
  {
    chave: "engajamento",
    rotulo: "Engajamento",
    icone: Users,
    ordenar: (e) => num(e.adocao),
    explicacao:
      "Mostra QUANTOS alunos usam as plataformas — é adoção, não desempenho. "
      + "Ordenado por PARTICIPAÇÃO (alunos com dado de alguma plataforma ÷ alunos "
      + "da escola). Uma escola pode ter desempenho alto e adoção baixa: são "
      + "coisas diferentes, e cada uma pede uma ação diferente.",
    colunas: [
      { rotulo: "Alunos", valor: (e) => inteiro(e.total_alunos), ocultarAte: "sm" },
      { rotulo: "Com dados", valor: (e) => inteiro(e.alunos_com_dados), ocultarAte: "sm",
        dica: "Alunos com dado real de alguma plataforma (não é contagem de notas)." },
      { rotulo: "Participação", curto: "Particip.", valor: (e) => `${dec(e.adocao)}%`, destaque: true,
        dica: "Alunos com dado de alguma plataforma ÷ alunos da escola." },
      { rotulo: "Adoção Elefante", curto: "Elef.", valor: (e) => `${dec(e.adocao_elefante)}%`, ocultarAte: "md",
        dica: "Alunos com dado do Elefante ÷ alunos da escola." },
      { rotulo: "Adoção Matific", curto: "Matific", valor: (e) => `${dec(e.adocao_matific)}%`, ocultarAte: "md",
        dica: "Alunos com dado do Matific ÷ alunos da escola." },
      { rotulo: "Livros/aluno", valor: (e) => dec(e.livros_por_matricula), ocultarAte: "lg" },
    ],
  },
];

const OCULTAR: Record<NonNullable<Coluna["ocultarAte"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
};

/** Faixa qualitativa da participação — leitura rápida, sem inventar métrica. */
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
function ComoFunciona({ aba, escolas, modulos }: { aba: Aba; escolas: EscolaCartao[]; modulos: string[] }) {
  const temLeitura = modulos.includes("leitura");
  const temMatematica = modulos.includes("matematica");
  const [aberto, setAberto] = useState(false);
  const melhorLeitura = Math.max(0, ...escolas.map((e) => num(e.livros_por_matricula)));
  const melhorMat = Math.max(0, ...escolas.map((e) => num(e.estrelas_por_matricula)));
  // Exemplo do enunciado: 35.000 livros / 200 alunos e 40.000 estrelas / 200 alunos.
  const exLivrosAluno = 35000 / 200;                       // = 175
  const exEstrelasAluno = 40000 / 200;                     // = 200
  const ptsEx = (v: number, melhor: number) =>
    (melhor > 0 ? Math.min(1000, (v / melhor) * 1000) : 0);

  return (
    <div>
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        aria-expanded={aberto}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300"
      >
        <HelpCircle size={14} /> Como funciona o ranking?
      </button>
      {aberto && (
        <div className="mt-2 max-w-2xl space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/60 p-3.5 text-sm text-zinc-700 dark:border-indigo-500/20 dark:bg-indigo-500/5 dark:text-zinc-200">
          <p className="rounded-md bg-white/60 p-2 text-xs dark:bg-zinc-900/50">
            O sistema mostra <b>duas medidas diferentes</b>, e vale não confundir:<br />
            <b>① Índice da rede (0–1000)</b> — ordena este ranking. Compara as escolas
            entre si, proporcionalmente ao tamanho de cada uma.<br />
            <b>② Notas de desempenho (0–100)</b> — as médias de Leitura/Matemática que
            aparecem no Panorama. Medem <b>quão bem vão os alunos que usam</b> a plataforma.
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
            <Formula>Livros por aluno = Total de livros lidos ÷ Nº de alunos da escola</Formula>
            <p>2. Depois, a comparação com a melhor escola da rede:</p>
            <Formula>
              Pontuação de Leitura = mín(1000 ; Livros por aluno ÷ Melhor da rede × 1000)
            </Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              “Melhor da rede” é o maior valor de livros por aluno entre as escolas
              {melhorLeitura > 0 && <> — hoje <b>{dec(melhorLeitura)} livros/aluno</b></>}.
              Quem tem esse valor marca 1000; metade dele marca 500.
            </p>
          </div>}

          {temMatematica && <div>
            <p className="font-semibold">🔢 Matemática (Matific)</p>
            <p className="mt-1">Mesma lógica, com o indicador da plataforma:</p>
            <Formula>Estrelas por aluno = Total de estrelas ÷ Nº de alunos da escola</Formula>
            <Formula>
              Pontuação de Matemática = mín(1000 ; Estrelas por aluno ÷ Melhor da rede × 1000)
            </Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              O Matific informa <b>atividades finalizadas</b> e <b>estrelas</b> — não
              “questões”. As atividades aparecem como contexto; quem decide a posição são as
              estrelas por aluno
              {melhorMat > 0 && <> (melhor da rede hoje: <b>{dec(melhorMat)}/aluno</b>)</>}.
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
            ② Notas de desempenho (0–100) — as médias do Panorama
          </p>
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            Estas notas medem <b>o desempenho de quem usa</b> a plataforma. Aluno sem dado
            NÃO entra como zero — ele simplesmente não é contado (quantos usam é a
            <b> adoção</b>, mostrada à parte).
          </p>

          {temLeitura && <div>
            <p className="font-semibold">📚 Nota de Leitura (0–100)</p>
            <p className="mt-1">Cada indicador do Elefante vira 0–100 comparando o aluno com os colegas da própria escola:</p>
            <Formula>
              volume (livros, tempo, tentativas): mín(100 ; [v ÷ (v+k)] ÷ [R ÷ (R+k)] × 100)
            </Formula>
            <Formula>qualidade (acertos, dificuldade): mín(100 ; v ÷ R × 100)</Formula>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              <b>R</b> = referência da escola (o <b>percentil 90</b> dos alunos que usam —
              escola pequena usa o maior valor). <b>k</b> = a <b>mediana</b>, que dá
              “retornos decrescentes” ao volume: dobrar a quantidade não dobra a nota.
            </p>
            <p className="mt-1.5">Os indicadores entram com os pesos configurados:</p>
            <Formula>
              Nota do aluno = 35%·livros + 30%·dificuldade + 30%·questões + 5%·tempo
            </Formula>
            <Formula>questões = 30%·tentativas + 70%·acertos</Formula>
            <Formula>Nota de Leitura da escola = média das notas dos alunos COM dado do Elefante</Formula>
          </div>}

          {temMatematica && <div>
            <p className="font-semibold">🔢 Nota de Matemática (0–100)</p>
            <p className="mt-1">Mesma normalização (P90 da escola, saturação no volume), com os indicadores do Matific:</p>
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
              Leitura: <b>80 é desempenho</b>; <b>75%/80% é participação</b>. Os 50 alunos
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
            <b>Aba aberta ({aba.rotulo}):</b> {aba.explicacao}
          </p>
        </div>
      )}
    </div>
  );
}

function ConteudoRankingDaRede({ redeId }: { redeId: number }) {
  const { dados, erro, carregando } = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const { selecionarEscola } = useApp();
  const navegar = useNavigate();
  const [abaIdx, setAbaIdx] = useState(0);

  // MÓDULOS CONTRATADOS: aba, coluna e explicação de produto não contratado não
  // existem para esta rede (≠ "sem dados", que existe e mostra vazio).
  const mods = dados?.modulos ?? ["leitura", "matematica"];
  const abas = useMemo(
    () => ABAS.filter((a) => !a.modulo || mods.includes(a.modulo)),
    [mods.join("|")],
  );
  const aba = abas[Math.min(abaIdx, abas.length - 1)] ?? ABAS[0];

  const ranked = useMemo(
    () => [...(dados?.escolas ?? [])]
      .filter((e) => e.alunos_com_dados > 0)
      // Desempate estável: métrica principal → participação → nome.
      .sort((a, b) => aba.ordenar(b) - aba.ordenar(a)
        || num(b.adocao) - num(a.adocao)
        || a.nome.localeCompare(b.nome, "pt-BR")),
    [dados, aba],
  );

  if (carregando && !dados) return <Carregando texto="Carregando o ranking da rede..." />;
  if (erro && !dados) {
    return <Vazio titulo="Não foi possível carregar o ranking" descricao={erro.message} />;
  }
  if (!dados) return null;

  const abrir = (id: number) => { selecionarEscola(id); navegar("/escola"); };

  return (
    <div className="space-y-4">
      <PageHeader
        titulo="🏆 Ranking da Rede"
        descricao={`${dados.escolas.length} escola(s) • ano letivo corrente • comparação proporcional ao tamanho da escola`}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="tablist"
          aria-label="Categoria do ranking"
          className="inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60"
        >
          {abas.map((opt, i) => {
            const Icone = opt.icone;
            return (
              <button
                key={opt.chave}
                type="button"
                role="tab"
                aria-selected={i === abaIdx}
                onClick={() => setAbaIdx(i)}
                className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  i === abaIdx
                    ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                }`}
              >
                <Icone size={14} /> {opt.rotulo}
              </button>
            );
          })}
        </div>
        <ComoFunciona aba={aba} escolas={dados.escolas ?? []} modulos={mods} />
      </div>

      <Card className="p-4">
        {ranked.length === 0 ? (
          <Vazio
            titulo="Sem dados ainda"
            descricao="Nenhuma escola da rede tem dados das plataformas no ano letivo corrente."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <caption className="sr-only">
                Ranking das escolas da rede por {aba.rotulo}
              </caption>
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th scope="col" className="px-3 py-2 font-medium">#</th>
                  <th scope="col" className="px-3 py-2 font-medium">Escola</th>
                  {aba.colunas.map((c) => (
                    <th
                      key={c.rotulo}
                      scope="col"
                      title={c.dica}
                      className={`px-3 py-2 text-right font-medium ${
                        c.ocultarAte ? OCULTAR[c.ocultarAte] : ""
                      } ${c.destaque ? "text-indigo-600 dark:text-indigo-400" : ""}`}
                    >
                      <span className="sm:hidden">{c.curto ?? c.rotulo}</span>
                      <span className="hidden sm:inline">{c.rotulo}</span>
                    </th>
                  ))}
                  {aba.chave === "engajamento" && (
                    <th scope="col" className={`px-3 py-2 text-right font-medium ${OCULTAR.sm}`}>Nível</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {ranked.map((e, i) => {
                  const faixa = faixaEngajamento(num(e.adocao));
                  return (
                    <tr
                      key={e.escola_id}
                      className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50 dark:border-zinc-800/60 dark:hover:bg-zinc-800/40"
                    >
                      <td className="px-3 py-2 text-center">
                        {MEDALHAS[i] ?? <span className="text-xs font-bold text-zinc-400">{i + 1}º</span>}
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => abrir(e.escola_id)}
                          className="text-left font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                        >
                          {e.nome}
                        </button>
                        {e.dimensoes_pontuadas?.length === 1 && (
                          <span
                            className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium text-amber-700 bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300"
                            title="A escola só tem dados de uma plataforma; o índice geral considera apenas ela."
                          >
                            só {e.dimensoes_pontuadas[0] === "leitura" ? "leitura" : "matemática"}
                          </span>
                        )}
                      </td>
                      {aba.colunas.map((c) => (
                        <td
                          key={c.rotulo}
                          className={`px-3 py-2 text-right ${c.ocultarAte ? OCULTAR[c.ocultarAte] : ""} ${
                            c.destaque
                              ? "text-base font-bold text-indigo-700 dark:text-indigo-300"
                              : "text-zinc-600 dark:text-zinc-300"
                          }`}
                        >
                          {c.valor(e)}
                        </td>
                      ))}
                      {aba.chave === "engajamento" && (
                        <td className={`px-3 py-2 text-right ${OCULTAR.sm}`}>
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${faixa.classe}`}>
                            {faixa.rotulo}
                          </span>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="px-1 text-xs text-zinc-500 dark:text-zinc-400">
        Clique em uma escola para ver o panorama detalhado dela. Os dados são agregados
        por escola — o ranking da rede nunca expõe informação individual de aluno.
      </p>
    </div>
  );
}

/** Página dedicada do Ranking da Rede (Secretaria e Admin Global). */
export default function RankingDaRede() {
  return <EnvolucroRede>{(redeId) => <ConteudoRankingDaRede redeId={redeId} />}</EnvolucroRede>;
}
