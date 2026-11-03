/**
 * Exemplos INVENTADOS (regra D13 — nenhum nome, código ou arquivo real) da tela Escolas
 * (`/rede/escolas`) e da ficha da escola (`/rede/escolas/:id`), DESENHO3 §3. Reaproveita o mundo
 * sintético de `AnaliseFixturesDiagnostico`/`SecretariaFixtures` (Alfa 2, Beta 3, Gama 4, Delta 5)
 * e acrescenta o que estas telas leem a mais:
 *  - uma 5ª escola, Épsilon (6): INATIVA no cadastro e SEM coleta nenhuma (sem dado, nunca 0);
 *  - os cartões do painel da rede (`/redes/1/dashboard`): cadastro, cidade, alunos, turmas;
 *  - as escolas do CONTEXTO (`GET /escolas`, a lista do cartão Contexto): só as ATIVAS, como o
 *    servidor manda — a Épsilon (inativa) fica fora;
 *  - a análise de cada escola (`/escolas/{id}/analise`): as avaliações externas por edição —
 *    Alfa com SARESP e IEE (e o ICA, que é só da rede), Beta com média instável, Delta com Ideb;
 *    Gama (sem código INEP) e Épsilon (fora de todas as edições importadas) no formato REAL do
 *    servidor sem número da escola — os 5 indicadores presentes, a série da escola sem valor;
 *  - a evolução por bimestre de UMA escola (`evolucaoDaEscola`), no formato do serviço, para a
 *    ficha: a escola com todas as séries pequenas (`evolucaoSeriesSuprimidas`) e as faltas com motivo.
 * Não é arquivo de teste (o vitest só roda `*.test.tsx`).
 */
import { Route, Routes, useLocation } from "react-router-dom";

import { useApp } from "../context/AppContext";
import type {
  EscolaPlataformas, PontoAnalise, RespostaAnaliseEscola, RespostaPlataformas, SerieAnalise,
} from "../pages/analise/tipos";
import type { EscolaNoBimestre, RespostaEvolucao } from "../pages/analise/tiposDiagnostico";
import type { DashboardRede, EscolaCartao } from "../pages/rede/comum";
import CompararEscolas from "../pages/rede/secretaria/CompararEscolas";
import FichaEscolaRede from "../pages/rede/secretaria/FichaEscolaRede";
import { FONTE, evolucao, plataformasRede, secretaria } from "./AnaliseFixturesDiagnostico";
import { painelRede, semearSecretaria } from "./SecretariaFixtures";
import { escolaFake, renderComApp, responder, type OpcoesRender } from "./utils";

/** O bloco de uma plataforma SEM coleta nenhuma (o formato do serviço: o motivo, nunca 0). */
const SEM_COLETA = {
  alunos_medidos: null, participacao_pct: null, coleta_parcial: false, coberto_ate: null,
  motivo_sem_dado: "sem_coleta", texto_sem_dado: "a escola não tem nenhuma coleta desta plataforma (texto sintético)",
};

export const EPSILON: EscolaPlataformas = {
  escola_id: 6, nome: "EMEF Sintética Épsilon", alunos: 40,
  cobertura: { elefante: "sem_coleta", matific: "sem_coleta" },
  ultima_coleta: { elefante: null, matific: null }, coberto_ate: { elefante: null, matific: null },
  elefante: { ...SEM_COLETA, alunos_com_leitura: null, livros_por_aluno: null, minutos_por_aluno: null, nivel_medio: null,
              taxa_acerto_pct: null, janela_questoes: null },
  matific: { ...SEM_COLETA, alunos_com_retrato: null, atividades_por_aluno: null, estrelas_por_aluno: null,
             desempenho_medio: null },
  series: [],
};

/** As plataformas da rede com a Épsilon (sem coleta nenhuma) — as 5 escolas. */
export function plataformasComEpsilon(over: Partial<RespostaPlataformas> = {}): RespostaPlataformas {
  const base = plataformasRede();
  return {
    ...base,
    escolas: [...base.escolas.map((e) => (e.escola_id === 2
      ? { ...e, ultima_coleta: { elefante: "2026-10-18T03:10:00", matific: "2026-10-19T03:12:00" } } : e)), EPSILON],
    ...over,
  };
}

