/**
 * Gestão de REDES (administrador GLOBAL) — provisiona o tier Secretaria:
 *   1. cria/renomeia uma rede;
 *   2. escolhe QUAIS escolas entram nela (e onde ficam no mapa: lat/long);
 *   3. designa QUEM é a Secretaria (usuários que recebem o escopo da rede).
 *
 * Sem isto, a rede só existia por seed. A segurança real é no backend
 * (todas as rotas exigem admin global); esta tela é só a interface.
 */
import { Landmark, LocateFixed, MapPin, Plus, ScanLine, Save, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
  estiloInput,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { ApiError, api, apiUpload } from "../../lib/api";

interface RedeItem {
  id: number;
  nome: string;
  uf: string | null;
  codigo_ibge: string | null;
  status: string;
}
interface EscolaItem {
  id: number;
  nome: string;
  cidade: string | null;
  estado: string | null;
  status: string;
  rede_id: number | null;
  latitude: number | null;
  longitude: number | null;
  codigo_inep: string | null;
}
interface PropostaInep {
  escola_id: number;
  inep: string | null;
  nome_oficial: string | null;
  municipio_oficial: string | null;
  ja_tem: string | null;
  valor: number | null;
  confianca: "alta" | "revisar" | "nenhum";
}
interface UsuarioItem {
  id: number;
  nome: string;
  email: string;
  cargo: string;
  is_global: boolean;
  escola_id: number | null;
  rede_id: number | null;
}
interface Gerenciar {
  redes: RedeItem[];
  escolas: EscolaItem[];
  usuarios: UsuarioItem[];
}

type Aviso = { tipo: "ok" | "erro"; texto: string } | null;

export default function RedeGestao() {
  const { usuario, recarregarEscolas } = useApp();
  const { dados, erro, carregando, recarregar } = useApi<Gerenciar>("/redes/gerenciar");

  const [redeSel, setRedeSel] = useState<number | null>(null);
  const [aviso, setAviso] = useState<Aviso>(null);
  const [ocupado, setOcupado] = useState(false);

  // Nova rede
  const [novaAberta, setNovaAberta] = useState(false);
  const [nome, setNome] = useState("");
  const [uf, setUf] = useState("");

  // Seleções editáveis da rede escolhida
  const [escolasSel, setEscolasSel] = useState<Set<number>>(new Set());
  const [usuariosSel, setUsuariosSel] = useState<Set<number>>(new Set());
  const [coords, setCoords] = useState<Record<number, { cidade: string; uf: string; lat: string; lng: string }>>({});
  // Códigos INEP (editável) + as propostas do casamento automático (para conferência).
  const [inep, setInep] = useState<Record<number, string>>({});
  const [propostas, setPropostas] = useState<Record<number, PropostaInep>>({});
  // Rede já carregada no estado de INEP: só reseto os códigos/propostas quando a
  // rede REALMENTE muda — um refetch da mesma rede (salvar local, geocodificar)
  // não pode apagar o casamento em revisão ainda não salvo.
  const redeCarregadaInep = useRef<number | null>(null);

  // Ao carregar (ou trocar de rede), assume a primeira e sincroniza as seleções.
  useEffect(() => {
    if (dados && redeSel === null && dados.redes.length > 0) {
      setRedeSel(dados.redes[0].id);
    }
  }, [dados, redeSel]);

  useEffect(() => {
    if (!dados || redeSel === null) return;
    setEscolasSel(new Set(dados.escolas.filter((e) => e.rede_id === redeSel).map((e) => e.id)));
    setUsuariosSel(new Set(dados.usuarios.filter((u) => u.rede_id === redeSel).map((u) => u.id)));
    setCoords(Object.fromEntries(
      dados.escolas
        .filter((e) => e.rede_id === redeSel)
        .map((e) => [e.id, {
          cidade: e.cidade ?? "",
          uf: e.estado ?? "",
          lat: e.latitude != null ? String(e.latitude) : "",
          lng: e.longitude != null ? String(e.longitude) : "",
        }]),
    ));
    // Só (re)semeia os códigos INEP e zera as propostas quando a rede MUDA — não
    // em refetch da mesma rede (senão apagaria o casamento em revisão não salvo).
    if (redeCarregadaInep.current !== redeSel) {
      redeCarregadaInep.current = redeSel;
      setInep(Object.fromEntries(
        dados.escolas
          .filter((e) => e.rede_id === redeSel)
          .map((e) => [e.id, e.codigo_inep ?? ""]),
      ));
      setPropostas({});
    }
  }, [dados, redeSel]);

  const redeAtual = useMemo(
    () => dados?.redes.find((r) => r.id === redeSel) ?? null,
    [dados, redeSel],
  );

  if (!usuario?.is_global) {
    return <Vazio titulo="Somente o administrador global"
                  descricao="A gestão de redes é exclusiva da conta global." />;
  }
  if (carregando && !dados) return <Carregando texto="Carregando as redes..." />;
  if (erro && !dados) return <Vazio titulo="Não foi possível carregar" descricao={erro.message} />;

  function alternar(conjunto: Set<number>, id: number): Set<number> {
    const proximo = new Set(conjunto);
    if (proximo.has(id)) proximo.delete(id);
    else proximo.add(id);
    return proximo;
  }

  async function criarRede() {
    if (nome.trim().length < 2) return;
    setOcupado(true);
    try {
      const criada = await api<RedeItem>("/redes", {
        method: "POST",
        body: JSON.stringify({ nome: nome.trim(), uf: uf.trim() || null }),
      });
      setAviso({ tipo: "ok", texto: `Rede “${criada.nome}” criada.` });
      setNovaAberta(false);
      setNome("");
      setUf("");
      recarregar();
      setRedeSel(criada.id);
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível criar." });
    } finally {
      setOcupado(false);
    }
  }

  async function salvarEscolas() {
    if (redeSel === null) return;
    setOcupado(true);
    try {
      await api(`/redes/${redeSel}/escolas`, {
        method: "PUT",
        body: JSON.stringify({ escola_ids: [...escolasSel] }),
      });
      setAviso({ tipo: "ok", texto: "Escolas da rede atualizadas." });
      recarregar();
      recarregarEscolas?.();
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
    } finally {
      setOcupado(false);
    }
  }

  async function salvarUsuarios() {
    if (redeSel === null) return;
    setOcupado(true);
    try {
      await api(`/redes/${redeSel}/usuarios`, {
        method: "PUT",
        body: JSON.stringify({ usuario_ids: [...usuariosSel] }),
      });
      setAviso({ tipo: "ok", texto: "Secretaria da rede atualizada." });
      recarregar();
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
    } finally {
      setOcupado(false);
    }
  }

  async function salvarLocalizacoes() {
    if (!dados || redeSel === null) return;
    setOcupado(true);
    let ok = 0;
    let falhas = 0;
    const naRede = dados.escolas.filter((e) => e.rede_id === redeSel);
    for (const escola of naRede) {
      const c = coords[escola.id];
      if (!c) continue;
      const corpo: Record<string, unknown> = {};
      if (c.cidade.trim()) corpo.cidade = c.cidade.trim();
      if (c.uf.trim()) corpo.estado = c.uf.trim().toUpperCase();
      if (c.lat.trim() !== "" && c.lng.trim() !== "") {
        const lat = Number(c.lat.replace(",", "."));
        const lng = Number(c.lng.replace(",", "."));
        if (Number.isNaN(lat) || Number.isNaN(lng)) { falhas += 1; continue; }
        corpo.latitude = lat;
        corpo.longitude = lng;
      }
      if (Object.keys(corpo).length === 0) continue;
      try {
        await api(`/redes/escolas/${escola.id}`, {
          method: "PATCH",
          body: JSON.stringify(corpo),
        });
        ok += 1;
      } catch {
        falhas += 1;
      }
    }
    setAviso({
      tipo: falhas ? "erro" : "ok",
      texto: `${ok} escola(s) salva(s)` + (falhas ? `; ${falhas} com erro.` : "."),
    });
    recarregar();
    setOcupado(false);
  }

  async function geocodificar() {
    if (redeSel === null) return;
    setOcupado(true);
    let encontradas = 0;
    let processadas = 0;
    let depoisDe = 0; // cursor de id: avança lote a lote, sem reprocessar falhas
    try {
      // O backend processa em LOTES (rate-limit do OSM ~1s/escola); chamamos em
      // sequência avançando o cursor `depois_de` até esgotar. `passo` é só um
      // limite de segurança (o cursor garante que cada escola é vista uma vez).
      for (let passo = 0; passo < 500; passo++) {
        const r = await api<{ processadas: number; encontradas: number; falhas: number; restantes: number; ultimo_id: number }>(
          `/redes/${redeSel}/geocodificar?depois_de=${depoisDe}`, { method: "POST" });
        encontradas += r.encontradas;
        processadas += r.processadas;
        depoisDe = r.ultimo_id;
        setAviso({ tipo: "ok", texto: `Geocodificando... ${encontradas} escola(s) localizada(s)` });
        if (r.restantes <= 0 || r.processadas === 0) break;
      }
      setAviso({
        tipo: encontradas ? "ok" : "erro",
        texto: processadas === 0
          ? "Todas as escolas já têm coordenada."
          : `Geocodificação concluída: ${encontradas} de ${processadas} localizada(s)`
            + (encontradas < processadas ? " — as demais podem ser ajustadas à mão." : "."),
      });
      recarregar();
      recarregarEscolas?.();
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível geocodificar." });
    } finally {
      setOcupado(false);
    }
  }

  async function preencherInep(f: File) {
    if (redeSel === null) return;
    setOcupado(true); setAviso(null);
    try {
      const fd = new FormData(); fd.append("arquivo", f);
      const r = await apiUpload<{
        propostas: PropostaInep[]; total: number; casadas: number;
        revisar: number; sem_correspondencia: number;
      }>(`/redes/${redeSel}/casar-inep`, fd);
      // Só preenche o campo de quem AINDA NÃO tem código — nunca sobrescreve um
      // INEP já verificado com um palpite. As propostas aparecem para conferência
      // em TODAS (os badges), mas o valor editável do que já tem fica intacto.
      setInep((m) => {
        const novo = { ...m };
        for (const p of r.propostas) if (p.inep && !p.ja_tem) novo[p.escola_id] = p.inep;
        return novo;
      });
      setPropostas(Object.fromEntries(r.propostas.map((p) => [p.escola_id, p])));
      setAviso({
        tipo: r.casadas > 0 ? "ok" : "erro",
        texto: `${r.casadas} casada(s) com alta confiança · ${r.revisar} para revisar · `
          + `${r.sem_correspondencia} sem correspondência. Confira e clique em Salvar códigos.`,
      });
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível casar os códigos." });
    } finally {
      setOcupado(false);
    }
  }

  async function salvarInep() {
    if (!dados || redeSel === null) return;
    setOcupado(true);
    let ok = 0;
    let falhas = 0;
    for (const e of dados.escolas.filter((x) => x.rede_id === redeSel)) {
      const valor = (inep[e.id] ?? "").trim();
      if (valor === (e.codigo_inep ?? "")) continue; // nada mudou
      try {
        await api(`/redes/escolas/${e.id}`, {
          method: "PATCH", body: JSON.stringify({ codigo_inep: valor }),
        });
        ok += 1;
      } catch {
        falhas += 1;
      }
    }
    setAviso({
      tipo: falhas ? "erro" : "ok",
      texto: `${ok} código(s) salvo(s)` + (falhas ? `; ${falhas} com erro.` : "."),
    });
    recarregar();
    setOcupado(false);
  }

  const escolas = dados?.escolas ?? [];
  const usuarios = dados?.usuarios ?? [];
  const escolasNaRede = escolas.filter((e) => e.rede_id === redeSel);

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Gestão de redes"
        descricao="Crie uma rede (Secretaria), escolha as escolas que entram nela e quem terá o acesso da Secretaria."
        acoes={
          <Botao onClick={() => { setNome(""); setUf(""); setNovaAberta(true); }}>
            <Plus size={15} /> Nova rede
          </Botao>
        }
      />

      {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}

      {dados && dados.redes.length === 0 ? (
        <Vazio titulo="Nenhuma rede ainda"
               descricao="Crie a primeira rede para habilitar o painel da Secretaria." />
      ) : (
        <>
          {/* Seletor de rede */}
          <Card className="flex flex-wrap items-center gap-2 p-3">
            <span className="flex items-center gap-1.5 text-sm font-medium text-zinc-500">
              <Landmark size={15} /> Rede:
            </span>
            {dados?.redes.map((r) => (
              <button
                key={r.id}
                onClick={() => setRedeSel(r.id)}
                className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                  r.id === redeSel
                    ? "bg-indigo-600 text-white"
                    : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                }`}
              >
                {r.nome}{r.status !== "ativa" ? " (inativa)" : ""}
              </button>
            ))}
          </Card>

          {redeAtual && (
            <div className="grid gap-6 lg:grid-cols-2">
              {/* --- Escolas da rede --- */}
              <Card className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="flex items-center gap-2 text-sm font-semibold">
                    <Landmark size={16} className="text-indigo-600" /> Escolas da rede
                  </h2>
                  <Botao onClick={salvarEscolas} disabled={ocupado}>
                    <Save size={14} /> Salvar vínculos
                  </Botao>
                </div>
                <p className="mb-2 text-xs text-zinc-500">
                  Marque as escolas que pertencem a <b>{redeAtual.nome}</b>. Desmarcar remove o
                  vínculo; marcar uma que esteja em outra rede a transfere para esta.
                </p>
                <ul className="max-h-80 space-y-0.5 overflow-y-auto">
                  {escolas.map((e) => {
                    const emOutraRede = e.rede_id != null && e.rede_id !== redeSel;
                    return (
                      <li key={e.id}>
                        <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-zinc-300 text-indigo-600"
                            checked={escolasSel.has(e.id)}
                            onChange={() => setEscolasSel((s) => alternar(s, e.id))}
                          />
                          <span className="flex-1 truncate text-sm">{e.nome}</span>
                          {e.status !== "ativa" && <Badge tom="neutro">inativa</Badge>}
                          {emOutraRede && <Badge tom="alerta">em outra rede</Badge>}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </Card>

              {/* --- Secretaria (usuários) --- */}
              <Card className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="flex items-center gap-2 text-sm font-semibold">
                    <Users size={16} className="text-indigo-600" /> Acesso da Secretaria
                  </h2>
                  <Botao onClick={salvarUsuarios} disabled={ocupado}>
                    <Save size={14} /> Salvar acessos
                  </Botao>
                </div>
                <p className="mb-2 text-xs text-zinc-500">
                  Quem for marcado passa a enxergar o painel desta rede (e só dela). O admin
                  global já vê todas as redes.
                </p>
                <ul className="max-h-80 space-y-0.5 overflow-y-auto">
                  {usuarios.filter((u) => !u.is_global).map((u) => (
                    <li key={u.id}>
                      <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-zinc-300 text-indigo-600"
                          checked={usuariosSel.has(u.id)}
                          onChange={() => setUsuariosSel((s) => alternar(s, u.id))}
                        />
                        <span className="flex-1 truncate text-sm">
                          {u.nome} <span className="text-zinc-400">· {u.email}</span>
                        </span>
                        <Badge tom="neutro">{u.cargo}</Badge>
                      </label>
                    </li>
                  ))}
                </ul>
              </Card>

              {/* --- Localização no mapa --- */}
              <Card className="p-4 lg:col-span-2">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="flex items-center gap-2 text-sm font-semibold">
                    <MapPin size={16} className="text-indigo-600" /> Localização no mapa
                  </h2>
                  <div className="flex flex-wrap gap-2">
                    <Botao variante="neutro" onClick={geocodificar} disabled={ocupado || escolasNaRede.length === 0}>
                      <LocateFixed size={14} /> Geocodificar automaticamente
                    </Botao>
                    <Botao onClick={salvarLocalizacoes} disabled={ocupado || escolasNaRede.length === 0}>
                      <Save size={14} /> Salvar localizações
                    </Botao>
                  </div>
                </div>
                <p className="mb-2 text-xs text-zinc-500">
                  Preencha ao menos a <b>cidade</b> e clique em <b>Geocodificar</b> — o sistema
                  busca as coordenadas no OpenStreetMap e posiciona os marcadores do mapa. Você
                  também pode informar latitude/longitude à mão (corrige o que não for localizado).
                  Salve os vínculos das escolas antes de posicionar.
                </p>
                {escolasNaRede.length === 0 ? (
                  <p className="py-4 text-center text-sm text-zinc-500">
                    Nenhuma escola vinculada ainda.
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {escolasNaRede.map((e) => {
                      const c = coords[e.id] ?? { cidade: "", uf: "", lat: "", lng: "" };
                      return (
                        <div key={e.id} className="flex flex-wrap items-center gap-2">
                          <span className="w-40 truncate text-sm font-medium">{e.nome}</span>
                          <input
                            className={`${estiloInput} w-40`}
                            placeholder="cidade"
                            value={c.cidade}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, cidade: ev.target.value } }))}
                          />
                          <input
                            className={`${estiloInput} w-14`}
                            placeholder="UF"
                            maxLength={2}
                            value={c.uf}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, uf: ev.target.value.toUpperCase() } }))}
                          />
                          <input
                            className={`${estiloInput} w-28`}
                            placeholder="latitude"
                            inputMode="decimal"
                            value={c.lat}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, lat: ev.target.value } }))}
                          />
                          <input
                            className={`${estiloInput} w-28`}
                            placeholder="longitude"
                            inputMode="decimal"
                            value={c.lng}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, lng: ev.target.value } }))}
                          />
                          {e.latitude != null && (
                            <Badge tom="ok">no mapa</Badge>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>

              {/* --- Códigos INEP (para casar avaliações oficiais) --- */}
              <Card className="p-4 lg:col-span-2">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="flex items-center gap-2 text-sm font-semibold">
                    <ScanLine size={16} className="text-indigo-600" /> Códigos INEP das escolas
                  </h2>
                  <div className="flex flex-wrap gap-2">
                    <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3.5 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800 ${ocupado || escolasNaRede.length === 0 ? "pointer-events-none opacity-50" : ""}`}>
                      <ScanLine size={14} /> Preencher automaticamente
                      <input type="file" accept=".xlsx,.xls,.csv,.zip" className="hidden"
                             onChange={(ev) => { const f = ev.target.files?.[0]; if (f) preencherInep(f); ev.target.value = ""; }} />
                    </label>
                    <Botao onClick={salvarInep} disabled={ocupado || escolasNaRede.length === 0}>
                      <Save size={14} /> Salvar códigos
                    </Botao>
                  </div>
                </div>
                <p className="mb-2 text-xs text-zinc-500">
                  O código INEP casa cada escola com as avaliações oficiais (IDEB, SAEB). Clique em{" "}
                  <b>Preencher automaticamente</b> e suba o arquivo oficial do INEP — o sistema casa
                  suas escolas <b>pelo nome</b>, dentro do município (preencha a cidade antes). Confira
                  as marcadas para <b>revisar</b> e clique em <b>Salvar códigos</b>.
                </p>
                {escolasNaRede.length === 0 ? (
                  <p className="py-4 text-center text-sm text-zinc-500">
                    Nenhuma escola vinculada ainda.
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {escolasNaRede.map((e) => {
                      const p = propostas[e.id];
                      return (
                        <div key={e.id} className="flex flex-wrap items-center gap-2">
                          <span className="w-40 truncate text-sm font-medium">{e.nome}</span>
                          <input
                            className={`${estiloInput} w-32`}
                            placeholder="código INEP"
                            inputMode="numeric"
                            value={inep[e.id] ?? ""}
                            onChange={(ev) => setInep((m) => ({ ...m, [e.id]: ev.target.value }))}
                          />
                          {p && p.confianca !== "nenhum" && (() => {
                            // Município oficial ≠ cidade da escola (casou fora da cidade)
                            // é o sinal para o gestor rejeitar homônima de outra cidade.
                            const foraDaCidade = Boolean(
                              p.municipio_oficial && e.cidade &&
                              p.municipio_oficial.trim().toLowerCase() !== e.cidade.trim().toLowerCase());
                            return (
                              <>
                                <Badge tom={p.confianca === "alta" ? "ok" : "alerta"}>
                                  {p.confianca === "alta" ? "casou" : "revisar"}
                                </Badge>
                                <span className="max-w-[320px] truncate text-xs text-zinc-500" title={p.nome_oficial ?? ""}>
                                  {p.nome_oficial}{p.valor != null ? ` · IDEB ${p.valor}` : ""}
                                  {p.municipio_oficial ? ` · ${p.municipio_oficial}` : ""}
                                </span>
                                {foraDaCidade && (
                                  <Badge tom="alerta">outra cidade!</Badge>
                                )}
                              </>
                            );
                          })()}
                          {p && p.confianca === "nenhum" && (
                            <Badge tom="neutro">sem correspondência</Badge>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>
            </div>
          )}
        </>
      )}

      {/* --- Nova rede --- */}
      <Modal titulo="Nova rede" aberto={novaAberta} aoFechar={() => setNovaAberta(false)}>
        <div className="space-y-3">
          <Campo rotulo="Nome da rede">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)}
                   placeholder="Ex.: Rede Municipal de Caraguatatuba" autoFocus />
          </Campo>
          <Campo rotulo="UF (opcional)">
            <input className={estiloInput} value={uf} maxLength={2}
                   onChange={(e) => setUf(e.target.value.toUpperCase())} placeholder="SP" />
          </Campo>
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="neutro" onClick={() => setNovaAberta(false)} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado || nome.trim().length < 2} onClick={criarRede}>
              {ocupado ? "Criando..." : "Criar rede"}
            </Botao>
          </div>
        </div>
      </Modal>
    </div>
  );
}
