/**
 * Gerar certificados EM LOTE — o mesmo modal no Ranking, na Visão Geral e nas
 * Premiações (identidade visual v2, D7).
 *
 * Recebe a lista ORDENADA que a tela está mostrando e emite os certificados dos N
 * primeiros, na ordem dada, sem pular ninguém:
 *   1. escolha de quantos (Top 3/5/10 ou personalizado até 50), do modelo (chips: a
 *      arte do Elefante só com o módulo "leitura", a do Matific só com "matematica",
 *      o Geral sempre) e do bimestre impresso;
 *   2. "Verificar" chama a PRÉVIA (POST /certificados/lote/previa), que roda as MESMAS
 *      guardas da rota individual e diz, aluno por aluno, quem está apto e por que os
 *      outros não estão;
 *   3. "Gerar PDF (N aptos)" chama o lote (POST /certificados/lote) e baixa UM PDF.
 *
 * Regras que esta tela NÃO decide (são do backend) e NÃO contorna:
 *   - recusado não é substituído pelo próximo colocado (isso mudaria quem é premiado);
 *   - linha sem ficha de aluno (aluno_id nulo) fica de fora, com aviso;
 *   - a ordem é a da tela; o componente não reordena nem filtra elegibilidade.
 */
import { useEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Award,
  BookOpen,
  Calculator,
  Check,
  CheckCircle2,
  FileDown,
  Info,
  Link2Off,
  ListChecks,
  Loader2,
  Users,
  XCircle,
} from "lucide-react";

import { useModulos } from "../hooks/useModulos";
import { useMutation } from "../hooks/useMutation";
import { api, apiDownloadPost } from "../lib/api";
import type { ApiError } from "../lib/api";
import { bimestreDeHoje, semCalendarioOficial, useCalendarioBimestres } from "../lib/calendarioBimestres";
import { MAX_CERTIFICADOS_LOTE } from "../lib/tiposCertificados";
import type {
  AlunoParaCertificado,
  ItemPreviaCertificado,
  ModeloCertificado,
  PedidoLoteCertificados,
  PedidoPreviaCertificados,
  PreviaCertificados,
} from "../lib/tiposCertificados";
import { Avatar, Badge, Botao, Chip, IconePastel, Medalha, Mensagem, Modal, PosicaoBolinha, Vazio, estiloInput } from "./ui";

export interface GerarCertificadosProps {
  escolaId: number | null;
  /** A lista na ORDEM em que a tela mostra (o Top N sai daqui, sem reordenar). */
  alunos: AlunoParaCertificado[];
  /** Modelo pela aba: Leitura → "elefante", Matemática → "matific", Geral → null. */
  modeloInicial: ModeloCertificado;
  /** De onde vem a lista, ex.: "Ranking · Matemática · 4º bimestre". */
  contexto: string;
  /** Bimestre (1–4) da lista, quando o período da tela é um bimestre (ver
   *  `bimestreDoPeriodo`). Sem ele, o seletor abre no bimestre de hoje pelo calendário
   *  oficial (do backend) — ou sem número, pedindo a escolha, se o ano não tem calendário. */
  bimestreInicial?: number;
  aberto: boolean;
  aoFechar: () => void;
}

type OpcaoQuantidade = "3" | "5" | "10" | "personalizado";

const OPCOES_QUANTIDADE: { valor: OpcaoQuantidade; rotulo: string }[] = [
  { valor: "3", rotulo: "Top 3" },
  { valor: "5", rotulo: "Top 5" },
  { valor: "10", rotulo: "Top 10" },
  { valor: "personalizado", rotulo: "Personalizado" },
];

type ChaveModelo = "elefante" | "matific" | "geral";

const MODELOS: Record<ChaveModelo, { rotulo: string; icone: LucideIcon; tom: TomPilula; descricao: string }> = {
  elefante: {
    rotulo: "Elefante Letrado",
    icone: BookOpen,
    tom: "violeta",
    descricao:
      "Arte oficial do Elefante Letrado. É o certificado de desempenho da plataforma: traz a escola, o nome, o bimestre e a data, sem nota nem posição.",
  },
  matific: {
    rotulo: "Matific",
    icone: Calculator,
    tom: "teal",
    descricao:
      "Arte oficial do Matific. É o certificado de desempenho da plataforma: traz a escola, o nome, o bimestre e a data, sem nota nem posição.",
  },
  geral: {
    rotulo: "Geral",
    icone: Award,
    tom: "ambar",
    descricao:
      "Certificado de mérito: imprime a turma, a nota geral e a posição no Ranking Geral da escola, que pode ser diferente da posição desta lista.",
  },
};

