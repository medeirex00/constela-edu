/**
 * Visão da Escola — tabela "Desempenho por turma" (revisão visual v2): em 1024 e 820 px
 * as colunas Livros, Tempo e o link "detalhes" ficavam fora do cartão, sem sinal de
 * rolagem, e "5 de 5 alunos" quebrava em três linhas. Agora o denominador fica numa
 * linha, as nove colunas seguem com o mesmo nome e, no tablet em pé, a coluna
 * "detalhes" fica presa à borda direita (sempre visível) com uma sombra que avisa que
 * há mais colunas.
 *
 * Celular (revisão das capturas, 31/10): só apareciam Turma, Alunos, Média e "detalhes"
 * (presa), e Leitura e Matific rolavam escondidas por baixo dela. Abaixo de 640 px a
 * TURMA fica presa à esquerda, o "detalhes" rola junto e um aviso em texto diz que a
 * tabela desliza; os cartões de indicador ficam 2 por linha.
 */
import { Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import VisaoEscola from "../pages/VisaoEscola";
import { renderComApp, responder, screen, userEvent, usuarioFake, waitFor, within } from "./utils";

const RESUMO = {
  escola: { id: 1, nome: "Escola Modelo Constela" },
  turmas: [{
    turma: { id: 21, nome: "5º Ano A", ano_escolar: "5º Ano" },
    total_alunos: 5,
    media_geral: 69.78,
    media_matific: 75.49,
    media_elefante: 64.06,
    indicadores: { livros_unicos: 21, tempo_leitura_min: 547 },
    n_leitura: 5,
    n_matematica: 4,
    contratadas: ["leitura", "matematica"],
    alcance: 100,
  }],
};

describe("Visão da Escola — Desempenho por turma", () => {
  it("todas as colunas seguem, o denominador fica numa linha e o 'detalhes' fica preso à direita no tablet", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola" });

    const link = await screen.findByRole("link", { name: "5º Ano A" });
    const linha = link.closest("tr") as HTMLElement;

    for (const nome of ["Turma", "Alunos", "Média geral", "Leitura", "Matific", "Alcance", "Livros", "Tempo", "Detalhes"]) {
      expect(screen.getByRole("columnheader", { name: nome })).toBeInTheDocument();
    }
    // "n de N alunos" numa linha só (antes: três linhas). No tablet em pé a palavra
    // "alunos" fica só para o leitor de tela; o texto completo continua no elemento.
    for (const n of ["5 de 5", "4 de 5"]) {
      const denominador = within(linha).getByText(n);
      expect(denominador).toHaveTextContent(`${n} alunos`);
      expect(denominador).toHaveClass("whitespace-nowrap");
      expect(within(denominador).getByText("alunos")).toHaveClass("sr-only", "lg:not-sr-only");
    }

    // O link "detalhes" continua em toda linha; no tablet (sm até lg) a célula dele fica
    // presa à direita (sticky) e volta ao normal a partir de lg. No celular (< sm) ela
    // rola junto com as outras: quem fica presa ali é a turma (abaixo).
    const detalhes = within(linha).getByRole("link", { name: "detalhes" });
    expect(detalhes).toHaveAttribute("href", "/turmas/21");
    const celula = detalhes.closest("td") as HTMLElement;
    expect(celula).toHaveClass("sm:sticky", "sm:right-0", "lg:static");
    expect(celula).not.toHaveClass("sticky");
    const cabecalhoDetalhes = screen.getByRole("columnheader", { name: "Detalhes" });
    expect(cabecalhoDetalhes).toHaveClass("sm:sticky", "sm:right-0", "lg:static");
    expect(cabecalhoDetalhes).not.toHaveClass("sticky");
  });

  it("celular: a turma fica presa à esquerda e Leitura e Matific seguem na mesma linha dela", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola" });

    const link = await screen.findByRole("link", { name: "5º Ano A" });
    const linha = link.closest("tr") as HTMLElement;
    // A célula da turma (e o cabeçalho dela) presa à esquerda só abaixo de sm.
    const celulaTurma = link.closest("td") as HTMLElement;
    expect(celulaTurma).toHaveClass("presa-esquerda-celular");
    expect(celulaTurma).not.toHaveClass("sticky");
    expect(screen.getByRole("columnheader", { name: "Turma" })).toHaveClass("presa-esquerda-celular");
    // Leitura e Matific continuam colunas da MESMA linha (uma vez só no DOM), com o "n de N".
    const cabecalhos = within(linha.closest("table") as HTMLElement).getAllByRole("columnheader")
      .map((th) => th.textContent?.trim());
    expect(cabecalhos.slice(0, 5)).toEqual(["Turma", "Alunos", "Média geral", "Leitura", "Matific"]);
    expect(within(linha).getByText("64,06")).toBeInTheDocument();
    expect(within(linha).getByText("75,49")).toBeInTheDocument();
    expect(screen.getAllByText("5º Ano A")).toHaveLength(1);
  });

  it("celular: os 4 indicadores ficam 2 por linha (do sm para cima, o de antes)", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola" });

    const grade = await screen.findByTestId("indicadores-da-escola");
    expect(grade).toHaveClass("grid-cols-2", "gap-3", "sm:gap-5", "lg:grid-cols-4");
    expect(grade).not.toHaveClass("grid-cols-1");
    expect(within(grade).getByText("Turmas")).toBeInTheDocument();
    expect(within(grade).getByText("Atividades Matific")).toBeInTheDocument();
  });
});

