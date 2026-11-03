/**
 * Exemplos INVENTADOS (regra D13 — nenhum nome, código ou arquivo real) e utilitários dos testes
 * das telas principais da Secretaria (DESENHO2 §2.3). Reaproveita o mundo sintético de
 * `AnaliseFixturesDiagnostico` (4 escolas: Alfa, Beta, Gama, Delta) e acrescenta o que as telas
 * novas leem a mais: o ICA com meta nos destaques, a Estimativa Constela, o número sem registro,
 * os alertas de cadastro e o painel da rede (totais do ano letivo). Não é arquivo de teste (o
 * vitest só roda `*.test.tsx`).
 */
import type { ReactElement } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { expect } from "vitest";

import type { RespostaIndicadoresRede, RespostaPlataformas } from "../pages/analise/tipos";
import type { DashboardRede, DestaquesRede, EscolaCartao } from "../pages/rede/comum";
import { baseRede, diagnostico, evolucao, plataformasRede, secretaria } from "./AnaliseFixturesDiagnostico";
import { api, renderComApp, responder, type OpcoesRender } from "./utils";

export { admin, baseRede, diagnostico, evolucao, plataformasRede, secretaria } from "./AnaliseFixturesDiagnostico";

/** O catálogo com o ICA (só da rede, com meta: 58% × 60%), a estimativa, o sem registro e alertas. */
export function catalogo(over: Partial<RespostaIndicadoresRede> = {}): RespostaIndicadoresRede {
  const b = baseRede();
  return {
    ...b,
    indicadores: [
      { chave: "ica", nome: "Indicador Criança Alfabetizada (ICA)", orgao: "INEP", oficial: true, unidade: "%",
        escala: "percentual", disponivel: true, motivo_indisponivel: null, abrangencias: ["rede"], por_escola: false,
        etapas: ["2_ano"], componentes: ["lp"], edicoes: [2024, 2025], edicao_mais_recente: 2025, tem_meta: true,
        avisos: ["O ICA existe só para a rede (texto sintético)."] },
      ...b.indicadores,
      { chave: "saeb", nome: "Saeb", orgao: "INEP", oficial: true, unidade: "pontos", escala: "escala_saeb",
        disponivel: false, motivo_indisponivel: "sem_importacao", abrangencias: ["rede", "escola"], por_escola: true,
        etapas: ["5_ano"], componentes: ["lp", "mt"], edicoes: [], edicao_mais_recente: null, tem_meta: false, avisos: [] },
    ],
    destaques: [
      { indicador: "ica", rotulo: "ICA da rede (2º ano)", edicao: 2025, valor: 58, casas: 0, unidade: "%", meta: 60,
        meta_casas: 0, diferenca_meta: -2, situacao_meta: "nao_atingiu", etapa: "2_ano", componente: "lp", fonte_id: 21,
        serie: [{ edicao: 2024, valor: 55 }, { edicao: 2025, valor: 58 }] },
      ...b.destaques,
    ],
    estimativas: [{ chave: "ideb_estimado", nome: "Ideb estimado", edicoes: [2025], tipo: "estimativa_constela" }],
    sem_registro_oficial: [{ chave: "ideb", nome: "Ideb", edicoes: [2023] }],
    alertas: [
      { tipo: "cadastro", escolas: [4], texto: "Escola sem código INEP no cadastro (texto sintético)." },
      ...b.alertas,
    ],
    ...over,
  };
}

/** Textos no MOLDE dos que o servidor manda na metodologia e nas limitações (a relação
 *  estatística é assunto das Análises avançadas). */
export const METODOLOGIA_COM_RELACAO = [
  "Sem resultado não é zero: cada falta vem com o motivo (texto sintético).",
  "Relação com as avaliações: por escola, com números oficiais, no mesmo ano letivo; correlação de postos de "
    + "Spearman com intervalo de 95%. Descreve associação entre escolas, nunca causa e efeito.",
];
export const LIMITACOES_COM_RELACAO = [
  "Coleta atrasada: a escola aparece como coleta parcial (texto sintético). Na relação estatística, toda coleta "
    + "parcial fica fora.",
  "Coorte: alunos ativos do 1º ao 5º ano (texto sintético).",
  "As plataformas só têm dados do ano letivo em curso; as avaliações oficiais por escola são de anos anteriores. "
    + "Por isso a relação entre as duas só é calculada no mesmo ano letivo — e, mesmo assim, não mede causa e efeito.",
];

/** O painel da rede (`/redes/1/dashboard`): só os totais importam para as telas novas. */
export function painelRede(over: Partial<DashboardRede["totais"]> = {}, modulos = ["leitura", "matematica"]): DashboardRede {
  return {
    rede_id: 1,
    modulos,
    totais: {
      escolas: 4, escolas_ativas: 4, alunos: 400, turmas: 16, professores: 22, alunos_com_dados: 360, adocao: 90,
      media_geral: 71.9, media_matific: 68.5, media_elefante: 61.2, pontuacao_geral: 640, escolas_em_atencao: 1,
      livros: 1300, tempo_leitura_min: 18200, atividades: 5130, estrelas: 10800, ativos_matific: 330,
      ativos_elefante: 350, livros_por_aluno: 3.25,
      melhor_escola: { nome: "EMEF Sintética Alfa", pontuacao_geral: 1000, media_geral: 73.5 },
      ...over,
    },
    equidade: { gap_indice: 300, escola_maior_indice: 1000, escola_menor_indice: 700, escolas_abaixo_do_indice_medio: 2,
                gap_media: 13.5, escola_maior_media: 73.5, escola_menor_media: 60, escolas_abaixo_da_media: 1 },
    escolas: [],
    atencao: [],
  };
}

