import { describe, expect, it, vi } from "vitest";

import { bimestreDeHoje, participaDePremiacao } from "../pages/Relatorios";

/** O calendário oficial, do lado da tela. As mesmas datas de
 *  `backend/app/services/bimestres.py` — se alguém mexer num lado só, isto cai. */
describe("bimestre que o seletor abre marcado", () => {
  it.each([
    ["2026-02-02", 1],
    ["2026-04-22", 1],
    ["2026-04-23", 2],
    ["2026-07-23", 2],
    ["2026-07-24", 3],
    ["2026-10-04", 3],
    ["2026-10-05", 4],
    ["2026-12-31", 4],
  ])("%s → %iº bimestre", (iso, esperado) => {
    const [a, m, d] = iso.split("-").map(Number);
    expect(bimestreDeHoje(new Date(a, m - 1, d))).toBe(esperado);
  });

  it("01/10/2026 ainda é o 3º — era aqui que o mapa por mês dizia 4", () => {
    expect(bimestreDeHoje(new Date(2026, 9, 1))).toBe(3);
  });

  it("não quebra em ano sem calendário cadastrado", () => {
    expect([1, 2, 3, 4]).toContain(bimestreDeHoje(new Date(2027, 5, 10)));
  });
});

/** Espelho de `backend/app/services/elegibilidade.py`. O backend é quem barra
 *  (409); isto só evita oferecer na tela um nome que não pode ser emitido. */
describe("quem aparece no seletor de certificados", () => {
  it.each(["1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano", "4ºB", "2° Ano", "1 ANO"])(
    "%s concorre", (rotulo) => {
      expect(participaDePremiacao(rotulo)).toBe(true);
    });

  it.each(["1ª Fase", "2ª Fase", "1 FASE A", "EMEI", "Maternal 2", "Pré II", "EJA 3º"])(
    "%s não concorre", (rotulo) => {
      expect(participaDePremiacao(rotulo)).toBe(false);
    });

  it("'4º Ano - Fase 2' concorre: o ANO explícito vence a palavra de etapa", () => {
    expect(participaDePremiacao("4º Ano - Fase 2")).toBe(true);
  });

  it("sem rótulo não dá para afirmar que é fase — não esconde", () => {
    expect(participaDePremiacao(null)).toBe(true);
    expect(participaDePremiacao("")).toBe(true);
  });

  it("6º ano não é Fundamental I", () => {
    expect(participaDePremiacao("6º Ano")).toBe(false);
  });
});