export function cartao(over: Partial<EscolaCartao> & { escola_id: number; nome: string }): EscolaCartao {
  return {
    cidade: "Cidade Sintética", status: "ativa", latitude: null, longitude: null,
    total_turmas: 5, total_professores: 7, total_alunos: 120,
    media_geral: 70, media_matific: 70, media_elefante: 70, dimensoes_com_dados: ["leitura", "matematica"],
    alunos_com_nota_elefante: 90, alunos_com_nota_matific: 80, alunos_com_dados: 100, comparada: true,
    adocao: 83, adocao_elefante: 75, adocao_matific: 67, livros: 300, tempo_leitura_min: 4000, atividades: 1200,
    estrelas: 2500, ativos_matific: 80, ativos_elefante: 90, livros_por_aluno: 3, livros_por_matricula: 2.5,
    estrelas_por_matricula: 20, atividades_por_matricula: 10, tempo_por_matricula_min: 33,
    pontuacao_leitura: 800, pontuacao_matematica: 700, pontuacao_geral: 750, dimensoes_pontuadas: ["leitura"],
    precisa_atencao: false, motivo_atencao: null,
    ...over,
  };
}

/** O painel da rede com os cartões das 5 escolas (a Épsilon inativa). */
export function painelEscolas(): DashboardRede {
  return {
    ...painelRede({ escolas: 5, escolas_ativas: 4 }),
    escolas: [
      cartao({ escola_id: 2, nome: "EMEF Sintética Alfa", total_alunos: 150, total_turmas: 6, total_professores: 8 }),
      cartao({ escola_id: 3, nome: "EMEF Sintética Beta" }),
      cartao({ escola_id: 4, nome: "EMEI Sintética Gama", total_alunos: 30, total_turmas: 2, total_professores: 3 }),
      cartao({ escola_id: 5, nome: "EMEF Sintética Delta", total_alunos: 130, cidade: null }),
      cartao({ escola_id: 6, nome: "EMEF Sintética Épsilon", status: "inativa", total_alunos: 40, total_turmas: 2,
               total_professores: 2 }),
    ],
  };
}

function ponto(edicao: number, valor: number | null, over: Partial<PontoAnalise> = {}): PontoAnalise {
  return {
    edicao, valor, casas: valor == null ? null : 1, motivo_ausencia: valor == null ? "fora_do_arquivo" : null,
    texto_ausencia: valor == null ? "a escola não está no arquivo oficial importado desta edição" : null,
    meta: null, meta_casas: null, diferenca_meta: null, situacao_meta: null, instavel: false, fonte_id: 21, ...over,
  };
}

function serie(over: Partial<SerieAnalise> & { pontos: PontoAnalise[] }): SerieAnalise {
  return {
    id: "x", rotulo: "Escola sintética", papel: "principal", abrangencia: "escola", escola_id: null,
    rede_ensino: "municipal", mesma_rede: true, comparavel: true, motivo_nao_comparavel: null, etapa: null,
    componente: null, ...over,
  };
}

const redeRef = (etapa: string | null, componente: string | null, pontos: PontoAnalise[]) =>
  serie({ id: "rede_municipal", rotulo: "Cidade Sintética — rede municipal", papel: "referencia", abrangencia: "rede",
          etapa, componente, pontos });

/** Os indicadores e as combinações (etapa × componente) do servidor, na ORDEM dele
 *  (`backend/app/services/analise/indicadores.py`: `ORDEM`, `etapas`, `componentes`, `por_escola`). */