const chaveDoModelo = (modelo: ModeloCertificado): ChaveModelo => modelo ?? "geral";
const modeloDaChave = (chave: ChaveModelo): ModeloCertificado => (chave === "geral" ? null : chave);

const plural = (n: number, um: string, varios: string) => (n === 1 ? `${n} ${um}` : `${n} ${varios}`);

/** O backend nomeia o lote "certificados_<modelo|geral>_<n>.pdf": o n é a contagem REAL
 *  de páginas que ele gerou (pode ser menor que o pedido se alguém deixou de ser apto). */
function quantosNoArquivo(nome: string | undefined): number | null {
  const achado = /_(\d+)\.pdf$/i.exec(nome ?? "");
  return achado ? Number(achado[1]) : null;
}

export function GerarCertificados(props: GerarCertificadosProps) {
  // Durante a verificação ou a geração o modal não fecha (Esc/fundo), como na Confirmacao.
  const [ocupado, setOcupado] = useState(false);
  return (
    <Modal
      titulo="Gerar certificados"
      aberto={props.aberto}
      aoFechar={ocupado ? () => undefined : props.aoFechar}
      largura="max-w-2xl"
    >
      {/* O corpo só existe com o modal aberto: ao reabrir, tudo volta ao padrão. */}
      <CorpoGerarCertificados {...props} ocupado={ocupado} aoMudarOcupado={setOcupado} />
    </Modal>
  );
}

export default GerarCertificados;

type Situacao = "lote" | "sem_ficha" | "repetido";

interface Linha {
  aluno: AlunoParaCertificado;
  situacao: Situacao;
  chave: string;
}

