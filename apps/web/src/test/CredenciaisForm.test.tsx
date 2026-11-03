import { describe, expect, it } from "vitest";

import { CredenciaisForm } from "../components/CredenciaisForm";
import { renderComApp, responder, screen, userEvent, waitFor, within } from "./utils";

const BASE = "/escolas/1/sync";

describe("CredenciaisForm — escola externa no Testar conexão", () => {
  it("mostra as escolas que a conta enxerga e o aviso, sem segredo", async () => {
    responder("POST", `${BASE}/credenciais/elefante/testar`, {
      ok: true, mensagem: "Conexão bem-sucedida.", codigo: "ok",
      escolas_externas: [{ id: "23952", nome: "EMEF ESCOLA TESTE" }, { id: "23953", nome: "EMEF OUTRA" }],
      escola_vinculada: null, escola_confere: null,
      aviso_escola: "A conta enxerga 2 escolas: escolha qual delas é esta escola antes de sincronizar.",
    });
    renderComApp(<CredenciaisForm base={BASE} plataforma="elefante" nome="Elefante Letrado"
      status="valida" />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Testar conexão" }));
    expect(await screen.findByText("Conexão bem-sucedida.")).toBeInTheDocument();
    expect(screen.getByText("EMEF ESCOLA TESTE (23952); EMEF OUTRA (23953)")).toBeInTheDocument();
    expect(screen.getByText(/escolha qual delas é esta escola/)).toBeInTheDocument();
  });

  it("resposta antiga (sem os campos novos) continua igual", async () => {
    responder("POST", `${BASE}/credenciais/matific/testar`, {
      ok: true, mensagem: "Conexão bem-sucedida.", codigo: "ok" });
    renderComApp(<CredenciaisForm base={BASE} plataforma="matific" nome="Matific"
      status="valida" />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Testar conexão" }));
    expect(await screen.findByText("Conexão bem-sucedida.")).toBeInTheDocument();
    expect(screen.queryByText(/Escola\(s\) que esta conta enxerga/)).toBeNull();
  });
});

describe("CredenciaisForm — credencial ilegível (S16)", () => {
  it("pede o recadastro e não deixa testar uma senha que o servidor não lê", () => {
    renderComApp(<CredenciaisForm base={BASE} plataforma="elefante" nome="Elefante Letrado"
      status="ilegivel" />);
    expect(screen.getByText(/não pode mais ser lida pelo servidor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Testar conexão" })).toBeDisabled();
    expect(screen.getByPlaceholderText("digite a senha de novo")).toBeInTheDocument();
  });

  it("com a credencial legível, nada muda", () => {
    renderComApp(<CredenciaisForm base={BASE} plataforma="elefante" nome="Elefante Letrado"
      status="valida" />);
    expect(screen.queryByText(/não pode mais ser lida pelo servidor/)).toBeNull();
    expect(screen.getByRole("button", { name: "Testar conexão" })).toBeEnabled();
  });
});

describe("CredenciaisForm — formulário e desconexão (identidade v2)", () => {
  it("Enter no campo de senha envia 'Salvar e validar' (é um <form>)", async () => {
    const puts: unknown[] = [];
    responder("PUT", `${BASE}/credenciais/matific`, (_c: string, opcoes: RequestInit | FormData) => {
      puts.push(JSON.parse(String((opcoes as RequestInit).body)));
      return { ok: true, mensagem: "Conexão bem-sucedida.", codigo: "ok" };
    });
    renderComApp(<CredenciaisForm base={BASE} plataforma="matific" nome="Matific" status="nao_configurada" />);
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Usuário do Matific"), "coord@escola");
    await u.type(screen.getByLabelText("Senha do Matific"), "segredo-ficticio{Enter}");
    expect(await screen.findByText("Conexão bem-sucedida.")).toBeInTheDocument();
    expect(puts).toEqual([{ usuario: "coord@escola", senha: "segredo-ficticio" }]);
  });

  it("'Desconectar' pede confirmação antes de remover a credencial", async () => {
    let deletes = 0;
    responder("DELETE", `${BASE}/credenciais/elefante`, () => { deletes += 1; return null; });
    renderComApp(<CredenciaisForm base={BASE} plataforma="elefante" nome="Elefante Letrado" status="valida" />);
    const u = userEvent.setup();

    await u.click(screen.getByRole("button", { name: "Desconectar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Desconectar a escola da plataforma Elefante Letrado?" });
    expect(dialogo).toHaveTextContent("Nenhum dado já coletado é apagado.");
    expect(deletes).toBe(0);

    // Cancelar não remove nada.
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deletes).toBe(0);

    await u.click(screen.getByRole("button", { name: "Desconectar" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Sim, desconectar" }));
    await waitFor(() => expect(deletes).toBe(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("'Opções avançadas' diz se está aberto (aria-expanded)", async () => {
    renderComApp(<CredenciaisForm base={BASE} plataforma="elefante" nome="Elefante Letrado" status="valida" />);
    const botao = screen.getByRole("button", { name: "Opções avançadas" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(botao);
    expect(screen.getByRole("button", { name: "Ocultar opções avançadas" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText(/Endereço de login \(opcional\)/)).toBeInTheDocument();
  });
});
