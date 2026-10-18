/**
 * ICA completo (etapa E3) na tela:
 *
 *  - `SeloFonte`: planilha × microdados ("microdados de dd/mm/aaaa", "detalhe dos
 *    microdados de dd/mm/aaaa"), sem inventar data (o Last-Modified só vale para os
 *    microdados, onde vem do servidor do INEP pelo pacote);
 *  - o cartão ganha a aba "Série, níveis e média de LP": linha com a meta tracejada
 *    e SP/Brasil na rede pública (rotulada: não é a rede do município) mais SP nas
 *    redes municipais, comparação em ordem fixa, níveis 0–8 em barra empilhada,
 *    média de LP × corte de 743, notas dos arquivos, selo em cada bloco;
 *  - as abas apontam para o painel (aria-controls / tabpanel);
 *  - "sem resultado" nunca vira 0; o ICA é da rede; sem ranking;
 *  - a importação aceita o pacote (.zip) e mostra o desfazer pelo id.
 *
 * Números, datas, arquivos e município SINTÉTICOS (os mesmos do teste do backend),
 * INVENTADOS — não são os oficiais com o inteiro trocado: nada dos arquivos do INEP
 * (licença CC BY-ND, repositório público — D13).
 */
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SeloFonte, { SeloNumero, diaDaFonte, textoDetalhe, textoFonte } from "../components/SeloFonte";
import CartaoICA, { type FonteICA, type RespostaICA } from "../pages/rede/CartaoICA";
import {
  renderComApp,
  responder,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const adminGlobal = usuarioFake({ nome: "Admin", cargo: "admin", is_global: true, escola_id: null });
const MUN = "Município Sintético";

function fonte(over: Partial<FonteICA> = {}): FonteICA {
  return {
    importacao_id: 3, fonte_nome: "INEP — Indicador Criança Alfabetizada",
    arquivo_nome: "resultados_e_metas_municipios_2025_3.xlsx", arquivo_data: "2026-07-15T10:00:00",
    last_modified_origem: null, url_origem: null, edicao_arquivo: 2025, versao_rotulo: null,
    importado_em: "2026-10-16T12:00:00", coletado_em: null, citacao: null,
    licenca: "Dado público do Inep (citar a fonte).", parser: "inep_ica_municipios", modo: "upload",
    notas: [], ...over,
  };
}
const FPLAN = fonte();
const FUF = fonte({ importacao_id: 4, arquivo_nome: "resultados_e_metas_ufs_2025_v2.xlsx",
  arquivo_data: "2026-07-29T11:20:00", parser: "inep_ica_ufs",
  notas: ["* Nota sintética de rodapé do arquivo de UFs."] });
const FMICRO = fonte({ importacao_id: 9, fonte_nome: "INEP — Microdados da avaliação da alfabetização",
  arquivo_nome: "microdados_sintetico_2025.zip", arquivo_data: "2026-03-10T10:00:00",
  last_modified_origem: "Tue, 10 Mar 2026 13:00:00 GMT", parser: "inep_aeeb_agregados", modo: "pacote_cli" });
const FMICRO24 = fonte({ ...FMICRO, importacao_id: 8, arquivo_nome: "microdados_sintetico_2024.zip",
  arquivo_data: "2025-06-17T09:00:00", edicao_arquivo: 2024 });

type N = Record<string, unknown>;
function num(edicao: number, valor: number | null, f: FonteICA, extra: N = {}) {
  return { edicao, valor, casas_decimais: valor == null ? null : 0, operador: null, unidade: "percentual",
           motivo_ausencia: null, fonte: f, detalhe: null, nivel: null, ...extra };
}
const dois = (edicao: number, valor: number | null, f: FonteICA, extra: N = {}) =>
  num(edicao, valor, f, { casas_decimais: valor == null ? null : 2, ...extra });
const NIV25 = [7.34, 9.72, 13.22, 16.06, 20.76, 15.76, 11.2, 5.05, 0.89];
const NIV24 = [9.04, 10.42, 14.87, 16.93, 19.46, 13.62, 9.45, 4.22, 1.99];
const NIVUF = [7.04, 8.76, 12.62, 18, 19.91, 16.58, 10.92, 4.45, 1.72];
function distribuicao(edicao: number, valores: number[], f: FonteICA) {
  return { edicao, soma: 100,
           niveis: valores.map((v, k) => dois(edicao, v, f, { nivel: String(k) })) };
}

function territorio(abrangencia: "municipio" | "uf" | "brasil", nome: string, rede: string,
                    resultados: ReturnType<typeof num>[], extra: N = {}) {
  const ultimo = [...resultados].reverse().find((r) => r.valor != null);
  const metas = (extra.metas as ReturnType<typeof num>[]) ?? [];
  return {
    abrangencia, codigo_territorio: abrangencia === "municipio" ? "3599999" : abrangencia === "uf" ? "35" : "BR",
    nome, rede_ensino: rede, resultados, metas, nivel: [], participacao: [], comparacoes: [],
    media_lp: [], distribuicao_niveis: [],
    destaque: ultimo ? { resultado: ultimo, meta: metas.find((m) => m.edicao === ultimo.edicao) ?? null, comparacao: null } : null,
    tem_dados: resultados.length > 0, ...extra,
  };
}

function resposta(comMicrodados = true): RespostaICA {
  const metas = [25, 32, 34, 35, 36, 37, 80].map((v, i) => num(2024 + i, v, FPLAN));
  const mun = territorio("municipio", MUN, "municipal", [
    num(2023, 26, FPLAN),
    num(2024, 22, FPLAN),
    num(2025, 30, FPLAN, comMicrodados ? { detalhe: { valor: 30.2, casas_decimais: 2, fonte: FMICRO } } : {}),
  ], {
    metas,
    participacao: [num(2025, 73, FPLAN)],
    nivel: [num(2025, 1, FPLAN, { unidade: "nivel" })],
    ...(comMicrodados ? {
      media_lp: [dois(2024, 721.27, FMICRO24, { unidade: "escala_alfabetizacao" }),
                 dois(2025, 726.48, FMICRO, { unidade: "escala_alfabetizacao" })],
      distribuicao_niveis: [distribuicao(2024, NIV24, FMICRO24), distribuicao(2025, NIV25, FMICRO)],
    } : {}),
  });
  const uf = territorio("uf", "São Paulo", "publica", [num(2023, 18, FUF), num(2024, 26, FUF),
    num(2025, 34, FUF, comMicrodados ? { detalhe: { valor: 33.5, casas_decimais: 2, fonte: FMICRO } } : {})]);
  const br = territorio("brasil", "Brasil", "publica", [num(2023, 27, FUF), num(2024, 26, FUF), num(2025, 23, FUF)]);
  const ufm = territorio("uf", "São Paulo", "municipal", comMicrodados
    ? [dois(2024, 30.84, FMICRO24), dois(2025, 31.57, FMICRO)] : [], comMicrodados ? {
      media_lp: [dois(2025, 728.91, FMICRO, { unidade: "escala_alfabetizacao" })],
      distribuicao_niveis: [distribuicao(2025, NIVUF, FMICRO)],
    } : {});
  return {
    rede_id: 1, rede_nome: "Rede Sintética", codigo_ibge: "3599999",
    indicador: { chave: "ica", nome: "Indicador Criança Alfabetizada (ICA)", orgao: "INEP", descricao: "" },
    aviso_rede: "O ICA é o indicador da REDE municipal: o INEP não publica o ICA por escola. Ele não serve para comparar nem ordenar escolas.",
    pendencia: null, corte_alfabetizado: 743,
    legenda_nivel: [{ nivel: 1, rotulo: "Nível 1", faixa: "entre 40% e 50%" }],
    territorios: [mun, uf, br] as RespostaICA["territorios"],
    uf_municipal: ufm as RespostaICA["uf_municipal"],
    fontes: comMicrodados ? [FUF, FPLAN, FMICRO, FMICRO24] : [FUF, FPLAN], tem_dados: true,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("SeloFonte", () => {
  it("planilha diz 'arquivo de'; microdados dizem 'microdados de' e, no detalhe, 'detalhe dos microdados de'", () => {
    expect(textoFonte(FPLAN)).toBe(
      "INEP — Indicador Criança Alfabetizada, arquivo de 15/07/2026 (resultados_e_metas_municipios_2025_3.xlsx)");
    expect(textoFonte(FMICRO)).toBe(
      "INEP — Microdados da avaliação da alfabetização, microdados de 10/03/2026 (microdados_sintetico_2025.zip)");
    expect(textoDetalhe(FMICRO)).toBe("detalhe dos microdados de 10/03/2026");
    expect(textoDetalhe(FPLAN)).toBe("no arquivo de 15/07/2026");
  });

  it("não inventa data: sem data interna, o Last-Modified só vale nos microdados", () => {
    expect(diaDaFonte({ ...FMICRO, arquivo_data: null })).toBe("10/03/2026");
    expect(diaDaFonte({ ...FPLAN, arquivo_data: null, last_modified_origem: "Tue, 10 Mar 2026 13:00:00 GMT" })).toBeNull();
    expect(textoFonte({ ...FPLAN, arquivo_data: null })).toBe(
      "INEP — Indicador Criança Alfabetizada, arquivo (resultados_e_metas_municipios_2025_3.xlsx)");
    expect(textoFonte({ ...FMICRO, arquivo_data: null, last_modified_origem: null })).toContain("microdados sem data");
  });

  it("bloco sem repetir arquivo, com licença; número com a data curta e o texto completo", () => {
    const { container } = render(<SeloFonte fontes={[FMICRO, null, FMICRO, FPLAN]} titulo="Fontes" />);
    expect(container.querySelectorAll("p")).toHaveLength(4);   // título + 2 fontes + licença
    expect(container).toHaveTextContent("Fonte: INEP — Microdados da avaliação da alfabetização, microdados de 10/03/2026");
    expect(container).toHaveTextContent("Dado público do Inep (citar a fonte).");
    const { container: vazio } = render(<SeloFonte fontes={[null]} />);
    expect(vazio.innerHTML).toBe("");
    const { container: n } = render(<SeloNumero fonte={FMICRO} />);
    expect(n.querySelector("span")?.getAttribute("title")).toContain("microdados_sintetico_2025.zip");
    expect(n).toHaveTextContent("microdados de 10/03/2026");
    const { container: d } = render(<SeloNumero fonte={FMICRO} detalhe />);
    expect(d).toHaveTextContent("detalhe dos microdados de 10/03/2026");
  });
});

describe("Cartão do ICA — aba 'Série, níveis e média de LP'", () => {
  it("no resumo, as casas dos microdados aparecem como detalhe datado", async () => {
    responder("GET", "/redes/1/indicadores/ica", resposta());
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    const serie = await screen.findByRole("table", { name: /resultado e meta por ano/ });
    expect(within(serie).getAllByRole("row")[3]).toHaveTextContent(
      "30%30,20 — detalhe dos microdados de 10/03/2026");
    expect(screen.getByTestId("ica-selo")).toHaveTextContent(
      "microdados de 10/03/2026 (microdados_sintetico_2025.zip)");
    const resumo = screen.getByRole("tab", { name: "Resumo" });
    expect(resumo).toHaveAttribute("aria-selected", "true");
    // a aba aponta para o painel, e o painel é rotulado pela aba ativa
    const painel = screen.getByRole("tabpanel", { name: "Resumo" });
    expect(resumo).toHaveAttribute("aria-controls", painel.id);
    expect(screen.getByRole("tab", { name: "Série, níveis e média de LP" }))
      .toHaveAttribute("aria-controls", painel.id);
    expect(within(painel).getByTestId("ica-capa")).toBeInTheDocument();
  });

  it("série com a meta tracejada, SP/Brasil na rede pública (rotulada) e SP nas redes municipais, comparação em ordem fixa, níveis, média e notas", async () => {
    responder("GET", "/redes/1/indicadores/ica", resposta());
    const usuario = userEvent.setup();
    const { container } = renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    await usuario.click(await screen.findByRole("tab", { name: "Série, níveis e média de LP" }));
    const aba = screen.getByTestId("aba-ica");
    expect(screen.getByRole("tabpanel", { name: "Série, níveis e média de LP" })).toContainElement(aba);

    // a rede pública NÃO é a do município: o aviso e o texto alternativo dizem a
    // rede de cada comparação (nunca "a mesma rede" para SP/Brasil na pública)
    const aviso = screen.getByTestId("ica-aviso-redes");
    expect(aviso).toHaveTextContent(
      "SP e Brasil aparecem na rede pública (estadual e municipal), que é como o INEP divulga o ICA — essa não "
      + "é a mesma rede do município. A comparação na mesma rede é “São Paulo (redes municipais)”, que vem dos microdados.");
    expect(aviso.textContent).not.toMatch(/sempre com a mesma rede/);

    // linha: município, meta (tracejada), SP pública, SP municipais, Brasil
    const grafico = within(aba).getByRole("img", {
      name: `ICA de ${MUN} (rede municipal) por ano, com a meta tracejada e as comparações: São Paulo (rede pública), `
        + "São Paulo (redes municipais), Brasil (rede pública)" });
    expect(grafico.getAttribute("aria-label")).not.toMatch(/mesma rede/);
    const legenda = aba.textContent ?? "";
    for (const nome of [`${MUN} (rede municipal)`, `Meta de ${MUN} (tracejada)`, "São Paulo (rede pública)",
                        "São Paulo (redes municipais) — microdados", "Brasil (rede pública)"]) {
      expect(legenda).toContain(nome);
    }
    expect(aba.querySelector('polyline[stroke-dasharray="6 4"]')).not.toBeNull();
    expect(within(aba).getByText(/O eixo vertical vai de 10% a 90% \(não começa em 0\)/)).toBeInTheDocument();
    const numeros = within(aba).getByRole("table", { name: "Números do gráfico: ICA e meta por ano" });
    expect(numeros).toHaveTextContent("São Paulo (redes municipais) — microdados—30,84%31,57%");

    // comparação de 2025 em ORDEM FIXA (não por valor): 30, 34, 31,57, 23
    const comparacao = within(aba).getByRole("list", { name: /ICA em 2025, na ordem fixa/ });
    expect(within(comparacao).getAllByRole("listitem").map((li) => li.textContent?.split("%")[0])).toEqual([
      `${MUN} (rede municipal)30`, "São Paulo (rede pública)34", "São Paulo (redes municipais)31,57",
      "Brasil (rede pública)23"]);

    // níveis 0–8 em barra empilhada: município 2024 e 2025, SP redes municipais 2025
    const niveis = within(aba).getByRole("group", { name: /Percentual de alunos em cada nível/ });
    expect(within(niveis).getAllByRole("img").map((i) => i.getAttribute("aria-label")?.split(" — ")[0] +
      " — " + i.getAttribute("aria-label")?.split(" — ")[1])).toEqual([
      `${MUN} (rede municipal) — 2024`, `${MUN} (rede municipal) — 2025`, "São Paulo (redes municipais) — 2025"]);
    expect(within(niveis).getByRole("table")).toHaveTextContent("Nível 0");
    // os níveis com as 2 casas publicadas (11,20 continua 11,20; 18,00 continua 18,00)
    expect(within(niveis).getByRole("table")).toHaveTextContent(`${MUN} (rede municipal) — 20257,34%9,72%`);
    expect(within(niveis).getAllByRole("img")[1].getAttribute("aria-label")).toContain("Nível 6: 11,20%");
    expect(within(niveis).getAllByRole("img")[2].getAttribute("aria-label")).toContain("Nível 3: 18,00%");
    expect(screen.getByTestId("ica-variacao")).toHaveTextContent(
      `De 2024 para 2025, o ICA de ${MUN} foi de 22% para 30%, e o percentual de alunos no nível 0 foi de 9,04% para 7,34%. Os números descrevem a variação; não indicam a causa dela.`);
    expect(screen.getByTestId("selo-niveis")).toHaveTextContent("microdados de 10/03/2026");
    expect(screen.getByTestId("selo-niveis")).toHaveTextContent("microdados de 17/06/2025");

    // média de LP × corte de 743, com a data de cada número
    const medias = within(aba).getByRole("table", { name: /Média de Língua Portuguesa/ });
    const filas = within(medias).getAllByRole("row").slice(1);
    // cada número com o selo dele (data curta visível; o arquivo, para leitor de tela e no título)
    expect(filas[0]).toHaveTextContent(`${MUN} (rede municipal)721,27microdados de 17/06/2025 — fonte: `
      + "INEP — Microdados da avaliação da alfabetização, microdados de 17/06/2025 (microdados_sintetico_2024.zip)"
      + "726,48microdados de 10/03/2026");
    expect(within(filas[0]).getAllByTitle(/^Fonte: /)).toHaveLength(2);
    expect(filas[1]).toHaveTextContent("São Paulo (redes municipais)—728,91");
    expect(filas[2]).toHaveTextContent("São Paulo (rede pública)——");   // a pública não tem média importada
    expect(screen.getByTestId("ica-corte")).toHaveTextContent(
      `Corte do ICA: 743 pontos na escala do Saeb — é alfabetizado o aluno com 743 ou mais. A média de ${MUN} em 2025 (726,48) está 16,52 ponto(s) abaixo do corte.`);

    // participação, nível oficial e as notas do próprio arquivo
    expect(aba).toHaveTextContent("Participação em 2025: 73%");
    expect(aba).toHaveTextContent("Nível oficial do município em 2025: 1 (entre 40% e 50% de alfabetizados)");
    expect(screen.getByTestId("ica-notas")).toHaveTextContent(
      "* Nota sintética de rodapé do arquivo de UFs. (resultados_e_metas_ufs_2025_v2.xlsx)");
    // a rede, sempre; nada de 0% inventado
    expect(container.textContent).toMatch(/o INEP não publica o ICA por escola/);
    expect(aba.textContent).not.toMatch(/(^|[^\d,])0%/);
  });

  it("sem os microdados: a aba diz o que falta (não mostra 0) e a série ainda aparece", async () => {
    responder("GET", "/redes/1/indicadores/ica", resposta(false));
    const usuario = userEvent.setup();
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    await usuario.click(await screen.findByRole("tab", { name: "Série, níveis e média de LP" }));
    const aba = screen.getByTestId("aba-ica");
    expect(aba).toHaveTextContent("Sem distribuição por nível importada");
    expect(aba).toHaveTextContent("Sem média de LP importada");
    expect(aba.textContent).not.toContain("redes municipais) — microdados");
    expect(within(aba).getByRole("img", { name: /ICA de Município Sintético \(rede municipal\) por ano/ }))
      .toBeInTheDocument();
  });

  it("detalhe sem data nem fonte não deixa travessão solto: o nome do arquivo, ou só o número", async () => {
    const dados = resposta();
    const [mun, uf] = dados.territorios;
    mun.resultados[2] = { ...mun.resultados[2],
      detalhe: { valor: 30.2, casas_decimais: 2, fonte: { ...FPLAN, arquivo_data: null } } };
    uf.resultados[2] = { ...uf.resultados[2], detalhe: { valor: 33.5, casas_decimais: 2, fonte: null } };
    responder("GET", "/redes/1/indicadores/ica", dados);
    const usuario = userEvent.setup();
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    await usuario.click(await screen.findByRole("tab", { name: "Série, níveis e média de LP" }));
    const itens = within(screen.getByRole("list", { name: /ICA em 2025, na ordem fixa/ })).getAllByRole("listitem");
    expect(itens[0]).toHaveTextContent("30,20% — no arquivo resultados_e_metas_municipios_2025_3.xlsx");
    expect(itens[1].textContent).toMatch(/33,50%$/);
    expect(itens[1].textContent).not.toMatch(/—\s*$/);
  });

  it("sem dado nenhum: sem abas, só 'sem resultado importado'", async () => {
    const vazia = resposta(false);
    vazia.territorios = vazia.territorios.map((t) => ({ ...t, resultados: [], metas: [], destaque: null, tem_dados: false }));
    vazia.tem_dados = false;
    vazia.fontes = [];
    responder("GET", "/redes/1/indicadores/ica", vazia);
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    expect(await screen.findByText(/Sem resultado importado do ICA/)).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});

describe("Importação do ICA — pacote dos microdados e desfazer pelo id", () => {
  it("prévia do pacote mostra nível, média e SP nas redes municipais; a lista diz qual desfazer antes", async () => {
    responder("GET", "/redes/1/indicadores/ica", resposta());
    responder("GET", "/redes/1/indicadores/importacoes", [
      { id: 9, status: "aplicada", arquivo_nome: "microdados_sintetico_2025.zip", modo: "pacote_cli", edicao_arquivo: 2025,
        arquivo_data: "2026-03-10T10:00:00", contadores: {}, avisos: [], created_at: "2026-10-16T10:00:00",
        aplicado_em: "2026-10-16T10:01:00", pode_desfazer: true, bloqueada_por: null },
      { id: 3, status: "aplicada", arquivo_nome: "resultados_e_metas_municipios_2025_3.xlsx", modo: "upload",
        edicao_arquivo: 2025, arquivo_data: null, contadores: {}, avisos: [], created_at: "2026-10-16T09:00:00",
        aplicado_em: "2026-10-16T09:01:00", pode_desfazer: false, bloqueada_por: 9 },
    ]);
    responder("UPLOAD", "/redes/1/indicadores/ica/previa", {
      id: 11, status: "previa", arquivo_nome: "microdados_sintetico_2025.zip", modo: "pacote_cli", edicao_arquivo: 2025,
      arquivo_data: "2026-03-10T10:00:00", created_at: null, aplicado_em: null,
      contadores: { novas: 2, alteradas: 1, iguais: 0 }, avisos: [],
      mudancas: [
        { tipo: "alterada", territorio: MUN, rede_ensino: "municipal", indicador: "percentual_alfabetizado", nivel: null,
          edicao: 2025, antes: 30, antes_detalhe: null, antes_motivo: null, antes_casas: 0, depois: 30,
          depois_detalhe: 30.2, depois_casas: 0, depois_casas_detalhe: 2, depois_motivo: null },
        { tipo: "nova", territorio: MUN, rede_ensino: "municipal", indicador: "pct_nivel", nivel: "0", edicao: 2025,
          antes: null, antes_detalhe: null, antes_motivo: null, depois: 7.34, depois_detalhe: null, depois_casas: 2,
          depois_motivo: null },
        { tipo: "nova", territorio: "UF 35 (redes municipais)", rede_ensino: "municipal", indicador: "media_lp",
          nivel: null, edicao: 2025, antes: null, antes_detalhe: null, antes_motivo: null, depois: 728.91,
          depois_detalhe: null, depois_casas: 2, depois_motivo: null },
      ],
    });
    const usuario = userEvent.setup();
    const { container } = renderComApp(<CartaoICA redeId={1} ehGlobal />, { usuario: adminGlobal });
    const entrada = await screen.findByLabelText("Planilha oficial do ICA");
    expect(entrada).toHaveAttribute("accept", ".xlsx,.zip");
    expect(container.textContent).toContain("python -m app.services.indicadores.preparar");

    // a lista: o pacote pode ser desfeito; a planilha anterior diz qual desfazer antes
    const lista = await screen.findByRole("table", { name: "Importações do ICA desta rede" });
    const filas = within(lista).getAllByRole("row").slice(1);
    expect(filas[0]).toHaveTextContent("#9 · microdados_sintetico_2025.zip (pacote dos microdados)");
    expect(within(filas[0]).getByRole("button", { name: /Desfazer/ })).toBeInTheDocument();
    expect(filas[1]).toHaveTextContent("para desfazer, desfaça antes a #9");
    expect(within(filas[1]).queryByRole("button")).not.toBeInTheDocument();

    await usuario.upload(entrada, new File(["zip"], "pacote_ica_aeeb_2025_3599999.zip"));
    const previa = await screen.findByTestId("ica-previa");
    expect(previa).toHaveTextContent("(avaliação 2025, arquivo de 10/03/2026) — nada foi gravado");
    const linhas = within(previa).getAllByRole("row").slice(1);
    expect(linhas[0]).toHaveTextContent(`${MUN}resultado 20253030 (30,20)`);
    expect(linhas[1]).toHaveTextContent(`${MUN}nível 0 2025—7,34`);
    expect(linhas[2]).toHaveTextContent("UF 35 (redes municipais)média de LP 2025—728,91");
  });
});