const INDICADORES_DO_SERVIDOR: { chave: string; nome: string; unidade: string; porEscola: boolean;
  combos: [string, string | null][] }[] = [
  { chave: "ica", nome: "ICA", unidade: "%", porEscola: false, combos: [["2_ano", "lp"]] },
  { chave: "saresp", nome: "SARESP", unidade: "pontos", porEscola: true,
    combos: [["5_ano", "lp"], ["5_ano", "mt"], ["2_ano", "lp"], ["2_ano", "mt"]] },
  { chave: "iee", nome: "IEE", unidade: "índice", porEscola: true, combos: [["anos_iniciais", null]] },
  { chave: "ideb", nome: "Ideb", unidade: "índice", porEscola: true, combos: [["anos_iniciais", null]] },
  { chave: "saeb", nome: "Saeb", unidade: "pontos", porEscola: true, combos: [["5_ano", "lp"], ["5_ano", "mt"]] },
];

/** A rede municipal do mundo sintético, por `indicador|etapa|componente` (a referência da escola). */
export const REDE_SINTETICA: Record<string, PontoAnalise[]> = {
  "ica|2_ano|lp": [ponto(2025, 58, { casas: 0 })],
  "saresp|5_ano|lp": [ponto(2024, 210.0), ponto(2025, 212.4)],
  "ideb|anos_iniciais|": [ponto(2023, 6.0)],
};

/**
 * Os indicadores de uma escola SEM número dela, no formato REAL do servidor
 * (`indicadores_da_escola`): os 5 sempre presentes, na ordem; em cada combinação, a série DA
 * escola (a principal) — sem ponto nenhum quando nenhuma edição importada a traz, ou com os pontos
 * sem valor (e o motivo) de `pontosDaEscola` — e a rede municipal só onde `daRede` tem ponto. O ICA
 * (só da rede) não tem série da escola.
 */
export function indicadoresSemNumeroDaEscola(id: number, nome: string, opcoes: {
  pontosDaEscola?: (chave: string) => PontoAnalise[];
  daRede?: Record<string, PontoAnalise[]>;
} = {}): RespostaAnaliseEscola["indicadores"] {
  const { pontosDaEscola = () => [], daRede = {} } = opcoes;
  return INDICADORES_DO_SERVIDOR.map((ind) => {
    const series = ind.combos.flatMap(([etapa, componente]) => {
      const rede = daRede[`${ind.chave}|${etapa}|${componente ?? ""}`] ?? [];
      return [
        ...(ind.porEscola
          ? [serie({ id: `escola_${id}`, rotulo: nome, escola_id: id, etapa, componente, pontos: pontosDaEscola(ind.chave) })]
          : []),
        ...(rede.length ? [redeRef(etapa, componente, rede)] : []),
      ];
    });
    return {
      chave: ind.chave, nome: ind.nome, unidade: ind.unidade, por_escola: ind.porEscola,
      disponivel: series.some((s) => s.pontos.some((p) => p.valor != null)), series, quebras: [], avisos: [],
    };
  });
}

/** Os pontos da escola sem código INEP: as edições importadas, cada uma com o motivo (sem número). */
const semInepNasEdicoes = (chave: string): PontoAnalise[] => {
  const edicoes = chave === "iee" ? [2025] : chave === "ideb" || chave === "saeb" ? [2021, 2023] : [2024, 2025];
  return edicoes.map((ed) => ponto(ed, null, {
    motivo_ausencia: "sem_codigo_inep", texto_ausencia: "a escola está sem código INEP no cadastro" }));
};

const NOMES: Record<number, string> = {
  2: "EMEF Sintética Alfa", 3: "EMEF Sintética Beta", 4: "EMEI Sintética Gama", 5: "EMEF Sintética Delta",
  6: "EMEF Sintética Épsilon",
};

/** A lista do CONTEXTO da Secretaria (`GET /escolas`): só as escolas ATIVAS da rede (o servidor não
 *  manda a inativa) — a Épsilon (6) fica fora. */
export const ESCOLAS_DO_CONTEXTO = [2, 3, 4, 5].map((id) => escolaFake({ id, nome: NOMES[id] }));

/** Um indicador só com a série DA escola, com um número em cada edição pedida (para os testes que
 *  montam escolas com edições diferentes do mesmo indicador). */
