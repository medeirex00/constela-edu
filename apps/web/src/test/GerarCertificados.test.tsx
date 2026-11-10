/**
 * GerarCertificados — o modal de certificados EM LOTE (Ranking, Visão Geral, Premiações).
 *
 * Trava o contrato com o backend e as regras que a tela não pode contornar:
 *   - Top N = os N PRIMEIROS da lista dada, na ordem dada (linha sem ficha fica de fora,
 *     com aviso, e ninguém entra no lugar);
 *   - chips de modelo só para os módulos contratados (Geral sempre);
 *   - a prévia recebe exatamente os ids do lote; recusado aparece com o motivo do
 *     backend e NÃO é substituído pelo próximo colocado;
 *   - "Gerar PDF" chama apiDownloadPost com o caminho e o corpo do contrato;
 *   - erros do backend aparecem com a mensagem dele.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import GerarCertificados from "../components/GerarCertificados";
import { useApp } from "../context/AppContext";
import type { GerarCertificadosProps } from "../components/GerarCertificados";
import { bimestreDeHoje } from "../lib/calendarioBimestres";
import { bimestreDoPeriodo } from "../lib/tiposCertificados";
import type { AlunoParaCertificado, ItemPreviaCertificado } from "../lib/tiposCertificados";
import {
  ApiError,
  api,
  apiDownloadPost,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

const PREVIA = "/escolas/1/certificados/lote/previa";
const LOTE = "/escolas/1/certificados/lote";

const LISTA: AlunoParaCertificado[] = [
  { aluno_id: 101, nome: "Ana Beatriz Souza", turma: "3º Ano A", posicao: 1 },
  { aluno_id: 102, nome: "Bruno Lima", turma: "4º Ano B", posicao: 2 },
  { aluno_id: 103, nome: "Carla Mendes", turma: "5º Ano A", posicao: 3 },
  { aluno_id: 104, nome: "Davi Rocha", turma: "3º Ano A", posicao: 4 },
  { aluno_id: 105, nome: "Elisa Prado", turma: "4º Ano A", posicao: 5 },
  { aluno_id: 106, nome: "Fábio Nunes", turma: "5º Ano B", posicao: 6 },
  { aluno_id: 107, nome: "Gabriela Torres", turma: "2º Ano A", posicao: 7 },
];

const MOTIVO_LISTA_PILOTO =
  "“Carla Mendes” ainda não está confirmado na Lista Piloto desta escola, então não dá para emitir um documento oficial no nome dele.";

/** Sinaliza que a sessão (/auth/me e /escolas) terminou de abrir: os módulos do
 *  usuário já valem e nenhum estado do AppProvider muda depois da asserção. */
function SessaoPronta() {
  const { carregando } = useApp();
  return carregando ? null : <span data-testid="sessao-pronta" hidden />;
}

async function renderizar(over: Partial<GerarCertificadosProps> = {}, modulos = ["leitura", "matematica"]) {
  const aoFechar = vi.fn();
  renderComApp(
    <>
      <GerarCertificados
        escolaId={1}
        alunos={LISTA}
        modeloInicial="matific"
        contexto="Ranking · Matemática · 4º bimestre"
        aberto
        aoFechar={aoFechar}
        {...over}
      />
      <SessaoPronta />
    </>,
    { usuario: usuarioFake({ modulos }) },
  );
  await screen.findByTestId("sessao-pronta");
  return { aoFechar, u: userEvent.setup() };
}

/** Nomes das linhas do lote, na ordem do DOM. */
function nomesDoLote(): string[] {
  const itens = within(screen.getByRole("list", { name: "Alunos do lote" })).getAllByRole("listitem");
  return itens.map((li) => {
    const nome = [...LISTA.map((a) => a.nome as string), "Linha sem ficha"].find((n) => li.textContent?.includes(n));
    return nome ?? "?";
  });
}

function linhaDe(nome: string): HTMLElement {
  return screen.getByText(nome).closest("li") as HTMLElement;
}

