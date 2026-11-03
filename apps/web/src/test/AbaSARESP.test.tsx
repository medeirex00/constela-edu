/**
 * Aba SARESP (etapa E5) na tela da rede — o que a tela garante:
 *
 *  - a série da REDE MUNICIPAL num gráfico por série/componente, com o Estado na
 *    MESMA rede (redes municipais); o 2º ano NÃO liga 2022 a 2023 (possível quebra de
 *    escala) e o 5º ano liga; a rede estadual fica à parte (outra rede);
 *  - níveis do SARESP "a confirmar" (nenhum corte inventado) e os anos marcados;
 *  - o aviso de que o SARESP do 2º ano não é comparável ao ICA;
 *  - a tabela por escola em ordem de NOME (sem ranking), com a proficiência oficial,
 *    participação, TPS, IEE e meta; a estimativa do Constela num bloco SEPARADO;
 *  - "sem resultado" nunca vira 0; a escola sem INEP é pendência de cadastro; o motivo
 *    da linha é o da API (código cadastrado/trocado depois da importação = "reimporte";
 *    D2 "não" = "oficial não gravado") e a frase da estimativa vale por EDIÇÃO;
 *  - corte confirmado: título sem "a confirmar", corte com a fonte, nível e distância;
 *  - selo de fonte em cada bloco (arquivo, edição do SARESP, data do arquivo);
 *  - sem dado: "sem resultado importado".
 *
 * Números, datas, nomes, códigos e arquivos SINTÉTICOS (os mesmos INVENTADOS do
 * teste do backend) — nada dos arquivos da SEDUC (repositório público — D13).
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { textoFonte, type FonteOficial } from "../components/SeloFonte";
import CartaoSARESP, { type RespostaSARESP } from "../pages/rede/CartaoSARESP";
import { renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });

function fonte(over: Partial<FonteOficial> = {}): FonteOficial {
  return {
    importacao_id: 21, fonte_nome: "SEDUC-SP — Proficiência do SARESP por município",
    arquivo_nome: "Proficiência do SARESP por Municipio de 2025_0.csv", arquivo_data: null,
    last_modified_origem: "Mon, 12 Jan 2026 09:00:00 GMT", url_origem: null, edicao_arquivo: 2025,
    versao_rotulo: null, importado_em: "2026-10-17T12:00:00", coletado_em: null, citacao: null,
    licenca: "Dados abertos da SEDUC-SP: uso livre, com citação obrigatória.",
    parser: "seduc_saresp_municipio", modo: "upload", notas: [],
    data_arquivo: "2026-01-12", data_arquivo_origem: "last_modified", ...over,
  };
}
const FMUN = fonte();
const FINST = fonte({ importacao_id: 22, fonte_nome: "SEDUC-SP — Proficiência do SARESP por instância",
  arquivo_nome: "Proficiência do SARESP por instância de 2025_0.csv", parser: "seduc_saresp_instancia",
  data_arquivo: "2025-12-01", last_modified_origem: "Mon, 01 Dec 2025 09:00:00 GMT" });
const FIEE25 = fonte({ importacao_id: 31, fonte_nome: "SEDUC-SP — Índice de Excelência Educacional (IEE)",
  arquivo_nome: "Indice de Excelencia Educacional 2025-2026_0.csv", parser: "seduc_iee" });
const FIEE24 = fonte({ ...FIEE25, importacao_id: 30, arquivo_nome: "Indice de Excelencia Educacional 2024-2025.csv",
  edicao_arquivo: 2024, data_arquivo: "2025-12-01" });

const A_CONFIRMAR = { situacao: "a_confirmar", nivel: null, distancia_adequado: null, calculo_do_constela: true };

function medida(edicao: number, valor: number | null, f: FonteOficial | null, casas = 1, unidade = "escala_saresp") {
  return { edicao, valor, casas_decimais: valor == null ? null : casas, unidade,
           motivo_ausencia: valor == null ? "nao_divulgado" : null, fonte: f, nivel: A_CONFIRMAR };
}

type Valores = Record<string, (number | null)[]>;      // "2_ano-lp" → [2022, 2023, 2024, 2025]
const ANOS = [2022, 2023, 2024, 2025];
const REDE: Valores = {
  "2_ano-lp": [121.3, 133.8, 129.6, 137.1], "2_ano-mt": [118.9, 124.4, null, 131.2],
  "5_ano-lp": [241.6, 238.3, 246.9, 249.4], "5_ano-mt": [252.7, 256.1, 258.8, 263.3],
};
const ESTADO: Valores = {
  "2_ano-lp": [126.6, 131.7, 135.4, 139.2], "2_ano-mt": [122.3, 125.8, 128.6, 133.9],
  "5_ano-lp": [236.4, 239.7, 243.2, 247.8], "5_ano-mt": [248.1, 251.6, 255.9, 259.4],
};

function territorio(chave: string, abrangencia: "municipio" | "uf", rede: "municipal" | "estadual",
                    rotulo: string, valores: Valores | null, f: FonteOficial) {
  const series = ["2_ano", "5_ano"].flatMap((etapa) => ["lp", "mt"].map((componente) => ({
    etapa, componente,
    numeros: valores ? ANOS.map((ano, i) => medida(ano, valores[`${etapa}-${componente}`][i], f)) : [],
  })));
  return { chave, abrangencia, codigo_territorio: abrangencia === "uf" ? "35" : "3599999", rede_ensino: rede,
           mesma_rede: rede === "municipal", nome: null, rotulo, series, tem_dados: Boolean(valores) };
}

function edicaoEscola(edicao: number, f: FonteOficial, v: {
  lp2?: number | null; mt2?: number | null; lp5?: number | null; mt5?: number | null;
  p2?: number | null; p5?: number | null; tps?: number; iee?: number; meta?: number; icm?: number;
} | null, extra: { motivo?: string; tem_estimativa?: boolean } = {}) {
  if (!v) {
    return { edicao, proficiencia: { "2_ano": { lp: null, mt: null }, "5_ano": { lp: null, mt: null } },
             participacao: { "2_ano": null, "5_ano": null }, tps: null, iee: null, meta: null, icm: null,
             tem_resultado: false, no_arquivo: false, motivo: extra.motivo ?? "fora_do_arquivo",
             tem_estimativa: extra.tem_estimativa ?? false };
  }
  const p = (x: number | null | undefined) => (x === undefined ? null : medida(edicao, x, f));
  const prof = { "2_ano": { lp: p(v.lp2), mt: p(v.mt2) }, "5_ano": { lp: p(v.lp5), mt: p(v.mt5) } };
  const temResultado = [v.lp2, v.mt2, v.lp5, v.mt5].some((x) => x != null);
  return {
    edicao, proficiencia: prof,
    participacao: { "2_ano": v.p2 === undefined ? null : medida(edicao, v.p2, f, 1, "percentual"),
                    "5_ano": v.p5 === undefined ? null : medida(edicao, v.p5, f, 1, "percentual") },
    tps: v.tps === undefined ? null : medida(edicao, v.tps, f, 0, "binario"),
    iee: v.iee === undefined ? null : medida(edicao, v.iee, f, 2, "indice"),
    meta: v.meta === undefined ? null : medida(edicao, v.meta, f, 2, "indice"),
    icm: v.icm === undefined ? null : medida(edicao, v.icm, f, 0, "binario"),
    tem_resultado: temResultado, no_arquivo: true,
    motivo: temResultado ? null : (extra.motivo ?? "nao_divulgado"),
    tem_estimativa: extra.tem_estimativa ?? false,
  };
}

function resposta(over: Partial<RespostaSARESP> = {}): RespostaSARESP {
  const linhas = [
    // De propósito FORA da ordem alfabética: a tela mostra por NOME.
    { escola_id: 14, nome: "ESCOLA SINTETICA GAMA", codigo_inep: null, status: "ativa", pendencia: "codigo_inep",
      tem_estimativa: false, por_edicao: [edicaoEscola(2025, FIEE25, null, { motivo: "sem_codigo_inep" }),
                                          edicaoEscola(2024, FIEE24, null, { motivo: "sem_codigo_inep" })] },
    { escola_id: 12, nome: "EMEF Sintética Beta", codigo_inep: "35990002", status: "ativa", pendencia: null,
      tem_estimativa: true, por_edicao: [
        edicaoEscola(2025, FIEE25, { lp2: null, mt2: null, lp5: 201.7, mt5: 189.4, p2: null, p5: 73.2, tps: 1,
                                     iee: 6.04, meta: 5.9, icm: 1 }, { tem_estimativa: true }),
        edicaoEscola(2024, FIEE24, { lp2: null, mt2: null, lp5: null, mt5: null, p5: 73.2, tps: 1 })] },
    { escola_id: 13, nome: "EMEF Sintética Delta", codigo_inep: "35990004", status: "ativa", pendencia: null,
      tem_estimativa: false, por_edicao: [edicaoEscola(2025, FIEE25, null), edicaoEscola(2024, FIEE24, null)] },
    { escola_id: 11, nome: "EMEF Sintética Alfa", codigo_inep: "35990001", status: "ativa", pendencia: null,
      tem_estimativa: false, por_edicao: [
        edicaoEscola(2025, FIEE25, { lp2: 148.3, mt2: 139.6, lp5: 187.2, mt5: 196.8, p2: 72.4, p5: 68.9, tps: 0,
                                     iee: 5.12, meta: 5.46, icm: 0 }),
        edicaoEscola(2024, FIEE24, { lp2: 148.3, mt2: 139.6, lp5: null, mt5: 196.8, p2: 72.4, p5: 68.9, tps: 1 })] },
  ];
  return {
    rede_id: 1, rede_nome: "Rede Sintética", codigo_ibge: "3599999", codigo_municipio_estadual: "901",
    municipio: "Cidade Sintetica",
    indicador: { chave: "saresp", nome: "SARESP", orgao: "SEDUC-SP", descricao: "" },
    pendencias: [],
    avisos: {
      escala: "O SARESP tem escala própria, da SEDUC-SP: as médias não se comparam com o Saeb nem com o ICA.",
      segundo_ano_x_ica: "O SARESP do 2º ano NÃO é comparável ao ICA, o indicador de alfabetização do INEP.",
      comparacao: "A comparação com o Estado é na MESMA rede: as redes municipais de São Paulo.",
      sem_ranking: "A tabela por escola está em ordem alfabética: não é ranking.",
      tps: "TPS = 0: a média da escola é instável.",
      estimativa: "Estas médias por escola NÃO são os números oficiais da SEDUC.",
    },
    etapas: [{ chave: "2_ano", rotulo: "2º ano" }, { chave: "5_ano", rotulo: "5º ano" }],
    componentes: [{ chave: "lp", rotulo: "Língua Portuguesa" }, { chave: "mt", rotulo: "Matemática" }],
    edicoes_rede: ANOS,
    territorios: [
      territorio("rede_municipal", "municipio", "municipal", "Cidade Sintetica — rede municipal", REDE, FMUN),
      territorio("estado_redes_municipais", "uf", "municipal", "Estado de São Paulo — redes municipais", ESTADO, FINST),
      territorio("rede_estadual_no_municipio", "municipio", "estadual",
                 "Cidade Sintetica — rede estadual no município", null, FMUN),
      territorio("estado_rede_estadual", "uf", "estadual", "Estado de São Paulo — rede estadual", null, FINST),
    ] as RespostaSARESP["territorios"],
    quebras_de_escala: [
      { etapa: "2_ano", de: 2022, para: 2023, motivo: "Possível quebra de escala no 2º ano entre 2022 e 2023." },
      { etapa: "2_ano", de: 2025, para: 2026, motivo: "A prova do 2º ano muda em 2026." },
    ],
    niveis: {
      rotulos: [{ nivel: "abaixo_do_basico", rotulo: "Abaixo do Básico" }, { nivel: "basico", rotulo: "Básico" },
                { nivel: "adequado", rotulo: "Adequado" }, { nivel: "avancado", rotulo: "Avançado" }],
      cortes: ANOS.flatMap((edicao) => ["2_ano", "5_ano"].flatMap((etapa) => ["lp", "mt"].map((componente) => ({
        edicao, etapa, componente, situacao: "a_confirmar", basico: null, adequado: null, avancado: null,
        fonte: "Pontos de corte não confirmados.",
      })))) as RespostaSARESP["niveis"]["cortes"],
      edicoes_a_confirmar: ANOS,
      aviso: "Os pontos de corte dos níveis do SARESP ainda não foram conferidos na fonte oficial.",
    },
    escolas: { edicoes: [2025, 2024], linhas: linhas as RespostaSARESP["escolas"]["linhas"] },
    estimativas: [
      { escola_id: 12, nome: "EMEF Sintética Beta", codigo_inep: "35990002", edicao: 2025, etapa: "5_ano",
        componente: "lp", valor: 200.1, casas_decimais: 1, unidade: "escala_saresp",
        fonte_texto: "SARESP 2025 — calculo_sintetico.csv", gravado_em: null },
    ],
    cobertura: [
      { edicao: 2025, total_escolas: 4, com_resultado: 2,
        sem_resultado: [{ escola_id: 13, nome: "EMEF Sintética Delta", codigo_inep: "35990004",
                          motivo: "fora_do_arquivo", tem_estimativa: false }],
        sem_inep: [{ escola_id: 14, nome: "ESCOLA SINTETICA GAMA", codigo_inep: null }],
        fora_do_cadastro: [{ codigo_inep: "35990003", cie: "990003", nome_no_arquivo: "ESCOLA SINTETICA GAMA" }],
        fonte: FIEE25 },
      { edicao: 2024, total_escolas: 4, com_resultado: 1,
        sem_resultado: [
          { escola_id: 12, nome: "EMEF Sintética Beta", codigo_inep: "35990002", motivo: "nao_divulgado",
            tem_estimativa: false },
          { escola_id: 13, nome: "EMEF Sintética Delta", codigo_inep: "35990004", motivo: "fora_do_arquivo",
            tem_estimativa: false }],
        sem_inep: [{ escola_id: 14, nome: "ESCOLA SINTETICA GAMA", codigo_inep: null }],
        fora_do_cadastro: [], fonte: FIEE24 },
    ],
    fontes: [FIEE25, FMUN, FINST, FIEE24],
    tem_dados: true,
    ...over,
  };
}

type LinhaEscola = RespostaSARESP["escolas"]["linhas"][number];
type EdicaoEscola = LinhaEscola["por_edicao"][number];

function linhaDe(dados: RespostaSARESP, nome: string): LinhaEscola {
  const linha = dados.escolas.linhas.find((l) => l.nome === nome);
  if (!linha) throw new Error(`fixture sem a escola ${nome}`);
  return linha;
}

const comoEdicao = (e: ReturnType<typeof edicaoEscola>) => e as unknown as EdicaoEscola;

/** A linha (tr) da escola numa tabela, pelo cabeçalho de linha. */
function linhaDaTabela(tabela: HTMLElement, nome: string): HTMLElement {
  const tr = within(tabela).getByRole("rowheader", { name: nome }).closest("tr");
  if (!tr) throw new Error(`sem linha para ${nome}`);
  return tr;
}

