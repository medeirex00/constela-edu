/**
 * Painel da Rede / Secretaria de Educação (perfil municipal).
 *
 * Visão consolidada de TODAS as escolas da rede + mapa geográfico (Leaflet +
 * OpenStreetMap — sem chave de API, sem enviar dados de criança a terceiros).
 * Só dados AGREGADOS por escola saem do backend; o isolamento por rede é
 * garantido no servidor (`exigir_rede`), esta tela apenas exibe.
 */
import "leaflet/dist/leaflet.css";

import L from "leaflet";
import {
  AlertTriangle,
  Building2,
  FileDown,
  Globe,
  GraduationCap,
  LineChart,
  MapPin,
  Scale,
  Settings2,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { Botao, Card, Carregando, Mensagem, PageHeader, StatCard, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, apiDownload } from "../../lib/api";
import { corPorMedia } from "../../lib/cores";
import { nota, numero } from "../../lib/formato";

interface EscolaCartao {
  escola_id: number;
  nome: string;
  cidade: string | null;
  status: string;
  latitude: number | null;
  longitude: number | null;
  total_turmas: number;
  total_alunos: number;
  alunos_com_dados: number;
  adocao: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  precisa_atencao: boolean;
  motivo_atencao: string | null;
  posicao?: number;
}

interface DashboardRede {
  rede_id: number;
  totais: {
    escolas: number;
    escolas_ativas: number;
    alunos: number;
    turmas: number;
    alunos_com_dados: number;
    adocao: number;
    media_geral: number;
    media_matific: number;
    media_elefante: number;
    escolas_em_atencao: number;
  };
  equidade: {
    gap_media: number;
    escola_maior_media: number;
    escola_menor_media: number;
    escolas_abaixo_da_media: number;
  };
  escolas: EscolaCartao[];
  atencao: EscolaCartao[];
}

function iconeEscola(cartao: EscolaCartao): L.DivIcon {
  const cor = corPorMedia(cartao.media_geral);
  return L.divIcon({
    className: "",
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${cor};
      border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

/** Ajusta o zoom para enquadrar todas as escolas com coordenada. */
function AjustarLimites({ pontos }: { pontos: [number, number][] }) {
  const mapa = useMap();
  useEffect(() => {
    if (pontos.length === 1) mapa.setView(pontos[0], 14);
    else if (pontos.length > 1) mapa.fitBounds(pontos, { padding: [40, 40] });
  }, [mapa, pontos]);
  return null;
}

function MapaRede({ escolas, aoAbrir }: { escolas: EscolaCartao[]; aoAbrir: (id: number) => void }) {
  const comCoord = escolas.filter((e) => e.latitude != null && e.longitude != null);
  const pontos = comCoord.map(
    (e) => [e.latitude as number, e.longitude as number] as [number, number],
  );

  if (comCoord.length === 0) {
    return (
      <Card className="flex h-[420px] flex-col items-center justify-center p-6 text-center">
        <MapPin className="mb-3 h-8 w-8 text-zinc-400" />
        <p className="text-sm font-medium">Nenhuma escola tem localização cadastrada ainda.</p>
        <p className="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
          Assim que as coordenadas (latitude/longitude) forem preenchidas — por geocodificação em
          lote ou manualmente — as escolas aparecem no mapa.
        </p>
      </Card>
    );
  }

  return (
    <div className="h-[420px] overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
      <MapContainer center={pontos[0]} zoom={12} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <AjustarLimites pontos={pontos} />
        {comCoord.map((escola) => (
          <Marker
            key={escola.escola_id}
            position={[escola.latitude as number, escola.longitude as number]}
            icon={iconeEscola(escola)}
          >
            <Popup>
              <div className="space-y-1">
                <p className="text-sm font-semibold">{escola.nome}</p>
                <p className="text-xs text-zinc-500">
                  {escola.total_alunos} alunos · {escola.total_turmas} turmas
                </p>
                <p className="text-xs">
                  Média geral <b>{nota(escola.media_geral)}</b> · adoção {nota(escola.adocao)}%
                </p>
                <button
                  className="mt-1 text-xs font-semibold text-indigo-600 hover:underline"
                  onClick={() => aoAbrir(escola.escola_id)}
                >
                  Abrir escola →
                </button>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}

function LinhaEscola({ escola, aoAbrir }: { escola: EscolaCartao; aoAbrir: (id: number) => void }) {
  return (
    <button
      onClick={() => aoAbrir(escola.escola_id)}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
    >
      <span className="w-6 text-center text-sm font-bold tabular-nums text-zinc-400">{escola.posicao ?? "–"}</span>
      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: corPorMedia(escola.media_geral) }} />
      <span className="flex-1 truncate text-sm font-medium">
        {escola.nome}
        {escola.precisa_atencao && <AlertTriangle size={13} className="ml-1 inline text-amber-500" />}
      </span>
      <span className="hidden text-xs text-zinc-500 sm:block">{escola.total_alunos} al.</span>
      <span className="w-14 text-right text-sm font-bold tabular-nums">{nota(escola.media_geral)}</span>
    </button>
  );
}

function VitrinePublica({ redeId }: { redeId: number }) {
  const { dados, recarregar } = useApi<{ ativo: boolean; token: string | null; url: string | null }>(
    `/redes/${redeId}/publico`);
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);

  async function alternar(ativo: boolean) {
    setOcupado(true);
    try {
      await api(`/redes/${redeId}/publico`, { method: "PUT", body: JSON.stringify({ ativo }) });
      recarregar();
    } finally {
      setOcupado(false);
    }
  }
  async function copiar() {
    if (!dados?.url) return;
    try {
      await navigator.clipboard.writeText(dados.url);
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 1500);
    } catch { /* clipboard indisponível: o link fica visível para copiar à mão */ }
  }

  return (
    <Card className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 text-sm">
      <span className="flex items-center gap-2 font-semibold">
        <Globe size={16} className="text-indigo-600" /> Vitrine pública
      </span>
      {dados?.ativo ? (
        <>
          <span className="text-zinc-500">Link aberto (sem login) com as melhores escolas:</span>
          <code className="rounded bg-zinc-100 px-2 py-1 text-xs dark:bg-zinc-800">{dados.url}</code>
          <Botao variante="neutro" onClick={copiar}>{copiado ? "Copiado!" : "Copiar link"}</Botao>
          <Botao variante="neutro" onClick={() => alternar(false)} disabled={ocupado}>Desligar</Botao>
        </>
      ) : (
        <>
          <span className="text-zinc-500">
            Publique um link aberto com as 5 melhores escolas em leitura e matemática — sem nome de criança.
          </span>
          <Botao onClick={() => alternar(true)} disabled={ocupado}>Ligar vitrine pública</Botao>
        </>
      )}
    </Card>
  );
}

function PainelRede({ redeId }: { redeId: number }) {
  const { usuario, selecionarEscola } = useApp();
  const navegar = useNavigate();
  const { dados, erro, carregando } = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const [filtro, setFiltro] = useState("");
  const [baixando, setBaixando] = useState(false);
  const [boletimErro, setBoletimErro] = useState("");

  async function baixarBoletim() {
    setBaixando(true);
    setBoletimErro("");
    try {
      await apiDownload(`/redes/${redeId}/boletim`);
    } catch (e) {
      setBoletimErro(e instanceof Error ? e.message : "Não foi possível gerar o boletim.");
    } finally {
      setBaixando(false);
    }
  }

  const abrirEscola = (escolaId: number) => {
    selecionarEscola(escolaId); // troca a escola ativa (o backend autoriza: é da rede)
    navegar("/escola"); // Visão da Escola lê a escola ativa do contexto
  };

  const escolasFiltradas = useMemo(() => {
    const q = filtro.trim().toLowerCase();
    const lista = dados?.escolas ?? [];
    return q ? lista.filter((e) => e.nome.toLowerCase().includes(q)) : lista;
  }, [dados, filtro]);

  if (carregando && !dados) return <Carregando texto="Carregando a rede..." />;
  if (erro && !dados) return <Vazio titulo="Não foi possível carregar a rede" descricao={erro.message} />;
  if (!dados) return null;

  const t = dados.totais;
  const eq = dados.equidade;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Secretaria de Educação"
        descricao="Visão consolidada da rede: desempenho, adoção, equidade entre escolas e distribuição geográfica."
        acoes={
          <div className="flex flex-wrap gap-2">
            <Botao variante="neutro" onClick={() => navegar("/rede/avaliacoes")}>
              <LineChart size={15} /> Avaliações externas
            </Botao>
            <Botao variante="neutro" onClick={baixarBoletim} disabled={baixando}>
              <FileDown size={15} /> {baixando ? "Gerando..." : "Baixar boletim (PDF)"}
            </Botao>
            {usuario?.is_global && (
              <Botao variante="neutro" onClick={() => navegar("/rede/gerenciar")}>
                <Settings2 size={15} /> Gerenciar redes
              </Botao>
            )}
          </div>
        }
      />
      {boletimErro && <Mensagem tipo="erro">{boletimErro}</Mensagem>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Building2 size={16} />} rotulo="Escolas" valor={numero(t.escolas)} detalhe={`${t.escolas_ativas} ativas`} />
        <StatCard icone={<Users size={16} />} rotulo="Alunos" valor={numero(t.alunos)} detalhe={`${numero(t.turmas)} turmas`} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Adoção" valor={`${nota(t.adocao)}%`} detalhe="alunos com dados" />
        <StatCard
          icone={<TrendingUp size={16} />}
          rotulo="Média geral"
          valor={nota(t.media_geral)}
          detalhe={`Matific ${nota(t.media_matific)} · Elefante ${nota(t.media_elefante)}`}
        />
      </div>

      {/* Escolas em atenção — a lista de AÇÃO da secretaria (o que priorizar). */}
      {dados.atencao.length > 0 && (
        <Card className="border-amber-200 p-4 dark:border-amber-500/30">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle size={16} className="text-amber-500" /> Escolas que precisam de atenção
            <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
              {dados.atencao.length}
            </span>
          </h2>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {dados.atencao.map((escola) => (
              <li key={escola.escola_id} className="flex items-center gap-3 py-2">
                <button
                  onClick={() => abrirEscola(escola.escola_id)}
                  className="min-w-0 flex-1 text-left text-sm font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                >
                  {escola.nome}
                </button>
                <span className="text-xs text-amber-700 dark:text-amber-400">{escola.motivo_atencao}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Equidade: quão distante está a melhor da pior escola. */}
      <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-sm">
        <span className="flex items-center gap-2 font-semibold">
          <Scale size={16} className="text-indigo-600" /> Equidade da rede
        </span>
        <span className="text-zinc-600 dark:text-zinc-300">
          Diferença entre a melhor e a pior escola:{" "}
          <b className="tabular-nums">{nota(eq.gap_media)}</b> pontos
          <span className="text-zinc-400"> ({nota(eq.escola_menor_media)} → {nota(eq.escola_maior_media)})</span>
        </span>
        <span className="text-zinc-600 dark:text-zinc-300">
          <b className="tabular-nums">{eq.escolas_abaixo_da_media}</b> escola(s) abaixo da média da rede
        </span>
      </Card>

      <VitrinePublica redeId={redeId} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <MapPin size={16} className="text-indigo-600" /> Distribuição geográfica
          </h2>
          <MapaRede escolas={escolasFiltradas} aoAbrir={abrirEscola} />
        </div>

        <Card className="flex flex-col p-4">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Trophy size={16} className="text-amber-500" /> Ranking das escolas
          </h2>
          <input
            className="mb-2 w-full rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            placeholder="Filtrar escola..."
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
          />
          <div className="-mx-1 max-h-[340px] flex-1 space-y-0.5 overflow-y-auto">
            {escolasFiltradas.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-zinc-500">Nenhuma escola.</p>
            ) : (
              escolasFiltradas.map((escola) => (
                <LinhaEscola key={escola.escola_id} escola={escola} aoAbrir={abrirEscola} />
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function RedeDashboard() {
  const { usuario } = useApp();
  const navegar = useNavigate();
  // Usuário de rede → sua rede. Admin global sem rede definida → usa a 1ª rede
  // que ele puder ver (o backend já escopa /redes).
  const redeDoUsuario = usuario?.rede_id ?? null;
  const { dados: redes, carregando } = useApi<{ id: number; nome: string }[]>(
    redeDoUsuario == null ? "/redes" : null,
  );
  const redeId = redeDoUsuario ?? redes?.[0]?.id ?? null;

  if (redeId == null) {
    if (carregando) return <Carregando texto="Carregando as redes..." />;
    // Admin global sem nenhuma rede: oferece criar a primeira (bootstrap).
    return (
      <div className="space-y-4">
        <Vazio
          titulo="Nenhuma rede disponível"
          descricao={usuario?.is_global
            ? "Ainda não há redes cadastradas. Crie a primeira para habilitar o painel da Secretaria."
            : "Sua conta não está vinculada a uma rede/Secretaria."}
        />
        {usuario?.is_global && (
          <div className="flex justify-center">
            <Botao onClick={() => navegar("/rede/gerenciar")}>
              <Settings2 size={15} /> Gerenciar redes
            </Botao>
          </div>
        )}
      </div>
    );
  }
  return <PainelRede redeId={redeId} />;
}
