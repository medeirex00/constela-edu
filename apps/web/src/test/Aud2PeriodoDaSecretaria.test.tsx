/**
 * G_GRUPO-2 (auditoria, fase C): o PERÍODO das telas da Secretaria é o ano letivo ou um bimestre
 * inteiro. Com o personalizado (ou o dia, a semana, o mês), dois períodos sobrepostos davam, pela
 * diferença, as estrelas, o desempenho e o nível de leitura de UMA criança que um deles escondia;
 * o servidor passou a recusar esses períodos à Secretaria (422) e a tela não os oferece mais. Um
 * link antigo (`?periodo=mes`) abre no ano letivo. O admin global continua com todos.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import { PRESETS_DA_REDE, periodoDaRede, presetsDoPeriodo } from "../pages/analise/comum";
import { renderEscolas, semearEscolas } from "./EscolasRedeFixtures";
import { admin, chamadas, consulta } from "./SecretariaFixtures";
import { screen, within } from "./utils";

const DA_SECRETARIA = ["bimestre", "bimestre_anterior", "bimestre_1", "bimestre_2", "bimestre_3", "bimestre_4",
                       "ano_letivo"];

describe("Período da Secretaria — só o ano letivo ou um bimestre inteiro", () => {
  it("as opções da Secretaria são as de PRESETS_DA_REDE; as do global, todas", () => {
    expect(presetsDoPeriodo(true).map((p) => p.valor)).toEqual(DA_SECRETARIA);
    expect([...PRESETS_DA_REDE].sort()).toEqual([...DA_SECRETARIA].sort());
    expect(presetsDoPeriodo(false).map((p) => p.valor)).toContain("personalizado");
    expect(periodoDaRede({ preset: "mes" }, true)).toEqual({ preset: "ano_letivo" });
    expect(periodoDaRede({ preset: "personalizado", inicio: "2026-03-01", fim: "2026-08-15" }, true))
      .toEqual({ preset: "ano_letivo" });
    expect(periodoDaRede({ preset: "bimestre_3" }, true)).toEqual({ preset: "bimestre_3" });
    expect(periodoDaRede({ preset: "mes" }, false)).toEqual({ preset: "mes" });
  });

  it("a tela Escolas não oferece personalizado, dia, semana nem mês à Secretaria", async () => {
    semearEscolas();
    renderEscolas("/rede/escolas");
    await screen.findByTestId("tabela-escolas-periodo");
    const opcoes = within(screen.getByLabelText("Período")).getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(opcoes).toEqual(DA_SECRETARIA);
    expect(screen.queryByLabelText("Data inicial")).toBeNull();
  });

  it("o link antigo com período personalizado abre no ano letivo (e é o que se pede ao servidor)", async () => {
    semearEscolas();
    renderEscolas("/rede/escolas?periodo=personalizado&inicio=2026-03-01&fim=2026-08-15");
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByLabelText("Período")).toHaveValue("ano_letivo");
    const pedidos = chamadas("/redes/1/analise/plataformas");
    expect(pedidos.length).toBeGreaterThan(0);
    expect(pedidos.every((c) => consulta(c).get("periodo") === "ano_letivo" && !consulta(c).has("inicio")))
      .toBe(true);
  });

  it("o admin global continua com o personalizado na mesma tela", async () => {
    semearEscolas();
    renderEscolas("/rede/escolas?periodo=personalizado&inicio=2026-03-01&fim=2026-08-15", { usuario: admin });
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByLabelText("Período")).toHaveValue("personalizado");
    expect(chamadas("/redes/1/analise/plataformas")
      .some((c) => consulta(c).get("periodo") === "personalizado" && consulta(c).get("inicio") === "2026-03-01"))
      .toBe(true);
  });
});
