/**
 * IMPORTACAO-7 / REVERIFICACAO-1 / IMPORTACAO-3 — a prévia só tratava a turma
 * ARQUIVADA como "turma sem destino". Com "turma ambígua" (mais de uma turma cadastrada
 * para a sala) ou "turma de outra etapa" (a única turma da sala é da Educação Infantil
 * e o relatório é do 1º Ano), a tela pré-escolhia uma turma ou oferecia "Criar na
 * turma do relatório", dizia "1 de 1 aluno(s) serão importados" (e "a turma será
 * criada") — e o backend mandava a linha para a Revisão, sem ficha nem turma. Um
 * "Criar" numa turma de outra etapa que a do relatório também vira Revisão no backend,
 * mesmo com a turma escolhida, e a tela o contava como importado.
 *
 * As prévias, as turmas e as respostas da confirmação são as REAIS, gravadas por
 * backend/tests/test_aud_impweb_turma_sem_destino.py, que confere cada corpo abaixo
 * do lado do backend. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { etapaDaSala } from "../lib/nomes";
import Importacoes from "../pages/Importacoes";
import type { Analise, ResultadoImportacao, Turma } from "../lib/types";
import ambigua from "./fixtures/importacoes/previa_da_tela/ambigua_analise.json";
import ambiguaTurmas from "./fixtures/importacoes/previa_da_tela/ambigua_turmas.json";
import ambiguaConfirmar from "./fixtures/importacoes/previa_da_tela/ambigua_confirmar_revisao.json";
import ambiguaTurno from "./fixtures/importacoes/previa_da_tela/ambigua_turno_analise.json";
import ambiguaTurnoTurmas from "./fixtures/importacoes/previa_da_tela/ambigua_turno_turmas.json";
import etapa from "./fixtures/importacoes/previa_da_tela/etapa_analise.json";
import etapaTurmas from "./fixtures/importacoes/previa_da_tela/etapa_turmas.json";
import etapaNaFase from "./fixtures/importacoes/previa_da_tela/etapa_confirmar_na_fase.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  screen,
  userEvent,
  within,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

const copia = <T,>(x: unknown) => JSON.parse(JSON.stringify(x)) as T;
const idDe = (turmas: { id: number; nome: string }[], nome: string) =>
  String(turmas.find((t) => t.nome === nome)!.id);

async function previa(analise: unknown, turmas: unknown) {
  const u = userEvent.setup();
  responder("GET", URL_HIST, []);
  responder("GET", URL_TURMAS, copia<Turma[]>(turmas));
  responder("UPLOAD", URL_ANALISAR, copia<Analise>(analise));
  renderComApp(
    <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText("Nenhuma importação ainda");
  await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
  await u.type(screen.getByRole("textbox"), "placar");
  await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
  await screen.findByText("Prévia da importação");
  const data = screen.queryByLabelText("Data do relatório (obrigatória)");
  if (data) fireEvent.change(data, { target: { value: "2026-08-14" } });
  return u;
}

const destino = () => screen.getByRole("combobox", { name: /^Destino de / }) as HTMLSelectElement;
const rodape = () => screen.getByText(/serão importados/).textContent;
const SO_REVISAO = "0 de 1 aluno(s) serão importados; 1 vai para Revisões de identidade.";

async function confirmacao(u: ReturnType<typeof userEvent.setup>) {
  await u.click(screen.getByRole("button", { name: "Sim, importar" }));
  return screen.findByRole("dialog", { name: "Gravar esta importação?" });
}

function corpo() {
  const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
  return JSON.parse(String((chamada?.[1] as RequestInit).body));
}

describe("Turma ambígua: a linha fica na Revisão até o gestor escolher a turma", () => {
  it("'3 ANO A' com '3º Ano A' e '3ª Série A': nenhuma turma pré-escolhida, contada em Revisões", async () => {
    expect((ambigua as unknown as Analise).linhas[0].correspondencia?.motivo).toBe("turma_ambigua");
    const u = await previa(ambigua, ambiguaTurmas);
    expect(destino().value).toBe("revisao");
    expect(Array.from(destino().options).map((o) => o.textContent))
      .toEqual(["Deixar para a Revisão", "Criar aluno novo…", "Ignorar"]);
    expect(screen.queryByRole("combobox", { name: /^Turma para Crianca/ })).toBeNull();
    expect(screen.getByText("Mais de uma turma possível — escolha a turma")).toBeInTheDocument();
    expect(rodape()).toBe(SO_REVISAO);
    expect(screen.queryByText(/já marcados para criar na turma do relatório/)).toBeNull();
    expect(screen.queryByText(/será criada automaticamente/)).toBeNull();

    const dialogo = await confirmacao(u);
    expect(dialogo).toHaveTextContent(/1 vai para Revisões de identidade — nenhuma ficha é criada/);
    expect(dialogo).not.toHaveTextContent(/aluno\(s\) novo\(s\)/);
    responder("POST", URL_CONFIRMAR, ambiguaConfirmar as unknown as ResultadoImportacao);
    await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
    // O corpo que o backend confirma: 0 importados, 1 revisão "turma_ambigua".
    expect(corpo().linhas).toMatchObject([
      { aluno_id: null, criar_em_turma_id: null, criar_em_turma_nome: "3 ANO A", deixar_para_revisao: true }]);
    expect(await screen.findByText(/1 aluno aguarda a decisão de um gestor/)).toBeInTheDocument();
  });

  it("'5º Ano A' com '5º Ano A Manhã' e '5º Ano A Tarde': a turma do relatório não é 'criada'", async () => {
    expect((ambiguaTurno as unknown as Analise).linhas[0].correspondencia?.motivo).toBe("turma_ambigua");
    const u = await previa(ambiguaTurno, ambiguaTurnoTurmas);
    expect(destino().value).toBe("revisao");
    expect(Array.from(destino().options).map((o) => o.value)).not.toContain("criar_nova");
    expect(rodape()).toBe(SO_REVISAO);
    expect(screen.queryByText(/será criada automaticamente/)).toBeNull();
    expect(screen.queryByRole("button", { name: /turma do relatório \(nova\)/ })).toBeNull();

    // A turma escolhida pelo gestor resolve: a ficha nasce nela (backend: cria).
    await u.selectOptions(destino(), "criar");
    await u.selectOptions(screen.getByRole("combobox", { name: /^Turma para Crianca/ }),
      idDe(ambiguaTurnoTurmas, "5º Ano A Tarde"));
    expect(rodape()).toBe("1 de 1 aluno(s) serão importados.");
  });
});

describe("Turma de outra etapa: a ficha não nasce na turma da Educação Infantil", () => {
  it("'1 ANO A' com só a '1ºA' da Fase: vai para a Revisão; 'Criar' na Fase também; numa turma do Fundamental, importa", async () => {
    expect((etapa as unknown as Analise).linhas[0].correspondencia?.motivo).toBe("turma_de_outra_etapa");
    const u = await previa(etapa, etapaTurmas);
    expect(destino().value).toBe("revisao");
    expect(Array.from(destino().options).map((o) => o.textContent))
      .toEqual(["Deixar para a Revisão", "Criar aluno novo…", "Ignorar"]);
    expect(screen.getByText("Turma de outra etapa — escolha a turma")).toBeInTheDocument();
    expect(rodape()).toBe(SO_REVISAO);

    // "Criar aluno novo…" na 1ºA da Fase: o backend recusa (turma de outra etapa).
    await u.selectOptions(destino(), "criar");
    const turma = screen.getByRole("combobox", { name: /^Turma para Crianca/ }) as HTMLSelectElement;
    await u.selectOptions(turma, idDe(etapaTurmas, "1ºA"));
    expect(rodape()).toBe(SO_REVISAO);
    expect(screen.getByText(/é de outra etapa que a turma do relatório/)).toBeInTheDocument();
    let dialogo = await confirmacao(u);
    expect(dialogo).toHaveTextContent(/1 vai para Revisões de identidade/);
    expect(dialogo).not.toHaveTextContent(/aluno\(s\) novo\(s\)/);
    responder("POST", URL_CONFIRMAR, etapaNaFase as unknown as ResultadoImportacao);
    await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
    expect(corpo().linhas).toMatchObject([{ criar_em_turma_id: Number(idDe(etapaTurmas, "1ºA")) }]);
    expect(await screen.findByText(/1 aluno aguarda a decisão de um gestor/)).toBeInTheDocument();
  });

  it("'Criar aluno novo…' numa turma do Fundamental: conta como importado", async () => {
    const u = await previa(etapa, etapaTurmas);
    await u.selectOptions(destino(), "criar");
    await u.selectOptions(screen.getByRole("combobox", { name: /^Turma para Crianca/ }), idDe(etapaTurmas, "3º Ano A"));
    expect(rodape()).toBe("1 de 1 aluno(s) serão importados.");
    expect(screen.queryByText(/é de outra etapa que a turma do relatório/)).toBeNull();
    const dialogo = await confirmacao(u);
    expect(dialogo).toHaveTextContent("1 aluno(s) novo(s)");
  });
});

describe("etapaDaSala: a mesma regra do backend (matriculas.etapa_da_sala)", () => {
  it.each([
    ["1ºA", "1ª Fase", "fora_do_fundamental"],
    ["1ª Fase A", "", "fora_do_fundamental"],
    ["Pré 1 A", "", "fora_do_fundamental"],
    ["1 ANO A TARDE ANUAL", "", "fundamental"],
    ["3º Ano A", "3º Ano", "fundamental"],
    // "ANO" explícito vence a palavra de etapa (elegibilidade._RE_ANO_EXPLICITO).
    ["4º Ano - Fase 2", "", "fundamental"],
    ["Turma do Primeiro Ano", "", "fundamental"],
  ])("'%s' (ano escolar '%s') → %s", (nome, ano, esperado) => {
    expect(etapaDaSala(nome, ano)).toBe(esperado);
  });
});
