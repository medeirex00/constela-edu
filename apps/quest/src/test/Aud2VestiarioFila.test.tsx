/**
 * Vestiário: toques rápidos viram UM PATCH por vez, na ordem dos toques (G_QUEST-3).
 *
 * Cada toque disparava `void definir()` em paralelo e a tela aplicava a resposta que
 * chegasse por último — não necessariamente a do último toque. Com o servidor já
 * serializando as gravações, a resposta do toque anterior pode chegar depois e trazer
 * o avatar SEM a troca seguinte: o item "voltava" na tela. Na fila, o 2º PATCH só sai
 * depois da resposta do 1º, e a última resposta aplicada é a que traz todas as trocas.
 * Dados fictícios.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const quest = vi.hoisted(() => ({ trocarAvatar: vi.fn(), escolherNome: vi.fn() }));
const sessao = vi.hoisted(() => ({ atualizarPerfil: vi.fn() }));

vi.mock("@constela/quest-core", () => quest);
vi.mock("../estado/sessao", () => ({
  useSessao: () => ({ perfil: PERFIL, atualizarPerfil: sessao.atualizarPerfil }),
}));
// WebGL e animações não existem no jsdom.
vi.mock("../personagem/Palco3D", () => ({ Palco3D: () => null }));
vi.mock("../lobby/AmbienteEspacial", () => ({ AmbienteEspacial: () => null }));
vi.mock("../cosmo/InvocacaoSkate", () => ({ InvocacaoSkate: () => null }));

import { Vestiario } from "../vestiario/Vestiario";

const PERFIL = {
  nome: "Bia", nome_exibicao: "Bia", nivel: 1, xp_total: 0, moedas: 0,
  estrelas_total: 0, sequencia_dias: 0, dias_sem_jogar: 0,
  avatar: { top: "camiseta", pele: "#F6C8A0" }, preferencias: {},
};

function adiada<T>() {
  let resolver!: (v: T) => void;
  const promessa = new Promise<T>((r) => { resolver = r; });
  return { promessa, resolver };
}

beforeEach(() => {
  quest.trocarAvatar.mockReset();
  sessao.atualizarPerfil.mockReset();
});

it("o 2º toque só envia depois da resposta do 1º, e as respostas entram na ordem", async () => {
  const primeira = adiada<unknown>();
  const segunda = adiada<unknown>();
  quest.trocarAvatar
    .mockReturnValueOnce(primeira.promessa)
    .mockReturnValueOnce(segunda.promessa);
  render(<Vestiario />);

  fireEvent.click(screen.getByRole("button", { name: "Moletom" }));
  fireEvent.click(screen.getByRole("button", { name: "Jaqueta" }));
  await Promise.resolve();
  expect(quest.trocarAvatar).toHaveBeenCalledTimes(1);
  expect(quest.trocarAvatar).toHaveBeenLastCalledWith({ top: "moletom" });

  const resposta1 = { ...PERFIL, avatar: { ...PERFIL.avatar, top: "moletom" } };
  primeira.resolver(resposta1);
  await waitFor(() => expect(quest.trocarAvatar).toHaveBeenCalledTimes(2));
  expect(quest.trocarAvatar).toHaveBeenLastCalledWith({ top: "jaqueta" });

  const resposta2 = { ...PERFIL, avatar: { ...PERFIL.avatar, top: "jaqueta" } };
  segunda.resolver(resposta2);
  await waitFor(() => expect(sessao.atualizarPerfil).toHaveBeenCalledTimes(2));
  expect(sessao.atualizarPerfil.mock.calls.map((c) => c[0])).toEqual([resposta1, resposta2]);
});

it("uma troca que falha não trava a fila: o toque seguinte ainda é enviado", async () => {
  quest.trocarAvatar
    .mockRejectedValueOnce(new Error("rede"))
    .mockResolvedValueOnce({ ...PERFIL, avatar: { ...PERFIL.avatar, top: "jaqueta" } });
  render(<Vestiario />);

  fireEvent.click(screen.getByRole("button", { name: "Moletom" }));
  fireEvent.click(screen.getByRole("button", { name: "Jaqueta" }));
  await waitFor(() => expect(quest.trocarAvatar).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(sessao.atualizarPerfil).toHaveBeenCalledTimes(1));
});
