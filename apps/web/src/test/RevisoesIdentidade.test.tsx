import { describe, expect, it } from "vitest";

import RevisoesIdentidade from "../pages/RevisoesIdentidade";
import type { RevisaoIdentidade } from "../pages/RevisoesIdentidade";
import fonteTurmas from "../pages/Turmas.tsx?raw";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  usuarioFake,
  waitFor,
  within,
} from "./utils";

// Revisões de identidade — a tela NÃO decide nada: mostra o que o backend
// guardou e envia a escolha explícita do gestor aos endpoints já existentes.
// Cada ação é seguida de uma releitura da fila (o backend é a verdade).

const BASE = "/escolas/1/importacoes/revisoes";

function revisaoFake(over: Partial<RevisaoIdentidade> = {}): RevisaoIdentidade {
  return {
    id: 7,
    plataforma: "matific",
    formato: "resumo",
    id_externo: "00000000-0000-4000-8000-0000000000a7",
    nome_recebido: "TOBIAS D",
    turma_informada: "5 ANO B",
    turma_id: 2,
    motivo: "candidatos_multiplos",
    motivo_texto: "mais de um aluno plausível na sala",
    candidatos: [
      { aluno_id: 31, nome: "TOBIAS DE OTTOLINI SANTELLI", status: "ativo", turma: "5ºB" },
      { aluno_id: 32, nome: "TOBIAS DUARTE LIMA", status: "arquivado", turma: "5ºB" },
    ],
    linhas: [{ turma_relatorio: "5 ANO B", matific_uuid: "00000000-0000-4000-8000-0000000000a7",
               estrelas: 120, atividades: 30, pontuacao_media: 4 }],
    contexto: { tipo: "texto", data_referencia: "2026-09-20T12:00:00",
                periodo_inicio: "2026-09-01T00:00:00", periodo_fim: "2026-09-30T23:59:59" },
    origem: "sincronizacao",
    importacao_id: 90,
    ocorrencias: 3,
    status: "pendente",
    aluno_escolhido_id: null,
    resolvida_por_id: null,
    resolvida_em: null,
    resolucao: null,
    created_at: "2026-09-18T10:00:00",
    atualizada_em: "2026-09-20T12:00:00",
    ...over,
  };
}

const TURMAS = [
  turmaFake({ id: 1, nome: "5ºA", ano_escolar: "5º Ano" }),
  turmaFake({ id: 2, nome: "5ºB", ano_escolar: "5º Ano" }),
];

/** Fila EM MEMÓRIA: o GET lê dela e os POSTs a alteram — como o backend faria. */
function filaMock(inicial: RevisaoIdentidade[], turmas = TURMAS) {
  const fila = [...inicial];
  responder("GET", (c) => c.startsWith(BASE) && !/\/revisoes\/\d+/.test(c), (caminho) => {
    const situacao = new URL(`http://x${caminho}`).searchParams.get("situacao") ?? "pendente";
    return situacao === "todas" ? [...fila] : fila.filter((r) => r.status === situacao);
  });
  responder("GET", "/escolas/1/turmas", turmas);
  return {
    fila,
    resolvida(id: number, alunoId: number, extras: Partial<RevisaoIdentidade> = {}) {
      const i = fila.findIndex((r) => r.id === id);
      const rev = { ...fila[i], status: "resolvida", aluno_escolhido_id: alunoId,
                    resolvida_por_id: 1, resolvida_em: "2026-09-21T09:00:00",
                    resolucao: { acao: "associar", aluno_id: alunoId, revisao_origem: id }, ...extras };
      fila[i] = rev;
      return rev;
    },
    descartada(id: number) {
      const i = fila.findIndex((r) => r.id === id);
      fila[i] = { ...fila[i], status: "descartada", resolvida_em: "2026-09-21T09:00:00" };
      return fila[i];
    },
  };
}

function corpoDoPost(caminho: string) {
  const chamada = api.mock.calls.find(
    ([c, o]) => c === caminho && (o as RequestInit)?.method === "POST");
  expect(chamada, `POST ${caminho}`).toBeDefined();
  return JSON.parse(String((chamada![1] as RequestInit).body));
}

function contarGets(caminhoPrefixo: string) {
  return api.mock.calls.filter(
    ([c, o]) => String(c).startsWith(caminhoPrefixo) && !((o as RequestInit)?.method)).length;
}

async function abrirDetalhe(u: ReturnType<typeof userEvent.setup>, nome = "TOBIAS D") {
  await u.click(await screen.findByRole("button", { name: `Ver revisão de ${nome}` }));
  return screen.findByRole("dialog", { name: "Revisão de identidade" });
}