describe("Visão da Escola — tabela que não cabe (celular)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("avisa em texto, acima da tabela, que ela desliza de lado, e nomeia a região que rola", async () => {
    // A moldura mede 300 px e a tabela pede 900: há colunas escondidas à direita.
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(300);
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockReturnValue(900);
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola" });

    const regiao = await screen.findByRole("region", { name: "Desempenho por turma: tabela completa" });
    expect(within(regiao).getByRole("columnheader", { name: "Leitura" })).toBeInTheDocument();
    expect(within(regiao).getByRole("columnheader", { name: "Matific" })).toBeInTheDocument();
    expect(regiao).toHaveAttribute("tabindex", "0");
    const aviso = screen.getByText(/Deslize a tabela para o lado para ver todas as colunas/);
    // O aviso vem ANTES da tabela (visível sem rolar a lista inteira).
    expect(aviso.compareDocumentPosition(regiao) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("Visão da Escola — Secretaria com turma protegida (grupo pequeno)", () => {
  const TEXTO = "Menos de 3 alunos com dado nesta matéria: para proteger as crianças, a média e os totais da turma não aparecem.";
  const PROTEGIDA = {
    turma: { id: 22, nome: "4º Ano A", ano_escolar: "4º Ano" },
    total_alunos: 20,
    media_geral: null,
    media_matific: 70.5,
    media_elefante: null,
    indicadores: { livros_unicos: null, tempo_leitura_min: null, atividades: 30 },
    n_leitura: 1,
    n_matematica: 12,
    contratadas: ["leitura", "matematica"],
    alcance: 60,
    grupo_pequeno: true,
    oculto: { leitura: { motivo: "grupo_pequeno", texto: TEXTO }, matematica: null },
  };

  it("mostra '—' e 'protegido' (nunca 0) na matéria escondida, e o total declara a soma parcial", async () => {
    responder("GET", "/escolas/1/resumo-escola", { ...RESUMO, turmas: [...RESUMO.turmas, PROTEGIDA] });
    renderComApp(<VisaoEscola />, {
      rota: "/escola",
      usuario: usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null }),
      escolaSelecionada: 1,
    });

    // A tela não quebra com média null (antes: nota(null) → TypeError → "Algo deu errado").
    // A escola selecionada entra depois do 1º render e a lista é buscada de novo: espera a
    // tabela final antes de olhar a linha — e olha a linha INTEIRA de uma vez (a tabela pode ser
    // trocada entre uma consulta e outra enquanto a 2ª busca chega).
    await screen.findByText("4º Ano A");
    await waitFor(() => {
      const linha = screen.getByText("4º Ano A").closest("tr") as HTMLElement;
      expect(within(linha).getAllByText("protegido").length).toBeGreaterThanOrEqual(3); // Leitura, Livros, Tempo
      expect(within(linha).getAllByText(TEXTO).length).toBeGreaterThanOrEqual(1); // motivo para o leitor de tela
      expect(within(linha).queryByText("0")).toBeNull();
      expect(within(linha).queryByText("0 min")).toBeNull();
      // A matéria que NÃO está escondida continua com o número.
      expect(within(linha).getByText("70,5")).toBeInTheDocument();
    });
    // Total de leitura da escola: soma só a turma visível e diz que há turma protegida fora.
    const indicadores = await screen.findByTestId("indicadores-da-escola");
    expect(within(indicadores).getByText(/sem 1 turma\(s\) protegida\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/“Protegido”: a turma tem menos de 3 alunos com dado/)).toBeInTheDocument();
  });

  it("se nenhuma turma visível tem número na matéria, o total da escola é '—' (não 0)", async () => {
    responder("GET", "/escolas/1/resumo-escola", { ...RESUMO, turmas: [PROTEGIDA] });
    renderComApp(<VisaoEscola />, {
      rota: "/escola",
      usuario: usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null }),
      escolaSelecionada: 1,
    });

    await screen.findByText("4º Ano A");
    await waitFor(() => expect(screen.getAllByText("protegido").length).toBeGreaterThan(0));
    // Espera os cartões do topo de novo: com a suíte inteira em paralelo, a tela ainda
    // re-renderizava (o contexto da escola e a análise da escola chegando) entre uma
    // consulta e outra, e o getBy pegava o meio do caminho.
    await waitFor(() => {
      const indicadores = screen.getByTestId("indicadores-da-escola");
      const tempo = within(indicadores).getByText("Tempo de leitura").closest(".card") as HTMLElement;
      expect(within(tempo).getByText("—")).toBeInTheDocument();
    });
  });
});

