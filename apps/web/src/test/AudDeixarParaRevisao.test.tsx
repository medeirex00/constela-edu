/**
 * IMPORTACAO-6 / WEB-3 — "Deixar para a Revisão" não era uma instrução: a tela mandava
 * o MESMO corpo de um "Criar" (a turma da linha) e confiava que o backend repetiria a
 * decisão da prévia. Com duas contas de mesmo nome e nenhuma ficha, ignorar uma
 * mandava a outra SOZINHA; sem a rival no mesmo envio, o backend decidia "criar" — e a
 * ficha nascia, embora o rodapé e a confirmação dissessem "vai para Revisões de
 * identidade — nenhuma ficha é criada". Agora a linha vai com `deixar_para_revisao`
 * (o backend nunca associa nem cria nela) e a turma do relatório pelo nome, só como
 * contexto da pendência.
 *
 * A prévia e a resposta da confirmação são as REAIS, gravadas por
 * backend/tests/test_aud_impweb_deixar_para_revisao.py — que confere, com este mesmo
 * corpo, que nenhuma ficha é criada e a pendência fica com o motivo
 * "deixada_para_revisao". Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import RevisoesIdentidade from "../pages/RevisoesIdentidade";
import type { RevisaoIdentidade } from "../pages/RevisoesIdentidade";
import type { Analise, ResultadoImportacao } from "../lib/types";
import duasContas from "./fixtures/importacoes/previa_da_tela/duas_contas_analise.json";
import duasContasConfirmar from "./fixtures/importacoes/previa_da_tela/duas_contas_confirmar_uma.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  screen,
  turmaFake,
  userEvent,
  within,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

async function previa(analise: unknown) {
  const u = userEvent.setup();
  responder("GET", URL_HIST, []);
  responder("GET", URL_TURMAS, [turmaFake()]);
  responder("UPLOAD", URL_ANALISAR, JSON.parse(JSON.stringify(analise)) as Analise);
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

describe("Importações: 'Deixar para a Revisão' é uma instrução ao backend", () => {
  it("duas contas com o mesmo nome, uma ignorada: a outra vai com 'deixar_para_revisao' e nenhuma ficha nasce", async () => {
    const u = await previa(duasContas);
    await u.selectOptions(
      screen.getByRole("combobox", { name: "Destino de Crianca Ficticia Repetida (conta 2 de 2)" }), "ignorar");
    expect((screen.getByRole("combobox", { name: "Destino de Crianca Ficticia Repetida (conta 1 de 2)" }) as HTMLSelectElement)
      .value).toBe("revisao");
    expect(screen.getByText(/serão importados/).textContent)
      .toBe("1 de 3 aluno(s) serão importados; 1 vai para Revisões de identidade.");

    responder("POST", URL_CONFIRMAR, duasContasConfirmar as unknown as ResultadoImportacao);
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(dialogo).toHaveTextContent(/1 vai para Revisões de identidade — nenhuma ficha é criada/);
    await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));

    const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
    const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
    expect(corpo.linhas.map((l: { dados: { matific_uuid: string } }) => l.dados.matific_uuid))
      .toEqual(["uuid-ficticio-ana", "uuid-ficticio-1"]);
    // A conta que ficou vai como instrução, sem turma escolhida: o backend não a cria.
    expect(corpo.linhas[1]).toMatchObject({
      aluno_id: null, criar_em_turma_id: null, criar_em_turma_nome: "3º Ano A", deixar_para_revisao: true });
    expect(corpo.linhas[0]).toMatchObject({ aluno_id: 1, deixar_para_revisao: false });
    // A resposta real: 1 importado (a Ana), 1 aguardando — o rodapé disse a verdade.
    expect(await screen.findByText(/1 aluno aguarda a decisão de um gestor/)).toBeInTheDocument();
    expect(screen.getByText(/quem confirmou a importação deixou esta linha para a Revisão de identidade/))
      .toBeInTheDocument();
  });

  it("o motivo 'deixada_para_revisao' tem rótulo e explicação próprios (não 'Requer revisão')", async () => {
    const analise = JSON.parse(JSON.stringify(duasContas)) as Analise;
    analise.linhas = [{ ...analise.linhas[1], correspondencia: {
      ...analise.linhas[1].correspondencia!, motivo: "deixada_para_revisao" } }];
    await previa(analise);
    const destino = screen.getByRole("combobox", { name: /^Destino de / }) as HTMLSelectElement;
    expect(screen.getByText("Deixada para a Revisão — vai para Revisões de identidade")).toBeInTheDocument();
    expect(screen.queryByText("Requer revisão")).toBeNull();
    expect(destino.value).toBe("revisao");
    expect(Array.from(destino.options).map((o) => o.textContent)).toEqual(["Deixar para a Revisão", "Ignorar"]);
  });
});

describe("Revisões de identidade: a linha deixada para a Revisão por quem importou", () => {
  it("o filtro e a orientação dão nome ao motivo 'deixada_para_revisao'", async () => {
    const u = userEvent.setup();
    const rev: RevisaoIdentidade = {
      id: 7, plataforma: "matific", formato: "resumo", id_externo: "uuid-ficticio-1",
      nome_recebido: "Crianca Ficticia Repetida", turma_informada: "3º Ano A", turma_id: 1,
      motivo: "deixada_para_revisao",
      motivo_texto: "quem confirmou a importação deixou esta linha para a Revisão de identidade: "
        + "nada foi associado nem criado (confira se a criança já tem ficha antes de criar uma)",
      candidatos: [], linhas: [{ turma_relatorio: "3º Ano A", matific_uuid: "uuid-ficticio-1",
                                 estrelas: 10, atividades: 3 }],
      contexto: { tipo: "texto", data_referencia: "2026-08-14T12:00:00" },
      origem: "importacao", importacao_id: 1, ocorrencias: 1, status: "pendente",
      aluno_escolhido_id: null, resolvida_por_id: null, resolvida_em: null, resolucao: null,
      created_at: "2026-08-14T12:00:00", atualizada_em: "2026-08-14T12:00:00",
    };
    responder("GET", (c) => c.startsWith("/escolas/1/importacoes/revisoes") && !/\/revisoes\/\d+/.test(c), [rev]);
    responder("GET", URL_TURMAS, [turmaFake()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const filtro = await screen.findByLabelText("Motivo");
    expect(within(filtro).getByRole("option", { name: "Deixada para a Revisão (1)" })).toBeInTheDocument();
    await u.click(await screen.findByRole("button", { name: "Ver revisão de Crianca Ficticia Repetida" }));
    const dialogo = await screen.findByRole("dialog", { name: "Revisão de identidade" });
    const identidade = within(dialogo).getByRole("region", { name: "Identidade recebida" });
    expect(within(identidade).getByText(
      "Quem importou preferiu decidir aqui: nada foi associado nem criado. Confira se a criança já tem "
      + "ficha antes de criar uma.")).toBeInTheDocument();
  });
});
