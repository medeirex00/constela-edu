/**
 * Importação do ICA oficial — só o admin global (até a decisão D4).
 *
 * Fluxo: subir a planilha do INEP (ou o PACOTE recortado dos microdados, que a
 * linha de comando `preparar` gera nesta máquina) → PRÉVIA (o que mudaria; nada
 * gravado) → APLICAR (reenvia o MESMO arquivo; o servidor confere o sha256) → e,
 * se preciso, DESFAZER uma importação aplicada pelo id (volta exatamente ao estado
 * anterior; se uma importação posterior usa os mesmos números, a tela diz qual
 * desfazer antes).
 * Rede sem código IBGE: a prévia é recusada e aqui se cadastra o código — o
 * Constela não o adivinha. O NOME da rede aparece no título e no campo: o código
 * vai para a rede do cartão, e o admin precisa ver qual é antes de gravar.
 */
import { FileUp, RotateCcw, Upload } from "lucide-react";
import { useState } from "react";

import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Botao, Campo, Confirmacao, Mensagem, estiloInput } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { ApiError, api, apiUpload } from "../../lib/api";
import { dataHora } from "../../lib/formato";

interface Mudanca {
  tipo: "nova" | "alterada" | "fonte";
  territorio: string;
  indicador: string;
  /** Só na distribuição por nível ("0" a "8"). */
  nivel?: string | null;
  rede_ensino?: string;
  edicao: number;
  antes: number | null;
  antes_detalhe: number | null;
  antes_casas?: number | null;
  antes_casas_detalhe?: number | null;
  antes_motivo: string | null;
  depois: number | null;
  depois_detalhe: number | null;
  depois_casas?: number | null;
  depois_casas_detalhe?: number | null;
  depois_motivo: string | null;
}
interface Importacao {
  id: number;
  status: "previa" | "aplicada" | "desfeita";
  arquivo_nome: string;
  edicao_arquivo: number;
  arquivo_data: string | null;
  contadores: Record<string, number>;
  avisos: string[];
  created_at: string | null;
  aplicado_em: string | null;
  mudancas?: Mudanca[];
  modo?: string;
  pode_desfazer?: boolean;
  /** Id da importação posterior que usa os mesmos números (desfazer antes ela). */
  bloqueada_por?: number | null;
}

const INDICADORES: Record<string, string> = {
  percentual_alfabetizado: "resultado",
  meta: "meta",
  nivel_municipio: "nível",
  participacao: "participação",
  media_lp: "média de LP",
  pct_nivel: "nível",
};
const STATUS: Record<string, string> = { previa: "prévia", aplicada: "aplicada", desfeita: "desfeita" };

const mensagemDe = (e: unknown, padrao: string) => (e instanceof ApiError ? e.message : padrao);

/** Na precisão publicada (27,90 continua 27,90), quando a API a informa. */
function numeroTexto(valor: number, casas: number | null | undefined): string {
  return casas == null
    ? valor.toLocaleString("pt-BR")
    : valor.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function valorTexto(valor: number | null, detalhe: number | null, motivo: string | null,
                    casas?: number | null, casasDetalhe?: number | null): string {
  if (valor == null) return motivo ? `ausente (${motivo})` : "—";
  const base = numeroTexto(valor, casas);
  return detalhe != null ? `${base} (${numeroTexto(detalhe, casasDetalhe)})` : base;
}

/** Só o dia da data interna do arquivo (a que decide entre versões da mesma edição). */
function diaInterno(iso: string | null): string | null {
  const [a, m, d] = (iso ?? "").slice(0, 10).split("-");
  return a && m && d ? `${d}/${m}/${a}` : null;
}

function CodigoIbge({ redeId, redeNome, aoSalvar, aoErrar }: {
  redeId: number; redeNome: string; aoSalvar: (texto: string) => void; aoErrar: (texto: string) => void;
}) {
  const [codigo, setCodigo] = useState("");
  const valido = /^\d{7}$/.test(codigo);
  async function salvar() {
    try {
      await api(`/redes/${redeId}`, { method: "PATCH", body: JSON.stringify({ codigo_ibge: codigo }) });
      aoSalvar(`Código IBGE ${codigo} gravado na rede “${redeNome}”. Envie a prévia de novo.`);
    } catch (e) {
      aoErrar(mensagemDe(e, "Não foi possível gravar o código."));
    }
  }
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Campo rotulo={`Código IBGE do município da rede “${redeNome}” (7 dígitos)`}>
        <input className={`${estiloInput} w-40`} inputMode="numeric" value={codigo}
               onChange={(e) => setCodigo(e.target.value.replace(/\D/g, "").slice(0, 7))} />
      </Campo>
      <Botao variante="neutro" disabled={!valido} onClick={salvar}>Gravar código</Botao>
    </div>
  );
}

