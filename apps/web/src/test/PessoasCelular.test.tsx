/**
 * Frente "pessoas" no celular (375–414 px; demo de 04/11) — dados fictícios.
 *
 * O jsdom não aplica CSS: o que se trava aqui é o que o celular PRECISA ter no DOM
 * (sem render duplo):
 * - a coluna que não pode sumir no celular (ações; na turma, também o Desempenho)
 *   leva `presa-celular` (fica presa à direita da tabela que rola abaixo de 640 px);
 * - a tabela que rola mostra o aviso em TEXTO acima dela ("Deslize a tabela…") e
 *   vira uma região com nome (o aviso só aparece quando há colunas escondidas — aqui
 *   simulado com scrollWidth > clientWidth);
 * - dado que antes sumia no celular (Professor, Último acesso, Nº de chamada, Autor)
 *   continua uma vez só no DOM, agora também abaixo de 640 px;
 * - botões tocados pela frente com 40 px no celular; avatar decorativo some no celular.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import Alunos from "../pages/Alunos";
import Escolas from "../pages/Escolas";
import Livros from "../pages/Livros";
import PerfilAluno from "../pages/PerfilAluno";
import SessoesAtivas from "../pages/SessoesAtivas";
import TurmaDetalhe from "../pages/TurmaDetalhe";
import Turmas from "../pages/Turmas";
import Usuarios from "../pages/Usuarios";
import { Professores } from "../pages/ListasSimples";
import {
  escolaFake,
  renderComApp,
  responder,
  screen,
  turmaFake,
  usuarioFake,
  within,
} from "./utils";
// O Vitest esvazia módulos .css (mesmo com ?raw): a folha é lida do disco.
const CSS_APP = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8");

const AVISO_ROLAGEM = "Deslize a tabela para o lado para ver todas as colunas.";

/** Simula a tabela mais larga que o cartão (celular): o TabelaRolavel mede
 *  scrollWidth × clientWidth. Restaura o jsdom no fim. */
async function comRolagemLateral(teste: () => Promise<void>) {
  const definir = (prop: "scrollWidth" | "clientWidth", valor: number) =>
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get: () => valor });
  definir("scrollWidth", 900);
  definir("clientWidth", 343);
  try {
    await teste();
  } finally {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
  }
}

// --- Detalhe da turma ---------------------------------------------------------

const RESUMO_TURMA = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 1, media_geral: 80, media_matific: 80, media_elefante: 80,
  indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
};

function semearTurma() {
  responder("GET", "/escolas/1/turmas/5/resumo", RESUMO_TURMA);
  responder("GET", "/escolas/1/turmas", [
    turmaFake({ id: 5, nome: "3º Ano A", professor_id: 3, professor_nome: "Mariana Ficticia" }),
  ]);
  responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [{
    id: 21, nome: "Bruno Ficticio Lima", foto_url: null, numero_chamada: 7, status: "ativo",
    turma: "3º Ano A", ano_escolar: "3º Ano", created_at: null, nota_geral: 79.94, posicao: 7,
  }]);
}

function montarTurma(usuario = usuarioFake({ cargo: "coordenador" })) {
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario },
  );
}

