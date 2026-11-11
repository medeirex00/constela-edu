/**
 * O calendário dos bimestres da web vem do BACKEND (auditoria PERIODOS-7 e RELATORIOS-6).
 *
 * Antes, lib/calendarioBimestres.ts só conhecia 2026: de 2027 em diante `bimestreDeHoje`
 * devolvia 1 ("o backend decide o padrão" — falso: a web mandava o número), o certificado
 * da plataforma (individual em Relatórios e em lote no modal) abria no "1º bimestre"
 * dizendo "pelo calendário oficial" e esse número ia impresso; o selo "Fim do bimestre"
 * sumia mesmo com o calendário de 2027 cadastrado no backend (BIMESTRES_CALENDARIO).
 *
 * Agora: a rota GET /escolas/{id}/configuracoes/calendario-bimestres?ano= é a fonte; com o
 * ano cadastrado lá, a tela abre no bimestre certo; sem calendário, o seletor abre VAZIO,
 * a dica não fala em "calendário oficial" e a arte da plataforma espera a escolha.
 * Datas de 2027 FICTÍCIAS (as do exemplo de backend/app/services/bimestres.py).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import GerarCertificados from "../components/GerarCertificados";
import Layout from "../components/Layout";
import { useApp } from "../context/AppContext";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import {
  bimestreDeHoje, bimestreEmCurso, semCalendarioOficial, type CalendarioDoAno,
} from "../lib/calendarioBimestres";
import { bimestreDoPeriodo } from "../lib/tiposCertificados";
import Relatorios from "../pages/Relatorios";
import {
  api, apiDownload, apiDownloadPost, escolaFake, renderComApp, responder, screen, userEvent, usuarioFake,
  waitFor, within,
} from "./utils";

const CAL_2027: CalendarioDoAno = {
  ano: 2027,
  bimestres: [
    { numero: 1, inicio: "2027-02-01", fim: "2027-04-23" },
    { numero: 2, inicio: "2027-04-26", fim: "2027-07-09" },
    { numero: 3, inicio: "2027-07-26", fim: "2027-10-01" },
    { numero: 4, inicio: "2027-10-04", fim: "2027-12-17" },
  ],
};
const SEM_2027: CalendarioDoAno = { ano: 2027, bimestres: null };
const ROTA_CAL = "/escolas/1/configuracoes/calendario-bimestres";
const DICA_OFICIAL = "Abre no bimestre de hoje pelo calendário oficial; vale o que você escolher.";
const DICA_SEM_CAL =
  "O calendário oficial de 2027 não está cadastrado no sistema: escolha o bimestre que o certificado vai afirmar.";

const EM_15_10_2027 = new Date(2027, 9, 15, 12, 0, 0);

function relogioEm(data: Date) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(data);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("funções do calendário: nada de bimestre inventado", () => {
  it("ano que a web não conhece não tem bimestre de hoje (antes: 1)", () => {
    expect(bimestreDeHoje(EM_15_10_2027)).toBeNull();
    expect(bimestreEmCurso(EM_15_10_2027)).toBeNull();
    expect(bimestreDoPeriodo("bimestre", EM_15_10_2027)).toBeUndefined();
  });

  it("com o calendário do backend, 15/10/2027 é o 4º (e o selo conta até 17/12)", () => {
    expect(bimestreDeHoje(EM_15_10_2027, CAL_2027)).toBe(4);
    expect(bimestreDoPeriodo("bimestre", EM_15_10_2027, CAL_2027)).toBe(4);
    expect(bimestreDoPeriodo("bimestre_anterior", EM_15_10_2027, CAL_2027)).toBe(3);
    expect(bimestreEmCurso(EM_15_10_2027, CAL_2027)).toMatchObject({ numero: 4, ano: 2027, diasParaOFim: 63 });
    // Recesso de julho de 2027 (entre o 2º e o 3º): abre no próximo, como no backend.
    expect(bimestreDeHoje(new Date(2027, 6, 15, 12), CAL_2027)).toBe(3);
    expect(bimestreEmCurso(new Date(2027, 6, 15, 12), CAL_2027)).toBeNull();
    // Depois do fim do 4º: continua o 4º.
    expect(bimestreDeHoje(new Date(2027, 11, 20, 12), CAL_2027)).toBe(4);
  });

  it("o backend sem calendário do ano: nada de número, e dá para dizer isso a quem usa", () => {
    expect(bimestreDeHoje(EM_15_10_2027, SEM_2027)).toBeNull();
    expect(semCalendarioOficial(EM_15_10_2027, SEM_2027)).toBe(true);
    // Sem resposta (carregando, erro) não se afirma que falta calendário.
    expect(semCalendarioOficial(EM_15_10_2027, null)).toBe(false);
    expect(semCalendarioOficial(EM_15_10_2027, CAL_2027)).toBe(false);
  });

  it("calendário de OUTRO ano não vale para a data: 2026 segue na cópia oficial", () => {
    expect(bimestreDeHoje(new Date(2026, 9, 1, 12), CAL_2027)).toBe(3);
    expect(bimestreDeHoje(new Date(2026, 9, 5, 12), SEM_2027)).toBe(4);
  });
});

function SessaoPronta() {
  const { carregando } = useApp();
  return carregando ? null : <span data-testid="sessao-pronta" hidden />;
}

async function abrirModal() {
  renderComApp(
    <>
      <GerarCertificados
        escolaId={1}
        alunos={[{ aluno_id: 101, nome: "Ana Beatriz Souza", posicao: 1 }]}
        modeloInicial="matific"
        contexto="Ranking · Matemática · Ano letivo"
        aberto
        aoFechar={() => undefined}
      />
      <SessaoPronta />
    </>,
    { usuario: usuarioFake({ modulos: ["leitura", "matematica"] }) },
  );
  await screen.findByTestId("sessao-pronta");
  return { u: userEvent.setup(), seletor: screen.getByLabelText("Bimestre impresso") as HTMLSelectElement };
}

describe("modal de certificados em lote em 15/10/2027", () => {
  it("com o calendário de 2027 cadastrado no backend, abre no 4º pelo calendário oficial", async () => {
    relogioEm(EM_15_10_2027);
    responder("GET", ROTA_CAL, CAL_2027);
    const { seletor } = await abrirModal();
    await waitFor(() => expect(seletor.value).toBe("4"));
    expect(screen.getByText(DICA_OFICIAL)).toBeInTheDocument();
    expect(api.mock.calls.some(([c]) => String(c) === `${ROTA_CAL}?ano=2027`)).toBe(true);
  });

  it("sem calendário de 2027: abre sem número, diz por quê e só gera depois da escolha", async () => {
    relogioEm(EM_15_10_2027);
    responder("GET", ROTA_CAL, SEM_2027);
    responder("POST", "/escolas/1/certificados/lote/previa", {
      modelo: "matific", itens: [{ aluno_id: 101, nome: "Ana Beatriz Souza", turma: null, apto: true, motivo: null }],
    });
    const { u, seletor } = await abrirModal();

    expect(await screen.findByText(DICA_SEM_CAL)).toBeInTheDocument();
    expect(seletor.value).toBe("");
    expect(within(seletor).getByRole("option", { selected: true })).toHaveTextContent("Escolha o bimestre");
    expect(screen.queryByText(DICA_OFICIAL)).toBeNull();

    await u.click(screen.getByRole("button", { name: "Verificar" }));
    const gerar = await screen.findByRole("button", { name: "Gerar PDF (1 apto)" });
    expect(gerar).toBeDisabled();

    await u.selectOptions(seletor, "3");
    expect(gerar).toBeEnabled();
    await u.click(gerar);
    expect(apiDownloadPost).toHaveBeenCalledWith(
      "/escolas/1/certificados/lote", { modelo: "matific", bimestre: 3, aluno_ids: [101] },
      "certificados_matific_1.pdf");
  });
});

function alunoFake(id: number, nome: string) {
  return { id, nome, foto_url: null, numero_chamada: null, status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano" };
}

async function abrirRelatorios() {
  responder("GET", /\/escolas\/1\/alunos/, {
    total: 1, pagina: 1, por_pagina: 1000, itens: [alunoFake(1, "Ana Beatriz Souza")] });
  renderComApp(<Relatorios />, {
    rota: "/relatorios", usuario: usuarioFake(), escolas: [escolaFake({ id: 1 })], escolaSelecionada: 1,
  });
  await screen.findByRole("option", { name: "Ana Beatriz Souza" });
  const u = userEvent.setup();
  await u.selectOptions(screen.getByRole("combobox", { name: "Aluno" }), "1");
  return { u, seletor: screen.getByRole("combobox", { name: "Bimestre" }) as HTMLSelectElement };
}

describe("certificado individual (Relatórios) em 15/10/2027", () => {
  it("com o calendário de 2027 no backend, o Elefante sai com o 4º", async () => {
    relogioEm(EM_15_10_2027);
    responder("GET", ROTA_CAL, CAL_2027);
    const { u, seletor } = await abrirRelatorios();
    await waitFor(() => expect(seletor.value).toBe("4"));
    await u.click(screen.getByRole("button", { name: "Elefante Letrado" }));
    expect(apiDownload).toHaveBeenCalledWith("/escolas/1/certificados/1?modelo=elefante&bimestre=4");
  });

  it("sem calendário de 2027: nada de '1º' pré-escolhido; as artes das plataformas esperam a escolha", async () => {
    relogioEm(EM_15_10_2027);
    responder("GET", ROTA_CAL, SEM_2027);
    const { u, seletor } = await abrirRelatorios();

    expect(await screen.findByText(DICA_SEM_CAL)).toBeInTheDocument();
    expect(seletor.value).toBe("");
    expect(screen.getByRole("button", { name: "Elefante Letrado" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Matific" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Geral" })).toBeEnabled();   // não imprime bimestre
    expect(screen.getByText("Escolha o bimestre para liberar os modelos das plataformas.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("abre no bimestre de hoje pelo calendário oficial");

    await u.selectOptions(seletor, "2");
    await u.click(screen.getByRole("button", { name: "Matific" }));
    expect(apiDownload).toHaveBeenCalledWith("/escolas/1/certificados/1?modelo=matific&bimestre=2");
    expect(apiDownload.mock.calls.some(([c]) => String(c).includes("bimestre=1"))).toBe(false);
  });
});

describe("selo 'Fim do bimestre' do menu em 2027", () => {
  it("vem do calendário do backend, em vez de sumir", async () => {
    relogioEm(EM_15_10_2027);
    responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
    responder("GET", "/notificacoes/contador", { nao_lidas: 0 });
    responder("GET", ROTA_CAL, CAL_2027);
    const usuario = usuarioFake({ cargo: "coordenador", nome: "Coordenadora Ficticia" });
    renderComApp(<ImportacaoLoteProvider><Layout /></ImportacaoLoteProvider>,
      { usuario, escolas: [escolaFake({ id: 1 })] });
    await screen.findAllByText(usuario.nome);
    expect((await screen.findAllByText("Fim do 4º bimestre em 63 dias")).length).toBeGreaterThan(0);
  });
});
