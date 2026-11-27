import "leaflet/dist/leaflet.css";

import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";
import { geoJSON, type PathOptions } from "leaflet";
import { Maximize } from "lucide-react";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";

import { Botao } from "../../../components/ui";
import contornos from "./dados/caraguatatuba-demo.geo.json";
import { FAIXAS, faixaDemo, totalizarDemo, type EscolaDemo, type RegiaoId } from "./dadosDemoCaragua";

const areas = contornos as FeatureCollection<Polygon | MultiPolygon, { id: RegiaoId; nome: string }>;
const municipio = geoJSON(areas).getBounds();
const enquadramento = { padding: [28, 28] as [number, number] };

function VisaoMunicipal() {
  const mapa = useMap();
  return (
    <div className="absolute bottom-3 right-3 z-[500]">
      <Botao type="button" variante="secundario" tamanho="sm" onClick={() => mapa.fitBounds(municipio, enquadramento)}>
        <Maximize size={14} aria-hidden /> Ver município inteiro
      </Botao>
    </div>
  );
}

export default function MapaDemoCaragua({ escolas, regiao, escola, escolherRegiao, escolherEscola }: {
  escolas: EscolaDemo[];
  regiao: RegiaoId | null;
  escola: string | null;
  escolherRegiao: (id: RegiaoId) => void;
  escolherEscola: (id: string) => void;
}) {
  return (
    <figure className="min-w-0 overflow-hidden rounded-2xl border border-zinc-200 dark:border-zinc-700">
      <div role="region" aria-label="Mapa interativo de Caraguatatuba">
        <MapContainer
          bounds={municipio}
          boundsOptions={enquadramento}
          scrollWheelZoom={false}
          className="isolate h-[23rem] w-full !bg-sky-100 sm:h-[29rem] lg:h-[34rem] dark:!bg-slate-900"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            className="dark:brightness-[.58] dark:saturate-50"
          />
          <GeoJSON
            data={areas}
            style={(feature): PathOptions => {
              const id = feature?.properties.id;
              const selecionada = regiao === id;
              const nota = totalizarDemo(escolas.filter((item) => item.regiao === id)).nota;
              return {
                fillColor: faixaDemo(nota).cor,
                fillOpacity: selecionada ? 0.96 : 0.87,
                color: selecionada ? "#f8fafc" : "#253348",
                weight: selecionada ? 2 : 1,
              };
            }}
            onEachFeature={(feature, layer) => {
              const id = feature.properties.id;
              layer.bindTooltip(feature.properties.nome);
              layer.on("click", () => escolherRegiao(id));
            }}
          />
          {escolas.map((item) => (
            <CircleMarker
              key={item.id}
              center={[item.latitude, item.longitude]}
              radius={escola === item.id ? 9 : 6}
              pathOptions={{
                color: escola === item.id ? "#f8fafc" : "#172235",
                fillColor: "#f8fafc",
                fillOpacity: 1,
                weight: escola === item.id ? 3 : 2,
                bubblingMouseEvents: false,
              }}
              eventHandlers={{ click: () => escolherEscola(item.id) }}
            >
              <Tooltip direction="top" offset={[0, -8]}>{item.nome}</Tooltip>
            </CircleMarker>
          ))}
          <VisaoMunicipal />
        </MapContainer>
      </div>
      <figcaption className="space-y-2 p-3 text-xs text-zinc-600 sm:p-4 dark:text-zinc-300">
        <ul aria-label="Faixas de desempenho da simulação" className="flex flex-wrap gap-x-4 gap-y-2">
          {FAIXAS.map(({ cor, rotulo, criterio }) => (
            <li key={rotulo} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: cor }} />
              {rotulo}{criterio && <span className="font-semibold tabular-nums">({criterio})</span>}
            </li>
          ))}
        </ul>
        <p>Contorno municipal da Malha Municipal do IBGE. Recortes e escolas da simulação.</p>
      </figcaption>
    </figure>
  );
}