async function montar(dados: RespostaSARESP | (() => RespostaSARESP) = resposta()) {
  responder("GET", "/redes/1/indicadores/saresp", typeof dados === "function" ? dados() : dados);
  const r = renderComApp(<CartaoSARESP redeId={1} ehGlobal={false} />, { usuario: secretaria });
  await screen.findByTestId("cartao-saresp");
  return r;
}

/** Os trechos (polylines) de UMA série do gráfico, pela cor. */
function trechos(grafico: HTMLElement, cor: string): string[][] {
  return Array.from(grafico.querySelectorAll(`polyline[stroke="${cor}"]`))
    .map((p) => (p.getAttribute("points") ?? "").trim().split(/\s+/).filter(Boolean));
}

describe("Aba SARESP — rede municipal", () => {
  it("um gráfico por série/componente; o 2º ano NÃO liga 2022 a 2023 e o 5º ano liga", async () => {
    await montar();
    expect(await screen.findByRole("tab", { name: "Rede municipal" })).toHaveAttribute("aria-selected", "true");
    for (const id of ["2_ano-lp", "2_ano-mt", "5_ano-lp", "5_ano-mt"]) {
      expect(screen.getByTestId(`saresp-grafico-${id}`)).toBeInTheDocument();
    }
    const rede = "#6C5CE7";
    const estado = "#D97706";
    const lp2 = screen.getByTestId("saresp-grafico-2_ano-lp");
    // Município e Estado (mesma rede): 2022 fica SOLTO (um trecho de 1 ponto) e a linha
    // recomeça em 2023 — nenhum trecho junta os dois anos.
    for (const cor of [rede, estado]) {
      const t = trechos(lp2, cor);
      expect(t.map((x) => x.length)).toEqual([1, 3]);
    }
    expect(within(lp2).getByTestId("saresp-quebra")).toHaveTextContent(
      "Sem linha de 2022 para 2023: possível quebra de escala no 2º ano.");
    expect(lp2.querySelector("svg")).toHaveAttribute("aria-label",
      expect.stringContaining("Sem linha de 2022 para 2023 (possível quebra de escala)"));
    // 2º MT com 2024 sem resultado: lacuna (nem ponto, nem zero).
    expect(trechos(screen.getByTestId("saresp-grafico-2_ano-mt"), rede).map((x) => x.length)).toEqual([1, 1, 1]);
    // 5º ano: a série inteira ligada, sem aviso de quebra.
    const lp5 = screen.getByTestId("saresp-grafico-5_ano-lp");
    expect(trechos(lp5, rede).map((x) => x.length)).toEqual([4]);
    expect(within(lp5).queryByTestId("saresp-quebra")).toBeNull();
    // Legenda com o nome da rede de cada linha (a cor não é o único código).
    // (legenda do gráfico e linha da tabela equivalente)
    expect(within(lp5).getAllByText("Cidade Sintetica — rede municipal")).toHaveLength(2);
    expect(within(lp5).getAllByText("Estado de São Paulo — redes municipais")).toHaveLength(2);
  });

  it("a tabela marca os anos sem corte confirmado, diz 'sem resultado' (não 0) e tem selo de fonte", async () => {
    await montar();
    const tabela = await screen.findByRole("table", { name: /Médias do SARESP da rede municipal e do Estado/ });
    for (const ano of ANOS) {
      const th = within(tabela).getByRole("columnheader", { name: new RegExp(`^${ano}`) });
      expect(th.querySelector("abbr")).toHaveAttribute("title", "Pontos de corte dos níveis a confirmar nesta edição");
    }
    expect(screen.getByTestId("saresp-anos-a-confirmar")).toHaveTextContent("2022, 2023, 2024, 2025");
    expect(within(tabela).getByText("137,1")).toBeInTheDocument();
    expect(within(tabela).getByText("não divulgado no arquivo oficial")).toBeInTheDocument();
    expect(tabela.textContent).not.toMatch(/(^|\s)0(,0)?(\s|$)/);
    // Cada número leva a fonte (título e leitor de tela).
    expect(within(tabela).getByText("137,1").closest("[title]")).toHaveAttribute("title",
      "Fonte: SEDUC-SP — Proficiência do SARESP por município, SARESP 2025, arquivo de 12/01/2026 "
      + "(Proficiência do SARESP por Municipio de 2025_0.csv)");
    const selo = screen.getByTestId("saresp-selo-rede");
    expect(selo).toHaveTextContent("SARESP 2025, arquivo de 12/01/2026");
    expect(selo).toHaveTextContent("Proficiência do SARESP por instância, SARESP 2025, arquivo de 01/12/2025");
    expect(selo).toHaveTextContent("citação obrigatória");
  });

  it("níveis 'a confirmar' (sem corte inventado), aviso do 2º ano × ICA e a rede estadual à parte", async () => {
    await montar();
    const niveis = await screen.findByTestId("saresp-niveis");
    expect(within(niveis).getAllByText("a confirmar")).toHaveLength(16);       // 4 edições × 4
    expect(niveis.textContent).not.toMatch(/Básico \d|Adequado \d|Avançado \d/);
    expect(niveis).toHaveTextContent("Abaixo do Básico, Básico, Adequado, Avançado");
    const aviso = screen.getByTestId("saresp-aviso-2ano");
    expect(aviso).toHaveTextContent("Possível quebra de escala no 2º ano entre 2022 e 2023.");
    expect(aviso).toHaveTextContent("NÃO é comparável ao ICA");
    const outras = screen.getByTestId("saresp-outras-redes");
    expect(outras).toHaveTextContent("outra rede, só como contexto");
    expect(outras).toHaveTextContent("Cidade Sintetica — rede estadual no município: sem resultado");
    // O gráfico só tem a MESMA rede: a estadual não vira linha.
    expect(screen.getByTestId("saresp-grafico-5_ano-mt").textContent).not.toMatch(/rede estadual/);
  });

  it("com um corte CONFIRMADO (valores inventados): o corte com a fonte, o nível e a distância até o Adequado", async () => {
    const u = userEvent.setup();
    const dados = resposta();
    // Cortes INVENTADOS, fora de qualquer média dos arquivos da SEDUC (só o teste da tela).
    const confirmado = (c: { edicao: number; etapa: string; componente: string }) =>
      c.edicao === 2025 && c.etapa === "5_ano" && c.componente === "mt";
    dados.niveis.cortes = dados.niveis.cortes.map((c) => (confirmado(c)
      ? { ...c, situacao: "confirmado", basico: 139, adequado: 262, avancado: 304, fonte: "Fonte sintética de teste" }
      : c));
    // A média da rede (263,3) fica acima do Adequado: nível, sem distância.
    const serie = dados.territorios[0].series.find((s) => s.etapa === "5_ano" && s.componente === "mt");
    if (!serie) throw new Error("fixture sem a série");
    serie.numeros = serie.numeros.map((n) => (n.edicao === 2025
      ? { ...n, nivel: { situacao: "confirmado", nivel: "adequado", distancia_adequado: 0, calculo_do_constela: true } }
      : n));
    // A da ALFA (196,8) fica abaixo: nível e distância até o Adequado.
    const alfa = linhaDe(dados, "EMEF Sintética Alfa").por_edicao[0].proficiencia["5_ano"];
    if (!alfa.mt) throw new Error("fixture sem a média");
    alfa.mt = { ...alfa.mt, nivel: { situacao: "confirmado", nivel: "basico", distancia_adequado: 65.2,
                                     calculo_do_constela: true } };
    await montar(dados);
    const niveis = await screen.findByTestId("saresp-niveis");
    expect(within(niveis).getByRole("heading")).toHaveTextContent("Níveis de proficiência do SARESP — parte a confirmar");
    expect(niveis).toHaveTextContent("Básico 139 · Adequado 262 · Avançado 304");
    expect(within(niveis).getAllByText("a confirmar")).toHaveLength(15);
    expect(screen.getByTestId("saresp-niveis-fonte")).toHaveTextContent(
      "Fonte dos pontos de corte confirmados: Fonte sintética de teste.");
    const tabela = screen.getByRole("table", { name: /Médias do SARESP da rede municipal e do Estado/ });
    const nivelRede = within(tabela).getByText(/nível Adequado/);
    expect(nivelRede).toHaveTextContent("nível Adequado (cálculo do Constela)");
    expect(nivelRede).not.toHaveTextContent("pontos do Adequado");
    await u.click(screen.getByRole("tab", { name: "Por escola" }));
    const porEscola = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2025 por escola/ });
    expect(linhaDaTabela(porEscola, "EMEF Sintética Alfa")).toHaveTextContent(
      "nível Básico, a 65,2 pontos do Adequado (cálculo do Constela)");
  });

  it("sem nenhum corte a confirmar, o título dos níveis não diz 'a confirmar'", async () => {
    const dados = resposta();
    dados.niveis.cortes = dados.niveis.cortes.map((c) => ({
      ...c, situacao: "confirmado", basico: 139, adequado: 262, avancado: 304, fonte: "Fonte sintética de teste" }));
    dados.niveis.edicoes_a_confirmar = [];
    await montar(dados);
    const niveis = await screen.findByTestId("saresp-niveis");
    expect(within(niveis).getByRole("heading")).toHaveTextContent(/^Níveis de proficiência do SARESP$/);
    expect(within(niveis).queryByText("a confirmar")).toBeNull();
    expect(screen.queryByTestId("saresp-anos-a-confirmar")).toBeNull();
  });
});

