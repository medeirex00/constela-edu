/**
 * RECÁLCULO AO MUDAR O CONTRATO — a tela do Admin Global.
 *
 * Mudar os módulos contratados muda a nota GRAVADA de cada aluno (pesos.geral é
 * redistribuído), então o PUT recalcula a rede inteira. O que estes testes
 * travam é a parte que o servidor não garante sozinho: o operador precisa SABER
 * o que aconteceu — quantas escolas foram refeitas e, se alguma falhou, quais e
 * como consertar sem medo de duplicar nada.
 */
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ModulosDaRede } from "../pages/rede/RedeGestao";
import {
  ApiError, api, renderComApp, responder, screen, userEvent, usuarioFake,
} from "./utils";

const CATALOGO = [
  { chave: "leitura", nome: "Leitura", produto: "Elefante Letrado", icone: "📚", ativo: true },
  { chave: "matematica", nome: "Matemática", produto: "Matific", icone: "🔢", ativo: true },
];

const root = usuarioFake({ nome: "Admin", cargo: "admin", is_global: true });

function resposta(over: Record<string, unknown> = {}) {
  return {
    modulos: CATALOGO,
    de: ["leitura", "matematica"],
    para: ["leitura"],
    recalculo: { escolas: 3, alunos: 55, recalculadas: [], falhas: [], ...over },
  };
}

async function desligarMatematica() {
  responder("GET", "/redes/1/modulos", CATALOGO);
  renderComApp(<ModulosDaRede redeId={1} />, { usuario: root });
  const caixa = await screen.findByRole("checkbox", { name: /Matemática contratado/i });
  await userEvent.click(caixa);
}

describe("Módulos contratados — recálculo ao mudar o contrato", () => {
  it("informa que as notas foram recalculadas, com escolas e alunos", async () => {
    responder("PUT", "/redes/1/modulos", resposta());
    await desligarMatematica();

    expect(await screen.findByText(/3 escola\(s\), 55 aluno\(s\)/i)).toBeInTheDocument();
    expect(screen.getByText(/notas recalculadas/i)).toBeInTheDocument();
    // Sem falha, não há por que oferecer "tentar novamente".
    expect(screen.queryByRole("button", { name: /Tentar novamente/i })).not.toBeInTheDocument();
  });

  it("falha parcial: diz QUAIS escolas ficaram para trás e deixa refazer", async () => {
    responder("PUT", "/redes/1/modulos", resposta({
      falhas: [{ escola_id: 7, nome: "EM JORGE PASSOS", erro: "banco indisponível" }],
    }));
    await desligarMatematica();

    // O contrato foi salvo (é a fonte da verdade) — a tela não pode dizer que
    // "não salvou"; ela precisa dizer o que exatamente falta refazer.
    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent(/Plano salvo/i);
    expect(aviso).toHaveTextContent("EM JORGE PASSOS");
    expect(screen.getByRole("button", { name: /Tentar novamente/i })).toBeInTheDocument();
  });

  it('"Tentar novamente" reenvia o MESMO pedido (idempotente) e limpa o aviso', async () => {
    responder("PUT", "/redes/1/modulos", resposta({
      falhas: [{ escola_id: 7, nome: "EM JORGE PASSOS", erro: "timeout" }],
    }));
    await desligarMatematica();
    await screen.findByRole("button", { name: /Tentar novamente/i });

    responder("PUT", "/redes/1/modulos", resposta());   // agora sem falha
    await userEvent.click(screen.getByRole("button", { name: /Tentar novamente/i }));

    expect(await screen.findByText(/notas recalculadas/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Tentar novamente/i })).not.toBeInTheDocument();

    // Mesmo corpo nas duas chamadas: é o que torna o reenvio seguro.
    const puts = (api as unknown as ReturnType<typeof vi.fn>).mock.calls
      .filter(([caminho, op]) => caminho === "/redes/1/modulos"
        && (op as RequestInit)?.method === "PUT");
    expect(puts).toHaveLength(2);
    expect((puts[0][1] as RequestInit).body).toBe((puts[1][1] as RequestInit).body);
    expect(JSON.parse((puts[0][1] as RequestInit).body as string)).toEqual({ matematica: false });
  });
});

/** Espelha o uso real, mas DE PROPÓSITO sem `key`: o componente tem de se
 *  proteger sozinho, sem depender de o chamador lembrar de remontá-lo. */
function PainelComTrocaDeRede() {
  const [id, setId] = useState(1);
  return (
    <div>
      <button type="button" onClick={() => setId(2)}>trocar rede</button>
      <ModulosDaRede redeId={id} />
    </div>
  );
}