/** O cartão AGREGADO de uma escola no painel da rede (`/redes/1/dashboard`). Os números de
 *  conta (`alunos_com_dados`, `adocao`) NÃO são uso: o Panorama não os lê para isso. */
export function cartaoEscola(over: Partial<EscolaCartao> = {}): EscolaCartao {
  return {
    escola_id: 2, nome: "EMEF Sintética Alfa", cidade: "Cidade Sintética", status: "ativa", latitude: null,
    longitude: null, total_turmas: 6, total_professores: 7, total_alunos: 150, media_geral: 70, media_matific: 68,
    media_elefante: 72, dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 100,
    alunos_com_nota_matific: 90, alunos_com_dados: 120, comparada: true, adocao: 80, adocao_elefante: 70,
    adocao_matific: 60, modulos: ["leitura", "matematica"], livros: 300, tempo_leitura_min: 4000, atividades: 900,
    estrelas: 2000, ativos_matific: 90, ativos_elefante: 100, livros_por_aluno: 3, livros_por_matricula: 2,
    estrelas_por_matricula: 13.3, atividades_por_matricula: 6, tempo_por_matricula_min: 26.7, pontuacao_leitura: 800,
    pontuacao_matematica: 900, pontuacao_geral: 850, dimensoes_pontuadas: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null, posicao: 1,
    ...over,
  };
}

/**
 * O mundo do PANORAMA (DESENHO3 §2): as 4 escolas da análise e mais duas — a Épsilon, INATIVA e
 * sem nenhum aluno; e a Zeta, ativa, com a coleta em dia e nenhum uso. A Gama não tem código
 * INEP (nenhuma avaliação externa) e fica protegida nas plataformas. Entregues fora de ordem.
 * Cadastradas 6 ≠ ativas 5 ≠ com uso 3 (Alfa, Beta, Delta).
 */
export function painelDoPanorama(modulos = ["leitura", "matematica"]): DashboardRede {
  const cartoes = [
    cartaoEscola({ escola_id: 5, nome: "EMEF Sintética Delta", total_alunos: 130, modulos }),
    cartaoEscola({ escola_id: 7, nome: "EMEF Sintética Zeta", total_alunos: 60, alunos_com_dados: 50, adocao: 83, modulos }),
    cartaoEscola({ escola_id: 3, nome: "EMEF Sintética Beta", total_alunos: 120, modulos }),
    // Inativa e sem alunos — o painel a traz com zeros (zero de conta, não de uso).
    cartaoEscola({ escola_id: 6, nome: "EMEF Sintética Épsilon", status: "inativa", total_alunos: 0, total_turmas: 0,
                   alunos_com_dados: 0, adocao: 0, comparada: false, modulos }),
    cartaoEscola({ escola_id: 2, nome: "EMEF Sintética Alfa", total_alunos: 150, modulos }),
    cartaoEscola({ escola_id: 4, nome: "EMEI Sintética Gama", total_alunos: 40, modulos }),
  ];
  return { ...painelRede({ escolas: 6, escolas_ativas: 5 }, modulos), escolas: cartoes };
}

/** As plataformas no ano letivo do mundo do Panorama: as 4 da análise, a Épsilon (sem aluno do
 *  1º ao 5º ano) e a Zeta (coleta em dia, ninguém leu nem fez atividade). */
export function plataformasDoPanorama(over: Partial<RespostaPlataformas> = {}): RespostaPlataformas {
  const base = plataformasRede();
  const semAlunos = (p: "elefante" | "matific") => ({
    ...(p === "elefante" ? base.rede.elefante! : base.rede.matific!), alunos_medidos: null, participacao_pct: null,
    alunos_com_leitura: null, livros_por_aluno: null, atividades_por_aluno: null, motivo_sem_dado: "sem_alunos_no_recorte",
    texto_sem_dado: "nenhum aluno ativo do 1º ao 5º ano matriculado no ano letivo",
  });
  return {
    ...base,
    escolas: [
      ...base.escolas,
      { escola_id: 6, nome: "EMEF Sintética Épsilon", alunos: 0,
        cobertura: { elefante: "sem_alunos_no_recorte", matific: "sem_alunos_no_recorte" },
        elefante: semAlunos("elefante") as RespostaPlataformas["escolas"][number]["elefante"],
        matific: semAlunos("matific") as RespostaPlataformas["escolas"][number]["matific"], series: [] },
      { escola_id: 7, nome: "EMEF Sintética Zeta", alunos: 60, cobertura: { elefante: "ok", matific: "ok" },
        elefante: { ...base.rede.elefante!, alunos_medidos: 50, alunos_com_leitura: 0, participacao_pct: 0, livros_por_aluno: 0 },
        matific: { ...base.rede.matific!, alunos_medidos: 45, participacao_pct: 0, atividades_por_aluno: 0 },
        series: [] },
    ],
    ...over,
  };
}

