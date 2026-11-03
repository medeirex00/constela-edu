import { describe, expect, it } from "vitest";

import { corDoAvatar } from "../components/ui";
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

  // Quem gera o link de redefinição é a régua do backend (admin._usuario_alvo):
  // conta da Secretaria ou global só o Admin Global; o administrador da escola
  // recebe 403. A tela não pode mandar a Secretaria pedir a quem não pode fazer.
  it("Secretaria é orientada a pedir a troca de senha ao Admin Global, não à escola", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({
        nome: "Secretaria Demo", email: "sec@demo.local",
        cargo: "coordenador", rede_id: 7, escola_id: null,
      }),
    });
    expect(await screen.findByText(/Administrador Global da plataforma/)).toBeInTheDocument();
    expect(screen.queryByText(/peça ao administrador da escola/i)).not.toBeInTheDocument();
  });

  it("Admin Global é orientado a pedir a outro Administrador Global", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({ nome: "Admin Demo", email: "admin@demo.local", is_global: true }),
    });
    expect(await screen.findByText(/por outro Administrador Global da plataforma/)).toBeInTheDocument();
    expect(screen.queryByText(/peça ao administrador da escola/i)).not.toBeInTheDocument();
  });

  it("professor e gestão da escola seguem pedindo ao administrador da escola", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({ nome: "Prof Demo", email: "prof@demo.local", cargo: "professor" }),
    });
    expect(await screen.findByText(/peça ao administrador da escola um link de redefinição/)).toBeInTheDocument();
    expect(screen.queryByText(/Administrador Global/)).not.toBeInTheDocument();
  });

  it("nome no cabeçalho com o texto inteiro no title e avatar com a cor do id (a mesma da barra lateral)", async () => {
    renderComApp(<MinhaConta />, {
      usuario: usuarioFake({ id: 42, nome: "Coordenadora Teste", email: "coord@demo.local", cargo: "coordenador" }),
    });
    const nome = await screen.findByRole("heading", { level: 2, name: "Coordenadora Teste" });
    expect(nome).toHaveAttribute("title", "Coordenadora Teste");
    expect(screen.getByText("CT")).toHaveClass(corDoAvatar(42));
  });
});
