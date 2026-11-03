/**
 * Polling da tela Integrações SEM cancelar o que está em voo.
 *
 * Em 21/10 o GET /status levava ~4,9 s. O polling de 4 s recomeçava o
 * intervalo a cada render (o `recarregar` da tela mudava de identidade a cada
 * render) e TODA recarga — o tick, o "Atualizar", o sucesso de "Sincronizar
 * agora" — abortava o GET em andamento (o proxy registra 499). Com o /status
 * acima de ~5,2 s (histórico + 4 s), nenhum /status chegava ao fim: a tela
 * ficava em "Carregando integrações…" durante toda a sincronização.
 *
 * Relógio falso; o transporte é o mock oficial (lib/__mocks__/api) com
 * respostas ATRASADAS que respeitam o AbortSignal: cada requisição registra
 * início, fim e se foi cancelada. Escola e dados fictícios.
 */
import { act, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Sincronizacao from "../pages/Sincronizacao";
import { renderComApp, responder, screen, usuarioFake } from "./utils";
import type { OpcoesRender } from "./utils";

type Rota = "status" | "historico" | "alertas" | "agora" | "dashboard";
type Ev = { rota: Rota; inicio: number; fim?: number; desfecho?: "200" | "cancelada" | "falha" };

let eventos: Ev[] = [];
let t0 = 0;
let lat: Record<Rota, number>;
/** Instante (ms desde a montagem) em que a coleta termina no servidor; null = não termina. */
let concluiEm: number | null = null;
/** O n-ésimo /status falha (rede) `falhaAntesMs` antes do fim normal. */
let falharStatusNumero: number | null = null;
let falhaAntesMs = 0;

const EXEC = {
  id: 16, plataforma: "elefante", origem: "manual", status: "executando", tentativa: 1,
  iniciada_em: "2026-10-21T10:55:34Z", finalizada_em: null, duracao_ms: 0,
  qtd_alunos: 0, qtd_turmas: 0, qtd_arquivos: 0, qtd_erros: 0, erro_resumo: null,
  conector_versao: null, parser_versao: null, created_at: "2026-10-21T10:55:30Z",
};
const EXEC_FIM = {
  ...EXEC, status: "concluida", finalizada_em: "2026-10-21T10:58:00Z", duracao_ms: 146000,
  qtd_alunos: 40, qtd_turmas: 4, qtd_arquivos: 1,
};
const DASH = {
  escolas_total: 1, escolas_configuradas: 1, escolas_sincronizadas: 0, escolas_com_erro: 0,
  em_andamento: 1, fila: 0, workers_ativos: 1, scheduler_ligado: false,
  ultima_sincronizacao: null, duracao_ultima_ms: null, tempo_medio_ms: null, alertas_abertos: 0,
};

const agora = () => Date.now() - t0;
const execAtual = () => (concluiEm !== null && agora() >= concluiEm ? EXEC_FIM : EXEC);

function corpoStatus() {
  const exec = execAtual();
  return {
    escola_id: 1, escola_nome: "ESCOLA FICTICIA", qtd_alunos: 60, qtd_turmas: 7,
    alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
    plataformas: [{
      plataforma: "elefante", estrategia: "navegador", conectada: true,
      credencial_status: "valida", validada_em: null, ultimo_erro: null,
      agendada: false, cadencia: "manual", hora_local: "03:00", dia_semana: null,
      proxima_execucao: null, ultima_execucao: exec,
      ultimo_sucesso_em: exec.status === "concluida" ? exec.finalizada_em : null,
      desatualizada: false,
    }],
  };
}

/** Resposta atrasada que respeita o AbortSignal (o servidor lê o estado no início). */
function atrasado(rota: Rota, corpo: () => unknown, opcoes: RequestInit | FormData) {
  const ev: Ev = { rota, inicio: agora() };
  eventos.push(ev);
  const valor = corpo();
  const n = eventos.filter((e) => e.rota === rota).length;
  const falha = rota === "status" && falharStatusNumero === n;
  const sinal = (opcoes as RequestInit | undefined)?.signal ?? null;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      ev.fim = agora();
      if (falha) {
        ev.desfecho = "falha";
        reject(new TypeError("Failed to fetch"));
        return;
      }
      ev.desfecho = "200";
      resolve(valor);
    }, falha ? lat[rota] - falhaAntesMs : lat[rota]);
    sinal?.addEventListener("abort", () => {
      if (ev.desfecho) return;
      clearTimeout(timer);
      ev.fim = agora();
      ev.desfecho = "cancelada";
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

function mocks() {
  responder("GET", "/escolas/1/configuracoes/sincronizacao", { criar_aluno: "permitir" });
  responder("GET", "/escolas/1/sync/status", (_c: string, o: RequestInit | FormData) =>
    atrasado("status", corpoStatus, o));
  responder("GET", "/escolas/1/sync/historico?limite=30", (_c: string, o: RequestInit | FormData) =>
    atrasado("historico", () => [execAtual()], o));
  responder("GET", "/escolas/1/sync/alertas?resolvido=false", (_c: string, o: RequestInit | FormData) =>
    atrasado("alertas", () => [], o));
  responder("POST", /\/escolas\/1\/sync\/agora/, (_c: string, o: RequestInit | FormData) =>
    atrasado("agora", () => [execAtual()], o));
  responder("GET", "/sync/dashboard", (_c: string, o: RequestInit | FormData) =>
    atrasado("dashboard", () => DASH, o));
}

/** Avança o relógio falso em passos, cada um no seu act() — os efeitos (o
 *  setInterval do polling) rodam entre os passos, como no navegador. */
async function avancar(ms: number, passo = 20) {
  for (let feito = 0; feito < ms; feito += passo) {
    await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(passo, ms - feito)); });
  }
}

