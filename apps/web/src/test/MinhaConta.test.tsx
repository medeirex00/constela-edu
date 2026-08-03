import { describe, expect, it } from "vitest";

import MinhaConta from "../pages/MinhaConta";
import { renderComApp, screen, usuarioFake } from "./utils";

describe("Minha conta (autoatendimento)", () => {
  it("Secretaria vê os próprios dados (nome, e-mail, perfil) sem depender de escola", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({
        nome: "Secretaria Demo", email: "sec@demo.local",
        cargo: "coordenador", rede_id: 7, escola_id: null,
      }),
    });
    expect(await screen.findByText("Secretaria Demo")).toBeInTheDocument();
    expect(screen.getByText("sec@demo.local")).toBeInTheDocument();
    expect(screen.getByText("Secretaria de Educação")).toBeInTheDocument();
  });

  it("Professor vê os próprios dados", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({ nome: "Prof Demo", email: "prof@demo.local", cargo: "professor" }),
    });
    expect(await screen.findByText("Prof Demo")).toBeInTheDocument();
    expect(screen.getByText("Professor(a)")).toBeInTheDocument();
  });

  it("Admin Global tem o perfil rotulado corretamente", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({ nome: "Admin Demo", email: "admin@demo.local", is_global: true }),
    });
    expect(await screen.findByText("Administrador Global")).toBeInTheDocument();
  });
});
