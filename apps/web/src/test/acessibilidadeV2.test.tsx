/**
 * Acessibilidade dos componentes comuns na identidade v2 (frente a11y):
 *
 *  - Modal: com o foco na caixa (onde abre), Shift+Tab vai ao último item e Tab ao
 *    primeiro; o véu "Fechar janela" fecha no clique mas fica fora do Tab;
 *  - Drawer: diálogo modal de verdade — foco entra ao abrir, Tab preso, foco volta
 *    a quem abriu; Esc de uma Confirmação aberta DENTRO dele fecha só ela;
 *  - Interruptor desligado com trilho de 3:1 (WCAG 1.4.11);
 *  - selos ouro (contador de pendências, escolas em atenção) com texto ≥ 4,5:1.
 *
 * Escolas, pessoas e números INVENTADOS.
 */
import { useEffect, useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("leaflet", () => ({ default: { divIcon: () => ({}) } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: () => undefined, fitBounds: () => undefined }),
}));

import { Confirmacao, Drawer, Interruptor } from "../components/ui";
import RevisoesIdentidade from "../pages/RevisoesIdentidade";
import RedeDashboard from "../pages/rede/RedeDashboard";
import {
  escolaFake,
  render,
  renderComApp,
  responder,
  screen,
  turmaFake,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

/** Página com uma Confirmação entre dois botões de fora (para ver se o foco escapa). */
function PaginaComConfirmacao() {
  const [aberta, setAberta] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAberta(true)}>Abrir confirmação</button>
      <Confirmacao
        titulo="Arquivar a turma?"
        aberto={aberta}
        aoFechar={() => setAberta(false)}
        aoConfirmar={() => setAberta(false)}
        rotuloConfirmar="Arquivar"
      >
        A turma sai da lista do ano.
      </Confirmacao>
      <button type="button">Botão da página</button>
    </>
  );
}

