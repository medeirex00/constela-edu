/**
 * Selo de FRESCOR dos rankings: a tela diz DE QUANDO é o dado e avisa quando
 * ele passou do limite que o BACKEND devolve (`limite_dias`). Sem dado é "sem
 * dados" (nunca zero nem data inventada); módulo não contratado não aparece;
 * falha ao buscar não derruba nada nem inventa estado; nunca "Funcionando".
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeloFrescor, SeloFrescorDaEscola, dataDoDia, type Frescor } from "../components/SeloFrescor";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import RankingGeral from "../pages/RankingGeral";
import {
  escolaFake, rankingItemFake, renderComApp, responder, responderErro, screen, turmaFake,
  userEvent, waitFor,
} from "./utils";

/** Troca a escola do contexto como o seletor do topo faz — a tela de ranking
 *  NÃO é remontada (não há `key={escolaId}` nas páginas). */
function TrocarEscola({ para }: { para: number }) {
  const { selecionarEscola } = useApp();
  return <button type="button" onClick={() => selecionarEscola(para)}>trocar escola</button>;
}

const DUAS_ESCOLAS = [escolaFake({ id: 1 }), escolaFake({ id: 2, nome: "ESCOLA DOIS TESTE" })];

function pediuFrescorDa(escolaId: number): boolean {
  return (api as unknown as { mock: { calls: unknown[][] } }).mock.calls
    .some((c) => c[0] === `/escolas/${escolaId}/ranking/frescor`);
}

function bloco(over: Record<string, unknown> = {}) {
  return {
    plataforma: "elefante", contratada: true, estado: "em_dia",
    dado_mais_recente_em: "2026-10-19", dado_mais_antigo_em: "2026-10-19",
    dias_desde_dado: 1, alunos_com_dado: 40, alunos_com_dado_antigo: 0,
    ultima_sincronizacao_ok_em: "2026-10-19T06:10:00", dias_desde_sincronizacao_ok: 1,
    ...over,
  };
}

function frescor(leitura: Record<string, unknown> = {}, matematica: Record<string, unknown> = {},
                 limite = 7): Frescor {
  return {
    limite_dias: limite, hoje: "2026-10-20", estado: "em_dia",
    dimensoes: {
      leitura: bloco(leitura),
      matematica: bloco({ plataforma: "matific", ...matematica }),
    },
  } as Frescor;
}

