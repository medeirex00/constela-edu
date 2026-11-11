/**
 * Indicadores oficiais da rede: FONTES E ARQUIVOS OFICIAIS (rastreabilidade, o detalhe
 * técnico) — e, para o admin global, a IMPORTAÇÃO. É a área documental: cada indicador
 * (ICA, SARESP, Ideb/Saeb) com o detalhe dos números, a cobertura por escola e o arquivo de
 * origem de cada número. Para a Secretaria fica DENTRO de "Avaliações externas" (o link
 * "Arquivos oficiais de cada número"); o h1 continua "Fontes dos indicadores". Para ENTENDER
 * os resultados, o lugar é "Avaliações externas" (`/rede/avaliacoes-externas`): o cartão do
 * topo leva de volta para lá.
 *
 * PERFIS (decisões D4 e D5 do dono, 17/10): a Secretaria LÊ a rede inteira (cartões e
 * abas); importar, remover uma edição e o robô de coleta são SÓ do admin global — a tela
 * não mostra esses controles a mais ninguém (o backend também barra).
 *
 * A antiga correlação (dispersão, evolução e Pearson) SAIU daqui: ela misturava número
 * oficial com estimativa, cruzava anos diferentes e fazia a "média da rede" pela média das
 * escolas. A relação com as plataformas agora é a das Análises avançadas
 * (`/rede/analise?ver=relacao`), com critérios documentados — esta página só aponta para lá,
 * e só para o admin global (as Análises avançadas não estão no menu da Secretaria).
 * A importação: upload do arquivo oficial → mapear colunas → conferir → gravar (casa por
 * código INEP). Só dados agregados por escola.
 */
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  ClipboardCheck,
  Clock,
  FileUp,
  Info,
  Landmark,
  Pause,
  Play,
  RefreshCw,
  Settings2,
  Trash2,
  Upload,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Confirmacao,
  ESTILOS_BOTAO,
  Erro,
  IconePastel,
  Mensagem,
  PageHeader,
  TAMANHOS_BOTAO,
  Vazio,
  estiloInput,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { ApiError, api, apiUpload } from "../../lib/api";
import { dataDia } from "../../lib/formato";
import CartaoICA from "./CartaoICA";
import CartaoIDEB from "./CartaoIDEB";
import CartaoSARESP from "./CartaoSARESP";
import ImportarIndicadoresOficiais from "./ImportarIndicadoresOficiais";

interface SerieOpcao {
  avaliacao: string; nome: string; tipo: string; indicador: string;
  etapa: string | null; componente: string | null; edicoes: number[];
}
interface CatalogoItem { chave: string; nome: string; tipo: string; orgao: string | null; descricao: string | null }
interface Analise { linhas_lidas: number; n_colunas: number; primeiras_linhas: string[][] }
interface Mapeamento {
  linha_dados: number; col_inep: number; col_valor: number;
  col_etapa?: number | null; col_componente?: number | null; col_turma?: number | null;
  etapa_fixa?: string | null; componente_fixo?: string | null;
  // Ao salvar: o texto do cabeçalho de cada coluna mapeada no arquivo conferido. Na lista,
  // vem o que o backend guardou (as colunas e, no arquivo do INEP, a etapa).
  cabecalho?: Record<string, unknown>;
}
interface Fonte {
  id: number; avaliacao: string; avaliacao_nome: string | null; nome: string;
  url: string; edicao: number; indicador: string; unidade: string;
  cadencia: string; ativo: boolean; mapeamento: Mapeamento;
  ultima_coleta: string | null; proxima_coleta: string | null;
  ultimo_status: string; ultimo_erro: string | null;
  ultimo_resumo: Record<string, unknown> | null;
  // O robô AUTOMÁTICO está ligado no servidor? Desligado (o padrão), a fonte mensal não é
  // coletada sozinha: só o "Coletar agora".
  robo_habilitado?: boolean;
}

const rotuloSerie = (s: SerieOpcao) =>
  [s.nome, s.indicador, s.etapa, s.componente].filter(Boolean).join(" · ");

// --- Para entender os resultados: Avaliações externas ------------------------------

/** O cartão-link de VOLTA para "Avaliações externas" (o resumo em linguagem simples de cada
 *  avaliação e a comparação entre escolas) — esta página é o detalhe técnico. Só para o admin
 *  global, um link secundário leva à relação com as plataformas (Análises avançadas), e a
 *  rede mostrada vai junto. */
