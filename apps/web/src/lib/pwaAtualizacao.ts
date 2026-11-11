/**
 * Atualização PREVISÍVEL do app instalado (PWA) — ver docs/operacao/PWA-ATUALIZACAO.md.
 *
 * Antes (registerType "autoUpdate"): o service worker novo entrava sozinho
 * (skipWaiting) e o vite-plugin-pwa recarregava a página na hora — segundos depois
 * de abrir o app, às vezes com alguém digitando (o formulário se perdia). E uma aba
 * que ficava aberta o dia todo (ou o telão na TV por semanas) só procurava versão
 * nova numa navegação de verdade: seguia na antiga até alguém dar "hard refresh".
 *
 * Agora (registerType "prompt"): a versão nova é baixada e ESPERA. Quem decide a
 * troca é esta máquina de estados:
 *   - app autenticado: aviso "Nova versão disponível — Atualizar agora". Nada
 *     recarrega sem o clique (quem está editando salva antes) enquanto o aviso
 *     espera numa aba servida pelo service worker: as telas dela seguem abrindo
 *     pela versão antiga, do cache. A página que veio da rede (1ª visita,
 *     Ctrl+Shift+R, plano B) mostra o mesmo aviso, mas é a exceção descrita em
 *     "outra aba atualizou", abaixo;
 *   - abertura do app servida pelo service worker (F5 comum, aba nova, ícone): se
 *     já havia versão nova esperando e a pessoa ainda não tocou na tela, ela entra
 *     direto, sem cartão. Se a pessoa tocar ou digitar antes da recarga, a troca é
 *     cancelada e vira o aviso — nada do que ela digitou se perde;
 *   - página que veio da REDE — sem service worker no controle (Ctrl+Shift+R, a
 *     recarga do plano B) ou o telão /p/, que o service worker nunca serve: ela JÁ
 *     é a versão mais nova que havia quando abriu. A versão que encontra esperando
 *     na abertura não é mais nova que ela; trocar só recarregava à toa — e, com
 *     outra aba segurando o service worker antigo, em laço a cada 4 s;
 *   - telas públicas (telão /p/…, vitrine /rede/p/…): sem formulário e sem
 *     ninguém para clicar, a troca é automática;
 *   - outra aba atualizou: esta não recarrega na hora; avisa para recarregar
 *     quando der. Mas o service worker novo, que agora a controla, não tem os
 *     arquivos da versão antiga, e o servidor também não: se a pessoa abrir uma
 *     tela que esta aba ainda não tinha aberto, ela recarrega UMA vez, sozinha, já
 *     na versão nova, sem perder o login (o socorro de lib/atualizacao.ts). O mesmo
 *     vale para a página que veio da rede (1ª visita, Ctrl+Shift+R, plano B) depois
 *     de um deploy;
 *   - procura versão nova a cada hora, ao voltar para a aba (5+ min depois da
 *     última procura) e ao voltar a conexão. A versão que chega é vista aqui também
 *     (updatefound/statechange do próprio registro), não só pelos avisos do
 *     plugin: o workbox-window desliga o ouvinte dele na 1ª atualização "externa",
 *     e uma 1ª instalação que falhasse deixava o telão cego para todos os deploys.
 *     A 1ª instalação do service worker (nenhum worker ativo no registro) não é
 *     versão nova: ela ativa sozinha ao instalar;
 *   - o pedido de troca (SKIP_WAITING) sai 1 s depois do `load`. Medido no
 *     Chromium com o build real: enviado durante a carga da página, ele fica PRESO —
 *     o worker novo não assume enquanto a página viver e reenviar não adianta
 *     (mais da metade das aberturas caía no plano B); 300 ms ou 1 s depois do
 *     `load`, assume na hora (10 de 10);
 *   - se o service worker novo ainda assim não assumir em 4 s, plano B: desregistra
 *     o service worker e recarrega (a página vem da rede). Na troca automática, no
 *     máximo uma vez a cada 10 min por aba (marca na sessionStorage, como o socorro
 *     do chunk obsoleto); o clique em "Atualizar agora" não é barrado pela marca.
 *
 * Sem import do módulo virtual `virtual:pwa-register` aqui: o main.tsx entrega o
 * `registerSW` e os testes, um falso (o plugin do PWA não roda no Vitest).
 */