describe("SeloFrescor", () => {
  it("em dia: só o selo com a data e a idade, sem aviso", () => {
    render(<SeloFrescor frescor={frescor()} dimensoes={["leitura"]} />);
    expect(screen.getByText("Leitura (Elefante Letrado): dados de 19/10/2026 (há 1 dia)")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/Funcionando/i)).not.toBeInTheDocument();
  });

  it("em dia, do 3º ao 7º dia, o selo diz a idade — a Integração já avisa nesse intervalo", () => {
    render(<SeloFrescor
      frescor={frescor({ dado_mais_recente_em: "2026-10-16", dias_desde_dado: 4 })}
      dimensoes={["leitura"]} />);
    expect(screen.getByText("Leitura (Elefante Letrado): dados de 16/10/2026 (há 4 dias)")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("dado de hoje diz 'hoje'; idade ausente ou negativa não vira texto", () => {
    const { unmount } = render(<SeloFrescor
      frescor={frescor({ dado_mais_recente_em: "2026-10-20", dias_desde_dado: 0 })}
      dimensoes={["leitura"]} />);
    expect(screen.getByText("Leitura (Elefante Letrado): dados de 20/10/2026 (hoje)")).toBeInTheDocument();
    unmount();
    render(<SeloFrescor
      frescor={frescor({ dado_mais_recente_em: "2026-10-21", dias_desde_dado: -1 },
        { dias_desde_dado: null })}
      dimensoes={["leitura", "matematica"]} />);
    expect(screen.getByText("Leitura (Elefante Letrado): dados de 21/10/2026")).toBeInTheDocument();
    expect(screen.getByText("Matemática (Matific): dados de 19/10/2026")).toBeInTheDocument();
    expect(screen.queryByText(/há -1/)).not.toBeInTheDocument();
  });

  it("desatualizado: aviso com a idade e o limite vindo do backend", () => {
    render(<SeloFrescor
      frescor={frescor({ estado: "desatualizado", dado_mais_recente_em: "2026-10-01",
        dias_desde_dado: 19, ultima_sincronizacao_ok_em: null }, {}, 3)}
      dimensoes={["leitura"]} />);
    const aviso = screen.getByRole("status");
    // O limite é o da RESPOSTA (3), não um número da tela — e nomeia o aviso:
    // "Dados desatualizados" é a palavra da tela Integrações, com outra régua.
    expect(aviso).toHaveTextContent("Dado com mais de 3 dias: o mais recente é de 01/10/2026 (há 19 dias)");
    expect(aviso).not.toHaveTextContent(/Dados desatualizados/);
    expect(aviso).toHaveTextContent(/Nenhuma sincronização automática concluída/);
    expect(screen.queryByText(/Funcionando/i)).not.toBeInTheDocument();
  });

  it("parcial: diz quantos alunos estão com retrato antigo", () => {
    render(<SeloFrescor
      frescor={frescor({ estado: "parcial", alunos_com_dado: 40, alunos_com_dado_antigo: 6,
        dado_mais_antigo_em: "2026-09-02" })}
      dimensoes={["leitura"]} />);
    const aviso = screen.getByRole("status");
    // Não diz "Coleta parcial": sem integração, o estado vem do número digitado, sem coleta.
    expect(aviso).toHaveTextContent("Parte dos dados é antiga: 6 de 40 aluno(s)");
    expect(aviso).toHaveTextContent("02/09/2026");
  });

  it("sem dados: diz 'sem dados ainda', nunca zero nem data", () => {
    render(<SeloFrescor
      frescor={frescor({ estado: "sem_dados", dado_mais_recente_em: null, alunos_com_dado: 0,
        dias_desde_dado: null })}
      dimensoes={["leitura"]} />);
    expect(screen.getByText(/Leitura \(Elefante Letrado\): sem dados ainda/)).toBeInTheDocument();
    expect(screen.queryByText(/dados de/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\b0\b/)).not.toBeInTheDocument();
  });

  it("só mostra as dimensões pedidas e contratadas", () => {
    render(<SeloFrescor
      frescor={frescor({}, { contratada: false, estado: null })}
      dimensoes={["leitura", "matematica"]} />);
    expect(screen.getByText(/Leitura \(Elefante Letrado\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Matific/)).not.toBeInTheDocument();
  });

  it("sem frescor (falha ou carregando): não renderiza nada", () => {
    const { container } = render(<SeloFrescor frescor={null} dimensoes={["leitura"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("dataDoDia não passa por fuso: o dia do backend é o dia da tela", () => {
    expect(dataDoDia("2026-10-01")).toBe("01/10/2026");
    expect(dataDoDia("2026-01-01T00:30:00")).toBe("01/01/2026");
    expect(dataDoDia(null)).toBe("—");
  });

  it("SeloFrescorDaEscola busca /ranking/frescor da escola selecionada", async () => {
    responder("GET", "/escolas/1/ranking/frescor",
      frescor({}, { estado: "desatualizado", dado_mais_recente_em: "2026-10-01", dias_desde_dado: 19 }));
    renderComApp(<SeloFrescorDaEscola dimensoes={["matematica"]} />);
    expect(await screen.findByText("Matemática (Matific): dados de 01/10/2026 (há 19 dias)")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/há 19 dias/);
  });

  it("troca de escola: o selo da escola anterior não fica enquanto a nova carrega", async () => {
    responder("GET", "/escolas/1/ranking/frescor", frescor());
    responder("GET", "/escolas/2/ranking/frescor", () => new Promise(() => {}));   // não responde
    renderComApp(<><TrocarEscola para={2} /><SeloFrescorDaEscola dimensoes={["leitura"]} /></>,
      { escolas: DUAS_ESCOLAS });
    expect(await screen.findByText(/Leitura \(Elefante Letrado\): dados de 19\/10\/2026/))
      .toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "trocar escola" }));
    await waitFor(() => expect(pediuFrescorDa(2)).toBe(true));
    expect(screen.queryByText(/dados de/)).not.toBeInTheDocument();
  });

  it("troca de escola com falha na busca: nenhum selo, nem o da escola anterior", async () => {
    responder("GET", "/escolas/1/ranking/frescor", frescor());
    responderErro("GET", "/escolas/2/ranking/frescor", 500, "falhou");
    renderComApp(<><TrocarEscola para={2} /><SeloFrescorDaEscola dimensoes={["leitura"]} /></>,
      { escolas: DUAS_ESCOLAS });
    expect(await screen.findByText(/dados de 19\/10\/2026/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "trocar escola" }));
    await waitFor(() => expect(pediuFrescorDa(2)).toBe(true));
    await waitFor(() => expect(screen.queryByText(/dados de/)).not.toBeInTheDocument());
  });

  it("falha ao buscar o frescor não derruba o ranking e não inventa estado", async () => {
    responderErro("GET", "/escolas/1/ranking/frescor", 500, "falhou");
    responder("GET", "/escolas/1/turmas", [turmaFake()]);
    responder("GET", "/escolas/1/ranking", [rankingItemFake({ aluno_id: 10, nome: "Aluna Teste A" })]);
    renderComApp(<RankingGeral />);
    expect(await screen.findByRole("link", { name: /Aluna Teste A/ })).toBeInTheDocument();
    expect(screen.queryByText(/dados de/)).not.toBeInTheDocument();
    expect(screen.queryByText(/desatualizad/i)).not.toBeInTheDocument();
  });

  it("no Ranking Geral, dado velho aparece com aviso ao lado da lista", async () => {
    responder("GET", "/escolas/1/ranking/frescor",
      frescor({ estado: "desatualizado", dado_mais_recente_em: "2026-10-05", dias_desde_dado: 15 }));
    responder("GET", "/escolas/1/turmas", [turmaFake()]);
    responder("GET", "/escolas/1/ranking", [rankingItemFake({ aluno_id: 10, nome: "Aluna Teste A" })]);
    renderComApp(<RankingGeral />);
    expect(await screen.findByRole("link", { name: /Aluna Teste A/ })).toBeInTheDocument();
    expect(await screen.findByText("Leitura (Elefante Letrado): dados de 05/10/2026 (há 15 dias)")).toBeInTheDocument();
    expect(screen.getByText("Matemática (Matific): dados de 19/10/2026 (há 1 dia)")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/há 15 dias/);
  });
});
