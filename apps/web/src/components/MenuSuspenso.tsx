/**
 * Menu suspenso (kebab ⋮) compartilhado pelas tabelas de usuários, alunos e
 * turmas.
 *
 * O painel usa position:fixed calculado a partir do botão — um menu com
 * position:absolute dentro de contêiner com overflow-x-auto (as tabelas
 * roláveis) era CORTADO na vertical, e nas últimas linhas as opções do fim
 * (Excluir) ficavam inalcançáveis. Regras de posicionamento:
 *   1. abre para baixo quando cabe;
 *   2. senão, para cima quando cabe;
 *   3. senão (janela muito baixa), abre no lado com mais espaço e rola por
 *      dentro (max-height) — nenhum item fica inalcançável.
 * As medidas usam documentElement.clientWidth/Height (viewport de layout,
 * sem a barra de rolagem — window.innerWidth desalinharia ~15px no Windows
 * e mistura viewport visual/layout no pinch-zoom do iOS).
 *
 * Teclado: setas/Home/End navegam os itens, Esc fecha devolvendo o foco ao
 * botão, Tab para fora fecha. Rolar a página fecha (o painel fixo não
 * acompanha o botão), mas rolagem interna do painel não.
 */
import { MoreVertical } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export function ItemMenu({ icone, rotulo, destrutiva = false, onClick }: {
  icone: ReactNode;
  rotulo: string;
  destrutiva?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      role="menuitem"
      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${
        destrutiva
          ? "text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10"
          : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
      }`}
      onClick={onClick}
    >
      {icone}
      {rotulo}
    </button>
  );
}

export default function MenuSuspenso({ ariaLabel, largura = "w-56", children }: {
  ariaLabel: string;
  /** Classe de largura do painel (ex.: "w-56"). */
  largura?: string;
  /** Itens do menu; recebe `fechar` para encerrar o menu ao escolher. */
  children: (fechar: () => void) => ReactNode;
}) {
  const [ancora, setAncora] = useState<HTMLButtonElement | null>(null);
  const painel = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const alvo = painel.current;
    if (!ancora || !alvo) return;

    // Posiciona imperativamente (antes da pintura): mede a altura natural,
    // escolhe o lado e só então torna o painel visível.
    const MARGEM = 8;
    const larguraJanela = document.documentElement.clientWidth;
    const alturaJanela = document.documentElement.clientHeight;
    const botao = ancora.getBoundingClientRect();
    alvo.style.maxHeight = "";
    alvo.style.overflowY = "";
    const altura = alvo.offsetHeight;
    const espacoAbaixo = alturaJanela - botao.bottom - 4 - MARGEM;
    const espacoAcima = botao.top - 4 - MARGEM;

    alvo.style.right = `${Math.max(MARGEM, larguraJanela - botao.right)}px`;
    if (altura <= espacoAbaixo) {
      alvo.style.top = `${botao.bottom + 4}px`;
    } else if (altura <= espacoAcima) {
      alvo.style.bottom = `${alturaJanela - botao.top + 4}px`;
    } else if (espacoAbaixo >= espacoAcima) {
      alvo.style.top = `${botao.bottom + 4}px`;
      alvo.style.maxHeight = `${Math.max(120, espacoAbaixo)}px`;
      alvo.style.overflowY = "auto";
    } else {
      alvo.style.bottom = `${alturaJanela - botao.top + 4}px`;
      alvo.style.maxHeight = `${Math.max(120, espacoAcima)}px`;
      alvo.style.overflowY = "auto";
    }
    alvo.style.visibility = "visible";

    const itens = () =>
      [...alvo.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    itens()[0]?.focus(); // padrão de menu: foco entra no primeiro item

    const fechar = () => setAncora(null);
    const fecharDevolvendoFoco = () => {
      setAncora(null);
      ancora.focus();
    };
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") {
        fecharDevolvendoFoco();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(evento.key)) return;
      evento.preventDefault(); // a seta navega o menu — não rola a página
      const lista = itens();
      if (!lista.length) return;
      const atual = lista.indexOf(document.activeElement as HTMLButtonElement);
      const destino =
        evento.key === "Home" ? 0
        : evento.key === "End" ? lista.length - 1
        : evento.key === "ArrowDown" ? (atual + 1) % lista.length
        : (atual - 1 + lista.length) % lista.length;
      lista[destino].focus();
    };
    // Tab (ou clique que foca) para fora do menu: fecha.
    const aoMoverFoco = (evento: FocusEvent) => {
      const foco = evento.target;
      if (!(foco instanceof Node)) return;
      if (alvo.contains(foco) || ancora.contains(foco)) return;
      fechar();
    };
    // O painel fixo não acompanha o botão quando a página rola; rolagem
    // INTERNA do painel (modo compacto) não fecha. O listener entra com um
    // pequeno atraso para eventos residuais do gesto de abrir não fecharem
    // o menu na hora (ex.: barra de endereço do celular recolhendo).
    const aoRolar = (evento: Event) => {
      if (evento.target instanceof Node && alvo.contains(evento.target)) return;
      fechar();
    };
    const timer = window.setTimeout(() => {
      window.addEventListener("scroll", aoRolar, { capture: true, passive: true });
      window.addEventListener("resize", fechar);
    }, 100);
    document.addEventListener("keydown", aoTeclar);
    document.addEventListener("focusin", aoMoverFoco);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("scroll", aoRolar, { capture: true });
      window.removeEventListener("resize", fechar);
      document.removeEventListener("keydown", aoTeclar);
      document.removeEventListener("focusin", aoMoverFoco);
    };
  }, [ancora]);

  return (
    <>
      <button
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={Boolean(ancora)}
        className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        onClick={(evento) => setAncora(ancora ? null : evento.currentTarget)}
      >
        <MoreVertical size={16} />
      </button>
      {ancora && (
        <>
          {/* Só para dispensar com o mouse/toque — Esc é o caminho do teclado */}
          <button
            aria-hidden="true"
            tabIndex={-1}
            className="fixed inset-0 z-30 cursor-default"
            onClick={() => {
              setAncora(null);
              ancora.focus();
            }}
          />
          <div
            ref={painel}
            role="menu"
            style={{ visibility: "hidden" }}
            className={`fixed z-40 ${largura} rounded-lg border border-zinc-200 bg-white p-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900`}
          >
            {children(() => setAncora(null))}
          </div>
        </>
      )}
    </>
  );
}