import type { RegisterSWOptions } from "vite-plugin-pwa/types";

export type EstadoPwa =
  /** Nada a fazer. */
  | "ocioso"
  /** Versão nova baixada, esperando o clique. */
  | "disponivel"
  /** Clique dado: esperando o service worker novo assumir (cartão "Atualizando…"). */
  | "aplicando"
  /** Troca automática (abertura sem toque, telão/vitrine): a mesma espera, sem cartão. */
  | "trocando"
  /** Outra aba aplicou a versão nova: esta segue na antiga até recarregar. */
  | "aplicada-em-outra-aba";

type RegistrarSW = (opcoes: RegisterSWOptions) => (recarregar?: boolean) => Promise<void>;

/** O pedaço de `navigator.serviceWorker` que a máquina usa. */
interface ContainerSW {
  controller: unknown;
  addEventListener(tipo: "controllerchange", fn: () => void): void;
}

/** O pedaço de um service worker (instalando/esperando) que a detecção própria usa. */
interface WorkerSW {
  state: string;
  addEventListener(tipo: "statechange", fn: () => void): void;
}

/** O pedaço do `ServiceWorkerRegistration` que a máquina usa. */
interface RegistroSW {
  installing: WorkerSW | null;
  waiting: WorkerSW | null;
  /** Só importa se há ou não: sem worker ativo, quem instala é a 1ª instalação. */
  active: unknown;
  update(): Promise<unknown>;
  addEventListener(tipo: "updatefound", fn: () => void): void;
}

export interface DependenciasPwa {
  registrar: RegistrarSW;
  sw?: ContainerSW | null;
  janela?: Pick<Window, "addEventListener" | "setInterval" | "setTimeout" | "clearTimeout" | "location">;
  documento?: Pick<Document, "addEventListener" | "visibilityState" | "readyState">;
  recarregar?: () => void;
  /** Plano B: desregistra o service worker e recarrega (a página vem da rede). */
  recarregarDaRede?: () => void;
  /** Onde fica a marca do último plano B desta aba. Padrão: sessionStorage. */
  sessao?: Pick<Storage, "getItem" | "setItem"> | null;
  agora?: () => number;
  online?: () => boolean;
  /** Procura periódica por versão nova. Padrão: 1 hora. */
  intervaloMs?: number;
  /** Ao voltar para a aba, só procura se a última procura tiver mais que isto. */
  minimoEntreProcurasMs?: number;
  /** Na abertura, a troca direta só vale até este tempo sem interação. */
  janelaDeAberturaMs?: number;
  /** O pedido de troca só sai este tempo depois do `load` da página. Padrão: 1 s. */
  atrasoAposCargaMs?: number;
  /** Tempo para o service worker novo assumir antes do plano B. Padrão: 4 s. */
  prazoParaAssumirMs?: number;
  /** Intervalo mínimo entre dois planos B na mesma aba. Padrão: 10 min. */
  intervaloEntrePlanosBMs?: number;
}

/** Telão da escola (/p/…) e vitrine da rede (/rede/p/…): sem login e sem formulário. */
export function ehTelaPublica(caminho: string): boolean {
  return caminho.startsWith("/p/") || caminho.startsWith("/rede/p/");
}

/** O telão (/p/…) nunca é servido pelo service worker (`navigateFallbackDenylist` do
 *  vite.config.ts): o HTML vem sempre da rede e, com ele, os arquivos da versão do
 *  dia. A vitrine (/rede/p/…) não: ela vem do cache como o app. */
function htmlVemSempreDaRede(caminho: string): boolean {
  return caminho.startsWith("/p/");
}

export interface AtualizacaoPwa {
  estado(): EstadoPwa;
  assinar(ouvinte: () => void): () => void;
  /** "Atualizar agora": aplica a versão que está esperando e recarrega. */
  atualizarAgora(): void;
  /** "Depois": some com o aviso; a versão entra na próxima abertura do app. */
  dispensar(): void;
  /** Recarrega a página (aviso de "atualizada em outra aba"). */
  recarregar(): void;
}