function CorpoGerarCertificados({
  escolaId,
  alunos,
  modeloInicial,
  contexto,
  bimestreInicial,
  aoFechar,
  ocupado,
  aoMudarOcupado,
}: GerarCertificadosProps & { ocupado: boolean; aoMudarOcupado: (ocupado: boolean) => void }) {
  const ids = {
    quantos: useId(),
    modelo: useId(),
    personalizado: useId(),
    dicaPersonalizado: useId(),
    bimestre: useId(),
    dicaBimestre: useId(),
    lista: useId(),
  };
  const { leitura, matematica } = useModulos();

  const [opcao, setOpcao] = useState<OpcaoQuantidade>("3");
  const [personalizado, setPersonalizado] = useState("");
  const [modeloEscolhido, setModeloEscolhido] = useState<ModeloCertificado>(modeloInicial);
  // Lista de um bimestre (ex.: Premiações do 3º, já fechado): abre NELE, não no de
  // hoje — antes, em 31/10 o 3º saía impresso como 4º se ninguém mexesse no seletor.
  const doPeriodo = bimestreInicial != null && Number.isInteger(bimestreInicial)
    && bimestreInicial >= 1 && bimestreInicial <= 4;
  // Sem lista de um bimestre, abre no de hoje pelo calendário OFICIAL, que vem do
  // backend. Ano sem calendário conhecido não tem "de hoje": o seletor abre vazio e a
  // pessoa escolhe — antes abria no 1º (de 2027 em diante, o ano todo) e esse número ia
  // impresso no certificado de quem não conferiu.
  const calendario = useCalendarioBimestres(escolaId);
  const hoje = new Date();
  const sugerido = doPeriodo ? bimestreInicial : bimestreDeHoje(hoje, calendario);
  const [bimestreEscolhido, setBimestre] = useState<string | null>(null);
  const bimestre = bimestreEscolhido ?? (sugerido != null ? String(sugerido) : "");
  const [previa, setPrevia] = useState<{ chave: string; itens: ItemPreviaCertificado[] } | null>(null);
  const [sucesso, setSucesso] = useState<{ chave: string; quantos: number } | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // Módulo fora do plano: o chip nem aparece e o modelo cai no Geral (derivado, sem
  // efeito: se a sessão ainda está carregando, useModulos assume os dois ligados).
  const disponivel = (m: ModeloCertificado) => m === null || (m === "elefante" ? leitura : matematica);
  const modelo: ModeloCertificado = disponivel(modeloEscolhido) ? modeloEscolhido : null;
  // A arte da plataforma imprime o bimestre: sem ele escolhido, não há o que gerar.
  const faltaBimestre = modelo !== null && bimestre === "";
  const chavesModelo: ChaveModelo[] = [
    ...(leitura ? (["elefante"] as const) : []),
    ...(matematica ? (["matific"] as const) : []),
    "geral",
  ];

  // Quantos: os N PRIMEIROS da lista, na ordem dada.
  const quantidade = opcao === "personalizado" ? Number(personalizado) : Number(opcao);
  const quantidadeValida =
    Number.isInteger(quantidade) && quantidade >= 1 && quantidade <= MAX_CERTIFICADOS_LOTE;
  const selecionados = quantidadeValida ? alunos.slice(0, quantidade) : [];

  const vistos = new Set<number>();
  const linhas: Linha[] = selecionados.map((aluno, i) => {
    if (aluno.aluno_id == null) return { aluno, situacao: "sem_ficha", chave: `sem-ficha-${i}` };
    if (vistos.has(aluno.aluno_id)) return { aluno, situacao: "repetido", chave: `repetido-${aluno.aluno_id}-${i}` };
    vistos.add(aluno.aluno_id);
    return { aluno, situacao: "lote", chave: `aluno-${aluno.aluno_id}` };
  });
  const idsLote = linhas.filter((l) => l.situacao === "lote").map((l) => l.aluno.aluno_id as number);
  const semFicha = linhas.filter((l) => l.situacao === "sem_ficha").length;

  // A prévia vale para ESTE pedido (modelo + ids); mudou a escolha, é preciso verificar de novo.
  const chavePedido = `${chaveDoModelo(modelo)}|${idsLote.join(",")}`;
  const previaAtual = previa?.chave === chavePedido ? previa.itens : null;
  const itemPorId = new Map((previaAtual ?? []).map((item) => [item.aluno_id, item]));
  const aptos = previaAtual ? idsLote.filter((id) => itemPorId.get(id)?.apto === true) : [];
  const naoEmitidos = previaAtual ? idsLote.length - aptos.length : 0;
  const sucessoAtual = sucesso?.chave === chavePedido ? sucesso : null;

  const aoErro = (e: ApiError) => {
    setErro(e.message);
    // 422 do lote ("Nenhum aluno apto") traz os itens no formato da prévia, só dos ids
    // enviados (os aptos): eles passam a mostrar o motivo atual; os que a prévia já
    // tinha recusado continuam com o motivo dela.
    const itens = (e as ApiError & { corpo?: { itens?: unknown } }).corpo?.itens;
    if (!Array.isArray(itens)) return;
    const novos = new Map((itens as ItemPreviaCertificado[]).map((item) => [item.aluno_id, item]));
    setPrevia((anterior) => {
      const base = anterior?.chave === chavePedido ? anterior.itens : [];
      return { chave: chavePedido, itens: [...base.filter((item) => !novos.has(item.aluno_id)), ...novos.values()] };
    });
  };
  const verificar = useMutation(
    (pedido: PedidoPreviaCertificados) =>
      api<PreviaCertificados>(`/escolas/${escolaId}/certificados/lote/previa`, {
        method: "POST",
        body: JSON.stringify(pedido),
      }),
    { aoErro },
  );
  const gerar = useMutation(
    (pedido: PedidoLoteCertificados) =>
      apiDownloadPost(
        `/escolas/${escolaId}/certificados/lote`,
        pedido,
        `certificados_${chaveDoModelo(pedido.modelo)}_${pedido.aluno_ids.length}.pdf`,
      ),
    { aoErro },
  );

  const trabalhando = verificar.enviando || gerar.enviando;
  useEffect(() => {
    aoMudarOcupado(trabalhando);
  }, [trabalhando, aoMudarOcupado]);
  useEffect(() => () => aoMudarOcupado(false), [aoMudarOcupado]);

  /** Toda mudança de escolha apaga o resultado anterior (erro e sucesso). */
  const mudar = (acao: () => void) => {
    acao();
    setErro(null);
    setSucesso(null);
  };

  async function aoVerificar() {
    if (!escolaId || idsLote.length === 0) return;
    setErro(null);
    setSucesso(null);
    const chave = chavePedido;
    const resposta = await verificar.executar({ modelo, aluno_ids: idsLote });
    if (resposta) setPrevia({ chave, itens: Array.isArray(resposta.itens) ? resposta.itens : [] });
  }

  async function aoGerar() {
    if (!escolaId || aptos.length === 0 || faltaBimestre) return;
    setErro(null);
    setSucesso(null);
    const chave = chavePedido;
    // Só os APTOS da prévia, na ordem da lista: o PDF tem exatamente quem a pessoa viu
    // como apto. O Geral não imprime bimestre (como na emissão individual).
    const nome = await gerar.executar({
      modelo,
      bimestre: modelo ? Number(bimestre) : null,
      aluno_ids: aptos,
    });
    if (nome !== undefined) setSucesso({ chave, quantos: quantosNoArquivo(nome) ?? aptos.length });
  }

  const podeVerificar = Boolean(escolaId) && idsLote.length > 0 && !trabalhando;
  const podeGerar = Boolean(escolaId) && aptos.length > 0 && !trabalhando && !faltaBimestre;
  const rotuloGerar = gerar.enviando
    ? "Gerando PDF…"
    : previaAtual
      ? `Gerar PDF (${plural(aptos.length, "apto", "aptos")})`
      : "Gerar PDF";

  const descricaoModelo = MODELOS[chaveDoModelo(modelo)].descricao;

  return (
    <div className="space-y-6">
      {/* Contexto: de onde vem a lista. */}
      <div className="flex items-start gap-3.5 rounded-2xl bg-gradient-to-br from-ouro-50 via-white to-indigo-50 p-4 ring-1 ring-ouro-100 dark:from-ouro-400/10 dark:via-zinc-900 dark:to-indigo-500/10 dark:ring-zinc-800">
        <IconePastel icone={Award} tom="ambar" tamanho="lg" />
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-zinc-900 dark:text-white">{contexto}</p>
          <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-300">
            Os primeiros da lista desta tela, na ordem em que aparecem. Sai um PDF só, com uma página
            por aluno apto.
          </p>
        </div>
      </div>

      {alunos.length === 0 ? (
        <Vazio
          icone={Users}
          titulo="Nenhum aluno nesta lista"
          descricao="A lista desta tela está vazia, então não há para quem gerar certificados agora."
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <fieldset disabled={trabalhando} className="min-w-0">
              <legend className={CLASSE_ROTULO}>Quantos alunos</legend>
              <div className="mt-2.5 flex flex-wrap gap-2">
                {OPCOES_QUANTIDADE.map((item) => (
                  <Pilula
                    key={item.valor}
                    nome={ids.quantos}
                    valor={item.valor}
                    marcado={opcao === item.valor}
                    aoMarcar={() =>
                      mudar(() => {
                        if (item.valor === "personalizado" && personalizado === "" && opcao !== "personalizado") {
                          setPersonalizado(opcao);
                        }
                        setOpcao(item.valor);
                      })
                    }
                  >
                    {item.rotulo}
                  </Pilula>
                ))}
              </div>
              {opcao === "personalizado" && (
                <div className="mt-3">
                  <label htmlFor={ids.personalizado} className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Quantos alunos (1 a {MAX_CERTIFICADOS_LOTE})
                  </label>
                  <input
                    id={ids.personalizado}
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={MAX_CERTIFICADOS_LOTE}
                    step={1}
                    value={personalizado}
                    onChange={(e) => mudar(() => setPersonalizado(e.target.value))}
                    aria-invalid={!quantidadeValida}
                    aria-describedby={ids.dicaPersonalizado}
                    className={`${estiloInput} max-w-[9rem] tabular-nums`}
                  />
                  <p
                    id={ids.dicaPersonalizado}
                    className={`mt-1.5 text-xs ${quantidadeValida ? "text-zinc-500 dark:text-zinc-400" : "font-medium text-rose-700 dark:text-rose-300"}`}
                  >
                    {quantidadeValida
                      ? `Até ${MAX_CERTIFICADOS_LOTE} alunos por lote.`
                      : `Informe um número inteiro de 1 a ${MAX_CERTIFICADOS_LOTE}.`}
                  </p>
                </div>
              )}
              {quantidadeValida && quantidade > alunos.length && (
                <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                  A lista do lote tem {plural(alunos.length, "aluno", "alunos")}: entram todos.
                </p>
              )}
            </fieldset>

            <fieldset disabled={trabalhando} className="min-w-0">
              <legend className={CLASSE_ROTULO}>Modelo do certificado</legend>
              <div className="mt-2.5 flex flex-wrap gap-2">
                {chavesModelo.map((chave) => {
                  const m = MODELOS[chave];
                  return (
                    <Pilula
                      key={chave}
                      nome={ids.modelo}
                      valor={chave}
                      tom={m.tom}
                      icone={m.icone}
                      marcado={chaveDoModelo(modelo) === chave}
                      aoMarcar={() => mudar(() => setModeloEscolhido(modeloDaChave(chave)))}
                    >
                      {m.rotulo}
                    </Pilula>
                  );
                })}
              </div>
              <p className="mt-2.5 text-xs leading-relaxed text-zinc-600 dark:text-zinc-300">{descricaoModelo}</p>
            </fieldset>
          </div>

          <div className="flex flex-wrap items-end gap-x-4 gap-y-1.5">
            <div className="w-full sm:w-56">
              <label htmlFor={ids.bimestre} className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Bimestre impresso
              </label>
              <select
                id={ids.bimestre}
                className={`${estiloInput} disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-zinc-500 dark:disabled:bg-zinc-800`}
                value={bimestre}
                onChange={(e) => setBimestre(e.target.value)}
                disabled={modelo === null || trabalhando}
                aria-describedby={ids.dicaBimestre}
              >
                {bimestre === "" && (
                  <option value="" disabled>
                    Escolha o bimestre
                  </option>
                )}
                {[1, 2, 3, 4].map((b) => (
                  <option key={b} value={b}>
                    {b}º bimestre
                  </option>
                ))}
              </select>
            </div>
            <p id={ids.dicaBimestre} className="pb-2.5 text-xs text-zinc-500 dark:text-zinc-400">
              {modelo === null
                ? "O certificado Geral não imprime bimestre."
                : doPeriodo
                  ? "Abre no bimestre do período desta lista; vale o que você escolher."
                  : sugerido != null
                    ? "Abre no bimestre de hoje pelo calendário oficial; vale o que você escolher."
                    : semCalendarioOficial(hoje, calendario)
                      ? `O calendário oficial de ${hoje.getFullYear()} não está cadastrado no sistema: escolha o bimestre que o certificado vai afirmar.`
                      : "Escolha o bimestre que o certificado vai afirmar."}
            </p>
          </div>

          <section aria-labelledby={ids.lista}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id={ids.lista} className={CLASSE_ROTULO}>
                Quem entra no lote
              </h3>
              {quantidadeValida && (
                <span className="text-xs font-medium text-zinc-500 tabular-nums dark:text-zinc-400">
                  {selecionados.length} de {plural(alunos.length, "aluno", "alunos")} da lista
                </span>
              )}
            </div>

            {semFicha > 0 && (
              <p className="mt-3 flex items-start gap-2 rounded-xl bg-zinc-100 px-3.5 py-2.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                <Info size={15} aria-hidden className="mt-px shrink-0 text-zinc-500" />
                <span>
                  {semFicha === 1
                    ? "1 dos primeiros da lista não tem ficha de aluno vinculada e fica de fora."
                    : `${semFicha} dos primeiros da lista não têm ficha de aluno vinculada e ficam de fora.`}{" "}
                  Ninguém entra no lugar.
                </span>
              </p>
            )}

            {linhas.length > 0 && (
              <ol aria-label="Alunos do lote" className="mt-3 space-y-2">
                {linhas.map((linha) => (
                  <LinhaAluno
                    key={linha.chave}
                    linha={linha}
                    item={linha.situacao === "lote" ? itemPorId.get(linha.aluno.aluno_id as number) : undefined}
                    verificado={previaAtual !== null}
                  />
                ))}
              </ol>
            )}

            <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
              Quem não puder receber aparece como “Não emitido”, com o motivo. O próximo colocado não
              entra no lugar.
            </p>
          </section>
        </>
      )}

      {/* Resultado anunciado sem interromper (verificação e download). A região fica
          SEMPRE no DOM (vazia não ocupa espaço) para o leitor de tela ouvir a mudança. */}
      <div role="status" aria-live="polite" className="empty:!mt-0">
        {verificar.enviando ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-300">Verificando os alunos…</p>
        ) : sucessoAtual ? (
          <div className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200">
            <CheckCircle2 size={18} aria-hidden className="mt-px shrink-0" />
            <span>
              <strong className="font-semibold">
                PDF com {plural(sucessoAtual.quantos, "certificado", "certificados")} baixado
              </strong>
              . Confira a pasta de downloads do navegador.
            </span>
          </div>
        ) : previaAtual ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-zinc-700 dark:text-zinc-200">Verificação:</span>
            <Badge tom="ok">
              <CheckCircle2 size={12} aria-hidden /> {plural(aptos.length, "apto", "aptos")}
            </Badge>
            {naoEmitidos > 0 && (
              <Badge tom="erro">
                <XCircle size={12} aria-hidden /> {plural(naoEmitidos, "não emitido", "não emitidos")}
              </Badge>
            )}
            {aptos.length === 0 && (
              <span className="text-zinc-600 dark:text-zinc-300">Nenhum aluno apto: não há PDF a gerar.</span>
            )}
          </div>
        ) : null}
      </div>

      {erro && <Mensagem tipo="erro">{erro}</Mensagem>}

      {/* Rodapé grudado na base da janela (Top 50 rola; "Gerar PDF" continua à vista).
          -bottom-6: o "grudar" do sticky desconta o padding (p-6) da janela; com
          bottom-0 sobrava uma faixa de 24 px por onde a lista aparecia embaixo dele. */}
      <div className="sticky -bottom-6 z-10 -mx-6 -mb-6 flex flex-wrap items-center justify-end gap-2.5 rounded-b-3xl border-t border-zinc-100 bg-white/95 px-6 py-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
        <Botao variante="fantasma" onClick={aoFechar} disabled={ocupado} className="mr-auto">
          Fechar
        </Botao>
        {alunos.length > 0 && (
          <>
            <Botao
              variante={previaAtual ? "secundario" : "primario"}
              onClick={aoVerificar}
              disabled={!podeVerificar}
              aria-busy={verificar.enviando}
            >
              {verificar.enviando ? <Girando /> : <ListChecks size={16} aria-hidden />}
              {verificar.enviando ? "Verificando…" : "Verificar"}
            </Botao>
            <Botao variante="ambar" onClick={aoGerar} disabled={!podeGerar} aria-busy={gerar.enviando}>
              {gerar.enviando ? <Girando /> : <FileDown size={16} aria-hidden />}
              {rotuloGerar}
            </Botao>
          </>
        )}
      </div>
    </div>
  );
}