export function indicadorDaEscola(id: number, chave: string, nome: string, etapa: string | null,
                                  componente: string | null, edicoes: [number, number][],
                                  unidade = "índice"): RespostaAnaliseEscola["indicadores"][number] {
  return {
    chave, nome, unidade, avisos: [],
    series: [serie({ id: `escola_${id}`, rotulo: NOMES[id] ?? `Escola ${id}`, escola_id: id, etapa, componente,
                     pontos: edicoes.map(([edicao, valor]) => ponto(edicao, valor)) })],
  };
}

/** `/escolas/{id}/analise` de cada escola sintética (as avaliações externas por edição). */
export function analiseEscola(id: number): RespostaAnaliseEscola {
  const nome = NOMES[id] ?? `Escola ${id}`;
  const principal = (etapa: string | null, componente: string | null, pontos: PontoAnalise[]) =>
    serie({ id: `escola_${id}`, rotulo: nome, escola_id: id, etapa, componente, pontos });
  const porEscola: Record<number, RespostaAnaliseEscola["indicadores"]> = {
    2: [
      { chave: "ica", nome: "ICA", unidade: "%", avisos: [],
        series: [redeRef("2_ano", "lp", [ponto(2025, 58, { casas: 0 })])] },
      { chave: "saresp", nome: "SARESP", unidade: "pontos", avisos: ["O SARESP tem escala própria (texto sintético)."],
        series: [principal("5_ano", "lp", [ponto(2024, 214.0), ponto(2025, 219.6)]),
                 redeRef("5_ano", "lp", [ponto(2024, 210.0), ponto(2025, 212.4)])] },
      { chave: "iee", nome: "IEE", unidade: "índice", avisos: [],
        series: [principal("anos_iniciais", null, [ponto(2025, 4.8, {
          casas: 2, meta: 5.2, meta_casas: 2, diferenca_meta: -0.4, situacao_meta: "nao_atingiu" })])] },
    ],
    3: [
      { chave: "saresp", nome: "SARESP", unidade: "pontos", avisos: [],
        series: [principal("5_ano", "lp", [ponto(2025, 198.0)]),
                 principal("5_ano", "mt", [ponto(2025, 230.1, { instavel: true })]),
                 redeRef("5_ano", "lp", [ponto(2025, 212.4)])] },
    ],
    // Sem número da escola, no formato REAL: os 5 indicadores presentes. Gama sem código INEP (as
    // edições importadas dizem isso); Épsilon inativa e fora de todas as edições (a série dela sem
    // ponto), com a rede municipal como referência.
    4: indicadoresSemNumeroDaEscola(4, NOMES[4], { pontosDaEscola: semInepNasEdicoes, daRede: REDE_SINTETICA }),
    5: [
      { chave: "ideb", nome: "Ideb", unidade: "índice", avisos: [],
        series: [principal("anos_iniciais", null, [ponto(2021, 5.8), ponto(2023, 6.1)]),
                 redeRef("anos_iniciais", null, [ponto(2023, 6.0)])] },
    ],
    6: indicadoresSemNumeroDaEscola(6, NOMES[6], { daRede: REDE_SINTETICA }),
  };
  return {
    escola: { id, nome, codigo_inep: id === 4 ? null : `3599000${id}`, pendencia: id === 4 ? "sem_codigo_inep" : null },
    rede: { id: 1, nome: "Rede Sintética Norte" },
    indicadores: porEscola[id] ?? [],
    plataformas: null,
    comparacoes_indisponiveis: [
      { tema: "ica", texto: "O ICA é da rede: não existe por escola." },
      { tema: "relacao", texto: "Relação com as plataformas: período sem sobreposição (texto sintético)." },
    ],
    fontes: { "21": FONTE },
  };
}

/** O texto do serviço quando TODAS as séries da escola têm poucos alunos (`SERIES_SUPRIMIDAS`). */
export const TEXTO_SERIES_SUPRIMIDAS = "todas as séries desta escola têm poucos alunos: os números das plataformas "
  + "não aparecem, para proteger as crianças (texto sintético)";

