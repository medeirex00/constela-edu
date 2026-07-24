/** Comparador aluno×aluno, aluno×turma e turma×turma (PRD §73–§75). */
import { GitCompareArrows } from "lucide-react";
import { useState } from "react";

import { BarraDupla } from "../components/Grafico";
import { Botao, Campo, Card, Carregando, Mensagem, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nota, tempoLeitura } from "../lib/formato";
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

function SeletorLado({
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
    <div className="grid flex-1 gap-2 sm:grid-cols-2">
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
  );
}

const INDICADORES: { chave: string; rotulo: string; formato?: (valor: number) => string }[] = [
  { chave: "atividades", rotulo: "Atividades (Matific)" },
  { chave: "estrelas", rotulo: "Estrelas (Matific)" },
  { chave: "pontuacao_media", rotulo: "Pontuação média (Matific)", formato: nota },
  { chave: "livros_unicos", rotulo: "Livros únicos (Elefante)" },
  { chave: "tempo_leitura_min", rotulo: "Tempo de leitura", formato: tempoLeitura },
  { chave: "questoes_tentativas", rotulo: "Questões respondidas" },
  { chave: "questoes_acertos", rotulo: "Acertos" },
];

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

  return (
    <div>
      <PageHeader
        titulo="Comparador"
        descricao="Compare aluno×aluno, aluno×turma ou turma×turma. Para turmas, valores de nota são médias e indicadores são somas."
      />

      <Card className="mb-6 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <SeletorLado rotulo="Lado A" tipo={tipoA} setTipo={setTipoA} id={idA} setId={setIdA} alunos={alunos} turmas={turmas ?? []} escolas={escolas} podeEscola={podeEscola} />
          <SeletorLado rotulo="Lado B" tipo={tipoB} setTipo={setTipoB} id={idB} setId={setIdB} alunos={alunos} turmas={turmas ?? []} escolas={escolas} podeEscola={podeEscola} />
          <Botao onClick={comparar} disabled={carregando || !idA || !idB} className="shrink-0">
            <GitCompareArrows size={15} /> Comparar
          </Botao>
        </div>
        {erroOpcoes && <div className="mt-3"><Mensagem tipo="erro">Não foi possível carregar as opções: {erroOpcoes.message}</Mensagem></div>}
        {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      </Card>

      {carregando && <Carregando />}

      {!carregando && !comparacao && (
        <Card>
          <Vazio titulo="Escolha os dois lados e clique em Comparar" />
        </Card>
      )}

      {comparacao && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            {(["matific", "elefante", "geral"] as const).map((chave) => (
              <Card key={chave} className="p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Nota {chave === "geral" ? "Geral" : chave === "matific" ? "Matific" : "Elefante Letrado"}
                  {(comparacao.a.tipo !== "aluno" || comparacao.b.tipo !== "aluno") && " (média)"}
                </p>
                <div className="mt-2 flex items-end justify-between">
                  <div>
                    <p className="text-[11px] text-zinc-400">{comparacao.a.nome}</p>
                    <p className="text-xl font-semibold tabular-nums text-indigo-600 dark:text-indigo-400">
                      {nota(comparacao.a.notas[chave])}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[11px] text-zinc-400">{comparacao.b.nome}</p>
                    <p className="text-xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                      {nota(comparacao.b.notas[chave])}
                    </p>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">Indicadores lado a lado</h3>
            {INDICADORES.map((indicador) => (
              <BarraDupla
                key={indicador.chave}
                rotulo={indicador.rotulo}
                nomeA={comparacao.a.nome}
                valorA={comparacao.a.indicadores[indicador.chave] ?? 0}
                nomeB={comparacao.b.nome}
                valorB={comparacao.b.indicadores[indicador.chave] ?? 0}
                formato={indicador.formato}
              />
            ))}
          </Card>
        </div>
      )}
    </div>
  );
}
