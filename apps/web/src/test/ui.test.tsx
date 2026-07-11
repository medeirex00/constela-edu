/**
 * MÉDIO-2 do RC (WCAG 4.1.3): mensagens de erro/sucesso do web precisam ser
 * anunciadas por leitor de tela — antes eram só visuais.
 */
import { Mensagem } from "../components/ui";
import { render, screen } from "./utils";

test("Mensagem de erro é anunciada como alert (assertivo)", () => {
  render(<Mensagem tipo="erro">Não foi possível salvar.</Mensagem>);
  expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível salvar.");
});

test("Mensagem de sucesso é anunciada como status (educado)", () => {
  render(<Mensagem tipo="ok">Salvo com sucesso.</Mensagem>);
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent("Salvo com sucesso.");
  expect(status).toHaveAttribute("aria-live", "polite");
});
