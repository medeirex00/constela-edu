/**
 * Importação da Lista Piloto (matrículas) — o fluxo em três passos da identidade v2:
 * planilha → conferência → confirmação. O que fica travado aqui:
 *
 *  - nada é gravado antes da confirmação (o /confirmar só sai do botão do diálogo);
 *  - a confirmação diz o efeito com os números da prévia, inclusive o "fora da lista
 *    piloto" (que não apaga ninguém);
 *  - planilha sem turma = estado vazio explícito e o botão de gravar desligado;
 *  - avisos além dos 8 primeiros não somem em silêncio (a contagem aparece).
 */
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Drawer } from "../components/ui";
import ImportacaoMatriculas from "../pages/ImportacaoMatriculas";
import { apiUpload, fireEvent, renderComApp, responder, responderErro, screen, userEvent, within } from "./utils";

const URL_ANALISAR = "/escolas/1/importacoes/matriculas/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/matriculas/confirmar";

function analiseFake(over: Record<string, unknown> = {}) {
  return {
    escola_detectada: "EMEF ESCOLA FICTÍCIA",
    ano_letivo: 2026,
    total_turmas: 2,
    total_alunos: 48,
    total_registros: 48,
    alunos_novos: 30,
    alunos_atualizar: 18,
    turmas_existentes: 1,
    turmas: [
      { nome: "3º Ano A", ano_escolar: "3º Ano", turno: "manhã", professor: "Prof. Fictícia", sed: "",
        total_alunos: 25, ja_existe: true, exemplos: ["Aluno Um", "Aluno Dois", "Aluno Três"] },
      { nome: "4º Ano B", ano_escolar: "4º Ano", turno: "tarde", professor: "", sed: "",
        total_alunos: 23, ja_existe: false, exemplos: ["Aluno Quatro"] },
    ],
    avisos: [],
    ...over,
  };
}

function montar(aoConcluir = vi.fn()) {
  const r = renderComApp(<ImportacaoMatriculas escolaId={1} aoConcluir={aoConcluir} aoAvancar={() => undefined} />);
  return { ...r, aoConcluir };
}

async function enviarPlanilha() {
  const u = userEvent.setup();
  const input = screen.getByLabelText("Planilha de matrículas da escola (.xls ou .xlsx)");
  fireEvent.change(input, {
    target: { files: [new File(["xls"], "lista-piloto.xlsx", { type: "application/vnd.ms-excel" })] },
  });
  expect(screen.getByText("lista-piloto.xlsx")).toBeInTheDocument();
  await u.click(screen.getByRole("button", { name: "Analisar planilha" }));
  return u;
}

const chamadasConfirmar = () => apiUpload.mock.calls.filter(([caminho]) => caminho === URL_CONFIRMAR);

