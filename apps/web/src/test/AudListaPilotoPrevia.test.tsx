/**
 * Auditoria (Lista Piloto): a prévia e o modal "Gravar a Lista Piloto?" dizem quantas
 * linhas ficam em revisão.
 *
 * IMPORTACAO-10: com "ANA BEATRIZ SOUZA LIMA" (a ficha é "Ana Beatriz Souza") e uma
 * criança que mudou de sala, o modal prometia "N aluno(s) novo(s) matriculado(s)" e a
 * confirmação não cadastrava esses dois: mandava para revisão. O backend passou a
 * contar como a confirmação (``alunos_em_revisao``); a tela não mostrava esse número.
 *
 * As respostas são as REAIS, gravadas por backend/tests/test_aud_impweb_lista_piloto.py.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import ImportacaoMatriculas from "../pages/ImportacaoMatriculas";
import analiseReal from "./fixtures/importacoes/previa_da_tela/lista_piloto_analise.json";
import confirmarReal from "./fixtures/importacoes/previa_da_tela/lista_piloto_confirmar.json";
import { fireEvent, renderComApp, responder, screen, userEvent, within } from "./utils";

const URL_ANALISAR = "/escolas/1/importacoes/matriculas/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/matriculas/confirmar";

const copia = (valor: unknown) => JSON.parse(JSON.stringify(valor));

async function previa(analise: unknown) {
  responder("UPLOAD", URL_ANALISAR, copia(analise));
  responder("UPLOAD", URL_CONFIRMAR, copia(confirmarReal));
  renderComApp(<ImportacaoMatriculas escolaId={1} aoConcluir={() => undefined} aoAvancar={() => undefined} />);
  const u = userEvent.setup();
  fireEvent.change(screen.getByLabelText("Planilha de matrículas da escola (.xls ou .xlsx)"), {
    target: { files: [new File(["xls"], "lista-piloto.xlsx", { type: "application/vnd.ms-excel" })] },
  });
  await u.click(screen.getByRole("button", { name: "Analisar planilha" }));
  await screen.findByText(/EMEF TESTE/);
  return u;
}

const EM_REVISAO_MODAL = "2 linha(s) ficam para revisão: parecem alunos já cadastrados, mas a "
  + "correspondência não é segura — nada é criado nem alterado nelas";

describe("Lista Piloto — linhas que ficam em revisão", () => {
  it("a prévia e o modal mostram novos, a atualizar e em revisão como a confirmação", async () => {
    expect([analiseReal.alunos_novos, analiseReal.alunos_atualizar, analiseReal.alunos_em_revisao])
      .toEqual([1, 0, 2]);
    const u = await previa(analiseReal);

    expect(screen.getByText("aluno(s) novo(s)").previousSibling).toHaveTextContent("1");
    expect(screen.getByText("a atualizar").previousSibling).toHaveTextContent("0");
    expect(screen.getByText("em revisão").previousSibling).toHaveTextContent("2");

    await u.click(screen.getByRole("button", { name: /Criar turmas e matricular/ }));
    const dialogo = await screen.findByRole("dialog", { name: "Gravar a Lista Piloto?" });
    expect(dialogo).toHaveTextContent("1 aluno(s) novo(s) matriculado(s)");
    expect(dialogo).toHaveTextContent(EM_REVISAO_MODAL);

    await u.click(within(dialogo).getByRole("button", { name: "Gravar matrículas" }));
    // O resultado da confirmação real: 1 cadastrado e 2 em revisão, com os avisos.
    expect(await screen.findByText("2 em revisão")).toBeInTheDocument();
    expect(screen.getByText("1 aluno(s) novo(s)")).toBeInTheDocument();
  });

  it("sem linha em revisão, nada de 'em revisão' na prévia nem no modal", async () => {
    const u = await previa({ ...copia(analiseReal), alunos_em_revisao: 0 });
    expect(screen.queryByText("em revisão")).toBeNull();
    await u.click(screen.getByRole("button", { name: /Criar turmas e matricular/ }));
    const dialogo = await screen.findByRole("dialog", { name: "Gravar a Lista Piloto?" });
    expect(dialogo).not.toHaveTextContent("ficam para revisão");
  });
});
