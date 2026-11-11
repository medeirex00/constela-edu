/**
 * Virada do ano letivo (G_VIRADA-1): a Lista Piloto de outro ano não pode ser gravada.
 *
 * A prévia dizia só "EMEF … · 2027" ao lado do nome da escola, e o botão de gravar
 * aplicava a lista de 2027 ao ano letivo 2026 da escola (matrículas movidas, formandos
 * "fora da lista", Notas recalculadas). Agora o backend marca ``ano_divergente`` com o
 * aviso (``aviso_ano``) e recusa o /confirmar com 409; a tela mostra o aviso em destaque
 * e não deixa abrir a confirmação. Planilha sem o ano: segue, com o aviso para conferir.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import ImportacaoMatriculas from "../pages/ImportacaoMatriculas";
import { apiUpload, fireEvent, renderComApp, responder, screen, userEvent } from "./utils";

const URL_ANALISAR = "/escolas/1/importacoes/matriculas/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/matriculas/confirmar";

const AVISO_2027 = "Esta é a Lista Piloto de 2027, e a escola ainda está no ano letivo 2026. "
  + "Nada será gravado: peça ao administrador global para trocar o ano letivo.";
const AVISO_SEM_ANO = "A planilha não diz de que ano é esta Lista Piloto: ao gravar, ela vale "
  + "para o ano letivo 2026 da escola. Confira antes de gravar.";

function analise(over: Record<string, unknown> = {}) {
  return {
    escola_detectada: "EMEF ESCOLA FICTÍCIA",
    ano_letivo: 2027,
    total_turmas: 1,
    total_alunos: 2,
    total_registros: 2,
    alunos_novos: 0,
    alunos_atualizar: 2,
    alunos_em_revisao: 0,
    turmas_existentes: 0,
    turmas: [
      { nome: "5º Ano A", ano_escolar: "5º Ano", turno: "tarde", professor: "", sed: "",
        total_alunos: 2, ja_existe: false, exemplos: ["Aluna Fictícia", "Aluno Fictício"] },
    ],
    avisos: [],
    ano_divergente: true,
    aviso_ano: AVISO_2027,
    ...over,
  };
}

async function previa(dados: unknown) {
  responder("UPLOAD", URL_ANALISAR, dados);
  responder("UPLOAD", URL_CONFIRMAR, {
    mensagem: "ok", turmas_criadas: 0, alunos_criados: 0, alunos_atualizados: 2, avisos: [],
  });
  renderComApp(<ImportacaoMatriculas escolaId={1} aoConcluir={() => undefined} aoAvancar={() => undefined} />);
  const u = userEvent.setup();
  fireEvent.change(screen.getByLabelText("Planilha de matrículas da escola (.xls ou .xlsx)"), {
    target: { files: [new File(["xls"], "lista-piloto.xlsx", { type: "application/vnd.ms-excel" })] },
  });
  await u.click(screen.getByRole("button", { name: "Analisar planilha" }));
  await screen.findByText(/EMEF ESCOLA FICTÍCIA/);
  return u;
}

const chamadasConfirmar = () => apiUpload.mock.calls.filter(([caminho]) => caminho === URL_CONFIRMAR);

describe("Lista Piloto de outro ano", () => {
  it("mostra o aviso em destaque e não deixa gravar", async () => {
    const u = await previa(analise());
    expect(screen.getByRole("alert")).toHaveTextContent(AVISO_2027);
    const gravar = screen.getByRole("button", { name: /Criar turmas e matricular/ });
    expect(gravar).toBeDisabled();
    await u.click(gravar);
    expect(screen.queryByRole("dialog", { name: "Gravar a Lista Piloto?" })).toBeNull();
    expect(chamadasConfirmar()).toHaveLength(0);
    // Trocar de arquivo continua possível.
    expect(screen.getByRole("button", { name: "Escolher outro arquivo" })).toBeEnabled();
  });

  it("planilha sem o ano: o aviso pede para conferir e a gravação segue", async () => {
    const u = await previa(analise({ ano_letivo: null, ano_divergente: false, aviso_ano: AVISO_SEM_ANO }));
    expect(screen.getByText(AVISO_SEM_ANO)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    await u.click(screen.getByRole("button", { name: /Criar turmas e matricular/ }));
    expect(await screen.findByRole("dialog", { name: "Gravar a Lista Piloto?" })).toBeInTheDocument();
  });

  it("lista do ano da escola: nenhum aviso de ano", async () => {
    await previa(analise({ ano_letivo: 2026, ano_divergente: false, aviso_ano: null }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/ano letivo/)).toBeNull();
    expect(screen.getByRole("button", { name: /Criar turmas e matricular/ })).toBeEnabled();
  });
});