const CLASSE_ROTULO =
  "text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400";

function Girando() {
  return <Loader2 size={16} aria-hidden className="animate-spin motion-reduce:animate-none" />;
}

type TomPilula = "violeta" | "teal" | "ambar";

const TONS_PILULA: Record<TomPilula, string> = {
  violeta: "peer-checked:border-indigo-600 peer-checked:bg-indigo-600 peer-checked:text-white peer-checked:shadow-pilula",
  // teal-700 (e não 600): texto branco em negrito precisa de 4,5:1.
  teal: "peer-checked:border-teal-700 peer-checked:bg-teal-700 peer-checked:text-white",
  ambar: "peer-checked:border-ouro-400 peer-checked:bg-ouro-400 peer-checked:text-marinho-900 peer-checked:shadow-ambar",
};

/** Opção em pílula: um <input type="radio"> nativo (teclado e leitor de tela de graça)
 *  escondido, com a pílula desenhada ao lado. Marcado também ganha o ✓ (não só a cor). */
function Pilula({
  nome,
  valor,
  marcado,
  aoMarcar,
  tom = "violeta",
  icone: Icone,
  children,
}: {
  nome: string;
  valor: string;
  marcado: boolean;
  aoMarcar: () => void;
  tom?: TomPilula;
  icone?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <label className="cursor-pointer has-[:disabled]:cursor-not-allowed">
      <input type="radio" name={nome} value={valor} checked={marcado} onChange={aoMarcar} className="peer sr-only" />
      <span
        className={`inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-3.5 py-2 text-sm font-semibold text-zinc-700 shadow-cartao transition-colors hover:border-zinc-300 hover:text-zinc-900 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-indigo-600 peer-disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:text-white ${TONS_PILULA[tom]}`}
      >
        {marcado ? (
          <Check size={14} strokeWidth={3} aria-hidden />
        ) : (
          Icone && <Icone size={15} aria-hidden />
        )}
        {children}
      </span>
    </label>
  );
}

