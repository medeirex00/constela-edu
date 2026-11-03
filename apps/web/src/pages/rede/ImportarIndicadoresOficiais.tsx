/**
 * Importação dos indicadores oficiais que não são o ICA — SARESP e IEE (SEDUC-SP), Ideb
 * e Saeb (INEP) — numa tela só (decisão D-C, opção (a)). Só o admin global (D4): o
 * backend exige (`exigir_admin_global`) e a tela não aparece para mais ninguém — nem
 * chama a API.
 *
 * Mesmo fluxo e mesmo padrão do `ImportarICA`:
 *  1. escolher a FONTE — cada uma diz qual arquivo usar e de onde ele vem (os pacotes do
 *     Ideb e do Saeb são gerados NESTA máquina pelo comando `preparar`);
 *  2. subir o arquivo → PRÉVIA (o que mudaria; nada gravado), com os contadores, os
 *     avisos e as recusas da API;
 *  3. se a prévia troca números por escola gravados SEM registro oficial (no SARESP, a
 *     média calculada pelo Constela — decisão D2), a pergunta sim/não EXPLÍCITA, sem
 *     opção marcada; "Aplicar" fica bloqueado até a resposta;
 *  4. APLICAR reenvia o MESMO arquivo da prévia (o servidor confere o sha256), depois de
 *     uma confirmação;
 *  5. a lista das importações da família, com DESFAZER e a recusa ("desfaça antes a #N")
 *     visível;
 *  6. o CODMUN da rede (código do município na SEDUC-SP — não é o IBGE), gravado por
 *     `PATCH /redes/{id}`; o valor atual vem de `GET /redes`.
 *
 * Montada em `RedeAvaliacoes`, logo abaixo dos cartões do SARESP e do Ideb/Saeb que ela
 * alimenta; `aoMudar` faz a página reler esses cartões depois de aplicar, desfazer ou
 * gravar o CODMUN. Os tipos das respostas ficam em `indicadoresImportacao.ts`.
 */
import { FileUp, RotateCcw, Upload } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { Badge, Botao, Campo, Card, Confirmacao, IconePastel, Mensagem, estiloInput } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { ApiError, api, apiUpload } from "../../lib/api";
import { dataHora } from "../../lib/formato";
import {
  ROTULO_PARSER,
  ROTULO_STATUS,
  ROTULO_TIPO,
  diaDoArquivoInterno,
  rotuloNumero,
  separaLocalizacao,
  valorImportacao,
  type FamiliaImportacao,
  type ImportacaoOficial,
  type MudancaImportacao,
  type RedeResumo,
} from "./indicadoresImportacao";

type ChaveFonte = "saresp_municipio" | "saresp_instancia" | "iee" | "ideb" | "saeb";

interface Fonte {
  chave: ChaveFonte;
  familia: FamiliaImportacao;
  orgao: "SEDUC-SP" | "INEP";
  rotulo: string;
  /** Os parsers que a API pode devolver para esta fonte (o SEDUC é detectado pelo cabeçalho). */
  parsers: string[];
  aceita: string;
  /** Pede o ano quando o nome do arquivo não o traz (só o SARESP por município e por instância). */
  pedeEdicao: boolean;
  explicacao: ReactNode;
}

const Cmd = ({ children }: { children: ReactNode }) => (
  <code className="break-all rounded bg-zinc-100 px-1 dark:bg-zinc-800">{children}</code>
);

const FONTES: Fonte[] = [
  {
    chave: "saresp_municipio", familia: "saresp", orgao: "SEDUC-SP", rotulo: "SARESP por município",
    parsers: ["seduc_saresp_municipio"], aceita: ".csv", pedeEdicao: true,
    explicacao: <>
      O CSV “Proficiência do SARESP por Município de AAAA”, dos dados abertos da SEDUC-SP, enviado do jeito que foi
      baixado. Traz a média da rede municipal (e da rede estadual) no município. <b>Precisa do CODMUN da rede</b>,
      no campo acima: sem ele, a prévia é recusada.
    </>,
  },
  {
    chave: "saresp_instancia", familia: "saresp", orgao: "SEDUC-SP", rotulo: "SARESP por instância",
    parsers: ["seduc_saresp_instancia"], aceita: ".csv", pedeEdicao: true,
    explicacao: <>
      O CSV “Proficiência do SARESP por Instância de AAAA”, dos dados abertos da SEDUC-SP, como foi baixado. Daqui
      entra só a linha do Estado de São Paulo (rede estadual e redes municipais), para comparar com a rede.
    </>,
  },
  {
    chave: "iee", familia: "saresp", orgao: "SEDUC-SP", rotulo: "IEE (Índice de Excelência Educacional)",
    parsers: ["seduc_iee"], aceita: ".csv", pedeEdicao: false,
    explicacao: <>
      O CSV “Índice de Excelência Educacional AAAA-AAAA”, dos dados abertos da SEDUC-SP, como foi baixado. Traz, por
      escola, a proficiência do SARESP no 2º e no 5º ano, a participação, o IEE e a meta. Casa pelo código INEP das
      escolas do cadastro (nunca pelo nome).
    </>,
  },
  {
    chave: "ideb", familia: "ideb", orgao: "INEP", rotulo: "Ideb (pacote)",
    parsers: ["inep_ideb_escolas", "inep_ideb_municipios", "inep_ideb_uf_brasil"], aceita: ".zip", pedeEdicao: false,
    explicacao: <>
      O <b>pacote</b> (.zip de poucos KB) que o comando <Cmd>preparar</Cmd> gera <b>nesta máquina</b> a partir do zip
      do Ideb do INEP — por escola, do município, da UF e regiões ou do Brasil. O zip do INEP não sobe para o
      servidor. Para gerar (na pasta <Cmd>backend</Cmd>):{" "}
      <Cmd>python -m app.services.indicadores.preparar --ibge &lt;código IBGE&gt; --zip &lt;zip do Ideb&gt; --saida &lt;pasta&gt;</Cmd>
    </>,
  },
  {
    chave: "saeb", familia: "saeb", orgao: "INEP", rotulo: "Saeb (pacote)",
    parsers: ["inep_saeb_planilha"], aceita: ".zip", pedeEdicao: false,
    explicacao: <>
      O <b>pacote</b> que o comando <Cmd>preparar</Cmd> gera <b>nesta máquina</b> a partir da planilha do Saeb do INEP
      (Brasil, estados e municípios). A planilha do INEP não sobe para o servidor. Para gerar (na pasta{" "}
      <Cmd>backend</Cmd>):{" "}
      <Cmd>python -m app.services.indicadores.preparar --ibge &lt;código IBGE&gt; --planilha &lt;planilha do Saeb&gt; --saida &lt;pasta&gt;</Cmd>
    </>,
  },
];