function CartaoAvaliacoesExternas({ redeId, ehGlobal }: { redeId: number; ehGlobal: boolean }) {
  const comRede = (caminho: string, extra = "") => {
    const q = new URLSearchParams(extra);
    if (ehGlobal) q.set("rede", String(redeId));
    const texto = q.toString();
    return texto ? `${caminho}?${texto}` : caminho;
  };
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-4" data-testid="cartao-avaliacoes-externas">
        <div className="flex min-w-0 items-start gap-3">
          <IconePastel icone={ClipboardCheck} tom="violeta" />
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-white">Avaliações externas</h2>
            <p className="mt-0.5 max-w-2xl text-xs text-zinc-600 dark:text-zinc-400">
              O que cada avaliação mede, a edição mais recente, a meta e a comparação entre as escolas, em linguagem
              simples, ficam em Avaliações externas. Aqui está o detalhe técnico: os arquivos e a cobertura de cada número.
              {/* As Análises avançadas saíram do menu da Secretaria (DESENHO3 §1, §5): o link
                  para a relação com as plataformas fica só para o admin global. */}
              {ehGlobal && (
                <>
                  {" "}A relação com o Elefante e o Matific fica nas{" "}
                  <Link to={comRede("/rede/analise", "ver=relacao")}
                        className="font-semibold text-indigo-700 hover:underline dark:text-indigo-300">
                    Análises avançadas
                  </Link>.
                </>
              )}
            </p>
          </div>
        </div>
        <Link to={comRede("/rede/avaliacoes-externas")}
              className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.primario}`}>
          Voltar para Avaliações externas <ArrowRight size={14} aria-hidden />
        </Link>
      </div>
    </Card>
  );
}

// --- Remover uma edição (só admin global) -------------------------------------------

/** Desfazer uma importação manual/1 clique errada: apaga só a série EXATA escolhida. */
function RemoverEdicao({ opcoes, aoRemover }: { opcoes: SerieOpcao[]; aoRemover: () => void }) {
  const [idx, setIdx] = useState(0);
  const [edicao, setEdicao] = useState<number | null>(null);
  const [removendo, setRemovendo] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [msgRemover, setMsgRemover] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const serie = opcoes[Math.min(idx, opcoes.length - 1)];
  const ed = edicao ?? serie?.edicoes[0] ?? null;

  /** Só depois do "Remover edição" da confirmação (o botão da linha só a abre). */
  async function removerSerie() {
    if (!serie || ed == null) { setConfirmando(false); return; }
    setRemovendo(true); setMsgRemover(null);
    try {
      // Identifica a série EXATA (com etapa/componente) — não apaga as irmãs.
      const qs = new URLSearchParams({
        avaliacao: serie.avaliacao, edicao: String(ed), indicador: serie.indicador,
      });
      if (serie.etapa) qs.set("etapa", serie.etapa);
      if (serie.componente) qs.set("componente", serie.componente);
      const r = await api<{ removidos: number }>(
        `/avaliacoes/resultados?${qs.toString()}`, { method: "DELETE" });
      setMsgRemover({ tipo: "ok", texto: `${r.removidos} resultado(s) removido(s) da edição ${ed}.` });
      setEdicao(null);
      aoRemover();
    } catch (e) {
      setMsgRemover({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível remover." });
    } finally { setRemovendo(false); setConfirmando(false); }
  }

  return (
    <Card className="space-y-3 p-5">
      <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
        <IconePastel icone={Trash2} tom="rosa" tamanho="sm" /> Remover uma edição importada
      </h2>
      <p className="text-xs text-zinc-500">
        Desfaz uma importação manual ou de 1 clique errada (apaga só a série escolhida). Uma série com número
        de importação oficial (com prévia) não é apagada aqui: ela se desfaz pela própria importação.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Campo rotulo="Avaliação / indicador">
          <select className={estiloInput} value={idx}
                  onChange={(e) => { setIdx(Number(e.target.value)); setEdicao(null); }}>
            {opcoes.map((s, i) => <option key={i} value={i}>{rotuloSerie(s)}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Edição">
          <select className={estiloInput} value={ed ?? ""} onChange={(e) => setEdicao(Number(e.target.value))}>
            {serie?.edicoes.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </Campo>
        {serie && ed != null && (
          <button type="button" onClick={() => setConfirmando(true)} disabled={removendo}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-500/30 dark:hover:bg-red-500/10"
                  title="Remover os resultados desta edição (desfazer importação errada)">
            <Trash2 size={14} /> {removendo ? "Removendo..." : `Remover edição ${ed}`}
          </button>
        )}
      </div>
      {msgRemover && <Mensagem tipo={msgRemover.tipo}>{msgRemover.texto}</Mensagem>}
      <Confirmacao
        titulo="Remover esta edição?"
        aberto={confirmando && serie != null && ed != null}
        aoFechar={() => setConfirmando(false)}
        aoConfirmar={() => void removerSerie()}
        rotuloConfirmar={removendo ? "Removendo..." : "Remover edição"}
        variante="perigo"
        ocupado={removendo}
      >
        {serie && ed != null && (
          <>
            <p>Remover os resultados de <strong>“{rotuloSerie(serie)} · edição {ed}”</strong>?</p>
            <p>
              Apaga só ESTA série (não afeta outras edições, etapas nem componentes). Use para desfazer uma
              importação errada.
            </p>
          </>
        )}
      </Confirmacao>
    </Card>
  );
}

// --- Importação --------------------------------------------------------------

// Indicador/unidade (e a etapa, quando a série só tem uma) sugeridos por avaliação
// — os MESMOS do `_PRESETS_IMPORT` do backend (routers/avaliacoes.py). Se
// divergirem, a importação manual grava uma série paralela à do 1 clique (ex.: a
// estimativa de alfabetização é taxa em %, do 2º ano). IDEB/SAEB/SARESP NÃO
// pré-preenchem a etapa: a importação manual é o caminho de Anos Finais e Ensino
// Médio, e um "anos_iniciais" esquecido no campo gravaria o arquivo de outra etapa
// POR CIMA dos Anos Iniciais (a sugestão fica no placeholder).
// `exemploEtapa` é o placeholder — o valor que o backend ACEITA: desde a 0035, SAEB e
// SARESP gravam a SÉRIE ("5_ano"; "2_ano" no SARESP) e recusam "anos_iniciais", que
// fica só para o IDEB (o índice cobre do 1º ao 5º ano).
const PRESETS: Record<string, { indicador: string; unidade: string; etapa?: string; exemploEtapa?: string }> = {
  ideb: { indicador: "ideb", unidade: "indice", exemploEtapa: "anos_iniciais" },
  saeb: { indicador: "proficiencia", unidade: "escala_saeb", exemploEtapa: "5_ano" },
  saresp: { indicador: "proficiencia", unidade: "escala_saresp", exemploEtapa: "5_ano ou 2_ano" },
  crianca_alfabetizada: { indicador: "taxa_alfabetizacao", unidade: "percentual", etapa: "2_ano" },
};
const EXEMPLO_ETAPA_PADRAO = "5_ano";

// Formatos que o backend LÊ (_iterar_grade): XLSX, CSV e o ZIP oficial. O .xls
// antigo não é lido — oferecê-lo só levaria a uma importação vazia.
const ACEITA_ARQUIVO = ".xlsx,.csv,.zip";

// Códigos INEP do arquivo que não casaram com escola do alcance. A API devolve
// TODOS; a tela mostra os primeiros e abre o resto em "ver todos". Quem usa só
// monta com lista não-vazia (zerar a lista a cada importação recolhe de novo).
const NAO_CASADOS_VISIVEIS = 20;

function CodigosNaoCasados({ codigos }: { codigos: string[] }) {
  const [todos, setTodos] = useState(false);
  const sobra = codigos.length > NAO_CASADOS_VISIVEIS;
  const visiveis = todos || !sobra ? codigos : codigos.slice(0, NAO_CASADOS_VISIVEIS);
  return (
    <div className="rounded-lg border border-zinc-200 p-3 text-xs dark:border-zinc-800">
      <p className="mb-1.5 text-zinc-600 dark:text-zinc-400">
        <b>{codigos.length}</b> código(s) INEP do arquivo sem escola correspondente no seu alcance
        {" "}(num arquivo nacional, quase todos são de outras redes):
      </p>
      <p className="max-h-48 overflow-y-auto break-words font-mono text-zinc-500">
        {visiveis.join(", ")}{!todos && sobra ? ", …" : ""}
      </p>
      {sobra && (
        <button type="button" onClick={() => setTodos((v) => !v)}
                className="mt-1.5 font-medium text-indigo-600 hover:underline dark:text-indigo-400">
          {todos ? "ver menos" : `ver todos (${codigos.length})`}
        </button>
      )}
    </div>
  );
}

// Linhas casadas que JÁ têm o número de uma importação oficial (com prévia e desfazer):
// a importação manual e a de 1 clique não as gravam por cima (`mantidos_oficiais`).
// Sem dizer isso, "N casada(s)" parecia sucesso mesmo quando nada foi gravado.
function textoMantidos(n: number): string {
  return `${n} número(s) mantido(s): a escola já tem o número da importação oficial (com prévia), `
    + "que esta importação não substitui — para trocá-lo, desfaça aquela importação.";
}

function ImportarAvaliacao({ catalogo, aoImportar, ehGlobal, aoSalvarFonte }: {
  catalogo: CatalogoItem[]; aoImportar: () => void;
  ehGlobal: boolean; aoSalvarFonte?: () => void;
}) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [analise, setAnalise] = useState<Analise | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [naoCasados, setNaoCasados] = useState<string[]>([]);
  // Robô (só admin global): salvar o MESMO mapeamento como fonte de coleta.
  const [urlFonte, setUrlFonte] = useState("");
  const [cadencia, setCadencia] = useState("mensal");
  const [salvandoFonte, setSalvandoFonte] = useState(false);
  const [msgFonte, setMsgFonte] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  const [avaliacao, setAvaliacao] = useState("ideb");
  const preset = PRESETS[avaliacao] ?? { indicador: "", unidade: "" };
  const [edicao, setEdicao] = useState(new Date().getFullYear() - 1);
  const [linhaDados, setLinhaDados] = useState(1);
  const [colInep, setColInep] = useState(0);
  const [colValor, setColValor] = useState(1);
  const [colEtapa, setColEtapa] = useState<number | "">("");
  const [colComp, setColComp] = useState<number | "">("");
  const [etapaFixa, setEtapaFixa] = useState(preset.etapa ?? "");
  const [compFixo, setCompFixo] = useState("");
  const [indicador, setIndicador] = useState(preset.indicador);
  const [unidade, setUnidade] = useState(preset.unidade);

  const cols = analise ? Array.from({ length: analise.n_colunas }, (_, i) => i) : [];

  async function analisar(f: File) {
    setOcupado(true); setMsg(null); setAnalise(null); setNaoCasados([]);
    try {
      const fd = new FormData(); fd.append("arquivo", f);
      const a = await apiUpload<Analise>("/avaliacoes/analisar", fd);
      setAnalise(a);
      setArquivo(f);
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível ler o arquivo." });
    } finally { setOcupado(false); }
  }

  function trocarAvaliacao(chave: string) {
    setAvaliacao(chave);
    const p = PRESETS[chave] ?? { indicador: "", unidade: "" };
    setIndicador(p.indicador); setUnidade(p.unidade);
    // A etapa SUGERIDA sai junto ao trocar (não fica "2_ano" num IDEB); a que o
    // gestor digitou fica.
    setEtapaFixa((atual) => p.etapa ?? (atual === preset.etapa ? "" : atual));
  }

  async function importar() {
    if (!arquivo) return;
    setOcupado(true); setMsg(null); setNaoCasados([]);
    try {
      const fd = new FormData();
      fd.append("arquivo", arquivo);
      fd.append("avaliacao", avaliacao);
      fd.append("edicao", String(edicao));
      fd.append("indicador", indicador.trim());
      fd.append("unidade", unidade.trim());
      fd.append("linha_dados", String(linhaDados));
      fd.append("col_inep", String(colInep));
      fd.append("col_valor", String(colValor));
      if (colEtapa !== "") fd.append("col_etapa", String(colEtapa));
      if (colComp !== "") fd.append("col_componente", String(colComp));
      if (etapaFixa.trim()) fd.append("etapa_fixa", etapaFixa.trim());
      if (compFixo.trim()) fd.append("componente_fixo", compFixo.trim());
      const r = await apiUpload<{
        casados: number; inseridos: number; atualizados: number; nao_casados: number;
        ignorados: number; mantidos_oficiais?: number; inep_nao_casados?: string[];
      }>("/avaliacoes/importar", fd);
      const mantidos = r.mantidos_oficiais ?? 0;
      setMsg({
        // O tom diz se algo foi GRAVADO (casar não é gravar: a de número oficial fica).
        tipo: r.inseridos + r.atualizados > 0 ? "ok" : "erro",
        texto: `${r.casados} escola(s) casada(s) por INEP — ${r.inseridos} nova(s), ${r.atualizados} atualizada(s)`
          + `; ${r.nao_casados} sem escola, ${r.ignorados} linha(s) ignorada(s).`
          + (mantidos > 0 ? ` ${textoMantidos(mantidos)}` : ""),
      });
      setNaoCasados(r.inep_nao_casados ?? []);
      aoImportar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha ao importar." });
    } finally { setOcupado(false); }
  }

  async function salvarFonte() {
    setSalvandoFonte(true); setMsgFonte(null);
    try {
      const mapeamento: Mapeamento = {
        linha_dados: linhaDados, col_inep: colInep, col_valor: colValor,
        col_etapa: colEtapa === "" ? null : Number(colEtapa),
        col_componente: colComp === "" ? null : Number(colComp),
        etapa_fixa: etapaFixa.trim() || null,
        componente_fixo: compFixo.trim() || null,
      };
      // O cabeçalho (a linha antes dos dados) de cada coluna mapeada, como está no arquivo
      // conferido acima: a cada coleta, o robô confere que o arquivo da URL ainda é este.
      // (Um texto longo demais fica de fora: a 1ª coleta vira a referência.)
      const linhaCabecalho = linhaDados >= 1 ? analise?.primeiras_linhas[linhaDados - 1] : undefined;
      const cabecalho = Object.fromEntries(
        (["col_inep", "col_valor", "col_etapa", "col_componente"] as const)
          .filter((c) => mapeamento[c] != null)
          .map((c) => [c, linhaCabecalho?.[mapeamento[c] as number] ?? ""]));
      if (linhaCabecalho && Object.values(cabecalho).every((t) => t.length <= 200)) {
        mapeamento.cabecalho = cabecalho;
      }
      const criada = await api<Fonte>("/avaliacoes/fontes", {
        method: "POST",
        body: JSON.stringify({
          avaliacao, nome: `${catalogo.find((c) => c.chave === avaliacao)?.nome ?? avaliacao} ${edicao}`,
          url: urlFonte.trim(), edicao, indicador: indicador.trim(), unidade: unidade.trim(),
          cadencia, mapeamento,
        }),
      });
      setMsgFonte({ tipo: "ok", texto: textoFonteSalva(cadencia, criada?.robo_habilitado === true) });
      setUrlFonte("");
      aoSalvarFonte?.();
    } catch (e) {
      setMsgFonte({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha ao salvar a fonte." });
    } finally { setSalvandoFonte(false); }
  }

  return (
    <Card className="space-y-4 p-5">
      <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
        <IconePastel icone={FileUp} tom="violeta" tamanho="sm" /> Importar resultado oficial
      </h2>
      <p className="text-xs text-zinc-500">
        Suba o arquivo oficial (XLSX, CSV ou o ZIP) do INEP/SEDUC. O sistema mostra as primeiras linhas;
        você escolhe a linha onde começam os dados e qual coluna é o código INEP e o valor.
        O casamento com as escolas é pelo <b>código INEP</b>.
      </p>

      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-zinc-300 px-4 py-2 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800">
        <Upload size={15} /> {arquivo ? arquivo.name : "Escolher arquivo..."}
        <input type="file" accept={ACEITA_ARQUIVO} className="hidden"
               onChange={(e) => { const f = e.target.files?.[0]; if (f) analisar(f); }} />
      </label>

      {/* Sem a grade de mapeamento, a resposta (inclusive a recusa da análise) fica
          aqui; com ela, junto do botão "Importar resultados" — onde o gestor está. */}
      {!analise && msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}

      {analise && (
        <>
          <div className="relative overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-zinc-100 dark:bg-zinc-800">
                  {cols.map((c) => <th key={c} className="px-2 py-1 font-mono text-zinc-500">col {c}</th>)}
                </tr>
              </thead>
              <tbody>
                {analise.primeiras_linhas.slice(0, 8).map((linha, i) => (
                  <tr key={i} className={i + 1 === linhaDados ? "bg-indigo-50 dark:bg-indigo-500/10" : ""}>
                    {cols.map((c) => (
                      <td key={c} className="whitespace-nowrap border-t border-zinc-100 px-2 py-1 dark:border-zinc-800/60">
                        {linha[c] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-zinc-500">
            A linha destacada é a <b>primeira linha de dados</b> (índice {linhaDados}). Ajuste abaixo.
          </p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Campo rotulo="Avaliação">
              {/* Agrupado por ÓRGÃO (INEP, CAEd, SEDUC-SP…): o CAEd aparece como
                  categoria própria, pronta para receber Fluência Leitora, Diagnóstica
                  e outras avaliações da plataforma. */}
              <select className={estiloInput} value={avaliacao} onChange={(e) => trocarAvaliacao(e.target.value)}>
                {Object.entries(
                  catalogo.reduce<Record<string, CatalogoItem[]>>((acc, a) => {
                    const org = a.orgao || "Outros";
                    if (!acc[org]) acc[org] = [];
                    acc[org].push(a);
                    return acc;
                  }, {}),
                ).map(([org, itens]) => (
                  <optgroup key={org} label={org}>
                    {itens.map((a) => (
                      <option key={a.chave} value={a.chave}>{a.nome}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Campo>
            <Campo rotulo="Edição (ano)">
              <input type="number" className={estiloInput} value={edicao} onChange={(e) => setEdicao(Number(e.target.value))} />
            </Campo>
            <Campo rotulo="Indicador">
              <input className={estiloInput} value={indicador} onChange={(e) => setIndicador(e.target.value)} />
            </Campo>
            <Campo rotulo="Unidade">
              <input className={estiloInput} value={unidade} onChange={(e) => setUnidade(e.target.value)} />
            </Campo>
            <Campo rotulo="1ª linha de dados (índice)">
              <input type="number" min={0} className={estiloInput} value={linhaDados} onChange={(e) => setLinhaDados(Number(e.target.value))} />
            </Campo>
            <Campo rotulo="Coluna do código INEP">
              <select className={estiloInput} value={colInep} onChange={(e) => setColInep(Number(e.target.value))}>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Coluna do valor">
              <select className={estiloInput} value={colValor} onChange={(e) => setColValor(Number(e.target.value))}>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Etapa (fixa, opcional)">
              <input className={estiloInput} value={etapaFixa}
                     placeholder={`ex.: ${preset.exemploEtapa ?? preset.etapa ?? EXEMPLO_ETAPA_PADRAO}`}
                     onChange={(e) => setEtapaFixa(e.target.value)} />
            </Campo>
            <Campo rotulo="Coluna da etapa (opcional)">
              <select className={estiloInput} value={colEtapa} onChange={(e) => setColEtapa(e.target.value === "" ? "" : Number(e.target.value))}>
                <option value="">— nenhuma —</option>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
            <Campo rotulo="Componente (fixo, opcional)">
              <input className={estiloInput} value={compFixo} placeholder="ex.: matematica" onChange={(e) => setCompFixo(e.target.value)} />
            </Campo>
            <Campo rotulo="Coluna do componente (opcional)">
              <select className={estiloInput} value={colComp} onChange={(e) => setColComp(e.target.value === "" ? "" : Number(e.target.value))}>
                <option value="">— nenhuma —</option>
                {cols.map((c) => <option key={c} value={c}>col {c}</option>)}
              </select>
            </Campo>
          </div>

          <div className="flex justify-end">
            <Botao onClick={importar} disabled={ocupado || !indicador.trim() || !unidade.trim()}>
              <FileUp size={15} /> {ocupado ? "Importando..." : "Importar resultados"}
            </Botao>
          </div>
          {/* A resposta da importação — inclusive a RECUSA do backend (ex.: etapa
              "anos_iniciais" num SAEB/SARESP), com a mensagem dele, palavra por palavra. */}
          {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
          {naoCasados.length > 0 && <CodigosNaoCasados codigos={naoCasados} />}

          {ehGlobal && (
            <div className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-500/30 dark:bg-indigo-500/10">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-indigo-800 dark:text-indigo-300">
                <Bot size={16} /> Automatizar (montar o robô com este mapeamento)
              </h3>
              <p className="text-xs text-zinc-600 dark:text-zinc-400">
                Guarde o endereço <b>fixo</b> do arquivo oficial (a URL de download do INEP/SEDUC),
                com o <b>mesmo mapeamento</b> que você conferiu acima: “Coletar agora”, na lista das
                fontes, baixa dessa URL e importa sem ninguém subir arquivo de novo. A coleta mensal
                automática só acontece com o robô ligado no servidor (ele vem desligado).
              </p>
              <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>Não funciona para o INEP (bloqueia downloads de servidor) — a importação que você
                acabou de fazer acima é o caminho certo. Guarde a URL só para quando isso for possível.</span>
              </p>
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-[280px] flex-1">
                  <Campo rotulo="URL do arquivo oficial">
                    <input className={estiloInput} value={urlFonte} placeholder="https://download.inep.gov.br/..."
                           onChange={(e) => setUrlFonte(e.target.value)} />
                  </Campo>
                </div>
                <Campo rotulo="Cadência">
                  <select className={estiloInput} value={cadencia} onChange={(e) => setCadencia(e.target.value)}>
                    <option value="mensal">Mensal (automática, se o robô estiver ligado)</option>
                    <option value="manual">Manual (só quando eu clicar)</option>
                  </select>
                </Campo>
                <Botao variante="neutro" onClick={salvarFonte}
                       disabled={salvandoFonte || !urlFonte.trim() || !indicador.trim() || !unidade.trim()}>
                  <Bot size={15} /> {salvandoFonte ? "Salvando..." : "Salvar fonte automática"}
                </Botao>
              </div>
              {msgFonte && <Mensagem tipo={msgFonte.tipo}>{msgFonte.texto}</Mensagem>}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// --- Fontes automáticas (o robô) — só admin global --------------------------

const _STATUS_TOM: Record<string, "ok" | "alerta" | "neutro"> = {
  ok: "ok", erro: "alerta", nunca: "neutro",
};

function quando(iso: string | null): string {
  return dataDia(iso);
}

/** O aviso depois de salvar a fonte: só promete a coleta automática quando ela acontece
 *  (cadência mensal com o robô ligado no servidor). */
function textoFonteSalva(cadencia: string, roboLigado: boolean): string {
  if (cadencia !== "mensal") {
    return "Fonte salva. Ela é baixada e importada quando você clicar em “Coletar agora”, na lista das fontes.";
  }
  return roboLigado
    ? "Fonte salva. O robô passa a baixar e importar sozinho, uma vez por mês."
    : "Fonte salva. A coleta automática está desligada neste servidor: para baixar e importar, "
      + "use “Coletar agora”, na lista das fontes.";
}

function FontesAutomaticas({ fontes, carregando, erro, recarregar }: {
  fontes: Fonte[] | null; carregando: boolean;
  erro: { message: string } | null; recarregar: () => void;
}) {
  const [ocupada, setOcupada] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  /** A fonte cujo "Remover" foi pedido: abre a confirmação (nada é apagado antes). */
  const [paraExcluir, setParaExcluir] = useState<Fonte | null>(null);

  async function acao(fn: () => Promise<unknown>, id: number, okTxt: string) {
    setOcupada(id); setMsg(null);
    try {
      await fn();
      setMsg({ tipo: "ok", texto: okTxt });
      recarregar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha na operação." });
    } finally { setOcupada(null); }
  }

  const coletar = (f: Fonte) => acao(
    () => api<Fonte>(`/avaliacoes/fontes/${f.id}/coletar`, { method: "POST" }), f.id,
    "Coleta disparada — veja o status atualizado abaixo.");
  const alternar = (f: Fonte) => acao(
    () => api<Fonte>(`/avaliacoes/fontes/${f.id}?ativo=${!f.ativo}`, { method: "PUT" }), f.id,
    f.ativo ? "Fonte pausada." : "Fonte reativada.");
  // Só depois do "Remover fonte" da confirmação; o diálogo fica aberto (ocupado) até a resposta.
  async function excluir() {
    const f = paraExcluir;
    if (!f) return;
    await acao(() => api(`/avaliacoes/fontes/${f.id}`, { method: "DELETE" }), f.id, "Fonte removida.");
    setParaExcluir(null);
  }

  return (
    <Card className="space-y-4 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
          <IconePastel icone={Bot} tom="azul" tamanho="sm" /> Coleta automática (robô)
        </h2>
        <button onClick={recarregar} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                title="Atualizar" aria-label="Atualizar">
          <RefreshCw size={15} />
        </button>
      </div>
      <p className="text-xs text-zinc-500">
        As fontes que o sistema tentaria baixar e importar sozinho (por URL fixa, casando por INEP).
      </p>
      <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <span>
          Uma fonte do INEP aqui vai ficar com <b>erro</b> (“Connection reset by peer”): os portais
          oficiais bloqueiam downloads de servidor. Pode <b>apagar (🗑)</b> a que deu erro — para
          IDEB/SAEB, o caminho é <b>“Importar resultado oficial”</b> acima.
        </span>
      </p>

      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
      {erro && !fontes && <Mensagem tipo="erro">Não foi possível carregar as fontes: {erro.message}</Mensagem>}
      {/* Refetch que falha (blip de rede) NÃO limpa a lista — surfaça o erro mesmo assim. */}
      {erro && fontes && <Mensagem tipo="erro">Não foi possível atualizar a lista: {erro.message}</Mensagem>}

      {carregando && !fontes ? <Carregando /> : fontes && fontes.length === 0 ? (
        <p className="flex items-center gap-2 py-4 text-sm text-zinc-500">
          <Info size={16} /> Nenhuma fonte automática cadastrada ainda.
        </p>
      ) : fontes && (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {fontes.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-[200px] flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {f.nome}
                  <Badge tom={_STATUS_TOM[f.ultimo_status] ?? "neutro"}>{f.ultimo_status}</Badge>
                  {!f.ativo && <Badge tom="neutro">pausada</Badge>}
                </p>
                <p className="truncate text-xs text-zinc-500" title={f.url}>{f.url}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-zinc-400">
                  <span className="inline-flex items-center gap-1">
                    <Clock size={12} /> última: {quando(f.ultima_coleta)}
                  </span>
                  <span>cadência: {f.cadencia}</span>
                  {f.cadencia === "mensal" && f.ativo && (f.robo_habilitado
                    ? <span>próxima: {quando(f.proxima_coleta)}</span>
                    : <span>coleta automática desligada: use “Coletar agora”</span>)}
                  {f.ultimo_status === "erro" && f.ultimo_erro && (
                    <span className="text-amber-600 dark:text-amber-400">{f.ultimo_erro}</span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <Botao variante="neutro" onClick={() => coletar(f)} disabled={ocupada === f.id}>
                  <RefreshCw size={14} /> Coletar agora
                </Botao>
                <button onClick={() => alternar(f)} disabled={ocupada === f.id}
                        className="rounded-lg border border-zinc-200 p-2 text-zinc-500 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                        title={f.ativo ? "Pausar" : "Reativar"} aria-label={f.ativo ? "Pausar" : "Reativar"}>
                  {f.ativo ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <button type="button" onClick={() => setParaExcluir(f)} disabled={ocupada === f.id}
                        className="rounded-lg border border-zinc-200 p-2 text-red-500 hover:bg-red-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-red-500/10"
                        title="Remover" aria-label={`Remover a fonte ${f.nome}`}>
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Confirmacao
        titulo="Remover a fonte automática?"
        aberto={paraExcluir !== null}
        aoFechar={() => setParaExcluir(null)}
        aoConfirmar={() => void excluir()}
        rotuloConfirmar={paraExcluir && ocupada === paraExcluir.id ? "Removendo..." : "Remover fonte"}
        variante="perigo"
        ocupado={paraExcluir !== null && ocupada === paraExcluir.id}
      >
        {paraExcluir && (
          <p>Remover a fonte <strong>“{paraExcluir.nome}”</strong>? Os resultados já importados permanecem.</p>
        )}
      </Confirmacao>
    </Card>
  );
}

// --- Importar em 1 CLIQUE (mapeamento já conhecido) --------------------------
// O gestor escolhe a base (IDEB/SAEB) e sobe o arquivo oficial do INEP; o sistema
// aplica o mapeamento sozinho (SAEB traz Matemática e Português numa leitura só).
// O download continua manual (o INEP bloqueia servidor) — o resto é 1 clique.

interface PresetImport { chave: string; rotulo: string; avaliacao: string; dica: string }
interface RespPreset {
  rotulo: string; edicao: number;
  series: {
    componente: string | null; coluna?: string | null; casados: number; inseridos: number;
    atualizados: number; mantidos_oficiais?: number; nao_casados?: number;
    inep_nao_casados?: string[];
  }[];
}

function ImportarUmClique({ aoImportar }: { aoImportar: () => void }) {
  const { dados: presets } = useApi<PresetImport[]>("/avaliacoes/presets-import");
  const [idx, setIdx] = useState(0);
  const [edicao, setEdicao] = useState(new Date().getFullYear() - 2);
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [naoCasados, setNaoCasados] = useState<string[]>([]);
  const preset = presets?.[idx];

  async function importar(f: File) {
    if (!preset) return;
    setOcupado(true); setMsg(null); setNaoCasados([]);
    try {
      const fd = new FormData();
      fd.append("arquivo", f);
      fd.append("preset", preset.chave);
      fd.append("edicao", String(edicao));
      const r = await apiUpload<RespPreset>("/avaliacoes/importar-preset", fd);
      // O tom diz se algo foi GRAVADO: a escola casada que já tem o número oficial (com
      // prévia) fica como está e é contada em `mantidos_oficiais`.
      const gravados = r.series.reduce((m, s) => m + s.inseridos + s.atualizados, 0);
      const mantidos = r.series.reduce((m, s) => m + (s.mantidos_oficiais ?? 0), 0);
      // No arquivo do INEP a coluna é achada pelo NOME (ex.: VL_OBSERVADO_2023):
      // mostrar de onde saiu cada série deixa a edição conferível.
      const detalhe = r.series
        .map((s) => `${s.componente ?? "resultado"}${s.coluna ? ` (${s.coluna})` : ""}: ${s.casados}`)
        .join(" · ");
      // A edição vem ANTES do rótulo: o da estimativa termina em "— não é o
      // indicador oficial", e "… oficial (2025) importado" se lia como uma frase só.
      // O título segue o tom: sem nada gravado (nenhuma casada, ou todas mantidas) nunca
      // diz "Importado" — os mantidos, quando há, explicam o porquê logo depois.
      const titulo = gravados === 0 ? "Nada gravado" : "Importado";
      setMsg({
        tipo: gravados > 0 ? "ok" : "erro",
        texto: `${titulo} (${r.edicao}): ${r.rotulo} — ${detalhe} escola(s) casada(s) por INEP.`
          + (mantidos > 0 ? ` ${textoMantidos(mantidos)}` : ""),
      });
      // Séries do mesmo arquivo (SAEB Mat/Port): a lista é a UNIÃO dos códigos.
      setNaoCasados([...new Set(r.series.flatMap((s) => s.inep_nao_casados ?? []))].sort());
      aoImportar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Falha ao importar." });
    } finally { setOcupado(false); }
  }

  return (
    <Card className="space-y-4 p-5">
      <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
        <IconePastel icone={FileUp} tom="teal" tamanho="sm" /> Importar em 1 clique
      </h2>
      <p className="text-xs text-zinc-500">
        Escolha a base e suba o arquivo — o sistema <b>já sabe ler as colunas</b> e casa por código
        INEP, sem você mapear nada. O <b>SAEB</b> traz Matemática e Português de uma vez; o
        <b> IDEB/SAEB</b> saem do próprio arquivo do INEP; a <b>SARESP</b> e a <b>estimativa de
        alfabetização do Constela</b> (não oficial), dos arquivos que o Constela prepara.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Campo rotulo="Base a importar">
          <select className={estiloInput} value={idx}
                  onChange={(e) => { setIdx(Number(e.target.value)); setMsg(null); }}>
            {(presets ?? []).map((p, i) => <option key={p.chave} value={i}>{p.rotulo}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Edição (ano)">
          <input type="number" className={`${estiloInput} w-28`} value={edicao}
                 onChange={(e) => setEdicao(Number(e.target.value))} />
        </Campo>
        <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-500 ${ocupado || !preset ? "pointer-events-none opacity-50" : ""}`}>
          <Upload size={15} /> {ocupado ? "Importando..." : "Escolher arquivo e importar"}
          <input type="file" accept={ACEITA_ARQUIVO} className="hidden"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) importar(f); e.target.value = ""; }} />
        </label>
      </div>
      {preset?.dica && (
        <p className="flex items-start gap-1.5 rounded-lg bg-indigo-50 p-2.5 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300">
          <Info size={14} className="mt-0.5 shrink-0" /> {preset.dica}
        </p>
      )}
      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
      {naoCasados.length > 0 && <CodigosNaoCasados codigos={naoCasados} />}
    </Card>
  );
}

