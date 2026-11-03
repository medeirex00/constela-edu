/**
 * Atualização do PWA (lib/pwaAtualizacao.ts + components/PwaAviso.tsx): a versão
 * nova é detectada e aplicada de forma PREVISÍVEL, sem perder formulário em edição.
 * O `registerSW` do vite-plugin-pwa e o `navigator.serviceWorker` são falsos (o
 * plugin não roda no Vitest): o teste dispara os mesmos callbacks que o plugin.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RegisterSWOptions } from "vite-plugin-pwa/types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import fonteDoViteConfig from "../../vite.config.ts?raw";
import { PwaAviso } from "../components/PwaAviso";
import { criarAtualizacaoPwa, ehTelaPublica, type DependenciasPwa } from "../lib/pwaAtualizacao";

/** Service worker falso (instalando/esperando) com o `statechange` que o navegador dispara. */
function workerFalso(state = "installing") {
  const ouvintes: (() => void)[] = [];
  return {
    state,
    addEventListener: (_t: "statechange", fn: () => void) => { ouvintes.push(fn); },
    mudarPara(novo: string) { this.state = novo; for (const fn of ouvintes) fn(); },
  };
}
type WorkerFalso = ReturnType<typeof workerFalso>;

/** Monta a máquina com tudo falso e devolve os "gatilhos" do plugin/navegador. */
function montar(over: Partial<DependenciasPwa> & {
  caminho?: string; comControle?: boolean; carregando?: boolean; esperandoNoRegistro?: WorkerFalso;
  /** 1ª visita: o registro ainda não tem worker ativo (nem nesta aba, nem em outra). */
  semAtivoNoRegistro?: boolean;
} = {}) {
  let opcoes: RegisterSWOptions = {};
  const atualizarSW = vi.fn(async () => undefined);
  const registrar = vi.fn((o: RegisterSWOptions) => { opcoes = o; return atualizarSW; });
  const aoTrocarControle: (() => void)[] = [];
  const sw = {
    controller: over.comControle === false ? null : {},
    addEventListener: (_t: "controllerchange", fn: () => void) => { aoTrocarControle.push(fn); },
  };
  const ouvintesJanela = new Map<string, (() => void)[]>();
  const janela = {
    location: { pathname: over.caminho ?? "/alunos" } as Location,
    addEventListener: (tipo: string, fn: () => void) => {
      ouvintesJanela.set(tipo, [...(ouvintesJanela.get(tipo) ?? []), fn]);
    },
    setInterval: ((fn: () => void, ms: number) => window.setInterval(fn, ms)) as Window["setInterval"],
    setTimeout: ((fn: () => void, ms: number) => window.setTimeout(fn, ms)) as Window["setTimeout"],
    clearTimeout: ((id: number) => window.clearTimeout(id)) as Window["clearTimeout"],
  };
  const ouvintesDoc: (() => void)[] = [];
  const documento = {
    visibilityState: "visible" as DocumentVisibilityState,
    // Padrão: a página já carregou (o pedido de troca não espera o `load`).
    readyState: (over.carregando ? "interactive" : "complete") as DocumentReadyState,
    addEventListener: (_t: string, fn: () => void) => { ouvintesDoc.push(fn); },
  };
  const guardado = new Map<string, string>();
  const sessao = { getItem: (k: string) => guardado.get(k) ?? null, setItem: (k: string, v: string) => { guardado.set(k, v); } };
  const recarregar = vi.fn();
  const recarregarDaRede = vi.fn();
  let relogio = 0;
  const atualizacao = criarAtualizacaoPwa({
    registrar, sw, janela, documento, recarregar, recarregarDaRede, sessao, agora: () => relogio, ...over,
  } as DependenciasPwa);
  // Registro falso com o `updatefound` do navegador (a detecção própria liga nele).
  // Com um worker ativo, como todo registro que já instalou alguma vez — mesmo numa
  // página sem controle (outra aba segura o worker).
  const aoAcharVersao: (() => void)[] = [];
  const reg = {
    installing: null as WorkerFalso | null,
    waiting: (over.esperandoNoRegistro ?? null) as WorkerFalso | null,
    active: (over.semAtivoNoRegistro ? null : workerFalso("activated")) as WorkerFalso | null,
    update: vi.fn(async () => undefined),
    addEventListener: (_t: "updatefound", fn: () => void) => { aoAcharVersao.push(fn); },
  };
  const registro = reg as unknown as ServiceWorkerRegistration;
  return {
    atualizacao, atualizarSW, recarregar, recarregarDaRede, registro, registrar, documento, sessao,
    avancar: (ms: number) => { relogio += ms; },
    novaVersao: () => act(() => { opcoes.onNeedRefresh?.(); }),
    registrado: () => opcoes.onRegisteredSW?.("/sw.js", registro),
    controleTrocou: () => act(() => { for (const fn of aoTrocarControle) fn(); }),
    pluginPedeRecarga: () => act(() => { opcoes.onNeedReload?.(); }),
    interagir: () => act(() => { for (const fn of ouvintesJanela.get("keydown") ?? []) fn(); }),
    carregou: () => act(() => { for (const fn of ouvintesJanela.get("load") ?? []) fn(); }),
    voltarParaAba: () => { for (const fn of ouvintesDoc) fn(); },
    conexaoVoltou: () => { for (const fn of ouvintesJanela.get("online") ?? []) fn(); },
    /** O navegador achou um sw.js novo e começou a instalar (o plugin NÃO é avisado). */
    instalacaoComecou: () => {
      const w = workerFalso();
      reg.installing = w;
      for (const fn of aoAcharVersao) fn();
      return w;
    },
    /** A instalação terminou: o worker vai para "esperando" (ou "redundant" se falhou). */
    instalacaoTerminou: (w: WorkerFalso, ok = true) => act(() => {
      reg.installing = null;
      if (ok) reg.waiting = w;
      w.mudarPara(ok ? "installed" : "redundant");
    }),
    /** 1ª instalação, como o Chromium mostra: no 'installed' ela aparece em `waiting`
     *  por um instante (sem worker ativo) e logo ativa sozinha. */
    primeiraInstalacaoTerminou: (w: WorkerFalso) => act(() => {
      reg.installing = null;
      reg.waiting = w;
      w.mudarPara("installed");
      reg.waiting = null;
      reg.active = w;
      w.mudarPara("activating");
      w.mudarPara("activated");
    }),
    reg,
    opcoes: () => opcoes,
  };
}