/** Prévia: 103 recusado (Lista Piloto), os demais aptos — sempre na ordem pedida. */
function responderPreviaComRecusa() {
  responder("POST", PREVIA, (_caminho: string, opcoes: RequestInit | FormData) => {
    const corpo = JSON.parse(String((opcoes as RequestInit).body));
    return {
      modelo: corpo.modelo,
      itens: (corpo.aluno_ids as number[]).map((id): ItemPreviaCertificado => {
        const aluno = LISTA.find((a) => a.aluno_id === id);
        return {
          aluno_id: id,
          nome: aluno?.nome ?? null,
          turma: aluno?.turma ?? null,
          apto: id !== 103,
          motivo: id === 103 ? MOTIVO_LISTA_PILOTO : null,
        };
      }),
    };
  });
}

function corpoDaPrevia(): unknown {
  const chamada = api.mock.calls.find(([caminho]) => caminho === PREVIA);
  expect(chamada).toBeDefined();
  expect(chamada?.[1]).toEqual(expect.objectContaining({ method: "POST" }));
  return JSON.parse(String((chamada?.[1] as RequestInit).body));
}

describe("GerarCertificados — quem entra no lote", () => {
  it("abre com o contexto e o Top 3: os 3 primeiros, na ordem dada", async () => {
    await renderizar();
    const dialogo = screen.getByRole("dialog", { name: "Gerar certificados" });
    expect(within(dialogo).getByText("Ranking · Matemática · 4º bimestre")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Top 3" })).toBeChecked();
    expect(nomesDoLote()).toEqual(["Ana Beatriz Souza", "Bruno Lima", "Carla Mendes"]);
    // A posição é a da tela (medalha do pódio com o texto para o leitor de tela).
    expect(within(linhaDe("Ana Beatriz Souza")).getByText("1º lugar")).toBeInTheDocument();
  });

  it("Top 5, Top 10 e personalizado pegam os N primeiros, sem pular ninguém", async () => {
    const { u } = await renderizar();

    await u.click(screen.getByRole("radio", { name: "Top 5" }));
    expect(nomesDoLote()).toEqual([
      "Ana Beatriz Souza", "Bruno Lima", "Carla Mendes", "Davi Rocha", "Elisa Prado",
    ]);

    await u.click(screen.getByRole("radio", { name: "Personalizado" }));
    const campo = screen.getByLabelText("Quantos alunos (1 a 50)");
    await u.clear(campo);
    await u.type(campo, "6");
    expect(nomesDoLote()).toEqual([
      "Ana Beatriz Souza", "Bruno Lima", "Carla Mendes", "Davi Rocha", "Elisa Prado", "Fábio Nunes",
    ]);

    await u.clear(campo);
    await u.type(campo, "51");
    expect(screen.getByText("Informe um número inteiro de 1 a 50.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Alunos do lote" })).toBeNull();
    expect(screen.getByRole("button", { name: "Verificar" })).toBeDisabled();

    await u.click(screen.getByRole("radio", { name: "Top 10" }));
    expect(nomesDoLote()).toEqual(LISTA.map((a) => a.nome));
    expect(screen.getByText("A lista desta tela tem 7 alunos: entram todos.")).toBeInTheDocument();
  });

  it("linha sem ficha (aluno_id nulo) fica de fora com aviso e ninguém entra no lugar", async () => {
    responderPreviaComRecusa();
    const alunos: AlunoParaCertificado[] = [
      LISTA[0],
      { aluno_id: null, nome: "Linha sem ficha", turma: "4º Ano B", posicao: 2 },
      ...LISTA.slice(2),
    ];
    const { u } = await renderizar({ alunos });
    await u.click(screen.getByRole("radio", { name: "Top 5" }));

    expect(nomesDoLote()).toEqual([
      "Ana Beatriz Souza", "Linha sem ficha", "Carla Mendes", "Davi Rocha", "Elisa Prado",
    ]);
    expect(
      screen.getByText(/1 dos primeiros da lista não tem ficha de aluno vinculada e fica de fora\./),
    ).toBeInTheDocument();
    expect(within(linhaDe("Linha sem ficha")).getByText("Fora do lote")).toBeInTheDocument();
    // O 6º colocado NÃO é puxado para completar o Top 5.
    expect(screen.queryByText("Fábio Nunes")).toBeNull();

    await u.click(screen.getByRole("button", { name: "Verificar" }));
    expect(await screen.findByRole("button", { name: "Gerar PDF (3 aptos)" })).toBeEnabled();
    expect(corpoDaPrevia()).toEqual({ modelo: "matific", aluno_ids: [101, 103, 104, 105] });
  });
});