describe("Revisões de identidade — lista", () => {
  it("carrega a fila: mostra 'Carregando…' e depois o contador e os itens", async () => {
    filaMock([revisaoFake(), revisaoFake({ id: 8, nome_recebido: "MAURO R", plataforma: "elefante",
      id_externo: "4242", formato: "leituras", ocorrencias: 1 })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });

    expect(screen.getByText("Carregando revisões…")).toBeInTheDocument();
    expect(await screen.findByText("2 pendências")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver revisão de MAURO R" })).toBeInTheDocument();
    expect(screen.queryByText("Carregando revisões…")).toBeNull();
  });

  it("fila vazia: diz que não há pendência (contador 'Nenhuma pendência')", async () => {
    filaMock([]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });

    expect(await screen.findByText("Nenhuma revisão pendente")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma pendência")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ver revisão/ })).toBeNull();
  });

  it("cada item mostra nome, plataforma, identidade externa, turma, série, período, motivo e ocorrências", async () => {
    filaMock([revisaoFake()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });

    const item = (await screen.findByRole("button", { name: "Ver revisão de TOBIAS D" }))
      .closest("li") as HTMLElement;
    const q = within(item);
    expect(q.getByText("TOBIAS D")).toBeInTheDocument();
    expect(q.getByText("Matific")).toBeInTheDocument();
    expect(q.getByText("00000000-0000-4000-8000-0000000000a7")).toBeInTheDocument();
    expect(q.getByText("5 ANO B")).toBeInTheDocument();
    expect(q.getByText("5º Ano")).toBeInTheDocument();            // série da turma cadastrada
    expect(q.getByText("01/09/2026 a 30/09/2026")).toBeInTheDocument();
    expect(q.getByText("Motivo: mais de um aluno plausível na sala")).toBeInTheDocument();
    expect(q.getByText("3 vezes")).toBeInTheDocument();
  });

  it("sem identidade externa e sem turma, não inventa valores", async () => {
    filaMock([revisaoFake({ id_externo: null, turma_informada: null, turma_id: null,
      contexto: { tipo: "texto" }, ocorrencias: 1 })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });

    const item = (await screen.findByRole("button", { name: "Ver revisão de TOBIAS D" }))
      .closest("li") as HTMLElement;
    expect(within(item).queryByText("Identidade:")).toBeNull();
    expect(within(item).getByText("não informada")).toBeInTheDocument();
    expect(within(item).queryByText("Série:")).toBeNull();
    expect(within(item).queryByText("Período:")).toBeNull();
  });

  it("filtro de situação reusa o parâmetro do endpoint e o de plataforma filtra a lista", async () => {
    const u = userEvent.setup();
    filaMock([
      revisaoFake(),
      revisaoFake({ id: 8, nome_recebido: "MAURO R", plataforma: "elefante", id_externo: "4242" }),
      revisaoFake({ id: 9, nome_recebido: "ANA LIMA", status: "resolvida", aluno_escolhido_id: 31,
        resolvida_em: "2026-09-19T08:00:00" }),
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    expect(await screen.findByText("2 pendências")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver revisão de ANA LIMA" })).toBeNull();

    await u.selectOptions(screen.getByLabelText("Plataforma"), "elefante");
    expect(screen.queryByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeNull();
    expect(screen.getByRole("button", { name: "Ver revisão de MAURO R" })).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Plataforma"), "todas");
    await u.selectOptions(screen.getByLabelText("Situação"), "resolvida");
    expect(await screen.findByRole("button", { name: "Ver revisão de ANA LIMA" })).toBeInTheDocument();
    expect(screen.getByText("Resolvida")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`${BASE}?situacao=resolvida`, expect.anything());
    expect(screen.queryByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeNull();
    // O contador continua sendo o de PENDENTES.
    expect(screen.getByText("2 pendências")).toBeInTheDocument();
  });

  it("erro ao carregar: mensagem + 'Tentar de novo' (sem lista fantasma)", async () => {
    const u = userEvent.setup();
    responderErro("GET", BASE, 500, "Banco indisponível");
    responder("GET", "/escolas/1/turmas", TURMAS);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });

    expect(await screen.findByText("Não foi possível carregar as revisões de identidade")).toBeInTheDocument();
    expect(screen.getByText("Banco indisponível")).toBeInTheDocument();
    expect(screen.queryByText(/pendência/)).toBeNull();

    filaMock([revisaoFake()]);
    await u.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("1 pendência")).toBeInTheDocument();
  });

  it("erro ao atualizar uma lista já carregada: avisa sem apagar a lista; fora de 'Pendentes', a falha do contador também é avisada", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    expect(await screen.findByText("1 pendência")).toBeInTheDocument();

    responderErro("GET", (c) => c.startsWith(BASE), 500, "Banco indisponível");
    await u.click(screen.getByRole("button", { name: "Atualizar" }));
    expect(await screen.findByText(/Não foi possível atualizar a lista: Banco indisponível/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeInTheDocument();
    expect(screen.queryByText(/A lista foi atualizada com a situação atual/)).toBeNull();

    await u.selectOptions(screen.getByLabelText("Situação"), "resolvida");
    expect(await screen.findByText(/Não foi possível atualizar o contador de pendências: Banco indisponível/)).toBeInTheDocument();
  });

  it("403 do backend (perfil sem permissão) vira mensagem clara, não tela quebrada", async () => {
    responderErro("GET", BASE, 403, "A Secretaria acompanha os resultados da rede, mas não opera as escolas.");
    responder("GET", "/escolas/1/turmas", TURMAS);
    // Secretaria (rede vinculada): o backend nega na raiz do router (403); a tela
    // reflete a recusa. `escolaSelecionada` fixa a escola (ela entra em "Toda a Rede").
    renderComApp(<RevisoesIdentidade />, {
      rota: "/revisoes-identidade",
      usuario: usuarioFake({ cargo: "coordenador", rede_id: 5 }),
      escolaSelecionada: 1,
    });
    expect(await screen.findByText("Sem permissão para ver as revisões de identidade")).toBeInTheDocument();
    expect(screen.getByText(/Você não tem permissão para esta ação\./)).toBeInTheDocument();
  });

  it("sessão expirada (401) na lista é explicada", async () => {
    responderErro("GET", BASE, 401, "Sessão expirada. Entre novamente.");
    responder("GET", "/escolas/1/turmas", TURMAS);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    expect(await screen.findByText("Sua sessão expirou. Entre novamente para continuar.")).toBeInTheDocument();
  });
});

describe("Revisões de identidade — detalhe", () => {
  it("abre o detalhe com os três blocos: identidade recebida, candidatos e dados pendentes", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const q = within(dialogo);

    // A. identidade recebida — só o que o backend informou
    const identidade = q.getByRole("region", { name: "Identidade recebida" });
    expect(within(identidade).getByText("TOBIAS D")).toBeInTheDocument();
    expect(within(identidade).getByText("UUID do Matific:")).toBeInTheDocument();
    expect(within(identidade).getByText("00000000-0000-4000-8000-0000000000a7")).toBeInTheDocument();
    expect(within(identidade).getByText("5 ANO B")).toBeInTheDocument();
    expect(within(identidade).getByText("5º Ano")).toBeInTheDocument();
    expect(within(identidade).getByText("01/09/2026 a 30/09/2026")).toBeInTheDocument();
    expect(within(identidade).getByText("Resumo do aluno")).toBeInTheDocument();
    expect(within(identidade).getByText("Sincronização automática")).toBeInTheDocument();
    expect(within(identidade).getByText("Motivo: mais de um aluno plausível na sala")).toBeInTheDocument();
    expect(within(identidade).getByText(/Mais de um aluno pode ser o dono destes dados/)).toBeInTheDocument();

    // B. candidatos — nome, turma, série, situação da ficha e o botão de vincular
    const candidatos = q.getByRole("region", { name: "Candidatos encontrados" });
    expect(within(candidatos).getByText("TOBIAS DE OTTOLINI SANTELLI")).toBeInTheDocument();
    expect(within(candidatos).getAllByText("5ºB · 5º Ano")).toHaveLength(2);
    expect(within(candidatos).getByText("Ficha ativa")).toBeInTheDocument();
    expect(within(candidatos).getByText("Ficha arquivada")).toBeInTheDocument();
    expect(within(candidatos).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" })).toBeInTheDocument();
    expect(within(candidatos).getByRole("button", { name: "Vincular este aluno: TOBIAS DUARTE LIMA" })).toBeInTheDocument();

    // C. dados pendentes — legíveis, sem as chaves técnicas
    const dados = q.getByRole("region", { name: "Dados que aguardam associação" });
    expect(within(dados).getByText("Estrelas")).toBeInTheDocument();
    expect(within(dados).getByText("120")).toBeInTheDocument();
    expect(within(dados).getByText("Atividades")).toBeInTheDocument();
    expect(within(dados).getByText("Pontuação média")).toBeInTheDocument();
    expect(within(dados).queryByText(/matific_uuid|turma_relatorio/)).toBeNull();
    // Nada foi chamado só por abrir o detalhe.
    expect(api.mock.calls.some(([, o]) => (o as RequestInit)?.method === "POST")).toBe(false);
  });

  // Motivos novos da sincronização (frente B): o texto do motivo vem do backend;
  // a tela diz ao gestor o que decidir.
  it.each([
    ["nome_incompleto", "a plataforma mandou só o nome abreviado", /Não crie ficha com o nome abreviado/],
    // D10: a conta efetiva em outra escola só é vinculada aqui pelo Admin Global.
    ["identidade_de_outra_escola",
      "a conta da plataforma já está vinculada a um aluno de OUTRA escola do Constela",
      /só o Admin Global vincula a conta à ficha dela aqui/],
    // D11 (item E): a importação manual não encerra a pendência; decide-se aqui.
    ["identidade_de_outra_escola",
      "a conta da plataforma já está vinculada a um aluno de OUTRA escola do Constela",
      /importação manual não encerra esta pendência: a decisão é feita aqui/],
    ["id_externo_duplicado", "o mesmo identificador da plataforma veio em mais de uma linha",
      /só o vínculo é gravado agora/],
    ["turma_arquivada", "a turma do relatório está arquivada no cadastro",
      /reative-a em Turmas: ligue “Mostrar arquivadas e de outros anos” e use “Reativar”/],
    ["turma_fora_do_ano_letivo", "a turma escolhida não é do ano letivo ativo da escola",
      /numa turma do ano letivo atual/],
    // Duas contas sem vínculo, mesmo nome, nenhuma ficha (nada foi criado).
    ["contas_repetidas_no_relatorio", "duas contas diferentes da plataforma vieram no mesmo relatório",
      /se são duas crianças, crie uma ficha para cada/],
    // Política "bloquear": a orientação diz o que fazer com os controles da gaveta.
    ["criacao_bloqueada_por_politica",
      "nenhum aluno corresponde e a política desta escola não deixa a plataforma criar ficha",
      /use “Criar novo aluno” só depois de confirmar com a secretaria da escola/],
  ])("motivo %s mostra o texto do backend e a orientação", async (motivo, texto, orientacao) => {
    const u = userEvent.setup();
    filaMock([revisaoFake({ motivo, motivo_texto: texto })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const identidade = within(dialogo).getByRole("region", { name: "Identidade recebida" });
    expect(within(identidade).getByText(`Motivo: ${texto}`)).toBeInTheDocument();
    expect(within(identidade).getByText(orientacao)).toBeInTheDocument();
  });

  // Criação barrada pela política: o motivo (texto do backend) já diz que nada
  // corresponde e que a matrícula vem da Lista Piloto. A orientação não repete isso
  // e é coerente com a gaveta: antes mandava "matricular pela Lista Piloto ou em
  // Alunos e depois vincular aqui" logo acima do botão "Criar novo aluno".
  it("criação barrada pela política: orientação curta, sem repetir o motivo, com os botões da gaveta", async () => {
    const u = userEvent.setup();
    const motivoTexto = "nenhum aluno corresponde e a política desta escola não deixa a plataforma "
      + "criar ficha — nem pela sincronização nem pela importação de relatório (a matrícula vem da "
      + "Lista Piloto)";
    filaMock([revisaoFake({ motivo: "criacao_bloqueada_por_politica", motivo_texto: motivoTexto,
      candidatos: [] })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const identidade = within(dialogo).getByRole("region", { name: "Identidade recebida" });
    expect(within(identidade).getByText(`Motivo: ${motivoTexto}`)).toBeInTheDocument();
    const orientacao = within(identidade).getByText(/Criar novo aluno/).textContent ?? "";
    expect(orientacao).toBe(
      "Se a criança já tem ficha, busque-a em “Buscar outro aluno da escola” e vincule. Se não "
      + "tem, use “Criar novo aluno” só depois de confirmar com a secretaria da escola que ela "
      + "está matriculada.");
    // Não repete o motivo nem manda matricular fora daqui.
    expect(orientacao).not.toMatch(/Lista Piloto|política|Nenhuma ficha corresponde|matricule-a/);
    // Cada controle citado está na gaveta, com esse nome.
    expect(within(dialogo).getByRole("button", { name: /Buscar outro aluno da escola/ })).toBeInTheDocument();
    const criar = within(dialogo).getByRole("region", { name: "Criar novo aluno" });
    expect(within(criar).getByRole("button", { name: "Criar novo aluno" })).toBeInTheDocument();
  });

  it("turma arquivada: a orientação cita o rótulo que a tela Turmas de fato mostra", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake({ motivo: "turma_arquivada", motivo_texto: "a turma do relatório está arquivada" })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const orientacao = within(dialogo).getByText(/reative-a em Turmas/).textContent ?? "";
    const rotulo = /ligue “([^”]+)”/.exec(orientacao)?.[1];
    expect(rotulo).toBe("Mostrar arquivadas e de outros anos");
    // O mesmo texto visível ao lado do interruptor em Turmas.tsx (o nome acessível do
    // interruptor é mais longo; quem lê a orientação procura o que está escrito).
    expect(fonteTurmas).toMatch(new RegExp(`>\\s*${rotulo}\\s*<`));
  });

  it("leituras (livro a livro) aparecem como tabela", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake({ plataforma: "elefante", formato: "leituras", id_externo: "4242",
      nome_recebido: "HELOISA DORVANTE GRASSETTI", motivo: "correspondencia_insegura",
      motivo_texto: "nome parecido, mas a correspondência não é segura",
      linhas: [
        { livro: "O Pequeno Príncipe", nivel: "D", data: "2026-09-02T10:00:00", elefante_student_id: "4242" },
        { livro: "A Casa Amarela", nivel: "E", data: "2026-09-05T10:00:00", elefante_student_id: "4242" },
      ] })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u, "HELOISA DORVANTE GRASSETTI");
    const dados = within(dialogo).getByRole("region", { name: "Dados que aguardam associação" });
    expect(within(dados).getByText("2 leituras")).toBeInTheDocument();
    expect(within(dados).getByRole("cell", { name: "O Pequeno Príncipe" })).toBeInTheDocument();
    expect(within(dados).getByRole("cell", { name: "02/09/2026" })).toBeInTheDocument();
    expect(within(dialogo).getByText("studentId do Elefante:")).toBeInTheDocument();
  });

  it("vincular a aluno existente: confirmação explícita → POST {aluno_id} → feedback → some da fila", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake(), revisaoFake({ id: 8, nome_recebido: "MAURO R" })]);
    responder("POST", `${BASE}/7/resolver`, (_c, o) => {
      const corpo = JSON.parse(String((o as RequestInit).body));
      const rev = mock.resolvida(7, corpo.aluno_id);
      return { revisao: rev, aluno_id: corpo.aluno_id, revisoes_resolvidas: [7], importacoes: [91],
               avisos: [] };
    });
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    expect(await screen.findByText("2 pendências")).toBeInTheDocument();
    const dialogo = await abrirDetalhe(u);
    const getsAntes = contarGets(BASE);

    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    // Nada enviado antes da confirmação.
    expect(api.mock.calls.some(([, o]) => (o as RequestInit)?.method === "POST")).toBe(false);
    const confirmacao = await screen.findByRole("heading", { name: "Vincular a este aluno?" });
    const modal = confirmacao.parentElement as HTMLElement;
    expect(within(modal).getByText(/Você está vinculando esta identidade ao aluno/)).toBeInTheDocument();
    expect(within(modal).getByText("TOBIAS DE OTTOLINI SANTELLI")).toBeInTheDocument();
    expect(within(modal).getByText(/Os dados pendentes .* serão aplicados a esta ficha/)).toBeInTheDocument();
    expect(within(modal).getByText(/Esta ação ficará registrada na auditoria/)).toBeInTheDocument();

    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));

    expect(corpoDoPost(`${BASE}/7/resolver`)).toEqual({ aluno_id: 31 });
    expect(await screen.findByText(/Revisão resolvida: os dados de “TOBIAS D” foram vinculados a TOBIAS DE OTTOLINI SANTELLI\./)).toBeInTheDocument();
    // Painel fechou, fila relida do backend (sem reload), contador e lista atualizados.
    expect(screen.queryByRole("dialog", { name: "Revisão de identidade" })).toBeNull();
    await waitFor(() => expect(contarGets(BASE)).toBe(getsAntes + 1));   // 1 releitura, sem duplicar
    expect(await screen.findByText("1 pendência")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeNull();
    expect(screen.getByRole("button", { name: "Ver revisão de MAURO R" })).toBeInTheDocument();
  });

  it("vincular a ficha inativa avisa que o aluno só volta ao ranking quando reativado; irmãs resolvidas e avisos do backend aparecem", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake()]);
    responder("POST", `${BASE}/7/resolver`, () => ({
      revisao: mock.resolvida(7, 32), aluno_id: 32, revisoes_resolvidas: [7, 12], importacoes: [91, 92],
      avisos: ["TOBIAS DUARTE LIMA está com a ficha “arquivado”: os dados foram aplicados, mas ele só volta ao ranking quando for reativado em Alunos."],
    }));
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DUARTE LIMA" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    expect(within(modal).getByText(/A ficha está “Ficha arquivada”/)).toBeInTheDocument();
    expect(within(modal).getByText(/A conta da plataforma \(UUID do Matific/)).toBeInTheDocument();
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));

    expect(await screen.findByText(/1 outra revisão da mesma identidade foram resolvidas junto\./)).toBeInTheDocument();
    expect(screen.getByText(/só volta ao ranking quando for reativado em Alunos/)).toBeInTheDocument();
  });

  it("criar novo aluno: só com turma escolhida, com confirmação → POST {criar_em_turma_id}", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake({ candidatos: [], motivo: "turma_ambigua",
      motivo_texto: "mais de uma turma cadastrada corresponde à sala do relatório" })]);
    responder("POST", `${BASE}/7/resolver`, (_c, o) => {
      const corpo = JSON.parse(String((o as RequestInit).body));
      const rev = mock.resolvida(7, 99, { resolucao: { acao: "criar", aluno_id: 99 } });
      return { revisao: rev, aluno_id: 99, revisoes_resolvidas: [7], importacoes: [91], avisos: [],
               turma: corpo.criar_em_turma_id };
    });
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const q = within(dialogo);
    expect(q.getByText("Nenhum aluno cadastrado corresponde a esta linha.")).toBeInTheDocument();

    // Sem turma escolhida o botão fica bloqueado — nunca "a primeira turma".
    const criar = q.getByRole("button", { name: "Criar novo aluno" });
    expect(criar).toBeDisabled();
    await u.selectOptions(q.getByLabelText("Turma da ficha nova"), "2");
    expect(q.getByText("5ºB · 5º Ano")).toBeInTheDocument();       // o que será usado
    expect(criar).toBeEnabled();
    await u.click(criar);
    expect(api.mock.calls.some(([, o]) => (o as RequestInit)?.method === "POST")).toBe(false);

    const modal = (await screen.findByRole("heading", { name: "Criar novo aluno?" })).parentElement as HTMLElement;
    expect(within(modal).getByText(/Uma ficha nova será criada para/)).toBeInTheDocument();
    expect(within(modal).getByText("5ºB")).toBeInTheDocument();
    await u.click(within(modal).getByRole("button", { name: "Confirmar criação" }));

    expect(corpoDoPost(`${BASE}/7/resolver`)).toEqual({ criar_em_turma_id: 2 });
    expect(await screen.findByText(/Revisão resolvida: uma ficha nova \(5ºB\) foi criada para “TOBIAS D” e recebeu os dados\./)).toBeInTheDocument();
    expect(await screen.findByText("Nenhuma pendência")).toBeInTheDocument();
  });

  it("criar novo aluno: promete o nome que a ficha recebe (sem a turma escrita no fim), turma a turma", async () => {
    // A10: o /resolver grava o nome sem o sufixo de turma ("5B") quando ele é o da sala
    // escolhida (ou o da linha). O backend manda o nome padrão e, por turma, onde ele muda;
    // a tela mostra o da turma escolhida — o mesmo que será gravado.
    const u = userEvent.setup();
    filaMock([revisaoFake({
      candidatos: [], motivo: "turma_ambigua", nome_recebido: "ZEFA QUARESMA LIMA 5B",
      motivo_texto: "mais de uma turma cadastrada corresponde à sala do relatório",
      nome_ficha_nova: "ZEFA QUARESMA LIMA 5B",
      nome_ficha_nova_por_turma: { "2": "ZEFA QUARESMA LIMA" },
    })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u, "ZEFA QUARESMA LIMA 5B");
    const q = within(dialogo);
    expect(q.getByText(/sem a turma, quando ela vem escrita no fim do nome/)).toBeInTheDocument();

    const nomeDaFicha = () => q.getByText("Nome:").nextElementSibling?.textContent;
    await u.selectOptions(q.getByLabelText("Turma da ficha nova"), "1");
    expect(nomeDaFicha()).toBe("ZEFA QUARESMA LIMA 5B");      // na 5ºA, o "5B" fica
    await u.selectOptions(q.getByLabelText("Turma da ficha nova"), "2");
    expect(nomeDaFicha()).toBe("ZEFA QUARESMA LIMA");         // na 5ºB, sai
    await u.click(q.getByRole("button", { name: "Criar novo aluno" }));
    const modal = (await screen.findByRole("heading", { name: "Criar novo aluno?" })).parentElement as HTMLElement;
    expect(modal.textContent).toContain("Uma ficha nova será criada para ZEFA QUARESMA LIMA na turma 5ºB");
    expect(modal.textContent).not.toContain("ZEFA QUARESMA LIMA 5B");
  });

  it("criar novo aluno: servidor antigo (sem o nome previsto) mostra o nome recebido", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake({ candidatos: [] })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const q = within(await abrirDetalhe(u));
    await u.selectOptions(q.getByLabelText("Turma da ficha nova"), "2");
    await u.click(q.getByRole("button", { name: "Criar novo aluno" }));
    const modal = (await screen.findByRole("heading", { name: "Criar novo aluno?" })).parentElement as HTMLElement;
    expect(modal.textContent).toContain("Uma ficha nova será criada para TOBIAS D na turma 5ºB");
  });

  it("sem turma cadastrada, a criação fica bloqueada com explicação", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake({ candidatos: [] })], []);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    expect(await within(dialogo).findByText(/Não há turma ativa cadastrada no ano letivo/)).toBeInTheDocument();
    expect(within(dialogo).queryByLabelText("Turma da ficha nova")).toBeNull();
    expect(within(dialogo).getByRole("button", { name: "Criar novo aluno" })).toBeDisabled();
  });

  it("descartar: confirmação explícita → POST /descartar → feedback → some da fila", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake()]);
    responder("POST", `${BASE}/7/descartar`, () => mock.descartada(7));
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);

    await u.click(within(dialogo).getByRole("button", { name: "Descartar revisão" }));
    const modal = (await screen.findByRole("heading", { name: "Descartar esta revisão?" })).parentElement as HTMLElement;
    expect(within(modal).getByText(/Os dados desta revisão não serão associados a nenhum aluno\. A decisão ficará registrada na auditoria\./)).toBeInTheDocument();
    await u.type(within(modal).getByLabelText("Justificativa (opcional)"), "conta de teste");
    await u.click(within(modal).getByRole("button", { name: "Confirmar descarte" }));

    expect(corpoDoPost(`${BASE}/7/descartar`)).toEqual({ motivo: "conta de teste" });
    expect(await screen.findByText(/Revisão descartada: os dados de “TOBIAS D” não foram associados a nenhum aluno\./)).toBeInTheDocument();
    expect(await screen.findByText("Nenhuma pendência")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Revisão de identidade" })).toBeNull();
  });

  it("erro da API ao vincular: mostra o erro, NÃO mostra sucesso e a revisão continua na fila", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    responderErro("POST", `${BASE}/7/resolver`, 500, "Falha ao aplicar os dados.");
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));

    expect(await within(modal).findByRole("alert")).toHaveTextContent("Falha ao aplicar os dados.");
    expect(screen.queryByText(/Revisão resolvida/)).toBeNull();
    // Continua no painel, com a pendência viva na fila.
    expect(screen.getByRole("dialog", { name: "Revisão de identidade" })).toBeInTheDocument();
    expect(screen.getByText("1 pendência")).toBeInTheDocument();
  });

  it("403 ao resolver reflete a recusa do backend; 401 explica a sessão expirada", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    responderErro("POST", `${BASE}/7/resolver`, 403, "Você não possui permissão para esta ação.");
    responderErro("POST", `${BASE}/7/descartar`, 401, "Sessão expirada. Entre novamente.");
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);

    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    let modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));
    expect(await within(modal).findByRole("alert")).toHaveTextContent(
      "Você não tem permissão para esta ação. Você não possui permissão para esta ação.");
    await u.click(within(modal).getByRole("button", { name: "Cancelar" }));

    await u.click(within(dialogo).getByRole("button", { name: "Descartar revisão" }));
    modal = (await screen.findByRole("heading", { name: "Descartar esta revisão?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar descarte" }));
    expect(await within(modal).findByRole("alert")).toHaveTextContent(
      "Sua sessão expirou. Entre novamente para continuar.");
    expect(screen.queryByText(/Revisão descartada/)).toBeNull();
  });

  it("revisão já resolvida por outra pessoa (409): fecha o painel, avisa e relê a fila", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake()]);
    responderErro("POST", `${BASE}/7/resolver`, 409, "Esta revisão já está resolvida.");
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    mock.resolvida(7, 31);                         // outra pessoa resolveu no servidor
    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));

    expect(await screen.findByText(/Esta revisão já está resolvida\. A lista foi atualizada com a situação atual\./)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Revisão de identidade" })).toBeNull();
    expect(await screen.findByText("Nenhuma pendência")).toBeInTheDocument();
    expect(screen.queryByText(/Revisão resolvida/)).toBeNull();
  });

  it("candidato que deixou de existir (400 do backend): erro no modal com orientação, sem sucesso", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    responderErro("POST", `${BASE}/7/resolver`, 400, "O aluno escolhido não pertence a esta escola.");
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));
    expect(await within(modal).findByRole("alert")).toHaveTextContent(
      "O aluno escolhido não pertence a esta escola. Esta ficha pode ter sido fundida, excluída ou movida");
    expect(screen.queryByText(/Revisão resolvida/)).toBeNull();
  });

  it("buscar outro aluno da escola: só lista o que o gestor pesquisar e vincula com a mesma confirmação", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake({ candidatos: [] })]);
    responder("GET", (c) => c.startsWith("/escolas/1/alunos?busca="), (caminho) => {
      const busca = new URL(`http://x${caminho}`).searchParams.get("busca");
      return { total: 1, pagina: 1, por_pagina: 20, itens: busca === "tobias"
        ? [{ id: 31, nome: "TOBIAS DE OTTOLINI SANTELLI", foto_url: null, numero_chamada: 4,
             status: "ativo", turma: "5ºA", ano_escolar: "5º Ano" }] : [] };
    });
    responder("POST", `${BASE}/7/resolver`, (_c, o) => {
      const corpo = JSON.parse(String((o as RequestInit).body));
      return { revisao: mock.resolvida(7, corpo.aluno_id), aluno_id: corpo.aluno_id,
               revisoes_resolvidas: [7], importacoes: [91], avisos: [] };
    });
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const q = within(dialogo);
    expect(q.queryByLabelText("Buscar aluno pelo nome")).toBeNull();     // nada sugerido sozinho
    await u.click(q.getByRole("button", { name: /Buscar outro aluno da escola/ }));
    await u.type(q.getByLabelText("Buscar aluno pelo nome"), "tobias");
    await u.click(q.getByRole("button", { name: "Buscar" }));
    const resultado = await q.findByRole("list", { name: "Resultado da busca" });
    expect(within(resultado).getByText("TOBIAS DE OTTOLINI SANTELLI")).toBeInTheDocument();
    expect(within(resultado).getByText("5ºA · 5º Ano")).toBeInTheDocument();

    await u.click(within(resultado).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));
    expect(corpoDoPost(`${BASE}/7/resolver`)).toEqual({ aluno_id: 31 });
    expect(await screen.findByText(/foram vinculados a TOBIAS DE OTTOLINI SANTELLI/)).toBeInTheDocument();
  });

  it("revisão resolvida/descartada abre só para leitura: sem botões de ação e com a decisão tomada", async () => {
    const u = userEvent.setup();
    filaMock([
      revisaoFake({ status: "resolvida", aluno_escolhido_id: 31, resolvida_por_id: 1,
        resolvida_em: "2026-09-21T09:00:00", resolucao: { acao: "associar", aluno_id: 31, revisao_origem: 7 } }),
      revisaoFake({ id: 8, nome_recebido: "MAURO R", status: "descartada", resolvida_por_id: 1,
        resolvida_em: "2026-09-21T09:30:00", resolucao: { acao: "descartar", motivo: "conta de teste" } }),
      revisaoFake({ id: 9, nome_recebido: "KAUA MENDES", candidatos: [], status: "resolvida",
        aluno_escolhido_id: 99, resolvida_por_id: 1, resolvida_em: "2026-09-21T10:00:00",
        resolucao: { acao: "criar", aluno_id: 99, revisao_origem: 9 } }),
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await u.selectOptions(await screen.findByLabelText("Situação"), "todas");

    const dialogo = await abrirDetalhe(u);
    expect(within(dialogo).getByText(/^Resolvida em/)).toBeInTheDocument();
    expect(within(dialogo).getByText(/Vinculada: TOBIAS DE OTTOLINI SANTELLI/)).toBeInTheDocument();
    expect(within(dialogo).getByRole("link", { name: "abrir ficha" })).toHaveAttribute("href", "/alunos/31");
    expect(within(dialogo).queryByRole("button", { name: /Vincular este aluno/ })).toBeNull();
    expect(within(dialogo).queryByRole("button", { name: "Criar novo aluno" })).toBeNull();
    expect(within(dialogo).queryByRole("button", { name: "Descartar revisão" })).toBeNull();
    await u.click(within(dialogo).getByRole("button", { name: "Fechar" }));

    const outra = await abrirDetalhe(u, "MAURO R");
    expect(within(outra).getByText(/^Descartada em/)).toBeInTheDocument();
    expect(within(outra).getByText("Justificativa: conta de teste")).toBeInTheDocument();
    await u.click(within(outra).getByRole("button", { name: "Fechar" }));

    // Resolvida CRIANDO ficha nova: o aluno não está entre os candidatos.
    const criada = await abrirDetalhe(u, "KAUA MENDES");
    expect(within(criada).getByText(/Uma ficha nova foi criada \(aluno nº 99\)/)).toBeInTheDocument();
    expect(within(criada).getByRole("link", { name: "abrir ficha" })).toHaveAttribute("href", "/alunos/99");
  });

  it("decisão do Admin Global fora da fila (D10) aparece como resolvida, com a origem legível", async () => {
    // A reativação de ficha excluída / conta aposentada de uma conta que vale em
    // outra escola grava a memória da decisão como revisão resolvida (origem
    // "confirmacao_admin", sem candidatos nem linhas): a tela não mostra o código cru.
    const u = userEvent.setup();
    filaMock([
      revisaoFake({ origem: "confirmacao_admin", motivo: "identidade_de_outra_escola",
        motivo_texto: "conta já vinculada a um aluno de outra escola", candidatos: [], linhas: [],
        contexto: {}, turma_informada: null, ocorrencias: 1, status: "resolvida",
        aluno_escolhido_id: 31, resolvida_por_id: 1, resolvida_em: "2026-10-24T09:00:00",
        resolucao: { acao: "associar", aluno_id: 31, automatica: false, resolvida_na: "reativar" } }),
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await u.selectOptions(await screen.findByLabelText("Situação"), "todas");

    const dialogo = await abrirDetalhe(u);
    expect(within(dialogo).getByText("Confirmação do Admin Global (reativação)")).toBeInTheDocument();
    expect(within(dialogo).queryByText("confirmacao_admin")).toBeNull();
    expect(within(dialogo).getByText(/^Resolvida em/)).toBeInTheDocument();
    expect(within(dialogo).getByRole("link", { name: "abrir ficha" })).toHaveAttribute("href", "/alunos/31");
  });

  it("revisão encerrada pelo sistema diz 'Encerrada automaticamente' e a regra; a humana segue 'Resolvida'", async () => {
    const u = userEvent.setup();
    filaMock([
      revisaoFake({ status: "resolvida", aluno_escolhido_id: 31, resolvida_por_id: null,
        resolvida_em: "2026-10-11T09:00:00",
        resolucao: { acao: "associar", aluno_id: 31, automatica: true, via: "abreviacao",
          regra: "nome abreviado, candidato único na sala" } }),
      revisaoFake({ id: 8, nome_recebido: "MAURO R", status: "resolvida", aluno_escolhido_id: 31,
        resolvida_por_id: 1, resolvida_em: "2026-10-11T09:30:00",
        resolucao: { acao: "associar", aluno_id: 31, automatica: false, via: "explicito",
          regra: "ficha fixada por quem confirmou a importação (prévia aceita ou alternativa escolhida)" } }),
      revisaoFake({ id: 9, nome_recebido: "KAUA MENDES", status: "resolvida", aluno_escolhido_id: 31,
        resolvida_por_id: null, resolvida_em: "2026-10-11T10:00:00",
        resolucao: { acao: "associar", aluno_id: 31, automatica: true } }),
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await u.selectOptions(await screen.findByLabelText("Situação"), "todas");

    const automatica = await abrirDetalhe(u);
    expect(within(automatica).getByText(/^Encerrada automaticamente em/)).toBeInTheDocument();
    expect(within(automatica).getByText("Regra: nome abreviado, candidato único na sala")).toBeInTheDocument();
    expect(within(automatica).queryByText(/^Resolvida em/)).toBeNull();
    expect(within(automatica).getByText(/Vinculada: TOBIAS DE OTTOLINI SANTELLI/)).toBeInTheDocument();
    await u.click(within(automatica).getByRole("button", { name: "Fechar" }));

    // Decisão de uma pessoa (automatica: false): continua "Resolvida", sem a regra.
    const humana = await abrirDetalhe(u, "MAURO R");
    expect(within(humana).getByText(/^Resolvida em/)).toBeInTheDocument();
    expect(within(humana).queryByText(/^Regra:/)).toBeNull();
    await u.click(within(humana).getByRole("button", { name: "Fechar" }));

    // Automática sem regra gravada: o título muda, a linha da regra não aparece.
    const semRegra = await abrirDetalhe(u, "KAUA MENDES");
    expect(within(semRegra).getByText(/^Encerrada automaticamente em/)).toBeInTheDocument();
    expect(within(semRegra).queryByText(/^Regra:/)).toBeNull();
  });

  it("Esc numa confirmação fecha só a confirmação (a revisão e o texto digitado ficam)", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    await u.click(within(dialogo).getByRole("button", { name: "Descartar revisão" }));
    const modal = (await screen.findByRole("heading", { name: "Descartar esta revisão?" })).parentElement as HTMLElement;
    await u.type(within(modal).getByLabelText("Justificativa (opcional)"), "conta de teste");
    await u.keyboard("{Escape}");
    expect(screen.queryByRole("heading", { name: "Descartar esta revisão?" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Revisão de identidade" })).toBeInTheDocument();
    // Reabrir mostra a justificativa preservada; Esc SEM confirmação aberta fecha o painel.
    await u.click(within(dialogo).getByRole("button", { name: "Descartar revisão" }));
    expect(await screen.findByLabelText("Justificativa (opcional)")).toHaveValue("conta de teste");
    await u.keyboard("{Escape}");
    await u.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Revisão de identidade" })).toBeNull();
    expect(api.mock.calls.some(([, o]) => (o as RequestInit)?.method === "POST")).toBe(false);
  });

  it("com a requisição EM VOO: botão bloqueado (sem duplo clique) e o painel não fecha por Esc/fundo", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake()]);
    let liberar: (() => void) | null = null;
    responder("POST", `${BASE}/7/resolver`, () => new Promise((resolve) => {
      liberar = () => resolve({ revisao: mock.resolvida(7, 31), aluno_id: 31,
                                revisoes_resolvidas: [7], importacoes: [91], avisos: [] });
    }));
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    const confirmar = within(modal).getByRole("button", { name: "Confirmar vínculo" });
    await u.click(confirmar);

    expect(await within(modal).findByRole("button", { name: "Aplicando…" })).toBeDisabled();
    await u.click(within(modal).getByRole("button", { name: "Aplicando…" }));          // duplo clique
    await u.keyboard("{Escape}");
    await u.click(screen.getByRole("button", { name: "Fechar painel" }));
    expect(screen.getByRole("dialog", { name: "Revisão de identidade" })).toBeInTheDocument();
    expect(api.mock.calls.filter(([, o]) => (o as RequestInit)?.method === "POST")).toHaveLength(1);

    liberar!();
    expect(await screen.findByText(/foram vinculados a TOBIAS DE OTTOLINI SANTELLI/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Revisão de identidade" })).toBeNull();
  });

  it("resolver com o filtro 'Todas' relê as duas listas e o item passa a 'Resolvida'", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake(), revisaoFake({ id: 8, nome_recebido: "MAURO R" })]);
    responder("POST", `${BASE}/7/resolver`, () => ({
      revisao: mock.resolvida(7, 31), aluno_id: 31, revisoes_resolvidas: [7], importacoes: [91], avisos: [] }));
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await u.selectOptions(await screen.findByLabelText("Situação"), "todas");
    await screen.findByRole("button", { name: "Ver revisão de MAURO R" });
    const getsAntes = contarGets(BASE);

    const dialogo = await abrirDetalhe(u);
    await u.click(within(dialogo).getByRole("button", { name: "Vincular este aluno: TOBIAS DE OTTOLINI SANTELLI" }));
    const modal = (await screen.findByRole("heading", { name: "Vincular a este aluno?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar vínculo" }));

    expect(await screen.findByText("1 pendência")).toBeInTheDocument();
    await waitFor(() => expect(contarGets(BASE)).toBe(getsAntes + 2));   // pendentes + todas
    const item = screen.getByRole("button", { name: "Ver revisão de TOBIAS D" }).closest("li") as HTMLElement;
    expect(within(item).getByText("Resolvida")).toBeInTheDocument();
  });

  it("descartar uma revisão que já foi resolvida (409): avisa, fecha e relê a fila", async () => {
    const u = userEvent.setup();
    const mock = filaMock([revisaoFake()]);
    responderErro("POST", `${BASE}/7/descartar`, 409, "Esta revisão já está resolvida.");
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    mock.resolvida(7, 31);
    await u.click(within(dialogo).getByRole("button", { name: "Descartar revisão" }));
    const modal = (await screen.findByRole("heading", { name: "Descartar esta revisão?" })).parentElement as HTMLElement;
    await u.click(within(modal).getByRole("button", { name: "Confirmar descarte" }));
    expect(await screen.findByText(/Esta revisão já está resolvida\. A lista foi atualizada com a situação atual\./)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Revisão de identidade" })).toBeNull();
    expect(await screen.findByText("Nenhuma pendência")).toBeInTheDocument();
  });
});

// Duas contas da MESMA plataforma na MESMA ficha: aqui vincular não é só dizer
// de quem é a linha — é escolher qual conta vai alimentar o aluno. A tela avisa
// ANTES do clique, sem tirar do gestor a decisão.
describe("Revisões de identidade — aviso de duas contas na mesma ficha", () => {
  const duasContas = () =>
    revisaoFake({
      motivo: "outra_identidade_na_plataforma",
      motivo_texto: "o aluno encontrado já tem outra conta nesta plataforma",
      candidatos: [
        { aluno_id: 31, nome: "ARIELLE CRISTINA TESTELLI DE AMARO", status: "ativo", turma: "5ºB" },
      ],
    });

  it("explica a consequência, o que confirmar e que volume não é prova", async () => {
    const u = userEvent.setup();
    filaMock([duasContas()]);
    // A ficha JÁ tem outra conta em uso — só então o aviso vale (sem conta nenhuma, o
    // mesmo motivo nasce da outra conta no relatório ou numa pendência).
    responder("GET", "/escolas/1/importacoes/identidades/matific/aluno/31", [
      { id: 1, id_externo: "conta-da-ficha", status: "efetiva", created_at: "2026-04-01T10:00:00",
        aposentada_em: null, aposentada_por: null, motivo_aposentadoria: null },
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const aviso = await within(dialogo).findByRole("note", {
      name: "Atenção: duas contas da mesma plataforma",
    });

    expect(within(aviso).getByText(/esta ficha tem duas contas no Matific/i)).toBeInTheDocument();
    // 1. a consequência de vincular
    expect(within(aviso).getByText(/deixam de aparecer no retrato/i)).toBeInTheDocument();
    // 2. o que o gestor precisa confirmar, e onde
    expect(within(aviso).getByText(/pelo nome completo e pelo login/i)).toBeInTheDocument();
    // 3. volume não é identidade
    expect(within(aviso).getByText(/Ter mais atividades ou mais estrelas/i)).toBeInTheDocument();
    expect(within(aviso).getByText(/prova que a conta é a\s*certa/i)).toBeInTheDocument();
    // 4. na dúvida, deixar pendente
    expect(within(aviso).getByText(/deixe pendente/i)).toBeInTheDocument();
  });

  it("não bloqueia a decisão: o botão de vincular continua disponível", async () => {
    const u = userEvent.setup();
    filaMock([duasContas()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    expect(
      within(dialogo).getByRole("button", {
        name: "Vincular este aluno: ARIELLE CRISTINA TESTELLI DE AMARO",
      }),
    ).toBeEnabled();
  });

  it("o aviso é só deste motivo — outras revisões não o mostram", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake()]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    expect(
      within(dialogo).queryByRole("note", { name: "Atenção: duas contas da mesma plataforma" }),
    ).toBeNull();
  });

  it("revisão já resolvida não mostra o aviso (não há mais o que decidir)", async () => {
    const u = userEvent.setup();
    filaMock([{ ...duasContas(), status: "resolvida", aluno_escolhido_id: 31,
                resolvida_por_id: 1, resolvida_em: "2026-09-25T09:00:00",
                resolucao: { acao: "associar", aluno_id: 31, revisao_origem: 7 } }]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await u.selectOptions(await screen.findByLabelText("Situação"), "todas");
    const dialogo = await abrirDetalhe(u);
    expect(
      within(dialogo).queryByRole("note", { name: "Atenção: duas contas da mesma plataforma" }),
    ).toBeNull();
  });
});

// Conta duplicada na MESMA plataforma: a tela mostra as duas contas, deixa
// escolher qual vale e diz, sem rodeio, que aposentar é decisão do Constela —
// a conta continua existindo no Matific.
describe("Revisões de identidade — contas do aluno na plataforma", () => {
  const CONTAS = "/escolas/1/importacoes/identidades/matific/aluno/31";

  const duasContas = () =>
    revisaoFake({
      motivo: "outra_identidade_na_plataforma",
      motivo_texto: "o aluno encontrado já tem outra conta nesta plataforma",
      candidatos: [
        { aluno_id: 31, nome: "ARIELLE CRISTINA TESTELLI DE AMARO", status: "ativo", turma: "5ºB" },
      ],
    });

  function contasMock(lista: unknown[]) {
    responder("GET", CONTAS, lista);
  }

  it("lista as duas contas com o estado de cada uma e o aviso sobre o Matific", async () => {
    const u = userEvent.setup();
    filaMock([duasContas()]);
    contasMock([
      { id: 1, id_externo: "conta-A", status: "efetiva", created_at: "2026-04-01T10:00:00",
        aposentada_em: null, aposentada_por: null, motivo_aposentadoria: null },
      { id: 2, id_externo: "conta-B", status: "aposentada", created_at: "2026-05-01T10:00:00",
        aposentada_em: "2026-09-25T09:00:00", aposentada_por: "Admin",
        motivo_aposentadoria: "conta de teste" },
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const bloco = await within(dialogo).findByRole("region", {
      name: "Contas do aluno no Matific",
    });

    expect(within(bloco).getByText("conta-A")).toBeInTheDocument();
    expect(within(bloco).getByText("Conta em uso")).toBeInTheDocument();
    expect(within(bloco).getByText("conta-B")).toBeInTheDocument();
    // REV2-COSTURA-3: o que já veio dela continua contando — "não contabilizada" prometia o contrário
    expect(within(bloco).getByText("Preservada, fora da importação")).toBeInTheDocument();
    expect(bloco).not.toHaveTextContent(/não contabilizada/);
    // o histórico da decisão
    expect(within(bloco).getByText(/por Admin — conta de teste/)).toBeInTheDocument();
    // a distinção que não pode se perder
    expect(within(bloco).getByText(/não desativa nem remove a conta no Matific/i)).toBeInTheDocument();
    // ALUNOS-4 / REV2-COSTURA-3: o histórico não guarda a conta de origem. O que já veio da
    // aposentada fica na ficha e continua contando, e o retrato atual só muda quando entra
    // uma coleta da conta que vale; a trava contra queda pode segurar essa coleta. O texto
    // não promete que os números saem na próxima coleta.
    expect(bloco).toHaveTextContent(/O que já veio dela continua na ficha \(o histórico não guarda de qual conta veio\): os retratos já importados continuam nos períodos em que entraram, e o retrato atual só muda quando entrar uma coleta da conta que vale\./);
    expect(bloco).toHaveTextContent(/Se a conta aposentada tinha números maiores, a coleta automática da que vale fica retida como queda/);
    expect(bloco).not.toHaveTextContent(/até a próxima coleta da conta que vale/);
    expect(bloco).not.toHaveTextContent(/alimentar o retrato e a pontuação/);
  });

  it("no Elefante, diz que as leituras que vieram da conta aposentada continuam contando", async () => {
    const u = userEvent.setup();
    filaMock([revisaoFake({
      plataforma: "elefante", formato: "leituras", id_externo: "4242",
      motivo: "outra_identidade_na_plataforma",
      motivo_texto: "o aluno encontrado já tem outra conta nesta plataforma",
      candidatos: [
        { aluno_id: 31, nome: "ARIELLE CRISTINA TESTELLI DE AMARO", status: "ativo", turma: "5ºB" },
      ],
    })]);
    responder("GET", "/escolas/1/importacoes/identidades/elefante/aluno/31", [
      { id: 1, id_externo: "4242", status: "efetiva", created_at: "2026-04-01T10:00:00",
        aposentada_em: null, aposentada_por: null, motivo_aposentadoria: null },
      { id: 2, id_externo: "4343", status: "aposentada", created_at: "2026-05-01T10:00:00",
        aposentada_em: "2026-09-25T09:00:00", aposentada_por: "Admin",
        motivo_aposentadoria: "conta de teste" },
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const bloco = await within(dialogo).findByRole("region", {
      name: "Contas do aluno no Elefante Letrado",
    });
    expect(bloco).toHaveTextContent(/as leituras já importadas continuam contando, e o retrato atual só muda quando entrar uma coleta da conta que vale\./);
    // a trava contra queda é do Matific: o aviso dela não aparece aqui
    expect(bloco).not.toHaveTextContent(/retida como queda/);
  });

  it("escolher a conta principal exige motivo e envia aposentando a outra", async () => {
    const u = userEvent.setup();
    filaMock([duasContas()]);
    contasMock([
      { id: 1, id_externo: "conta-A", status: "efetiva", created_at: "2026-04-01T10:00:00",
        aposentada_em: null, aposentada_por: null, motivo_aposentadoria: null },
      { id: 2, id_externo: "conta-B", status: "efetiva", created_at: "2026-05-01T10:00:00",
        aposentada_em: null, aposentada_por: null, motivo_aposentadoria: null },
    ]);
    responder("POST", "/escolas/1/importacoes/identidades/matific/efetiva", {
      aluno_id: 31, plataforma: "matific", identidade_efetiva: "conta-A",
      identidades_aposentadas: ["conta-B"], revisoes_encerradas: [], motivo: "é a que ela usa",
      observacao: "Decisão interna do Constela.",
    });
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    const bloco = await within(dialogo).findByRole("region", {
      name: "Contas do aluno no Matific",
    });

    await u.click(within(bloco).getAllByRole("button", { name: "Usar só esta conta" })[0]);
    const confirmar = within(bloco).getByRole("button", { name: "Confirmar" });
    expect(confirmar).toBeDisabled();                 // sem motivo, não envia

    await u.type(within(bloco).getByRole("textbox"), "é a que ela usa");
    await u.click(within(bloco).getByRole("button", { name: "Confirmar" }));

    await waitFor(() => {
      const chamada = api.mock.calls.find(
        ([c, o]) => String(c).endsWith("/identidades/matific/efetiva")
          && (o as RequestInit)?.method === "POST");
      expect(chamada).toBeTruthy();
      expect(JSON.parse(String((chamada?.[1] as RequestInit)?.body))).toEqual({
        aluno_id: 31, id_externo_efetivo: "conta-A",
        aposentar: ["conta-B"], motivo: "é a que ela usa",
      });
    });
  });

  it("com uma conta só, o bloco não aparece (não há o que decidir)", async () => {
    const u = userEvent.setup();
    filaMock([duasContas()]);
    contasMock([
      { id: 1, id_externo: "conta-A", status: "efetiva", created_at: "2026-04-01T10:00:00",
        aposentada_em: null, aposentada_por: null, motivo_aposentadoria: null },
    ]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u);
    await within(dialogo).findByRole("region", { name: "Candidatos encontrados" });
    expect(within(dialogo).queryByRole("region", {
      name: "Contas do aluno no Matific",
    })).toBeNull();
  });
});

// ── A14: a triagem do backend na tela (selo, filtro por motivo, "só seguras") ──
// A tela mostra o veredito e filtra; NÃO resolve nada em lote.

function triagemFake(classificacao: "segura" | "decisao_humana", motivo_texto: string,
                     extra: Partial<NonNullable<RevisaoIdentidade["triagem"]>> = {}) {
  return { classificacao, motivo: classificacao === "segura" ? "candidato_unico_compativel" : "ambigua_decisao_humana",
           motivo_texto, aluno_id: null, evidencias: [], conflitos: [], retrato_superado: null,
           irmas: [], ...extra };
}

function filaComTriagem() {
  return filaMock([
    revisaoFake({ triagem: triagemFake("decisao_humana",
      "mais de um candidato e nenhuma evidência objetiva desempata",
      { conflitos: ["2 fichas candidatas, e a linha não traz a conta da plataforma"] }) }),
    revisaoFake({ id: 8, nome_recebido: "MAURO R", motivo: "correspondencia_insegura",
      motivo_texto: "nome parecido, mas a correspondência não é segura",
      candidatos: [{ aluno_id: 40, nome: "MAURO RIBEIRO FICTONI", status: "ativo", turma: "5ºB" }],
      triagem: triagemFake("segura", "candidato único, turma e série compatíveis, sem conta concorrente",
        { evidencias: ["Candidato único registrado: MAURO RIBEIRO FICTONI (5ºB)",
                       "Série compatível (5º ano)"] }) }),
    revisaoFake({ id: 9, nome_recebido: "LIA S", motivo: "nome_incompleto",
      motivo_texto: "a plataforma mandou só o nome abreviado", candidatos: [],
      triagem: triagemFake("decisao_humana", "nenhum aluno corresponde — criar ficha é decisão de gestão") }),
  ]);
}

describe("Revisões de identidade — triagem", () => {
  it("cada pendência mostra o selo da triagem e o porquê", async () => {
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const item = (n: string) =>
      screen.getByRole("button", { name: `Ver revisão de ${n}` }).closest("li") as HTMLElement;
    await screen.findByText("3 pendências");
    expect(within(item("MAURO R")).getByText("Segura")).toBeInTheDocument();
    expect(within(item("MAURO R")).getByText(/Triagem: candidato único/)).toBeInTheDocument();
    expect(within(item("TOBIAS D")).getByText("Decisão humana")).toBeInTheDocument();
    expect(within(item("LIA S")).getByText("Decisão humana")).toBeInTheDocument();
  });

  it("filtra por motivo, com a contagem de cada um", async () => {
    const u = userEvent.setup();
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await screen.findByText("3 pendências");
    const filtro = screen.getByLabelText("Motivo");
    expect(within(filtro).getByRole("option", { name: "Nome abreviado (1)" })).toBeInTheDocument();
    await u.selectOptions(filtro, "nome_incompleto");
    expect(screen.getByRole("button", { name: "Ver revisão de LIA S" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ver revisão de MAURO R" })).toBeNull();
  });

  it("'Só as seguras' deixa só as que a triagem chamou de seguras", async () => {
    const u = userEvent.setup();
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await screen.findByText("3 pendências");
    await u.click(screen.getByRole("checkbox", { name: /Só as seguras \(1\)/ }));
    expect(screen.getByRole("button", { name: "Ver revisão de MAURO R" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver revisão de TOBIAS D" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ver revisão de LIA S" })).toBeNull();
  });

  it("não há ação em lote: resolver continua sendo um por um", async () => {
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    await screen.findByText("3 pendências");
    expect(screen.queryByRole("button", { name: /lote|todas as seguras|resolver todas/i })).toBeNull();
    expect(api.mock.calls.some(([, o]) => (o as RequestInit)?.method === "POST")).toBe(false);
  });

  it("o detalhe explica a triagem com as evidências e os conflitos", async () => {
    const u = userEvent.setup();
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u, "MAURO R");
    const bloco = within(dialogo).getByRole("region", { name: "Triagem automática" });
    expect(within(bloco).getByText("Segura")).toBeInTheDocument();
    expect(within(bloco).getByText("Série compatível (5º ano)")).toBeInTheDocument();
    expect(within(bloco).getByText(/nada é vinculado sem a sua escolha/)).toBeInTheDocument();
  });

  // Evidências e conflitos que ocupam duas linhas: a 2ª linha alinha com o texto da 1ª,
  // não volta para baixo do marcador. O jsdom não faz layout — a medida no navegador
  // (desalinhamento de 17 px antes, 0 depois) fica no relatório da correção; aqui, a
  // estrutura que a garante: marcador FORA do texto ("list-outside") e o recuo da
  // lista para ele ("pl-4"), nunca "list-inside".
  it("triagem: listas com o marcador fora do texto e recuo, para a 2ª linha alinhar", async () => {
    const u = userEvent.setup();
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const lista = async (nome: string, rotulo: string) => {
      const dialogo = await abrirDetalhe(u, nome);
      const bloco = within(dialogo).getByRole("region", { name: "Triagem automática" });
      const classes = within(bloco).getByRole("list", { name: rotulo }).className.split(/\s+/);
      await u.click(within(dialogo).getByRole("button", { name: "Fechar" }));
      return classes;
    };
    for (const classes of [await lista("TOBIAS D", "Conflitos da triagem"),
                           await lista("MAURO R", "Evidências da triagem")]) {
      expect(classes).toEqual(expect.arrayContaining(["list-outside", "list-disc", "pl-4"]));
      expect(classes).not.toContain("list-inside");
    }
  });

  it("no detalhe, a frase da triagem começa com maiúscula", async () => {
    const u = userEvent.setup();
    filaComTriagem();
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    const dialogo = await abrirDetalhe(u, "TOBIAS D");
    const bloco = within(dialogo).getByRole("region", { name: "Triagem automática" });
    // Abre o bloco, logo depois do selo: frase com maiúscula, não "mais de um…".
    expect(within(bloco).getByText("Mais de um candidato e nenhuma evidência objetiva desempata"))
      .toBeInTheDocument();
    expect(within(bloco).queryByText(/^mais de um candidato/)).toBeNull();
  });

  it("o contador usa o total real quando a fila passa do limite da lista", async () => {
    filaComTriagem();
    responder("GET", "/escolas/1/importacoes/contagem-revisoes",
      { pendentes: 612, por_motivo: {}, limite_da_lista: 500 });
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
    expect(await screen.findByText("612 pendências")).toBeInTheDocument();
    expect(screen.queryByText(/500\+ pendências/)).toBeNull();
  });
});
