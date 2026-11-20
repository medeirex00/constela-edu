/**
 * Gestão de redes — códigos INEP das escolas: o 409 do backend (o código já é de
 * OUTRA escola) aparece com a mensagem dele, escola por escola — "N com erro"
 * sozinho não diz qual código está repetido nem de quem ele é. E o salvamento em
 * lote não depende da ordem da lista: quem limpa vai antes e o 409 tenta de novo
 * enquanto houver progresso (a troca A↔B continua erro, sem repetir sem fim). A dica
 * "Como resolver" só aparece quando as esperas fecham um ciclo dentro do lote; uma
 * cadeia que termina numa escola fora do lote fica só com a mensagem do backend.
 *
 * Escolas, nomes e códigos FICTÍCIOS.
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "../lib/api";
import RedeGestao from "../pages/rede/RedeGestao";
import { api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor, within } from "./utils";

const adminGlobal = usuarioFake({ nome: "Admin Global", cargo: "admin", is_global: true, escola_id: null });

function escola(id: number, nome: string, codigo_inep: string | null, rede_id = 1) {
  return { id, nome, cidade: null, estado: null, bairro: null, status: "ativa", rede_id,
           latitude: null, longitude: null, codigo_inep };
}

const MSG_409 = "O código INEP 35990001 já pertence à escola “EMEF Sintética Alfa” (id 11). Cada escola tem "
  + "o seu INEP: confira o código ou corrija primeiro a outra escola. Nada foi alterado.";

describe("Gestão de redes — códigos INEP", () => {
  it("o 409 de INEP de outra escola mostra a mensagem do backend, com o nome da escola", async () => {
    responder("GET", "/redes/gerenciar", {
      redes: [{ id: 1, nome: "Rede Sintética", uf: "SP", codigo_ibge: null, status: "ativa" }],
      escolas: [escola(11, "EMEF Sintética Alfa", "35990001"), escola(14, "ESCOLA SINTETICA GAMA", null),
                escola(13, "EMEF Sintética Delta", null)],
      usuarios: [],
    });
    responder("GET", "/redes/1/modulos", []);
    responderErro("PATCH", "/redes/escolas/14", 409, MSG_409);
    responder("PATCH", "/redes/escolas/13", { id: 13, codigo_inep: "35990004" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });

    // Os códigos salvos entram juntos no formulário, depois de o título aparecer.
    await screen.findByDisplayValue("35990001");
    const campos = screen.getAllByPlaceholderText("código INEP");        // Alfa, Gama, Delta
    await u.type(campos[1], "35990001");
    await u.type(campos[2], "35990004");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));

    const aviso = (await screen.findByText(/1 código\(s\) salvo\(s\); 1 com erro:/)).closest('[role="alert"]')!;
    expect(aviso).not.toBeNull();
    expect(screen.getByTestId("aviso-detalhes")).toHaveTextContent(`ESCOLA SINTETICA GAMA: ${MSG_409}`);
    expect(aviso.textContent).not.toContain("EMEF Sintética Delta:");     // a que salvou não é erro
    // A Alfa (dona do código) não está no lote: não é troca, a mensagem do backend basta.
    expect(aviso.textContent).not.toContain("Como resolver");
    expect(api).toHaveBeenCalledWith("/redes/escolas/13", expect.objectContaining({ method: "PATCH" }));
  });

  /** O código em 8 dígitos, como o `normalizar_inep` do backend ("035990001" = "35990001"). */
  function normalizado(v: string | null): string | null {
    const digitos = (v ?? "").trim().replace(/\.0$/, "").replace(/\D/g, "");
    return digitos ? digitos.padStart(8, "0").slice(-8) : null;
  }

  /** Backend FALSO com a trava de INEP único: 409 se o código ainda é de outra escola. */
  function backendInep(inicial: Record<number, string | null>) {
    const codigos: Record<number, string | null> = { ...inicial };
    const ordem: number[] = [];
    responder("PATCH", /^\/redes\/escolas\/\d+$/, (caminho: string, opcoes: unknown) => {
      const id = Number(caminho.split("/").pop());
      const valor = normalizado(JSON.parse(String((opcoes as RequestInit).body)).codigo_inep as string);
      ordem.push(id);
      const dono = Object.entries(codigos).find(([outra, c]) => Number(outra) !== id && valor && normalizado(c) === valor);
      if (dono) return new ApiError(409, `O código INEP ${valor} já pertence à escola (id ${dono[0]}).`);
      codigos[id] = valor;
      return { id, codigo_inep: valor };
    });
    return { codigos, ordem };
  }

  function semearRede(escolas: ReturnType<typeof escola>[]) {
    responder("GET", "/redes/gerenciar", {
      redes: [{ id: 1, nome: "Rede Sintética", uf: "SP", codigo_ibge: null, status: "ativa" }],
      escolas, usuarios: [],
    });
    responder("GET", "/redes/1/modulos", []);
  }

  it("mover o código de uma escola para outra e limpar a primeira salva de uma vez (a que limpa vai antes)", async () => {
    semearRede([escola(11, "EMEF Sintética Alfa", null), escola(12, "EMEF Sintética Beta", "35990002")]);
    const fake = backendInep({ 11: null, 12: "35990002" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByDisplayValue("35990002");
    const [alfa, beta] = screen.getAllByPlaceholderText("código INEP");
    await u.type(alfa, "35990002");
    await u.clear(beta);
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText("2 código(s) salvo(s).")).toBeInTheDocument();
    expect(fake.ordem).toEqual([12, 11]);                          // a Beta (limpa) primeiro
    expect(fake.codigos).toEqual({ 11: "35990002", 12: null });
  });

  it("em cadeia (A recebe o de B, B recebe um novo), o 409 tenta de novo e salva tudo", async () => {
    semearRede([escola(11, "EMEF Sintética Alfa", null), escola(12, "EMEF Sintética Beta", "35990002")]);
    const fake = backendInep({ 11: null, 12: "35990002" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByDisplayValue("35990002");
    const [alfa, beta] = screen.getAllByPlaceholderText("código INEP");
    await u.type(alfa, "35990002");
    await u.clear(beta);
    await u.type(beta, "35990003");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText("2 código(s) salvo(s).")).toBeInTheDocument();
    expect(fake.ordem).toEqual([11, 12, 11]);                      // 409, salva, de novo
    expect(fake.codigos).toEqual({ 11: "35990002", 12: "35990003" });
  });

  it("uma troca (A↔B) não tem ordem que resolva: para sem repetir sem fim, mostra os dois 409 e o que resolve", async () => {
    semearRede([escola(11, "EMEF Sintética Alfa", "35990001"), escola(12, "EMEF Sintética Beta", "35990002")]);
    const fake = backendInep({ 11: "35990001", 12: "35990002" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByDisplayValue("35990001");
    const [alfa, beta] = screen.getAllByPlaceholderText("código INEP");
    await u.clear(alfa);
    await u.type(alfa, "35990002");
    await u.clear(beta);
    await u.type(beta, "35990001");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText(/0 código\(s\) salvo\(s\); 2 com erro:/)).toBeInTheDocument();
    expect(fake.ordem).toEqual([11, 12]);                          // uma passada só
    const detalhes = screen.getByTestId("aviso-detalhes");
    expect(detalhes).toHaveTextContent("EMEF Sintética Alfa: O código INEP 35990002");
    // Os 409 dizem "corrija primeiro a outra escola" (circular): a dica diz o que resolve.
    expect(detalhes).toHaveTextContent(/Como resolver: .*trocados entre escolas deste lote.*Apague o código de uma delas/);
    expect(fake.codigos).toEqual({ 11: "35990001", 12: "35990002" });
  });

  it("um ciclo (A→B→C→A) também é troca: uma passada, três 409 e a dica", async () => {
    semearRede([escola(11, "EMEF Sintética Alfa", "35990001"), escola(12, "EMEF Sintética Beta", "35990002"),
                escola(13, "EMEF Sintética Gama", "35990003")]);
    const fake = backendInep({ 11: "35990001", 12: "35990002", 13: "35990003" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByDisplayValue("35990001");
    const [a, b, c] = screen.getAllByPlaceholderText("código INEP");
    await u.clear(a); await u.type(a, "35990002");
    await u.clear(b); await u.type(b, "35990003");
    await u.clear(c); await u.type(c, "35990001");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText(/0 código\(s\) salvo\(s\); 3 com erro:/)).toBeInTheDocument();
    expect(fake.ordem).toEqual([11, 12, 13]);
    expect(screen.getByTestId("aviso-detalhes")).toHaveTextContent(/Como resolver:/);
  });

  it("uma cadeia que termina FORA do lote (A quer o de B; B quer o de uma escola de outra rede) não é troca: sem a dica", async () => {
    responder("GET", "/redes/gerenciar", {
      redes: [{ id: 1, nome: "Rede Sintética", uf: "SP", codigo_ibge: null, status: "ativa" },
              { id: 2, nome: "Rede Vizinha", uf: "SP", codigo_ibge: null, status: "ativa" }],
      escolas: [escola(11, "EMEF Sintética Alfa", "35990001"), escola(12, "EMEF Sintética Beta", "35990002"),
                escola(19, "EMEF Sintética Zeta", "35990009", 2)],
      usuarios: [],
    });
    responder("GET", "/redes/1/modulos", []);
    const fake = backendInep({ 11: "35990001", 12: "35990002", 19: "35990009" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByText("Códigos INEP das escolas");
    const alfa = screen.getByRole("textbox", { name: "Código INEP de EMEF Sintética Alfa" });
    const beta = screen.getByRole("textbox", { name: "Código INEP de EMEF Sintética Beta" });
    // O título aparece antes de o efeito preencher os campos com os códigos da rede.
    await waitFor(() => {
      expect(alfa).toHaveValue("35990001");
      expect(beta).toHaveValue("35990002");
    });
    await u.clear(alfa); await u.type(alfa, "35990002");
    await u.clear(beta); await u.type(beta, "35990009");
    expect(alfa).toHaveValue("35990002");
    expect(beta).toHaveValue("35990009");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText(/0 código\(s\) salvo\(s\); 2 com erro:/)).toBeInTheDocument();
    expect(fake.ordem).toEqual([11, 12]);
    // Quem segura é a Zeta, fora do lote: apagar o código da Alfa ou da Beta não resolve a
    // Beta — a mensagem do backend (de quem é o código) é o que orienta.
    const detalhes = screen.getByTestId("aviso-detalhes");
    expect(detalhes).toHaveTextContent("EMEF Sintética Beta: O código INEP 35990009 já pertence à escola (id 19).");
    expect(detalhes).not.toHaveTextContent(/Como resolver/);
  });

  it("quem espera por uma escola presa numa troca (D quer o de A; A↔B) também recebe a dica", async () => {
    semearRede([escola(11, "EMEF Sintética Alfa", "35990001"), escola(12, "EMEF Sintética Beta", "35990002"),
                escola(13, "EMEF Sintética Delta", null)]);
    const fake = backendInep({ 11: "35990001", 12: "35990002", 13: null });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByDisplayValue("35990001");
    const [a, b, d] = screen.getAllByPlaceholderText("código INEP");
    await u.clear(a); await u.type(a, "35990002");
    await u.clear(b); await u.type(b, "35990001");
    await u.type(d, "035990001");                                   // o de A, com outra grafia
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText(/0 código\(s\) salvo\(s\); 3 com erro:/)).toBeInTheDocument();
    expect(fake.ordem).toEqual([11, 12, 13]);
    expect(screen.getByTestId("aviso-detalhes")).toHaveTextContent(/Como resolver:/);
  });

  it("duas escolas pedem o MESMO código livre: uma salva, a outra leva o 409 sem a dica de troca", async () => {
    semearRede([escola(11, "EMEF Sintética Alfa", null), escola(12, "EMEF Sintética Beta", null)]);
    const fake = backendInep({ 11: null, 12: null });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByText("Códigos INEP das escolas");
    const [alfa, beta] = screen.getAllByPlaceholderText("código INEP");
    await u.type(alfa, "35990007");
    await u.type(beta, "035990007");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText(/1 código\(s\) salvo\(s\); 1 com erro:/)).toBeInTheDocument();
    expect(fake.codigos).toEqual({ 11: "35990007", 12: null });
    expect(screen.getByTestId("aviso-detalhes")).not.toHaveTextContent(/Como resolver/);
  });

  it("sem erro, o aviso continua o de sempre (sem lista)", async () => {
    responder("GET", "/redes/gerenciar", {
      redes: [{ id: 1, nome: "Rede Sintética", uf: "SP", codigo_ibge: null, status: "ativa" }],
      escolas: [escola(13, "EMEF Sintética Delta", null)], usuarios: [],
    });
    responder("GET", "/redes/1/modulos", []);
    responder("PATCH", "/redes/escolas/13", { id: 13, codigo_inep: "35990004" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByText("Códigos INEP das escolas");
    await u.type(screen.getByPlaceholderText("código INEP"), "35990004");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText("1 código(s) salvo(s).")).toBeInTheDocument();
    expect(screen.queryByTestId("aviso-detalhes")).toBeNull();
  });
});

describe("Gestão de redes — rótulo da escola nos campos, no celular", () => {
  it("em Localização e em Códigos INEP o nome ocupa a linha no celular (inteiro) e mantém o w-40 do sm para cima", async () => {
    const NOME = "EMEF Sintética Constelação do Vale Comprido";
    responder("GET", "/redes/gerenciar", {
      redes: [{ id: 1, nome: "Rede Sintética", uf: "SP", codigo_ibge: null, status: "ativa" }],
      escolas: [escola(21, NOME, null)], usuarios: [],
    });
    responder("GET", "/redes/1/modulos", []);
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByText("Códigos INEP das escolas");

    for (const campo of [`Cidade de ${NOME}`, `Código INEP de ${NOME}`]) {
      const linha = screen.getByLabelText(campo).parentElement!;
      const rotulo = within(linha).getByText(NOME);
      expect(rotulo).toHaveAttribute("title", NOME);
      expect(rotulo).toHaveClass("w-full", "max-sm:whitespace-normal", "sm:w-40", "truncate");
      expect(rotulo).not.toHaveClass("w-40");
    }
  });
});
