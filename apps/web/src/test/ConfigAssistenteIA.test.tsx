/**
 * Assistente de IA (P9): ligar/configurar o provedor EXTERNO e gravar a chave é
 * do Admin Global. O admin da escola vê o estado, desliga (volta ao modo local)
 * e testa — sem seletor de provedor externo, sem campo de chave. O backend é a
 * trava real (tests/test_ia_provedor_externo_admin_global.py); aqui é a tela.
 */
import { describe, expect, it } from "vitest";

import ConfigAssistenteIA from "../components/ConfigAssistenteIA";
import {
  api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, within,
} from "./utils";

const URL_CONFIG = "/escolas/1/assistente/config";
const adminEscola = usuarioFake({ is_global: false, cargo: "admin", nome: "Admin Local" });
const global = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });

interface Config { provedor: string; modelo: string; chave_definida: boolean }

/** GET da configuração com estado: o PUT muda o que o próximo GET devolve. */
function servidor(inicial: Config) {
  let atual = inicial;
  const puts: Record<string, unknown>[] = [];
  responder("GET", URL_CONFIG, () => atual);
  responder("PUT", URL_CONFIG, (_c: string, opcoes: RequestInit | FormData) => {
    const corpo = JSON.parse(String((opcoes as RequestInit).body));
    puts.push(corpo);
    atual = { provedor: corpo.provedor, modelo: corpo.modelo ?? "", chave_definida: false };
    return atual;
  });
  return puts;
}

describe("Configuração do Assistente de IA", () => {
  it("admin da escola vê a IA externa ligada pelo global e a desliga", async () => {
    const u = userEvent.setup();
    const puts = servidor({ provedor: "anthropic", modelo: "claude-ficticio", chave_definida: true });
    renderComApp(<ConfigAssistenteIA />, { usuario: adminEscola });

    expect(await screen.findByText(/Claude \(Anthropic\)/)).toBeInTheDocument();
    expect(screen.getByText(/modelo claude-ficticio/)).toBeInTheDocument();
    expect(screen.getByText(/chave configurada/)).toBeInTheDocument();
    expect(screen.getByText(/fora do país/)).toBeInTheDocument();
    // Nada de ligar/configurar: sem seletor de provedor, sem campo de chave, sem "Salvar".
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByPlaceholderText(/chave/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Salvar" })).toBeNull();

    await u.click(screen.getByRole("button", { name: "Desligar a IA externa" }));
    // Pede confirmação antes de gravar: abrir o diálogo não chama a API.
    const dialogo = await screen.findByRole("dialog", { name: "Desligar a IA externa?" });
    expect(dialogo).toHaveTextContent(/a chave salva é\s+apagada/);
    expect(puts).toEqual([]);
    await u.click(within(dialogo).getByRole("button", { name: "Desligar" }));

    expect(await screen.findByText("IA externa desligada. O assistente voltou ao modo local."))
      .toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Desligar a IA externa?" })).toBeNull();
    expect(puts).toEqual([{ provedor: "local", api_key: null, modelo: null }]);
    // Recarregado: modo local, sem botão de desligar.
    expect(await screen.findByText(/exclusivo\s+do Admin Global/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desligar a IA externa" })).toBeNull();
  });

  it("admin da escola que cancela a confirmação não desliga nada", async () => {
    const u = userEvent.setup();
    const puts = servidor({ provedor: "openai", modelo: "", chave_definida: true });
    renderComApp(<ConfigAssistenteIA />, { usuario: adminEscola });

    await u.click(await screen.findByRole("button", { name: "Desligar a IA externa" }));
    const dialogo = await screen.findByRole("dialog", { name: "Desligar a IA externa?" });
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog", { name: "Desligar a IA externa?" })).toBeNull();
    expect(puts).toEqual([]);
    expect(api).not.toHaveBeenCalledWith(URL_CONFIG, expect.objectContaining({ method: "PUT" }));
    // Segue ligada: o botão de desligar continua na tela.
    expect(screen.getByRole("button", { name: "Desligar a IA externa" })).toBeInTheDocument();
  });

  it("admin da escola no modo local: vê o estado e só testa", async () => {
    const u = userEvent.setup();
    servidor({ provedor: "local", modelo: "", chave_definida: false });
    responder("POST", "/escolas/1/assistente/config/testar", { ok: true, provedor: "local" });
    renderComApp(<ConfigAssistenteIA />, { usuario: adminEscola });

    expect(await screen.findByText(/exclusivo\s+do Admin Global/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("option", { name: /Anthropic/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Desligar a IA externa" })).toBeNull();

    await u.click(screen.getByRole("button", { name: "Testar o assistente" }));
    expect(await screen.findByText(/respondeu pelo provedor "local"/)).toBeInTheDocument();
  });

  it("Admin Global escolhe o provedor externo, cola a chave e salva", async () => {
    const u = userEvent.setup();
    const puts = servidor({ provedor: "local", modelo: "", chave_definida: false });
    renderComApp(<ConfigAssistenteIA />, { usuario: global });

    const seletor = await screen.findByRole("combobox");
    // Nome do campo pelo rótulo; select nativo com a seta da v2 e espaço para ela (o
    // texto longo do "Modo local" não encosta mais na seta no celular).
    expect(screen.getByRole("combobox", { name: "Provedor" })).toBe(seletor);
    expect(seletor).toHaveClass("appearance-none", "truncate", "pr-10");
    expect(screen.getByRole("option", { name: /Anthropic/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenAI" })).toBeInTheDocument();
    await u.selectOptions(seletor, "anthropic");
    expect(screen.getByText(/fora do país/)).toBeInTheDocument();
    await u.type(screen.getByPlaceholderText("cole aqui a chave de API"), "sk-ant-ficticia");
    await u.click(screen.getByRole("button", { name: "Salvar" }));

    expect(await screen.findByText("Configuração salva.")).toBeInTheDocument();
    expect(puts).toEqual([{ provedor: "anthropic", api_key: "sk-ant-ficticia", modelo: null }]);
  });
});

describe("Chave de IA sem uso (chave_definida=false com provedor externo)", () => {
  // O backend devolve chave_definida=false também para a cifra que não abre mais
  // (DATA_ENCRYPTION_KEY trocada) e recusa o "Salvar" em branco com este 400.
  const semChaveUtil: Config = { provedor: "anthropic", modelo: "", chave_definida: false };
  const recusa = "A chave de API salva não abre mais com a chave de cifra do servidor "
    + "(trocada desde que foi gravada): informe a chave de API de novo.";

  it("Admin Global: o rótulo não diz 'nenhuma chave salva' ao lado da recusa do servidor", async () => {
    const u = userEvent.setup();
    responder("GET", URL_CONFIG, semChaveUtil);
    responderErro("PUT", URL_CONFIG, 400, recusa);
    renderComApp(<ConfigAssistenteIA />, { usuario: global });

    expect(await screen.findByText("nenhuma chave utilizável: informe a chave de API"))
      .toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText(/A chave de API salva não abre mais/)).toBeInTheDocument();
    expect(screen.queryByText(/nenhuma chave salva/)).toBeNull();
  });

  it("admin da escola: diz que o assistente responde no modo local, não 'sem chave salva'", async () => {
    responder("GET", URL_CONFIG, semChaveUtil);
    renderComApp(<ConfigAssistenteIA />, { usuario: adminEscola });

    expect(await screen.findByText(/sem chave utilizável: o assistente responde no modo local/))
      .toBeInTheDocument();
    expect(screen.queryByText(/sem chave salva/)).toBeNull();
  });
});
