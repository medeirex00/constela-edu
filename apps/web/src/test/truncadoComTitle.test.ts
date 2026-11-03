/**
 * Trava estática (identidade v2, varredura da D24): texto cortado com reticências (`truncate`) que
 * mostra UM valor dinâmico — nome de aluno, escola, e-mail, título — precisa de `title`
 * com o mesmo valor, senão quem usa a tela no tablet não tem como ler o nome inteiro.
 * A varredura visual achou 48 casos; este teste impede que voltem.
 */
import { describe, expect, it } from "vitest";

const FONTES = import.meta.glob(["../**/*.tsx", "!../test/**", "!../**/publico/**"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const TRUNCADO_COM_UMA_EXPRESSAO =
  /<(span|p|a|dd|dt|Link|h3|h4|div|td|strong|button)(\s[^<>]*?className="[^"]*\btruncate\b[^"]*"[^<>]*?)>\s*\{([^{}<>]+)\}\s*<\/\1>/g;

describe("texto truncado tem title", () => {
  it("a varredura acha os arquivos do app", () => {
    expect(Object.keys(FONTES).length).toBeGreaterThan(50);
  });

  it("todo `truncate` com um valor dinâmico leva title com ESSE valor", () => {
    const faltando: string[] = [];
    for (const [arquivo, texto] of Object.entries(FONTES)) {
      for (const m of texto.matchAll(TRUNCADO_COM_UMA_EXPRESSAO)) {
        const expr = m[3].trim();
        const title = /\btitle=\{([^{}]+)\}/.exec(m[2])?.[1].trim();
        if (title !== expr) {
          const linha = texto.slice(0, m.index).split("\n").length;
          faltando.push(`${arquivo}:${linha} {${expr}} title=${title ?? "(nenhum)"}`);
        }
      }
    }
    expect(faltando).toEqual([]);
  });
});
