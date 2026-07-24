/**
 * Configuração do Painel Público — a tela que controla a PRIVACIDADE das
 * crianças no telão sem senha. Regressão aqui é grave (LGPD/ECA), então cobrimos
 * o padrão protegido e o gesto consciente para expor.
 */
import { vi } from "vitest";

import PainelPublicoConfig from "../pages/PainelPublicoConfig";
import { renderComApp, responder, screen, userEvent } from "./utils";

interface ConfigOver {
  ativo?: boolean;
  anonimizar?: boolean;
}

function responderConfig(over: ConfigOver = {}) {
  responder("GET", "/escolas/1/painel-publico", {
    ativo: over.ativo ?? true,
    slides: ["ranking", "evolucao", "destaques", "mural"],
    intervalo_s: 12,
    max_posicoes: 10,
    anonimizar: over.anonimizar ?? true,
    url: "https://www.constelaedu.com/p/tok123",
  });
}

test("a proteção do nome das crianças vem LIGADA por padrão", async () => {
  responderConfig({ anonimizar: true });
  renderComApp(<PainelPublicoConfig />);
  const toggle = await screen.findByLabelText(/Proteger o nome dos alunos/i);
  expect(toggle).toBeChecked();
});

test("o aviso de privacidade aparece mesmo com o painel DESATIVADO", async () => {
  responderConfig({ ativo: false, anonimizar: true });
  renderComApp(<PainelPublicoConfig />);
  // O card de privacidade não fica mais escondido atrás de "painel ativo".
  expect(await screen.findByText(/Privacidade dos alunos/i)).toBeInTheDocument();
  expect(await screen.findByLabelText(/Proteger o nome dos alunos/i)).toBeChecked();
});

test("desligar a proteção PEDE confirmação; se recusar, continua protegido", async () => {
  responderConfig({ anonimizar: true });
  const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderComApp(<PainelPublicoConfig />);
  const toggle = await screen.findByLabelText(/Proteger o nome dos alunos/i);

  await userEvent.click(toggle);

  expect(confirmar).toHaveBeenCalled(); // avisou antes de expor
  expect(toggle).toBeChecked(); // recusou → nada mudou, segue protegido
  confirmar.mockRestore();
});
