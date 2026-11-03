/**
 * MÉDIO-2 do RC (WCAG 4.1.3): mensagens de erro/sucesso do web precisam ser
 * anunciadas por leitor de tela — antes eram só visuais.
 */
import { useState } from "react";

import { Activity } from "lucide-react";
import { vi } from "vitest";

import {
  Abas,
  Botao,
  Chip,
  Erro,
  Mensagem,
  StatCard,
  TAMANHOS_BOTAO,
  Vazio,
  classesTabela,
  mostrarAbaNaLista,
} from "../components/ui";
import { render, screen, userEvent } from "./utils";

test("Mensagem de erro é anunciada como alert (assertivo)", () => {
  render(<Mensagem tipo="erro">Não foi possível salvar.</Mensagem>);
  expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível salvar.");
});

test("Mensagem de sucesso é anunciada como status (educado)", () => {
  render(<Mensagem tipo="ok">Salvo com sucesso.</Mensagem>);
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent("Salvo com sucesso.");
  expect(status).toHaveAttribute("aria-live", "polite");
});

// Casca da identidade v2 (revisão visual): sem CSS no jsdom, as classes são a prova; o
// efeito visual é conferido na varredura (e2e-visual).
test("Chip não quebra linha (o chip de turma \"2º Ano A\" virava três linhas)", () => {
  render(<Chip>2º Ano A</Chip>);
  expect(screen.getByText("2º Ano A")).toHaveClass("whitespace-nowrap");
});

test("StatCard ancora o conteúdo no topo e mantém a ordem rótulo, valor, detalhe no DOM", () => {
  const { container } = render(
    <StatCard icone={<Activity size={20} />} rotulo="Alunos ativos" valor="15" detalhe="de 15 alunos" />,
  );
  const cartao = container.firstElementChild as HTMLElement;
  expect(cartao).toHaveClass("content-start");
  expect(cartao).toHaveTextContent(/^Alunos ativos15de 15 alunos$/);
});

test("a moldura das tabelas indica a rolagem horizontal (sombra nas bordas)", () => {
  expect(classesTabela.moldura.split(" ")).toEqual(expect.arrayContaining(["sombra-rolagem-x", "overflow-x-auto"]));
});

// ── Celular (revisão das capturas de 375–414 px) ─────────────────────────────

const ITENS_ABAS = [
  { valor: "perfil", rotulo: "Perfil" },
  { valor: "linha", rotulo: "Linha do tempo" },
  { valor: "historico", rotulo: "Histórico de Leituras" },
  { valor: "evolucao", rotulo: "Evolução" },
] as const;
type ValorAba = (typeof ITENS_ABAS)[number]["valor"];

function AbasDeTeste({ inicial = "perfil" }: { inicial?: ValorAba }) {
  const [valor, setValor] = useState<ValorAba>(inicial);
  return <Abas rotulo="Seções do perfil" itens={[...ITENS_ABAS]} valor={valor} aoMudar={setValor} />;
}

test("Abas no celular: uma linha que rola de lado (não quebra em duas); do sm em diante, as classes de antes", () => {
  render(<AbasDeTeste />);
  const lista = screen.getByRole("tablist", { name: "Seções do perfil" });
  // Celular: sem quebra, rolagem lateral, sombra na borda escondida (barra oculta em .abas-rolaveis).
  expect(lista).toHaveClass("abas-rolaveis", "max-sm:flex-nowrap", "max-sm:overflow-x-auto", "max-sm:sombra-rolagem-x");
  // Desktop igual: a pílula de sempre, que quebra linha se não couber.
  expect(lista).toHaveClass("inline-flex", "max-w-full", "flex-wrap", "gap-1", "rounded-2xl", "p-1", "shadow-cartao");
  expect(lista.className).not.toMatch(/(^|\s)(sm|md|lg):/);
  const abas = screen.getAllByRole("tab");
  expect(abas).toHaveLength(4);
  for (const aba of abas) {
    // Celular: a aba não encolhe nem quebra o rótulo e tem 40 px de alvo de toque.
    expect(aba).toHaveClass("max-sm:shrink-0", "max-sm:whitespace-nowrap", "max-sm:min-h-10");
    expect(aba).toHaveClass("px-3.5", "py-2", "text-sm");
  }
  expect(screen.getByRole("tab", { name: "Perfil" })).toHaveClass("bg-indigo-600", "shadow-pilula");
});

test("Abas: setas, Home/End e foco itinerante seguem funcionando", async () => {
  render(<AbasDeTeste />);
  const perfil = screen.getByRole("tab", { name: "Perfil" });
  expect(perfil).toHaveAttribute("tabindex", "0");
  perfil.focus();
  await userEvent.keyboard("{ArrowRight}");
  const linha = screen.getByRole("tab", { name: "Linha do tempo" });
  expect(linha).toHaveAttribute("aria-selected", "true");
  expect(linha).toHaveAttribute("tabindex", "0");
  expect(linha).toHaveFocus();
  expect(perfil).toHaveAttribute("tabindex", "-1");
  await userEvent.keyboard("{End}");
  expect(screen.getByRole("tab", { name: "Evolução" })).toHaveFocus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Perfil" })).toHaveFocus();
  expect(screen.getByRole("tab", { name: "Perfil" })).toHaveAttribute("aria-selected", "true");
});