describe("Detalhe da turma no celular", () => {
  it("o botão 'Cartões do Quest' desce para a linha de baixo (largura total) em vez de espremer o texto", async () => {
    semearTurma();
    montarTurma();

    const titulo = await screen.findByRole("heading", { level: 1, name: "3º Ano A" });
    // A coluna do texto tem base mínima: com o botão ao lado não cabe, ele quebra a linha.
    expect(titulo.parentElement).toHaveClass("min-w-0", "flex-1", "basis-[12rem]");
    expect(await screen.findByText("Professor(a) Mariana Ficticia")).toBeInTheDocument();
    const botao = screen.getByRole("button", { name: /Cartões do Quest/ });
    // Largura total no celular; do sm em diante, a largura do próprio botão (como antes).
    expect(botao).toHaveClass("w-full", "sm:w-auto");
  });

  it("nota e menu ⋮ presos à direita; avatar some no celular; nome quebra em vez de correr por baixo", async () => {
    semearTurma();
    montarTurma();

    const menu = await screen.findByLabelText("Ações de Bruno Ficticio Lima");
    const linha = menu.closest("tr") as HTMLElement;
    expect(menu.closest("td")).toHaveClass("presa-celular", "max-sm:w-14");
    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular", "max-sm:w-14");

    // O Desempenho fica preso logo antes do menu (right-14 = a largura da coluna dele).
    const thDesempenho = screen.getByRole("columnheader", { name: "Desempenho" });
    expect(thDesempenho).toHaveClass("presa-celular", "max-sm:right-14");
    const nota = within(linha).getByText("79,94");
    expect(nota.closest("td")).toHaveClass("presa-celular", "max-sm:right-14");
    expect(within(linha).getByText("7º")).toBeInTheDocument();

    // Nº continua na própria coluna (vem com a rolagem), uma vez só.
    expect(within(linha).getAllByText("7")).toHaveLength(1);

    // Avatar decorativo some abaixo de 640 px; o nome (link do perfil) continua.
    expect(within(linha).getByText("BL").parentElement).toHaveClass("hidden", "sm:flex");
    const link = within(linha).getByRole("link", { name: "Bruno Ficticio Lima" });
    expect(link).toHaveClass("truncate", "max-sm:whitespace-normal");
    expect(link).toHaveAttribute("title", "Bruno Ficticio Lima");
  });

  it("sem o menu (Secretaria, só leitura), o Desempenho encosta na borda", async () => {
    semearTurma();
    renderComApp(
      <Routes>
        <Route path="/turmas/:id" element={<TurmaDetalhe />} />
      </Routes>,
      { rota: "/turmas/5", usuario: usuarioFake({ rede_id: 7 }), escolaSelecionada: 1 },
    );

    const nota = await screen.findByText("79,94");
    expect(nota.closest("td")).toHaveClass("presa-celular");
    expect(nota.closest("td")).not.toHaveClass("max-sm:right-14");
    expect(screen.queryByRole("columnheader", { name: "Ações" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cartões do Quest/ })).toBeNull();
  });

  it("tabela mais larga que o cartão: aviso em texto acima dela e região rolável com nome", async () => {
    await comRolagemLateral(async () => {
      semearTurma();
      montarTurma();
      expect(await screen.findByRole("region", { name: "Alunos da turma: tabela completa" })).toBeInTheDocument();
      expect(screen.getByText(AVISO_ROLAGEM)).toBeInTheDocument();
    });
  });
});

// --- Turmas -------------------------------------------------------------------

describe("Turmas no celular", () => {
  it("o professor titular aparece também abaixo de 640 px (uma vez só) e as ações ficam presas, com 40 px", async () => {
    responder("GET", "/escolas/1/turmas", [
      turmaFake({ id: 1, nome: "3º Ano A", professor_id: 4, professor_nome: "Prof. Marina" }),
    ]);
    responder("GET", "/escolas/1/professores", []);
    renderComApp(<Turmas />, { rota: "/turmas" });

    const link = await screen.findByRole("link", { name: "3º Ano A" });
    const linha = link.closest("tr") as HTMLElement;
    // Antes: `hidden md:table-cell` — sumia no celular sem rolagem que o mostrasse.
    // Agora aparece abaixo de 640 px (a tabela rola) e de 768 px em diante, como antes.
    const thProfessor = screen.getByRole("columnheader", { name: "Professor" });
    expect(thProfessor).toHaveClass("max-sm:table-cell", "md:table-cell");
    expect(within(linha).getAllByText("Prof. Marina")).toHaveLength(1);
    expect(within(linha).getByText("Prof. Marina").closest("td")).toHaveClass("max-sm:table-cell", "md:table-cell");

    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular");
    for (const nome of ["Editar turma 3º Ano A", "Arquivar turma 3º Ano A", "Excluir turma 3º Ano A"]) {
      const botao = screen.getByRole("button", { name: nome });
      expect(botao.closest("td")).toHaveClass("presa-celular");
      expect(botao).toHaveClass("max-sm:h-10", "max-sm:w-10");
    }
  });

  it("tabela mais larga que o cartão: aviso em texto acima dela", async () => {
    await comRolagemLateral(async () => {
      responder("GET", "/escolas/1/turmas", [turmaFake()]);
      responder("GET", "/escolas/1/professores", []);
      renderComApp(<Turmas />, { rota: "/turmas" });
      expect(await screen.findByRole("region", { name: "Turmas: tabela completa" })).toBeInTheDocument();
      expect(screen.getByText(AVISO_ROLAGEM)).toBeInTheDocument();
    });
  });
});

// --- Professores --------------------------------------------------------------