// --- Página ------------------------------------------------------------------

/** Cabeçalho da página (o mesmo com e sem rede): título e a descrição de uma linha. */
function Cabecalho({ ehGlobal }: { ehGlobal: boolean }) {
  return (
    <PageHeader
      titulo={ehGlobal ? "Importações e fontes" : "Fontes dos indicadores"}
      descricao={ehGlobal
        ? "Fontes e arquivos oficiais (detalhe técnico): cada indicador oficial (ICA, SARESP, Ideb e Saeb) com o detalhe dos números, a cobertura por escola e o arquivo de origem — e a importação, a prévia e o desfazer."
        : "Fontes e arquivos oficiais (detalhe técnico): cada indicador oficial (ICA, SARESP, Ideb e Saeb) com o detalhe dos números, a cobertura por escola e o arquivo de origem. Para entender os resultados, comece por Avaliações externas."}
    />
  );
}

function Painel({ redeId, podeImportar, ehGlobal }: {
  redeId: number; podeImportar: boolean; ehGlobal: boolean;
}) {
  const { dados: opcoes, carregando, erro: erroOpcoes, recarregar } = useApi<SerieOpcao[]>(
    `/redes/${redeId}/avaliacoes/opcoes`);
  const { dados: catalogo } = useApi<CatalogoItem[]>("/avaliacoes");
  // Lista das fontes do robô: vive AQUI (não dentro de FontesAutomaticas) para que
  // salvar uma fonte no bloco de importação (componente irmão) a atualize.
  const fontesApi = useApi<Fonte[]>(ehGlobal ? "/avaliacoes/fontes" : null);
  // Aplicar ou desfazer uma importação oficial (ou gravar o CODMUN) remonta os cartões do
  // SARESP e do Ideb/Saeb e relê as séries importadas: eles mostram na hora o que mudou.
  const [versaoOficiais, setVersaoOficiais] = useState(0);
  // A importação do ICA mudou algo da rede (inclusive o código IBGE, de que o SARESP e o
  // Ideb/Saeb também dependem): os dois cartões e a importação oficial releem.
  const [versaoIca, setVersaoIca] = useState(0);

  return (
    <div className="space-y-6">
      <Cabecalho ehGlobal={ehGlobal} />

      <CartaoAvaliacoesExternas redeId={redeId} ehGlobal={ehGlobal} />

      <CartaoICA redeId={redeId} ehGlobal={ehGlobal} aoMudar={() => setVersaoIca((v) => v + 1)} />
      <CartaoSARESP key={`saresp-${versaoOficiais}-${versaoIca}`} redeId={redeId} ehGlobal={ehGlobal} />
      <CartaoIDEB key={`ideb-${versaoOficiais}-${versaoIca}`} redeId={redeId} ehGlobal={ehGlobal} />
      <ImportarIndicadoresOficiais redeId={redeId} ehGlobal={ehGlobal} versaoRede={versaoIca}
                                   aoMudar={() => { setVersaoOficiais((v) => v + 1); recarregar(); }} />

      {carregando && !opcoes ? (
        <Carregando texto="Carregando avaliações..." />
      ) : erroOpcoes && !opcoes ? (
        <Card className="p-4">
          <Mensagem tipo="erro">
            Não foi possível carregar as avaliações: {erroOpcoes.message}
          </Mensagem>
        </Card>
      ) : opcoes && opcoes.length > 0 ? (
        podeImportar && <RemoverEdicao opcoes={opcoes} aoRemover={recarregar} />
      ) : (
        <Card className="p-6">
          <p className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            <Info size={16} aria-hidden className="shrink-0 text-indigo-500" /> Ainda não há resultados de avaliação importados para esta rede.
            {podeImportar
              ? " Importe um arquivo oficial abaixo para começar."
              : " Os resultados oficiais são importados pelo administrador global do Constela."}
          </p>
        </Card>
      )}

      {podeImportar && <ImportarUmClique aoImportar={recarregar} />}

      {podeImportar && catalogo && (
        <ImportarAvaliacao catalogo={catalogo} aoImportar={recarregar}
                           ehGlobal={ehGlobal} aoSalvarFonte={fontesApi.recarregar} />
      )}

      {ehGlobal && (
        <FontesAutomaticas fontes={fontesApi.dados} carregando={fontesApi.carregando}
                           erro={fontesApi.erro} recarregar={fontesApi.recarregar} />
      )}
    </div>
  );
}

