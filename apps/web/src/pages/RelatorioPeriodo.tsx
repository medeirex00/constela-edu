/**
 * Relatório por PERÍODO — "o que aconteceu em setembro", por plataforma e por
 * escopo (escola, turma, aluno).
 *
 * O que esta tela NÃO faz: calcular. Todo número chega pronto de
 * `/escolas/{id}/relatorios/periodo`, que reusa o serviço OFICIAL de períodos
 * (`periodos.resolver`) — então "setembro" aqui é o mesmo "setembro" do pódio.
 * Mérito, nota, ranking e certificado não passam por aqui.
 *
 * O que ela faz de propósito, e é o ponto da tela: DIZER DE QUAL DATA CADA
 * NÚMERO VEM. O Elefante entrega dois fatos diferentes e somá-los contaria o
 * mesmo livro duas vezes:
 *
 *   • "livros novos" e "tempo" vêm de `Leitura.data` — o MESMO campo da
 *     premiação oficial. É o número que bate com a cerimônia.
 *   • "livros com atividade" e "relidos" vêm de `EventoAluno.ocorrido_em` — o
 *     único campo que vê a releitura (a §35 nunca atualiza `Leitura.data`).
 *
 * E o que o sistema NÃO sabe responder aparece como "—" com o motivo visível,
 * nunca como zero: questões do Matific (não existe o contador) e tempo por
 * evento no Elefante (o campo é acumulado por livro; medição em produção
 * refutou tanto a soma quanto a diferença). Um zero silencioso num relatório
 * de gestão é pior que uma lacuna declarada — a diretora agiria sobre ele.
 */