describe("Aba SARESP — por escola e cobertura", () => {
  it("tabela oficial em ordem de NOME, sem ranking; sem INEP = pendência; sem resultado ≠ 0", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    const tabela = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2025 por escola/ });
    const nomes = within(tabela).getAllByRole("rowheader").map((th) => th.textContent);
    expect(nomes).toEqual(["EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta",
                           "ESCOLA SINTETICA GAMA"]);
    expect(screen.getByTestId("cartao-saresp").textContent).not.toMatch(/ranking:|melhor|pior|posição/i);
    const [alfa, beta, delta, gama] = within(tabela).getAllByRole("row").slice(1);
    expect(alfa).toHaveTextContent("148,3");
    expect(alfa).toHaveTextContent("72,4%");                         // Participação do 2º ano
    expect(alfa).toHaveTextContent("não atingiu");                   // TPS 0
    expect(alfa).toHaveTextContent("média instável");
    expect(alfa).toHaveTextContent("5,12");
    expect(beta).toHaveTextContent("não divulgado no arquivo oficial");   // 2º ano sem número
    expect(beta).toHaveTextContent("sim");                           // cumpriu a meta (ICM 1)
    expect(delta).toHaveTextContent("Sem resultado oficial: a escola não está no arquivo oficial importado");
    expect(gama).toHaveTextContent("sem código INEP");
    expect(gama).toHaveTextContent("Pendência de cadastro");
    expect(screen.getByTestId("saresp-selo-escolas")).toHaveTextContent(
      "SEDUC-SP — Índice de Excelência Educacional (IEE), SARESP 2025, arquivo de 12/01/2026");
  });

  it("a estimativa do Constela fica num bloco separado e rotulado, fora da tabela oficial", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    const oficial = screen.getByTestId("saresp-escolas");
    const estimativas = screen.getByTestId("saresp-estimativas");
    expect(oficial.contains(estimativas)).toBe(false);
    expect(estimativas).toHaveTextContent("Estimativas do Constela — não oficiais");
    expect(estimativas).toHaveTextContent("200,1 (estimativa)");
    expect(estimativas).toHaveTextContent("SARESP 2025 — calculo_sintetico.csv");
    expect(oficial.textContent).not.toContain("200,1");
  });

  it("trocar a edição mostra a do ano escolhido (com o selo daquele arquivo)", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    await u.selectOptions(screen.getByLabelText("Edição"), "2024");
    const tabela = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2024 por escola/ });
    const alfa = within(tabela).getAllByRole("row")[1];
    expect(within(alfa).getAllByText("não divulgado no arquivo oficial")).toHaveLength(1);   // 5º LP de 2024
    expect(alfa).toHaveTextContent("atingiu");
    expect(screen.getByTestId("saresp-selo-escolas")).toHaveTextContent(
      "SARESP 2024, arquivo de 01/12/2025 (Indice de Excelencia Educacional 2024-2025.csv)");
  });

  it("a frase da estimativa vale para a EDIÇÃO escolhida (e o motivo é o que a API manda)", async () => {
    const u = userEvent.setup();
    const dados = resposta();
    // BETA: fora do arquivo de 2024 e com estimativa só de 2025.
    const beta = linhaDe(dados, "EMEF Sintética Beta");
    beta.por_edicao[1] = comoEdicao(edicaoEscola(2024, FIEE24, null));
    // DELTA: fora do arquivo de 2025, com estimativa de 2025.
    const delta = linhaDe(dados, "EMEF Sintética Delta");
    delta.tem_estimativa = true;
    delta.por_edicao[0] = comoEdicao(edicaoEscola(2025, FIEE25, null, { tem_estimativa: true }));
    await montar(dados);
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    let tabela = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2025 por escola/ });
    expect(linhaDaTabela(tabela, "EMEF Sintética Delta")).toHaveTextContent(
      "Há uma estimativa do Constela desta edição (não oficial), no bloco abaixo.");
    await u.selectOptions(screen.getByLabelText("Edição"), "2024");
    tabela = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2024 por escola/ });
    const linhaBeta = linhaDaTabela(tabela, "EMEF Sintética Beta");
    expect(linhaBeta).toHaveTextContent(
      "Sem resultado oficial: a escola não está no arquivo oficial importado desta edição.");
    expect(linhaBeta).not.toHaveTextContent("estimativa");
  });

  it("código INEP cadastrado depois da importação: a linha e a cobertura pedem a reimportação", async () => {
    const u = userEvent.setup();
    const dados = resposta();
    linhaDe(dados, "EMEF Sintética Delta").por_edicao[0] = comoEdicao(
      edicaoEscola(2025, FIEE25, null, { motivo: "cadastrado_depois_da_importacao" }));
    dados.cobertura[0].sem_resultado[0].motivo = "cadastrado_depois_da_importacao";
    await montar(dados);
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    const tabela = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2025 por escola/ });
    const delta = linhaDaTabela(tabela, "EMEF Sintética Delta");
    expect(delta).toHaveTextContent(
      "Sem resultado oficial: o código INEP foi cadastrado depois da importação; reimporte o arquivo oficial desta edição.");
    expect(delta).not.toHaveTextContent("não está no arquivo");
    await u.click(screen.getByRole("tab", { name: "Cobertura" }));
    const c25 = screen.getByTestId("saresp-cobertura-2025");
    expect(c25).toHaveTextContent("EMEF Sintética Delta: o código INEP foi cadastrado depois da importação; reimporte");
    expect(c25).toHaveTextContent("cadastre o código (Gestão de redes) e reimporte o arquivo oficial desta edição");
    expect(c25).not.toHaveTextContent("cadastrar o código resolve");
  });

  it("D2 'não': a célula do 5º ano diz que o oficial não foi gravado — não 'sem resultado'", async () => {
    const u = userEvent.setup();
    const dados = resposta();
    const ed = linhaDe(dados, "EMEF Sintética Alfa").por_edicao[0];
    for (const c of ["lp", "mt"] as const) {
      ed.proficiencia["5_ano"][c] = { ...medida(2025, null, FIEE25), motivo_ausencia: "estimativa_mantida_d2" };
    }
    await montar(dados);
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    const tabela = screen.getByRole("table", { name: /Proficiência oficial do SARESP 2025 por escola/ });
    const alfa = linhaDaTabela(tabela, "EMEF Sintética Alfa");
    expect(within(alfa).getAllByText(
      "oficial não gravado: a estimativa do Constela foi mantida (decisão D2)")).toHaveLength(2);
    expect(within(alfa).queryByText("sem resultado")).toBeNull();
  });

  it("as estimativas ficam em ordem de NOME (sem acento e sem caixa), como a tabela oficial", async () => {
    const u = userEvent.setup();
    const est = (escola_id: number, nome: string) => ({
      escola_id, nome, codigo_inep: null, edicao: 2025, etapa: "5_ano" as const, componente: "lp",
      valor: 400, casas_decimais: 1, unidade: "escala_saresp", fonte_texto: "estimativa sintética", gravado_em: null,
    });
    await montar(resposta({ estimativas: [est(31, "EMEF Zélia Fictícia"), est(32, "emef bruno fictício"),
                                         est(33, "EMEF Álvaro Fictício")] }));
    await u.click(await screen.findByRole("tab", { name: "Por escola" }));
    const bloco = screen.getByTestId("saresp-estimativas");
    expect(within(bloco).getAllByRole("rowheader").map((th) => th.textContent)).toEqual(
      ["EMEF Álvaro Fictício", "emef bruno fictício", "EMEF Zélia Fictícia"]);
  });

  it("cobertura: N de M com resultado, motivo da ausência, pendência de INEP e fora do cadastro", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(await screen.findByRole("tab", { name: "Cobertura" }));
    const c25 = screen.getByTestId("saresp-cobertura-2025");
    expect(c25).toHaveTextContent("2 de 4 escolas da rede com resultado oficial");
    expect(c25).toHaveTextContent("EMEF Sintética Delta: a escola não está no arquivo oficial importado desta edição");
    expect(c25).toHaveTextContent("Sem código INEP no cadastro (1) — pendência de cadastro");
    expect(c25).toHaveTextContent("ESCOLA SINTETICA GAMA");
    expect(c25).toHaveTextContent("INEP 35990003 · CIE 990003");
    expect(c25).toHaveTextContent("nunca pelo nome");
    const c24 = screen.getByTestId("saresp-cobertura-2024");
    expect(c24).toHaveTextContent("EMEF Sintética Beta: não divulgado no arquivo oficial");
    expect(c24).toHaveTextContent("1 de 4 escolas");
  });
});

