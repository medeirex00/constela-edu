/**
 * PROMOÇÃO A SECRETARIA — a senha da conta promovida deixa de valer (decisão
 * do dono).
 *
 * Quem decide é o backend (`PUT /redes/{id}/usuarios`): invalida a senha de quem
 * PASSA a ter o rede_id (nunca a da conta global nem a do e-mail do dono) e
 * devolve `exigem_redefinicao`. O que estes testes travam é a parte que o
 * servidor não garante sozinho: o admin global é AVISADO antes de salvar e,
 * depois, sabe QUEM precisa do link e ONDE gerá-lo — sem link gerado aqui.
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import RedeGestao from "../pages/rede/RedeGestao";
import {
  api, renderComApp, responder, screen, userEvent, usuarioFake, within,
} from "./utils";

const root = usuarioFake({ id: 99, nome: "Admin", cargo: "admin", is_global: true });

const GERENCIAR = {
  redes: [{ id: 1, nome: "Rede Sint", uf: "SP", codigo_ibge: null, status: "ativa" }],
  escolas: [{
    id: 7, nome: "EM Origem Sint", cidade: null, estado: null, bairro: null, status: "ativa",
    rede_id: 1, latitude: null, longitude: null, codigo_inep: null,
  }],
  usuarios: [
    { id: 10, nome: "Ana Ja Secretaria", email: "ana@sint.local", cargo: "coordenador",
      is_global: false, escola_id: null, rede_id: 1 },
    { id: 11, nome: "Bia Coordenadora", email: "bia@sint.local", cargo: "coordenador",
      is_global: false, escola_id: 7, rede_id: null },
    { id: 12, nome: "Caio Sem Escola", email: "caio@sint.local", cargo: "coordenador",
      is_global: false, escola_id: null, rede_id: null },
  ],
};

const RESPOSTA_COM_PROMOCAO = {
  rede_id: 1,
  usuario_ids: [10, 11, 12],
  exigem_redefinicao: [
    { id: 11, nome: "Bia Coordenadora", email: "bia@sint.local", escola_id: 7 },
    { id: 12, nome: "Caio Sem Escola", email: "caio@sint.local", escola_id: null },
  ],
};

function montar() {
  responder("GET", "/redes/gerenciar", GERENCIAR);
  responder("GET", "/redes/1/modulos", []);
  renderComApp(
    <Routes>
      <Route path="/" element={<RedeGestao />} />
      <Route path="/usuarios" element={<p>Tela de Usuários</p>} />
    </Routes>,
    { usuario: root },
  );
}

function chamadas(filtro: (caminho: string, metodo: string) => boolean) {
  return (api as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
    ([c, o]) => filtro(String(c), String((o as RequestInit | undefined)?.method ?? "GET")),
  );
}
const putsUsuarios = () =>
  chamadas((c, m) => c === "/redes/1/usuarios" && m === "PUT");

async function marcar(nome: RegExp) {
  await userEvent.click(await screen.findByRole("checkbox", { name: nome }));
}

describe("Gestão de redes — promoção a Secretaria invalida a senha", () => {
  it("avisa ANTES de salvar e não envia nada até a confirmação", async () => {
    montar();
    await marcar(/Bia Coordenadora/);
    // O aviso já aparece na própria linha marcada, antes de qualquer clique.
    expect(screen.getByText(/perde a senha ao salvar/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Salvar acessos/i }));
    expect(screen.getByRole("heading", { name: /Promover a Secretaria/i })).toBeInTheDocument();
    expect(screen.getByText(/a senha atual dessas contas deixa de valer/i)).toBeInTheDocument();
    expect(screen.getByText(/nenhum\s+link é gerado automaticamente/i)).toBeInTheDocument();
    expect(putsUsuarios()).toHaveLength(0);

    // Cancelar não grava nada.
    await userEvent.click(screen.getByRole("button", { name: /^Cancelar$/ }));
    expect(screen.queryByRole("heading", { name: /Promover a Secretaria/i })).not.toBeInTheDocument();
    expect(putsUsuarios()).toHaveLength(0);
  });

  it("DEPOIS de salvar, lista quem precisa do link e onde gerá-lo — sem gerar link", async () => {
    responder("PUT", "/redes/1/usuarios", RESPOSTA_COM_PROMOCAO);
    montar();
    await marcar(/Bia Coordenadora/);
    await marcar(/Caio Sem Escola/);
    await userEvent.click(screen.getByRole("button", { name: /Salvar acessos/i }));
    await userEvent.click(screen.getByRole("button", { name: /Salvar e invalidar as senhas/i }));

    const lista = await screen.findByRole("region", {
      name: /Contas que precisam de link de redefinição/i,
    });
    // Conta COM escola: a tela de Usuários da escola de origem, "Redefinir senha".
    expect(lista).toHaveTextContent(/Bia Coordenadora/);
    expect(lista).toHaveTextContent(/EM Origem Sint/);
    expect(lista).toHaveTextContent(/Redefinir senha/);
    // Conta SEM escola: o script do operador, com o admin logado como autor.
    expect(lista).toHaveTextContent(/Caio Sem Escola/);
    expect(lista).toHaveTextContent(
      /python -m scripts\.link_redefinicao --usuario-id 12 --por 99 --confirmar/,
    );
    expect(screen.getByText(/2 conta\(s\) promovida\(s\) perderam a senha/i)).toBeInTheDocument();

    // Um único PUT com a lista marcada; nenhum link gerado pela tela.
    expect(putsUsuarios()).toHaveLength(1);
    expect(JSON.parse((putsUsuarios()[0][1] as RequestInit).body as string))
      .toEqual({ usuario_ids: [10, 11, 12] });
    expect(chamadas((c) => c.includes("redefinir-senha"))).toHaveLength(0);
  });

  it("o atalho abre os Usuários da escola de origem (só navega)", async () => {
    responder("PUT", "/redes/1/usuarios", RESPOSTA_COM_PROMOCAO);
    montar();
    await marcar(/Bia Coordenadora/);
    await userEvent.click(screen.getByRole("button", { name: /Salvar acessos/i }));
    await userEvent.click(screen.getByRole("button", { name: /Salvar e invalidar as senhas/i }));

    const lista = await screen.findByRole("region", {
      name: /Contas que precisam de link de redefinição/i,
    });
    await userEvent.click(within(lista).getByRole("button", { name: /Abrir Usuários de EM Origem Sint/i }));
    expect(await screen.findByText("Tela de Usuários")).toBeInTheDocument();
    expect(localStorage.getItem("sgpe_escola")).toBe("7");
    expect(chamadas((c) => c.includes("redefinir-senha"))).toHaveLength(0);
  });

  it("sem promoção nova, salva direto — sem confirmação e sem lista", async () => {
    // Resposta de uma API anterior ao campo: ausente = ninguém perdeu a senha.
    responder("PUT", "/redes/1/usuarios", { rede_id: 1, usuario_ids: [10] });
    montar();
    await screen.findByRole("checkbox", { name: /Ana Ja Secretaria/ });
    expect(screen.queryByText(/perde a senha ao salvar/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Salvar acessos/i }));
    expect(await screen.findByText("Secretaria da rede atualizada.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Promover a Secretaria/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", {
      name: /Contas que precisam de link de redefinição/i,
    })).not.toBeInTheDocument();
    expect(putsUsuarios()).toHaveLength(1);
  });
});