// O "Voltar" de quem é de rede leva à tela de onde a escola foi aberta, com o nome dela; sem
// origem, à página de rede do PERFIL, com o nome dela: a Secretaria, ao Panorama da Rede (a
// página inicial dela — o Painel da Rede saiu do menu dela, DESENHO3 §5); o Admin Global, ao
// Painel da Rede ("Voltar para a visão da rede" levava ao Painel e se confundia com a tela
// "Visão da rede", /rede/visao, dele).
describe("Visão da Escola — o Voltar de quem é de rede", () => {
  const SECRETARIA = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
  const GLOBAL = usuarioFake({ nome: "Raiz", cargo: "admin", is_global: true, escola_id: null });

  /** Uma tela da rede que abre a Visão da Escola como as telas da rede fazem: navega para
   *  /escola com a origem no estado da navegação. */
  function Origem({ estado }: { estado?: unknown }) {
    const navegar = useNavigate();
    return (
      <>
        <p>TELA:acompanhamento</p>
        <button type="button" onClick={() => navegar("/escola", { state: estado })}>Ver a escola</button>
      </>
    );
  }

  async function abrirDaOrigem(estado?: unknown) {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(
      <Routes>
        <Route path="/rede/acompanhamento" element={<Origem estado={estado} />} />
        <Route path="/" element={<p>TELA:panorama-da-rede</p>} />
        <Route path="/rede" element={<p>TELA:painel-da-rede</p>} />
        <Route path="/escola" element={<VisaoEscola />} />
      </Routes>,
      { rota: "/rede/acompanhamento", usuario: SECRETARIA, escolaSelecionada: 1 },
    );
    await userEvent.click(await screen.findByRole("button", { name: "Ver a escola" }));
  }

  it("aberta de outra tela (ex.: Escolas em acompanhamento): o Voltar diz o nome dessa tela e leva de volta a ela", async () => {
    await abrirDaOrigem({ voltar: { caminho: "/rede/acompanhamento", texto: "Voltar para Escolas em acompanhamento" } });

    const voltar = await screen.findByRole("link", { name: "Voltar para Escolas em acompanhamento" });
    expect(voltar).toHaveAttribute("href", "/rede/acompanhamento");
    expect(screen.queryByText(/visão da rede|Painel da Rede|Panorama da Rede/i)).toBeNull();
    await userEvent.click(voltar);
    expect(await screen.findByText("TELA:acompanhamento")).toBeInTheDocument();
  });

  it("Secretaria, entrada direta (sem origem): volta ao Panorama da Rede, a página inicial dela", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola", usuario: SECRETARIA, escolaSelecionada: 1 });

    const voltar = await screen.findByRole("link", { name: "Voltar ao Panorama da Rede" });
    expect(voltar).toHaveAttribute("href", "/");
    // O Painel da Rede saiu do menu dela: o Voltar não leva mais para lá.
    expect(screen.queryByText(/visão da rede|Painel da Rede/i)).toBeNull();
  });

  it("Admin Global, entrada direta (sem origem): volta ao Painel da Rede, com esse nome — nunca 'visão da rede'", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola", usuario: GLOBAL, escolaSelecionada: 1 });

    const voltar = await screen.findByRole("link", { name: "Voltar ao Painel da Rede" });
    expect(voltar).toHaveAttribute("href", "/rede");
    expect(screen.queryByText(/visão da rede|Panorama da Rede/i)).toBeNull();
  });

  it.each([
    ["caminho de outro site", { voltar: { caminho: "//outro-site.example/x", texto: "Voltar" } }],
    ["sem texto", { voltar: { caminho: "/rede/escolas", texto: "  " } }],
    ["estado de outra forma", { de: "acompanhamento" }],
  ])("origem inválida (%s): ignorada — a Secretaria volta ao Panorama da Rede", async (_caso, estado) => {
    await abrirDaOrigem(estado);

    const voltar = await screen.findByRole("link", { name: "Voltar ao Panorama da Rede" });
    expect(voltar).toHaveAttribute("href", "/");
    await userEvent.click(voltar);
    expect(await screen.findByText("TELA:panorama-da-rede")).toBeInTheDocument();
  });

  it("coordenação da escola (sem rede): não há Voltar", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    renderComApp(<VisaoEscola />, { rota: "/escola" });

    await screen.findByRole("link", { name: "5º Ano A" });
    expect(screen.queryByRole("link", { name: /^Voltar/ })).toBeNull();
  });
});