/** Por família: o nome nas mensagens e a pergunta da troca (D2) com as palavras dela. */
const FAMILIAS: Record<FamiliaImportacao, {
  rotulo: string;
  troca: { contador: string; pergunta: string; sim: string; nao: string };
}> = {
  saresp: {
    rotulo: "SARESP/IEE",
    troca: {
      contador: "média(s) calculada(s) pelo Constela a trocar pela oficial",
      pergunta: "Esta prévia troca médias por escola que o Constela calculou (sem registro oficial) pelos números "
        + "oficiais da SEDUC-SP. Confira o antes × depois e responda:",
      sim: "Sim, trocar as médias calculadas pelo Constela pelas oficiais",
      nao: "Não, manter as calculadas",
    },
  },
  ideb: {
    rotulo: "Ideb",
    troca: {
      contador: "número(s) gravado(s) sem registro oficial a trocar pelo oficial",
      pergunta: "Esta prévia troca números por escola gravados sem registro oficial (por uma importação antiga, sem "
        + "prévia), diferentes do arquivo oficial do INEP. Confira o antes × depois e responda:",
      sim: "Sim, trocar os números sem registro oficial pelos oficiais",
      nao: "Não, manter os números atuais",
    },
  },
  saeb: {
    rotulo: "Saeb",
    troca: {
      contador: "número(s) gravado(s) sem registro oficial a trocar pelo oficial",
      pergunta: "Esta prévia troca números gravados sem registro oficial pelos números oficiais do INEP. Confira o "
        + "antes × depois e responda:",
      sim: "Sim, trocar os números sem registro oficial pelos oficiais",
      nao: "Não, manter os números atuais",
    },
  },
};

/** Os contadores da prévia, na ordem em que se confere com o gabarito. `sem_linha` sai
 *  da lista `sem_linha_no_arquivo` (Ideb por escola). */
const CONTADORES: [string, string][] = [
  ["novas", "número(s) novo(s)"],
  ["alteradas", "número(s) alterado(s)"],
  ["iguais", "igual(is) ao que já está gravado (nada muda)"],
  ["substituicoes", ""],                          // o rótulo é o da família
  ["mantidas", "mantido(s): já vale um arquivo mais novo"],
  ["ausentes", "sem resultado oficial (fica registrado como ausência, nunca como zero)"],
  ["iguais_sem_proveniencia", "igual(is) aos gravados sem registro oficial (ficam como estão)"],
  ["escolas_casadas", "escola(s) da rede casada(s) pelo código INEP"],
  ["fora_do_cadastro", "escola(s) do arquivo fora do cadastro (não importadas)"],
  ["sem_linha", "escola(s) do cadastro sem linha no arquivo"],
  ["territorios", "território(s) de referência"],
  ["lidas", "linha(s) lida(s) no arquivo"],
  ["recortadas", "número(s) recortado(s) para a rede"],
];
const CONHECIDOS = new Set(CONTADORES.map(([c]) => c));
const LIMITE_MUDANCAS = 300;

/** Rede de segurança: se uma recusa do servidor ainda citar o identificador interno de
 *  um parser ("inep_ideb_escolas"), a tela mostra o nome dele em português. */
function semIdentificadores(texto: string): string {
  return texto.replace(/'?\b((?:inep|seduc)_[a-z_]+)\b'?/g,
    (trecho, id: string) => (ROTULO_PARSER[id] ? `“${ROTULO_PARSER[id]}”` : trecho));
}

/** Mensagem da API em português claro, com o que estava sendo feito. A recusa (4xx)
 *  vem do servidor já explicada ("... Nada foi gravado."). */
function explicar(e: unknown, recusa: string, falha: string): string {
  if (e instanceof ApiError) {
    const texto = semIdentificadores(e.message);
    return e.status >= 400 && e.status < 500 ? `${recusa}: ${texto}` : `${falha}: ${texto}`;
  }
  return `${falha}. Tente de novo.`;
}

const contagem = (n: number | undefined) => (n ?? 0).toLocaleString("pt-BR");

/** Quantos números a resposta da troca (D2) decide: o contador da API, a lista do antes ×
 *  depois e as linhas `substituicao` — o maior (nunca menos do que a prévia mostrou). */