describe("Professores no celular", () => {
  it("e-mail quebra só no @ (nada de break-all letra a letra); ações presas com 40 px; avatar some", async () => {
    responder("GET", "/escolas/1/professores", [
      { id: 1, nome: "Carlos Eduardo Ficticio", email: "carlos.eduardo@escola.com", observacoes: null },
    ]);
    responder("GET", "/escolas/1/turmas", []);
    renderComApp(<Professores />);

    const nome = await screen.findByText("Carlos Eduardo Ficticio");
    const linha = nome.closest("tr") as HTMLElement;
    const celulaEmail = within(linha).getAllByRole("cell")[1];
    expect(celulaEmail).toHaveTextContent("carlos.eduardo@escola.com");
    // Ponto de quebra só antes do "@" (EmailQuebravel).
    expect(celulaEmail.querySelector("wbr")?.nextSibling?.textContent).toBe("@escola.com");
    expect(celulaEmail.querySelector(".break-all")).toBeNull();
    // Nome com base mínima no celular (não uma palavra por linha).
    expect(nome).toHaveClass("max-sm:min-w-[8rem]");
    expect(within(linha).getByText("CF")).toHaveClass("hidden", "sm:grid");

    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular");
    for (const rotulo of ["Editar nome e e-mail de Carlos Eduardo Ficticio", "Excluir Carlos Eduardo Ficticio"]) {
      const botao = screen.getByRole("button", { name: rotulo });
      expect(botao.closest("td")).toHaveClass("presa-celular");
      expect(botao).toHaveClass("max-sm:h-10", "max-sm:w-10");
    }
  });

  it("professor sem e-mail continua com o travessão", async () => {
    responder("GET", "/escolas/1/professores", [{ id: 2, nome: "Prof Ana", email: null, observacoes: null }]);
    responder("GET", "/escolas/1/turmas", []);
    renderComApp(<Professores />);

    const linha = (await screen.findByText("Prof Ana")).closest("tr") as HTMLElement;
    expect(within(linha).getAllByRole("cell")[1]).toHaveTextContent("—");
  });
});

// --- Usuários -----------------------------------------------------------------

describe("Usuários no celular", () => {
  it("o menu ⋮ (único caminho para gerir a conta) fica preso; Último acesso vem também abaixo de 640 px", async () => {
    responder("GET", "/escolas/1/usuarios", [
      usuarioFake({ id: 2, nome: "Maria Souza", email: "maria@escola.com", cargo: "professor", username: "maria.souza" }),
    ]);
    renderComApp(<Usuarios />, {
      rota: "/usuarios",
      usuario: usuarioFake({ id: 1, nome: "Admin Geral", email: "admin@escola.com", cargo: "admin" }),
    });

    const menu = await screen.findByRole("button", { name: "Ações do usuário Maria Souza" });
    expect(menu.closest("td")).toHaveClass("presa-celular");
    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular");

    // Antes: `hidden md:table-cell` — sumia abaixo de 768 px. De 640 a 767 px (menu
    // não preso) segue fora, como antes.
    expect(screen.getByRole("columnheader", { name: "Último acesso" }))
      .toHaveClass("hidden", "max-sm:table-cell", "md:table-cell");

    const linha = menu.closest("tr") as HTMLElement;
    // Avatar decorativo some no celular; a célula do nome tem base de 9rem.
    expect(within(linha).getByText("MS").parentElement).toHaveClass("hidden", "sm:flex");
    expect(within(linha).getByText("Maria Souza").closest("div.min-w-0")).toHaveClass("max-sm:min-w-[9rem]");
  });
});

// --- Sessões ativas -----------------------------------------------------------

const SESSOES = {
  agora: "2026-07-30T18:00:00+00:00",
  limiar_online_seg: 90,
  total: 1,
  online: 1,
  sessoes: [{
    id: 2, nome: "Professora Marta", email: "marta@escola.com",
    cargo: "professor", is_global: false, rede_id: null,
    escola_id: 1, escola_nome: "Escola Modelo", status: "ativo",
    online: true, visto_em: "2026-07-30T17:59:30+00:00",
    ultimo_acesso: "2026-07-30T15:00:00+00:00",
  }],
};

describe("Sessões ativas no celular", () => {
  it("avatar some no celular e a célula do usuário tem base para o e-mail não quebrar no @", async () => {
    responder("GET", "/presenca/sessoes", SESSOES);
    renderComApp(<SessoesAtivas />, { rota: "/sessoes" });

    const nome = await screen.findByText("Professora Marta");
    const linha = nome.closest("tr") as HTMLElement;
    expect(within(linha).getByText("PM")).toHaveClass("hidden", "sm:grid");
    expect(nome.parentElement).toHaveClass("max-sm:min-w-[9.5rem]");
    // As 4 colunas seguem (nada some).
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
  });

  it("tabela mais larga que o cartão: aviso em texto (não só a sombra) e região rolável", async () => {
    await comRolagemLateral(async () => {
      responder("GET", "/presenca/sessoes", SESSOES);
      renderComApp(<SessoesAtivas />, { rota: "/sessoes" });
      expect(await screen.findByRole("region", { name: "Sessões: tabela completa" })).toBeInTheDocument();
      expect(screen.getByText(AVISO_ROLAGEM)).toBeInTheDocument();
    });
  });
});

