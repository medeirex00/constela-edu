/**
 * G_MODULOS-6 — rede só com a Leitura: as METAS de um módulo fora do plano.
 *
 * O cadastro do Painel da Rede (`/rede`, Secretaria) não recebia os módulos da rede e
 * oferecia "Matemática (Matific)" e "Atividades Matific na rede" numa rede que não contratou
 * a Matemática; e o progresso mostrava a meta de Matemática gravada antes de o Admin Global
 * desligar o módulo, calculada com o dado do Matific. O backend agora recusa e omite essas
 * metas; a tela também não as oferece nem as mostra (resposta antiga no cache do PWA).
 *
 * Redes, escolas e números INVENTADOS.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("leaflet", () => ({ default: { divIcon: () => ({}) } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: () => undefined, fitBounds: () => undefined }),
}));

import RedeDashboard, { PanoramaDaRede } from "../pages/rede/RedeDashboard";
import { escolaFake, renderComApp, responder, screen, usuarioFake, within } from "./utils";

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador", escola_id: null });
const admin = usuarioFake({ nome: "Admin Inventado", is_global: true, cargo: "admin", escola_id: null });

const META_LEITURA = {
  id: 1, metrica: "media_elefante", rotulo: "Leitura (Elefante Letrado)", sufixo: "", alvo: 50,
  atual: 40, progresso: 80, atingida: false, descricao: null,
  escolas_atingiram: null, escolas_total: null, comparavel: false, medida: true,
};
// Gravada quando a rede tinha a Matemática (o backend antigo ainda a devolvia).
const META_MATIFIC = {
  id: 2, metrica: "atividades", rotulo: "Atividades Matific na rede", sufixo: "", alvo: 1000,
  atual: 21, progresso: 2.1, atingida: false, descricao: null,
  escolas_atingiram: null, escolas_total: null, comparavel: false, medida: true,
};

function semear() {
  responder("GET", "/redes/7/dashboard", {
    rede_id: 7,
    modulos: ["leitura"],
    totais: {
      escolas: 0, escolas_ativas: 0, alunos: 0, turmas: 0, professores: 0,
      alunos_com_dados: 0, adocao: 0, media_geral: 0, media_matific: null, media_elefante: 0,
      pontuacao_geral: 0, escolas_em_atencao: 0, livros: 0, tempo_leitura_min: 0, atividades: null,
      estrelas: null, ativos_matific: null, ativos_elefante: 0, livros_por_aluno: 0, melhor_escola: null,
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 0, escola_menor_indice: 0, escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 0, escola_menor_media: 0, escolas_abaixo_da_media: 0,
    },
    escolas: [],
    atencao: [],
  });
  responder("GET", "/redes/7/metas", [META_LEITURA, META_MATIFIC]);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

describe("Metas numa rede só com a Leitura", () => {
  it("Painel da Rede: o cadastro não oferece meta de Matemática", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const select = await screen.findByLabelText("Indicador da meta");
    const opcoes = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toContain("Leitura (Elefante Letrado)");
    expect(opcoes).not.toContain("Matemática (Matific)");
    expect(opcoes).not.toContain("Atividades Matific na rede");
  });

  it("Painel da Rede: o progresso e a lista do cadastro não mostram a meta do Matific", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    // As metas carregadas (o resumo só aparece com elas): a de Leitura, sem a do Matific.
    expect(await screen.findByTestId("resumo-metas")).toHaveTextContent("0 de 1 meta atingida");
    expect(screen.getByRole("button", { name: "Remover a meta Leitura (Elefante Letrado)" })).toBeInTheDocument();
    expect(screen.queryByText("Atividades Matific na rede")).not.toBeInTheDocument();
  });

  it("Panorama de uma rede (Admin Global): o progresso não mostra a meta do Matific", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    expect(await screen.findByTestId("resumo-metas")).toHaveTextContent("0 de 1 meta atingida");
    expect(screen.getByText("Leitura (Elefante Letrado)")).toBeInTheDocument();
    expect(screen.queryByText("Atividades Matific na rede")).not.toBeInTheDocument();
  });
});