/** As escolas em destaque (`/redes/1/destaques`, DESENHO3 §6): Alfa e Delta em leitura (uma
 *  terceira ficou fora para a Secretaria, protegida), Beta em matemática. O valor tem UMA casa
 *  decimal, como o servidor manda (`round(…, 1)` em `_top_escolas`). */
export function destaquesRede(over: Partial<DestaquesRede> = {}): DestaquesRede {
  return {
    modulos: ["leitura", "matematica"], limite: 5, k_minimo: 5,
    leitura: { escolas: [{ escola_id: 2, nome: "EMEF Sintética Alfa", valor: 12.4 },
                         { escola_id: 5, nome: "EMEF Sintética Delta", valor: 9.7 }], fora_por_protecao: 1 },
    matematica: { escolas: [{ escola_id: 3, nome: "EMEF Sintética Beta", valor: 41.5 }], fora_por_protecao: 0 },
    ...over,
  };
}

/** A vitrine pública desligada (o estado de `GET /redes/1/publico`). */
export const VITRINE_DESLIGADA = { ativo: false, token: null, url: null };

/** O selo de frescor do cabeçalho: datas sintéticas, nenhuma escola atrasada. */
export const FRESCOR = { limite_dias: 7, escolas: [] };

/** Responde TODAS as leituras das telas novas (cada teste sobrescreve o que quiser). */
export function semearSecretaria() {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
  responder("GET", "/redes/1/analise/indicadores", catalogo());
  responder("GET", "/redes/1/analise/diagnostico", diagnostico());
  responder("GET", "/redes/1/analise/plataformas", plataformasRede());
  responder("GET", "/redes/1/analise/plataformas/evolucao", evolucao());
  responder("GET", "/redes/1/dashboard", painelRede());
  responder("GET", "/redes/1/ranking/frescor", FRESCOR);
  responder("GET", "/redes/1/destaques", destaquesRede());
  responder("GET", "/redes/1/publico", VITRINE_DESLIGADA);
  responder("GET", "/redes/1/metas", []);
}

/** O mundo do Panorama inteiro: o de `semearSecretaria` com as 6 escolas no painel e nas plataformas. */
export function semearPanorama() {
  semearSecretaria();
  responder("GET", "/redes/1/dashboard", painelDoPanorama());
  responder("GET", "/redes/1/analise/plataformas", plataformasDoPanorama());
}

/** Os caminhos que a tela leu (sem a consulta), na ordem — para conferir "só as necessárias". */
export const caminhosLidos = () => [...new Set(api.mock.calls.map(([c]) => String(c).split("?")[0]))]
  .filter((c) => c !== "/auth/me" && c !== "/escolas");
export const chamadas = (caminho: string) =>
  api.mock.calls.map(([c]) => String(c)).filter((c) => c.split("?")[0] === caminho);
export const consulta = (url: string) => new URLSearchParams(url.split("?")[1] ?? "");

/** A tela sem palavra causal (DESENHO2 §1 e §4): "causa", "por causa", "efeito", "impacto", "graças". */
export function semCausalidade(el: HTMLElement) {
  expect(el.textContent ?? "").not.toMatch(/\bcausa|\befeito|impacto|graças/i);
}

/** O fluxo principal sem termo técnico (DESENHO2 §1.5). */
export function semJargao(el: HTMLElement) {
  expect(el.textContent ?? "").not.toMatch(/Spearman|coorte|\bTPS\b|IC 95|correla|proveni|\bk\s*=/i);
}

/** A posição do 1º nó com o texto (para conferir a ORDEM na tela: a conclusão antes do detalhe). */
export function antes(a: Node, b: Node): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

/** Mostra o caminho atual (para conferir para onde um botão levou) e o "Voltar" levado no estado. */
function Onde() {
  const l = useLocation();
  const voltar = (l.state as { voltar?: { caminho: string; texto: string } } | null)?.voltar;
  return (
    <p data-testid="onde" data-voltar-caminho={voltar?.caminho ?? ""} data-voltar-texto={voltar?.texto ?? ""}>
      {`${l.pathname}${l.search}`}
    </p>
  );
}

/**
 * Monta a tela numa rota de verdade (com `Routes`), mais as telas vizinhas como marcas — os
 * links e os botões levam a um lugar que o teste confere.
 */
export function renderTela(caminho: string, tela: ReactElement, opcoes: OpcoesRender = {}) {
  return renderComApp(
    <>
      <Routes>
        <Route path={caminho.split("?")[0]} element={tela} />
        <Route path="/escola" element={<p>TELA:escola</p>} />
        <Route path="*" element={<p>TELA:outra</p>} />
      </Routes>
      <Onde />
    </>,
    { usuario: secretaria, rota: caminho, ...opcoes },
  );
}