describe("Modal — foco preso a partir da caixa", () => {
  it("com o foco na caixa, Shift+Tab vai ao último item (não ao véu nem à página)", async () => {
    const user = userEvent.setup();
    render(<PaginaComConfirmacao />);
    await user.click(screen.getByRole("button", { name: "Abrir confirmação" }));
    const dialogo = screen.getByRole("dialog", { name: "Arquivar a turma?" });
    expect(dialogo).toHaveFocus(); // abre com o foco na caixa (tabIndex -1)

    await user.tab({ shift: true });
    expect(within(dialogo).getByRole("button", { name: "Arquivar" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(dialogo).getByRole("button", { name: "Cancelar" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(dialogo).getByRole("button", { name: "Arquivar" })).toHaveFocus();
    await user.tab();
    expect(within(dialogo).getByRole("button", { name: "Cancelar" })).toHaveFocus();
  });

  it("com o foco na caixa, Tab vai ao primeiro item", async () => {
    const user = userEvent.setup();
    render(<PaginaComConfirmacao />);
    await user.click(screen.getByRole("button", { name: "Abrir confirmação" }));
    const dialogo = screen.getByRole("dialog", { name: "Arquivar a turma?" });
    expect(dialogo).toHaveFocus();
    await user.tab();
    expect(within(dialogo).getByRole("button", { name: "Cancelar" })).toHaveFocus();
  });

  it("o véu continua um botão 'Fechar janela' que fecha no clique, mas fora do Tab", async () => {
    const user = userEvent.setup();
    render(<PaginaComConfirmacao />);
    const abrir = screen.getByRole("button", { name: "Abrir confirmação" });
    await user.click(abrir);
    const veu = screen.getByRole("button", { name: "Fechar janela" });
    expect(veu).toHaveAttribute("tabindex", "-1");
    await user.click(veu);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });
});

/** Gaveta com uma Confirmação dentro (como "Gravar a Lista Piloto?" em Sincronização). */
function PaginaComGaveta() {
  const [gaveta, setGaveta] = useState(false);
  const [confirmacao, setConfirmacao] = useState(false);
  const [nota, setNota] = useState("");
  return (
    <>
      <button type="button" onClick={() => setGaveta(true)}>Abrir gaveta</button>
      <p>Rascunho: {nota}</p>
      {/* aoFechar é uma arrow nova a cada render (como nas telas reais). */}
      <Drawer titulo="Atualizar Lista Piloto" aberto={gaveta} aoFechar={() => setGaveta(false)}>
        <p>Prévia da planilha</p>
        <label>
          Observação
          <input value={nota} onChange={(e) => setNota(e.target.value)} />
        </label>
        <button type="button" onClick={() => setConfirmacao(true)}>Gravar matrículas</button>
        <Confirmacao
          titulo="Gravar a Lista Piloto?"
          aberto={confirmacao}
          aoFechar={() => setConfirmacao(false)}
          aoConfirmar={() => setConfirmacao(false)}
        >
          Nada é apagado.
        </Confirmacao>
      </Drawer>
      <button type="button">Botão da página</button>
    </>
  );
}

/** Gaveta cujo conteúdo pega o foco ao montar (como o detalhe de Revisões de identidade). */
function ConteudoQueFocaAoMontar() {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return <label>Busca<input ref={ref} /></label>;
}

function PaginaComGavetaQueFoca() {
  const [aberta, setAberta] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAberta(true)}>Ver revisão</button>
      <Drawer titulo="Revisão" aberto={aberta} aoFechar={() => setAberta(false)}>
        <ConteudoQueFocaAoMontar />
      </Drawer>
    </>
  );
}

describe("Drawer — diálogo modal para o teclado", () => {
  it("conteúdo que foca ao montar: ao fechar, o foco volta a quem abriu (não ao <body>)", async () => {
    const user = userEvent.setup();
    render(<PaginaComGavetaQueFoca />);
    const abrir = screen.getByRole("button", { name: "Ver revisão" });
    await user.click(abrir);
    expect(screen.getByRole("textbox", { name: "Busca" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });

  it("ao abrir, o foco vai ao 'Fechar'; o Tab fica preso; ao fechar, volta a quem abriu", async () => {
    const user = userEvent.setup();
    render(<PaginaComGaveta />);
    const abrir = screen.getByRole("button", { name: "Abrir gaveta" });
    await user.click(abrir);
    const gaveta = screen.getByRole("dialog", { name: "Atualizar Lista Piloto" });
    const fechar = within(gaveta).getByRole("button", { name: "Fechar" });
    expect(fechar).toHaveFocus();

    // Shift+Tab no 1º item volta ao último DA GAVETA (não ao véu nem à página).
    await user.tab({ shift: true });
    expect(within(gaveta).getByRole("button", { name: "Gravar matrículas" })).toHaveFocus();
    await user.tab();
    expect(fechar).toHaveFocus();
    // O véu fecha no clique, mas fica fora do Tab.
    expect(screen.getByRole("button", { name: "Fechar painel" })).toHaveAttribute("tabindex", "-1");

    await user.click(fechar);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });

  it("re-render da tela (aoFechar novo) não tira o foco de quem digita na gaveta", async () => {
    const user = userEvent.setup();
    render(<PaginaComGaveta />);
    await user.click(screen.getByRole("button", { name: "Abrir gaveta" }));
    const campo = screen.getByRole("textbox", { name: "Observação" });
    await user.click(campo);
    await user.keyboard("abc");
    expect(campo).toHaveValue("abc");
    expect(campo).toHaveFocus();
    expect(screen.getByText("Rascunho: abc")).toBeInTheDocument();
  });

  it("Esc na Confirmação aberta dentro da gaveta fecha só ela; o 2º Esc fecha a gaveta", async () => {
    const user = userEvent.setup();
    render(<PaginaComGaveta />);
    const abrir = screen.getByRole("button", { name: "Abrir gaveta" });
    await user.click(abrir);
    await user.click(screen.getByRole("button", { name: "Gravar matrículas" }));
    expect(screen.getByRole("dialog", { name: "Gravar a Lista Piloto?" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Gravar a Lista Piloto?" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Atualizar Lista Piloto" })).toBeInTheDocument();
    expect(screen.getByText("Prévia da planilha")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gravar matrículas" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });

  it("Tab dentro da Confirmação aninhada segue preso nela (a gaveta não interfere)", async () => {
    const user = userEvent.setup();
    render(<PaginaComGaveta />);
    await user.click(screen.getByRole("button", { name: "Abrir gaveta" }));
    await user.click(screen.getByRole("button", { name: "Gravar matrículas" }));
    const confirmacao = screen.getByRole("dialog", { name: "Gravar a Lista Piloto?" });
    await user.tab({ shift: true });
    expect(within(confirmacao).getByRole("button", { name: "Confirmar" })).toHaveFocus();
    await user.tab();
    expect(within(confirmacao).getByRole("button", { name: "Cancelar" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(confirmacao).getByRole("button", { name: "Confirmar" })).toHaveFocus();
  });
});

describe("Interruptor — trilho desligado visível (WCAG 1.4.11)", () => {
  it("desligado usa zinc-400 (3,22:1 no branco) e zinc-500 no escuro, não zinc-300/700", () => {
    render(<Interruptor ligado={false} aoMudar={() => undefined} rotulo="Mostrar arquivados" />);
    const chave = screen.getByRole("switch", { name: "Mostrar arquivados" });
    expect(chave).toHaveAttribute("aria-checked", "false");
    expect(chave).toHaveClass("bg-zinc-400", "dark:bg-zinc-500");
    expect(chave).not.toHaveClass("bg-zinc-300");
    expect(chave).not.toHaveClass("dark:bg-zinc-700");
  });

  it("ligado continua violeta", () => {
    render(<Interruptor ligado aoMudar={() => undefined} rotulo="Mostrar arquivados" />);
    expect(screen.getByRole("switch", { name: "Mostrar arquivados" })).toHaveClass("bg-indigo-600");
  });
});

// ── Selos ouro: ouro-700 sobre ouro-100 = 4,39:1; sobre ouro-50 = 4,72:1 ──────

const BASE_REVISOES = "/escolas/1/importacoes/revisoes";

function revisaoPendente() {
  return {
    id: 7,
    plataforma: "matific",
    formato: "resumo",
    id_externo: "00000000-0000-4000-8000-0000000000a7",
    nome_recebido: "ALUNO FICTICIO D",
    turma_informada: "5 ANO B",
    turma_id: 2,
    motivo: "candidatos_multiplos",
    motivo_texto: "mais de um aluno plausível na sala",
    candidatos: [{ aluno_id: 31, nome: "ALUNO FICTICIO DOIS", status: "ativo", turma: "5ºB" }],
    linhas: [],
    contexto: { tipo: "texto", data_referencia: "2026-09-20T12:00:00",
                periodo_inicio: "2026-09-01T00:00:00", periodo_fim: "2026-09-30T23:59:59" },
    origem: "sincronizacao",
    importacao_id: 90,
    ocorrencias: 1,
    status: "pendente",
    aluno_escolhido_id: null,
    resolvida_por_id: null,
    resolvida_em: null,
    resolucao: null,
    created_at: "2026-09-18T10:00:00",
    atualizada_em: "2026-09-20T12:00:00",
  };
}

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador", escola_id: null });

function cartaoEscola(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM Fundamental Testelli", cidade: "Cidade Ficticia", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2,
    total_alunos: 10, alunos_com_dados: 5, adocao: 50,
    media_geral: 60, media_matific: 60, media_elefante: 60,
    dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 5,
    alunos_com_nota_matific: 5, adocao_elefante: 50, adocao_matific: 50,
    livros: 25, tempo_leitura_min: 250, atividades: 25, estrelas: 50,
    ativos_matific: 5, ativos_elefante: 5, livros_por_aluno: 5,
    livros_por_matricula: 2.5, estrelas_por_matricula: 5,
    atividades_por_matricula: 2.5, tempo_por_matricula_min: 25,
    pontuacao_leitura: 1000, pontuacao_matematica: 1000, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura", "matematica"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null,
    comparada: true, posicao: 1,
    ...over,
  };
}

describe("Selos ouro — texto com 4,5:1", () => {
  it("Revisões de identidade: o contador de pendências usa bg-ouro-50", async () => {
    responder("GET", (c) => c.startsWith(BASE_REVISOES) && !/\/revisoes\/\d+/.test(c), (caminho: string) => {
      const situacao = new URL(`http://x${caminho}`).searchParams.get("situacao") ?? "pendente";
      return situacao === "pendente" || situacao === "todas" ? [revisaoPendente()] : [];
    });
    responder("GET", "/escolas/1/turmas", [turmaFake({ id: 2, nome: "5ºB", ano_escolar: "5º Ano" })]);
    renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });

    const selo = await screen.findByText("1 pendência");
    const pilula = selo.closest("span") as HTMLElement;
    expect(pilula).toHaveClass("bg-ouro-50", "text-ouro-700");
    expect(pilula).not.toHaveClass("bg-ouro-100");
  });

  it("Painel da Rede: o número de escolas com alerta de uso usa bg-ouro-50", async () => {
    const emAtencao = cartaoEscola({ precisa_atencao: true, motivo_atencao: "Adoção abaixo da meta" });
    responder("GET", "/redes/7/dashboard", {
      rede_id: 7,
      modulos: ["leitura", "matematica"],
      totais: {
        escolas: 1, escolas_ativas: 1, alunos: 10, turmas: 2, professores: 2,
        alunos_com_dados: 5, adocao: 50, media_geral: 60, media_matific: 60,
        media_elefante: 60, pontuacao_geral: 1000, escolas_em_atencao: 1,
        livros: 25, tempo_leitura_min: 250, atividades: 25, estrelas: 50,
        ativos_matific: 5, ativos_elefante: 5, livros_por_aluno: 5,
        melhor_escola: { nome: "EM Fundamental Testelli", pontuacao_geral: 1000, media_geral: 60 },
      },
      equidade: {
        gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000,
        escolas_abaixo_do_indice_medio: 0,
        gap_media: 0, escola_maior_media: 60, escola_menor_media: 60, escolas_abaixo_da_media: 0,
      },
      escolas: [emAtencao],
      atencao: [emAtencao],
    });
    responder("GET", "/redes/7/metas", []);
    responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria, escolas: [escolaFake()] });

    const titulo = await screen.findByRole("heading", { name: /Escolas com alerta de uso das plataformas/ });
    const selo = within(titulo).getByText("1");
    expect(selo).toHaveClass("bg-ouro-50", "text-ouro-700");
    expect(selo).not.toHaveClass("bg-ouro-100");
  });
});

/** Lista com "Remover" por item: a confirmação some e o item é retirado depois de
 *  `atraso` ms (a lista recarregando da API), como nas telas reais. */
function ListaQueRemove({ atraso }: { atraso: number }) {
  const [itens, setItens] = useState(["Meta de leitura", "Meta de matemática"]);
  const [alvo, setAlvo] = useState<string | null>(null);
  return (
    <main>
      <h1>Metas da rede</h1>
      <ul>
        {itens.map((item) => (
          <li key={item}>
            {item} <button onClick={() => setAlvo(item)}>Remover {item}</button>
          </li>
        ))}
      </ul>
      <Confirmacao
        titulo="Remover a meta?"
        aberto={alvo !== null}
        aoFechar={() => setAlvo(null)}
        aoConfirmar={() => {
          const removido = alvo;
          setAlvo(null);
          const tirar = () => setItens((atual) => atual.filter((i) => i !== removido));
          if (atraso === 0) tirar();
          else window.setTimeout(tirar, atraso);
        }}
        variante="perigo"
      >
        <p>Remove a meta.</p>
      </Confirmacao>
    </main>
  );
}

describe("Modal — o foco não se perde quando quem abriu some", () => {
  it("o item sai junto com a janela: o foco vai ao título da página (não ao <body>)", async () => {
    const usuario = userEvent.setup();
    render(<ListaQueRemove atraso={0} />);
    await usuario.click(screen.getByRole("button", { name: "Remover Meta de leitura" }));
    await usuario.click(within(screen.getByRole("dialog", { name: "Remover a meta?" })).getByRole("button", { name: "Confirmar" }));
    expect(screen.queryByRole("button", { name: "Remover Meta de leitura" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Metas da rede" }));
  });

  it("o item sai DEPOIS (lista recarregando): o foco volta ao botão e, quando ele some, vai ao título", async () => {
    const usuario = userEvent.setup();
    render(<ListaQueRemove atraso={300} />);
    const botao = screen.getByRole("button", { name: "Remover Meta de leitura" });
    await usuario.click(botao);
    await usuario.click(within(screen.getByRole("dialog", { name: "Remover a meta?" })).getByRole("button", { name: "Confirmar" }));
    expect(document.activeElement).toBe(botao);
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: "Remover Meta de leitura" })).toBeNull(), { timeout: 2000 });
    await vi.waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Metas da rede" })), { timeout: 2000 });
  });

  it("cancelar devolve o foco ao botão que abriu (que continua na tela)", async () => {
    const usuario = userEvent.setup();
    render(<ListaQueRemove atraso={0} />);
    const botao = screen.getByRole("button", { name: "Remover Meta de matemática" });
    await usuario.click(botao);
    await usuario.click(within(screen.getByRole("dialog", { name: "Remover a meta?" })).getByRole("button", { name: "Cancelar" }));
    expect(document.activeElement).toBe(botao);
  });
});
