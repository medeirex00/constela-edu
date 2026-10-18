/**
 * Cartão do ICA oficial (etapa E2) — o que a Secretaria e o admin global precisam ver:
 *
 *  - a capa na mesma precisão: "30% (2025) × meta 32% (−2 p.p.)", com "não atingiu";
 *  - a série 2023–2030 (resultado × meta) e as casas decimais de outro arquivo como
 *    DETALHE, com a data do arquivo de origem e a precisão publicada (21,90, não 21,9);
 *  - SP e Brasil (rede pública) em ordem fixa, nunca ordenados por valor, e a meta
 *    de cada território com o ano dela;
 *  - SEMPRE o selo de fonte ("INEP — Indicador Criança Alfabetizada, arquivo de …") e
 *    o aviso de que é o indicador da REDE (não existe por escola);
 *  - sem dado: "sem resultado importado" — nunca 0%; importado sem resultado oficial:
 *    "o INEP não divulgou", com o motivo;
 *  - só o admin global importa (prévia → aplicar → desfazer), vendo a rede que recebe.
 *
 * Números, datas e município da resposta simulada são SINTÉTICOS (os mesmos do teste
 * do backend): o repositório é público e os arquivos do INEP têm licença CC BY-ND —
 * nada deles é copiado nem recortado aqui (D13).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import CartaoICA, { type FonteICA, type RespostaICA } from "../pages/rede/CartaoICA";
import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import {
  api,
  apiUpload,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  waitFor,
  within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const adminGlobal = usuarioFake({ nome: "Admin", cargo: "admin", is_global: true, escola_id: null });

const MUNICIPIO = "Município Sintético";

function fonte(over: Partial<FonteICA> = {}): FonteICA {
  return {
    importacao_id: 3, fonte_nome: "INEP — Indicador Criança Alfabetizada",
    arquivo_nome: "resultados_e_metas_municipios_2025_3.xlsx", arquivo_data: "2026-07-15T10:00:00",
    last_modified_origem: null, url_origem: null, edicao_arquivo: 2025, versao_rotulo: "municipios_2025_3",
    importado_em: "2026-10-16T12:00:00", coletado_em: null,
    citacao: "Fonte: Inep — Indicador Criança Alfabetizada.",
    licenca: "Dado público do Inep (citar a fonte).", ...over,
  };
}
const F2025 = fonte();
const F2024 = fonte({ importacao_id: 2, arquivo_nome: "resultados_e_metas_municipios_2024.xlsx",
  arquivo_data: "2025-12-03T09:30:00", edicao_arquivo: 2024 });
const F2023 = fonte({ importacao_id: 1, arquivo_nome: "resultados_e_metas_municipios.xlsx",
  arquivo_data: "2024-04-22T14:05:00", edicao_arquivo: 2023 });
const FUF = fonte({ importacao_id: 4, arquivo_nome: "resultados_e_metas_ufs_2025_v2.xlsx",
  arquivo_data: "2026-07-29T11:20:00" });

function num(edicao: number, valor: number | null, f: FonteICA, extra: Record<string, unknown> = {}) {
  return { edicao, valor, casas_decimais: valor == null ? null : 0, operador: null,
           unidade: "percentual", motivo_ausencia: null, fonte: f, detalhe: null, ...extra };
}
const det = (valor: number, f: FonteICA) => ({ valor, casas_decimais: 2, fonte: f });

function comp(edicao: number, resultado: number, meta: number, dif: number,
              situacao: "atingiu" | "nao_atingiu" | "inconclusivo", difDet: number | null = null) {
  return { edicao, resultado, meta, operador: null, diferenca_pp: dif, casas_decimais: 0,
           diferenca_pp_detalhe: difDet, casas_decimais_detalhe: difDet == null ? null : 2, situacao };
}

function territorio(abrangencia: "municipio" | "uf" | "brasil", nome: string, resultados: ReturnType<typeof num>[],
                    metas: ReturnType<typeof num>[], comparacoes: ReturnType<typeof comp>[], extra = {}) {
  const ultimo = [...resultados].reverse().find((r) => r.valor != null);
  return {
    abrangencia, codigo_territorio: abrangencia === "municipio" ? "3599999" : abrangencia === "uf" ? "35" : "BR",
    nome, rede_ensino: abrangencia === "municipio" ? "municipal" : "publica",
    resultados, metas, nivel: [], participacao: [], comparacoes,
    destaque: ultimo ? { resultado: ultimo, meta: metas.find((m) => m.edicao === ultimo.edicao) ?? null,
                         comparacao: comparacoes.find((c) => c.edicao === ultimo.edicao) ?? null } : null,
    tem_dados: resultados.length + metas.length > 0, ...extra,
  };
}

const LEGENDA = [
  { nivel: 0, rotulo: "Abaixo do nível 1", faixa: "até 40%" },
  { nivel: 1, rotulo: "Nível 1", faixa: "entre 40% e 50%" },
];

function municipio(over: { detalhe2024?: ReturnType<typeof det> } = {}) {
  const metasMun = [25, 32, 34, 35, 36, 37, 80].map((v, i) => num(2024 + i, v, F2025));
  metasMun[0].detalhe = det(25.36, F2024);
  metasMun[1].detalhe = det(31.93, F2024);
  return territorio("municipio", MUNICIPIO, [
    num(2023, 26, F2025, { detalhe: det(26.18, F2023) }),
    num(2024, 22, F2025, { detalhe: over.detalhe2024 ?? det(21.84, F2024) }),
    num(2025, 30, F2025),
  ], metasMun, [comp(2024, 22, 25, -3, "nao_atingiu", -3.52), comp(2025, 30, 32, -2, "nao_atingiu")], {
    nivel: [num(2025, 1, F2025, { unidade: "nivel" })],
    participacao: [num(2025, 73, F2025)],
  });
}

function respostaComDado(territorios?: RespostaICA["territorios"]): RespostaICA {
  const uf = territorio("uf", "São Paulo", [num(2023, 18, FUF), num(2024, 26, FUF), num(2025, 34, FUF)],
    [num(2025, 33, FUF)], [comp(2025, 34, 33, 1, "atingiu")]);
  const br = territorio("brasil", "Brasil", [num(2023, 27, FUF), num(2024, 26, FUF), num(2025, 23, FUF)],
    [num(2025, 23, FUF), num(2030, 80, FUF, { operador: ">" })], [comp(2025, 23, 23, 0, "inconclusivo")]);
  return {
    rede_id: 1, rede_nome: "Rede Sintética", codigo_ibge: "3599999",
    indicador: { chave: "ica", nome: "Indicador Criança Alfabetizada (ICA)", orgao: "INEP", descricao: "" },
    aviso_rede: "O ICA é o indicador da REDE municipal: o INEP não publica o ICA por escola. Ele não serve para comparar nem ordenar escolas.",
    pendencia: null, legenda_nivel: LEGENDA,
    territorios: territorios ?? ([municipio(), uf, br] as RespostaICA["territorios"]),
    fontes: [FUF, F2025, F2024, F2023], tem_dados: true,
  };
}

function respostaSemDado(over: Partial<RespostaICA> = {}): RespostaICA {
  const vazio = (a: "municipio" | "uf" | "brasil", nome: string) => territorio(a, nome, [], [], []);
  return {
    ...respostaComDado(),
    territorios: [vazio("municipio", "Rede Sintética"), vazio("uf", "UF 35"), vazio("brasil", "Brasil")] as RespostaICA["territorios"],
    fontes: [], tem_dados: false, ...over,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("Cartão do ICA oficial", () => {
  it("mostra a capa na mesma precisão, a série com o detalhe datado, SP e Brasil e o selo de fonte", async () => {
    responder("GET", "/redes/1/indicadores/ica", respostaComDado());
    const { container } = renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });

    const capa = await screen.findByTestId("ica-capa");
    expect(capa).toHaveTextContent("30% (2025) × meta 32% (−2 p.p.)");
    expect(screen.getAllByText("não atingiu a meta").length).toBeGreaterThan(0);
    expect(screen.getByText(/Nível oficial 1 \(2025\) — entre 40% e 50%/)).toBeInTheDocument();
    expect(screen.getByText("Participação 73% (2025)")).toBeInTheDocument();
    // o aviso da REDE aparece sempre
    expect(container.textContent).toMatch(/indicador da REDE municipal: o INEP não publica o ICA por escola/);

    // série 2023–2030: resultado, meta e o detalhe com a data do arquivo de origem
    const serie = screen.getByRole("table", { name: /resultado e meta por ano/ });
    const linhas = within(serie).getAllByRole("row").slice(1);
    expect(linhas.map((l) => l.firstElementChild?.textContent)).toEqual(
      ["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"]);
    expect(linhas[0]).toHaveTextContent("26%26,18 no arquivo de 22/04/2024");
    expect(linhas[1]).toHaveTextContent("21,84 no arquivo de 03/12/2025");
    expect(linhas[1]).toHaveTextContent("−3 p.p.−3,52 p.p. no detalhe");
    expect(linhas[2]).toHaveTextContent("30%32%31,93 no arquivo de 03/12/2025−2 p.p.");
    expect(linhas[7]).toHaveTextContent("2030—80%—");          // sem resultado ainda: "—", não 0

    // comparação em ordem FIXA: município, SP, Brasil (não por valor), meta com o ano
    const comparacao = screen.getByRole("table", { name: /município, do estado e do Brasil/ });
    const filas = within(comparacao).getAllByRole("row").slice(1);
    expect(filas.map((l) => l.firstElementChild?.textContent)).toEqual(
      [`${MUNICIPIO} (rede municipal)`, "São Paulo (rede pública)", "Brasil (rede pública)"]);
    expect(filas[0]).toHaveTextContent("32% (2025)");
    expect(filas[1]).toHaveTextContent("33% (2025)");
    expect(within(comparacao).getByText("empate na precisão divulgada — a confirmar")).toBeInTheDocument();
    expect(within(comparacao).getByText("atingiu a meta")).toBeInTheDocument();

    const selo = screen.getByTestId("ica-selo");
    expect(selo).toHaveTextContent(
      "Fonte: INEP — Indicador Criança Alfabetizada, arquivo de 15/07/2026 (resultados_e_metas_municipios_2025_3.xlsx)");
    expect(selo).toHaveTextContent("arquivo de 29/07/2026 (resultados_e_metas_ufs_2025_v2.xlsx)");

    // Secretaria só lê: nada de importação
    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByText(/Importar o ICA oficial/)).not.toBeInTheDocument();
  });

  it("sem dado: 'sem resultado importado', nunca 0%", async () => {
    responder("GET", "/redes/1/indicadores/ica", respostaSemDado());
    const { container } = renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });

    expect(await screen.findByText(/Sem resultado importado do ICA/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\b0%|0 p\.p\./);
    expect(screen.queryByTestId("ica-selo")).not.toBeInTheDocument();
    expect(container.textContent).toMatch(/o INEP não publica o ICA por escola/);
  });

  it("importado sem resultado oficial: diz que o INEP não divulgou, com o motivo (não 'nada importado')", async () => {
    const semResultado = territorio("municipio", MUNICIPIO, [
      num(2023, null, F2025, { motivo_ausencia: "nao_divulgado" }),
      num(2024, null, F2025, { motivo_ausencia: "nao_divulgado" }),
      num(2025, null, F2025, { motivo_ausencia: "participacao_baixa" }),
    ], [num(2025, null, F2025, { motivo_ausencia: "sem_meta" })], []);
    const vazio = (a: "uf" | "brasil", nome: string) => territorio(a, nome, [], [], []);
    responder("GET", "/redes/1/indicadores/ica", {
      ...respostaComDado([semResultado, vazio("uf", "UF 35"), vazio("brasil", "Brasil")] as RespostaICA["territorios"]),
      fontes: [F2025],
    });
    const { container } = renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });

    expect(await screen.findByTestId("ica-sem-resultado")).toHaveTextContent(
      `O INEP não divulgou resultado do ICA para ${MUNICIPIO} — 2025: sem resultado (participação abaixo de 70%).`);
    expect(screen.queryByText(/Sem resultado importado do ICA/)).not.toBeInTheDocument();
    expect(screen.getByTestId("ica-selo")).toHaveTextContent("arquivo de 15/07/2026");
    expect(container.textContent).not.toMatch(/\b0%|0 p\.p\./);
  });

  it("territórios em anos diferentes: a meta da comparação diz o ano; o detalhe sai na precisão publicada", async () => {
    // SP só com o arquivo de UF de 2024 importado (estado intermediário normal)
    const uf = territorio("uf", "São Paulo", [num(2023, 18, FUF), num(2024, 26, FUF)],
      [num(2024, 25.4, FUF, { casas_decimais: 1 })], [comp(2024, 26, 25.4, 1, "atingiu")]);
    const br = territorio("brasil", "Brasil", [num(2025, 23, FUF)], [num(2025, 23, FUF)],
      [comp(2025, 23, 23, 0, "inconclusivo")]);
    responder("GET", "/redes/1/indicadores/ica", respostaComDado(
      [municipio({ detalhe2024: det(21.9, F2024) }), uf, br] as RespostaICA["territorios"]));
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });

    const comparacao = await screen.findByRole("table", { name: /município, do estado e do Brasil/ });
    const filas = within(comparacao).getAllByRole("row").slice(1);
    expect(within(comparacao).getByText("Meta (ano do último resultado)")).toBeInTheDocument();
    expect(filas[0]).toHaveTextContent("32% (2025)");
    expect(filas[1]).toHaveTextContent("25,4% (2024)");             // a de SP é de 2024, e diz
    expect(filas[2]).toHaveTextContent("23% (2025)");
    // 21,90 publicado com 2 casas não vira "21,9"
    const serie = screen.getByRole("table", { name: /resultado e meta por ano/ });
    expect(within(serie).getAllByRole("row")[2]).toHaveTextContent("21,90 no arquivo de 03/12/2025");
  });

  it("rede sem código IBGE: avisa que o município não pode ser recortado e quem cadastra", async () => {
    responder("GET", "/redes/1/indicadores/ica",
      respostaSemDado({ codigo_ibge: null, pendencia: "codigo_ibge", territorios: [] }));
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    expect(await screen.findByText(/não tem o código IBGE do município cadastrado/)).toHaveTextContent(
      "Quem cadastra o código é o administrador global do Constela.");
  });

  it("erro da API aparece (não vira cartão vazio)", async () => {
    responderErro("GET", "/redes/1/indicadores/ica", 403, "Acesso negado: você não pertence a esta rede.");
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    expect(await screen.findByText(/Não foi possível carregar o ICA: Acesso negado/)).toBeInTheDocument();
  });

  it("admin global: prévia (nada gravado) → aplicar com o mesmo arquivo → desfazer", async () => {
    let carregamentos = 0;
    responder("GET", "/redes/1/indicadores/ica", () => {
      carregamentos += 1;
      return carregamentos === 1 ? respostaSemDado() : respostaComDado();
    });
    responder("GET", "/redes/1/indicadores/importacoes", [
      { id: 7, status: "aplicada", arquivo_nome: "resultados_e_metas_ufs_2025_v2.xlsx", edicao_arquivo: 2025,
        arquivo_data: null, contadores: {}, avisos: [], created_at: "2026-10-16T10:00:00",
        aplicado_em: "2026-10-16T10:01:00", pode_desfazer: true },
    ]);
    responder("UPLOAD", "/redes/1/indicadores/ica/previa", {
      id: 9, status: "previa", arquivo_nome: "resultados_e_metas_municipios_2025_3.xlsx", edicao_arquivo: 2025,
      arquivo_data: "2026-07-15T10:00:00", created_at: null, aplicado_em: null,
      contadores: { novas: 12, alteradas: 0, iguais: 0, ausentes: 0 },
      avisos: [`${MUNICIPIO}: aviso sintético da prévia`],
      mudancas: [{ tipo: "nova", territorio: MUNICIPIO, indicador: "percentual_alfabetizado", edicao: 2024,
                   antes: null, antes_detalhe: null, antes_motivo: null, depois: 27.9, depois_detalhe: null,
                   depois_casas: 2, depois_casas_detalhe: null, depois_motivo: null }],
    });
    responder("UPLOAD", "/redes/1/indicadores/ica/aplicar", {
      id: 9, status: "aplicada", arquivo_nome: "resultados_e_metas_municipios_2025_3.xlsx", edicao_arquivo: 2025,
      arquivo_data: null, created_at: null, aplicado_em: null, avisos: [],
      contadores: { novas: 12, alteradas: 0, iguais: 0 },
    });
    responder("POST", "/redes/1/indicadores/importacoes/7/desfazer", { id: 7, status: "desfeita" });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const usuario = userEvent.setup();
    renderComApp(<CartaoICA redeId={1} ehGlobal />, { usuario: adminGlobal });
    await screen.findByText(/Sem resultado importado do ICA/);
    // o admin vê para QUAL rede está importando
    expect(screen.getByText(/Importar o ICA oficial para a rede “Rede Sintética”/)).toBeInTheDocument();

    const planilha = new File(["xlsx"], "resultados_e_metas_municipios_2025_3.xlsx");
    await usuario.upload(screen.getByLabelText("Planilha oficial do ICA"), planilha);
    const previa = await screen.findByTestId("ica-previa");
    expect(previa).toHaveTextContent("(avaliação 2025, arquivo de 15/07/2026) — nada foi gravado");
    expect(previa).toHaveTextContent("12 nova(s) · 0 alterada(s) · 0 igual(is)");
    expect(previa).toHaveTextContent("aviso sintético da prévia");
    expect(previa).toHaveTextContent("resultado 2024—27,90");       // na precisão publicada

    await usuario.click(screen.getByRole("button", { name: "Aplicar esta prévia" }));
    expect(await screen.findByText(/Importação aplicada: 12 nova\(s\)/)).toBeInTheDocument();
    const envio = apiUpload.mock.calls.find(([caminho]) => caminho === "/redes/1/indicadores/ica/aplicar");
    const corpo = envio?.[1] as FormData;
    expect(corpo.get("previa_id")).toBe("9");
    expect((corpo.get("arquivo") as File).name).toBe("resultados_e_metas_municipios_2025_3.xlsx");
    // o cartão recarrega e passa a mostrar o número
    expect(await screen.findByTestId("ica-capa")).toHaveTextContent("30% (2025) × meta 32% (−2 p.p.)");

    await usuario.click(screen.getByRole("button", { name: /Desfazer/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/redes/1/indicadores/importacoes/7/desfazer", { method: "POST" }));
    expect(await screen.findByText(/desfeita/)).toBeInTheDocument();
  });

  it("admin global: prévia de arquivo sem data interna diz isso (não inventa data)", async () => {
    responder("GET", "/redes/1/indicadores/ica", respostaSemDado());
    responder("GET", "/redes/1/indicadores/importacoes", []);
    responder("UPLOAD", "/redes/1/indicadores/ica/previa", {
      id: 10, status: "previa", arquivo_nome: "resultados_e_metas_municipios_2025_2.xlsx", edicao_arquivo: 2025,
      arquivo_data: null, created_at: null, aplicado_em: null,
      contadores: { novas: 0, alteradas: 0, iguais: 12 }, avisos: [], mudancas: [],
    });
    const usuario = userEvent.setup();
    renderComApp(<CartaoICA redeId={1} ehGlobal />, { usuario: adminGlobal });
    await screen.findByText(/Sem resultado importado do ICA/);
    await usuario.upload(screen.getByLabelText("Planilha oficial do ICA"),
      new File(["xlsx"], "resultados_e_metas_municipios_2025_2.xlsx"));
    expect(await screen.findByTestId("ica-previa")).toHaveTextContent("(avaliação 2025, arquivo sem data interna)");
  });

  it("admin global: rede sem código IBGE pede o código (sem adivinhar), mostra a rede e confirma o gravado", async () => {
    let carregamentos = 0;
    responder("GET", "/redes/1/indicadores/ica", () => {
      carregamentos += 1;
      return carregamentos === 1
        ? respostaSemDado({ codigo_ibge: null, pendencia: "codigo_ibge", territorios: [] })
        : respostaSemDado();
    });
    responder("GET", "/redes/1/indicadores/importacoes", []);
    responder("PATCH", "/redes/1", { id: 1, nome: "Rede Sintética", codigo_ibge: "3599999" });
    const usuario = userEvent.setup();
    renderComApp(<CartaoICA redeId={1} ehGlobal />, { usuario: adminGlobal });

    const campo = await screen.findByLabelText("Código IBGE do município da rede “Rede Sintética” (7 dígitos)");
    const gravar = screen.getByRole("button", { name: "Gravar código" });
    expect(gravar).toBeDisabled();
    await usuario.type(campo, "35999");
    expect(gravar).toBeDisabled();                     // 7 dígitos, nem um a menos
    await usuario.type(campo, "99");
    await usuario.click(gravar);
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/redes/1", { method: "PATCH", body: JSON.stringify({ codigo_ibge: "3599999" }) }));
    // o cartão recarrega, a pendência some e o campo sai — a confirmação fica
    expect(await screen.findByText("Código IBGE 3599999 gravado na rede “Rede Sintética”. Envie a prévia de novo."))
      .toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText(/Código IBGE do município/)).not.toBeInTheDocument());
    expect(screen.getByText("Código IBGE 3599999 gravado na rede “Rede Sintética”. Envie a prévia de novo."))
      .toBeInTheDocument();
  });
});

describe("Avaliações externas — o cartão do ICA entra na tela", () => {
  it("aparece no topo de /rede/avaliacoes para a Secretaria", async () => {
    responder("GET", "/redes/1/avaliacoes/opcoes", []);
    responder("GET", "/avaliacoes", []);
    responder("GET", "/avaliacoes/presets-import", []);
    responder("GET", "/redes/1/indicadores/ica", respostaComDado());
    renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByText("Indicador Criança Alfabetizada (ICA) — oficial")).toBeInTheDocument();
    expect(await screen.findByTestId("ica-capa")).toHaveTextContent("30% (2025)");
  });
});
