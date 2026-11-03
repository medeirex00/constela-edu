import { describe, expect, it } from "vitest";

import Configuracoes from "../pages/configuracoes/Configuracoes";
import {
  api,
  apiDownload,
  apiUpload,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

// Endpoints disparados no carregamento pela coordenadora (usuário padrão, não-admin):
// - PesosEditor (namespace "geral") -> GET pesos
// - Aparência -> GET aparencia
// Backup e Assistente de IA são só-admin: não renderizam com o usuário padrão.
const URL_PESOS = "/escolas/1/configuracoes/pesos/geral";
const URL_APARENCIA = "/escolas/1/aparencia";
const URL_ESCOLA = "/escolas/1";
const URL_REGRA = "/escolas/1/configuracoes/pontuacao/regra";

/** GET /pontuacao/regra: a régua EFETIVA (aqui interessa a Nota Geral). */
function regraFake(perfil: "institucional" | "personalizado") {
  return {
    perfil,
    versoes: { composicao: "por_dimensao_v1", dificuldade: "elefante_dificuldade_v1", dificuldade_da_rede: "elefante_dificuldade_v1" },
    dimensoes: [
      { dimensao: "leitura", plataforma: "elefante", contratada: true,
        pesos: { livros: 35, dificuldade: 30, questoes: 30, tempo: 5 }, subpesos_questoes: { tentativas: 30, acertos: 70 } },
      { dimensao: "matematica", plataforma: "matific", contratada: true,
        pesos: { atividades: 40, media: 35, estrelas: 25 } },
    ],
    nota_geral: { pesos: perfil === "institucional" ? { matific: 50, elefante: 50 } : { matific: 60, elefante: 40 } },
    normalizacao: { modo: "auto", percentil_referencia: 90, minimo_alunos_percentil: 8, indicadores_volume: [] },
  };
}

/** Registra as respostas de sucesso que a tela busca ao montar. */
function carregarSucesso() {
  responder("GET", URL_PESOS, {
    namespace: "geral",
    valores: { matific: 60, elefante: 40 },
    soma: 100,
  });
  responder("GET", URL_APARENCIA, { cor_primaria: "#1B2A4A" });
}

describe("Configurações", () => {
  it("carrega e mostra os dados da escola e os pesos do Ranking Geral", async () => {
    carregarSucesso();
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    expect(
      await screen.findByRole("heading", { name: "Configurações", level: 1 }),
    ).toBeInTheDocument();
    // Formulário da escola semeado a partir da escola atual (id=1).
    expect(await screen.findByDisplayValue("Escola Modelo Constela")).toBeInTheDocument();
    // Pesos do Ranking Geral: rótulos vindos do PesosEditor.
    expect(await screen.findByText("Matific")).toBeInTheDocument();
    expect(screen.getByText("Elefante Letrado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar dados da escola" })).toBeInTheDocument();
  });

  it("edita o nome e salva os dados da escola (PATCH)", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responder("PATCH", URL_ESCOLA, { id: 1, nome: "Escola Renovada" });
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    const nome = await screen.findByDisplayValue("Escola Modelo Constela");
    await u.clear(nome);
    await u.type(nome, "Escola Renovada");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));

    expect(await screen.findByText("Dados da escola atualizados.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      URL_ESCOLA,
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("Admin Global salva os pesos do Ranking Geral (PUT)", async () => {
    // GOVERNANÇA: PUT /pesos/{ns} é exclusivo do Admin Global — o editor só
    // oferece "Salvar pesos" para ele.
    const u = userEvent.setup();
    carregarSucesso();
    responder("PUT", URL_PESOS, { namespace: "geral", valores: { matific: 60, elefante: 40 }, soma: 100 });
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ is_global: true, cargo: "admin" }),
    });

    const botaoPesos = await screen.findByRole("button", { name: "Salvar pesos" });
    // Para quem pode salvar, os controles dos pesos ficam editáveis.
    expect(screen.getByRole("slider", { name: "Matific" })).toBeEnabled();
    expect(screen.getByRole("spinbutton", { name: "Matific (valor exato)" })).toBeEnabled();
    await u.click(botaoPesos);

    expect(
      await screen.findByText("Pesos salvos. Todas as notas foram recalculadas."),
    ).toBeInTheDocument();
  });

  it("coordenadora vê os pesos do Ranking Geral em somente leitura", async () => {
    carregarSucesso();
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    const botao = await screen.findByRole("button", { name: "Somente leitura" });
    expect(botao).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Salvar pesos" })).toBeNull();
    // Os controles também ficam desabilitados: nada de mexer num valor que
    // nunca poderá ser salvo.
    for (const rotulo of ["Matific", "Elefante Letrado"]) {
      expect(screen.getByRole("slider", { name: rotulo })).toBeDisabled();
      expect(screen.getByRole("spinbutton", { name: `${rotulo} (valor exato)` })).toBeDisabled();
    }
  });

  it("mostra mensagem de falha quando salvar a escola erra", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responderErro("PATCH", URL_ESCOLA, 500, "Erro ao salvar no servidor");
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    const nome = await screen.findByDisplayValue("Escola Modelo Constela");
    await u.clear(nome);
    await u.type(nome, "Nova");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));

    expect(await screen.findByText("Erro ao salvar no servidor")).toBeInTheDocument();
  });

  it("diz qual régua decide a Nota Geral: no Padrão Constela, os pesos fixos da rede", async () => {
    // No perfil institucional o motor ignora os pesos gravados aqui: a tela
    // precisa dizer isso (e quais pesos valem), sem ilusão de controle.
    carregarSucesso();
    responder("GET", URL_REGRA, regraFake("institucional"));
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    const aviso = await screen.findByText(/Esta escola usa a Régua Padrão Constela/);
    expect(aviso).toHaveTextContent("em uso: Elefante Letrado 50% · Matific 50%");
    expect(aviso).toHaveTextContent("só passam a valer numa régua personalizada");
    expect(screen.getByText(/A Nota Geral é legado/)).toBeInTheDocument();
    // O "(PRD §41)" saiu do texto mostrado ao usuário.
    expect(screen.queryByText(/PRD/)).toBeNull();
  });

  it("régua personalizada: os pesos do editor são os que valem na Nota Geral", async () => {
    carregarSucesso();
    responder("GET", URL_REGRA, regraFake("personalizado"));
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    expect(
      await screen.findByText("Esta escola usa uma régua personalizada: os pesos abaixo estão em uso na Nota Geral."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Régua Padrão Constela/)).toBeNull();
  });

  it("sem conseguir ler a régua, não afirma qual vale", async () => {
    carregarSucesso();
    responderErro("GET", URL_REGRA, 403, "Sem acesso");
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    expect(await screen.findByText("Não foi possível verificar a régua em uso agora.")).toBeInTheDocument();
    expect(screen.queryByText(/Régua Padrão Constela/)).toBeNull();
    expect(screen.queryByText(/régua personalizada:/)).toBeNull();
  });

  it("mostra o erro quando os pesos não carregam", async () => {
    // Aparência ok; pesos falham -> PesosEditor renderiza a mensagem de erro.
    responder("GET", URL_APARENCIA, { cor_primaria: "#1B2A4A" });
    responderErro("GET", URL_PESOS, 500, "Falha ao carregar pesos");
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    expect(await screen.findByText("Falha ao carregar pesos")).toBeInTheDocument();
  });

  // GOVERNANÇA: restaurar backup substitui livros, leituras, faixas, pesos e
  // parâmetros de pontuação — exclusivo do Admin Global (o backend dá 403 aos
  // demais). Baixar o backup continua com o admin da escola.
  it("admin da escola baixa o backup, mas não vê a ação de restaurar", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    const baixar = await screen.findByRole("button", { name: /Baixar backup/ });
    expect(screen.queryByRole("button", { name: /Restaurar de um arquivo/ })).toBeNull();
    expect(screen.getByText(/só o Admin Global pode fazer isso/)).toBeInTheDocument();

    await u.click(baixar);
    expect(apiDownload).toHaveBeenCalledWith("/escolas/1/backup");
  });

  it("logos da cidade: no celular o botão Enviar desce para baixo do texto e tem 40 px", async () => {
    carregarSucesso();
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    const brasao = await screen.findByText("Brasão da cidade");
    expect(screen.getByText("Logo da prefeitura")).toBeInTheDocument();
    const enviar = screen.getAllByRole("button", { name: "Enviar" });
    expect(enviar).toHaveLength(2);
    for (const botao of enviar) {
      expect(botao).toHaveClass("max-sm:min-h-10");
      // As ações ocupam a linha inteira abaixo do texto no celular (a linha quebra).
      expect(botao.parentElement).toHaveClass("max-sm:w-full", "max-sm:flex-row");
    }
    const linha = enviar[0].parentElement?.parentElement as HTMLElement;
    expect(linha).toContainElement(brasao);
    expect(linha).toHaveClass("flex-wrap", "sm:flex-nowrap");
  });

  it("Assistente de IA no padrão dos outros blocos: título dentro do cartão e um robô só", async () => {
    // Revisão v2: o título ficava FORA do cartão e o ícone do robô se repetia dentro dele.
    carregarSucesso();
    responder("GET", "/escolas/1/assistente/config", { provedor: "local", modelo: "", chave_definida: false });
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    const regiao = await screen.findByRole("region", { name: "Assistente de IA" });
    await within(regiao).findByText(/Modo local: nada sai do servidor/);
    const titulo = within(regiao).getByRole("heading", { name: "Assistente de IA", level: 2 });
    // O cartão (.card) que tem o título é o mesmo que tem o estado e as ações.
    const cartao = titulo.closest(".card") as HTMLElement;
    expect(cartao).not.toBeNull();
    expect(within(cartao).getByText(/Modo local: nada sai do servidor/)).toBeInTheDocument();
    expect(within(cartao).getByRole("button", { name: "Testar o assistente" })).toBeInTheDocument();
    expect(regiao.querySelectorAll("svg.lucide-bot")).toHaveLength(1);
  });

  it("Admin Global vê a ação de restaurar e restaura de um arquivo", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responder("UPLOAD", "/escolas/1/restaurar", {
      mensagem: "Backup restaurado: 12 registros. Notas recalculadas.",
    });
    const { container } = renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: true }),
    });

    expect(
      await screen.findByRole("button", { name: /Restaurar de um arquivo/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/só o Admin Global pode fazer isso/)).toBeNull();

    const entrada = container.querySelector<HTMLInputElement>('input[type="file"][accept=".json"]');
    expect(entrada).not.toBeNull();
    await u.upload(entrada!, new File(["{}"], "backup.json", { type: "application/json" }));

    // Escolher o arquivo só abre a confirmação: nada é enviado antes do "sim".
    const dialogo = await screen.findByRole("dialog", { name: "Restaurar este backup?" });
    expect(apiUpload).not.toHaveBeenCalled();
    expect(dialogo).toHaveTextContent("backup.json");
    // A confirmação diz o que a restauração NÃO toca (travas da sincronização).
    expect(dialogo).toHaveTextContent(/política de criação de alunos/);
    expect(dialogo).toHaveTextContent(/vínculo\s+da escola externa/);
    await u.click(within(dialogo).getByRole("button", { name: "Substituir os dados" }));

    expect(
      await screen.findByText("Backup restaurado: 12 registros. Notas recalculadas."),
    ).toBeInTheDocument();
    expect(apiUpload).toHaveBeenCalledWith("/escolas/1/restaurar", expect.any(FormData));
    expect(apiUpload).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Restaurar este backup?" })).toBeNull();
    // Sem conta de outra escola, nenhum aviso do D10.
    expect(screen.queryByRole("alert", { name: "Avisos da restauração" })).toBeNull();
  });

  it("Admin Global que cancela a confirmação não restaura nada", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responder("UPLOAD", "/escolas/1/restaurar", { mensagem: "não deveria chegar aqui" });
    const { container } = renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: true }),
    });

    await screen.findByRole("button", { name: /Restaurar de um arquivo/ });
    const entrada = container.querySelector<HTMLInputElement>('input[type="file"][accept=".json"]');
    await u.upload(entrada!, new File(["{}"], "backup.json", { type: "application/json" }));
    const dialogo = await screen.findByRole("dialog", { name: "Restaurar este backup?" });
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog", { name: "Restaurar este backup?" })).toBeNull();
    expect(apiUpload).not.toHaveBeenCalled();
    expect(screen.queryByText("não deveria chegar aqui")).toBeNull();
    // O arquivo é esquecido: escolher de novo reabre a confirmação.
    expect(entrada!.value).toBe("");
  });

  it("restauração que faz uma conta valer também aqui mostra o aviso do D10 (avisos)", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    const aviso =
      "Atenção: esta conta da plataforma continua vinculada a um aluno de outra escola do Constela, que não foi alterada.";
    responder("UPLOAD", "/escolas/1/restaurar", {
      mensagem: "Backup restaurado: 12 registros. Notas recalculadas.",
      tabelas: { alunos: 3 },
      avisos: [aviso],
    });
    const { container } = renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: true }),
    });

    await screen.findByRole("button", { name: /Restaurar de um arquivo/ });
    const entrada = container.querySelector<HTMLInputElement>('input[type="file"][accept=".json"]');
    await u.upload(entrada!, new File(["{}"], "backup.json", { type: "application/json" }));
    const dialogo = await screen.findByRole("dialog", { name: "Restaurar este backup?" });
    await u.click(within(dialogo).getByRole("button", { name: "Substituir os dados" }));

    expect(
      await screen.findByText("Backup restaurado: 12 registros. Notas recalculadas."),
    ).toBeInTheDocument();
    const alerta = await screen.findByRole("alert", { name: "Avisos da restauração" });
    expect(alerta).toHaveTextContent(aviso);
  });
});
