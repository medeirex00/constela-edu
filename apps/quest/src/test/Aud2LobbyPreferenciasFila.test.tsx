/**
 * Mochila do Lobby: toques rápidos em "Efeitos" e "Narração" viram UM PATCH por vez,
 * na ordem dos toques (G_QUEST-3, REV2-QUEST-1).
 *
 * Cada toque disparava o PATCH /preferencias em paralelo e a tela aplicava a resposta
 * que chegasse por último — não necessariamente a do último toque. Com o servidor já
 * serializando as gravações, a resposta do toque anterior podia chegar depois e trazer
 * as preferências SEM a troca seguinte: o banco guardava as duas, mas a tela (e o som e
 * a narração, que leem perfil.preferencias) ficava com a resposta velha. Na fila, o 2º
 * PATCH só sai depois da resposta do 1º — o mesmo padrão do vestiário. Dados fictícios.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const quest = vi.hoisted(() => ({ trocarPreferencias: vi.fn() }));
const sessao = vi.hoisted(() => ({ atualizarPerfil: vi.fn() }));
const audio = vi.hoisted(() => ({ configurarAudio: vi.fn(), narrar: vi.fn(), tocar: vi.fn() }));

vi.mock("@constela/quest-core", () => quest);
vi.mock("../estado/sessao", () => ({
  useSessao: () => ({ perfil: PERFIL, atualizarPerfil: sessao.atualizarPerfil, sair: vi.fn() }),
}));
vi.mock("../audio/audio", () => audio);
// WebGL, cena e telas vizinhas não interessam aqui (e não existem no jsdom).
vi.mock("../carreira/Carreira", () => ({ Carreira: () => null }));
vi.mock("../cosmo/Cosmo", () => ({ Cosmo: () => null }));
vi.mock("../personagem/Palco3D", () => ({ Palco3D: () => null }));
vi.mock("../vestiario/Vestiario", () => ({ Vestiario: () => null }));
vi.mock("../lobby/Cena", () => ({ Cena: () => null }));
vi.mock("../lobby/Ceu", () => ({ Ceu: () => null }));

import { Lobby } from "../lobby/Lobby";

const PERFIL = {
  nome: "Bia", nome_exibicao: "Bia", apelido: "Estrela Valente", codigo_amigo: "COSMO-AAAA",
  nivel: 1, xp_total: 0, moedas: 0, estrelas_total: 0, sequencia_dias: 0, dias_sem_jogar: 0,
  avatar: {}, preferencias: { som: true, narracao: true },
};

function adiada<T>() {
  let resolver!: (v: T) => void;
  const promessa = new Promise<T>((r) => { resolver = r; });
  return { promessa, resolver };
}

beforeEach(() => {
  quest.trocarPreferencias.mockReset();
  sessao.atualizarPerfil.mockReset();
  audio.tocar.mockReset();
});

it("o 2º toque só envia depois da resposta do 1º, e as respostas entram na ordem", async () => {
  const primeira = adiada<unknown>();
  const segunda = adiada<unknown>();
  quest.trocarPreferencias
    .mockReturnValueOnce(primeira.promessa)
    .mockReturnValueOnce(segunda.promessa);
  render(<Lobby />);

  fireEvent.click(screen.getByRole("button", { name: /Efeitos/ }));
  fireEvent.click(screen.getByRole("button", { name: /Narração/ }));
  await Promise.resolve();
  expect(quest.trocarPreferencias).toHaveBeenCalledTimes(1);
  expect(quest.trocarPreferencias).toHaveBeenLastCalledWith({ som: false });

  const resposta1 = { ...PERFIL, preferencias: { som: false, narracao: true } };
  primeira.resolver(resposta1);
  await waitFor(() => expect(quest.trocarPreferencias).toHaveBeenCalledTimes(2));
  expect(quest.trocarPreferencias).toHaveBeenLastCalledWith({ narracao: false });

  const resposta2 = { ...PERFIL, preferencias: { som: false, narracao: false } };
  segunda.resolver(resposta2);
  await waitFor(() => expect(sessao.atualizarPerfil).toHaveBeenCalledTimes(2));
  // A última resposta aplicada é a que traz as duas trocas.
  expect(sessao.atualizarPerfil.mock.calls.map((c) => c[0])).toEqual([resposta1, resposta2]);
});

it("uma troca que falha não trava a fila: avisa e o toque seguinte ainda é enviado", async () => {
  quest.trocarPreferencias
    .mockRejectedValueOnce(new Error("rede"))
    .mockResolvedValueOnce({ ...PERFIL, preferencias: { som: true, narracao: false } });
  render(<Lobby />);

  fireEvent.click(screen.getByRole("button", { name: /Efeitos/ }));
  fireEvent.click(screen.getByRole("button", { name: /Narração/ }));
  await waitFor(() => expect(quest.trocarPreferencias).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(sessao.atualizarPerfil).toHaveBeenCalledTimes(1));
  expect(screen.getByText("Não consegui salvar. Tente de novo!")).toBeInTheDocument();
});
