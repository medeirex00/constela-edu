/**
 * G_VIRADA-3: o par "ficha do ano anterior × ficha nova da turma" (mesmo RA, ou
 * nome e nascimento) aparece no "Fundir duplicatas" para conferir, com o motivo
 * certo — não como "nome contido no nome mais completo".
 */
import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { renderComApp, responder, screen } from "./utils";

test("o par de outro ano vem desmarcado e diz por que foi sugerido", async () => {
  responder("GET", "/escolas/1/alunos/duplicados", {
    total: 1, alta: 0, provavel: 0, revisar: 1,
    candidatos: [
      { loser_id: 40, manter_id: 4, apagar: "Davi Ficticio Lopes", manter: "Davi Ficticio Lopes",
        turma: "4º Ano A", confianca: "revisar", motivo: "outro_ano",
        impacto: { leituras: 0, snapshots_matific: 0, snapshots_elefante: 0, eventos: 0,
                   notas: 0, plataformas: [] },
        recusa: null },
    ],
  });
  renderComApp(<ModalAlunosDuplicados escolaId={1} aoFechar={() => {}} aoConcluir={() => {}} />);

  const aviso = await screen.findByText(/confira:/);
  expect(aviso).toHaveTextContent(
    "mesmo RA ou mesmo nome e nascimento, e uma das fichas não tem turma neste ano");
  expect(aviso).not.toHaveTextContent("nome contido");
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
});