/** Posição da TELA: medalha para o pódio, bolinha para os demais (texto "Nº lugar" no leitor). */
function MarcaPosicao({ posicao }: { posicao?: number | null }) {
  if (posicao === 1 || posicao === 2 || posicao === 3) return <Medalha posicao={posicao} semFita tamanho={28} />;
  if (typeof posicao === "number") {
    return (
      <span className="inline-flex shrink-0">
        <PosicaoBolinha posicao={posicao} />
        <span className="sr-only">º lugar</span>
      </span>
    );
  }
  return <span aria-hidden className="h-7 w-7 shrink-0" />;
}

function LinhaAluno({
  linha,
  item,
  verificado,
}: {
  linha: Linha;
  item: ItemPreviaCertificado | undefined;
  verificado: boolean;
}) {
  const { aluno, situacao } = linha;
  const nome = aluno.nome?.trim() || "Aluno sem nome";

  let selo: ReactNode = null;
  let detalhe: ReactNode = null;
  let moldura = "border-zinc-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900";

  if (situacao === "sem_ficha") {
    selo = (
      <Badge tom="neutro">
        <Link2Off size={12} aria-hidden /> Fora do lote
      </Badge>
    );
    detalhe = (
      <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
        Linha sem ficha de aluno vinculada no sistema: não dá para emitir.
      </p>
    );
    moldura = "border-dashed border-zinc-300 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/60";
  } else if (situacao === "repetido") {
    selo = <Badge tom="neutro">Repetido</Badge>;
    detalhe = <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">Já aparece acima nesta lista.</p>;
    moldura = "border-dashed border-zinc-300 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/60";
  } else if (verificado) {
    if (item?.apto) {
      selo = (
        <Badge tom="ok">
          <CheckCircle2 size={12} aria-hidden /> Apto
        </Badge>
      );
      moldura = "border-emerald-200 bg-white dark:border-emerald-500/30 dark:bg-zinc-900";
    } else {
      selo = (
        <Badge tom="erro">
          <XCircle size={12} aria-hidden /> Não emitido
        </Badge>
      );
      detalhe = (
        <p className="mt-1 text-xs leading-relaxed text-rose-700 dark:text-rose-300">
          {item?.motivo || (item ? "Recusado pelo sistema, sem motivo informado." : "A verificação não trouxe este aluno.")}
        </p>
      );
      moldura = "border-rose-200 bg-rose-50/50 dark:border-rose-500/30 dark:bg-rose-500/5";
    }
  }

  return (
    <li className={`flex items-start gap-3 rounded-2xl border p-3 ${moldura}`}>
      <span className="mt-1.5 flex shrink-0">
        <MarcaPosicao posicao={aluno.posicao} />
      </span>
      <Avatar nome={aluno.nome} chave={aluno.aluno_id ?? nome} tamanho="md" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="break-words font-semibold text-zinc-900 dark:text-white">{nome}</span>
          {aluno.turma && <Chip>{aluno.turma}</Chip>}
        </div>
        {detalhe}
      </div>
      {selo && <span className="mt-1.5 shrink-0">{selo}</span>}
    </li>
  );
}