/** Instância ociosa (antes do main.tsx ligar o registro, ou sem service worker). */
const OCIOSA: AtualizacaoPwa = {
  estado: () => "ocioso",
  assinar: () => () => undefined,
  atualizarAgora: () => undefined,
  dispensar: () => undefined,
  recarregar: () => undefined,
};

const CHAVE_PLANO_B = "pwa_plano_b_em";

function sessaoDoNavegador(): Pick<Storage, "getItem" | "setItem"> | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;   // navegação privada/bloqueada: sem a marca, sobra a regra da página da rede
  }
}

/** Desregistra o service worker e recarrega — a página vem da REDE, já na versão
 *  nova. É o plano B daqui, o socorro do chunk obsoleto (lib/atualizacao.ts) e o botão
 *  "Recarregar" da tela de erro (LimiteErro). Não apaga o cache do PWA: ele é de todas
 *  as abas do navegador, outra aba aberta ainda roda a versão antiga com ele, e sem o
 *  cache as telas dela (chunks com o nome de antes do deploy) não abririam mais. Para
 *  a recarga vir da rede basta desregistrar. */
export async function recarregarSemServiceWorker(): Promise<void> {
  try {
    const registros = (await navigator.serviceWorker?.getRegistrations?.()) ?? [];
    await Promise.all(registros.map((r) => r.unregister()));
  } catch {
    /* mesmo sem desregistrar, a recarga abaixo é a melhor tentativa */
  }
  window.location.reload();
}

