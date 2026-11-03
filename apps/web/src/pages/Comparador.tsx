/** Comparador aluno×aluno, aluno×turma e turma×turma (PRD §73–§75).
 *
 *  Identidade visual v2: os dois lados em cartões (A em violeta, B em azul), notas
 *  em cartões de indicador com ícone pastel e número grande, e os indicadores lado
 *  a lado agrupados por plataforma. Os números são os da API (`/comparar`); a tela
 *  não calcula diferença nem média. */
import { Award, BookOpen, Calculator, GitCompareArrows, Info, LayoutGrid, School, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";

import { Avatar, Botao, Campo, Card, Carregando, Chip, IconePastel, Mensagem, PageHeader, Vazio, estiloInput } from "../components/ui";
import type { TomPastel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nota, numero, tempoLeitura } from "../lib/formato";
import type { Escola, PaginaAlunos, Turma } from "../lib/types";

interface Lado {
  tipo: string;
  id: number;
  nome: string;
  total_alunos?: number;
  indicadores: Record<string, number>;
  notas: { matific: number; elefante: number; geral: number; posicao: number | null };
}

interface Comparacao {
  a: Lado;
  b: Lado;
}

interface OpcaoAluno {
  id: number;
  nome: string;
}

/** Cor de cada lado (o nome vai sempre em texto ao lado; a cor é só reforço). */
const LADOS = {
  A: { ponto: "bg-indigo-600", barra: "from-indigo-500 to-indigo-600", texto: "text-indigo-700 dark:text-indigo-300",
       moldura: "border-indigo-200 bg-indigo-50/60 dark:border-indigo-500/30 dark:bg-indigo-500/10" },
  B: { ponto: "bg-sky-500", barra: "from-sky-400 to-sky-600", texto: "text-sky-700 dark:text-sky-300",
       moldura: "border-sky-200 bg-sky-50/60 dark:border-sky-500/30 dark:bg-sky-500/10" },
} as const;

const ICONE_TIPO: Record<string, LucideIcon> = { aluno: User, turma: LayoutGrid, escola: School };
const ROTULO_TIPO: Record<string, string> = { aluno: "Aluno", turma: "Turma", escola: "Escola" };

function SeletorLado({
  lado,
  rotulo,
  tipo,
  setTipo,
  id,
  setId,
  alunos,
  turmas,
  escolas,
  podeEscola,
}: {
  lado: keyof typeof LADOS;
  rotulo: string;
  tipo: string;
  setTipo: (tipo: string) => void;
  id: string;
  setId: (id: string) => void;
  alunos: OpcaoAluno[];
  turmas: Turma[];
  escolas: OpcaoAluno[];
  podeEscola: boolean;
}) {
  const opcoes = tipo === "aluno" ? alunos : tipo === "escola" ? escolas : turmas;
  return (
    <div className={`min-w-0 flex-1 rounded-2xl border p-4 ${LADOS[lado].moldura}`}>
      <p className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-600 dark:text-zinc-300">
        <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${LADOS[lado].ponto}`} />
        {rotulo}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)]">
        <Campo rotulo={`${rotulo} — tipo`}>
          <select className={estiloInput} value={tipo} onChange={(evento) => { setTipo(evento.target.value); setId(""); }}>
            <option value="aluno">Aluno</option>
            <option value="turma">Turma</option>
            {/* "Escola" só para ADM supremo (rede/Secretaria) — compara escolas inteiras. */}
            {podeEscola && <option value="escola">Escola</option>}
          </select>
        </Campo>
        <Campo rotulo={rotulo}>
          <select className={estiloInput} value={id} onChange={(evento) => setId(evento.target.value)}>
            <option value="">Selecione…</option>
            {opcoes.map((opcao) => (
              <option key={opcao.id} value={opcao.id}>{opcao.nome}</option>
            ))}
          </select>
        </Campo>
      </div>
    </div>
  );
}

const INDICADORES: {
  chave: string;
  rotulo: string;
  grupo: "matific" | "elefante";
  formato?: (valor: number) => string;
}[] = [
  { chave: "atividades", rotulo: "Atividades (Matific)", grupo: "matific" },
  { chave: "estrelas", rotulo: "Estrelas (Matific)", grupo: "matific" },
  { chave: "pontuacao_media", rotulo: "Pontuação média (Matific)", grupo: "matific", formato: nota },
  { chave: "livros_unicos", rotulo: "Livros únicos (Elefante)", grupo: "elefante" },
  { chave: "tempo_leitura_min", rotulo: "Tempo de leitura", grupo: "elefante", formato: tempoLeitura },
  { chave: "questoes_tentativas", rotulo: "Questões respondidas", grupo: "elefante" },
  { chave: "questoes_acertos", rotulo: "Acertos", grupo: "elefante" },
];

const GRUPOS: { chave: "matific" | "elefante"; titulo: string; icone: LucideIcon; tom: TomPastel }[] = [
  { chave: "elefante", titulo: "Leitura · Elefante Letrado", icone: BookOpen, tom: "violeta" },
  { chave: "matific", titulo: "Matemática · Matific", icone: Calculator, tom: "teal" },
];

const NOTAS: { chave: "matific" | "elefante" | "geral"; rotulo: string; icone: LucideIcon; tom: TomPastel }[] = [
  { chave: "elefante", rotulo: "Nota Elefante Letrado", icone: BookOpen, tom: "violeta" },
  { chave: "matific", rotulo: "Nota Matific", icone: Calculator, tom: "teal" },
  { chave: "geral", rotulo: "Nota Geral", icone: Award, tom: "ambar" },
];

/** Duas barras (A e B) de um indicador, na mesma escala (o maior dos dois). */
function BarrasLado({ rotulo, a, b, formato = (valor: number) => valor.toLocaleString("pt-BR") }: {
  rotulo: string;
  a: { nome: string; valor: number };
  b: { nome: string; valor: number };
  formato?: (valor: number) => string;
}) {
  const maximo = Math.max(a.valor, b.valor, 1);
  return (
    <div className="py-2.5">
      <p className="mb-2 text-[13px] font-semibold text-zinc-700 dark:text-zinc-200">{rotulo}</p>
      {([["A", a], ["B", b]] as const).map(([lado, barra]) => (
        <div key={lado} className="mb-1.5 flex items-center gap-3 last:mb-0">
          <span className="w-28 shrink-0 truncate text-xs text-zinc-500 sm:w-40 dark:text-zinc-400" title={barra.nome}>
            <span className={`font-bold ${LADOS[lado].texto}`}>{lado}</span> · {barra.nome}
          </span>
          <span aria-hidden className="h-2.5 flex-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
            <span
              className={`block h-full rounded-full bg-gradient-to-r ${LADOS[lado].barra}`}
              style={{ width: `${Math.max(2, (barra.valor / maximo) * 100)}%` }}
            />
          </span>
          <span className="w-20 shrink-0 text-right text-sm font-semibold tabular-nums text-zinc-900 dark:text-white">
            {formato(barra.valor)}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Cartão de apresentação de um lado (nome, tipo, alunos e posição quando a API manda). */
function CartaoLado({ lado, dados }: { lado: keyof typeof LADOS; dados: Lado }) {
  const Icone = ICONE_TIPO[dados.tipo] ?? User;
  return (
    <div className={`flex min-w-0 items-center gap-3 rounded-2xl border p-4 ${LADOS[lado].moldura}`}>
      {dados.tipo === "aluno"
        ? <Avatar nome={dados.nome} chave={dados.id} tamanho="lg" />
        : <IconePastel icone={Icone} tom={lado === "A" ? "violeta" : "azul"} tamanho="lg" />}
      <div className="min-w-0">
        <p className={`text-[11px] font-bold uppercase tracking-[0.08em] ${LADOS[lado].texto}`}>Lado {lado}</p>
        <p className="break-words text-base font-semibold text-zinc-900 dark:text-white">{dados.nome}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Chip>{ROTULO_TIPO[dados.tipo] ?? dados.tipo}</Chip>
          {dados.total_alunos != null && <Chip>{numero(dados.total_alunos)} aluno(s)</Chip>}
          {dados.notas.posicao != null && <Chip>{dados.notas.posicao}º no Ranking Geral</Chip>}
        </div>
      </div>
    </div>
  );
}

export default function Comparador() {
  const { escolaId, usuario } = useApp();
  // "Escola" como lado é exclusivo do ADM supremo (rede/Secretaria).
  const podeEscola = !!usuario?.is_global;
  // Opções dos seletores: buscas de leitura (ociosas sem escola) via useApi.
  const { dados: turmas, erro: erroTurmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null,
  );
  const { dados: paginaAlunos, erro: erroAlunos } = useApi<PaginaAlunos>(
    escolaId ? `/escolas/${escolaId}/alunos?por_pagina=100` : null,
  );
  // Lista de escolas p/ o ADM supremo comparar escola×escola (ocioso p/ os demais).
  const { dados: escolasLista } = useApi<Escola[]>(podeEscola ? "/escolas" : null);
  const escolas: OpcaoAluno[] = (escolasLista ?? []).map((e) => ({ id: e.id, nome: e.nome }));
  // Reduz a página de alunos às opções (id + nome) que os seletores consomem.
  const alunos: OpcaoAluno[] = (paginaAlunos?.itens ?? []).map((aluno) => ({ id: aluno.id, nome: aluno.nome }));
  // A busca traz só a 1ª página (100): a tela diz quando há mais alunos que isso.
  const alunosDeFora = paginaAlunos && paginaAlunos.total > alunos.length ? paginaAlunos.total : null;
  const erroOpcoes = erroTurmas ?? erroAlunos;
  const [tipoA, setTipoA] = useState("aluno");
  const [idA, setIdA] = useState("");
  const [tipoB, setTipoB] = useState("turma");
  const [idB, setIdB] = useState("");
  const [comparacao, setComparacao] = useState<Comparacao | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");

  async function comparar() {
    if (!escolaId || !idA || !idB) return;
    setCarregando(true);
    setErro("");
    try {
      const parametros = new URLSearchParams({ tipo_a: tipoA, id_a: idA, tipo_b: tipoB, id_b: idB });
      setComparacao(await api<Comparacao>(`/escolas/${escolaId}/comparar?${parametros}`));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível comparar.");
      setComparacao(null);
    } finally {
      setCarregando(false);
    }
  }

  const comMedia = comparacao != null && (comparacao.a.tipo !== "aluno" || comparacao.b.tipo !== "aluno");

  return (
    <div>
      <PageHeader
        titulo="Comparador"
        descricao="Compare aluno×aluno, aluno×turma ou turma×turma. Para turmas, valores de nota são médias e indicadores são somas."
      />

      <Card className="mb-6 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
          <SeletorLado lado="A" rotulo="Lado A" tipo={tipoA} setTipo={setTipoA} id={idA} setId={setIdA} alunos={alunos} turmas={turmas ?? []} escolas={escolas} podeEscola={podeEscola} />
          <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center self-center rounded-full bg-marinho-900 text-xs font-bold text-white shadow-cartao dark:bg-indigo-500">
            vs
          </span>
          <SeletorLado lado="B" rotulo="Lado B" tipo={tipoB} setTipo={setTipoB} id={idB} setId={setIdB} alunos={alunos} turmas={turmas ?? []} escolas={escolas} podeEscola={podeEscola} />
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-start gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            {alunosDeFora != null && (
              <>
                <Info size={14} aria-hidden className="mt-px shrink-0" />
                <span>
                  A lista de alunos mostra os {numero(alunos.length)} primeiros de {numero(alunosDeFora)} da escola.
                </span>
              </>
            )}
          </p>
          <Botao onClick={comparar} disabled={carregando || !idA || !idB} className="shrink-0">
            <GitCompareArrows size={16} aria-hidden /> Comparar
          </Botao>
        </div>
        {erroOpcoes && <div className="mt-3"><Mensagem tipo="erro">Não foi possível carregar as opções: {erroOpcoes.message}</Mensagem></div>}
        {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      </Card>

      {carregando && <Card><Carregando texto="Comparando…" /></Card>}

      {!carregando && !comparacao && (
        <Card>
          <Vazio
            icone={GitCompareArrows}
            titulo="Escolha os dois lados e clique em Comparar"
            descricao="As notas e os indicadores dos dois aparecem lado a lado, com os dados reais das plataformas."
          />
        </Card>
      )}

      {!carregando && comparacao && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <CartaoLado lado="A" dados={comparacao.a} />
            <CartaoLado lado="B" dados={comparacao.b} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {NOTAS.map((n) => (
              <Card key={n.chave} className="p-5">
                <div className="flex items-center gap-3">
                  <IconePastel icone={n.icone} tom={n.tom} />
                  <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">
                    {n.rotulo}{comMedia && " (média)"}
                  </p>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  {(["a", "b"] as const).map((chave) => {
                    const lado = chave === "a" ? "A" : "B";
                    return (
                      <div key={chave} className="min-w-0">
                        <p className="truncate text-[11px] text-zinc-500 dark:text-zinc-400" title={comparacao[chave].nome}>
                          <span className={`font-bold ${LADOS[lado].texto}`}>{lado}</span> · {comparacao[chave].nome}
                        </p>
                        <p className={`mt-0.5 text-[26px] font-bold leading-tight tabular-nums ${LADOS[lado].texto}`}>
                          {nota(comparacao[chave].notas[n.chave])}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {GRUPOS.map((grupo) => (
              <Card key={grupo.chave} className="p-5">
                <div className="mb-2 flex items-center gap-3">
                  <IconePastel icone={grupo.icone} tom={grupo.tom} />
                  <h2 className="text-base font-semibold text-zinc-900 dark:text-white">{grupo.titulo}</h2>
                </div>
                <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {INDICADORES.filter((i) => i.grupo === grupo.chave).map((indicador) => (
                    <BarrasLado
                      key={indicador.chave}
                      rotulo={indicador.rotulo}
                      a={{ nome: comparacao.a.nome, valor: comparacao.a.indicadores[indicador.chave] ?? 0 }}
                      b={{ nome: comparacao.b.nome, valor: comparacao.b.indicadores[indicador.chave] ?? 0 }}
                      formato={indicador.formato}
                    />
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