describe("Aba SARESP — sem dado e pendências", () => {
  it("sem nada importado: 'sem resultado importado', sem abas e sem número", async () => {
    const vazio = resposta({
      tem_dados: false, edicoes_rede: [], estimativas: [], cobertura: [], fontes: [],
      escolas: { edicoes: [], linhas: [] },
      territorios: resposta().territorios.map((t) => ({ ...t, tem_dados: false,
        series: t.series.map((s) => ({ ...s, numeros: [] })) })),
    });
    await montar(vazio);
    expect(await screen.findByTestId("saresp-sem-dado")).toHaveTextContent(
      "Sem resultado oficial do SARESP importado para a rede.");
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByTestId("cartao-saresp").textContent).not.toMatch(/\d+,\d/);
  });

  it("só a estimativa (sem oficial): ela aparece, separada, e a tabela oficial diz que não há", async () => {
    const u = userEvent.setup();
    const soEstimativa = resposta({
      tem_dados: false, edicoes_rede: [], cobertura: [], escolas: { edicoes: [], linhas: [] },
      territorios: [], pendencias: ["codigo_ibge", "codigo_municipio_estadual"],
    });
    await montar(soEstimativa);
    expect(await screen.findByTestId("saresp-pendencias")).toHaveTextContent("código IBGE");
    expect(screen.getByTestId("saresp-pendencias")).toHaveTextContent("CODMUN");
    expect(screen.getByTestId("saresp-pendencias")).toHaveTextContent("administrador global");
    await u.click(screen.getByRole("tab", { name: "Por escola" }));
    expect(screen.getByTestId("saresp-escolas-sem-resultado")).toBeInTheDocument();
    expect(screen.getByTestId("saresp-estimativas")).toHaveTextContent("200,1 (estimativa)");
  });
});

describe("SeloFonte — CSV da SEDUC", () => {
  it("diz a edição do SARESP e a data do arquivo; sem data, não inventa", () => {
    expect(textoFonte(FIEE25)).toBe("SEDUC-SP — Índice de Excelência Educacional (IEE), SARESP 2025, "
      + "arquivo de 12/01/2026 (Indice de Excelencia Educacional 2025-2026_0.csv)");
    const semData = fonte({ data_arquivo: null, data_arquivo_origem: null, last_modified_origem: null });
    expect(textoFonte(semData)).toBe("SEDUC-SP — Proficiência do SARESP por município, SARESP 2025, "
      + "data do arquivo não informada (Proficiência do SARESP por Municipio de 2025_0.csv)");
    render(<span>{textoFonte(FINST)}</span>);
    expect(screen.getByText(/instância, SARESP 2025, arquivo de 01\/12\/2025/)).toBeInTheDocument();
  });
});