export default function RedeAvaliacoes() {
  const { usuario } = useApp();
  const navegar = useNavigate();
  const redeDoUsuario = usuario?.rede_id ?? null;
  const { dados: redes, carregando, erro: erroRedes, recarregar: recarregarRedes } =
    useApi<{ id: number; nome: string }[]>(redeDoUsuario == null ? "/redes" : null);
  const redeId = redeDoUsuario ?? redes?.[0]?.id ?? null;
  const ehGlobal = Boolean(usuario?.is_global);
  // Importar e desfazer (inclusive "Remover edição"): SÓ o admin global (decisão D4).
  // A Secretaria — que costuma ter cargo "coordenador" — fica só com a leitura.
  const podeImportar = ehGlobal;

  const conteudo = useMemo(() => {
    if (redeId == null) {
      // A página tem h1 (e a descrição) também sem rede (antes ficava sem título nenhum).
      const cabecalho = <Cabecalho ehGlobal={ehGlobal} />;
      // Carregando: sem h1 provisório (seria trocado pelo do painel logo em seguida).
      if (carregando) return <Carregando texto="Carregando as redes..." />;
      if (erroRedes) {
        return (
          <div>
            {cabecalho}
            <Card><Erro titulo="Não foi possível carregar as redes" descricao={erroRedes.message} aoTentar={recarregarRedes} /></Card>
          </div>
        );
      }
      // Admin Global sem rede nenhuma: a mesma mensagem e o mesmo "Gerenciar redes" das
      // telas irmãs (/rede, /rede/analise, /rede/ranking) — antes dizia que a conta dele
      // não estava vinculada a uma rede, sem ação nenhuma.
      return (
        <div>
          {cabecalho}
          <Card>
            <Vazio
              icone={ehGlobal ? Landmark : Info}
              titulo="Nenhuma rede disponível"
              descricao={ehGlobal
                ? "Ainda não há redes cadastradas. Crie a primeira para habilitar as importações e as fontes da rede."
                : "Sua conta não está vinculada a uma rede/Secretaria."}
              acao={ehGlobal ? (
                <Botao onClick={() => navegar("/rede/gerenciar")}>
                  <Settings2 size={15} aria-hidden /> Gerenciar redes
                </Botao>
              ) : undefined}
            />
          </Card>
        </div>
      );
    }
    return <Painel redeId={redeId} podeImportar={podeImportar} ehGlobal={ehGlobal} />;
  }, [redeId, carregando, erroRedes, podeImportar, ehGlobal, recarregarRedes, navegar]);

  return conteudo;
}