// --- Escolas ------------------------------------------------------------------

describe("Escolas no celular", () => {
  it("Usuários, Renomear e Desativar ficam presos à direita com 40 px; o ícone decorativo some", async () => {
    renderComApp(<Escolas />, {
      rota: "/escolas",
      usuario: usuarioFake({ is_global: true }),
      escolas: [escolaFake({ id: 1, nome: "Escola Alpha", status: "ativa" })],
    });

    const nome = await screen.findByText("Escola Alpha", { selector: "td span" });
    expect(nome).toHaveClass("max-sm:min-w-[8.5rem]");
    expect(nome.previousElementSibling).toHaveClass("hidden", "sm:grid");
    for (const rotulo of ["Usuários de Escola Alpha", "Renomear Escola Alpha", "Desativar Escola Alpha"]) {
      const botao = screen.getByRole("button", { name: rotulo });
      expect(botao.closest("td")).toHaveClass("presa-celular");
      expect(botao).toHaveClass("max-sm:h-10", "max-sm:w-10");
    }
    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular");
  });
});

// --- Alunos -------------------------------------------------------------------

describe("Alunos no celular", () => {
  it("Nº de chamada também abaixo de 640 px; ⋮ preso à direita; avatar some e o nome tem base", async () => {
    responder("GET", "/escolas/1/turmas", [turmaFake()]);
    responder("GET", "/escolas/1/alunos", {
      total: 1, pagina: 1, por_pagina: 25,
      itens: [{
        id: 10, nome: "Ana Beatriz Ficticia", foto_url: null, numero_chamada: 12,
        status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
      }],
    });
    renderComApp(<Alunos />, { rota: "/alunos" });

    const link = await screen.findByRole("link", { name: "Ana Beatriz Ficticia" });
    const linha = link.closest("tr") as HTMLElement;
    expect(link).toHaveClass("max-sm:min-w-[8.5rem]");
    expect(within(linha).getByText("AF").parentElement).toHaveClass("hidden", "sm:flex");

    // Antes: `hidden sm:table-cell` — o Nº não aparecia em lugar nenhum da lista no celular.
    const thNumero = screen.getByRole("columnheader", { name: "Nº chamada" });
    expect(thNumero).not.toHaveClass("hidden");
    expect(within(linha).getByText("12").closest("td")).not.toHaveClass("hidden");
    // A Série segue fora no celular: já está no chip da turma.
    expect(screen.getByRole("columnheader", { name: "Série" })).toHaveClass("hidden", "sm:table-cell");

    const menu = within(linha).getByRole("button", { name: "Ações de Ana Beatriz Ficticia" });
    expect(menu.closest("td")).toHaveClass("presa-celular");
    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular");
  });
});

// --- Livros -------------------------------------------------------------------

function livro(over = {}) {
  return {
    id: 7, titulo: "Laerte, o Gato Inerte", autor: "Ana Autora Ficticia", nivel_codigo: "D",
    categoria: null, paginas: null, pontos: 1.2, leituras: 3, elefante_id: 8, nivel_fonte: "B",
    nivel_oficial: "B", word_count: 78, origem_nivel: "admin_global", atualizado_em: null,
    no_catalogo: true, divergente: false, editavel: true, vale_para_proximas_leituras: false,
    historico_preservado: true, leituras_atualizadas: 0, leituras_sem_nivel_congelado: 0,
    ...over,
  };
}

