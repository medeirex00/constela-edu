/**
 * Campo do nome (vestiário e cerimônia): letra invisível não entra (G_QUEST-4).
 *
 * O filtro do campo (/[^\p{L} ]/gu) mantinha o HANGUL FILLER (U+3164, o "nome
 * invisível" que circula em jogos): ele é "letra" para o \p{L}, mas não desenha
 * nada, e a criança passava a ser chamada de "" nas falas e no "É você?". O servidor
 * agora recusa (422); o campo já não deixa o caractere entrar. Dados fictícios.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const quest = vi.hoisted(() => ({
  trocarAvatar: vi.fn(), escolherNome: vi.fn(), personagensBase: vi.fn(),
}));
vi.mock("@constela/quest-core", () => quest);
vi.mock("../estado/sessao", () => ({
  useSessao: () => ({ perfil: PERFIL, atualizarPerfil: vi.fn() }),
}));
vi.mock("../personagem/Palco3D", () => ({ Palco3D: () => null }));
vi.mock("../lobby/AmbienteEspacial", () => ({ AmbienteEspacial: () => null }));
vi.mock("../cosmo/InvocacaoSkate", () => ({ InvocacaoSkate: () => null }));

import { Cerimonia } from "../cerimonia/Cerimonia";
import { soLetrasDoNome } from "../cerimonia/nome";
import { Vestiario } from "../vestiario/Vestiario";

const PERFIL = {
  nome: "Bia", nome_exibicao: "Bia", nivel: 1, xp_total: 0, moedas: 0,
  estrelas_total: 0, sequencia_dias: 0, dias_sem_jogar: 0,
  avatar: {}, preferencias: {},
};

it("o campo do apelido no vestiário descarta o nome invisível", () => {
  render(<Vestiario />);
  const campo = screen.getByLabelText("Meu apelido") as HTMLInputElement;
  fireEvent.change(campo, { target: { value: "\u3164\u3164\u3164" } });
  expect(campo.value).toBe("");
  fireEvent.change(campo, { target: { value: "Lu\u3164a" } });
  expect(campo.value).toBe("Lua");
  expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
});

it("o campo \"Como você quer ser chamado\" da cerimônia descarta o nome invisível", async () => {
  // Cobre a cerimônia de verdade (REV2-QUEST-3): sem este caso, voltar o filtro antigo
  // só na Cerimonia.tsx deixava a suíte verde.
  quest.personagensBase.mockResolvedValue({ astro: { nome: "Astro", top: "camiseta" } });
  quest.trocarAvatar.mockResolvedValue(PERFIL);
  render(<Cerimonia aoConcluir={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: /É esse!/ }));
  const campo = await screen.findByLabelText("Como você quer ser chamado") as HTMLInputElement;
  fireEvent.change(campo, { target: { value: "\u3164\u3164\u3164" } });
  expect(campo.value).toBe("");
  expect(screen.getByRole("button", { name: /Começar!/ })).toBeDisabled();
  fireEvent.change(campo, { target: { value: "Lu\u3164a" } });
  expect(campo.value).toBe("Lua");
  expect(screen.getByRole("button", { name: /Começar!/ })).toBeEnabled();
});

it("o filtro mantém letras com acento e espaço e tira número, símbolo e invisível", () => {
  expect(soLetrasDoNome("João Zoë")).toBe("João Zoë");
  expect(soLetrasDoNome("Ana 2 Luz!")).toBe("Ana  Luz");
  expect(soLetrasDoNome("\uFFA0Mía\u3164")).toBe("Mía");
});
