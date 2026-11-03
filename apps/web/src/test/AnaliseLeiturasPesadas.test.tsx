/**
 * As leituras PESADAS — o diagnóstico (mede as plataformas da rede inteira) e a evolução por
 * bimestre (mede uma vez por bimestre já começado), hoje lidas pelas telas de detalhe da
 * Secretaria (Escolas em acompanhamento, Elefante e Matific; o Panorama não lê nenhuma): 60 s de
 * tempo limite, SEM nova tentativa automática (o servidor não cancela o cálculo quando a tela desiste: repetir
 * somaria outro cálculo inteiro) e cache curto (trocar de tela não refaz a medição) — sem nunca
 * mostrar a resposta de outro recorte sob o filtro atual. As plataformas (leitura de segundos com
 * dados reais) também ficam guardadas entre as telas.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// O useApi DE VERDADE, só observado: as opções que cada leitura passa a ele.
vi.mock("../hooks/useApi", async (importOriginal) => {
  const original = await importOriginal<typeof import("../hooks/useApi")>();
  return { ...original, useApi: vi.fn(original.useApi) };
});

import { limparCacheApi, useApi } from "../hooks/useApi";
import AcompanhamentoRede from "../pages/rede/secretaria/AcompanhamentoRede";
import PanoramaSecretaria from "../pages/rede/secretaria/PanoramaSecretaria";
import PlataformasRedePagina from "../pages/rede/secretaria/PlataformasRedePagina";
import { evolucao, secretaria } from "./AnaliseFixturesDiagnostico";
import { chamadas, semearSecretaria } from "./SecretariaFixtures";
import { renderComApp, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

const EVOLUCAO = "/redes/1/analise/plataformas/evolucao";
const DIAGNOSTICO = "/redes/1/analise/diagnostico";
const PLATAFORMAS = "/redes/1/analise/plataformas";

const opcoesDe = (caminho: string) => vi.mocked(useApi).mock.calls
  .filter(([fonte]) => typeof fonte === "string" && fonte.split("?")[0] === caminho)
  .map(([, opcoes]) => opcoes);

/** As três telas que leem o pesado, numa rota de verdade (para navegar entre elas). */
function TelasDaRede() {
  return (
    <Routes>
      <Route path="/" element={<PanoramaSecretaria />} />
      <Route path="/rede/acompanhamento" element={<AcompanhamentoRede />} />
      <Route path="/rede/plataformas" element={<PlataformasRedePagina />} />
    </Routes>
  );
}
const abrir = (rota: string) => renderComApp(<TelasDaRede />, { usuario: secretaria, rota });

beforeEach(() => {
  vi.mocked(useApi).mockClear();
  limparCacheApi();
});

describe("Leituras pesadas (diagnóstico e evolução por bimestre)", () => {
  it("60 s de tempo limite (não os 15 s padrão), sem nova tentativa automática e com cache curto", async () => {
    semearSecretaria();
    // Do Panorama ao detalhe do uso (a evolução por bimestre)...
    const panorama = abrir("/");
    await screen.findByTestId("conclusao-plataformas");
    await userEvent.click(screen.getByRole("link", { name: /Ver o uso em detalhe/ }));
    await screen.findByTestId("tabela-evolucao-rede");
    panorama.unmount();
    // ...e às Escolas em acompanhamento (o diagnóstico).
    abrir("/rede/acompanhamento");
    await screen.findByTestId("lista-acompanhamento");
    for (const caminho of [EVOLUCAO, DIAGNOSTICO]) {
      const opcoes = opcoesDe(caminho);
      expect(opcoes.length).toBeGreaterThan(0);
      for (const op of opcoes) {
        expect(op).toMatchObject({ timeoutMs: 60_000, tentativas: 0 });
        expect(op?.cacheMs).toBeGreaterThan(0);
      }
    }
  });

  it("falha transitória (503): uma leitura só — o erro aparece, sem repetir o cálculo sozinho", async () => {
    semearSecretaria();
    responderErro("GET", EVOLUCAO, 503, "FALHA-EVO");
    responderErro("GET", DIAGNOSTICO, 503, "FALHA-DIAG");
    abrir("/rede/plataformas");
    expect(await screen.findByText("Não foi possível carregar a evolução por bimestre: FALHA-EVO")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 400));      // a nova tentativa do padrão viria em 300 ms
    expect(chamadas(EVOLUCAO)).toHaveLength(1);
  });

  it("falha transitória do diagnóstico: uma leitura só, e o erro na tela do acompanhamento", async () => {
    semearSecretaria();
    responderErro("GET", DIAGNOSTICO, 503, "FALHA-DIAG");
    abrir("/rede/acompanhamento");
    expect(await screen.findByText("Não foi possível carregar as escolas em acompanhamento: FALHA-DIAG")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 400));
    expect(chamadas(DIAGNOSTICO)).toHaveLength(1);
  });

  it("o Panorama da Rede não pede nenhuma leitura pesada: o diagnóstico e a evolução ficam nas telas de detalhe", async () => {
    semearSecretaria();
    abrir("/");
    await screen.findByTestId("lista-escolas");
    await screen.findByTestId("conclusao-plataformas");
    expect(chamadas(DIAGNOSTICO)).toHaveLength(0);
    expect(chamadas(EVOLUCAO)).toHaveLength(0);
  });

  it("ir do Panorama à tela das plataformas não refaz a leitura das plataformas do ano letivo", async () => {
    semearSecretaria();
    abrir("/");
    await screen.findByTestId("conclusao-plataformas");
    await userEvent.click(screen.getByRole("link", { name: /Ver o uso em detalhe/ }));
    await screen.findByTestId("totais-gerais");
    expect(screen.getByTestId("conclusao-plataformas")).toHaveTextContent("No ano letivo de 2026");
    expect(chamadas(PLATAFORMAS)).toHaveLength(1);
  });

  it("com o cache, a evolução de outra série nunca aparece sob o recorte atual — e a já lida volta sem nova leitura", async () => {
    semearSecretaria();
    const soPrimeiro = evolucao({ bimestres: evolucao().bimestres.slice(0, 1) });
    responder("GET", EVOLUCAO, (c: string) => {
      const serie = new URLSearchParams(c.split("?")[1] ?? "").get("serie");
      if (serie === "4") return new Promise(() => {});                         // ainda a caminho
      return serie === "5" ? soPrimeiro : evolucao();
    });
    abrir("/rede/plataformas");
    const linhas = () => within(screen.getByTestId("tabela-evolucao-rede")).getAllByRole("row").length - 1;
    await screen.findByTestId("tabela-evolucao-rede");
    expect(linhas()).toBe(4);
    // A série fica no topo da tela (vale para os cartões e a evolução).
    const serie = screen.getByLabelText("Série");
    // A série 4 ainda a caminho: a tabela de "1º ao 5º ano" (guardada) NÃO fica sob o recorte novo.
    await userEvent.selectOptions(serie, "4");
    expect(await screen.findByText("Carregando a evolução por bimestre...")).toBeInTheDocument();
    expect(screen.queryByTestId("tabela-evolucao-rede")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Série"), "5");
    await waitFor(() => expect(linhas()).toBe(1));
    // De volta a "1º ao 5º ano": a resposta guardada volta (o cache não chama `aoSucesso`), sem nova leitura.
    await userEvent.selectOptions(screen.getByLabelText("Série"), "");
    await waitFor(() => expect(linhas()).toBe(4));
    expect(chamadas(EVOLUCAO).filter((c) => !c.includes("serie="))).toHaveLength(1);
  });
});