describe("Importação da Lista Piloto", () => {
  it("prévia → confirmação com o efeito → gravação", async () => {
    responder("UPLOAD", URL_ANALISAR, analiseFake());
    responder("UPLOAD", URL_CONFIRMAR, {
      mensagem: "Lista Piloto importada.", turmas_criadas: 1, alunos_criados: 30,
      alunos_atualizados: 18, alunos_fora_lista: 2, avisos: [],
    });
    const { aoConcluir } = montar();
    const u = await enviarPlanilha();

    // Prévia: os números da análise e a situação de cada turma.
    expect(await screen.findByText("EMEF ESCOLA FICTÍCIA · 2026")).toBeInTheDocument();
    expect(screen.getByText("aluno(s) novo(s)").previousSibling).toHaveTextContent("30");
    expect(screen.getByText("a atualizar").previousSibling).toHaveTextContent("18");
    expect(screen.getByText("nova")).toBeInTheDocument();
    expect(screen.getByText("já existe")).toBeInTheDocument();

    // O botão da prévia só ABRE a confirmação.
    await u.click(screen.getByRole("button", { name: "Criar turmas e matricular 48 aluno(s)" }));
    const dialogo = await screen.findByRole("dialog", { name: "Gravar a Lista Piloto?" });
    expect(chamadasConfirmar()).toHaveLength(0);
    expect(dialogo).toHaveTextContent("1 turma(s) nova(s) criada(s)");
    expect(dialogo).toHaveTextContent("30 aluno(s) novo(s) matriculado(s)");
    expect(dialogo).toHaveTextContent("18 aluno(s) já cadastrado(s) atualizado(s)");
    expect(dialogo).toHaveTextContent("continua cadastrado (nada é apagado)");

    // Cancelar não grava.
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog", { name: "Gravar a Lista Piloto?" })).toBeNull();
    expect(chamadasConfirmar()).toHaveLength(0);

    await u.click(screen.getByRole("button", { name: "Criar turmas e matricular 48 aluno(s)" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Gravar matrículas" }));

    expect(await screen.findByText("Lista Piloto importada.")).toBeInTheDocument();
    expect(chamadasConfirmar()).toHaveLength(1);
    expect(aoConcluir).toHaveBeenCalledTimes(1);
    expect(screen.getByText("2 fora da lista piloto")).toBeInTheDocument();
    expect(screen.getByText(/continuam\s+cadastrados \(nada foi apagado\)/)).toBeInTheDocument();
  });

  it("planilha sem nenhuma turma: estado vazio explícito e nada para gravar", async () => {
    responder("UPLOAD", URL_ANALISAR, analiseFake({ total_turmas: 0, total_alunos: 0, total_registros: 0,
      alunos_novos: 0, alunos_atualizar: 0, turmas_existentes: 0, turmas: [] }));
    montar();
    await enviarPlanilha();
    expect(await screen.findByText("Nenhuma turma encontrada na planilha")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar turmas e matricular 0 aluno(s)" })).toBeDisabled();
  });

  it("avisos além dos 8 primeiros não somem em silêncio", async () => {
    const avisos = Array.from({ length: 11 }, (_, i) => `Aviso fictício ${i + 1}`);
    responder("UPLOAD", URL_ANALISAR, analiseFake({ avisos }));
    montar();
    const u = await enviarPlanilha();
    expect(await screen.findByText("11 avisos da planilha")).toBeInTheDocument();
    expect(screen.getByText("Aviso fictício 8")).toBeInTheDocument();
    expect(screen.queryByText("Aviso fictício 9")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Ver mais 3 avisos" }));
    expect(screen.getByText("Aviso fictício 11")).toBeInTheDocument();
  });

  it("erro ao ler a planilha aparece e nada avança", async () => {
    responderErro("UPLOAD", URL_ANALISAR, 422, "A planilha não tem abas de turma.");
    montar();
    await enviarPlanilha();
    expect(await screen.findByText("A planilha não tem abas de turma.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analisar planilha" })).toBeEnabled();
  });

  it("dentro da gaveta 'Atualizar Lista Piloto': Esc na confirmação fecha só ela e a prévia fica", async () => {
    // Como em Sincronizacao.tsx: o componente vive num Drawer. Os dois ouvintes de
    // Esc ficam no window; antes, o Esc da confirmação fechava a gaveta junto e
    // descartava a prévia já analisada.
    responder("UPLOAD", URL_ANALISAR, analiseFake());
    function NaGaveta() {
      const [aberta, setAberta] = useState(true);
      return (
        <Drawer titulo="Atualizar Lista Piloto" aberto={aberta} aoFechar={() => setAberta(false)}>
          <ImportacaoMatriculas escolaId={1} aoConcluir={() => undefined} aoAvancar={() => undefined} />
        </Drawer>
      );
    }
    renderComApp(<NaGaveta />);
    const u = await enviarPlanilha();
    expect(await screen.findByText("EMEF ESCOLA FICTÍCIA · 2026")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Criar turmas e matricular 48 aluno(s)" }));
    await screen.findByRole("dialog", { name: "Gravar a Lista Piloto?" });

    await u.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Gravar a Lista Piloto?" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Atualizar Lista Piloto" })).toBeInTheDocument();
    expect(screen.getByText("EMEF ESCOLA FICTÍCIA · 2026")).toBeInTheDocument();
    expect(chamadasConfirmar()).toHaveLength(0);

    await u.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Atualizar Lista Piloto" })).toBeNull();
    expect(chamadasConfirmar()).toHaveLength(0);
  });
});