// A Secretaria começa toda sessão em "Toda a Rede Municipal" (escola nula no contexto): "Ver as
// turmas da escola" aberto numa aba nova, ou a recarga em /escola, chega aqui sem escola. Antes, os
// blocos cinzas de carregamento ficavam na tela para sempre; agora, o caminho por extenso.
describe("Visão da Escola — sem escola no contexto", () => {
  const SECRETARIA = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });

  it("Secretaria: 'Escolha uma escola', com o link para Escolas — nada de carregamento sem fim", async () => {
    responder("GET", "/escolas/1/resumo-escola", RESUMO);
    const { container } = renderComApp(<VisaoEscola />, { rota: "/escola", usuario: SECRETARIA });

    expect(await screen.findByText("Escolha uma escola")).toBeInTheDocument();
    expect(screen.getByText(/Em Escolas, abra a ficha da escola e use “Ver as turmas da escola”/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ir para Escolas" })).toHaveAttribute("href", "/rede/escolas");
    expect(screen.queryByText("Carregando...")).toBeNull();
    expect(container.querySelector(".animate-pulse")).toBeNull();
    // O Voltar continua (ao Panorama da Rede) e nenhuma turma de escola alguma aparece.
    expect(screen.getByRole("link", { name: "Voltar ao Panorama da Rede" })).toHaveAttribute("href", "/");
    expect(screen.queryByText("5º Ano A")).toBeNull();
  });
});
