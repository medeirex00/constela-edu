/**
 * Gestão de REDES (administrador GLOBAL) — provisiona o tier Secretaria:
 *   1. cria/renomeia uma rede;
 *   2. escolhe QUAIS escolas entram nela (e onde ficam no mapa: lat/long);
 *   3. designa QUEM é a Secretaria (usuários que recebem o escopo da rede).
 *
 * Sem isto, a rede só existia por seed. A segurança real é no backend
 * (todas as rotas exigem admin global); esta tela é só a interface.
 */
import {
  ArrowRight, Blocks, Building2, Landmark, LocateFixed, MapPin, Plus, ScanLine, Save, Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Avatar,
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Chip,
  Erro,
  IconePastel,
  Mensagem,
  Modal,
  PageHeader,
  SecaoRecolhivel,
  Vazio,
  estiloInput,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { ApiError, api, apiUpload } from "../../lib/api";
import { normalizar } from "../../lib/nomes";

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
  bairro: string | null;
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

/** Escola cujas notas não foram recalculadas depois de mudar de rede (o recálculo dela falhou). */
type EscolaSemRecalculo = { escola_id: number; nome: string };

// `detalhes`: uma linha por item que falhou, com a mensagem do backend (ex.: o 409 de
// um código INEP que já é de outra escola) — "N com erro" sozinho não diz o que fazer.
// `recalcular`: as escolas com o recálculo pendente — o aviso oferece "Recalcular as notas".
type Aviso = { tipo: "ok" | "erro"; texto: string; detalhes?: string[]; recalcular?: EscolaSemRecalculo[] } | null;

// O mesmo código INEP em 8 dígitos que o backend compara (`normalizar_inep`): "035012345"
// e "35012345" são o mesmo código.
function inepNormalizado(valor: string | null | undefined): string {
  const digitos = (valor ?? "").trim().replace(/\.0$/, "").replace(/\D/g, "");
  return digitos ? digitos.padStart(8, "0").slice(-8) : "";
}

// O código DIGITADO só vale com os seus 8 dígitos (o `inep_digitado` do backend): saem os
// separadores (ponto, traço, barra, espaço), o ".0" do número colado do Excel e o "0" à
// esquerda do cadastro antigo com 9 dígitos — nada é cortado, completado ou ignorado.
// `null` = não é um código INEP (um dígito a mais ou a menos, uma letra).
function inepDigitado(valor: string): string | null {
  const s = valor.trim().replace(/\.0$/, "").replace(/[\s./-]/g, "");
  const codigo = s.length === 9 && s.startsWith("0") ? s.slice(1) : s;
  return /^[0-9]{8}$/.test(codigo) ? codigo : null;
}

const MSG_INEP_8_DIGITOS = "o código INEP tem 8 dígitos, só números (ex.: 35012345). Não foi salvo.";

// Troca (A↔B) ou ciclo (A→B→C→A) dentro do MESMO lote: cada 409 diz "corrija primeiro a
// outra escola", o que é circular — a outra também espera. O que resolve é liberar um código.
const DICA_TROCA_INEP = "Como resolver: os códigos estão sendo trocados entre escolas deste "
  + "lote e nenhuma ordem de salvamento resolve isso. Apague o código de uma delas, clique em "
  + "Salvar códigos e depois preencha os novos.";

// Há troca só quando as esperas fecham um CICLO dentro do lote: seguindo "escola em espera →
// a escola, também em espera, que HOJE tem o código que ela pede", o caminho volta a uma
// escola já vista. Se o caminho sai do grupo (o código é de uma escola fora do lote — de
// outra rede, por exemplo — ou de ninguém), é bloqueio de fora: apagar o código de uma
// escola do lote não resolve, e a mensagem do backend (de quem é o código) é o que orienta.
// `atual`: o código de hoje (normalizado) de cada escola, de qualquer rede.
function haTrocaNoLote(pedidos: { id: number; valor: string }[],
                       atual: Map<number, string>): boolean {
  const esperando = pedidos.map((p) => p.id);
  const proxima = new Map<number, number>();
  for (const { id, valor } of pedidos) {
    const codigo = inepNormalizado(valor);
    if (!codigo) continue;
    const dona = esperando.find((outra) => outra !== id && atual.get(outra) === codigo);
    if (dona !== undefined) proxima.set(id, dona);
  }
  return esperando.some((inicio) => {
    const vistas = new Set<number>();
    let escola: number | undefined = inicio;
    while (escola !== undefined && !vistas.has(escola)) {
      vistas.add(escola);
      escola = proxima.get(escola);
    }
    return escola !== undefined;            // voltou a uma escola já vista: ciclo
  });
}

// Palavras que NÃO distinguem uma escola de outra (tipo de unidade e títulos).
// Tiradas antes de casar o nome colado com a escola da rede.
const RUIDO_ESCOLA = new Set([
  "emef", "emei", "emeiemef", "emefebs", "ciefi", "cei", "ciase", "cries",
  "escola", "municipal", "ensino", "fundamental", "infantil", "creche",
  "prof", "profa", "professor", "professora", "dr", "dra",
  "de", "do", "da", "das", "dos", "e",
]);
function tokensEscola(nome: string): string[] {
  return normalizar(nome)
    .replace(/[.,()/º°ª-]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 1 && !RUIDO_ESCOLA.has(t));
}
/** Casa um nome colado a UMA escola da rede pelos tokens distintivos. Funciona
 *  nos dois sentidos: o nome no sistema pode ser o oficial completo OU um
 *  apelido curto (ex.: "Adolfina") — basta um caber no outro. Pontua por
 *  tokens em comum e exige um vencedor claro; empate sem desempate = null
 *  (a linha entra em "não encontrei" e o usuário resolve à mão). */
function casarEscola(escolas: EscolaItem[], nome: string): EscolaItem | null {
  const alvo = tokensEscola(nome);
  if (!alvo.length) return null;
  const A = new Set(alvo);
  const cand = escolas
    .map((e) => {
      const t = tokensEscola(e.nome);
      const T = new Set(t);
      const shared = alvo.filter((x) => T.has(x)).length;
      // subconjunto em qualquer direção: apelido curto cabe no oficial, ou vice-versa.
      const sub = (t.length > 0 && t.every((x) => A.has(x))) || alvo.every((x) => T.has(x));
      return { e, t, shared, sub };
    })
    .filter((c) => c.shared > 0);
  if (!cand.length) return null;
  cand.sort((a, b) => b.shared - a.shared);
  const maxs = cand[0].shared;
  const top = cand.filter((c) => c.shared === maxs);
  // Vencedor único em nº de tokens comuns: aceita se 2+ em comum (sinal forte)
  // ou se um nome for subconjunto do outro (apelido curto reconhecido).
  if (top.length === 1) return top[0].shared >= 2 || top[0].sub ? top[0].e : null;
  // Empate: prefere quem for subconjunto (o apelido cabe inteiro em um só).
  const subs = top.filter((c) => c.sub);
  if (subs.length === 1) return subs[0].e;
  // Ainda empatado: só aceita igualdade exata de tokens.
  const ex = cand.filter((c) => c.t.length === alvo.length && c.shared === alvo.length);
  return ex.length === 1 ? ex[0].e : null;
}


/** MÓDULOS CONTRATADOS pela rede (SaaS). Ligar/desligar muda a rede inteira na
 *  hora: médias, ranking, adoção e interface. O backend é quem manda — a API
 *  recusa módulo não contratado mesmo se alguém digitar a URL. */
type RespostaContrato = {
  recalculo: {
    escolas: number;
    alunos: number;
    falhas: { escola_id: number; nome: string; erro: string }[];
  };
};

/** Resposta de "Salvar vínculos" (PUT /redes/{id}/escolas): o recálculo das escolas cujo plano
 *  mudou com o vínculo (o mesmo formato do PUT de módulos). Ausente = API anterior. */
type RespostaVinculo = { recalculo?: RespostaContrato["recalculo"] };

const nomesDas = (escolas: EscolaSemRecalculo[]) => escolas.map((e) => e.nome).join(", ");

/** Cargo em linguagem de gente (antes aparecia o valor cru do banco). */
function rotuloCargo(u: { cargo: string; rede_id: number | null }): string {
  if (u.cargo === "admin") return "Administrador";
  if (u.cargo === "coordenador") return u.rede_id != null ? "Secretaria" : "Coordenador";
  if (u.cargo === "professor") return "Professor";
  return u.cargo;
}

/** O código IBGE do município da rede (7 dígitos): as importações dos indicadores oficiais
 *  (Ideb, Saeb, SARESP, ICA) são recortadas por ele. Aqui ele se corrige ou se tira (campo
 *  vazio): o backend recusa (409) o código que já é de outra rede e manda tirá-lo dela
 *  primeiro — antes, nenhuma tela trocava nem limpava o código de uma rede que já tinha um.
 *  Montado com `key` pela rede e pelo código gravado: trocar de rede ou salvar recomeça o
 *  campo; uma recusa mantém o que foi digitado, para corrigir. */
function CodigoIbgeDaRede({ rede, aoSalvar }: {
  rede: RedeItem; aoSalvar: (aviso: NonNullable<Aviso>, gravou: boolean) => void;
}) {
  const atual = rede.codigo_ibge ?? "";
  const [codigo, setCodigo] = useState(atual);
  const [salvando, setSalvando] = useState(false);
  const valido = codigo === "" || /^\d{7}$/.test(codigo);
  const tirar = codigo === "" && atual !== "";

  async function salvar() {
    setSalvando(true);
    try {
      const salva = await api<RedeItem>(`/redes/${rede.id}`, {
        method: "PATCH", body: JSON.stringify({ codigo_ibge: codigo }),
      });
      const gravado = salva?.codigo_ibge ?? null;
      aoSalvar({
        tipo: "ok",
        texto: gravado
          ? `Código IBGE ${gravado} gravado na rede “${rede.nome}”.`
          : `Código IBGE tirado da rede “${rede.nome}”.`,
      }, true);
    } catch (e) {
      aoSalvar({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível gravar o código." }, false);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <Campo rotulo="Código IBGE do município (7 dígitos)">
        <input className={`${estiloInput} w-40`} inputMode="numeric" value={codigo} placeholder="sem código"
               onChange={(e) => setCodigo(e.target.value.replace(/\D/g, "").slice(0, 7))} />
      </Campo>
      <Botao variante="neutro" disabled={salvando || !valido || codigo === atual} onClick={salvar}>
        <Save size={14} /> {tirar ? "Tirar o código IBGE" : "Salvar código IBGE"}
      </Botao>
      <p className="w-full text-xs text-zinc-500">
        Os indicadores oficiais (Ideb, Saeb, SARESP e ICA) são importados pelo município deste código.
        Para tirar o código desta rede, apague o campo e clique em “Tirar o código IBGE”.
      </p>
    </div>
  );
}

/** Interruptor visual sobre um checkbox de verdade (os testes e o leitor de tela
 *  continuam vendo role=checkbox com o mesmo nome). */
function VisualChave({ marcado }: { marcado: boolean }) {
  return (
    <>
      <span
        aria-hidden
        className={`h-7 w-12 rounded-full transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500 peer-focus-visible:ring-offset-2 peer-disabled:opacity-60 ${
          marcado ? "bg-indigo-600 shadow-pilula" : "bg-zinc-300 dark:bg-zinc-700"}`}
      />
      <span
        aria-hidden
        className={`pointer-events-none absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${
          marcado ? "translate-x-5" : ""}`}
      />
    </>
  );
}

export function ModulosDaRede({ redeId }: { redeId: number }) {
  const { dados, erro, carregando, recarregar } =
    useApi<{ chave: string; nome: string; produto: string; icone: string; ativo: boolean }[]>(
      `/redes/${redeId}/modulos`);
  const [salvando, setSalvando] = useState<string | null>(null);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // Último pedido enviado — o botão "Tentar novamente" reenvia exatamente ele.
  // Como o PUT é idempotente, reenviar só refaz o recálculo que ficou para trás.
  const [pendente, setPendente] = useState<Record<string, boolean> | null>(null);

  // Trava SÍNCRONA contra envio duplicado. `salvando` é estado do React e só
  // vale no render seguinte: dois cliques no mesmo tick veem os dois `null` e
  // disparam dois PUTs. O ref fecha essa janela no ato.
  const enviando = useRef(false);

  // Aviso e pedido pendente pertencem a UMA rede. Trocar de rede tem de zerá-los
  // — senão o "Tentar novamente" de um erro da rede A dispararia o PUT contra a
  // rede B, recalculando uma rede que ninguém pediu. O chamador ainda passa
  // `key={redeId}` (remonta de vez); isto aqui torna o componente correto
  // sozinho, para qualquer chamador.
  useEffect(() => {
    setAviso(null);
    setPendente(null);
  }, [redeId]);

  async function alternar(chave: string, ativo: boolean) {
    await enviar({ [chave]: ativo }, chave);
  }

  async function enviar(pedido: Record<string, boolean>, chave: string) {
    if (enviando.current) return;
    enviando.current = true;
    setSalvando(chave);
    setAviso(null);
    try {
      const r = await api<RespostaContrato>(`/redes/${redeId}/modulos`,
        { method: "PUT", body: JSON.stringify(pedido) });
      const { escolas, alunos, falhas } = r.recalculo;
      if (falhas.length) {
        // O CONTRATO foi gravado (é a fonte da verdade); o que faltou foi
        // atualizar as notas de algumas escolas. Dizemos exatamente quais.
        setPendente(pedido);
        setAviso({
          tipo: "erro",
          texto: `Plano salvo, mas as notas de ${falhas.length} escola(s) não foram recalculadas: `
            + `${falhas.map((f) => f.nome).join(", ")}. Use "Tentar novamente" — nada é duplicado.`,
        });
      } else {
        setPendente(null);
        setAviso({
          tipo: "ok",
          texto: `Plano atualizado e notas recalculadas: ${escolas} escola(s), ${alunos} aluno(s). `
            + "A rede já opera com o novo plano.",
        });
      }
      recarregar();
    } catch (e) {
      // NÃO dá para afirmar "falha ao salvar": o contrato é gravado ANTES do
      // recálculo, então um erro aqui (timeout do gateway, queda de rede depois
      // do commit) pode ter deixado o plano já aplicado no servidor. Recarrega o
      // estado real — os checkboxes passam a mostrar a verdade — e a mensagem
      // diz o que de fato se sabe.
      setPendente(pedido);
      setAviso({
        tipo: "erro",
        texto: `${e instanceof ApiError ? e.message : "A conexão falhou."} `
          + "Não foi possível confirmar o resultado: o plano PODE já ter sido aplicado. "
          + "Recarregamos o estado atual — se as notas estiverem atrasadas, use "
          + '"Tentar novamente" (nada é duplicado).',
      });
      recarregar();
    } finally {
      enviando.current = false;
      setSalvando(null);
    }
  }

  if (carregando && !dados) return <Carregando texto="Carregando os módulos..." />;
  if (erro && !dados) return <Mensagem tipo="erro">{erro.message}</Mensagem>;

  const ativos = (dados ?? []).filter((m) => m.ativo).length;
  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-500">
        O que a rede <b>contratou</b>. O módulo desligado desaparece por completo para
        ela — menu, indicadores, ranking e API. Não confundir com <b>sem dados</b>:
        módulo contratado que ainda não recebeu importação continua aparecendo, vazio.
      </p>
      {aviso && (
        <Mensagem tipo={aviso.tipo}>
          {aviso.texto}
          {pendente && (
            <button
              type="button"
              className="ml-2 font-semibold underline underline-offset-2 disabled:opacity-50"
              disabled={salvando !== null}
              onClick={() => enviar(pendente, Object.keys(pendente)[0] ?? "")}
            >
              Tentar novamente
            </button>
          )}
        </Mensagem>
      )}
      {ativos === 0 && (
        <Mensagem tipo="erro">
          Nenhum módulo contratado: a rede fica sem indicadores. Ligue pelo menos um.
        </Mensagem>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {(dados ?? []).map((m) => (
          <label
            key={m.chave}
            className={`flex items-center justify-between gap-3 rounded-2xl border p-4 transition-colors ${
              m.ativo
                ? "border-indigo-200 bg-indigo-50/50 dark:border-indigo-500/30 dark:bg-indigo-500/10"
                : "border-zinc-200 dark:border-zinc-800"} ${salvando !== null ? "cursor-wait" : "cursor-pointer"}`}
          >
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {m.icone} {m.nome}
              </span>
              <span className="block text-xs text-zinc-500 dark:text-zinc-400">{m.produto}</span>
              <span className={`mt-1.5 inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${
                m.ativo
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                  : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"}`}>
                {m.ativo ? "Contratado" : "Não contratado"}
              </span>
            </span>
            <span className="relative inline-flex shrink-0">
              <input
                type="checkbox"
                className="peer sr-only"
                aria-label={`${m.nome} contratado`}
                checked={m.ativo}
                disabled={salvando !== null}
                onChange={(e) => alternar(m.chave, e.target.checked)}
              />
              <VisualChave marcado={m.ativo} />
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

export default function RedeGestao() {
  const { usuario, recarregarEscolas } = useApp();
  const navegar = useNavigate();
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
  const [coords, setCoords] = useState<Record<number, { cidade: string; bairro: string; uf: string; lat: string; lng: string }>>({});
  // Colagem em massa de localizações (uma escola por linha).
  const [colar, setColar] = useState("");
  const [resColar, setResColar] = useState<{ ok: number; erros: string[] } | null>(null);
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
          bairro: e.bairro ?? "",
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
    return (
      <div>
        <PageHeader titulo="Gestão de redes" />
        <Card>
          <Vazio icone={Landmark} titulo="Somente o administrador global"
                 descricao="A gestão de redes é exclusiva da conta global." />
        </Card>
      </div>
    );
  }
  if (carregando && !dados) {
    return (
      <div>
        <PageHeader titulo="Gestão de redes" />
        <Carregando texto="Carregando as redes..." />
      </div>
    );
  }
  if (erro && !dados) {
    return (
      <div>
        <PageHeader titulo="Gestão de redes" />
        <Card><Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} /></Card>
      </div>
    );
  }

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
      const r = await api<RespostaVinculo>(`/redes/${redeSel}/escolas`, {
        method: "PUT",
        body: JSON.stringify({ escola_ids: [...escolasSel] }),
      });
      // O VÍNCULO foi gravado; o que pode ter faltado é recalcular as notas da escola que
      // mudou de plano com ele. Reenviar o mesmo vínculo não refaz isso (nada mudou): a ação
      // é o recálculo de cada escola que ficou para trás.
      const falhas = (r?.recalculo?.falhas ?? []).map((f) => ({ escola_id: f.escola_id, nome: f.nome }));
      setAviso(falhas.length
        ? {
          tipo: "erro",
          texto: `Vínculos salvos, mas as notas de ${falhas.length} escola(s) não foram recalculadas com o `
            + `plano da rede: ${nomesDas(falhas)}. Até lá, as notas delas seguem o plano anterior. `
            + 'Use "Recalcular as notas" — nada é duplicado.',
          recalcular: falhas,
        }
        : { tipo: "ok", texto: "Escolas da rede atualizadas." });
      recarregar();
      recarregarEscolas?.();
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
    } finally {
      setOcupado(false);
    }
  }

  /** Refaz o recálculo das escolas que ficaram para trás ao salvar os vínculos (o recálculo de
   *  cada escola com o plano de agora: idempotente). Quem falhar de novo continua no aviso. */
  async function recalcularNotas(escolas: EscolaSemRecalculo[]) {
    setOcupado(true);
    const falharam: EscolaSemRecalculo[] = [];
    const motivos: string[] = [];
    for (const e of escolas) {
      try {
        await api(`/escolas/${e.escola_id}/recalcular`, { method: "POST" });
      } catch (erro) {
        falharam.push(e);
        motivos.push(`${e.nome}: ${erro instanceof ApiError ? erro.message : "a conexão falhou."}`);
      }
    }
    const feitas = escolas.filter((e) => !falharam.includes(e));
    setAviso(falharam.length
      ? {
        tipo: "erro",
        texto: (feitas.length ? `Notas recalculadas: ${nomesDas(feitas)}. ` : "")
          + `As notas de ${falharam.length} escola(s) ainda não foram recalculadas: ${nomesDas(falharam)}. `
          + "Tente de novo em instantes — nada é duplicado.",
        detalhes: motivos,
        recalcular: falharam,
      }
      : { tipo: "ok", texto: `Notas recalculadas: ${nomesDas(escolas)}.` });
    setOcupado(false);
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

  // Cola um bloco "Nome; bairro; latitude; longitude" (bairro e/ou coordenadas
  // opcionais), casa cada linha com uma escola da rede pelo nome e preenche os
  // campos do formulário. NÃO salva — o usuário confere e clica em Salvar.
  function aplicarColagem() {
    if (!dados || redeSel === null) return;
    const escolas = dados.escolas.filter((e) => e.rede_id === redeSel);
    const eNumero = (p: string) => /^-?\d{1,3}[.,]\d+$/.test(p);
    const naoAchou: string[] = [];
    let ok = 0;
    const novo = { ...coords };
    for (const linha of colar.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)) {
      const partes = linha.split(/[;\t]/).map((p) => p.trim()).filter(Boolean);
      if (partes.length < 2) continue;
      const escola = casarEscola(escolas, partes[0]);
      if (!escola) { naoAchou.push(partes[0]); continue; }
      const resto = partes.slice(1);
      const nums = resto.filter(eNumero);
      const bairro = resto.find((p) => !eNumero(p));
      const atual = novo[escola.id] ?? { cidade: "", bairro: "", uf: "", lat: "", lng: "" };
      const proximo = { ...atual };
      if (bairro) proximo.bairro = bairro;
      if (nums.length >= 2) {
        proximo.lat = nums[0].replace(",", ".");
        proximo.lng = nums[1].replace(",", ".");
      }
      novo[escola.id] = proximo;
      ok += 1;
    }
    setCoords(novo);
    setResColar({ ok, erros: naoAchou });
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
      if (c.bairro.trim()) corpo.bairro = c.bairro.trim();  // bairro = a chave da geocodificação
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
    // O INEP é único (409 quando o código ainda é de OUTRA escola) e cada PATCH vai
    // sozinho: os que LIMPAM o código vão primeiro (liberam o código para outra escola);
    // e quem levou 409 tenta de novo enquanto houver progresso — o código pode sair da
    // outra escola mais adiante no MESMO salvamento (ex.: A recebe o de B, B recebe um
    // novo). Uma troca entre duas escolas (A↔B) não tem ordem que resolva: segue como
    // erro, com a mensagem do backend e a dica do que resolve (DICA_TROCA_INEP).
    // `atual`: o código de HOJE de cada escola (o 409 vem de qualquer rede), atualizado a
    // cada PATCH aceito — é por ele que se reconhece a troca no fim.
    const atual = new Map(dados.escolas.map((x) => [x.id, inepNormalizado(x.codigo_inep)]));
    let troca = false;
    let fila = dados.escolas
      .filter((x) => x.rede_id === redeSel)
      .map((e) => ({ e, valor: (inep[e.id] ?? "").trim() }))
      .filter(({ e, valor }) => valor !== (e.codigo_inep ?? "")) // nada mudou
      .sort((a, b) => Number(a.valor !== "") - Number(b.valor !== ""));
    let ok = 0;
    const erros: string[] = [];
    // O que não tem 8 dígitos nem vai ao backend (que também o recusa): fica como erro,
    // com o nome da escola, e o código de antes continua gravado.
    fila = fila.filter(({ e, valor }) => {
      if (valor === "" || inepDigitado(valor) !== null) return true;
      erros.push(`${e.nome}: ${MSG_INEP_8_DIGITOS}`);
      return false;
    });
    while (fila.length > 0) {
      const conflitos: { item: (typeof fila)[number]; msg: string }[] = [];
      for (const item of fila) {
        try {
          const salvo = await api<{ codigo_inep?: string | null }>(`/redes/escolas/${item.e.id}`, {
            method: "PATCH", body: JSON.stringify({ codigo_inep: item.valor }),
          });
          ok += 1;
          atual.set(item.e.id, inepNormalizado(item.valor));
          // O campo passa a mostrar o código GRAVADO (ex.: "035012345" vira "35012345").
          if (salvo && "codigo_inep" in salvo) {
            setInep((m) => ({ ...m, [item.e.id]: salvo.codigo_inep ?? "" }));
          }
        } catch (err) {
          // A recusa do backend, como veio (o 409 diz de qual escola é o código).
          const msg = err instanceof ApiError ? err.message : "não foi possível salvar.";
          if (err instanceof ApiError && err.status === 409) conflitos.push({ item, msg });
          else erros.push(`${item.e.nome}: ${msg}`);
        }
      }
      if (conflitos.length === fila.length) {           // nenhum progresso: fica o erro
        erros.push(...conflitos.map(({ item, msg }) => `${item.e.nome}: ${msg}`));
        // Troca: as esperas fecham um ciclo dentro do lote (não basta uma escola pedir o
        // código de outra que também espera — a cadeia pode terminar fora do lote).
        troca = haTrocaNoLote(conflitos.map(({ item }) => ({ id: item.e.id, valor: item.valor })),
                              atual);
        break;
      }
      fila = conflitos.map(({ item }) => item);
    }
    setAviso({
      tipo: erros.length ? "erro" : "ok",
      texto: `${ok} código(s) salvo(s)` + (erros.length ? `; ${erros.length} com erro:` : "."),
      detalhes: troca ? [...erros, DICA_TROCA_INEP] : erros,
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

      {aviso && (
        <Mensagem tipo={aviso.tipo}>
          {aviso.texto}
          {aviso.recalcular && aviso.recalcular.length > 0 && (
            <button
              type="button"
              className="ml-2 font-semibold underline underline-offset-2 disabled:opacity-50"
              disabled={ocupado}
              onClick={() => void recalcularNotas(aviso.recalcular ?? [])}
            >
              Recalcular as notas
            </button>
          )}
          {aviso.detalhes && aviso.detalhes.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-5" data-testid="aviso-detalhes">
              {aviso.detalhes.map((d) => <li key={d}>{d}</li>)}
            </ul>
          )}
        </Mensagem>
      )}

      {dados && dados.redes.length === 0 ? (
        <Card>
          <Vazio icone={Landmark} titulo="Nenhuma rede ainda"
                 descricao="Crie a primeira rede para habilitar o painel da Secretaria." />
        </Card>
      ) : (
        <>
          {/* Seletor de rede: a pílula SÓ seleciona (antes, clicar na selecionada
              navegava — uma ação escondida); abrir o painel é um botão explícito. */}
          <Card className="flex flex-wrap items-center gap-3 p-4">
            <span className="flex items-center gap-2 text-sm font-semibold text-zinc-600 dark:text-zinc-300">
              <IconePastel icone={Landmark} tom="violeta" tamanho="sm" /> Rede
            </span>
            <div role="group" aria-label="Rede a gerenciar"
                 className="inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-zinc-200/80 bg-zinc-50 p-1 dark:border-zinc-800 dark:bg-zinc-900">
              {dados?.redes.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  aria-pressed={r.id === redeSel}
                  onClick={() => setRedeSel(r.id)}
                  className={`inline-flex items-center gap-1 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
                    r.id === redeSel
                      ? "bg-indigo-600 text-white shadow-pilula"
                      : "text-zinc-600 hover:bg-white hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
                  }`}
                >
                  {r.nome}{r.status !== "ativa" ? " (inativa)" : ""}
                </button>
              ))}
            </div>
            {redeSel !== null && (
              <Botao variante="secundario" tamanho="sm" className="sm:ml-auto" onClick={() => navegar("/rede")}>
                Abrir painel da rede <ArrowRight size={14} aria-hidden />
              </Botao>
            )}
            {redeAtual && (
              <div className="w-full border-t border-zinc-100 pt-3 dark:border-zinc-800">
                <CodigoIbgeDaRede
                  key={`${redeAtual.id}:${redeAtual.codigo_ibge ?? ""}`}
                  rede={redeAtual}
                  aoSalvar={(a, gravou) => { setAviso(a); if (gravou) recarregar(); }}
                />
              </div>
            )}
          </Card>

          {redeAtual && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* --- Escolas da rede --- */}
              <Card className="min-w-0 p-5 sm:p-6">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
                    <IconePastel icone={Building2} tom="violeta" tamanho="sm" /> Escolas da rede
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
                        <label className="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                          <input
                            type="checkbox"
                            className="h-4 w-4 shrink-0 rounded border-zinc-300 accent-indigo-600"
                            checked={escolasSel.has(e.id)}
                            onChange={() => setEscolasSel((s) => alternar(s, e.id))}
                          />
                          <span aria-hidden className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${
                            e.status === "ativa"
                              ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300"
                              : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"}`}>
                            <Building2 size={15} />
                          </span>
                          <span className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-800 dark:text-zinc-100" title={e.nome}>{e.nome}</span>
                          {e.status !== "ativa" && <Badge tom="neutro">Inativa</Badge>}
                          {emOutraRede && <Badge tom="alerta">em outra rede</Badge>}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </Card>

              {/* --- Secretaria (usuários) --- */}
              <Card className="p-5 sm:p-6">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
                    <IconePastel icone={Users} tom="teal" tamanho="sm" /> Acesso da Secretaria
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
                      <label className="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                        <input
                          type="checkbox"
                          className="h-4 w-4 shrink-0 rounded border-zinc-300 accent-indigo-600"
                          checked={usuariosSel.has(u.id)}
                          onChange={() => setUsuariosSel((s) => alternar(s, u.id))}
                        />
                        <Avatar nome={u.nome} chave={u.id} tamanho="sm" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-zinc-800 dark:text-zinc-100" title={u.nome}>{u.nome}</span>
                          <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400" title={u.email}>{u.email}</span>
                        </span>
                        <Chip>{rotuloCargo(u)}</Chip>
                      </label>
                    </li>
                  ))}
                </ul>
              </Card>

              {/* --- Módulos contratados (largura inteira: antes ficava sozinho numa coluna) --- */}
              <SecaoRecolhivel
                className="lg:col-span-2"
                icone={<IconePastel icone={Blocks} tom="violeta" tamanho="sm" />}
                titulo="Módulos contratados"
              >
                {/* `key` obriga a remontagem ao trocar de rede: sem ela o aviso
                    e o pedido pendente de UMA rede sobreviviam na tela, e o
                    "Tentar novamente" disparava o PUT contra a rede NOVA. */}
                <ModulosDaRede key={redeSel!} redeId={redeSel!} />
              </SecaoRecolhivel>

              {/* --- Localização no mapa --- */}
              <SecaoRecolhivel
                className="lg:col-span-2"
                icone={<IconePastel icone={MapPin} tom="azul" tamanho="sm" />}
                // Título sem quebra: quando não cabem título e botões na mesma linha, os
                // BOTÕES descem (o cabeçalho quebra), em vez de espremer o título em duas.
                titulo={<span className="whitespace-nowrap">Localização no mapa</span>}
                acoes={
                  <>
                    <Botao variante="neutro" onClick={geocodificar} disabled={ocupado || escolasNaRede.length === 0}>
                      <LocateFixed size={14} /> Geocodificar automaticamente
                    </Botao>
                    <Botao onClick={salvarLocalizacoes} disabled={ocupado || escolasNaRede.length === 0}>
                      <Save size={14} /> Salvar localizações
                    </Botao>
                  </>
                }
              >
                <p className="mb-2 text-xs text-zinc-500">
                  Preencha o <b>bairro</b> (e a cidade) e clique em <b>Geocodificar</b> — o sistema
                  acha as coordenadas no OpenStreetMap pelo bairro e posiciona os marcadores.
                  Sem o bairro, escolas municipais pequenas costumam não ser localizadas.
                  Você também pode informar latitude/longitude à mão. Salve os vínculos antes.
                </p>

                {escolasNaRede.length > 0 && (
                  <div className="mb-3 rounded-lg border border-indigo-200 bg-indigo-50/50 p-3 dark:border-indigo-500/30 dark:bg-indigo-500/5">
                    <p className="mb-1 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
                      Colar localizações em massa
                    </p>
                    <p className="mb-2 text-xs text-zinc-500">
                      Uma escola por linha: <code>Nome; bairro; latitude; longitude</code> (bairro e
                      coordenadas são opcionais). O sistema casa pelo nome e preenche os campos —
                      confira e clique em <b>Salvar localizações</b>.
                    </p>
                    <textarea
                      aria-label="Localizações das escolas, uma por linha"
                      className={`${estiloInput} h-28 w-full font-mono text-xs`}
                      placeholder={"Jorge Passos; Jaraguazinho; -23.61590; -45.43217\nBenedito Inácio Soares; Massaguaçu; -23.58121; -45.33248"}
                      value={colar}
                      onChange={(ev) => setColar(ev.target.value)}
                    />
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Botao variante="neutro" onClick={aplicarColagem} disabled={!colar.trim()}>
                        <MapPin size={14} /> Aplicar ao formulário
                      </Botao>
                      {resColar && (
                        <span className="text-xs text-zinc-600 dark:text-zinc-300">
                          {resColar.ok} preenchida(s)
                          {resColar.erros.length > 0 && (
                            <> · não encontrei: <b>{resColar.erros.join(", ")}</b></>
                          )}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {escolasNaRede.length === 0 ? (
                  <p className="py-4 text-center text-sm text-zinc-500">
                    Nenhuma escola vinculada ainda.
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {escolasNaRede.map((e) => {
                      const c = coords[e.id] ?? { cidade: "", bairro: "", uf: "", lat: "", lng: "" };
                      return (
                        <div key={e.id} className="flex flex-wrap items-center gap-2 rounded-xl px-1 py-1">
                          {/* No celular o rótulo ocupa a linha toda e o nome aparece inteiro
                              (quebra linha): com o `w-40` de sempre, escolas de prefixo igual
                              ("EMEF Fictícia…") ficavam indistinguíveis. Do `sm` para cima, igual. */}
                          <span className="w-full truncate text-sm font-semibold text-zinc-800 max-sm:whitespace-normal max-sm:break-words sm:w-40 dark:text-zinc-100" title={e.nome}>{e.nome}</span>
                          <input
                            className={`${estiloInput} w-36`}
                            aria-label={`Cidade de ${e.nome}`}
                            placeholder="cidade"
                            value={c.cidade}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, cidade: ev.target.value } }))}
                          />
                          <input
                            className={`${estiloInput} w-40`}
                            aria-label={`Bairro de ${e.nome}`}
                            placeholder="bairro (para o mapa)"
                            value={c.bairro}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, bairro: ev.target.value } }))}
                          />
                          <input
                            className={`${estiloInput} w-14`}
                            aria-label={`UF de ${e.nome}`}
                            placeholder="UF"
                            maxLength={2}
                            value={c.uf}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, uf: ev.target.value.toUpperCase() } }))}
                          />
                          <input
                            className={`${estiloInput} w-28`}
                            aria-label={`Latitude de ${e.nome}`}
                            placeholder="latitude"
                            inputMode="decimal"
                            value={c.lat}
                            onChange={(ev) => setCoords((m) => ({ ...m, [e.id]: { ...c, lat: ev.target.value } }))}
                          />
                          <input
                            className={`${estiloInput} w-28`}
                            aria-label={`Longitude de ${e.nome}`}
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
              </SecaoRecolhivel>

              {/* --- Códigos INEP (para casar avaliações oficiais) --- */}
              <SecaoRecolhivel
                className="lg:col-span-2"
                icone={<IconePastel icone={ScanLine} tom="ambar" tamanho="sm" />}
                titulo={<span className="whitespace-nowrap">Códigos INEP das escolas</span>}
                acoes={
                  <>
                    <label className={`inline-flex cursor-pointer items-center gap-2 rounded-xl border border-zinc-200 bg-white px-4 py-2.5 text-sm font-semibold text-zinc-800 shadow-cartao hover:border-zinc-300 hover:bg-zinc-50 focus-within:ring-2 focus-within:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800 ${ocupado || escolasNaRede.length === 0 ? "pointer-events-none opacity-50" : ""}`}>
                      <ScanLine size={14} /> Preencher automaticamente
                      {/* Só o que o backend lê (o mesmo leitor das avaliações): o .xls
                          antigo voltaria uma proposta vazia, sem erro. */}
                      <input type="file" accept=".xlsx,.csv,.zip" className="sr-only"
                             onChange={(ev) => { const f = ev.target.files?.[0]; if (f) preencherInep(f); ev.target.value = ""; }} />
                    </label>
                    <Botao onClick={salvarInep} disabled={ocupado || escolasNaRede.length === 0}>
                      <Save size={14} /> Salvar códigos
                    </Botao>
                  </>
                }
              >
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
                        <div key={e.id} className="flex flex-wrap items-center gap-2 rounded-xl px-1 py-1">
                          {/* No celular o rótulo ocupa a linha toda e o nome aparece inteiro
                              (quebra linha): com o `w-40` de sempre, escolas de prefixo igual
                              ("EMEF Fictícia…") ficavam indistinguíveis. Do `sm` para cima, igual. */}
                          <span className="w-full truncate text-sm font-semibold text-zinc-800 max-sm:whitespace-normal max-sm:break-words sm:w-40 dark:text-zinc-100" title={e.nome}>{e.nome}</span>
                          <input
                            className={`${estiloInput} w-32`}
                            aria-label={`Código INEP de ${e.nome}`}
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
              </SecaoRecolhivel>
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