async function avancarAte(condicao: () => boolean, limiteMs: number, passo = 20) {
  for (let feito = 0; feito < limiteMs && !condicao(); feito += passo) {
    await act(async () => { await vi.advanceTimersByTimeAsync(passo); });
  }
  expect(condicao()).toBe(true);
}

const daRota = (rota: Rota) => eventos.filter((e) => e.rota === rota);
const cancelados = () => eventos.filter((e) => e.desfecho === "cancelada");
const statusNoAr = () => daRota("status").find((e) => e.desfecho === undefined);

async function montar(opcoes: OpcoesRender = {}) {
  t0 = Date.now();
  const tela = renderComApp(<Sincronizacao />, { rota: "/sincronizacao", ...opcoes });
  await avancar(10, 10);
  return tela;
}

/** Monta e espera o 2º /status (o primeiro do polling) estar no ar. */
async function montarAteStatusDoPollingNoAr() {
  const tela = await montar();
  await avancarAte(() => daRota("status")[0]?.desfecho === "200", 15_000);
  await avancarAte(() => daRota("status").length >= 2 && statusNoAr() !== undefined, 15_000);
  return tela;
}

beforeEach(() => {
  vi.useFakeTimers();
  eventos = [];
  lat = { status: 4874, historico: 1165, alertas: 1159, agora: 2100, dashboard: 3000 };
  concluiEm = null;
  falharStatusNumero = null;
  falhaAntesMs = 0;
  mocks();
});
afterEach(() => { vi.useRealTimers(); });

