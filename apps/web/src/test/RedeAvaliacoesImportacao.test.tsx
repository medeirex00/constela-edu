/**
 * Avaliações externas da rede — o que a tela de importação precisa garantir:
 *
 *  - a importação manual sugere o MESMO indicador/unidade do 1 clique do backend
 *    (a estimativa de alfabetização é taxa em %, não proficiência em pontos) e,
 *    para ela, a mesma etapa (2_ano) — as outras não pré-preenchem a etapa;
 *  - o seletor de arquivo só oferece o que o backend lê (sem .xls);
 *  - nenhum texto fixo chama a estimativa do Constela de "Criança Alfabetizada"
 *    nem a apresenta como base oficial (decisão D1): o rótulo e o órgão vêm da API;
 *  - a recusa do backend (coluna da edição ausente) aparece para o gestor, e os
 *    códigos INEP não casados aparecem TODOS (com "ver todos");
 *  - a correlação antiga (dispersão com o eixo do nome curto, evolução e Pearson) SAIU
 *    desta tela: ela misturava estimativa com oficial e cruzava anos diferentes; a relação
 *    com as plataformas é a da Análise educacional (/rede/analise?ver=relacao).
 *
 * (O arquivo não se chama RedeAvaliacoes.test.tsx: esse caminho já existe, não
 * rastreado, no trabalho paralelo do working tree principal.)
 *
 * Desde a E9 (decisão D4), SÓ o admin global vê os controles de importação: estes
 * testes rodam como admin global (antes, como a Secretaria — que agora só lê; o teste
 * dos controles por perfil está em `IndicadoresPerfis.test.tsx`).
 */
import { describe, expect, it } from "vitest";

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

const ROTULO_ESTIMATIVA =
  "Estimativa Constela de alfabetização (SARESP 2º ano) — não é o indicador oficial";
const ORGAO_ESTIMATIVA = "Constela (estimativa a partir do SARESP)";

// Quem importa: o admin global (D4). Ele escolhe a rede pela lista de redes.
const admin = usuarioFake({
  nome: "Root", cargo: "admin", is_global: true, escola_id: null,
});

function semear() {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética" }]);
  responder("GET", "/avaliacoes/fontes", []);
  responder("GET", "/redes/1/avaliacoes/opcoes", []);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
    { chave: "saeb", nome: "SAEB", tipo: "avaliacao", orgao: "INEP", descricao: null },
    { chave: "saresp", nome: "SARESP", tipo: "avaliacao", orgao: "SEDUC-SP", descricao: null },
    { chave: "crianca_alfabetizada", nome: ROTULO_ESTIMATIVA, tipo: "avaliacao",
      orgao: ORGAO_ESTIMATIVA, descricao: "Cálculo do Constela a partir do SARESP do 2º ano." },
  ]);
  responder("GET", "/avaliacoes/presets-import", [
    { chave: "ideb_ai", rotulo: "IDEB — Anos Iniciais", avaliacao: "ideb", dica: "Suba o .zip oficial." },
    { chave: "crianca_alfab", rotulo: ROTULO_ESTIMATIVA, avaliacao: "crianca_alfabetizada",
      dica: "É uma estimativa do Constela, não o indicador oficial do INEP." },
  ]);
}

/** As entradas de arquivo da importação POR ESCOLA (o cartão do ICA, que o admin global
 *  também vê, tem a dele — com outro formato — e fica de fora). */
function entradasDeArquivo(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLInputElement>('input[type="file"]'))
    .filter((e) => e.closest('[data-testid="cartao-ica"]') == null);
}