export default function ImportarICA({ redeId, redeNome, semCodigoIbge, aoMudar }: {
  redeId: number; redeNome: string; semCodigoIbge: boolean; aoMudar: () => void;
}) {
  const lista = useApi<Importacao[]>(`/redes/${redeId}/indicadores/importacoes`);
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [previa, setPrevia] = useState<Importacao | null>(null);
  const [urlOrigem, setUrlOrigem] = useState("");
  const [lastModified, setLastModified] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [pedeCodigo, setPedeCodigo] = useState(false);
  /** A importação cujo "Desfazer" foi pedido: abre a confirmação (nada é desfeito antes). */
  const [paraDesfazer, setParaDesfazer] = useState<Importacao | null>(null);

  function atualizar() {
    lista.recarregar();
    aoMudar();
  }

  async function gerarPrevia(f: File) {
    setArquivo(f); setPrevia(null); setMsg(null); setOcupado(true);
    const fd = new FormData();
    fd.append("arquivo", f);
    if (urlOrigem.trim()) fd.append("url_origem", urlOrigem.trim());
    if (lastModified.trim()) fd.append("last_modified_origem", lastModified.trim());
    try {
      setPrevia(await apiUpload<Importacao>(`/redes/${redeId}/indicadores/ica/previa`, fd));
      lista.recarregar();
    } catch (e) {
      const texto = mensagemDe(e, "Não foi possível ler o arquivo.");
      setPedeCodigo(texto.includes("código IBGE"));
      setMsg({ tipo: "erro", texto });
    } finally { setOcupado(false); }
  }

  async function aplicar() {
    if (!previa || !arquivo) return;
    setOcupado(true); setMsg(null);
    const fd = new FormData();
    fd.append("previa_id", String(previa.id));
    fd.append("arquivo", arquivo);
    try {
      const r = await apiUpload<Importacao>(`/redes/${redeId}/indicadores/ica/aplicar`, fd);
      const c = r.contadores;
      setMsg({ tipo: "ok", texto: `Importação aplicada: ${c.novas ?? 0} nova(s), ${c.alteradas ?? 0} alterada(s), ${c.iguais ?? 0} igual(is).` });
      setPrevia(null); setArquivo(null);
      atualizar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: mensagemDe(e, "Não foi possível aplicar.") });
    } finally { setOcupado(false); }
  }

  /** Só depois do "Desfazer importação" da confirmação. O resultado (ou a recusa) fica na tela. */
  async function desfazer() {
    const imp = paraDesfazer;
    if (!imp) return;
    setOcupado(true); setMsg(null);
    try {
      await api(`/redes/${redeId}/indicadores/importacoes/${imp.id}/desfazer`, { method: "POST" });
      setMsg({ tipo: "ok", texto: `Importação de “${imp.arquivo_nome}” desfeita.` });
      atualizar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: mensagemDe(e, "Não foi possível desfazer.") });
    } finally { setOcupado(false); setParaDesfazer(null); }
  }

  const c = previa?.contadores ?? {};
  return (
    <div className="space-y-3 border-t border-zinc-200 pt-4 dark:border-zinc-800">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <FileUp size={15} className="text-indigo-600" /> Importar o ICA oficial para a rede “{redeNome}” (admin global)
      </h3>
      <p className="text-xs text-zinc-500">
        Suba a planilha do INEP como baixada — por município (resultados_e_metas_municipios_*.xlsx) ou
        por UF e Brasil (resultados_e_metas_ufs_*.xlsx) — ou o <b>pacote dos microdados</b>{" "}
        (pacote_ica_aeeb_*.zip, média de LP e níveis 0–8), gerado nesta máquina com{" "}
        <code className="rounded bg-zinc-100 px-1 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">python -m app.services.indicadores.preparar</code>.
        Primeiro vem a <b>prévia</b>: nada é gravado até você aplicar. Entre arquivos, a capa é a planilha mais
        recente; as casas decimais dos outros (inclusive dos microdados) aparecem como detalhe.
      </p>
      {(semCodigoIbge || pedeCodigo) && (
        <CodigoIbge
          redeId={redeId}
          redeNome={redeNome}
          // A confirmação fica AQUI (não no campo): gravado o código, o cartão recarrega,
          // a pendência some e o campo desmonta — a mensagem continua na tela.
          aoSalvar={(texto) => { setPedeCodigo(false); setMsg({ tipo: "ok", texto }); atualizar(); }}
          aoErrar={(texto) => setMsg({ tipo: "erro", texto })}
        />
      )}
      <div className="flex flex-wrap items-end gap-3">
        <Campo rotulo="URL de origem (opcional; no pacote, vale a do manifesto)">
          <input className={`${estiloInput} w-72`} value={urlOrigem} placeholder="https://download.inep.gov.br/..."
                 onChange={(e) => setUrlOrigem(e.target.value)} />
        </Campo>
        <Campo rotulo="Publicado em (Last-Modified, opcional; idem)">
          <input className={`${estiloInput} w-56`} value={lastModified}
                 onChange={(e) => setLastModified(e.target.value)} />
        </Campo>
        {/* `sr-only` (e não `hidden`): o campo de arquivo continua alcançável pelo Tab. */}
        <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-500 focus-within:ring-2 focus-within:ring-indigo-400 focus-within:ring-offset-2 dark:focus-within:ring-offset-zinc-900 ${ocupado ? "pointer-events-none opacity-50" : ""}`}>
          <Upload size={15} /> {ocupado && !previa ? "Lendo..." : "Escolher arquivo e ver prévia"}
          <input type="file" accept=".xlsx,.zip" className="sr-only" aria-label="Planilha oficial do ICA"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) gerarPrevia(f); e.target.value = ""; }} />
        </label>
      </div>

      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}

      {previa && (
        <div className="space-y-2 rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800" data-testid="ica-previa">
          <p className="font-medium">
            Prévia de “{previa.arquivo_nome}” (avaliação {previa.edicao_arquivo},{" "}
            {diaInterno(previa.arquivo_data) ? `arquivo de ${diaInterno(previa.arquivo_data)}` : "arquivo sem data interna"})
            {" "}— nada foi gravado.
          </p>
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            {c.novas ?? 0} nova(s) · {c.alteradas ?? 0} alterada(s) · {c.iguais ?? 0} igual(is)
            {c.fonte_atualizada ? ` · ${c.fonte_atualizada} só com a fonte atualizada` : ""}
            {c.ausentes ? ` · ${c.ausentes} ausência(s) registrada(s)` : ""}
          </p>
          {previa.avisos.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-700 dark:text-amber-300">
              {previa.avisos.map((a) => <li key={a}>{a}</li>)}
            </ul>
          )}
          {(previa.mudancas ?? []).length > 0 && (
            <table className="w-full text-xs">
              <caption className="sr-only">O que mudaria</caption>
              <thead>
                <tr className="text-left text-zinc-500">
                  <th className="py-1 pr-2 font-medium">Território</th>
                  <th className="py-1 pr-2 font-medium">Número</th>
                  <th className="py-1 pr-2 font-medium">Antes</th>
                  <th className="py-1 font-medium">Depois</th>
                </tr>
              </thead>
              <tbody>
                {(previa.mudancas ?? []).map((m) => (
                  <tr key={`${m.territorio}-${m.rede_ensino ?? ""}-${m.indicador}-${m.nivel ?? ""}-${m.edicao}`}
                      className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="py-1 pr-2">{m.territorio}</td>
                    <td className="py-1 pr-2">
                      {INDICADORES[m.indicador] ?? m.indicador}{m.nivel != null ? ` ${m.nivel}` : ""} {m.edicao}
                    </td>
                    <td className="py-1 pr-2 tabular-nums">
                      {m.tipo === "nova" ? "—" : valorTexto(m.antes, m.antes_detalhe, m.antes_motivo, m.antes_casas, m.antes_casas_detalhe)}
                    </td>
                    <td className="py-1 tabular-nums">
                      {valorTexto(m.depois, m.depois_detalhe, m.depois_motivo, m.depois_casas, m.depois_casas_detalhe)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="flex gap-2">
            <Botao onClick={aplicar} disabled={ocupado}>Aplicar esta prévia</Botao>
            <Botao variante="neutro" onClick={() => { setPrevia(null); setArquivo(null); }} disabled={ocupado}>
              Descartar
            </Botao>
          </div>
        </div>
      )}

      {lista.erro && !lista.dados && (
        <Mensagem tipo="erro">Não foi possível carregar as importações: {lista.erro.message}</Mensagem>
      )}
      {(lista.dados ?? []).length > 0 && (
        <TabelaRolavel rotulo="Histórico de importações do ICA: tabela completa">
          <table className="w-full text-xs">
            <caption className="sr-only">Importações do ICA desta rede</caption>
            <thead>
              <tr className="text-left text-zinc-500">
                <th className="py-1 pr-2 font-medium">Arquivo</th>
                <th className="py-1 pr-2 font-medium">Avaliação</th>
                <th className="py-1 pr-2 font-medium">Situação</th>
                <th className="py-1 pr-2 font-medium">Quando</th>
                <th className="py-1 font-medium" />
              </tr>
            </thead>
            <tbody>
              {(lista.dados ?? []).map((i) => (
                <tr key={i.id} className="border-t border-zinc-100 dark:border-zinc-800">
                  <td className="py-1 pr-2">
                    #{i.id} · {i.arquivo_nome}
                    {i.modo === "pacote_cli" && <span className="text-zinc-500"> (pacote dos microdados)</span>}
                  </td>
                  <td className="py-1 pr-2 tabular-nums">{i.edicao_arquivo}</td>
                  <td className="py-1 pr-2">{STATUS[i.status] ?? i.status}</td>
                  <td className="py-1 pr-2">{dataHora(i.aplicado_em ?? i.created_at)}</td>
                  <td className="py-1 text-right">
                    {i.pode_desfazer ? (
                      <Botao variante="neutro" className="px-2 py-1 text-xs" disabled={ocupado}
                             aria-label={`Desfazer a importação #${i.id}`} onClick={() => setParaDesfazer(i)}>
                        <RotateCcw size={13} aria-hidden="true" /> Desfazer
                      </Botao>
                    ) : i.status === "aplicada" && i.bloqueada_por ? (
                      <span className="text-zinc-500">para desfazer, desfaça antes a #{i.bloqueada_por}</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TabelaRolavel>
      )}

      <Confirmacao
        titulo="Desfazer a importação?"
        aberto={paraDesfazer !== null}
        aoFechar={() => setParaDesfazer(null)}
        aoConfirmar={() => void desfazer()}
        rotuloConfirmar={ocupado ? "Desfazendo..." : "Desfazer importação"}
        variante="perigo"
        ocupado={ocupado}
      >
        {paraDesfazer && (
          <p>
            Desfazer a importação <strong>#{paraDesfazer.id}</strong> (“{paraDesfazer.arquivo_nome}”)? Os números
            voltam exatamente ao estado anterior a ela.
          </p>
        )}
      </Confirmacao>
    </div>
  );
}