function trocasDa(p: ImportacaoOficial): number {
  return Math.max(p.contadores?.substituicoes ?? 0, p.substituicoes?.length ?? 0,
                  (p.mudancas ?? []).filter((m) => m.tipo === "substituicao").length);
}

// --- CODMUN da rede -----------------------------------------------------------------

function CodigosDaRede({ redeId, rede, carregando, erro, destacarCodmun, aoGravar }: {
  redeId: number;
  rede: RedeResumo | undefined;
  carregando: boolean;
  erro: ApiError | null;
  destacarCodmun: boolean;
  aoGravar: (codigo: string) => void;
}) {
  const [codigo, setCodigo] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const nome = rede?.nome ?? `#${redeId}`;
  const atual = rede?.codigo_municipio_estadual || null;
  const soDigitos = /^\d{1,8}$/.test(codigo);
  const ehIbge = soDigitos && Boolean(rede?.codigo_ibge) && codigo === rede?.codigo_ibge;
  const igualAoAtual = soDigitos && atual != null && codigo === atual;
  const problema = codigo === "" ? null
    : !soDigitos ? "Use só dígitos (até 8), sem pontos, traços nem espaços."
    : ehIbge ? "Esse é o código IBGE da rede. O CODMUN da SEDUC-SP é outro número: o da coluna CODMUN do "
      + "arquivo do SARESP por município."
    : null;

  async function gravar() {
    setOcupado(true); setMsg(null);
    try {
      await api(`/redes/${redeId}`, {
        method: "PATCH", body: JSON.stringify({ codigo_municipio_estadual: codigo }),
      });
      setMsg({ tipo: "ok", texto: `CODMUN ${codigo} gravado na rede “${nome}”.` });
      setCodigo("");
      aoGravar(codigo);
    } catch (e) {
      setMsg({ tipo: "erro", texto: explicar(e, "O código foi recusado", "Não foi possível gravar o código") });
    } finally { setOcupado(false); }
  }

  return (
    <div className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800" data-testid="codigos-da-rede">
      <p className="text-sm font-medium">Códigos da rede “{nome}”</p>
      {erro && !rede ? (
        <Mensagem tipo="erro">Não foi possível ler os códigos atuais da rede: {erro.message}</Mensagem>
      ) : carregando && !rede ? (
        <p className="text-xs text-zinc-500">Lendo os códigos da rede...</p>
      ) : (
        <ul className="space-y-1 text-xs text-zinc-600 dark:text-zinc-400">
          <li data-testid="ibge-atual">
            {rede?.codigo_ibge
              ? <>Código IBGE do município: <b className="tabular-nums">{rede.codigo_ibge}</b> (cadastrado no cartão do ICA).</>
              : <span className="text-amber-700 dark:text-amber-300">
                  {rede ? "Sem código IBGE cadastrado: todas as importações abaixo são recusadas até ele ser gravado no "
                    + "cartão do ICA, acima."
                    : "Não encontrei esta rede entre as redes ativas: os códigos atuais não puderam ser lidos."}
                </span>}
          </li>
          <li data-testid="codmun-atual">
            {atual
              ? <>CODMUN da SEDUC-SP: <b className="tabular-nums">{atual}</b>.</>
              : rede
                ? <span className="text-amber-700 dark:text-amber-300">
                    Sem CODMUN cadastrado: o SARESP por município é recusado até ele ser gravado aqui.
                  </span>
                : null}
          </li>
        </ul>
      )}
      {destacarCodmun && (
        <p className="text-xs font-medium text-amber-700 dark:text-amber-300" data-testid="codmun-pedido">
          A prévia foi recusada por falta do CODMUN: grave-o aqui e envie o arquivo de novo.
        </p>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <Campo rotulo={`CODMUN da rede “${nome}” (código do município na SEDUC-SP)`}>
          <input className={`${estiloInput} w-40`} inputMode="numeric" value={codigo} maxLength={12}
                 aria-invalid={problema ? true : undefined} aria-describedby={`codmun-ajuda-${redeId}`}
                 onChange={(e) => { setCodigo(e.target.value.trim()); setMsg(null); }} />
        </Campo>
        <Botao variante="neutro" disabled={!soDigitos || ehIbge || igualAoAtual || ocupado} onClick={gravar}>
          {ocupado ? "Gravando..." : atual ? "Trocar CODMUN" : "Gravar CODMUN"}
        </Botao>
      </div>
      <p id={`codmun-ajuda-${redeId}`} className="text-xs text-zinc-500">
        Só dígitos. É o código do município na SEDUC-SP (a coluna CODMUN dos arquivos do SARESP); não é o código do
        IBGE. O Constela não o adivinha pelo nome do município.
      </p>
      {problema && <p className="text-xs text-red-700 dark:text-red-300" role="alert">{problema}</p>}
      {igualAoAtual && <p className="text-xs text-zinc-500">Esse já é o CODMUN gravado.</p>}
      {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
    </div>
  );
}

// --- Prévia -------------------------------------------------------------------------

/** O ANTES × DEPOIS de cada número que a resposta da troca decide — as linhas
 *  `substituicao` de `mudancas` (que dizem também QUAL número é: Ideb, proficiência...). */
function TabelaTrocas({ trocas, comLocalizacao }: { trocas: MudancaImportacao[]; comLocalizacao: boolean }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">Antes e depois de cada número que seria trocado</caption>
        <thead>
          <tr className="text-left text-zinc-500">
            <th className="py-1 pr-2 font-medium">Escola</th>
            <th className="py-1 pr-2 font-medium">Número</th>
            <th className="py-1 pr-2 font-medium">Hoje (sem registro oficial)</th>
            <th className="py-1 pr-2 font-medium">Oficial</th>
            <th className="py-1 font-medium">Diferença</th>
          </tr>
        </thead>
        <tbody>
          {trocas.map((m, i) => {
            const dif = m.antes != null && m.depois != null ? Math.round((m.depois - m.antes) * 100) / 100 : null;
            return (
              <tr key={`${i}-${m.codigo_inep ?? m.onde ?? ""}-${m.indicador}-${m.etapa ?? ""}-${m.componente ?? ""}-${m.edicao}`}
                  className="border-t border-zinc-100 align-top dark:border-zinc-800">
                <td className="py-1 pr-2">{m.onde ?? `INEP ${m.codigo_inep ?? "—"}`}</td>
                <td className="py-1 pr-2">{rotuloNumero(m, { localizacao: comLocalizacao })}</td>
                <td className="py-1 pr-2 tabular-nums">
                  {valorImportacao(m.antes, m.antes_motivo)}
                  {m.antes_fonte && <span className="block text-[11px] text-zinc-500">{m.antes_fonte}</span>}
                </td>
                <td className="py-1 pr-2 tabular-nums">{valorImportacao(m.depois, m.depois_motivo)}</td>
                <td className="py-1 tabular-nums">
                  {dif == null ? "—" : `${dif > 0 ? "+" : dif < 0 ? "−" : ""}${
                    Math.abs(dif).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Previa({ previa, fonte, resposta, aoResponder }: {
  previa: ImportacaoOficial;
  fonte: Fonte;
  resposta: "sim" | "nao" | null;
  aoResponder: (r: "sim" | "nao") => void;
}) {
  const c = previa.contadores ?? {};
  const familia = FAMILIAS[fonte.familia];
  const mudancas = previa.mudancas ?? [];
  const trocas = mudancas.filter((m) => m.tipo === "substituicao");
  // O Saeb grava total, urbana e rural separadas: o rótulo diz qual é cada linha.
  const comLocalizacao = separaLocalizacao(mudancas);
  const nTrocas = trocasDa(previa);
  const foraDoCadastro = previa.fora_do_cadastro ?? [];
  const semLinha = previa.sem_linha_no_arquivo ?? [];
  const territorios = Object.values(previa.territorios ?? {});
  const dia = diaDoArquivoInterno(previa.arquivo_data);
  const outroTipo = !fonte.parsers.includes(previa.parser);
  const valorDe = (chave: string) => (chave === "sem_linha"
    ? (previa.sem_linha_no_arquivo ? semLinha.length : undefined) : c[chave]);
  const extras = Object.entries(c).filter(([k, v]) => !CONHECIDOS.has(k) && typeof v === "number");

  return (
    <>
      <p className="font-medium">
        Prévia #{previa.id} de “{previa.arquivo_nome}”
        {previa.modo === "pacote_cli" ? " (pacote do preparar)" : ""} — {ROTULO_PARSER[previa.parser] ?? previa.parser},
        edição {previa.edicao_arquivo}{dia ? `, arquivo de ${dia}` : ""} — nada foi gravado.
      </p>
      {outroTipo && (
        <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"
           data-testid="oficiais-outro-tipo">
          Você escolheu “{fonte.rotulo}”, mas o arquivo enviado é “{ROTULO_PARSER[previa.parser] ?? previa.parser}”.
          A prévia abaixo é do que o arquivo é: confira antes de aplicar.
        </p>
      )}
      {territorios.length > 0 && <p className="text-xs text-zinc-500">Recorte: {territorios.join(", ")}.</p>}
      {(previa.edicoes ?? []).length > 1 && (
        <p className="text-xs text-zinc-500">Edições no arquivo: {(previa.edicoes ?? []).join(", ")}.</p>
      )}

      <ul className="grid grid-cols-1 gap-x-4 gap-y-0.5 text-xs text-zinc-700 sm:grid-cols-2 dark:text-zinc-300"
          aria-label="Contadores da prévia">
        {CONTADORES.map(([chave, rotulo]) => {
          const valor = valorDe(chave);
          if (valor === undefined) return null;
          return (
            <li key={chave} data-testid={`contador-${chave}`}>
              <b className="tabular-nums">{contagem(valor)}</b>{" "}
              {chave === "substituicoes" ? familia.troca.contador : rotulo}
            </li>
          );
        })}
        {extras.map(([chave, valor]) => (
          <li key={chave} data-testid={`contador-${chave}`}>
            <b className="tabular-nums">{contagem(valor)}</b> {chave.replace(/_/g, " ")}
          </li>
        ))}
      </ul>

      {previa.avisos.length > 0 && (
        <div className="text-xs text-amber-700 dark:text-amber-300">
          <p className="font-medium">Avisos da leitura do arquivo:</p>
          <ul className="list-disc space-y-0.5 pl-5">
            {previa.avisos.map((a) => <li key={a}>{a}</li>)}
          </ul>
        </div>
      )}

      {previa.cobertura && Object.keys(previa.cobertura).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">Escolas com número, por edição</summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {Object.entries(previa.cobertura).map(([ano, cob]) => (
              <li key={ano}>{ano}: Ideb em {contagem(cob.ideb)} escola(s), Saeb em {contagem(cob.saeb)}</li>
            ))}
          </ul>
        </details>
      )}
      {foraDoCadastro.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
            Escolas do arquivo fora do cadastro ({foraDoCadastro.length}) — não serão importadas
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {foraDoCadastro.map((e) => (
              <li key={`${e.codigo_inep}-${e.cie ?? ""}`}>
                INEP {e.codigo_inep}{e.nome_no_arquivo ? ` — ${e.nome_no_arquivo}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
      {semLinha.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
            Escolas do cadastro sem linha no arquivo ({semLinha.length}) — nada a importar para elas
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {semLinha.map((e) => <li key={e.escola_id}>{e.escola ?? "escola"} (INEP {e.codigo_inep})</li>)}
          </ul>
        </details>
      )}

      {mudancas.length > 0 && (
        <details className="text-xs" data-testid="oficiais-mudancas">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
            Ver o que muda, número a número ({contagem(mudancas.length)})
          </summary>
          <div className="relative mt-1 overflow-x-auto">
            <table className="w-full">
              <caption className="sr-only">O que mudaria</caption>
              <thead>
                <tr className="text-left text-zinc-500">
                  <th className="py-1 pr-2 font-medium">Onde</th>
                  <th className="py-1 pr-2 font-medium">Número</th>
                  <th className="py-1 pr-2 font-medium">O que acontece</th>
                  <th className="py-1 pr-2 font-medium">Antes</th>
                  <th className="py-1 font-medium">Depois</th>
                </tr>
              </thead>
              <tbody>
                {mudancas.slice(0, LIMITE_MUDANCAS).map((m, i) => (
                  <tr key={`${i}-${m.onde ?? ""}-${m.indicador}-${m.localizacao ?? ""}-${m.edicao}`}
                      className="border-t border-zinc-100 align-top dark:border-zinc-800">
                    <td className="py-1 pr-2">{m.onde ?? "—"}</td>
                    <td className="py-1 pr-2">{rotuloNumero(m, { localizacao: comLocalizacao })}</td>
                    <td className="py-1 pr-2">{ROTULO_TIPO[m.tipo] ?? m.tipo}</td>
                    <td className="py-1 pr-2 tabular-nums">
                      {m.tipo === "nova" ? "—" : valorImportacao(m.antes, m.antes_motivo)}
                    </td>
                    <td className="py-1 tabular-nums">{valorImportacao(m.depois, m.depois_motivo)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {mudancas.length > LIMITE_MUDANCAS && (
            <p className="mt-1 text-zinc-500">
              Mostrando os {LIMITE_MUDANCAS} primeiros de {contagem(mudancas.length)}. Os contadores acima valem para todos.
            </p>
          )}
        </details>
      )}

      {nTrocas > 0 && (
        <fieldset className="space-y-2 rounded-lg border border-amber-300 bg-amber-50/60 p-3 dark:border-amber-500/40 dark:bg-amber-500/5"
                  data-testid="oficiais-d2">
          <legend className="px-1 text-sm font-medium text-amber-900 dark:text-amber-200">
            Trocar {contagem(nTrocas)} número(s) pelo oficial?
          </legend>
          <p className="text-xs text-zinc-700 dark:text-zinc-300">{familia.troca.pergunta}</p>
          {trocas.length > 0 && <TabelaTrocas trocas={trocas} comLocalizacao={comLocalizacao} />}
          <div className="space-y-1 text-sm">
            {(["sim", "nao"] as const).map((opcao) => (
              <label key={opcao} className="flex cursor-pointer items-start gap-2">
                <input type="radio" name={`troca-${previa.id}`} value={opcao} className="mt-1"
                       checked={resposta === opcao} onChange={() => aoResponder(opcao)} />
                <span>{opcao === "sim" ? familia.troca.sim : familia.troca.nao}</span>
              </label>
            ))}
          </div>
          <p className="text-xs text-zinc-500">
            Nada vem marcado: a resposta é sua. Respondendo “não”, o resto da importação é aplicado e esses números
            ficam como estão. Nos dois casos dá para desfazer depois, pela lista abaixo.
          </p>
        </fieldset>
      )}
    </>
  );
}

// --- Componente ---------------------------------------------------------------------

/** A recusa que é a FALTA do CODMUN (e não qualquer recusa que cite o CODMUN). */
const FALTA_CODMUN = "não tem o código do município na SEDUC";
/** A recusa que é a FALTA do código IBGE da rede. */
const FALTA_IBGE = "não tem o código IBGE";

function Importador({ redeId, versaoRede, aoMudar }: {
  redeId: number; versaoRede: number; aoMudar: () => void;
}) {
  const redes = useApi<RedeResumo[]>("/redes");
  const recarregarRedes = redes.recarregar;
  // Os códigos da rede mudam também FORA desta tela (o IBGE, no cartão do ICA): a
  // página avisa por `versaoRede` e a lista de redes é relida.
  useEffect(() => {
    if (versaoRede > 0) recarregarRedes();
  }, [versaoRede, recarregarRedes]);
  const rede = (redes.dados ?? []).find((r) => r.id === redeId);
  const nomeRede = rede?.nome ?? `#${redeId}`;
  const [chaveFonte, setChaveFonte] = useState<ChaveFonte | null>(null);
  const fonte = FONTES.find((f) => f.chave === chaveFonte) ?? null;
  const base = fonte ? `/redes/${redeId}/indicadores/${fonte.familia}` : null;
  const lista = useApi<ImportacaoOficial[]>(base ? `${base}/importacoes` : null);

  const [arquivo, setArquivo] = useState<File | null>(null);
  const [previa, setPrevia] = useState<ImportacaoOficial | null>(null);
  const [resposta, setResposta] = useState<"sim" | "nao" | null>(null);
  const [edicao, setEdicao] = useState("");
  const [urlOrigem, setUrlOrigem] = useState("");
  const [lastModified, setLastModified] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [faltaCodmun, setFaltaCodmun] = useState(false);
  const [faltaIbge, setFaltaIbge] = useState(false);
  // As duas confirmações (nada é gravado nem desfeito antes do "sim" no diálogo).
  const [confirmandoAplicar, setConfirmandoAplicar] = useState(false);
  const [paraDesfazer, setParaDesfazer] = useState<ImportacaoOficial | null>(null);

  function limparPrevia() {
    setPrevia(null); setArquivo(null); setResposta(null);
  }

  /** O ano e a origem digitados valem para UM arquivo: trocar de fonte, aplicar ou
   *  descartar a prévia os apaga (senão a importação seguinte gravaria a origem do
   *  arquivo anterior). Uma recusa os mantém: é o mesmo arquivo, enviado de novo. */
  function limparCamposDoArquivo() {
    setEdicao(""); setUrlOrigem(""); setLastModified("");
  }

  function escolher(chave: ChaveFonte) {
    setChaveFonte(chave); limparPrevia(); limparCamposDoArquivo(); setMsg(null);
    setFaltaCodmun(false); setFaltaIbge(false);
  }

  function descartar() {
    limparPrevia(); limparCamposDoArquivo();
  }

  async function gerarPrevia(f: File) {
    if (!fonte || !base) return;
    limparPrevia(); setMsg(null); setFaltaCodmun(false); setFaltaIbge(false); setOcupado(true);
    const fd = new FormData();
    fd.append("arquivo", f);
    if (fonte.familia === "saresp") {
      if (fonte.pedeEdicao && /^\d{4}$/.test(edicao)) fd.append("edicao", edicao);
      if (urlOrigem.trim()) fd.append("url_origem", urlOrigem.trim());
      if (lastModified.trim()) fd.append("last_modified_origem", lastModified.trim());
    }
    try {
      const r = await apiUpload<ImportacaoOficial>(`${base}/previa`, fd);
      setPrevia(r); setArquivo(f);
      lista.recarregar();
    } catch (e) {
      const texto = explicar(e, "Prévia recusada", "Não foi possível gerar a prévia");
      // Só a recusa que É a falta do código aponta o campo — não qualquer uma que o cite
      // (ex.: "o CODMUN 901 aparece com mais de um nome no arquivo").
      setFaltaCodmun(e instanceof ApiError && e.message.includes(FALTA_CODMUN));
      setFaltaIbge(e instanceof ApiError && e.message.includes(FALTA_IBGE));
      setMsg({ tipo: "erro", texto });
    } finally { setOcupado(false); }
  }

  const nTrocas = previa ? trocasDa(previa) : 0;
  const faltaResposta = nTrocas > 0 && resposta == null;
  const idFaltaResposta = `oficiais-falta-resposta-${redeId}`;
  const anuncio = ocupado && !previa ? "Lendo o arquivo e montando a prévia..."
    : previa ? `Prévia #${previa.id} pronta, logo abaixo: nada foi gravado.${
      faltaResposta ? " Responda a pergunta da troca de números para poder aplicar." : ""}`
    : "";

  /** "Aplicar esta prévia" só abre a confirmação, que resume a prévia e a resposta da troca. */
  function pedirAplicar() {
    if (!previa || !arquivo || !fonte || !base || faltaResposta) return;
    setConfirmandoAplicar(true);
  }

  async function aplicar() {
    if (!previa || !arquivo || !fonte || !base || faltaResposta) { setConfirmandoAplicar(false); return; }
    setOcupado(true); setMsg(null);
    const fd = new FormData();
    fd.append("previa_id", String(previa.id));
    fd.append("arquivo", arquivo);                 // o MESMO arquivo da prévia (sha256)
    if (nTrocas > 0 && resposta) fd.append("substituir_calculadas", resposta);
    try {
      const r = await apiUpload<ImportacaoOficial>(`${base}/aplicar`, fd);
      const c = r.contadores ?? {};
      const trocas = (c.substituicoes_aplicadas ?? 0) + (c.substituicoes_mantidas ?? 0) > 0
        ? `; ${contagem(c.substituicoes_aplicadas)} trocado(s) pelo oficial e ${contagem(c.substituicoes_mantidas)} mantido(s)`
        : "";
      setMsg({ tipo: "ok", texto: `Importação #${r.id} aplicada: ${contagem(c.novas)} novo(s), ${
        contagem(c.alteradas)} alterado(s), ${contagem(c.iguais)} igual(is)${trocas}. Os cartões acima já foram relidos.` });
      limparPrevia();
      limparCamposDoArquivo();
      lista.recarregar();
      aoMudar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: explicar(e, "Aplicação recusada", "Não foi possível aplicar") });
    } finally { setOcupado(false); setConfirmandoAplicar(false); }
  }

  /** Só depois do "Desfazer importação" da confirmação. */
  async function desfazer() {
    const imp = paraDesfazer;
    if (!base || !imp) { setParaDesfazer(null); return; }
    setOcupado(true); setMsg(null);
    try {
      await api(`${base}/importacoes/${imp.id}/desfazer`, { method: "POST" });
      setMsg({ tipo: "ok", texto: `Importação #${imp.id} (“${imp.arquivo_nome}”) desfeita: os números voltaram ao estado anterior.` });
      lista.recarregar();
      aoMudar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: explicar(e, "Desfazer recusado", "Não foi possível desfazer") });
    } finally { setOcupado(false); setParaDesfazer(null); }
  }

  function codmunGravado() {
    setFaltaCodmun(false);
    // A prévia do SARESP por município recortou pelo código ANTERIOR: o servidor recusaria.
    if (previa?.parser === "seduc_saresp_municipio") {
      limparPrevia();
      setMsg({ tipo: "erro", texto: "A prévia aberta do SARESP por município usava o CODMUN anterior e foi "
        + "descartada: envie o arquivo de novo." });
    }
    redes.recarregar();
    aoMudar();
  }

  const familia = fonte ? FAMILIAS[fonte.familia] : null;
  return (
    <section data-testid="importar-oficiais" aria-label="Importar indicadores oficiais">
      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
            <IconePastel icone={FileUp} tom="violeta" tamanho="sm" />
            Importar indicadores oficiais para a rede “{nomeRede}”
          </h2>
          <Badge tom="destaque">só admin global</Badge>
        </div>
        <p className="text-xs text-zinc-500">
          SARESP e IEE (SEDUC-SP), Ideb e Saeb (INEP). O ICA tem a importação própria, no cartão dele. Primeiro vem
          a <b>prévia</b>: nada é gravado até você aplicar, e cada importação aplicada pode ser desfeita. Diferente do
          “Importar em 1 clique”, mais abaixo, aqui cada número guarda a fonte oficial.
        </p>

        <CodigosDaRede redeId={redeId} rede={rede} carregando={redes.carregando} erro={redes.erro}
                       destacarCodmun={faltaCodmun} aoGravar={codmunGravado} />

        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Qual arquivo você vai enviar?
          </legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {FONTES.map((f) => (
              <label key={f.chave}
                     className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-sm ${
                       chaveFonte === f.chave
                         ? "border-indigo-500 bg-indigo-50/60 dark:bg-indigo-500/10"
                         : "border-zinc-200 dark:border-zinc-800"}`}>
                <input type="radio" name={`fonte-oficial-${redeId}`} value={f.chave} className="mt-1"
                       checked={chaveFonte === f.chave} disabled={ocupado} onChange={() => escolher(f.chave)} />
                <span>{f.rotulo} <span className="text-xs text-zinc-500">({f.orgao})</span></span>
              </label>
            ))}
          </div>
        </fieldset>

        {fonte && (
          <div className="space-y-3" data-testid="oficiais-fonte">
            <p className="rounded-lg bg-indigo-50 p-2.5 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300">
              {fonte.explicacao}
            </p>
            <div className="flex flex-wrap items-end gap-3">
              {fonte.pedeEdicao && (
                <Campo rotulo="Ano do SARESP (só se o nome do arquivo não trouxer)">
                  <input className={`${estiloInput} w-28`} inputMode="numeric" value={edicao} placeholder="AAAA"
                         onChange={(e) => setEdicao(e.target.value.replace(/\D/g, "").slice(0, 4))} />
                </Campo>
              )}
              {fonte.familia === "saresp" && (
                <>
                  <Campo rotulo="Endereço de onde baixou (opcional)">
                    <input className={`${estiloInput} w-72`} value={urlOrigem} placeholder="https://dados.educacao.sp.gov.br/..."
                           onChange={(e) => setUrlOrigem(e.target.value)} />
                  </Campo>
                  <Campo rotulo="Data de publicação no site (opcional — como aparece na página de download)">
                    <input className={`${estiloInput} w-56`} value={lastModified}
                           onChange={(e) => setLastModified(e.target.value)} />
                  </Campo>
                </>
              )}
              {/* O campo de arquivo fica `sr-only` (e não `hidden`, que é display:none):
                  continua alcançável pelo Tab e pelo leitor de tela, e Enter/Espaço nele
                  abre o seletor. O foco aparece no botão (focus-within). */}
              <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-500 focus-within:ring-2 focus-within:ring-indigo-400 focus-within:ring-offset-2 dark:focus-within:ring-offset-zinc-900 ${ocupado ? "pointer-events-none opacity-50" : ""}`}>
                <Upload size={15} aria-hidden="true" /> {ocupado && !previa ? "Lendo..." : "Escolher arquivo e ver prévia"}
                <input type="file" accept={fonte.aceita} className="sr-only" disabled={ocupado}
                       aria-label={`Arquivo: ${fonte.rotulo}`}
                       onChange={(e) => { const f = e.target.files?.[0]; if (f) gerarPrevia(f); e.target.value = ""; }} />
              </label>
            </div>
            {fonte.pedeEdicao && edicao !== "" && edicao.length < 4 && (
              <p className="text-xs text-amber-700 dark:text-amber-300">
                O ano tem 4 dígitos; incompleto, ele não é enviado (vale o ano do nome do arquivo).
              </p>
            )}
            {fonte.familia !== "saresp" && (
              <p className="text-xs text-zinc-500">
                No pacote, o endereço e a data do arquivo do INEP já vêm junto, registrados pelo preparar.
              </p>
            )}
          </div>
        )}

        {/* Para o leitor de tela: a prévia pronta (que não gera Mensagem) e a pergunta da
            troca que bloqueia o "Aplicar" são anunciadas sem mover o foco. */}
        <p className="sr-only" role="status" aria-live="polite" data-testid="oficiais-anuncio">
          {anuncio}
        </p>
        {msg && <Mensagem tipo={msg.tipo}>{msg.texto}</Mensagem>}
        {/* Some quando o IBGE é gravado (no cartão do ICA): a lista de redes é relida. */}
        {faltaIbge && !rede?.codigo_ibge && (
          <p className="text-xs font-medium text-amber-700 dark:text-amber-300">
            Cadastre o código IBGE da rede no cartão do ICA, acima, e envie o arquivo de novo.
          </p>
        )}

        {previa && fonte && (
          <div className="space-y-2 rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800"
               data-testid="oficiais-previa">
            <Previa previa={previa} fonte={fonte} resposta={resposta} aoResponder={setResposta} />
            <div className="flex flex-wrap items-center gap-2">
              <Botao onClick={pedirAplicar} disabled={ocupado || faltaResposta}
                     aria-describedby={faltaResposta ? idFaltaResposta : undefined}>
                Aplicar esta prévia
              </Botao>
              <Botao variante="neutro" onClick={descartar} disabled={ocupado}>Descartar</Botao>
              {faltaResposta && (
                <span id={idFaltaResposta} className="text-xs text-amber-700 dark:text-amber-300">
                  Responda a pergunta da troca, acima, para aplicar.
                </span>
              )}
            </div>
          </div>
        )}

        {fonte && familia && (
          <div className="space-y-1" data-testid="oficiais-lista">
            <h3 className="text-sm font-medium">Importações do {familia.rotulo} nesta rede</h3>
            {lista.erro && !lista.dados ? (
              <Mensagem tipo="erro">Não foi possível carregar as importações: {lista.erro.message}</Mensagem>
            ) : lista.carregando && !lista.dados ? (
              <p className="text-xs text-zinc-500">Carregando as importações...</p>
            ) : (lista.dados ?? []).length === 0 ? (
              <p className="text-xs text-zinc-500">Nenhuma importação do {familia.rotulo} nesta rede ainda.</p>
            ) : (
              <div className="relative overflow-x-auto">
                <table className="w-full text-xs">
                  <caption className="sr-only">Importações do {familia.rotulo} desta rede</caption>
                  <thead>
                    <tr className="text-left text-zinc-500">
                      <th className="py-1 pr-2 font-medium">Arquivo</th>
                      <th className="py-1 pr-2 font-medium">Tipo</th>
                      <th className="py-1 pr-2 font-medium">Edição</th>
                      <th className="py-1 pr-2 font-medium">Situação</th>
                      <th className="py-1 pr-2 font-medium">Quando</th>
                      <th className="py-1 font-medium"><span className="sr-only">Ações</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(lista.dados ?? []).map((i) => (
                      <tr key={i.id} className="border-t border-zinc-100 align-top dark:border-zinc-800">
                        <td className="py-1 pr-2">
                          #{i.id} · {i.arquivo_nome}
                          {i.modo === "pacote_cli" && <span className="text-zinc-500"> (pacote do preparar)</span>}
                        </td>
                        <td className="py-1 pr-2">{ROTULO_PARSER[i.parser] ?? i.parser}</td>
                        <td className="py-1 pr-2 tabular-nums">{i.edicao_arquivo}</td>
                        <td className="py-1 pr-2">{ROTULO_STATUS[i.status] ?? i.status}</td>
                        <td className="py-1 pr-2">{dataHora(i.desfeito_em ?? i.aplicado_em ?? i.created_at)}</td>
                        <td className="py-1 text-right">
                          {i.pode_desfazer ? (
                            <Botao variante="neutro" className="px-2 py-1 text-xs" disabled={ocupado}
                                   aria-label={`Desfazer a importação #${i.id}`} onClick={() => setParaDesfazer(i)}>
                              <RotateCcw size={13} aria-hidden="true" /> Desfazer
                            </Botao>
                          ) : i.status === "aplicada" && i.bloqueada_por ? (
                            <span className="text-zinc-500">para desfazer, desfaça antes a #{i.bloqueada_por}</span>
                          ) : i.status === "aplicada" ? (
                            <span className="text-zinc-500">não guardou o estado anterior: não dá para desfazer</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Fora do Card: as confirmações não herdam o espaçamento entre os blocos dele. */}
      <Confirmacao
        titulo="Aplicar esta prévia?"
        aberto={confirmandoAplicar && previa !== null}
        aoFechar={() => setConfirmandoAplicar(false)}
        aoConfirmar={() => void aplicar()}
        rotuloConfirmar={ocupado ? "Aplicando..." : "Aplicar"}
        ocupado={ocupado}
      >
        {previa && (
          <>
            <p>
              Aplicar a prévia <strong>#{previa.id}</strong> (“{previa.arquivo_nome}”, {
                ROTULO_PARSER[previa.parser] ?? previa.parser}) na rede “{nomeRede}”?
            </p>
            {nTrocas > 0 && familia && (
              <p>
                Sua resposta: “{resposta === "sim" ? familia.troca.sim : familia.troca.nao}” ({nTrocas} número(s)).
              </p>
            )}
            <p>Os números passam a valer nas telas da rede. Dá para desfazer depois, pela lista de importações.</p>
          </>
        )}
      </Confirmacao>
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
            voltam exatamente ao estado anterior a ela (inclusive as médias que ela tenha trocado).
          </p>
        )}
      </Confirmacao>
    </section>
  );
}

/** A tela só existe para o admin global: para os demais, nada aparece e nada é pedido à API.
 *  `versaoRede` muda quando um código da rede é gravado fora daqui (o IBGE, no cartão do
 *  ICA): a tela relê os códigos. */
export default function ImportarIndicadoresOficiais({ redeId, ehGlobal, aoMudar, versaoRede = 0 }: {
  redeId: number; ehGlobal: boolean; aoMudar: () => void; versaoRede?: number;
}) {
  if (!ehGlobal) return null;
  return <Importador redeId={redeId} versaoRede={versaoRede} aoMudar={aoMudar} />;
}