describe("Avaliações externas — importação", () => {
  it("só aceita os formatos que o backend lê (sem .xls)", async () => {
    semear();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("Importar em 1 clique");
    await screen.findByText("Importar resultado oficial");

    const entradas = entradasDeArquivo(container);
    expect(entradas).toHaveLength(2);                 // 1 clique + importação manual
    for (const e of entradas) {
      expect(e.accept.split(",")).toEqual([".xlsx", ".csv", ".zip"]);
    }
    expect(container.textContent).not.toMatch(/\.xls\b|XLS[^X]/);
  });

  it("a estimativa de alfabetização sugere taxa em % do 2º ano (igual ao backend), fora do grupo do INEP", async () => {
    semear();
    responder("UPLOAD", "/avaliacoes/analisar", {
      linhas_lidas: 2, n_colunas: 2,
      primeiras_linhas: [["CO_ESCOLA", "TAXA_ALFABETIZADOS_PCT"], ["35012345", "96.8"]],
    });
    responder("UPLOAD", "/avaliacoes/importar", {
      casados: 1, inseridos: 1, atualizados: 0, nao_casados: 0, ignorados: 0, inep_nao_casados: [],
    });
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("Importar resultado oficial");

    const manual = entradasDeArquivo(container)[1];
    await u.upload(manual, new File(["x"], "alfab.csv", { type: "text/csv" }));
    await screen.findByText(/primeira linha de dados/);

    const seletor = screen.getAllByRole<HTMLSelectElement>("combobox")
      .find((s) => s.querySelector('option[value="crianca_alfabetizada"]'));
    expect(seletor).toBeDefined();
    // O seletor agrupa pelo ÓRGÃO: a estimativa não fica sob "INEP / CAEd".
    const grupo = seletor!.querySelector('option[value="crianca_alfabetizada"]')!
      .closest("optgroup");
    expect(grupo).toHaveAttribute("label", ORGAO_ESTIMATIVA);

    const etapa = screen.getByLabelText("Etapa (fixa, opcional)");
    expect(etapa).toHaveValue("");                    // IDEB (inicial): sem etapa sugerida
    await u.selectOptions(seletor!, "crianca_alfabetizada");
    expect(screen.getByLabelText("Indicador")).toHaveValue("taxa_alfabetizacao");
    expect(screen.getByLabelText("Unidade")).toHaveValue("percentual");
    expect(etapa).toHaveValue("2_ano");               // a mesma etapa do 1 clique
    // As demais seguem iguais ao backend — e a etapa sugerida sai junto.
    await u.selectOptions(seletor!, "saresp");
    expect(screen.getByLabelText("Indicador")).toHaveValue("proficiencia");
    expect(screen.getByLabelText("Unidade")).toHaveValue("escala_saresp");
    expect(etapa).toHaveValue("");
    // A etapa que o gestor DIGITOU não some ao trocar entre avaliações sem sugestão.
    await u.type(etapa, "anos_finais");
    await u.selectOptions(seletor!, "saeb");
    expect(etapa).toHaveValue("anos_finais");

    // Importar a estimativa manda a etapa — a série é a MESMA do 1 clique.
    await u.selectOptions(seletor!, "crianca_alfabetizada");
    await u.click(screen.getByRole("button", { name: /Importar resultados/ }));
    await screen.findByText(/1 escola\(s\) casada\(s\) por INEP/);
    const chamada = apiUpload.mock.calls.find(([caminho]) => caminho === "/avaliacoes/importar");
    const enviado = chamada![1] as FormData;
    expect(enviado.get("indicador")).toBe("taxa_alfabetizacao");
    expect(enviado.get("unidade")).toBe("percentual");
    expect(enviado.get("etapa_fixa")).toBe("2_ano");

    // O rótulo é o da API (D1) — nenhum texto fixo da IMPORTAÇÃO diz "Criança
    // Alfabetizada". O cartão do ICA OFICIAL do INEP (E2) leva o nome de propósito:
    // ele é o indicador de verdade; fica fora desta conferência.
    expect(screen.getAllByRole("option", { name: ROTULO_ESTIMATIVA }).length).toBeGreaterThan(0);
    const semCartaoOficial = container.cloneNode(true) as HTMLElement;
    semCartaoOficial.querySelector('[data-testid="cartao-ica"]')?.remove();
    expect(container.querySelector('[data-testid="cartao-ica"]')).not.toBeNull();
    expect(semCartaoOficial.textContent).not.toMatch(/Criança Alfabetizada/);
  });

  it("etapa: o exemplo é o que o backend aceita (5_ano/2_ano no SAEB/SARESP) e a recusa aparece junto do botão", async () => {
    semear();
    responder("UPLOAD", "/avaliacoes/analisar", {
      linhas_lidas: 2, n_colunas: 2, primeiras_linhas: [["INEP", "PROF"], ["35990001", "201,7"]],
    });
    const RECUSA = "Para o SAEB e o SARESP, a etapa é a SÉRIE avaliada: use “5_ano” (ou “2_ano” no SARESP), "
      + "não “anos_iniciais” — esse rótulo fica para o IDEB. Nada foi gravado.";
    responderErro("UPLOAD", "/avaliacoes/importar", 400, RECUSA);
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("Importar resultado oficial");
    await u.upload(entradasDeArquivo(container)[1], new File(["x"], "saresp.csv", { type: "text/csv" }));
    await screen.findByText(/primeira linha de dados/);
    const seletor = screen.getAllByRole<HTMLSelectElement>("combobox")
      .find((s) => s.querySelector('option[value="saresp"]'))!;
    const etapa = screen.getByLabelText("Etapa (fixa, opcional)");

    // O exemplo do campo muda com a avaliação — e nunca sugere "anos_iniciais" fora do IDEB.
    expect(etapa).toHaveAttribute("placeholder", "ex.: anos_iniciais");     // IDEB (inicial)
    await u.selectOptions(seletor, "saeb");
    expect(etapa).toHaveAttribute("placeholder", "ex.: 5_ano");
    await u.selectOptions(seletor, "saresp");
    expect(etapa).toHaveAttribute("placeholder", "ex.: 5_ano ou 2_ano");
    await u.selectOptions(seletor, "crianca_alfabetizada");
    expect(etapa).toHaveAttribute("placeholder", "ex.: 2_ano");

    // Quem digita "anos_iniciais" num SARESP vê a recusa do backend, palavra por
    // palavra, logo abaixo do botão que clicou.
    await u.selectOptions(seletor, "saresp");
    await u.type(etapa, "anos_iniciais");
    const botao = screen.getByRole("button", { name: /Importar resultados/ });
    await u.click(botao);
    const recusa = (await screen.findByText(RECUSA)).closest('[role="alert"]')!;
    expect(recusa).not.toBeNull();                                  // erro anunciado (role=alert)
    expect(botao.compareDocumentPosition(recusa) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const enviado = apiUpload.mock.calls.find(([caminho]) => caminho === "/avaliacoes/importar")![1] as FormData;
    expect(enviado.get("etapa_fixa")).toBe("anos_iniciais");
  });

  it("1 clique não chama a base de 'oficial' (a estimativa do Constela está na lista)", async () => {
    semear();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByRole("option", { name: ROTULO_ESTIMATIVA });
    expect(screen.getByLabelText("Base a importar")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Base oficial|Importar oficial/);
    expect(container.textContent).toMatch(/estimativa de\s+alfabetização do Constela \(não oficial\)/);
  });

  it("1 clique: a recusa do backend (coluna da edição ausente) aparece para o gestor", async () => {
    semear();
    responderErro("UPLOAD", "/avaliacoes/importar-preset", 400,
      "O arquivo não tem a coluna VL_OBSERVADO_2025; confira se é o arquivo oficial do INEP "
      + "de Anos Iniciais (Ideb por escola) da edição 2025. Nada foi gravado.");
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("Importar em 1 clique");
    await screen.findByRole("option", { name: "IDEB — Anos Iniciais" });

    await u.upload(entradasDeArquivo(container)[0],
      new File(["x"], "divulgacao_anos_iniciais_escolas_2023.zip", { type: "application/zip" }));
    expect(await screen.findByText(/não tem a coluna VL_OBSERVADO_2025.*Nada foi gravado/))
      .toBeInTheDocument();
  });

  it("1 clique: mostra de qual coluna saiu a série e TODOS os códigos não casados", async () => {
    semear();
    const fora = Array.from({ length: 25 }, (_, i) => String(41000000 + i));
    responder("UPLOAD", "/avaliacoes/importar-preset", {
      avaliacao: "ideb", rotulo: "IDEB — Anos Iniciais", edicao: 2023,
      series: [{ componente: null, coluna: "VL_OBSERVADO_2023", casados: 1, inseridos: 1,
                 atualizados: 0, nao_casados: 25, inep_nao_casados: fora }],
    });
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByRole("option", { name: "IDEB — Anos Iniciais" });

    await u.upload(entradasDeArquivo(container)[0],
      new File(["x"], "divulgacao_anos_iniciais_escolas_2023.zip", { type: "application/zip" }));
    // A edição vem antes do rótulo (o da estimativa termina em "não é o indicador oficial").
    expect(await screen.findByText(
      /^Importado \(2023\): IDEB — Anos Iniciais — resultado \(VL_OBSERVADO_2023\): 1 escola\(s\) casada\(s\)/))
      .toBeInTheDocument();
    expect(apiUpload).toHaveBeenCalledWith("/avaliacoes/importar-preset", expect.any(FormData));

    // Os 20 primeiros à vista; o 25º só depois de "ver todos".
    expect(screen.getByText(/41000000, 41000001/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("41000024");
    await u.click(screen.getByRole("button", { name: "ver todos (25)" }));
    expect(container.textContent).toContain("41000024");
    expect(screen.getByRole("button", { name: "ver menos" })).toBeInTheDocument();
  });

  it("1 clique: casada que já tem o número OFICIAL não é gravada — a tela diz 'nada gravado' e por quê (não verde)", async () => {
    semear();
    responder("UPLOAD", "/avaliacoes/importar-preset", {
      avaliacao: "ideb", rotulo: "IDEB — Anos Iniciais", edicao: 2023,
      series: [{ componente: null, coluna: "VL_OBSERVADO_2023", casados: 3, inseridos: 0,
                 atualizados: 0, mantidos_oficiais: 3, nao_casados: 0, inep_nao_casados: [] }],
    });
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByRole("option", { name: "IDEB — Anos Iniciais" });
    await u.upload(entradasDeArquivo(container)[0],
      new File(["x"], "divulgacao_anos_iniciais_escolas_2023.zip", { type: "application/zip" }));
    const aviso = (await screen.findByText(/^Nada gravado \(2023\): IDEB — Anos Iniciais/)).closest('[role="alert"]');
    expect(aviso).not.toBeNull();                                   // vermelho: nada mudou
    expect(aviso!.textContent).toMatch(/3 número\(s\) mantido\(s\): .*importação oficial.*desfaça/);
  });

  it("1 clique: nenhuma escola casada também é 'Nada gravado' (o título segue o tom, sem mantidos)", async () => {
    semear();
    responder("UPLOAD", "/avaliacoes/importar-preset", {
      avaliacao: "ideb", rotulo: "IDEB — Anos Iniciais", edicao: 2023,
      series: [{ componente: null, coluna: "VL_OBSERVADO_2023", casados: 0, inseridos: 0,
                 atualizados: 0, mantidos_oficiais: 0, nao_casados: 2,
                 inep_nao_casados: ["41000000", "41000001"] }],
    });
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByRole("option", { name: "IDEB — Anos Iniciais" });
    await u.upload(entradasDeArquivo(container)[0],
      new File(["x"], "divulgacao_anos_iniciais_escolas_2023.zip", { type: "application/zip" }));
    const aviso = (await screen.findByText(/^Nada gravado \(2023\): IDEB — Anos Iniciais/)).closest('[role="alert"]');
    expect(aviso).not.toBeNull();
    expect(aviso!.textContent).toMatch(/0 escola\(s\) casada\(s\)/);
    expect(aviso!.textContent).not.toMatch(/Importado|mantido/);
  });

  it("importação manual: os mantidos pela importação oficial aparecem, e o tom segue o que foi gravado", async () => {
    semear();
    responder("UPLOAD", "/avaliacoes/analisar", {
      linhas_lidas: 2, n_colunas: 2, primeiras_linhas: [["INEP", "IDEB"], ["35990001", "6,1"]],
    });
    responder("UPLOAD", "/avaliacoes/importar", {
      casados: 3, inseridos: 1, atualizados: 0, mantidos_oficiais: 2, nao_casados: 0, ignorados: 0,
      inep_nao_casados: [],
    });
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("Importar resultado oficial");
    await u.upload(entradasDeArquivo(container)[1], new File(["x"], "ideb.csv", { type: "text/csv" }));
    await screen.findByText(/primeira linha de dados/);
    await u.click(screen.getByRole("button", { name: /Importar resultados/ }));
    const aviso = (await screen.findByText(/3 escola\(s\) casada\(s\) por INEP — 1 nova\(s\)/)).closest('[role="status"]');
    expect(aviso).not.toBeNull();                                   // gravou 1: verde
    expect(aviso!.textContent).toMatch(/2 número\(s\) mantido\(s\)/);
  });
});

describe("Avaliações externas — a correlação saiu desta tela", () => {
  // Leitura: a Secretaria (que lê a rede) basta — não depende de importar.
  const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });

  function semearSeries(nome: string) {
    responder("GET", "/avaliacoes", []);
    responder("GET", "/avaliacoes/presets-import", []);
    responder("GET", "/redes/1/avaliacoes/opcoes", [{
      avaliacao: "crianca_alfabetizada", nome, tipo: "avaliacao",
      indicador: "taxa_alfabetizacao", etapa: "2_ano", componente: null, edicoes: [2025],
    }]);
  }

  it("mesmo com série importada (inclusive a estimativa), não há dispersão nem correlação", async () => {
    semearSeries(ROTULO_ESTIMATIVA);
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByTestId("cartao-avaliacoes-externas")).toBeInTheDocument();
    await waitFor(() => expect(api.mock.calls.some(([c]) => String(c) === "/redes/1/avaliacoes/opcoes")).toBe(true));
    expect(container.querySelector('svg[aria-label^="Dispersão"]')).toBeNull();
    expect(screen.queryByText("Dispersão por escola")).not.toBeInTheDocument();
    expect(api.mock.calls.some(([c]) => String(c).includes("/avaliacoes/correlacao"))).toBe(false);
  });

  it("a página se diz a área de fontes e arquivos oficiais e o cartão volta a Avaliações externas", async () => {
    semearSeries(ROTULO_ESTIMATIVA);
    renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByRole("heading", { level: 1, name: "Fontes dos indicadores" })).toBeInTheDocument();
    expect(screen.getByText(/Fontes e arquivos oficiais \(detalhe técnico\)/))
      .toHaveTextContent("Para entender os resultados, comece por Avaliações externas.");
    expect(await screen.findByRole("link", { name: /Voltar para Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    // As Análises avançadas não estão no menu da Secretaria: o cartão não aponta para lá.
    expect(screen.queryByRole("link", { name: "Análises avançadas" })).not.toBeInTheDocument();
  });

  it("o admin global continua com o link secundário para a relação (Análises avançadas), com a rede", async () => {
    semearSeries(ROTULO_ESTIMATIVA);
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética" }]);
    responder("GET", "/avaliacoes/fontes", []);
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    expect(await screen.findByRole("heading", { level: 1, name: "Importações e fontes" })).toBeInTheDocument();
    expect(within(screen.getByTestId("cartao-avaliacoes-externas")).getByRole("link", { name: "Análises avançadas" }))
      .toHaveAttribute("href", "/rede/analise?ver=relacao&rede=1");
  });
});
