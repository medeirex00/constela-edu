/**
 * Vitrine Pública e Painel Público numa instalação LOCAL (demo, ambiente de teste): o link
 * vinha do backend com o domínio de produção (`PUBLIC_BASE_URL` padrão), onde o token local
 * não existe — "Abrir" e "Copiar" levavam para lá e a vitrine "não abria".
 *
 * O contrato (lib/linkPublico): quem decide a base do link é o SERVIDOR — o `PUBLIC_BASE_URL`
 * configurado de propósito vence; sem ele, a origem de loopback que a tela informa. A tela só
 * INFORMA a própria origem (`?origem=`, só em loopback) e mostra, copia e abre o `url` que o
 * servidor devolve, sem reescrevê-lo. Quando esse link é do próprio computador, a tela avisa
 * que ele não abre no telão, no celular nem no QR lido por outro aparelho.
 *
 * O jsdom roda em http://localhost:3000 (loopback), como a demo e o ambiente de teste.
 */
import { describe, expect, it } from "vitest";

import { comOrigemLocal, ehOrigemLocal, linkSoNestaMaquina } from "../lib/linkPublico";
import PainelPublicoConfig from "../pages/PainelPublicoConfig";
import RedeDashboard from "../pages/rede/RedeDashboard";
import { api, apiDownload, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const PRODUCAO = "https://www.constelaedu.com";
/** O `?origem=` que a tela manda: a origem do jsdom, codificada. */
const ORIGEM = `origem=${encodeURIComponent(window.location.origin)}`;

/** Painel da rede mínimo (uma escola sintética) — o mesmo formato do /redes/{id}/dashboard. */
function dashRede() {
  const escola = {
    escola_id: 1, nome: "EMEF Sintética da Vitrine", cidade: "Cidade Sintética", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2, total_alunos: 15,
    alunos_com_dados: 15, adocao: 100, media_geral: 60, media_matific: 60, media_elefante: 60,
    dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 15, alunos_com_nota_matific: 15,
    adocao_elefante: 100, adocao_matific: 100, livros: 30, tempo_leitura_min: 300, atividades: 30,
    estrelas: 60, ativos_matific: 15, ativos_elefante: 15, livros_por_aluno: 2, livros_por_matricula: 2,
    estrelas_por_matricula: 4, atividades_por_matricula: 2, tempo_por_matricula_min: 20,
    pontuacao_leitura: 1000, pontuacao_matematica: 1000, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura", "matematica"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null, comparada: true, posicao: 1,
  };
  return {
    rede_id: 7, modulos: ["leitura", "matematica"],
    totais: {
      escolas: 1, escolas_ativas: 1, alunos: 15, turmas: 2, professores: 2, alunos_com_dados: 15,
      adocao: 100, media_geral: 60, media_matific: 60, media_elefante: 60, pontuacao_geral: 1000,
      escolas_em_atencao: 0, livros: 30, tempo_leitura_min: 300, atividades: 30, estrelas: 60,
      ativos_matific: 15, ativos_elefante: 15, livros_por_aluno: 2,
      melhor_escola: { nome: escola.nome, pontuacao_geral: 1000, media_geral: 60 },
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000, escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 60, escola_menor_media: 60, escolas_abaixo_da_media: 0,
    },
    escolas: [escola], atencao: [],
  };
}

const metodo = (opcoes: unknown) => (opcoes as RequestInit | undefined)?.method ?? "GET";

/** As chamadas feitas ao caminho com o método (com a consulta, como saíram). */
function chamadasA(metodoPedido: string, caminho: string): string[] {
  return api.mock.calls
    .filter(([c, opcoes]) => String(c).split("?")[0] === caminho && metodo(opcoes) === metodoPedido)
    .map(([c]) => String(c));
}

describe("lib/linkPublico — a tela informa a origem, o servidor decide o link", () => {
  it("ehOrigemLocal só aceita http(s) de loopback (o app de desktop não conta)", () => {
    for (const o of ["http://localhost:8050", "http://admin.localhost:8050", "http://127.0.0.1", "http://[::1]:8050"]) {
      expect(ehOrigemLocal(o), o).toBe(true);
    }
    // O app de desktop (Windows: http://tauri.localhost) fala com o servidor de verdade.
    for (const o of [PRODUCAO, "http://localhost.evil.example", "http://10.0.0.2", "file:///c:/x", "nada",
                     "http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"]) {
      expect(ehOrigemLocal(o), o).toBe(false);
    }
  });

  it("comOrigemLocal: em loopback acrescenta a origem codificada; fora dele, o caminho segue igual", () => {
    expect(comOrigemLocal("/escolas/1/painel-publico", "http://localhost:8050"))
      .toBe("/escolas/1/painel-publico?origem=http%3A%2F%2Flocalhost%3A8050");
    // Caminho que já tem consulta: entra com "&".
    expect(comOrigemLocal("/redes/7/publico?x=1", "http://127.0.0.1:8040"))
      .toBe("/redes/7/publico?x=1&origem=http%3A%2F%2F127.0.0.1%3A8040");
    for (const o of [PRODUCAO, "http://tauri.localhost", "tauri://localhost", "http://10.0.0.2:8040"]) {
      expect(comOrigemLocal("/redes/7/publico", o), o).toBe("/redes/7/publico");
    }
    // Sem a origem explícita, vale a da tela (o jsdom é loopback).
    expect(ehOrigemLocal(window.location.origin)).toBe(true);
    expect(comOrigemLocal("/redes/7/publico")).toBe(`/redes/7/publico?${ORIGEM}`);
  });

  it("linkSoNestaMaquina: o link do servidor é do próprio computador?", () => {
    expect(linkSoNestaMaquina("http://localhost:8050/p/tok1")).toBe(true);
    expect(linkSoNestaMaquina("http://127.0.0.1:8040/rede/p/tok2")).toBe(true);
    expect(linkSoNestaMaquina(`${PRODUCAO}/p/tok1`)).toBe(false);
    expect(linkSoNestaMaquina("http://192.168.0.10:8040/p/tok1")).toBe(false);
    expect(linkSoNestaMaquina("http://tauri.localhost/p/tok1")).toBe(false);
    expect(linkSoNestaMaquina(null)).toBe(false);
    expect(linkSoNestaMaquina(undefined)).toBe(false);
    expect(linkSoNestaMaquina("não é link")).toBe(false);
  });
});

describe("Painel Público da escola", () => {
  function responderConfig(url: string) {
    responder("GET", "/escolas/1/painel-publico", {
      ativo: true, slides: ["ranking"], intervalo_s: 12, max_posicoes: 10, anonimizar: true, url,
    });
  }

  it("pede a configuração com ?origem= e mostra e abre o link COMO o servidor devolveu", async () => {
    responderConfig(`${PRODUCAO}/p/tok123`);
    renderComApp(<PainelPublicoConfig />);
    const abrir = await screen.findByRole("link", { name: /Abrir/ });
    expect(chamadasA("GET", "/escolas/1/painel-publico")).toEqual([`/escolas/1/painel-publico?${ORIGEM}`]);
    // Nada de reescrever a base: o domínio publicado (que o servidor escolheu) fica.
    expect(abrir).toHaveAttribute("href", `${PRODUCAO}/p/tok123`);
    expect(abrir).toHaveAttribute("target", "_blank");
    expect(screen.getByText(`${PRODUCAO}/p/tok123`)).toBeInTheDocument();
    // Link de domínio: abre em qualquer aparelho, sem aviso.
    expect(screen.queryByTestId("aviso-link-local")).toBeNull();
  });

  it("link do próprio computador: avisa que só abre aqui (telão, celular e QR em outro aparelho, não)", async () => {
    responderConfig("http://localhost:3000/p/tok123");
    renderComApp(<PainelPublicoConfig />);
    expect(await screen.findByRole("link", { name: /Abrir/ })).toHaveAttribute("href", "http://localhost:3000/p/tok123");
    expect(screen.getByTestId("aviso-link-local")).toHaveTextContent(
      "Este link usa localhost: só abre no computador onde o Constela está instalado. Para o telão, o celular ou o "
      + "QR code lido em outro aparelho, o servidor "
      + "precisa ter configurado o endereço dele na rede (variável PUBLIC_BASE_URL).");
  });

  it("'Baixar QR code' pede o QR com ?origem= (o mesmo link que a tela mostra)", async () => {
    responderConfig(`${PRODUCAO}/p/tok123`);
    renderComApp(<PainelPublicoConfig />);
    await userEvent.click(await screen.findByRole("button", { name: /Baixar QR code/ }));
    expect(apiDownload).toHaveBeenCalledWith(`/escolas/1/painel-publico/qr?${ORIGEM}`);
  });

  it("salvar e gerar novo endereço também informam a origem", async () => {
    responderConfig(`${PRODUCAO}/p/tok123`);
    responder("PUT", "/escolas/1/painel-publico", (_c, opcoes) => ({
      ...JSON.parse(String((opcoes as RequestInit).body)), url: `${PRODUCAO}/p/tok123` }));
    responder("POST", "/escolas/1/painel-publico/novo-token", {
      ativo: true, slides: ["ranking"], intervalo_s: 12, max_posicoes: 10, anonimizar: true, url: `${PRODUCAO}/p/tok999`,
    });
    renderComApp(<PainelPublicoConfig />);
    await userEvent.click(await screen.findByLabelText(/Ranking de Evolução/));
    expect(await screen.findByText("Configuração salva.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Gerar novo endereço/ }));
    const dialogo = await screen.findByRole("dialog", { name: "Gerar um novo endereço?" });
    await userEvent.click(within(dialogo).getByRole("button", { name: "Gerar novo endereço" }));
    expect(await screen.findByText(`${PRODUCAO}/p/tok999`)).toBeInTheDocument();
    expect(chamadasA("PUT", "/escolas/1/painel-publico")).toEqual([`/escolas/1/painel-publico?${ORIGEM}`]);
    expect(chamadasA("POST", "/escolas/1/painel-publico/novo-token"))
      .toEqual([`/escolas/1/painel-publico/novo-token?${ORIGEM}`]);
  });
});

describe("Vitrine da rede (Painel da Rede)", () => {
  const secretaria = usuarioFake({ nome: "Secretaria Sintética", cargo: "coordenador", rede_id: 7, escola_id: null });

  function semear(url: string) {
    responder("GET", "/redes/7/dashboard", dashRede());
    responder("GET", "/redes/7/metas", []);
    responder("GET", "/redes/7/publico", { ativo: true, token: "tokRede", url });
  }

  it("pede a vitrine com ?origem= e 'Abrir vitrine' leva ao link do servidor, sem aviso para domínio", async () => {
    semear(`${PRODUCAO}/rede/p/tokRede`);
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const abrir = await screen.findByRole("link", { name: /Abrir vitrine/ });
    expect(chamadasA("GET", "/redes/7/publico")).toEqual([`/redes/7/publico?${ORIGEM}`]);
    expect(abrir).toHaveAttribute("href", `${PRODUCAO}/rede/p/tokRede`);
    expect(abrir).toHaveAttribute("target", "_blank");
    expect(screen.getByText(`${PRODUCAO}/rede/p/tokRede`)).toBeInTheDocument();
    expect(screen.queryByTestId("aviso-link-local")).toBeNull();
  });

  it("link do próprio computador: o mesmo aviso junto do endereço; desligar informa a origem", async () => {
    semear("http://127.0.0.1:8040/rede/p/tokRede");
    responder("PUT", "/redes/7/publico", { ok: true });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByRole("link", { name: /Abrir vitrine/ }))
      .toHaveAttribute("href", "http://127.0.0.1:8040/rede/p/tokRede");
    expect(screen.getByTestId("aviso-link-local")).toHaveTextContent(
      "Este link usa localhost: só abre no computador onde o Constela está instalado. Para o telão ou o celular, o "
      + "servidor precisa ter configurado o endereço "
      + "dele na rede (variável PUBLIC_BASE_URL).");
    await userEvent.click(screen.getByRole("button", { name: /Desligar/ }));
    expect(chamadasA("PUT", "/redes/7/publico")).toEqual([`/redes/7/publico?${ORIGEM}`]);
  });
});