describe("GerarCertificados — modelo por módulo contratado", () => {
  it("com os dois módulos: Elefante Letrado, Matific e Geral; abre no modelo da aba", async () => {
    await renderizar({ modeloInicial: "elefante" });
    expect(screen.getByRole("radio", { name: "Elefante Letrado" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Matific" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Geral" })).not.toBeChecked();
  });

  it("a descrição da arte da plataforma usa o nome impresso no PDF (certificado de desempenho)", async () => {
    await renderizar({ modeloInicial: "elefante" });
    expect(screen.getByText(/certificado de desempenho da plataforma/)).toBeInTheDocument();
    expect(screen.queryByText(/certificado de participação/)).not.toBeInTheDocument();
  });

  it("rede só com Matemática: sem o chip do Elefante", async () => {
    await renderizar({ modeloInicial: "matific" }, ["matematica"]);
    expect(screen.queryByRole("radio", { name: "Elefante Letrado" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Matific" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Geral" })).toBeInTheDocument();
  });

  it("rede só com Leitura: sem o chip do Matific, e o modelo da aba cai no Geral", async () => {
    responderPreviaComRecusa();
    const { u } = await renderizar({ modeloInicial: "matific" }, ["leitura"]);
    expect(screen.queryByRole("radio", { name: "Matific" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Elefante Letrado" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Geral" })).toBeChecked();
    // O Geral não imprime bimestre: o seletor fica desabilitado, com o porquê.
    expect(screen.getByLabelText("Bimestre impresso")).toBeDisabled();
    expect(screen.getByText("O certificado Geral não imprime bimestre.")).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Verificar" }));
    await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" });
    expect(corpoDaPrevia()).toEqual({ modelo: null, aluno_ids: [101, 102, 103] });
  });
});