describe("Livros no celular", () => {
  it("o autor aparece também abaixo de 640 px (a busca é por título ou autor)", async () => {
    responder("GET", "/escolas/1/livros", { total: 1, pagina: 1, por_pagina: 25, itens: [livro()] });
    renderComApp(<Livros />, { rota: "/livros" });

    const autor = await screen.findByText("Ana Autora Ficticia");
    expect(autor).toHaveClass("max-sm:min-w-[6rem]");
    // Para quem só consulta (sem coluna de ações), as Leituras ficam presas à direita.
    expect(screen.getByRole("columnheader", { name: "Leituras" })).toHaveClass("presa-celular");
    expect(screen.getByText("3").closest("td")).toHaveClass("presa-celular");
    // Antes: `hidden md:table-cell`. De 640 a 767 px segue fora, como antes.
    expect(autor.closest("td")).toHaveClass("hidden", "max-sm:table-cell", "md:table-cell");
    expect(screen.getByRole("columnheader", { name: "Autor" })).toHaveClass("max-sm:table-cell", "md:table-cell");
    expect(screen.getAllByText("Ana Autora Ficticia")).toHaveLength(1);
  });

  it("quem edita tem editar e excluir presos à direita, com 40 px", async () => {
    responder("GET", "/escolas/1/livros", { total: 1, pagina: 1, por_pagina: 25, itens: [livro()] });
    renderComApp(<Livros />, {
      rota: "/livros",
      usuario: usuarioFake({ id: 99, nome: "Admin Constela", is_global: true, cargo: "admin" }),
    });

    for (const rotulo of ["Editar Laerte, o Gato Inerte", "Excluir Laerte, o Gato Inerte"]) {
      const botao = await screen.findByRole("button", { name: rotulo });
      expect(botao.closest("td")).toHaveClass("presa-celular");
      expect(botao).toHaveClass("max-sm:h-10", "max-sm:w-10");
    }
    expect(screen.getByRole("columnheader", { name: "Ações" })).toHaveClass("presa-celular");
  });
});

// --- Perfil do aluno ----------------------------------------------------------

describe("Perfil do aluno no celular", () => {
  it("Leitura por nível: a barra ocupa a linha inteira abaixo do rótulo e do valor", async () => {
    responder("GET", "/escolas/1/alunos/10/perfil", {
      aluno: {
        id: 10, nome: "Ana Beatriz Ficticia", turma: "3º Ano A", ano_escolar: "3º Ano",
        status: "ativo", foto_url: null, numero_chamada: 4,
      },
      posicao: 2, nota_matific: 80, nota_elefante: 70, nota_geral: 75, ficha: {}, calculada_em: null,
      detalhes: {
        modo_normalizacao: "auto",
        matific: { indicadores: [], nota: 80 },
        elefante: { indicadores: [], questoes: null, nota: 70 },
        geral: { pesos: { matific: 50, elefante: 50 }, nota: 75 },
      },
      leitura_niveis: {
        faixas: [{ codigo: "pre", nome: "Pré-Leitor", quantidade: 2, pontos_por_livro: 1.5, pontos: 3, percentual: 100 }],
        total_livros: 2, pontos_dificuldade: 3, faixa_predominante: "Pré-Leitor",
      },
    });
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    renderComApp(
      <Routes>
        <Route path="/alunos/:id" element={<PerfilAluno />} />
      </Routes>,
      { rota: "/alunos/10", usuario: usuarioFake({ cargo: "coordenador" }) },
    );

    const rotulo = await screen.findByTitle("Pré-Leitor");
    const grade = rotulo.parentElement as HTMLElement;
    // Celular: 2 colunas (rótulo | valor) e a barra numa linha própria; do sm em diante,
    // a grade de antes (rótulo 6,5rem | barra | valor).
    expect(grade).toHaveClass("grid-cols-[1fr_auto]", "sm:grid-cols-[6.5rem_1fr_auto]");
    const [, barra, valor] = Array.from(grade.children);
    expect(barra).toHaveClass("max-sm:order-last", "max-sm:col-span-2");
    expect(valor).toHaveTextContent("100% · 3 pts");
    expect(valor).toHaveClass("w-28", "max-sm:w-auto");
  });
});

// --- Coluna presa com menu ou janela aberta ------------------------------------

describe("coluna presa no celular com menu ⋮ ou janela aberta", () => {
  it("a célula presa sobe acima do cabeçalho fixo (z-20) enquanto há menu/janela dentro dela", () => {
    // sticky + z-index cria contexto de empilhamento: sem esta regra, o menu (fixed z-40)
    // e o Modal (fixed z-50) ficavam presos no z-1 da célula, por baixo das células
    // presas das linhas seguintes. O jsdom não calcula :has() nem empilhamento: a trava
    // é na folha de estilos.
    const regra = /\.presa-celular:has\(\[aria-expanded="true"\]\),\s*\.presa-celular:has\(\[role="menu"\]\),\s*\.presa-celular:has\(\[role="dialog"\]\)\s*\{\s*z-index:\s*(\d+);/;
    const m = CSS_APP.match(regra);
    expect(m).not.toBeNull();
    expect(Number(m![1])).toBeGreaterThan(20);
  });
});