describe("Integrações — polling sem cancelar o que está em voo", () => {
  it.each([4874, 5400, 8200])(
    "/status de %i ms durante uma coleta: nenhum GET cancelado e o card acompanha até o fim",
    async (ms) => {
      lat.status = ms;
      concluiEm = 30_000;
      await montar();

      await avancar(15_000, 50);
      expect(screen.queryByText(/Carregando integrações/)).toBeNull();
      expect(screen.getByText(/Uma sincronização está em andamento/)).toBeInTheDocument();

      await avancar(45_000, 50);
      expect(screen.queryByText(/Uma sincronização está em andamento/)).toBeNull();
      expect(cancelados()).toEqual([]);
      expect(daRota("status").filter((e) => e.desfecho === "200").length).toBeGreaterThanOrEqual(3);

      // Coleta terminada: o polling para.
      const total = eventos.length;
      await avancar(20_000, 100);
      expect(eventos.length).toBe(total);
    },
  );

  it("o intervalo de 4 s não recomeça a cada resposta: o histórico é consultado a cada 4 s", async () => {
    await montar();
    await avancar(40_000);
    const inicios = daRota("historico").slice(1).map((e) => e.inicio);
    const ciclos = inicios.slice(1).map((v, i) => v - inicios[i]);
    expect(ciclos.length).toBeGreaterThanOrEqual(5);
    for (const c of ciclos) expect(Math.abs(c - 4000)).toBeLessThan(50);
    expect(cancelados()).toEqual([]);
  });

  it("'Sincronizar agora' com um /status no ar: nada é cancelado e a tela recarrega depois do POST", async () => {
    await montarAteStatusDoPollingNoAr();
    await avancar(1500);
    const emVoo = statusNoAr();
    expect(emVoo).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /Sincronizar agora/i }));
    await avancar(20_000);

    const post = daRota("agora")[0];
    expect(post?.desfecho).toBe("200");
    expect(cancelados()).toEqual([]);
    expect(emVoo!.desfecho).toBe("200");
    // O sucesso do POST ainda recarrega o /status (depois do que estava no ar).
    expect(daRota("status").some((e) => e.inicio >= (post.fim as number) && e.desfecho === "200"))
      .toBe(true);
  });

  it("'Atualizar' com um /status no ar: não cancela; um /status novo sai assim que o em voo termina", async () => {
    await montarAteStatusDoPollingNoAr();
    await avancar(2550);
    const emVoo = statusNoAr();
    expect(emVoo).toBeDefined();
    const clique = agora();

    fireEvent.click(screen.getByRole("button", { name: /^\s*Atualizar\s*$/ }));
    await avancar(15_000);

    expect(cancelados()).toEqual([]);
    expect(emVoo!.desfecho).toBe("200");
    // O pedido do usuário não se perde: o /status seguinte sai quando o em voo termina.
    const seguinte = daRota("status").find((e) => e.inicio >= (emVoo!.fim as number));
    expect(seguinte).toBeDefined();
    expect(seguinte!.inicio - (emVoo!.fim as number)).toBeLessThan(50);
    expect(seguinte!.desfecho).toBe("200");
    // O que estava parado recarrega na hora.
    expect(daRota("alertas").some((e) => e.inicio >= clique && e.inicio < clique + 50)).toBe(true);
  });

  it("'Atualizar' com a tela parada (nada em andamento) recarrega status, histórico e alertas na hora", async () => {
    concluiEm = 0;
    await montar();
    await avancar(10_000, 50);
    expect(eventos.map((e) => e.rota).sort()).toEqual(["alertas", "historico", "status"]);
    const clique = agora();

    fireEvent.click(screen.getByRole("button", { name: /^\s*Atualizar\s*$/ }));
    await avancar(8_000, 50);

    for (const rota of ["status", "historico", "alertas"] as const) {
      const novos = daRota(rota).filter((e) => e.inicio >= clique);
      expect(novos).toHaveLength(1);
      expect(novos[0].inicio - clique).toBeLessThan(50);
      expect(novos[0].desfecho).toBe("200");
    }
    expect(cancelados()).toEqual([]);
  });

  it("falha de rede no fim de um /status: a nova tentativa do useApi não é cancelada pelo polling", async () => {
    falharStatusNumero = 2;
    falhaAntesMs = 400;
    await montar();
    await avancar(60_000, 50);

    const st = daRota("status");
    const falha = st.find((e) => e.desfecho === "falha");
    expect(falha).toBeDefined();
    expect(cancelados()).toEqual([]);
    const repeticao = st.find((e) => e.inicio > (falha!.fim as number));
    expect(repeticao).toBeDefined();
    expect(repeticao!.inicio - (falha!.fim as number)).toBeGreaterThanOrEqual(300);
    expect(repeticao!.desfecho).toBe("200");
  });

  it("sair da tela com um /status no ar cancela só ele e nada mais é consultado", async () => {
    const tela = await montarAteStatusDoPollingNoAr();
    await avancar(3600);
    const saida = agora();
    tela.unmount();
    await avancar(30_000, 100);

    expect(cancelados().map((e) => e.rota)).toEqual(["status"]);
    expect(eventos.filter((e) => e.inicio > saida)).toEqual([]);
  });

  it("admin global: o painel geral entra no mesmo polling e também não é cancelado", async () => {
    await montar({ usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: 1 }) });
    await avancar(40_000, 50);

    expect(cancelados()).toEqual([]);
    expect(daRota("dashboard").filter((e) => e.desfecho === "200").length).toBeGreaterThanOrEqual(3);
  });
});