describe("PWA — versão nova no app logado", () => {
  it("o registro é imediato e em modo 'prompt' (o vite.config não volta ao autoUpdate)", () => {
    const m = montar();
    expect(m.registrar).toHaveBeenCalledTimes(1);
    expect(m.opcoes().immediate).toBe(true);
    // Com "autoUpdate" o plugin liga skipWaiting e recarrega a página sozinho.
    expect(fonteDoViteConfig).toMatch(/registerType:\s*"prompt"/);
    expect(fonteDoViteConfig).not.toMatch(/registerType:\s*"autoUpdate"/);
  });

  it("depois de a pessoa usar a tela: só AVISA — nada recarrega nem troca sem o clique", async () => {
    const m = montar();
    m.interagir();                       // começou a preencher um formulário
    await m.novaVersao();
    expect(m.atualizacao.estado()).toBe("disponivel");
    expect(m.atualizarSW).not.toHaveBeenCalled();
    expect(m.recarregar).not.toHaveBeenCalled();
  });

  it("'Atualizar agora' manda o service worker novo assumir e recarrega UMA vez", async () => {
    const m = montar();
    m.interagir();
    m.avancar(30_000);                                // usando a tela há meio minuto
    await m.novaVersao();
    m.atualizacao.atualizarAgora();
    expect(m.atualizacao.estado()).toBe("aplicando");
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    expect(m.recarregar).not.toHaveBeenCalled();     // ainda não assumiu
    await m.controleTrocou();
    await m.pluginPedeRecarga();                      // o plugin também avisa: sem recarga dupla
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("'Depois' some com o aviso; a próxima versão volta a avisar", async () => {
    const m = montar();
    m.interagir();
    await m.novaVersao();
    m.atualizacao.dispensar();
    expect(m.atualizacao.estado()).toBe("ocioso");
    await m.novaVersao();
    expect(m.atualizacao.estado()).toBe("disponivel");
  });

  it("outra aba aplicou a versão: esta NÃO recarrega sozinha (formulário a salvo) e avisa", async () => {
    const m = montar();
    m.interagir();
    await m.novaVersao();
    await m.controleTrocou();
    await m.pluginPedeRecarga();
    expect(m.recarregar).not.toHaveBeenCalled();
    expect(m.atualizacao.estado()).toBe("aplicada-em-outra-aba");
    m.atualizacao.recarregar();
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("1ª instalação (sem service worker antes) não é troca de versão", async () => {
    const m = montar({ comControle: false });
    await m.controleTrocou();
    expect(m.atualizacao.estado()).toBe("ocioso");
    expect(m.recarregar).not.toHaveBeenCalled();
  });
});

describe("PWA — abertura do app e telas públicas", () => {
  it("na abertura, antes de qualquer toque, a versão que já esperava entra direto (F5 comum basta)", async () => {
    const m = montar();
    m.avancar(2_000);
    await m.novaVersao();
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    expect(m.atualizacao.estado()).toBe("trocando");       // automática: sem cartão
    await m.controleTrocou();
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("passada a janela da abertura, mesmo sem toque, vira aviso", async () => {
    const m = montar();
    m.avancar(10_001);
    await m.novaVersao();
    expect(m.atualizacao.estado()).toBe("disponivel");
    expect(m.atualizarSW).not.toHaveBeenCalled();
  });

  it.each(["/p/tok-telao", "/rede/p/tok-vitrine"])("tela pública %s troca e recarrega sozinha", async (caminho) => {
    const m = montar({ caminho });
    m.interagir();
    m.avancar(3_600_000);
    await m.novaVersao();
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    await m.controleTrocou();
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("ehTelaPublica: só o telão e a vitrine", () => {
    expect(ehTelaPublica("/p/abc")).toBe(true);
    expect(ehTelaPublica("/rede/p/abc")).toBe(true);
    for (const c of ["/", "/painel-publico", "/rede", "/rede/analise", "/premiacoes"]) expect(ehTelaPublica(c)).toBe(false);
  });
});

describe("PWA — procura por versão nova (aba aberta o dia todo, telão na TV)", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("procura a cada hora, ao voltar para a aba (5+ min depois) e quando a conexão volta", () => {
    const m = montar({ agora: () => Date.now() });     // o relógio falso do Vitest
    m.registrado();
    expect(m.registro.update).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60 * 60_000);
    expect(m.registro.update).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(60_000);                    // 1 min depois: não procura de novo
    m.voltarParaAba();
    expect(m.registro.update).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5 * 60_000);
    m.voltarParaAba();
    expect(m.registro.update).toHaveBeenCalledTimes(2);
    m.conexaoVoltou();
    expect(m.registro.update).toHaveBeenCalledTimes(3);
  });

  it("sem conexão não procura (e uma falha de rede na procura não quebra nada)", () => {
    const m = montar({ online: () => false });
    m.registrado();
    vi.advanceTimersByTime(2 * 60 * 60_000);
    expect(m.registro.update).not.toHaveBeenCalled();
    const comRede = montar();
    (comRede.registro.update as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    comRede.registrado();
    expect(() => vi.advanceTimersByTime(60 * 60_000)).not.toThrow();
  });
});

describe("PWA — plano B quando o service worker novo não assume", () => {
  /** Um relógio de verdade (a marca do plano B é um Date.now()). */
  const AGORA = Date.UTC(2026, 9, 20, 12);
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("sem a troca de controle em 4 s, recarrega pela rede (o F5 não deixa na versão antiga) e marca a aba", async () => {
    const m = montar({ agora: () => AGORA });
    await m.novaVersao();                     // abertura: troca direto, pedido 1 s depois do load
    vi.advanceTimersByTime(1_000);
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(3_999);
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(m.recarregarDaRede).toHaveBeenCalledTimes(1);
    expect(m.sessao.getItem("pwa_plano_b_em")).toBe(String(AGORA));
    await m.controleTrocou();                 // se ainda chegar: nada de recarga dupla
    expect(m.recarregar).not.toHaveBeenCalled();
  });

  it("com a troca de controle no prazo, o plano B não dispara", async () => {
    const m = montar();
    await m.novaVersao();
    vi.advanceTimersByTime(1_000);
    await m.controleTrocou();
    vi.advanceTimersByTime(10_000);
    expect(m.recarregar).toHaveBeenCalledTimes(1);
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
  });

  it("plano B no máximo uma vez a cada 10 min por aba: o app volta ao aviso em vez de recarregar de novo", async () => {
    const m = montar({ agora: () => AGORA });
    m.sessao.setItem("pwa_plano_b_em", String(AGORA - 60_000));   // a aba voltou do plano B há 1 min
    await m.novaVersao();
    vi.advanceTimersByTime(1_000 + 4_000);
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    expect(m.recarregar).not.toHaveBeenCalled();
    expect(m.atualizacao.estado()).toBe("disponivel");     // a pessoa decide (o botão volta a valer)
  });

  it("plano B barrado na vitrine: tenta de novo quando o intervalo de 10 min passa (uma vez)", async () => {
    let relogio = AGORA;
    const m = montar({ caminho: "/rede/p/tok-vitrine", agora: () => relogio });
    m.sessao.setItem("pwa_plano_b_em", String(AGORA - 60_000));
    await m.novaVersao();
    relogio = AGORA + 5_000;
    vi.advanceTimersByTime(5_000);
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    relogio = AGORA + 9 * 60_000;
    vi.advanceTimersByTime(9 * 60_000 - 5_000);
    expect(m.recarregarDaRede).toHaveBeenCalledTimes(1);
  });
});

describe("PWA — página que veio da rede não entra em laço de recarga", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("sem service worker no controle (Ctrl+Shift+R, volta do plano B com outra aba aberta): a versão que espera não recarrega nada", async () => {
    // Medido no Chromium: com outra aba segurando o worker antigo, o plano B
    // desregistra, a página volta SEM controle, o register() reaproveita o mesmo
    // registro com o mesmo worker esperando — e a troca recomeçava a cada 4 s.
    const m = montar({ comControle: false });
    m.avancar(2_000);
    await m.novaVersao();
    vi.advanceTimersByTime(60_000);
    expect(m.atualizarSW).not.toHaveBeenCalled();
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    expect(m.recarregar).not.toHaveBeenCalled();
    expect(m.atualizacao.estado()).toBe("ocioso");        // ela já é a versão nova: nada de aviso
  });

  it("telão /p/ (o service worker nunca serve esse HTML) aberto com versão esperando: não recarrega; deploy DEPOIS de aberto, sim", async () => {
    // A rota /p/ fica fora do fallback do service worker: a página e os arquivos
    // dela vêm da rede mesmo com um worker antigo no controle.
    expect(fonteDoViteConfig).toMatch(/navigateFallbackDenylist:\s*\[[^\]]*\/\^\\\/p\\\/\//);
    const m = montar({ caminho: "/p/tok-telao" });
    m.avancar(1_000);
    await m.novaVersao();
    vi.advanceTimersByTime(60_000);
    expect(m.atualizarSW).not.toHaveBeenCalled();
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    m.avancar(3_600_000);                                 // deploy novo uma hora depois
    await m.novaVersao();
    vi.advanceTimersByTime(1_000);
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    await m.controleTrocou();
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("o worker que já esperava na abertura não volta como versão nova na procura de hora em hora", async () => {
    let relogio = 0;
    const esperando = workerFalso("installed");
    const m = montar({ comControle: false, esperandoNoRegistro: esperando, agora: () => relogio });
    await m.novaVersao();                                 // o plugin avisa antes do registro chegar
    m.registrado();
    relogio = 60 * 60_000;
    await vi.advanceTimersByTimeAsync(60 * 60_000);
    expect(m.reg.update).toHaveBeenCalledTimes(1);
    expect(m.atualizacao.estado()).toBe("ocioso");
    expect(m.atualizarSW).not.toHaveBeenCalled();
    // Um deploy de verdade depois de a página abrir: aí ela está velha e avisa.
    const nova = m.instalacaoComecou();
    await m.instalacaoTerminou(nova);
    expect(m.atualizacao.estado()).toBe("disponivel");
  });
});

describe("PWA — a versão nova é vista mesmo quando o plugin não avisa", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("1ª instalação falha (o workbox-window desliga o ouvinte dele), a 2ª dá certo: a aba aberta mostra o aviso", async () => {
    const m = montar();
    m.interagir();
    m.avancar(3_600_000);
    m.registrado();
    const falhou = m.instalacaoComecou();
    await m.instalacaoTerminou(falhou, false);           // rede caiu no precache
    expect(m.atualizacao.estado()).toBe("ocioso");
    const certa = m.instalacaoComecou();                  // a procura seguinte instala certo
    await m.instalacaoTerminou(certa);
    expect(m.atualizacao.estado()).toBe("disponivel");
    expect(m.atualizarSW).not.toHaveBeenCalled();
  });

  it("no telão, a mesma 2ª instalação troca sozinha", async () => {
    const m = montar({ caminho: "/p/tok-telao" });
    m.avancar(3_600_000);
    m.registrado();
    await m.instalacaoTerminou(m.instalacaoComecou(), false);
    await m.instalacaoTerminou(m.instalacaoComecou());
    vi.advanceTimersByTime(1_000);
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    await m.controleTrocou();
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("instalação que já tinha começado quando o registro chegou também é vista", async () => {
    const m = montar();
    m.interagir();
    m.avancar(30_000);
    const andamento = workerFalso();
    m.reg.installing = andamento;
    m.registrado();
    await m.instalacaoTerminou(andamento);
    expect(m.atualizacao.estado()).toBe("disponivel");
  });

  it("depois da procura de hora em hora, o worker que já espera (e ninguém avisou) vira aviso", async () => {
    let relogio = 30_000;
    const m = montar({ agora: () => relogio });
    m.interagir();
    m.registrado();
    m.reg.waiting = workerFalso("installed");
    relogio += 60 * 60_000;
    await vi.advanceTimersByTimeAsync(60 * 60_000);
    expect(m.atualizacao.estado()).toBe("disponivel");
  });

  it("plugin e detecção própria avisando o MESMO worker = uma decisão só; 'Depois' não volta na procura seguinte", async () => {
    let relogio = 30_000;
    const m = montar({ agora: () => relogio });
    m.interagir();
    m.registrado();
    const nova = m.instalacaoComecou();
    await m.instalacaoTerminou(nova);
    await m.novaVersao();                                 // o plugin avisa o mesmo worker
    expect(m.atualizacao.estado()).toBe("disponivel");
    m.atualizacao.dispensar();
    await m.novaVersao();                                 // o "waiting" do plugin, 200 ms depois
    relogio += 60 * 60_000;
    await vi.advanceTimersByTimeAsync(60 * 60_000);       // a procura reencontra o mesmo worker
    expect(m.atualizacao.estado()).toBe("ocioso");
  });
});

describe("PWA — 1ª instalação do service worker não é versão nova", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  // Medido no Chromium (build real, precache de 186 arquivos/3,78 MB com um chunk
  // segurado por 11–13 s): no 'installed' da 1ª instalação, `waiting` === o worker
  // por um instante. Passada a janela da abertura, isso virava aviso no /login e
  // troca + plano B (worker recém-instalado desregistrado, 2 cargas) no telão/vitrine.
  it.each(["/login", "/p/tok-telao", "/rede/p/tok-vitrine"])(
    "%s na 1ª visita, precache mais lento que a janela da abertura: fica ocioso, sem troca nem plano B",
    async (caminho) => {
      let relogio = 0;
      const m = montar({ caminho, comControle: false, semAtivoNoRegistro: true, agora: () => relogio });
      render(<PwaAviso atualizacao={m.atualizacao} />);
      const primeira = workerFalso();
      m.reg.installing = primeira;                // o register() devolve o registro já instalando
      m.registrado();
      relogio = 12_000;
      vi.advanceTimersByTime(12_000);
      await m.primeiraInstalacaoTerminou(primeira);
      vi.advanceTimersByTime(60_000);
      expect(m.atualizacao.estado()).toBe("ocioso");
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      expect(m.atualizarSW).not.toHaveBeenCalled();
      expect(m.recarregarDaRede).not.toHaveBeenCalled();
      expect(m.recarregar).not.toHaveBeenCalled();
    },
  );

  it("a 1ª instalação que começa depois do registro (updatefound) também não vira aviso", async () => {
    let relogio = 0;
    const m = montar({ caminho: "/login", comControle: false, semAtivoNoRegistro: true, agora: () => relogio });
    m.registrado();
    const primeira = m.instalacaoComecou();
    relogio = 15_000;
    await m.primeiraInstalacaoTerminou(primeira);
    expect(m.atualizacao.estado()).toBe("ocioso");
  });

  it("a conexão volta no instante em que a 1ª instalação aparece em `waiting`: a procura não a toma por versão nova", async () => {
    let relogio = 0;
    const m = montar({ caminho: "/p/tok-telao", comControle: false, semAtivoNoRegistro: true, agora: () => relogio });
    m.registrado();
    const primeira = workerFalso("installed");
    m.reg.update.mockImplementation(async () => { m.reg.waiting = primeira; return undefined; });
    relogio = 20_000;
    m.conexaoVoltou();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(m.reg.update).toHaveBeenCalledTimes(1);
    expect(m.atualizacao.estado()).toBe("ocioso");
    expect(m.atualizarSW).not.toHaveBeenCalled();
  });

  it("depois que a 1ª instalação ativa, um deploy de verdade continua sendo visto", async () => {
    let relogio = 0;
    const m = montar({ caminho: "/login", comControle: false, semAtivoNoRegistro: true, agora: () => relogio });
    m.registrado();
    const primeira = m.instalacaoComecou();
    relogio = 15_000;
    await m.primeiraInstalacaoTerminou(primeira);
    relogio = 60 * 60_000;                              // uma hora depois, sai um deploy
    await m.instalacaoTerminou(m.instalacaoComecou());
    expect(m.atualizacao.estado()).toBe("disponivel");
  });
});

describe("PWA — o clique não é barrado pela marca do plano B", () => {
  const AGORA = Date.UTC(2026, 9, 21, 12);
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("nos 10 min depois de um plano B, 'Atualizar agora' numa página sem controle recarrega pela rede", async () => {
    // A página é a volta de um plano B de 1 min atrás (sem controle; outra aba segura
    // o worker). Chega um deploy: o worker novo nunca assume esta página (sem
    // clientsClaim), então só o plano B a atualiza. Barrado pela marca, o clique
    // voltava ao aviso sem fazer nada.
    let relogio = AGORA;
    const m = montar({ comControle: false, agora: () => relogio });
    m.sessao.setItem("pwa_plano_b_em", String(AGORA - 60_000));
    m.interagir();
    m.registrado();
    relogio = AGORA + 2 * 60_000;
    await m.instalacaoTerminou(m.instalacaoComecou());
    expect(m.atualizacao.estado()).toBe("disponivel");
    m.atualizacao.atualizarAgora();
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(4_000);
    expect(m.recarregarDaRede).toHaveBeenCalledTimes(1);
    expect(m.atualizacao.estado()).toBe("aplicando");
    expect(m.sessao.getItem("pwa_plano_b_em")).toBe(String(relogio));
  });

  it("a troca AUTOMÁTICA continua barrada no mesmo intervalo (é ela que fazia o laço)", async () => {
    const m = montar({ agora: () => AGORA });
    m.sessao.setItem("pwa_plano_b_em", String(AGORA - 60_000));
    await m.novaVersao();
    expect(m.atualizacao.estado()).toBe("trocando");
    vi.advanceTimersByTime(1_000 + 4_000);
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    expect(m.atualizacao.estado()).toBe("disponivel");
    m.atualizacao.atualizarAgora();                     // a pessoa decide: aí vale
    vi.advanceTimersByTime(1_000 + 4_000);              // relógio parado: o atraso pós-load conta de novo
    expect(m.recarregarDaRede).toHaveBeenCalledTimes(1);
  });
});

describe("PWA — troca automática da abertura não atropela quem começou a usar a tela", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("o pedido de troca sai 1 s depois do load (enviado durante a carga, o Chromium o deixa preso)", async () => {
    let relogio = 0;
    const m = montar({ carregando: true, agora: () => relogio });
    await m.novaVersao();                                 // aviso do plugin com a página ainda carregando
    vi.advanceTimersByTime(5_000);
    expect(m.atualizarSW).not.toHaveBeenCalled();
    relogio = 200;
    await m.carregou();
    vi.advanceTimersByTime(999);
    expect(m.atualizarSW).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
  });

  it("tocou/digitou antes da recarga: cancela a troca (sem plano B), vira o aviso e a troca que chegar depois não recarrega", async () => {
    const m = montar();
    m.avancar(500);
    render(<PwaAviso atualizacao={m.atualizacao} />);
    const regiao = screen.getByRole("status");
    await m.novaVersao();
    expect(m.atualizacao.estado()).toBe("trocando");
    expect(regiao).toBeEmptyDOMElement();                 // ninguém pediu: sem cartão
    vi.advanceTimersByTime(1_000);                        // o pedido já saiu
    await m.interagir();                                  // começou a digitar o e-mail
    expect(m.atualizacao.estado()).toBe("disponivel");
    expect(regiao).toHaveTextContent("Nova versão do Constela disponível");
    vi.advanceTimersByTime(60_000);
    expect(m.recarregarDaRede).not.toHaveBeenCalled();
    await m.controleTrocou();                             // o worker novo assumiu mais tarde
    expect(m.recarregar).not.toHaveBeenCalled();
    expect(m.atualizacao.estado()).toBe("aplicada-em-outra-aba");
  });

  it("tocou antes de o pedido sair: o SKIP_WAITING nem é enviado", async () => {
    const m = montar();
    await m.novaVersao();
    await m.interagir();
    vi.advanceTimersByTime(10_000);
    expect(m.atualizarSW).not.toHaveBeenCalled();
    expect(m.atualizacao.estado()).toBe("disponivel");
  });

  it("no telão/vitrine um toque não cancela a troca (não há formulário)", async () => {
    const m = montar({ caminho: "/rede/p/tok-vitrine" });
    await m.novaVersao();
    await m.interagir();
    vi.advanceTimersByTime(1_000);
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    expect(m.atualizacao.estado()).toBe("trocando");
  });
});

describe("PwaAviso", () => {
  it("anuncia a versão nova (role=status) e o clique aplica; 'Depois' some com o aviso", async () => {
    const m = montar();
    m.interagir();
    m.avancar(30_000);
    render(<PwaAviso atualizacao={m.atualizacao} />);
    const regiao = screen.getByRole("status");
    expect(regiao).toBeEmptyDOMElement();
    await m.novaVersao();
    expect(regiao).toHaveTextContent("Nova versão do Constela disponível");
    expect(regiao).toHaveTextContent("Salve o que estiver editando");
    await userEvent.click(screen.getByRole("button", { name: "Depois" }));
    expect(regiao).toBeEmptyDOMElement();
    await m.novaVersao();
    await userEvent.click(screen.getByRole("button", { name: "Atualizar agora" }));
    expect(m.atualizarSW).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Atualizando…" })).toBeDisabled();
  });

  it("atualizada em outra aba: pede para recarregar quando der", async () => {
    const m = montar();
    m.interagir();
    render(<PwaAviso atualizacao={m.atualizacao} />);
    await m.controleTrocou();
    expect(screen.getByRole("status")).toHaveTextContent("atualizado em outra aba");
    await userEvent.click(screen.getByRole("button", { name: "Recarregar" }));
    expect(m.recarregar).toHaveBeenCalledTimes(1);
  });

  it("nas telas públicas não monta nada (elas trocam sozinhas)", () => {
    const m = montar({ caminho: "/p/tok" });
    window.history.pushState({}, "", "/p/tok");
    try {
      const { container } = render(<PwaAviso atualizacao={m.atualizacao} />);
      expect(container).toBeEmptyDOMElement();
    } finally {
      window.history.pushState({}, "", "/");
    }
  });
});
