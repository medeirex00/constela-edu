/**
 * Auditoria (importação em lote): o arquivo que a confirmação manda para a Revisão.
 *
 * IMPORTACAO-8: o lote dizia "Aluno novo — será criado nesta turma." para o relatório
 * cujo nome só PARECE o de um aluno (a prévia diz "revisar") e, no fim, "Importados" —
 * mas o backend não cria nem importa nada: a linha vai para Revisões de identidade, e
 * ninguém ficava sabendo que precisa decidir. Com a política "bloquear", o mesmo com
 * todo aluno sem ficha.
 *
 * As respostas são as REAIS, gravadas por backend/tests/test_aud_impweb_lote_revisao.py
 * (que confere, do lado do backend, o que o corpo do lote faz). Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise, ResultadoImportacao, Turma } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import bloquearAnalise from "./fixtures/importacoes/previa_da_tela/lote_bloquear_analise.json";
import bloquearConfirmar from "./fixtures/importacoes/previa_da_tela/lote_bloquear_confirmar.json";
import parecidoAnalise from "./fixtures/importacoes/previa_da_tela/lote_nome_parecido_analise.json";
import parecidoConfirmar from "./fixtures/importacoes/previa_da_tela/lote_nome_parecido_confirmar.json";
import novoAnalise from "./fixtures/importacoes/previa_da_tela/lote_novo_analise.json";
import novoConfirmar from "./fixtures/importacoes/previa_da_tela/lote_novo_confirmar.json";
import loteTurmas from "./fixtures/importacoes/previa_da_tela/lote_revisao_turmas.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  screen,
  userEvent,
  within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";
const URL_RECALCULAR = "/escolas/1/importacoes/recalcular";

const copia = <T,>(valor: unknown) => JSON.parse(JSON.stringify(valor)) as T;
const TURMA_3A = copia<Turma[]>(loteTurmas).find((t) => t.nome === "3º Ano A")!.id;

async function conferir(analise: unknown, confirmar: unknown) {
  const u = userEvent.setup();
  responder("GET", URL_TURMAS, copia<Turma[]>(loteTurmas));
  responder("UPLOAD", URL_ANALISAR, copia<Analise>(analise));
  responder("POST", URL_CONFIRMAR, copia<ResultadoImportacao>(confirmar));
  responder("POST", URL_RECALCULAR, { mensagem: "Notas recalculadas.", alunos: 0 });
  const { container } = renderComApp(
    <ImportacaoLoteProvider><ImportacaoLote /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText(/Arraste os relatórios em PDF aqui/);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["%PDF-1.4"], "relatorio-ficticio.pdf", { type: "application/pdf" })] },
  });
  await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
  await screen.findByText("Conferência da importação");
  return u;
}

async function gravar(u: ReturnType<typeof userEvent.setup>) {
  await u.click(screen.getByRole("button", { name: /Importar todos \(1\)/ }));
  const confirmacao = await screen.findByRole("dialog", { name: "Gravar 1 arquivo(s)?" });
  const resumo = confirmacao.textContent ?? "";
  await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
  await screen.findByText(/Importação em lote concluída/);
  return resumo;
}

/** O número de um cartão do relatório final ("Importados", "Em revisão"…). */
function cartao(rotulo: string): string {
  const p = screen.getByText(rotulo, { selector: "p" });
  return (p.parentElement?.textContent ?? "").replace(rotulo, "");
}

function corpoDoConfirmar() {
  const chamada = api.mock.calls.find(([c, o]) => c === URL_CONFIRMAR
    && (o as RequestInit)?.method === "POST");
  expect(chamada).toBeDefined();
  return JSON.parse(String((chamada![1] as RequestInit).body));
}

const rodape = () => screen.getByText(/serão importados/).textContent;

