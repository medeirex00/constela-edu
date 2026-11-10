import { describe, expect, it } from "vitest";

import Importacoes from "../pages/Importacoes";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise, Importacao, ResultadoImportacao } from "../lib/types";
import analiseReal from "./fixtures/importacoes/analise_matific_motivos.json";
import analiseDuasContas from "./fixtures/importacoes/analise_matific_duas_contas.json";
import analisePlacarMotivos from "./fixtures/importacoes/analise_matific_placar_motivos.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  within,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

// A tela usa useImportacaoLote(), cujo Provider fica ACIMA do Layout no app real
// (não dentro do AppProvider). Como o harness só injeta AppProvider + Router,
// envolvemos a tela no provider aqui — o AppProvider externo (do renderComApp)
// continua acima, então useApp() dentro do provider funciona.
function montar() {
  return (
    <ImportacaoLoteProvider>
      <Importacoes />
    </ImportacaoLoteProvider>
  );
}

function importacaoFake(over: Partial<Importacao> = {}): Importacao {
  return {
    id: 1,
    plataforma: "matific",
    tipo: "Leaderboard mensal",
    arquivo_original: "relatorio.pdf",
    qtd_alunos: 37,
    qtd_erros: 0,
    tempo_ms: 1200,
    status: "ok",
    created_at: "2026-07-01T12:00:00Z",
    usuario_nome: "Prof. Mariana",
    ...over,
  };
}

