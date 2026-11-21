/**
 * Perfil PÚBLICO (link do QR do telão): a matéria em que a criança não tem dado
 * mostra "—", nunca "0,0".
 *
 * `PerfilPublico.tsx` chamava `notaDaMateria(valor)` sem o `aferido`: com o 0
 * que o motor grava para quem não é aferido, a página aberta a qualquer um
 * dizia "Leitura 0,0" da criança que só usa o Matific. O servidor agora manda
 * `aferido_leitura`/`aferido_matematica` (e a nota nula); a página respeita o
 * discriminante mesmo que a nota chegue 0. O retrato zerado (aferido) segue
 * "0,0". Achado RANKINGS-9. Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { expect, test } from "vitest";

import PerfilPublico from "../pages/publico/PerfilPublico";
import { renderComApp, responder, screen } from "./utils";

function valorDe(rotulo: string): string {
  const cartao = screen.getByText(rotulo).parentElement as HTMLElement;
  return cartao.querySelector("p:last-child")?.textContent ?? "";
}

function abrir(corpo: Record<string, unknown>) {
  responder("GET", /\/publico\/.+\/alunos\/.+/, {
    nome: "Aluna F.", turma: null, posicao: 2, nivel: 2, xp: 120, conquistas: [],
    escola: "Escola Inventada", ...corpo,
  });
  renderComApp(
    <Routes><Route path="/p/:token/alunos/:id" element={<PerfilPublico />} /></Routes>,
    { rota: "/p/tok123/alunos/7", autenticado: false },
  );
}

test("só Matific: Leitura sai com traço, não com 0,0", async () => {
  abrir({ nota_matific: 70, nota_elefante: 0, aferido_leitura: false, aferido_matematica: true });
  expect(await screen.findByText("Aluna F.")).toBeInTheDocument();
  expect(valorDe("Leitura")).toBe("—");
  expect(valorDe("Matific")).toBe("70,0");
});

test("retrato zerado do Matific (aferido): 0,0 é verdade e continua", async () => {
  abrir({ nota_matific: 0, nota_elefante: null, aferido_leitura: false, aferido_matematica: true });
  expect(await screen.findByText("Aluna F.")).toBeInTheDocument();
  expect(valorDe("Matific")).toBe("0,0");
  expect(valorDe("Leitura")).toBe("—");
});