function puts(caminho: string) {
  return (api as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
    ([c, o]) => c === caminho && (o as RequestInit)?.method === "PUT",
  );
}

describe("Módulos contratados — o estado não vaza entre redes", () => {
  it("trocar de rede descarta o aviso e o pedido pendente da rede anterior", async () => {
    responder("GET", "/redes/1/modulos", CATALOGO);
    responder("GET", "/redes/2/modulos", CATALOGO);
    responder("PUT", "/redes/1/modulos", resposta({
      falhas: [{ escola_id: 7, nome: "EM JORGE PASSOS", erro: "timeout" }],
    }));
    responder("PUT", "/redes/2/modulos", resposta());

    renderComApp(<PainelComTrocaDeRede />, { usuario: root });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Matemática contratado/i }));
    await screen.findByRole("button", { name: /Tentar novamente/i });

    // O Admin Global desiste e vai olhar OUTRA rede.
    await userEvent.click(screen.getByRole("button", { name: /trocar rede/i }));

    // O aviso era da rede 1 e não pode sobreviver na tela da rede 2 — senão o
    // "Tentar novamente" recalcularia uma rede que ninguém pediu.
    expect(screen.queryByText(/EM JORGE PASSOS/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Tentar novamente/i })).not.toBeInTheDocument();
    expect(puts("/redes/2/modulos")).toHaveLength(0);
  });

  it("nenhum PUT jamais chega a uma rede diferente daquela do aviso", async () => {
    responder("GET", "/redes/1/modulos", CATALOGO);
    responder("GET", "/redes/2/modulos", CATALOGO);
    responder("PUT", "/redes/1/modulos", resposta({
      falhas: [{ escola_id: 7, nome: "EM X", erro: "timeout" }],
    }));
    responder("PUT", "/redes/2/modulos", resposta());

    renderComApp(<PainelComTrocaDeRede />, { usuario: root });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Matemática contratado/i }));
    await screen.findByRole("button", { name: /Tentar novamente/i });
    await userEvent.click(screen.getByRole("button", { name: /trocar rede/i }));
    // Na rede 2, mexe normalmente: o PUT tem de ser o da AÇÃO nova, não o pendente.
    await userEvent.click(await screen.findByRole("checkbox", { name: /Leitura contratado/i }));

    expect(puts("/redes/1/modulos")).toHaveLength(1);       // só o toque original
    const naRede2 = puts("/redes/2/modulos");
    expect(naRede2).toHaveLength(1);
    expect(JSON.parse((naRede2[0][1] as RequestInit).body as string)).toEqual({ leitura: false });
  });
});

describe("Módulos contratados — envio duplicado e erro de rede", () => {
  it("duplo clique gera UM único PUT", async () => {
    responder("GET", "/redes/1/modulos", CATALOGO);
    responder("PUT", "/redes/1/modulos", resposta({
      falhas: [{ escola_id: 7, nome: "EM X", erro: "timeout" }],
    }));
    renderComApp(<ModulosDaRede redeId={1} />, { usuario: root });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Matemática contratado/i }));

    const botao = await screen.findByRole("button", { name: /Tentar novamente/i });
    await userEvent.dblClick(botao);

    // 1 do checkbox + 1 do duplo clique (que conta como UM envio, não dois).
    expect(puts("/redes/1/modulos")).toHaveLength(2);
  });

  it("erro de rede: não afirma que falhou, recarrega o estado real e deixa refazer", async () => {
    responder("GET", "/redes/1/modulos", CATALOGO);
    responder("PUT", "/redes/1/modulos", new ApiError(0, "Não foi possível conectar."));

    renderComApp(<ModulosDaRede redeId={1} />, { usuario: root });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Matemática contratado/i }));

    const aviso = await screen.findByRole("alert");
    // O contrato é gravado ANTES do recálculo: um erro aqui NÃO prova que nada
    // foi salvo. A mensagem tem de dizer isso em vez de "Falha ao salvar".
    expect(aviso).toHaveTextContent(/pode já ter sido aplicado/i);
    expect(aviso).not.toHaveTextContent(/Falha ao salvar/i);
    expect(screen.getByRole("button", { name: /Tentar novamente/i })).toBeInTheDocument();

    // E o estado real é buscado de novo (o checkbox não pode mentir).
    const gets = (api as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([c, o]) => c === "/redes/1/modulos" && ((o as RequestInit)?.method ?? "GET") === "GET",
    );
    expect(gets.length).toBeGreaterThanOrEqual(2);
  });
});
