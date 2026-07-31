import { describe, expect, it } from "vitest";

import { usePerfil } from "../hooks/usePerfil";
import { renderComApp, screen, usuarioFake } from "./utils";

/** Sonda: expõe os flags do usePerfil como texto para asserção. */
function Sonda() {
  const p = usePerfil();
  return (
    <div>
      {`global:${p.global} secretaria:${p.secretaria} rede:${p.rede} gestor:${p.gestor} escolaOnly:${p.escolaOnly}`}
    </div>
  );
}

describe("usePerfil (fonte única de decisão de papel)", () => {
  it("coordenador de escola (sem rede): gestor + escolaOnly", async () => {
    renderComApp(<Sonda />); // usuarioFake padrão = coordenador de escola
    expect(await screen.findByText(
      "global:false secretaria:false rede:false gestor:true escolaOnly:true",
    )).toBeInTheDocument();
  });

  it("professor: nem gestor; opera só a escola", async () => {
    renderComApp(<Sonda />, { usuario: usuarioFake({ cargo: "professor" }) });
    expect(await screen.findByText(
      "global:false secretaria:false rede:false gestor:false escolaOnly:true",
    )).toBeInTheDocument();
  });

  it("Secretaria (rede_id, não global): secretaria + rede, não escolaOnly", async () => {
    renderComApp(<Sonda />, { usuario: usuarioFake({ rede_id: 7 }) });
    expect(await screen.findByText(
      "global:false secretaria:true rede:true gestor:true escolaOnly:false",
    )).toBeInTheDocument();
  });

  it("Admin Global: global + rede (alcança /rede), não secretaria", async () => {
    renderComApp(<Sonda />, { usuario: usuarioFake({ is_global: true }) });
    expect(await screen.findByText(
      "global:true secretaria:false rede:true gestor:true escolaOnly:false",
    )).toBeInTheDocument();
  });
});