describe("GerarCertificados — prévia e geração", () => {
  it("recusado aparece com o motivo do backend e não é substituído pelo próximo colocado", async () => {
    responderPreviaComRecusa();
    const { u } = await renderizar();
    await u.click(screen.getByRole("button", { name: "Verificar" }));

    expect(await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" })).toBeEnabled();
    expect(corpoDaPrevia()).toEqual({ modelo: "matific", aluno_ids: [101, 102, 103] });

    const carla = linhaDe("Carla Mendes");
    expect(within(carla).getByText("Não emitido")).toBeInTheDocument();
    expect(within(carla).getByText(MOTIVO_LISTA_PILOTO)).toBeInTheDocument();
    expect(within(linhaDe("Ana Beatriz Souza")).getByText("Apto")).toBeInTheDocument();
    expect(within(linhaDe("Bruno Lima")).getByText("Apto")).toBeInTheDocument();
    // Continua o Top 3 da tela: o 4º colocado não entra no lugar da recusada.
    expect(nomesDoLote()).toEqual(["Ana Beatriz Souza", "Bruno Lima", "Carla Mendes"]);
    expect(screen.queryByText("Davi Rocha")).toBeNull();

    const resultado = within(screen.getByRole("dialog")).getByRole("status");
    expect(resultado).toHaveTextContent("2 aptos");
    expect(resultado).toHaveTextContent("1 não emitido");
  });

  it("Gerar PDF chama apiDownloadPost com o caminho e o corpo do contrato (só os aptos, na ordem)", async () => {
    responderPreviaComRecusa();
    const { u } = await renderizar();
    const bimestre = screen.getByLabelText("Bimestre impresso");
    expect(bimestre).toHaveValue(String(bimestreDeHoje(new Date())));
    await u.selectOptions(bimestre, "3");

    // Antes de verificar não há o que gerar.
    expect(screen.getByRole("button", { name: "Gerar PDF" })).toBeDisabled();
    await u.click(screen.getByRole("button", { name: "Verificar" }));
    await u.click(await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" }));

    expect(apiDownloadPost).toHaveBeenCalledTimes(1);
    expect(apiDownloadPost).toHaveBeenCalledWith(
      LOTE,
      { modelo: "matific", bimestre: 3, aluno_ids: [101, 102] },
      "certificados_matific_2.pdf",
    );
    const resultado = within(screen.getByRole("dialog")).getByRole("status");
    expect(await within(resultado).findByText("PDF com 2 certificados baixado")).toBeInTheDocument();
  });

  it("Geral manda bimestre nulo; a contagem do sucesso vem do arquivo que o backend devolveu", async () => {
    responderPreviaComRecusa();
    apiDownloadPost.mockResolvedValueOnce("certificados_geral_1.pdf");
    const { u } = await renderizar({ modeloInicial: null });
    expect(screen.getByRole("radio", { name: "Geral" })).toBeChecked();

    await u.click(screen.getByRole("button", { name: "Verificar" }));
    await u.click(await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" }));

    expect(apiDownloadPost).toHaveBeenCalledWith(
      LOTE,
      { modelo: null, bimestre: null, aluno_ids: [101, 102] },
      "certificados_geral_2.pdf",
    );
    expect(await screen.findByText("PDF com 1 certificado baixado")).toBeInTheDocument();
  });

  it("mudar a escolha depois de verificar exige verificar de novo", async () => {
    responderPreviaComRecusa();
    const { u } = await renderizar();
    await u.click(screen.getByRole("button", { name: "Verificar" }));
    await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" });

    await u.click(screen.getByRole("radio", { name: "Top 5" }));
    expect(screen.queryByText("Apto")).toBeNull();
    expect(screen.queryByText("Não emitido")).toBeNull();
    expect(screen.getByRole("button", { name: "Gerar PDF" })).toBeDisabled();
    expect(apiDownloadPost).not.toHaveBeenCalled();
  });
});

// Lista de um bimestre (ex.: Premiações do 3º, já fechado): o seletor abre NELE. Antes
// abria sempre no bimestre de hoje e, em 31/10, o 3º saía impresso como 4º.
describe("GerarCertificados — bimestre impresso da lista", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Só o relógio é falso (timers de verdade: o userEvent e o useApi seguem normais). */
  function hojeEm(data: Date) {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(data);
  }

  it("com bimestreInicial, abre nele (não no de hoje) e é ele que vai no lote", async () => {
    hojeEm(new Date(2026, 9, 31, 12, 0, 0));
    responderPreviaComRecusa();
    const { u } = await renderizar({ bimestreInicial: 3 });

    const bimestre = screen.getByLabelText("Bimestre impresso");
    expect(bimestre).toHaveValue("3");
    expect(within(bimestre).getByRole("option", { name: "3º bimestre", selected: true })).toBeInTheDocument();
    expect(screen.getByText("Abre no bimestre do período desta lista; vale o que você escolher."))
      .toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Verificar" }));
    await u.click(await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" }));
    expect(apiDownloadPost).toHaveBeenCalledWith(
      LOTE,
      { modelo: "matific", bimestre: 3, aluno_ids: [101, 102] },
      "certificados_matific_2.pdf",
    );
  });

  it("sem bimestreInicial (ou fora de 1–4), o padrão continua o bimestre de hoje", async () => {
    hojeEm(new Date(2026, 9, 31, 12, 0, 0));
    await renderizar({ bimestreInicial: 7 });

    expect(screen.getByLabelText("Bimestre impresso")).toHaveValue("4");
    expect(screen.getByText("Abre no bimestre de hoje pelo calendário oficial; vale o que você escolher."))
      .toBeInTheDocument();
  });

  it("bimestreDoPeriodo: o número do preset de bimestre; outro período não sugere nada", () => {
    const hoje = new Date(2026, 9, 31, 12, 0, 0); // 31/10/2026: 4º bimestre em curso
    expect(bimestreDoPeriodo("bimestre_3", hoje)).toBe(3);
    expect(bimestreDoPeriodo("bimestre_1", hoje)).toBe(1);
    expect(bimestreDoPeriodo("bimestre", hoje)).toBe(4);
    expect(bimestreDoPeriodo("bimestre_anterior", hoje)).toBe(3);
    // Do 1º bimestre, o anterior é o 4º (do ano passado, como no backend).
    expect(bimestreDoPeriodo("bimestre_anterior", new Date(2026, 2, 10, 12, 0, 0))).toBe(4);
    // Recesso de janeiro: fora do calendário, não afirma qual é o anterior.
    expect(bimestreDoPeriodo("bimestre_anterior", new Date(2026, 0, 15, 12, 0, 0))).toBeUndefined();
    for (const preset of ["mes", "semana", "ano_letivo", "personalizado", "dia", "bimestre_5"]) {
      expect(bimestreDoPeriodo(preset, hoje)).toBeUndefined();
    }
  });
});

describe("GerarCertificados — erros e estados", () => {
  it("erro da prévia aparece com a mensagem do backend", async () => {
    responderErro("POST", PREVIA, 403, "O módulo Matemática não está no plano desta rede.");
    const { u } = await renderizar();
    await u.click(screen.getByRole("button", { name: "Verificar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("O módulo Matemática não está no plano desta rede.");
    expect(screen.getByRole("button", { name: "Gerar PDF" })).toBeDisabled();
  });

  it("422 do lote mostra o detail e atualiza os alunos enviados com os itens devolvidos", async () => {
    responderPreviaComRecusa();
    // O lote recebe só os aptos da prévia (101 e 102): o 422 devolve os itens deles.
    const erro = Object.assign(new ApiError(422, "Nenhum aluno apto para o certificado."), {
      corpo: {
        detail: "Nenhum aluno apto para o certificado.",
        itens: [101, 102].map((id) => ({
          aluno_id: id, nome: null, turma: null, apto: false, motivo: `Motivo atual do aluno ${id}.`,
        })),
      },
    });
    apiDownloadPost.mockRejectedValueOnce(erro);
    const { u } = await renderizar();
    await u.click(screen.getByRole("button", { name: "Verificar" }));
    await u.click(await screen.findByRole("button", { name: "Gerar PDF (2 aptos)" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nenhum aluno apto para o certificado.");
    expect(within(linhaDe("Ana Beatriz Souza")).getByText("Motivo atual do aluno 101.")).toBeInTheDocument();
    expect(within(linhaDe("Bruno Lima")).getByText("Motivo atual do aluno 102.")).toBeInTheDocument();
    // A recusada da prévia continua com o motivo que a prévia deu.
    expect(within(linhaDe("Carla Mendes")).getByText(MOTIVO_LISTA_PILOTO)).toBeInTheDocument();
    expect(screen.getAllByText("Não emitido")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Gerar PDF (0 aptos)" })).toBeDisabled();
    expect(screen.queryByText(/certificados? baixado/)).toBeNull();
  });

  it("lista vazia: estado vazio, sem botões de verificar/gerar; Fechar chama aoFechar", async () => {
    const { u, aoFechar } = await renderizar({ alunos: [] });
    expect(screen.getByText("Nenhum aluno nesta lista")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verificar" })).toBeNull();
    await u.click(screen.getByRole("button", { name: "Fechar" }));
    expect(aoFechar).toHaveBeenCalledTimes(1);
  });

  it("fechado não renderiza nada", async () => {
    await renderizar({ aberto: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

/**
 * O helper REAL de download por POST (lib/api.ts), com fetch simulado: o mock global de
 * ../lib/api cobre as telas; aqui se confere o transporte de verdade (token, corpo JSON,
 * nome pelo Content-Disposition, detail do backend e o corpo do erro para os itens).
 */
describe("apiDownloadPost (implementação real, fetch simulado)", () => {
  const desfazer: Array<() => void> = [];
  afterEach(() => {
    while (desfazer.length) desfazer.pop()?.();
  });

  function prepararDownload(resposta: Response | Error) {
    const fetchFalso = vi.fn(async (_url: string, _init?: RequestInit) => {
      if (resposta instanceof Error) throw resposta;
      return resposta;
    });
    vi.stubGlobal("fetch", fetchFalso);
    const salvos: string[] = [];
    const clique = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        salvos.push(this.download);
      });
    const criar = URL.createObjectURL;
    const revogar = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:teste");
    URL.revokeObjectURL = vi.fn();
    desfazer.push(() => {
      vi.unstubAllGlobals();
      clique.mockRestore();
      URL.createObjectURL = criar;
      URL.revokeObjectURL = revogar;
    });
    return { fetchFalso, salvos };
  }

  const real = () => vi.importActual<typeof import("../lib/api")>("../lib/api");

  it("faz POST com o token e o corpo JSON e salva com o nome do Content-Disposition", async () => {
    localStorage.setItem("sgpe_token", "token-real");
    const { fetchFalso, salvos } = prepararDownload(
      new Response("%PDF-1.4", {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="certificados_matific_2.pdf"',
        },
      }),
    );
    const { apiDownloadPost: baixar } = await real();
    const corpo = { modelo: "matific", bimestre: 4, aluno_ids: [101, 102] };

    await expect(baixar(LOTE, corpo, "padrao.pdf")).resolves.toBe("certificados_matific_2.pdf");
    expect(salvos).toEqual(["certificados_matific_2.pdf"]);
    expect(fetchFalso).toHaveBeenCalledTimes(1);
    const [url, init] = fetchFalso.mock.calls[0];
    expect(url).toBe(`/api/v1${LOTE}`);
    expect(init?.method).toBe("POST");
    expect(init?.headers).toEqual({ "Content-Type": "application/json", Authorization: "Bearer token-real" });
    expect(JSON.parse(String(init?.body))).toEqual(corpo);
  });

  it("sem Content-Disposition, salva com o nome padrão pedido", async () => {
    const { salvos } = prepararDownload(new Response("%PDF-1.4", { status: 200 }));
    const { apiDownloadPost: baixar } = await real();
    await expect(baixar(LOTE, { modelo: null, bimestre: null, aluno_ids: [101] }, "certificados_geral_1.pdf"))
      .resolves.toBe("certificados_geral_1.pdf");
    expect(salvos).toEqual(["certificados_geral_1.pdf"]);
  });

  it("erro: a mensagem é o detail do backend e o corpo (itens do 422) vai junto; nada é baixado", async () => {
    const itens = [{ aluno_id: 101, nome: null, turma: null, apto: false, motivo: "Fora da Lista Piloto." }];
    const { salvos } = prepararDownload(
      new Response(JSON.stringify({ detail: "Nenhum aluno apto para o certificado.", itens }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { apiDownloadPost: baixar } = await real();
    await expect(baixar(LOTE, { modelo: "matific", bimestre: 4, aluno_ids: [101] })).rejects.toMatchObject({
      status: 422,
      message: "Nenhum aluno apto para o certificado.",
      corpo: { detail: "Nenhum aluno apto para o certificado.", itens },
    });
    expect(salvos).toEqual([]);
  });

  it("falha de rede vira ApiError(0) com a mensagem amigável (nunca o texto cru do navegador)", async () => {
    prepararDownload(new TypeError("Failed to fetch"));
    const { apiDownloadPost: baixar, ApiError: ErroReal } = await real();
    const promessa = baixar(LOTE, { modelo: "matific", bimestre: 4, aluno_ids: [101] });
    await expect(promessa).rejects.toBeInstanceOf(ErroReal);
    await expect(promessa).rejects.toMatchObject({
      status: 0,
      message: "Não foi possível conectar. Verifique a internet e tente de novo.",
    });
  });
});