import { BookOpen, CalendarRange, Clock, FileDown, Info, RefreshCw, Sigma, Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { Botao, Card, Carregando, Mensagem, PageHeader, SecaoRecolhivel, StatCard, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
import { dataHora, numero, tempoLeitura } from "../lib/formato";
import type { Turma } from "../lib/types";

type Classificacao = "SUPORTADO" | "SUPORTADO COM RESSALVA" | "NÃO SUPORTADO";

interface Suporte {
  campo?: string;
  classificacao: Classificacao;
  por_que: string;
  ressalva?: string;
}

interface JanelaEfetiva {
  data_base_mais_antiga: string | null;
  data_base_mais_recente: string | null;
  data_atual_mais_antiga: string;
  data_atual_mais_recente: string;
  observacao: string;
}

interface BlocoElefante {
  livros_novos: number;
  tempo_min: number;
  alunos_com_livro_novo: number;
  livros_com_atividade: number;
  livros_relidos: number;
  eventos_leitura: number;
  tempo_min_por_evento: null;
  alunos_com_atividade: number;
  questoes_tentativas: number | null;
  questoes_acertos: number | null;
  alunos_sem_retrato: number;
  janela_efetiva_questoes: JanelaEfetiva | null;
  sem_atividade: number;
  primeiro_evento_da_escola: string | null;
  suporte: Record<string, Suporte>;
}

interface BlocoMatific {
  atividades: number;
  estrelas: number;
  alunos_com_atividade: number;
  alunos_sem_retrato: number;
  questoes: null;
  janela_efetiva: JanelaEfetiva | null;
  sem_atividade: number;
  /** O bloco do Matific tem UM suporte (atividades/estrelas) e, dentro dele, o
   *  de `questoes` — que é a métrica inexistente. Daí o tipo não ser um mapa. */
  suporte: Suporte & { questoes: Suporte };
}

interface LinhaTurma {
  turma_id: number;
  turma: string;
  ano_escolar: string;
  turno: string | null;
  alunos: number;
  com_atividade: number;
  elefante: { livros_novos: number; tempo_min: number; livros_com_atividade: number; livros_relidos: number; eventos_leitura: number };
  matific: { atividades: number; estrelas: number };
}

interface LinhaAluno {
  aluno_id: number;
  nome: string;
  turma: string;
  turma_id: number;
  ano_escolar: string;
  elefante: { livros_novos: number; tempo_min: number; livros_com_atividade: number; livros_relidos: number; eventos_leitura: number } | null;
  matific: { atividades: number; estrelas: number } | null;
  sem_atividade: boolean;
}

interface RelatorioPeriodoT {
  escola: { id: number; nome: string; ano_letivo: number };
  periodo: { preset: string; rotulo: string; inicio: string | null; fim: string | null; inclusivo: boolean };
  escopo: { tipo: string; turma_id: number | null; aluno_id: number | null; restrito_a_turmas: number[] | null };
  plataformas: string[];
  plataformas_rotulo: string;
  alunos: { considerados: number; com_atividade: number; sem_atividade: number };
  nao_suportado: { plataforma: string; metrica: string; por_que: string }[];
  elefante?: BlocoElefante;
  matific?: BlocoMatific;
  por_turma?: LinhaTurma[];
  por_aluno: LinhaAluno[];
}

interface PaginaAlunos {
  itens: { id: number; nome: string; turma_id: number | null }[];
}

const PLATAFORMAS = [
  { valor: "elefante,matific", rotulo: "Elefante Letrado + Matific" },
  { valor: "elefante", rotulo: "Somente Elefante Letrado" },
  { valor: "matific", rotulo: "Somente Matific" },
] as const;

const TOM_CLASSIFICACAO: Record<Classificacao, string> = {
  SUPORTADO: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  "SUPORTADO COM RESSALVA": "bg-amber-50 text-amber-700 ring-amber-200",
  "NÃO SUPORTADO": "bg-zinc-100 text-zinc-600 ring-zinc-300",
};

/** Etiqueta da classificação — o vocabulário é o do backend, não um apelido. */
function Selo({ classificacao }: { classificacao: Classificacao }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ${TOM_CLASSIFICACAO[classificacao]}`}>
      {classificacao}
    </span>
  );
}

/** Intervalo REAL que um número vindo de retratos cobre. Só aparece quando o
 *  backend o devolve — e ele só devolve quando houve retrato na janela. */
function AvisoJanelaEfetiva({ janela, titulo }: { janela: JanelaEfetiva; titulo: string }) {
  return (
    <p className="mt-2 flex gap-2 text-xs text-amber-700">
      <Info size={14} className="mt-0.5 shrink-0" />
      <span>
        <strong>{titulo}:</strong> a conta vai de{" "}
        {dataHora(janela.data_base_mais_antiga)} a {dataHora(janela.data_atual_mais_recente)} —{" "}
        {janela.observacao}.
      </span>
    </p>
  );
}

export default function RelatorioPeriodo() {
  // O PERÍODO é global (AppContext): o recorte que o gestor escolheu aqui
  // continua valendo nos rankings e nas premiações, e vice-versa — é a mesma
  // pergunta ("qual janela?") e seria ruído pedi-la de novo em cada tela.
  const { escolaId, periodo, definirPeriodo } = useApp();
  const [plataformas, setPlataformas] = useState<string>("elefante,matific");
  const [turmaId, setTurmaId] = useState<number | null>(null);
  const [alunoId, setAlunoId] = useState<number | null>(null);

  const { dados: turmas } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const { dados: paginaAlunos } = useApi<PaginaAlunos>(
    escolaId && turmaId ? `/escolas/${escolaId}/alunos?por_pagina=500&turma_id=${turmaId}` : null,
  );

  const escopo = alunoId ? "aluno" : turmaId ? "turma" : "escola";
  // Personalizado sem as DUAS datas devolveria 422: a tela espera o gestor
  // terminar de escolher em vez de mostrar um erro que ele já sabe.
  const personalizadoIncompleto =
    periodo.preset === "personalizado" && !(periodo.inicio && periodo.fim);

  // UMA query para os DOIS formatos. A tela e o PDF não podem divergir de
  // filtro: se o botão montasse a própria URL, bastaria alguém mexer num
  // seletor para o papel sair de um recorte e a tela mostrar outro.
  const consulta = useMemo(() => {
    if (!escolaId || personalizadoIncompleto) return null;
    const q = new URLSearchParams(periodoParaQuery(periodo));
    for (const p of plataformas.split(",")) q.append("plataformas", p);
    q.set("escopo", escopo);
    if (turmaId) q.set("turma_id", String(turmaId));
    if (alunoId) q.set("aluno_id", String(alunoId));
    return q.toString();
  }, [escolaId, periodo, plataformas, escopo, turmaId, alunoId, personalizadoIncompleto]);

  const url = consulta ? `/escolas/${escolaId}/relatorios/periodo?${consulta}` : null;
  const urlPdf = consulta ? `/escolas/${escolaId}/relatorios/periodo.pdf?${consulta}` : null;

  const { dados, erro, carregando } = useApi<RelatorioPeriodoT>(url);

  // O PDF é gerado sob demanda e devolvido na resposta — nada é guardado no
  // servidor. Quem nomeia o arquivo é o backend (Content-Disposition).
  const [gerandoPdf, setGerandoPdf] = useState(false);
  const [erroPdf, setErroPdf] = useState("");
  // Mudou o recorte? O erro do recorte anterior deixou de valer.
  useEffect(() => { setErroPdf(""); }, [consulta]);

  async function gerarPdf() {
    if (!urlPdf || gerandoPdf) return;
    setGerandoPdf(true);
    setErroPdf("");
    try {
      await apiDownload(urlPdf);
    } catch (excecao) {
      setErroPdf(excecao instanceof Error ? excecao.message
                                          : "Não foi possível gerar o PDF.");
    } finally {
      setGerandoPdf(false);
    }
  }

  const ele = dados?.elefante;
  const mat = dados?.matific;
  // O espelho de eventos nasceu na migração 0010: janela anterior a ele devolve
  // zero por FALTA DE HISTÓRICO, não por inatividade. Dizer isso é o que separa
  // "ninguém leu" de "o sistema ainda não registrava".
  const antesDoHistorico =
    ele?.primeiro_evento_da_escola && dados?.periodo.inicio
      ? dados.periodo.inicio < ele.primeiro_evento_da_escola
      : false;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Relatório por Período"
        descricao="O que aconteceu numa janela de datas — do mês fechado ao intervalo que você escolher."
        acoes={
          <Botao
            onClick={gerarPdf}
            disabled={!urlPdf || gerandoPdf || carregando}
            aria-busy={gerandoPdf}
          >
            <FileDown size={15} className="mr-1.5 inline" />
            {gerandoPdf ? "Gerando PDF..." : "Gerar PDF"}
          </Botao>
        }
      />
      {erroPdf && <Mensagem tipo="erro">{erroPdf}</Mensagem>}

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-500">Período</label>
            <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
          </div>
          <div>
            <label htmlFor="rp-plataformas" className="mb-1 block text-xs font-medium text-zinc-500">
              Plataforma
            </label>
            <select
              id="rp-plataformas"
              className={`${estiloInput} w-auto`}
              value={plataformas}
              onChange={(e) => setPlataformas(e.target.value)}
            >
              {PLATAFORMAS.map((p) => (
                <option key={p.valor} value={p.valor}>{p.rotulo}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="rp-turma" className="mb-1 block text-xs font-medium text-zinc-500">
              Turma
            </label>
            <select
              id="rp-turma"
              className={`${estiloInput} w-auto`}
              value={turmaId ?? ""}
              onChange={(e) => {
                setTurmaId(e.target.value ? Number(e.target.value) : null);
                setAlunoId(null);
              }}
            >
              <option value="">Toda a escola</option>
              {(turmas ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.nome}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="rp-aluno" className="mb-1 block text-xs font-medium text-zinc-500">
              Aluno
            </label>
            <select
              id="rp-aluno"
              className={`${estiloInput} w-auto`}
              value={alunoId ?? ""}
              disabled={!turmaId}
              onChange={(e) => setAlunoId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Toda a turma</option>
              {(paginaAlunos?.itens ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.nome}</option>
              ))}
            </select>
          </div>
        </div>
        {personalizadoIncompleto && (
          <p className="mt-3 text-xs text-zinc-500">
            Escolha a data inicial e a final para gerar o relatório personalizado.
          </p>
        )}
      </Card>

      {erro && <Mensagem tipo="erro">{erro.message}</Mensagem>}
      {carregando && !dados && <Carregando texto="Montando o relatório..." />}

      {dados && (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="flex items-center gap-2 text-sm font-semibold text-zinc-800">
                  <CalendarRange size={16} className="text-zinc-400" />
                  {dados.periodo.rotulo}
                </p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {dados.plataformas_rotulo} · {dados.escola.nome} · ano letivo {dados.escola.ano_letivo}
                  {dados.periodo.inclusivo && " · intervalo inclusivo nas duas datas"}
                </p>
              </div>
              <p className="text-xs text-zinc-500">
                <strong className="text-zinc-800">{numero(dados.alunos.considerados)}</strong>{" "}
                {dados.alunos.considerados === 1 ? "aluno ativo" : "alunos ativos"} no recorte ·{" "}
                {numero(dados.alunos.com_atividade)} com atividade
              </p>
            </div>
            {dados.escopo.restrito_a_turmas && (
              <p className="mt-2 text-xs text-zinc-500">
                Você vê as turmas vinculadas ao seu cadastro ({dados.escopo.restrito_a_turmas.length}).
              </p>
            )}
            {antesDoHistorico && (
              <p className="mt-2 flex gap-2 text-xs text-amber-700">
                <Info size={14} className="mt-0.5 shrink-0" />
                <span>
                  O histórico de atividade desta escola começa em{" "}
                  {dataHora(ele?.primeiro_evento_da_escola ?? null)}. Antes disso o relatório
                  mostra zero por <strong>falta de registro</strong>, não por inatividade.
                </span>
              </p>
            )}
          </Card>

          {ele && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-zinc-700">Elefante Letrado</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard
                  icone={<BookOpen size={18} />}
                  rotulo="Livros novos"
                  valor={numero(ele.livros_novos)}
                  detalhe={`${numero(ele.alunos_com_livro_novo)} aluno(s) · mesmo número da premiação`}
                />
                <StatCard
                  icone={<Clock size={18} />}
                  rotulo="Tempo de leitura"
                  valor={tempoLeitura(ele.tempo_min)}
                  detalhe="tempo informado por livro novo"
                />
                <StatCard
                  icone={<RefreshCw size={18} />}
                  rotulo="Livros com atividade"
                  valor={numero(ele.livros_com_atividade)}
                  detalhe={`${numero(ele.livros_relidos)} relido(s) · inclui releitura`}
                />
                <StatCard
                  icone={<Sigma size={18} />}
                  rotulo="Questões"
                  valor={
                    ele.questoes_tentativas === null
                      ? "—"
                      : `${numero(ele.questoes_acertos ?? 0)}/${numero(ele.questoes_tentativas)}`
                  }
                  detalhe={
                    ele.alunos_sem_retrato
                      ? `${numero(ele.alunos_sem_retrato)} sem coleta na janela (não contam como zero)`
                      : "acertos sobre tentativas"
                  }
                />
              </div>
              {ele.janela_efetiva_questoes && (
                <Card>
                  <AvisoJanelaEfetiva janela={ele.janela_efetiva_questoes} titulo="Questões" />
                </Card>
              )}
            </section>
          )}

          {mat && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-zinc-700">Matific</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard
                  icone={<Sigma size={18} />}
                  rotulo="Atividades"
                  valor={numero(mat.atividades)}
                  detalhe={`${numero(mat.alunos_com_atividade)} aluno(s) com ganho no período`}
                />
                <StatCard
                  icone={<Star size={18} />}
                  rotulo="Estrelas"
                  valor={numero(mat.estrelas)}
                  detalhe="ganho entre coletas"
                />
                <StatCard
                  icone={<Info size={18} />}
                  rotulo="Sem coleta na janela"
                  valor={numero(mat.alunos_sem_retrato)}
                  detalhe="ausência de dado, não zero"
                />
                <StatCard
                  icone={<Sigma size={18} />}
                  rotulo="Questões"
                  valor="—"
                  detalhe="não existe este contador no Matific"
                />
              </div>
              {mat.janela_efetiva && (
                <Card>
                  <AvisoJanelaEfetiva janela={mat.janela_efetiva} titulo="Matific" />
                </Card>
              )}
            </section>
          )}

          <SecaoRecolhivel titulo="Como ler estes números" icone={<Info size={16} />} inicialAberto={false}>
            <div className="space-y-4 text-sm">
              {ele && (
                <div className="space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Elefante Letrado
                  </p>
                  {Object.entries(ele.suporte).map(([chave, s]) => (
                    <div key={chave} className="rounded border border-zinc-200 p-3">
                      <p className="flex flex-wrap items-center gap-2">
                        <strong className="text-zinc-800">{chave.replace(/_/g, " ")}</strong>
                        <Selo classificacao={s.classificacao} />
                        {s.campo && <code className="text-[11px] text-zinc-500">{s.campo}</code>}
                      </p>
                      <p className="mt-1 text-xs text-zinc-600">{s.por_que}</p>
                      {s.ressalva && (
                        <p className="mt-1 text-xs text-amber-700">Ressalva: {s.ressalva}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {mat && (
                <div className="space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Matific
                  </p>
                  <div className="rounded border border-zinc-200 p-3">
                    <p className="flex flex-wrap items-center gap-2">
                      <strong className="text-zinc-800">atividades e estrelas</strong>
                      <Selo classificacao={mat.suporte.classificacao} />
                      {mat.suporte.campo && (
                        <code className="text-[11px] text-zinc-500">{mat.suporte.campo}</code>
                      )}
                    </p>
                    <p className="mt-1 text-xs text-zinc-600">{mat.suporte.por_que}</p>
                    {mat.suporte.ressalva && (
                      <p className="mt-1 text-xs text-amber-700">Ressalva: {mat.suporte.ressalva}</p>
                    )}
                  </div>
                </div>
              )}
              {dados.nao_suportado.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    O que este relatório NÃO responde
                  </p>
                  {dados.nao_suportado.map((n) => (
                    <div key={`${n.plataforma}-${n.metrica}`} className="rounded bg-zinc-50 p-3">
                      <p className="text-xs font-medium text-zinc-700">
                        {n.plataforma} · {n.metrica.replace(/_/g, " ")}
                      </p>
                      <p className="mt-1 text-xs text-zinc-600">{n.por_que}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </SecaoRecolhivel>

          {dados.por_turma && dados.por_turma.length > 0 && (
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-zinc-700">Por turma</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                      <th className="py-2 pr-3">Turma</th>
                      <th className="py-2 pr-3 text-right">Alunos</th>
                      <th className="py-2 pr-3 text-right">Com atividade</th>
                      {ele && <th className="py-2 pr-3 text-right">Livros novos</th>}
                      {ele && <th className="py-2 pr-3 text-right">Tempo</th>}
                      {ele && <th className="py-2 pr-3 text-right">Relidos</th>}
                      {mat && <th className="py-2 pr-3 text-right">Atividades</th>}
                      {mat && <th className="py-2 text-right">Estrelas</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {dados.por_turma.map((t) => (
                      <tr key={t.turma_id} className="border-b border-zinc-100">
                        <td className="py-2 pr-3">
                          {t.turma}
                          <span className="ml-1 text-xs text-zinc-400">{t.turno ?? ""}</span>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">{numero(t.alunos)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{numero(t.com_atividade)}</td>
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{numero(t.elefante.livros_novos)}</td>}
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{tempoLeitura(t.elefante.tempo_min)}</td>}
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{numero(t.elefante.livros_relidos)}</td>}
                        {mat && <td className="py-2 pr-3 text-right tabular-nums">{numero(t.matific.atividades)}</td>}
                        {mat && <td className="py-2 text-right tabular-nums">{numero(t.matific.estrelas)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-zinc-700">Por aluno</h2>
            {dados.por_aluno.length === 0 ? (
              <Vazio titulo="Nenhum aluno no recorte" descricao="Confira a turma escolhida e o ano letivo." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                      <th className="py-2 pr-3">Aluno</th>
                      <th className="py-2 pr-3">Turma</th>
                      {ele && <th className="py-2 pr-3 text-right">Livros novos</th>}
                      {ele && <th className="py-2 pr-3 text-right">Tempo</th>}
                      {ele && <th className="py-2 pr-3 text-right">Com atividade</th>}
                      {ele && <th className="py-2 pr-3 text-right">Relidos</th>}
                      {mat && <th className="py-2 pr-3 text-right">Atividades</th>}
                      {mat && <th className="py-2 text-right">Estrelas</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {dados.por_aluno.map((a) => (
                      <tr key={a.aluno_id} className={`border-b border-zinc-100 ${a.sem_atividade ? "text-zinc-400" : ""}`}>
                        <td className="py-2 pr-3">{a.nome}</td>
                        <td className="py-2 pr-3 text-xs">{a.turma}</td>
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{numero(a.elefante?.livros_novos ?? 0)}</td>}
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{tempoLeitura(a.elefante?.tempo_min ?? 0)}</td>}
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{numero(a.elefante?.livros_com_atividade ?? 0)}</td>}
                        {ele && <td className="py-2 pr-3 text-right tabular-nums">{numero(a.elefante?.livros_relidos ?? 0)}</td>}
                        {mat && <td className="py-2 pr-3 text-right tabular-nums">{numero(a.matific?.atividades ?? 0)}</td>}
                        {mat && <td className="py-2 text-right tabular-nums">{numero(a.matific?.estrelas ?? 0)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
