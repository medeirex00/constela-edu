/**
 * Data do relatório na importação manual (achado [10] da auditoria de 31/10).
 *
 * Antes, o /confirmar nunca levava `data_referencia`: o servidor datava o retrato
 * com o relógio de agora, e um relatório antigo virava "o dado de hoje" (ranking,
 * nota e frescor), sobrescrevendo o que a sincronização gravou. Agora, no total
 * acumulado (formato "resumo" sem "Intervalo de datas"), a tela pede a data —
 * vazia por padrão, sem presumir hoje — e a envia; sem ela, não deixa gravar.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import {
  dataDoRelatorioValida,
  exigeDataDoRelatorio,
  hojeEmBrasilia,
  instanteDoRelatorio,
  primeiroDiaDoRelatorio,
  problemaDaDataDoRelatorio,
} from "../lib/dataRelatorio";
import type { Analise } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import Importacoes from "../pages/Importacoes";
import {
  api,
  escolaFake,
  fireEvent,
  renderComApp,
  responder,
  screen,
  turmaFake,
  userEvent,
  within,
} from "./utils";
import type { OpcoesRender } from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";
const URL_RECALCULAR = "/escolas/1/importacoes/recalcular";

function analiseResumo(over: Partial<Analise> = {}): Analise {
  return {
    plataforma: "matific",
    formato: "resumo",
    tipo: "pdf",
    arquivo_token: "tok-123",
    arquivo_nome: "Matific.pdf",
    estrategia: "perfil_matific",
    mensagem_deteccao: "Este arquivo pertence ao Matific.",
    turma_detectada: "3º Ano A",
    origem_nome: "conteudo",
    periodo_inicio: "",
    periodo_fim: "",
    total_alunos: 1,
    total_linhas: 1,
    total_erros: 0,
    total_avisos: 0,
    erros_gerais: [],
    linhas: [
      {
        numero: 1,
        nome: "Ana Beatriz Souza",
        dados: { atividades: 20, pontuacao_media: 3, estrelas: 100 },
        erros: [],
        avisos: [],
        correspondencia: {
          status: "exato",
          aluno_id: 10,
          aluno_nome: "Ana Beatriz Souza",
          similaridade: 100,
          alternativas: [
            { aluno_id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A", similaridade: 100 },
          ],
        },
      },
    ],
    ...over,
  } as Analise;
}

function corpoDoConfirmar(): Record<string, unknown> {
  const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
  expect(chamada).toBeTruthy();
  const opcoes = chamada![1] as { body: string };
  return JSON.parse(opcoes.body) as Record<string, unknown>;
}

async function abrirPrevia(analise: Analise, opcoes: OpcoesRender = {}) {
  const u = userEvent.setup();
  responder("GET", URL_HIST, []);
  responder("GET", URL_TURMAS, [turmaFake()]);
  responder("UPLOAD", URL_ANALISAR, analise);
  responder("POST", URL_CONFIRMAR, {
    mensagem: "Importação concluída com sucesso.", importacao_id: 1, qtd_alunos: 1,
    qtd_erros: 0, avisos: [],
  });
  renderComApp(
    <ImportacaoLoteProvider>
      <Importacoes />
    </ImportacaoLoteProvider>,
    { rota: "/importacoes", ...opcoes },
  );
  await screen.findByText("Nenhuma importação ainda");
  await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
  await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 20");
  await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
  await screen.findByText("Prévia da importação");
  return u;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("lib/dataRelatorio", () => {
  it("o instante é o fim do dia em Brasília, nunca depois de agora", () => {
    const agora = new Date("2026-10-31T15:00:00Z");
    expect(instanteDoRelatorio("2026-08-14", agora)).toBe("2026-08-15T02:59:59.000Z");
    // Hoje: o fim do dia ainda não chegou — vale o agora.
    expect(instanteDoRelatorio("2026-10-31", agora)).toBe("2026-10-31T15:00:00.000Z");
    expect(instanteDoRelatorio("", agora)).toBeNull();
    expect(instanteDoRelatorio("2026-11-01", agora)).toBeNull();   // amanhã
  });

  it("'hoje' é o dia de Brasília (às 22h de 31/10 em Brasília o UTC já é 01/11)", () => {
    expect(hojeEmBrasilia(new Date("2026-11-01T01:00:00Z"))).toBe("2026-10-31");
    expect(dataDoRelatorioValida("2026-11-01", new Date("2026-11-01T01:00:00Z"))).toBe(false);
  });

  it("o mínimo é 1º de janeiro do ano letivo anterior (sem ano letivo, o ano anterior ao de hoje)", () => {
    const agora = new Date("2026-10-31T15:00:00Z");
    expect(primeiroDiaDoRelatorio(2026, agora)).toBe("2025-01-01");
    expect(primeiroDiaDoRelatorio(2025, agora)).toBe("2024-01-01");
    expect(primeiroDiaDoRelatorio(null, agora)).toBe("2025-01-01");
    // 31/12 às 23h em Brasília: o UTC já é 2027, mas o ano de hoje ainda é 2026.
    expect(primeiroDiaDoRelatorio(undefined, new Date("2027-01-01T02:00:00Z"))).toBe("2025-01-01");

    expect(dataDoRelatorioValida("2024-12-31", agora, 2026)).toBe(false);
    expect(dataDoRelatorioValida("2025-01-01", agora, 2026)).toBe(true);
    expect(dataDoRelatorioValida("2006-10-25", agora)).toBe(false);     // 2006 em vez de 2026
    expect(dataDoRelatorioValida("2024-06-01", agora, 2025)).toBe(true);

    expect(problemaDaDataDoRelatorio("", agora, 2026)).toBeNull();
    expect(problemaDaDataDoRelatorio("2026-08-14", agora, 2026)).toBeNull();
    expect(problemaDaDataDoRelatorio("2026-11-01", agora, 2026)).toBe(
      "A data do relatório não pode ser depois de hoje.");
    expect(problemaDaDataDoRelatorio("2006-10-25", agora, 2026)).toBe(
      "A data do relatório parece errada: confira o ano (a partir de 01/01/2025).");
  });

  it("só o total acumulado sem período exige a data", () => {
    expect(exigeDataDoRelatorio({ formato: "resumo" })).toBe(true);
    expect(exigeDataDoRelatorio({ formato: "resumo", periodo_inicio: "2026-03-01",
                                  periodo_fim: "2026-04-01" })).toBe(false);
    expect(exigeDataDoRelatorio({ formato: "leituras" })).toBe(false);
  });
});

describe("Importações — data do relatório (um por vez)", () => {
  it("total acumulado: a data começa vazia, é obrigatória e vai no /confirmar", async () => {
    const u = await abrirPrevia(analiseResumo());

    const campo = screen.getByLabelText("Data do relatório (obrigatória)") as HTMLInputElement;
    expect(campo.value).toBe("");                     // nunca presume hoje
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeDisabled();
    expect(screen.getByText("Informe a data do relatório para importar.")).toBeInTheDocument();

    fireEvent.change(campo, { target: { value: "2026-08-14" } });
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeEnabled();

    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent("Data do relatório: 14/08/2026");
    await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
    await screen.findByText("Importação concluída com sucesso.");

    expect(corpoDoConfirmar().data_referencia).toBe("2026-08-15T02:59:59.000Z");
  });

  it("data depois de hoje não deixa gravar", async () => {
    await abrirPrevia(analiseResumo());
    const campo = screen.getByLabelText("Data do relatório (obrigatória)");
    fireEvent.change(campo, { target: { value: "2999-01-01" } });
    expect(screen.getByRole("alert")).toHaveTextContent("não pode ser depois de hoje");
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeDisabled();
  });

  it("o campo tem mínimo (1º/01 do ano letivo anterior) e um ano errado não deixa gravar", async () => {
    // Escola com o ano letivo 2025 ativo: o mínimo vem DELE (2024), não do reserva
    // "ano de hoje − 1" — em 2026 os dois dariam 2025 e o teste não distinguiria.
    await abrirPrevia(analiseResumo(), { escolas: [escolaFake({ ano_letivo_ativo: 2025 })] });
    const campo = screen.getByLabelText("Data do relatório (obrigatória)") as HTMLInputElement;
    expect(campo.min).toBe("2024-01-01");
    fireEvent.change(campo, { target: { value: "2023-12-31" } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A data do relatório parece errada: confira o ano (a partir de 01/01/2024).");
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeDisabled();
    fireEvent.change(campo, { target: { value: "2024-01-01" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeEnabled();
  });

  it("relatório com 'Intervalo de datas' já traz as datas: nada a pedir", async () => {
    const u = await abrirPrevia(analiseResumo({
      periodo_inicio: "2026-03-01", periodo_fim: "2026-04-01",
    }));
    expect(screen.queryByLabelText("Data do relatório (obrigatória)")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    await u.click(await screen.findByRole("button", { name: "Gravar importação" }));
    await screen.findByText("Importação concluída com sucesso.");
    const corpo = corpoDoConfirmar();
    expect(corpo.data_referencia).toBeNull();
    expect(corpo.periodo_inicio).toBe("2026-03-01");
  });
});

describe("Importações — data do relatório (em lote)", () => {
  it("arquivo de total acumulado no lote: pede a data e a envia", async () => {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseResumo());
    responder("POST", URL_CONFIRMAR, { mensagem: "ok", importacao_id: 1, qtd_alunos: 1,
                                       qtd_erros: 0, avisos: [] });
    responder("POST", URL_RECALCULAR, { mensagem: "Notas recalculadas.", alunos: 1 });
    // Ano letivo 2025 ativo: o mínimo vem da escola (2024), não do reserva.
    const { container } = renderComApp(
      <ImportacaoLoteProvider>
        <ImportacaoLote />
      </ImportacaoLoteProvider>,
      { rota: "/importacoes", escolas: [escolaFake({ ano_letivo_ativo: 2025 })] },
    );
    await screen.findByText(/Arraste os relatórios em PDF aqui/);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["%PDF-1.4"], "Matific.pdf", { type: "application/pdf" })] },
    });
    await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
    await screen.findByText("Conferência da importação");

    const botao = screen.getByRole("button", { name: /Importar todos \(1\)/ });
    expect(botao).toBeDisabled();
    const campo = screen.getByLabelText("Data dos relatórios (obrigatória)") as HTMLInputElement;
    expect(campo.value).toBe("");
    expect(campo.min).toBe("2024-01-01");             // 1º/01 do ano letivo anterior
    fireEvent.change(campo, { target: { value: "2006-08-14" } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A data do relatório parece errada: confira o ano (a partir de 01/01/2024).");
    expect(botao).toBeDisabled();
    fireEvent.change(campo, { target: { value: "2024-01-01" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(botao).toBeEnabled();
    fireEvent.change(campo, { target: { value: "2026-08-14" } });
    expect(botao).toBeEnabled();

    await u.click(botao);
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar 1 arquivo(s)?" });
    expect(confirmacao).toHaveTextContent("14/08/2026");
    await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
    await screen.findByText("Importação em lote concluída");

    expect(corpoDoConfirmar().data_referencia).toBe("2026-08-15T02:59:59.000Z");
  });
});