// Prévia com um aluno de correspondência exata (formato de leaderboard, não
// "leituras"), suficiente para renderizar a tabela e habilitar a confirmação.
function analiseFake(): Analise {
  return {
    plataforma: "matific",
    formato: "leaderboard",
    tipo: "leaderboard",
    arquivo_token: "tok-123",
    arquivo_nome: "relatorio.pdf",
    estrategia: "tabela",
    mensagem_deteccao: "Este arquivo pertence ao Matific.",
    turma_detectada: "3º Ano A",
    origem_nome: "conteudo",
    total_alunos: 1,
    total_linhas: 1,
    total_erros: 0,
    total_avisos: 0,
    erros_gerais: [],
    linhas: [
      {
        numero: 1,
        nome: "Ana Beatriz Souza",
        dados: { atividades: 42, pontuacao_media: 85, estrelas: 120 },
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
  };
}

describe("Importacoes", () => {
  it("mostra o histórico de importações da escola", async () => {
    responder("GET", URL_HIST, [
      importacaoFake(),
      importacaoFake({ id: 2, plataforma: "elefante", tipo: "Relatório individual", qtd_alunos: 12, qtd_erros: 2, usuario_nome: "Coord. Ana" }),
    ]);
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });

    expect(await screen.findByText("Leaderboard mensal")).toBeInTheDocument();
    expect(screen.getByText("Relatório individual")).toBeInTheDocument();
    expect(screen.getByText("Prof. Mariana")).toBeInTheDocument();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Histórico" })).toBeInTheDocument();
    // Sem a referência ao documento interno de requisitos ("PRD §15") no texto da escola.
    const subtitulo = screen.getByText(/Toda importação fica registrada com autor, quantidade e tempo/);
    expect(subtitulo.textContent).toBe("Toda importação fica registrada com autor, quantidade e tempo.");
    expect(subtitulo.textContent).not.toMatch(/PRD/);
  });

  it("o passo a passo tem as três etapas, numa lista ordenada, com a atual marcada", async () => {
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    // A página abre em "Matrículas da escola"; o passo a passo aqui é o do envio individual.
    await userEvent.click(await screen.findByRole("button", { name: /Um por vez/ }));

    const passos = await screen.findByRole("list", { name: "Etapas da importação" });
    const itens = within(passos).getAllByRole("listitem");
    expect(itens.map((li) => li.textContent)).toEqual([
      "1Enviar o relatório", "2Conferir a prévia", "3Confirmar e gravar",
    ]);
    expect(itens[0]).toHaveAttribute("aria-current", "step");
    expect(itens[1]).not.toHaveAttribute("aria-current");
  });

  it("mostra o estado vazio quando não há importações", async () => {
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });

    expect(await screen.findByText("Nenhuma importação ainda")).toBeInTheDocument();
    expect(
      screen.getByText("O histórico aparecerá aqui após a primeira importação."),
    ).toBeInTheDocument();
  });

  it("mostra a falha quando o histórico não carrega", async () => {
    responderErro("GET", URL_HIST, 500, "Erro interno");
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });

    expect(await screen.findByText("Não foi possível carregar")).toBeInTheDocument();
    expect(screen.getByText("Erro interno")).toBeInTheDocument();
  });

  it("analisa o texto colado, mostra a prévia e confirma a importação", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseFake());
    const resultado: ResultadoImportacao = {
      mensagem: "Importação concluída com sucesso.",
      importacao_id: 99,
      qtd_alunos: 1,
      qtd_erros: 0,
      avisos: [],
    };
    responder("POST", URL_CONFIRMAR, resultado);

    renderComApp(montar(), { rota: "/importacoes" });

    // Espera a tela terminar de carregar (histórico vazio) antes de interagir.
    await screen.findByText("Nenhuma importação ainda");

    // A página abre por padrão em "Matrículas da escola"; este teste é do envio
    // individual, então troca para a aba "Um por vez" primeiro.
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));

    // A área de texto é o único textbox do formulário de envio individual.
    await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));

    // Prévia renderizada com o aluno e a correspondência encontrada.
    expect(await screen.findByText("Prévia da importação")).toBeInTheDocument();
    expect(screen.getByText("Ana Beatriz Souza")).toBeInTheDocument();
    expect(screen.getByText("Vinculado automaticamente")).toBeInTheDocument();

    // "Sim, importar" abre a confirmação (nada gravado ainda): ela resume o que vai
    // ser gravado e só o "Gravar importação" chama o /confirmar.
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent("1 vinculado(s) a um aluno já cadastrado");
    expect(api.mock.calls.some(([caminho]) => caminho === URL_CONFIRMAR)).toBe(false);
    await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
    expect(
      await screen.findByText("Importação concluída com sucesso."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Gravar esta importação?" })).toBeNull();
  });

  async function previaComCorrespondencia(corr: Analise["linhas"][number]["correspondencia"]) {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = analiseFake();
    analise.linhas[0].correspondencia = corr;
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Ana B 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    return u;
  }

  it("'nome parecido' (revisar) NÃO vem pré-selecionado como vínculo", async () => {
    await previaComCorrespondencia({
      status: "revisar", aluno_id: 10, aluno_nome: "Ana Beatriz Souza",
      similaridade: 90, motivo: "correspondencia_insegura",
      alternativas: [{ aluno_id: 10, nome: "Ana Beatriz Souza",
                       turma: "3º Ano A", similaridade: 90 }],
    });
    expect(screen.getByText("Nome parecido com o de um aluno — vai para Revisões de identidade"))
      .toBeInTheDocument();
    // Segurança: o destino NÃO vem no aluno (grafia parecida nunca vira vínculo por
    // 1 clique). E não vem em "Criar": a confirmação manda a linha para a Revisão
    // (o backend não cria ficha quando há candidato) — o destino diz isso.
    const destino = screen.getByRole("combobox",
      { name: /Destino de/ }) as HTMLSelectElement;
    expect(destino.value).toBe("revisao");
    const opcoes = Array.from(destino.options).map((o) => o.value);
    expect(opcoes).toEqual(["10", "revisao", "ignorar"]);
  });

  // Linhas que o backend SEMPRE manda para Revisões de identidade (nome abreviado,
  // duas contas com o mesmo nome): a prévia diz o motivo, não oferece "Criar", não
  // as conta como aluno novo e a confirmação as conta à parte.
  it.each([
    ["nome_incompleto", "Nome abreviado — vai para Revisões de identidade", /só parte do nome/],
    ["contas_repetidas_no_relatorio", "Duas contas com o mesmo nome — vai para Revisões de identidade",
     /podem ser a mesma criança ou duas/],
  ])("linha '%s' vai para a Revisão: sem 'Criar', fora dos alunos novos", async (motivo, rotulo, explicacao) => {
    const u = await previaComCorrespondencia({
      status: "revisar", aluno_id: null, aluno_nome: null, similaridade: null,
      motivo, alternativas: [],
    });
    expect(screen.getByText(rotulo)).toBeInTheDocument();
    expect(screen.getByText(explicacao)).toBeInTheDocument();
    expect(screen.queryByText("Possível duplicata — requer revisão")).toBeNull();
    const destino = screen.getByRole("combobox", { name: /Destino de/ }) as HTMLSelectElement;
    expect(destino.value).toBe("revisao");
    expect(Array.from(destino.options).map((o) => o.textContent)).toEqual(
      ["Deixar para a Revisão", "Ignorar"]);
    // Não é "aluno novo": nem a faixa de criação em massa aparece.
    expect(screen.queryByText(/aluno\(s\) novo\(s\)/)).toBeNull();
    // Concordância: com uma linha, "1 vai" (não "1 vão").
    expect(screen.getByText(/serão importados/).textContent)
      .toBe("0 de 1 aluno(s) serão importados; 1 vai para Revisões de identidade.");

    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent(
      "1 vai para Revisões de identidade — nenhuma ficha é criada; um gestor decide de quem são os dados");
    expect(confirmacao).not.toHaveTextContent(/1 vão/);
    expect(confirmacao).not.toHaveTextContent(/aluno\(s\) novo\(s\)/);
    expect(confirmacao).not.toHaveTextContent(/não se desfaz sozinha/);
    responder("POST", URL_CONFIRMAR, {
      mensagem: "0 aluno(s) com dado novo importado(s).", importacao_id: 7,
      qtd_alunos: 0, qtd_erros: 0, avisos: [], qtd_revisoes: 1, criacao_bloqueada: 0,
    } satisfies ResultadoImportacao);
    await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
    // A linha SEGUE para o backend (é ele quem abre a pendência), com a turma da
    // prévia e sem aluno escolhido.
    const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
    const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
    expect(corpo.linhas).toHaveLength(1);
    expect(corpo.linhas[0]).toMatchObject({ aluno_id: null, criar_em_turma_id: 1 });
    // O resultado leva às Revisões mesmo sem a política "bloquear".
    expect(await screen.findByText(/1 aluno aguarda/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
  });

  // Contrato com o backend: a prévia REAL do /analisar, gravada por
  // backend/tests/test_importacao_previa_motivo.py — não um mock montado à mão.
  // Antes o backend descartava o "motivo" (CorrespondenciaOut sem o campo) e o nome
  // abreviado chegava como "Possível duplicata", com "Criar" e contado como novo.
  it.each([
    ["sem turma no cabeçalho", ""],
    ["com a turma do cabeçalho", "3º Ano A"],
  ])("prévia real do backend (%s): o nome abreviado vai para a Revisão", async (_caso, turma) => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = JSON.parse(JSON.stringify(analiseReal)) as Analise;
    analise.turma_detectada = turma;
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Zefa Q 10");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");

    const destino = screen.getByRole("combobox", { name: /Destino de Zefa Q/ }) as HTMLSelectElement;
    expect(destino.value).toBe("revisao");
    expect(Array.from(destino.options).map((o) => o.textContent)).toEqual(
      ["Deixar para a Revisão", "Ignorar"]);
    expect(screen.getByText("Nome abreviado — vai para Revisões de identidade")).toBeInTheDocument();
    expect(screen.queryByText("Possível duplicata — requer revisão")).toBeNull();
    if (turma) {
      // Só a criança sem ficha é aluno novo (antes: "2 aluno(s) novo(s)").
      expect(screen.getByText(/aluno\(s\) novo\(s\)/).textContent).toMatch(/^1 aluno\(s\) novo\(s\)/);
    }
  });

  // "Aplicar a todos" muda o destino só dos alunos NOVOS: a linha que vai para a
  // Revisão (o nome abreviado da prévia real) fica onde está — "Criar" nela seria
  // ignorado pelo backend. Os dois botões: a turma escolhida e a turma do relatório
  // ainda não cadastrada (nova).
  it.each([
    ["Aplicar a todos", "3º Ano A", "criar"],
    ["Aplicar a todos: turma do relatório (nova)", "5º Ano Z", "criar_nova"],
  ])("'%s' não tira da Revisão a linha que vai para lá", async (botao, turma, novoDestino) => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = JSON.parse(JSON.stringify(analiseReal)) as Analise;
    analise.turma_detectada = turma;
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Zefa Q 10");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    fireEvent.change(screen.getByLabelText("Data do relatório (obrigatória)"),
      { target: { value: "2026-08-14" } });
    const destino = (nome: string) =>
      screen.getByRole("combobox", { name: `Destino de ${nome}` }) as HTMLSelectElement;
    // O aluno novo começa em "Ignorar": o botão tem de mudá-lo (senão o teste não
    // prova nada).
    await u.selectOptions(destino("Crianca Ficticia Sem Ficha"), "ignorar");
    expect(destino("Zefa Q").value).toBe("revisao");

    await u.click(screen.getByRole("button", { name: botao }));
    expect(destino("Crianca Ficticia Sem Ficha").value).toBe(novoDestino);
    expect(destino("Zefa Q").value).toBe("revisao");
    expect(destino("Ana Beatriz Souza").value).toBe("1");
    // O select da linha de Revisão não tem "Criar": se o botão a mudasse, o React
    // mostraria a 1ª opção ("Deixar para a Revisão") e só a contagem denunciaria —
    // "3 de 3 serão importados", sem nada para Revisões.
    expect(screen.getByText(/serão importados/).textContent)
      .toBe("2 de 3 aluno(s) serão importados; 1 vai para Revisões de identidade.");
  });

  // Política "bloquear" com a mesma prévia real: o backend vincula 1, não cria
  // ninguém e abre 2 pendências (o nome abreviado e o "Criar" barrado pela política
  // — backend/tests/test_importacao_previa_motivo.py). Antes o rodapé dizia "2 de 3
  // serão importados; 1 vão para Revisões" e a confirmação "1 aluno(s) novo(s)".
  it("política 'bloquear': o rodapé e a confirmação contam o 'Criar' em Revisões", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = JSON.parse(JSON.stringify(analiseReal)) as Analise;
    analise.turma_detectada = "3º Ano A";
    analise.criacao_bloqueada_por_politica = true;
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Zefa Q 10");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    fireEvent.change(screen.getByLabelText("Data do relatório (obrigatória)"),
      { target: { value: "2026-08-14" } });

    // Plural: "2 vão".
    expect(screen.getByText(/serão importados/).textContent)
      .toBe("1 de 3 aluno(s) serão importados; 2 vão para Revisões de identidade.");
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent("1 vinculado(s) a um aluno já cadastrado");
    expect(confirmacao).toHaveTextContent(/2 vão para Revisões de identidade — nenhuma ficha é criada/);
    expect(confirmacao).not.toHaveTextContent(/aluno\(s\) novo\(s\)/);
    expect(confirmacao).toHaveTextContent(/Pela política desta escola/);
    expect(confirmacao).not.toHaveTextContent(/não se desfaz sozinha/);
  });

  it("sem a política 'bloquear', o 'Criar' continua contado como aluno novo", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = JSON.parse(JSON.stringify(analiseReal)) as Analise;
    analise.turma_detectada = "3º Ano A";
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Zefa Q 10");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    fireEvent.change(screen.getByLabelText("Data do relatório (obrigatória)"),
      { target: { value: "2026-08-14" } });

    expect(screen.getByText(/serão importados/).textContent)
      .toBe("2 de 3 aluno(s) serão importados; 1 vai para Revisões de identidade.");
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent("1 aluno(s) novo(s)");
    expect(confirmacao).toHaveTextContent(/1 vai para Revisões de identidade — nenhuma ficha é criada/);
    expect(confirmacao).toHaveTextContent(/não se desfaz sozinha/);
    expect(confirmacao).not.toHaveTextContent(/Pela política desta escola/);
  });

  // Duas contas da plataforma com o mesmo nome, na mesma sala e sem ficha — a prévia
  // REAL do /analisar (Placar do Matific), gravada por
  // backend/tests/test_importacao_previa_motivo.py. O backend abre UMA pendência por
  // conta (o mesmo teste confirma o corpo abaixo: 1 vinculado, 2 pendências, nenhuma
  // ficha). Antes a tela juntava as duas contas numa linha (chave nome|turma) e dizia
  // "1 de 2 … ; 1 vai para Revisões", enquanto o resultado dizia "2 alunos aguardam".
  it("duas contas com o mesmo nome: uma linha por conta, e a contagem bate com o backend", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, JSON.parse(JSON.stringify(analiseDuasContas)) as Analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "placar");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    fireEvent.change(screen.getByLabelText("Data do relatório (obrigatória)"),
      { target: { value: "2026-08-14" } });

    // Uma linha por conta, cada uma com o seu destino.
    const destinos = screen.getAllByRole("combobox", { name: /^Destino de / }) as HTMLSelectElement[];
    expect(destinos.map((d) => d.getAttribute("aria-label"))).toEqual([
      "Destino de Ana Beatriz Souza",
      "Destino de Crianca Ficticia Repetida (conta 1 de 2)",
      "Destino de Crianca Ficticia Repetida (conta 2 de 2)",
    ]);
    expect(destinos.map((d) => d.value)).toEqual(["1", "revisao", "revisao"]);
    expect(screen.getAllByText("Duas contas com o mesmo nome — vai para Revisões de identidade"))
      .toHaveLength(2);
    expect(screen.getByText(/serão importados/).textContent)
      .toBe("1 de 3 aluno(s) serão importados; 2 vão para Revisões de identidade.");

    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent("1 vinculado(s) a um aluno já cadastrado");
    expect(confirmacao).toHaveTextContent(/2 vão para Revisões de identidade — nenhuma ficha é criada/);
    responder("POST", URL_CONFIRMAR, {
      mensagem: "1 aluno(s) com dado novo importado(s).", importacao_id: 9,
      qtd_alunos: 1, qtd_erros: 2, avisos: [], qtd_revisoes: 2, criacao_bloqueada: 0,
    } satisfies ResultadoImportacao);
    await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
    // O corpo é o que o teste do backend confirma: cada conta na sua linha, sem aluno
    // escolhido, com a turma da prévia.
    const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
    const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
    expect(corpo.linhas.map((l: { dados: { matific_uuid: string } }) => l.dados.matific_uuid))
      .toEqual(["uuid-ficticio-ana", "uuid-ficticio-1", "uuid-ficticio-2"]);
    expect(corpo.linhas.slice(1)).toMatchObject([
      { aluno_id: null, criar_em_turma_id: 1 }, { aluno_id: null, criar_em_turma_id: 1 }]);
    expect(await screen.findByText(/2 alunos aguardam a decisão de um gestor/)).toBeInTheDocument();
  });

  it("revisão de TURMA (a turma escolhida resolve) continua com 'Criar'", async () => {
    await previaComCorrespondencia({
      status: "revisar", aluno_id: null, aluno_nome: null, similaridade: null,
      motivo: "turma_ambigua", alternativas: [],
    });
    const destino = screen.getByRole("combobox", { name: /Destino de/ }) as HTMLSelectElement;
    expect(destino.value).toBe("criar");
    expect(screen.getByText(/aluno\(s\) novo\(s\)/)).toBeInTheDocument();
    // O motivo diz o que é (não "Possível duplicata") e o que fazer.
    expect(screen.getByText("Mais de uma turma possível — escolha a turma")).toBeInTheDocument();
    expect(destino).toHaveAccessibleDescription(
      "Mais de uma turma possível — escolha a turma Mais de uma turma cadastrada corresponde à "
      + "turma do relatório: confira a turma da ficha nova.");
  });

  // Cada motivo que o backend manda tem rótulo e explicação próprios — com a prévia
  // REAL de um Placar do Matific com um aluno por motivo (gravada por
  // backend/tests/test_importacao_previa_motivo.py, que também confere que todo
  // motivo do backend tem rótulo aqui). Antes, todos apareciam como "Possível
  // duplicata — requer revisão", inclusive a conta de outra escola, a ficha inativa e
  // a mesma conta em duas linhas; e a explicação não era ligada ao "Destino de …".
  it("prévia real com um aluno por motivo: cada um com o seu rótulo, ligado ao destino", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, JSON.parse(JSON.stringify(analisePlacarMotivos)) as Analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "placar");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");

    const vai = "vai para Revisões de identidade";
    const esperado: [string, string, RegExp | null][] = [
      ["Ana Beatriz Souza", "Vinculado automaticamente", null],
      ["Sofia Almeida Durte", `Nome parecido com o de um aluno — ${vai}`, /não o bastante para vincular sozinho/],
      ["Davi Ficticio", `Mais de um aluno possível — ${vai}`, /Mais de um aluno cadastrado pode ser/],
      ["Lara Ficticia Brandao", `Mesmo nome em outra turma — ${vai}`, /pode ser a mesma criança, que mudou de sala/],
      ["Teo Ficticio", `Nome parecido em outra turma — ${vai}`, /aluno de outra turma, não da turma do relatório/],
      ["Heitor Fictorino Lemos", `Aluno com a ficha inativa — ${vai}`, /está com a ficha inativa/],
      ["Iara Ficticia Neves", `Conta de um aluno com a ficha inativa — ${vai}`, /já está vinculada a um aluno com a ficha inativa/],
      ["Joao Pedro Barbosa", `O aluno já tem outra conta — ${vai}`, /já tem outra conta nesta plataforma/],
      ["Crianca Ficticia Um", `A mesma conta em mais de uma linha — ${vai}`, /veio em mais de uma linha/],
      ["Crianca Ficticia Dois", `A mesma conta em mais de uma linha — ${vai}`, /veio em mais de uma linha/],
      ["Bento Ficticio Moura", `Conta de um aluno de outra escola — ${vai}`, /aluno de outra escola do Constela/],
      ["Zefa Q", `Nome abreviado — ${vai}`, /só parte do nome/],
      ["Crianca Ficticia Repetida (conta 1 de 2)", `Duas contas com o mesmo nome — ${vai}`, /podem ser a mesma criança ou duas/],
      ["Crianca Ficticia Repetida (conta 2 de 2)", `Duas contas com o mesmo nome — ${vai}`, /podem ser a mesma criança ou duas/],
      ["Crianca Nova Ficticia", "Novo aluno", null],
    ];
    expect(screen.getAllByRole("combobox", { name: /^Destino de / }).map((d) => d.getAttribute("aria-label")))
      .toEqual(esperado.map(([nome]) => `Destino de ${nome}`));
    for (const [nome, rotulo, explicacao] of esperado) {
      const destino = screen.getByRole("combobox", { name: `Destino de ${nome}` });
      const linha = within(destino.closest("tr") as HTMLElement);
      expect(linha.getByText(rotulo)).toBeInTheDocument();
      // O leitor de tela ouve o selo e a explicação ao chegar no seletor do destino.
      const descricao = destino.getAttribute("aria-describedby")?.split(" ")
        .map((id) => document.getElementById(id)?.textContent).join(" ");
      expect(descricao?.startsWith(rotulo), `${nome}: ${descricao}`).toBe(true);
      if (explicacao) {
        expect(descricao, nome).toMatch(explicacao);
        expect(destino).toHaveAccessibleDescription(descricao);
      }
    }
    expect(screen.queryByText(/Possível duplicata/)).toBeNull();
    // 15 linhas: o vínculo e o aluno novo são importados; as 13 outras vão para a fila.
    fireEvent.change(screen.getByLabelText("Data do relatório (obrigatória)"),
      { target: { value: "2026-08-14" } });
    expect(screen.getByText(/serão importados/).textContent)
      .toBe("2 de 15 aluno(s) serão importados; 13 vão para Revisões de identidade.");
  });

  it("motivo que a tela ainda não conhece: 'Requer revisão', sem chamar de duplicata", async () => {
    await previaComCorrespondencia({
      status: "revisar", aluno_id: null, aluno_nome: null, similaridade: null,
      motivo: "motivo_futuro_do_backend", alternativas: [],
    });
    expect(screen.getByText("Requer revisão")).toBeInTheDocument();
    expect(screen.queryByText(/Possível duplicata/)).toBeNull();
  });

  it("resultado com pendências e sem a política 'bloquear' leva às revisões", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseFake());
    responder("POST", URL_CONFIRMAR, {
      mensagem: "1 aluno(s) com dado novo importado(s).", importacao_id: 8,
      qtd_alunos: 1, qtd_erros: 0, avisos: [], qtd_revisoes: 2, criacao_bloqueada: 0,
    } satisfies ResultadoImportacao);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    await u.click(await screen.findByRole("button", { name: "Gravar importação" }));
    expect(await screen.findByText(/2 alunos aguardam a decisão de um gestor/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
  });

  it("nome da escola do relatório diferente do cadastro: só aviso, a prévia segue", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = analiseFake();
    analise.escola_detectada = "EMEF OUTRA ESCOLA";
    analise.aviso_escola = "Aviso: o relatório é da escola “EMEF OUTRA ESCOLA” e esta escola está cadastrada como “ESCOLA TESTE”.";
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    expect(await screen.findByText(/o relatório é da escola “EMEF OUTRA ESCOLA”/)).toBeInTheDocument();
    // Não bloqueia: a confirmação continua disponível.
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeEnabled();
  });

  it("escola com a política 'bloquear': a prévia avisa que quem não casar não ganha ficha", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = analiseFake();
    analise.criacao_bloqueada_por_politica = true;
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    expect(
      await screen.findByText(/A matrícula desta escola vem da Lista Piloto/),
    ).toBeInTheDocument();
    // Só aviso: a confirmação continua disponível (o backend manda para a revisão).
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeEnabled();
  });

  it("sem a política 'bloquear', a prévia não mostra o aviso", async () => {
    await previaComCorrespondencia(analiseFake().linhas[0].correspondencia);
    expect(screen.queryByText(/A matrícula desta escola vem da Lista Piloto/)).toBeNull();
  });

  it("criação barrada pela política: o resultado diz o motivo e leva às revisões", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseFake());
    const resultado: ResultadoImportacao = {
      mensagem:
        "0 aluno(s) com dado novo importado(s). 1 aluno(s) sem ficha não foram criados: a "
        + "política desta escola não deixa a plataforma criar ficha (a matrícula vem da "
        + "Lista Piloto). Eles ficaram em Revisão de identidade para um gestor apontar a "
        + "ficha certa.",
      importacao_id: 99,
      qtd_alunos: 0,
      qtd_erros: 1,
      avisos: [],
      // Política "bloquear" + um nome abreviado: o backend barra 1 e manda os 2
      // para a fila (o abreviado sai com outro motivo). Quem aguarda são os 2.
      qtd_revisoes: 2,
      criacao_bloqueada: 1,
    };
    responder("POST", URL_CONFIRMAR, resultado);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    await u.click(await screen.findByRole("button", { name: "Gravar importação" }));
    expect(
      await screen.findByText(/a política desta escola não deixa a plataforma criar ficha/),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 alunos aguardam/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
  });

  it("'bloqueado por conflito' aparece com o rótulo certo", async () => {
    await previaComCorrespondencia({
      status: "bloqueado", aluno_id: null, aluno_nome: null,
      similaridade: null, alternativas: [],
    });
    expect(
      screen.getByText("Bloqueado por conflito de identidade"),
    ).toBeInTheDocument();
  });
});