export function criarAtualizacaoPwa(deps: DependenciasPwa): AtualizacaoPwa {
  const janela = deps.janela ?? window;
  const documento = deps.documento ?? document;
  const sw = deps.sw !== undefined ? deps.sw : (navigator.serviceWorker ?? null);
  const recarregarPagina = deps.recarregar ?? (() => window.location.reload());
  const recarregarDaRede = deps.recarregarDaRede ?? (() => { void recarregarSemServiceWorker(); });
  const sessao = deps.sessao !== undefined ? deps.sessao : sessaoDoNavegador();
  const agora = deps.agora ?? (() => Date.now());
  const online = deps.online ?? (() => navigator.onLine !== false);
  const intervaloMs = deps.intervaloMs ?? 60 * 60_000;
  const minimoEntreProcurasMs = deps.minimoEntreProcurasMs ?? 5 * 60_000;
  const janelaDeAberturaMs = deps.janelaDeAberturaMs ?? 10_000;
  const atrasoAposCargaMs = deps.atrasoAposCargaMs ?? 1_000;
  const prazoParaAssumirMs = deps.prazoParaAssumirMs ?? 4_000;
  const intervaloEntrePlanosBMs = deps.intervaloEntrePlanosBMs ?? 10 * 60_000;

  if (!sw) return OCIOSA;

  const inicio = agora();
  let estado: EstadoPwa = "ocioso";
  let pediu = false;            // ESTA aba pediu a troca (clique ou troca automática)
  let recarregou = false;       // guarda contra recarga dupla
  let interagiu = false;        // a pessoa já tocou/digitou nesta página
  let ultimaProcura = inicio;
  let carregouEm: number | null = documento.readyState === "complete" ? inicio : null;
  let aguardandoCarga = false;  // pedido de troca esperando o `load`
  let envio: number | undefined;   // pedido de troca agendado
  let prazo: number | undefined;   // plano B agendado
  const tinhaControle = sw.controller != null;
  // O HTML desta página veio da rede (e não do cache do service worker)? Vale o
  // caminho de QUANDO ela abriu: a navegação interna do app não busca HTML.
  const veioDaRede = !tinhaControle || htmlVemSempreDaRede(janela.location.pathname);
  let registro: RegistroSW | null = null;
  // O worker esperando que já virou decisão nesta página (aviso, troca ou "esta
  // página já é a nova"): o plugin avisa o mesmo worker mais de uma vez e a procura
  // de hora em hora o reencontra — sem isto, o "Depois" voltava a cada hora.
  let versaoDecidida: unknown = null;
  let pluginAvisouAntesDoRegistro = false;
  const ouvintes = new Set<() => void>();

  const mudar = (novo: EstadoPwa) => {
    if (novo === estado) return;
    estado = novo;
    for (const ouvinte of ouvintes) ouvinte();
  };
  const recarregarUmaVez = () => {
    if (recarregou) return;
    recarregou = true;
    recarregarPagina();
  };
  const publica = () => ehTelaPublica(janela.location.pathname);

  let atualizarSW: (recarregar?: boolean) => Promise<void> = async () => undefined;

  /** Desiste da troca pedida (sem recarregar) e vai para `proximo`. */
  const desistir = (proximo: EstadoPwa) => {
    pediu = false;
    aguardandoCarga = false;
    if (envio !== undefined) janela.clearTimeout(envio);
    if (prazo !== undefined) janela.clearTimeout(prazo);
    envio = prazo = undefined;
    mudar(proximo);
  };

  const restanteDoIntervaloDoPlanoB = (): number => {
    try {
      const ultimo = Number(sessao?.getItem(CHAVE_PLANO_B));
      return ultimo > 0 ? Math.min(ultimo + intervaloEntrePlanosBMs - agora(), intervaloEntrePlanosBMs) : 0;
    } catch {
      return 0;
    }
  };
  const planoB = () => {
    prazo = undefined;
    if (recarregou || !pediu) return;
    // A marca segura só a troca AUTOMÁTICA, que era a do laço. O clique é a pessoa
    // pedindo a cada vez: barrado, o botão "Atualizar agora" não fazia nada por 10 min
    // (numa página sem controle o worker novo nunca assume, só o plano B a atualiza).
    const restante = estado === "trocando" ? restanteDoIntervaloDoPlanoB() : 0;
    if (restante > 0) {
      // Esta aba já recarregou pelo plano B há pouco e o worker novo segue sem
      // assumir: recarregar de novo seria um laço. O app volta ao aviso (a pessoa
      // decide); o telão tenta outra vez quando o intervalo passar.
      if (publica()) prazo = janela.setTimeout(planoB, restante);
      else desistir("disponivel");
      return;
    }
    try {
      sessao?.setItem(CHAVE_PLANO_B, String(agora()));
    } catch {
      /* sem a marca: a página que volta da rede já não troca na abertura */
    }
    recarregou = true;
    recarregarDaRede();
  };
  const pedirTroca = () => {
    envio = undefined;
    if (recarregou || !pediu) return;
    void atualizarSW(true);
    prazo = janela.setTimeout(planoB, prazoParaAssumirMs);
  };
  /** Envia o SKIP_WAITING 1 s depois do `load` (antes disso ele fica preso no Chromium). */
  const agendarPedido = () => {
    if (carregouEm === null) {
      aguardandoCarga = true;
      return;
    }
    const falta = carregouEm + atrasoAposCargaMs - agora();
    if (falta > 0) envio = janela.setTimeout(pedirTroca, falta);
    else pedirTroca();
  };
  if (carregouEm === null) {
    janela.addEventListener("load", () => {
      carregouEm = agora();
      if (aguardandoCarga) {
        aguardandoCarga = false;
        agendarPedido();
      }
    }, { once: true });
  }

  const aplicar = (automatico: boolean) => {
    pediu = true;
    mudar(automatico ? "trocando" : "aplicando");
    agendarPedido();
  };

  for (const tipo of ["pointerdown", "keydown"] as const) {
    janela.addEventListener(tipo, () => {
      interagiu = true;
      // A troca automática da abertura ainda não recarregou e a pessoa começou a
      // usar a tela: a recarga apagaria o que ela digitar. Vira o aviso.
      if (estado === "trocando" && !publica()) desistir("disponivel");
    }, { capture: true });
  }

  /** Há uma versão nova esperando: o que fazer com ela NESTA página. */
  const versaoNova = () => {
    if (pediu) return;
    const naAbertura = agora() - inicio <= janelaDeAberturaMs;
    // Página que veio da rede: a versão que ela acha esperando ao abrir é a dela
    // (ou mais velha). Nada a trocar — era o laço de recarga com outra aba aberta.
    if (veioDaRede && naAbertura) return;
    if (publica() || (naAbertura && !interagiu)) aplicar(true);
    else mudar("disponivel");
  };

  // O service worker novo assumiu esta aba. Quem pediu recarrega (a página antiga
  // não pode seguir rodando com os arquivos novos); as outras abas só avisam.
  // Tela pública também recarrega: não há formulário a perder nem ninguém para clicar.
  sw.addEventListener("controllerchange", () => {
    if (!tinhaControle) return;            // 1ª instalação: nada mudou de versão
    if (pediu || publica()) recarregarUmaVez();
    else mudar("aplicada-em-outra-aba");
  });

  atualizarSW = deps.registrar({
    immediate: true,
    onNeedRefresh() {
      if (registro) {
        const esperando = registro.waiting;
        if (esperando && esperando === versaoDecidida) return;
        if (esperando) versaoDecidida = esperando;
      } else {
        pluginAvisouAntesDoRegistro = true;
      }
      versaoNova();
    },
    // Sem isto, o plugin dá window.location.reload() em toda aba que viu o aviso.
    onNeedReload() {
      if (pediu || publica()) recarregarUmaVez();
      else mudar("aplicada-em-outra-aba");
    },
    onRegisteredSW(_url, r) {
      if (!r) return;
      const reg: RegistroSW = r;
      registro = reg;
      // O worker que já esperava no registro é avisado pelo plugin (às vezes antes
      // de o registro chegar aqui): é a mesma decisão, não uma versão nova.
      if (pluginAvisouAntesDoRegistro && reg.waiting) versaoDecidida = reg.waiting;
      // A 1ª instalação (nenhum worker ativo no registro) ativa sozinha assim que
      // instala: não é versão nova. Mas no 'installed' dela o Chromium ainda mostra
      // `waiting` === ela por um instante — com o precache lento (mais que a janela
      // da abertura, na rede da escola), isso virava o aviso no /login e troca +
      // plano B no telão e na vitrine, na 1ª visita. Uma versão nova de verdade
      // sempre espera ATRÁS de um worker ativo.
      const primeiraInstalacao = () => reg.active == null;
      const conferir = () => {
        const esperando = reg.waiting;
        if (!esperando || primeiraInstalacao() || esperando === versaoDecidida) return;
        versaoDecidida = esperando;
        versaoNova();
      };
      const vigiados = new WeakSet<object>();
      const vigiar = (worker: WorkerSW | null) => {
        if (!worker || primeiraInstalacao() || vigiados.has(worker)) return;
        vigiados.add(worker);
        worker.addEventListener("statechange", () => {
          if (worker.state === "installed") conferir();
        });
      };
      reg.addEventListener("updatefound", () => vigiar(reg.installing));
      vigiar(reg.installing);      // instalação que começou antes do registro chegar aqui
      const procurar = () => {
        if (!online()) return;
        ultimaProcura = agora();
        // Falha de rede: tenta na próxima. Depois da procura, o que já estiver
        // instalando/esperando é conferido aqui mesmo.
        reg.update().then(() => { vigiar(reg.installing); conferir(); }, () => undefined);
      };
      janela.setInterval(procurar, intervaloMs);
      documento.addEventListener("visibilitychange", () => {
        if (documento.visibilityState === "visible" && agora() - ultimaProcura >= minimoEntreProcurasMs) procurar();
      });
      janela.addEventListener("online", procurar);
    },
  });

  return {
    estado: () => estado,
    assinar(ouvinte) {
      ouvintes.add(ouvinte);
      return () => ouvintes.delete(ouvinte);
    },
    atualizarAgora() {
      if (estado === "disponivel") aplicar(false);
    },
    dispensar() {
      if (estado === "disponivel") mudar("ocioso");
    },
    recarregar: recarregarUmaVez,
  };
}

let instancia: AtualizacaoPwa = OCIOSA;

/** Liga o registro do service worker (uma vez, no main.tsx, ANTES do 1º render). */
export function iniciarAtualizacaoPwa(registrar: RegistrarSW): AtualizacaoPwa {
  instancia = criarAtualizacaoPwa({ registrar });
  return instancia;
}

/** A instância ligada pelo main.tsx (ociosa fora dele: testes, sem service worker). */
export function atualizacaoPwaAtual(): AtualizacaoPwa {
  return instancia;
}