/** Layout falso de um celular: a lista mostra 298 px e as 4 abas (116 px + 4 de vão)
 *  somam 486 px. A posição de cada aba acompanha o scrollLeft da lista. */
function simularListaEstreita() {
  const caixa = (left: number, right: number) =>
    ({ left, right, top: 0, bottom: 50, width: right - left, height: 50, x: left, y: 0, toJSON: () => ({}) }) as DOMRect;
  const ehLista = (el: Element) => el.getAttribute("role") === "tablist";
  const espioes = [
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockImplementation(function (this: Element) {
      return ehLista(this) ? 486 : 0;
    }),
    vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(function (this: Element) {
      return ehLista(this) ? 298 : 0;
    }),
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (ehLista(this)) return caixa(0, 300);
      const lista = this.parentElement;
      if (this.getAttribute("role") === "tab" && lista) {
        const esquerda = 5 + Array.from(lista.children).indexOf(this) * 120 - lista.scrollLeft;
        return caixa(esquerda, esquerda + 116);
      }
      return caixa(0, 0);
    }),
  ];
  return () => espioes.forEach((e) => e.mockRestore());
}

test("Abas no celular: a lista rola sozinha até a aba ativa (ao abrir e a cada troca), sem mexer na página", async () => {
  const restaurar = simularListaEstreita();
  const rolarPagina = vi.spyOn(window, "scrollTo");
  const rolarAteElemento = vi.spyOn(Element.prototype, "scrollIntoView");
  try {
    render(<AbasDeTeste inicial="historico" />);
    const lista = screen.getByRole("tablist", { name: "Seções do perfil" });
    // Ao abrir com a 3ª aba ativa (245–361 px, além da borda de 300): rola até ela inteira
    // aparecer, com folga de 24 px para a vizinha.
    expect(lista.scrollLeft).toBe(85);

    await userEvent.click(screen.getByRole("tab", { name: "Evolução" }));
    expect(lista.scrollLeft).toBe(188); // o fim da lista (486 − 298)

    await userEvent.click(screen.getByRole("tab", { name: "Perfil" }));
    expect(lista.scrollLeft).toBe(0);

    screen.getByRole("tab", { name: "Perfil" }).focus();
    await userEvent.keyboard("{End}");
    expect(lista.scrollLeft).toBe(188);

    expect(rolarPagina).not.toHaveBeenCalled();
    expect(rolarAteElemento).not.toHaveBeenCalled();
  } finally {
    restaurar();
    rolarPagina.mockRestore();
    rolarAteElemento.mockRestore();
  }
});

test("mostrarAbaNaLista: sem rolagem lateral (desktop, ou tudo coube) não mexe em nada", () => {
  const lista = { scrollWidth: 300, clientWidth: 300, scrollLeft: 0, getBoundingClientRect: () => ({ left: 0, right: 300 }) };
  const aba = { getBoundingClientRect: () => ({ left: 400, right: 500 }) };
  mostrarAbaNaLista(lista as unknown as HTMLElement, aba as unknown as HTMLElement);
  expect(lista.scrollLeft).toBe(0);
  // Aba já inteira à vista: também não rola.
  const larga = { scrollWidth: 600, clientWidth: 300, scrollLeft: 40, getBoundingClientRect: () => ({ left: 0, right: 300 }) };
  mostrarAbaNaLista(larga as unknown as HTMLElement, { getBoundingClientRect: () => ({ left: 100, right: 200 }) } as unknown as HTMLElement);
  expect(larga.scrollLeft).toBe(40);
});

test("Botao sm tem 40 px de altura mínima só no celular; no desktop, o mesmo tamanho de antes", () => {
  render(<Botao tamanho="sm">Próxima</Botao>);
  const botao = screen.getByRole("button", { name: "Próxima" });
  expect(botao).toHaveClass("max-sm:min-h-10", "px-3", "py-1.5", "text-xs", "rounded-lg");
  expect(TAMANHOS_BOTAO.sm.split(" ")).toContain("max-sm:min-h-10");
  expect(TAMANHOS_BOTAO.sm.split(" ").filter((c) => /^(sm|md|lg|xl):/.test(c))).toEqual([]);
});

test("Vazio e Erro têm folga lateral: o texto não encosta nas bordas do cartão no celular", () => {
  render(
    <>
      <Vazio titulo="Escolha os dois lados e clique em Comparar" descricao="As notas aparecem lado a lado." />
      <Erro descricao="Falhou." />
    </>,
  );
  const vazio = screen.getByText("Escolha os dois lados e clique em Comparar").parentElement as HTMLElement;
  expect(vazio).toHaveClass("px-5", "py-14", "text-center");
  expect(screen.getByRole("alert")).toHaveClass("px-5", "py-12", "text-center");
});