describe("Importação em lote — nome parecido (a prévia diz 'revisar')", () => {
  it("a conferência diz que vai para Revisões, não que o aluno será criado", async () => {
    const corr = (parecidoAnalise as unknown as Analise).linhas[0].correspondencia!;
    expect([corr.status, corr.motivo]).toEqual(["revisar", "correspondencia_insegura"]);
    await conferir(parecidoAnalise, parecidoConfirmar);

    expect(screen.queryByText(/será criado nesta turma/)).toBeNull();
    expect(screen.getByText(
      "Vai para Revisões de identidade: o nome lembra o de Sofia Almeida Duarte, mas não o "
      + "bastante para vincular sozinho. Nada é criado nem vinculado — se você já sabe quem é "
      + "o aluno, use “Corrigir”.")).toBeInTheDocument();
    expect(rodape()).toBe("0 arquivo(s) serão importados. 1 vai para Revisões de identidade.");
  });

  it("o lote deixa o arquivo para a Revisão e o relatório conta 'Em revisão', não 'Importados'", async () => {
    const u = await conferir(parecidoAnalise, parecidoConfirmar);
    const resumo = await gravar(u);
    expect(resumo).toContain("1 vai para Revisões de identidade — nada é criado nem vinculado");

    // O corpo: nenhuma ficha escolhida nem turma de criação — a instrução de deixar
    // para a Revisão, com a turma do relatório só como contexto da pendência.
    const corpo = corpoDoConfirmar();
    expect(corpo.linhas).toHaveLength(2);
    for (const linha of corpo.linhas) {
      expect(linha).toMatchObject({ aluno_id: null, criar_em_turma_id: null,
                                    criar_em_turma_nome: "3 ANO A", deixar_para_revisao: true });
    }
    expect(cartao("Importados")).toBe("0");
    expect(cartao("Em revisão")).toBe("1");
    const bloco = screen.getByText("1 arquivo(s) foram para Revisões de identidade:").parentElement!;
    expect(bloco).toHaveTextContent("relatorio-ficticio.pdf");
    expect(within(bloco).getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
    expect(screen.queryByText(/não foram importados/)).toBeNull();
  });
});

describe("Importação em lote — política 'bloquear'", () => {
  it("o aluno sem ficha vai para Revisões: a conferência e o relatório dizem isso", async () => {
    expect((bloquearAnalise as unknown as Analise).criacao_bloqueada_por_politica).toBe(true);
    const u = await conferir(bloquearAnalise, bloquearConfirmar);
    expect(screen.queryByText(/será criado nesta turma/)).toBeNull();
    expect(screen.getByText(
      "Vai para Revisões de identidade: a matrícula desta escola vem da Lista Piloto e a "
      + "importação não cria ficha. Se a criança já tem ficha, use “Corrigir”.")).toBeInTheDocument();
    expect(rodape()).toBe("0 arquivo(s) serão importados. 1 vai para Revisões de identidade.");

    await gravar(u);
    // O corpo de sempre ("criar" na turma da prévia): a pendência nasce com o motivo da
    // política e a turma resolvida.
    expect(corpoDoConfirmar().linhas[0]).toMatchObject({ aluno_id: null, criar_em_turma_id: TURMA_3A,
                                                         deixar_para_revisao: false });
    expect(cartao("Importados")).toBe("0");
    expect(cartao("Em revisão")).toBe("1");
  });
});

describe("Importação em lote — contraprova e resposta sem nada gravado", () => {
  it("aluno novo sem a política: 'será criado' e, no fim, 'Importados'", async () => {
    const u = await conferir(novoAnalise, novoConfirmar);
    expect(screen.getByText("Aluno novo — será criado nesta turma.")).toBeInTheDocument();
    expect(rodape()).toBe("1 arquivo(s) serão importados.");
    await gravar(u);
    expect(corpoDoConfirmar().linhas[0]).toMatchObject({ criar_em_turma_id: TURMA_3A,
                                                         deixar_para_revisao: false });
    expect(cartao("Importados")).toBe("1");
    expect(cartao("Em revisão")).toBe("0");
  });

  it("resposta 200 sem aluno nem revisão: o arquivo não conta como importado e o motivo aparece", async () => {
    const aviso = "Linha “CRIANCA FICTICIA NOVA”: aluno não pertence a esta escola — ignorada.";
    const u = await conferir(novoAnalise, {
      ...copia<ResultadoImportacao>(novoConfirmar), qtd_alunos: 0, qtd_revisoes: 0, avisos: [aviso],
      mensagem: "0 aluno(s) com dado novo importado(s).",
    });
    await gravar(u);
    expect(cartao("Importados")).toBe("0");
    const bloco = screen.getByText("1 arquivo(s) não foram importados:").parentElement!;
    expect(bloco.textContent).toBe(
      `1 arquivo(s) não foram importados:relatorio-ficticio.pdf — Nada foi gravado deste arquivo. ${aviso}`);
  });
});
