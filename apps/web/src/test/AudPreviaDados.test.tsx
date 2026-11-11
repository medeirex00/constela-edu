/**
 * IMPORTACAO-15 — a coluna Dados da prévia juntava os campos com " · " (espaço comum
 * antes do ponto): quando a coluna apertava, o navegador quebrava ANTES do "·", e a
 * linha seguinte começava com ele ("Atividades: 1 / · Estrelas: 5 · Média: 5"). Com o
 * espaço inseparável antes do ponto, o "·" fica preso ao valor anterior e a quebra
 * acontece depois dele. O jsdom não faz layout: aqui fica o texto que garante a quebra
 * certa (a medida no Chromium está na prova do auditor).
 *
 * Prévia REAL do Placar com um aluno por motivo (backend/tests/test_importacao_previa_motivo.py).
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise } from "../lib/types";
import placarMotivos from "./fixtures/importacoes/analise_matific_placar_motivos.json";
import {
  fireEvent,
  renderComApp,
  responder,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

describe("Coluna Dados da prévia: nenhuma linha começa com '·'", () => {
  it("o '·' fica preso ao valor anterior (espaço inseparável antes, espaço comum depois)", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/1/importacoes", []);
    responder("GET", "/escolas/1/turmas", [turmaFake()]);
    responder("UPLOAD", "/escolas/1/importacoes/analisar", JSON.parse(JSON.stringify(placarMotivos)) as Analise);
    renderComApp(
      <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "placar");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    fireEvent.change(screen.getByLabelText("Data do relatório (obrigatória)"), { target: { value: "2026-08-14" } });

    const celulas = screen.getAllByRole("combobox", { name: /^Destino de / })
      .map((d) => (d.closest("tr") as HTMLTableRowElement).cells[1].textContent ?? "");
    expect(celulas.length).toBeGreaterThan(1);
    for (const texto of celulas) {
      expect(texto, texto).toMatch(/\u00a0· /);
      // Nenhum ponto depois de um espaço que quebra.
      expect(texto, texto).not.toMatch(/[ \t\n]·/);
    }
    const zefa = (screen.getByRole("combobox", { name: "Destino de Zefa Q" }).closest("tr") as HTMLTableRowElement)
      .cells[1].textContent;
    expect(zefa).toBe("Atividades: 2\u00a0· Estrelas: 9\u00a0· Média: 4,5");
  });
});