type BlocoDaEscola = NonNullable<EscolaNoBimestre["elefante"]> & NonNullable<EscolaNoBimestre["matific"]>;

/** O bloco de uma plataforma SEM número num bimestre, como o serviço manda (`evolucao._bloco`): os
 *  campos nulos, o motivo e o texto dele — nunca 0. */
export function blocoSemNumero(motivo: string, texto: string, over: Partial<BlocoDaEscola> = {}): BlocoDaEscola {
  return {
    participacao_pct: null, livros_por_aluno: null, atividades_por_aluno: null, motivo_sem_dado: motivo,
    texto_sem_dado: texto, coleta_parcial: false, metricas_protegidas: [], ...over,
  };
}

/**
 * A evolução por bimestre pedida com `escola_id` (a da ficha): os 4 bimestres de `evolucao()` com
 * SÓ esta escola, a coleta em dia e os blocos de `blocos(numero)` em cada bimestre.
 */
export function evolucaoDaEscola(id: number, blocos: (numero: number) => Partial<EscolaNoBimestre>): RespostaEvolucao {
  const base = evolucao();
  return {
    ...base,
    bimestres: base.bimestres.map((b) => ({
      ...b,
      escolas: [{ id, nome: NOMES[id] ?? `Escola ${id}`, cobertura: { elefante: "ok", matific: "ok" }, suprimido: false,
                  elefante: null, matific: null, ...blocos(b.numero) }],
    })),
  };
}

/** A escola com TODAS as séries pequenas (o caso da ficha protegida): nenhum número em nenhum
 *  bimestre, o mesmo motivo nas duas plataformas (o formato do serviço). */
export const evolucaoSeriesSuprimidas = (id: number) => evolucaoDaEscola(id, () => ({
  elefante: blocoSemNumero("series_suprimidas", TEXTO_SERIES_SUPRIMIDAS),
  matific: blocoSemNumero("series_suprimidas", TEXTO_SERIES_SUPRIMIDAS),
}));

/** Todas as leituras da tela Escolas e da ficha (cada teste sobrescreve o que quiser). */
export function semearEscolas() {
  semearSecretaria();
  responder("GET", "/redes/1/analise/plataformas", plataformasComEpsilon());
  responder("GET", "/redes/1/dashboard", painelEscolas());
  responder("GET", (c) => /^\/escolas\/\d+\/analise(\?|$)/.test(c),
            (c: string) => analiseEscola(Number(c.split("/")[2])));
}

/** Mostra o caminho atual, o "Voltar" levado no estado e a escola do CONTEXTO (Ver as turmas). */
function Onde() {
  const l = useLocation();
  const { escolaId } = useApp();
  const voltar = (l.state as { voltar?: { caminho: string; texto: string } } | null)?.voltar;
  return (
    <p data-testid="onde" data-voltar-caminho={voltar?.caminho ?? ""} data-voltar-texto={voltar?.texto ?? ""}
       data-escola-contexto={escolaId ?? ""}>
      {`${l.pathname}${l.search}`}
    </p>
  );
}

/** A lista e a ficha nas rotas de verdade (a ficha com o `:escolaId`), mais a Visão da Escola. O
 *  contexto traz as escolas ATIVAS (`ESCOLAS_DO_CONTEXTO`), como o servidor. */
export function renderEscolas(caminho: string, opcoes: OpcoesRender = {}) {
  return renderComApp(
    <>
      <Routes>
        <Route path="/rede/escolas" element={<CompararEscolas />} />
        <Route path="/rede/escolas/:escolaId" element={<FichaEscolaRede />} />
        <Route path="/escola" element={<p>TELA:escola</p>} />
        <Route path="*" element={<p>TELA:outra</p>} />
      </Routes>
      <Onde />
    </>,
    { usuario: secretaria, rota: caminho, escolas: ESCOLAS_DO_CONTEXTO, ...opcoes },
  );
}
