/** Simulador de pontuação (PRD §44): testa as regras atuais sem gravar nada. */
import { FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";

import { Botao, Campo, Card, Carregando, Mensagem, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { nota } from "../lib/formato";
import type { LinhaCalculo, Turma } from "../lib/types";

interface Resultado {
  modo_normalizacao: string;
  pontos_dificuldade: number;
  matific: { indicadores: LinhaCalculo[]; nota: number };
  elefante: { indicadores: LinhaCalculo[]; nota: number };
  geral: { pesos: Record<string, number>; nota: number };
}

export default function Simulador() {
  const { escolaId } = useApp();
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [formulario, setFormulario] = useState({
    ano_escolar: "",
    atividades: 20,
    pontuacao_media: 75,
    estrelas: 100,
    niveis_texto: "AA:2, D:1",
    tempo_leitura_min: 120,
    questoes_tentativas: 20,
    questoes_acertos: 15,
  });
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then((lista) => {
      setTurmas(lista);
      setFormulario((atual) => ({ ...atual, ano_escolar: atual.ano_escolar || lista[0]?.ano_escolar || "" }));
    }).catch(() => setTurmas([]));
  }, [escolaId]);

  const series = Array.from(new Set(turmas.map((turma) => turma.ano_escolar))).sort();

  async function simular() {
    if (!escolaId || !formulario.ano_escolar) return;
    setOcupado(true);
    setErro("");
    try {
      const niveis: Record<string, number> = {};
      for (const [, codigo, quantidade] of formulario.niveis_texto.matchAll(/([A-Za-z]{1,2})\s*[:=]\s*(\d+)/g)) {
        niveis[codigo.toUpperCase()] = Number(quantidade);
      }
      setResultado(
        await api<Resultado>(`/escolas/${escolaId}/simulador`, {
          method: "POST",
          body: JSON.stringify({
            ano_escolar: formulario.ano_escolar,
            atividades: formulario.atividades,
            pontuacao_media: formulario.pontuacao_media,
            estrelas: formulario.estrelas,
            livros_por_nivel: niveis,
            tempo_leitura_min: formulario.tempo_leitura_min,
            questoes_tentativas: formulario.questoes_tentativas,
            questoes_acertos: formulario.questoes_acertos,
          }),
        }),
      );
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha na simulação.");
    } finally {
      setOcupado(false);
    }
  }

  function numeroCampo(rotulo: string, chave: keyof typeof formulario, max?: number) {
    return (
      <Campo rotulo={rotulo}>
        <input
          type="number" min={0} max={max} className={estiloInput}
          value={formulario[chave] as number}
          onChange={(e) => setFormulario({ ...formulario, [chave]: Number(e.target.value) })}
        />
      </Campo>
    );
  }

  return (
    <div>
      <PageHeader
        titulo="Simulador de Pontuação"
        descricao="Calcule a nota de um aluno hipotético com os pesos e referências ATUAIS da escola. Nada é gravado."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <div className="grid grid-cols-2 gap-3">
            <Campo rotulo="Série (dificuldade por turma)">
              <select className={estiloInput} value={formulario.ano_escolar}
                      onChange={(e) => setFormulario({ ...formulario, ano_escolar: e.target.value })}>
                {series.map((serie) => <option key={serie} value={serie}>{serie}</option>)}
              </select>
            </Campo>
            {numeroCampo("Atividades (Matific)", "atividades")}
            {numeroCampo("Pontuação média", "pontuacao_media", 100)}
            {numeroCampo("Estrelas", "estrelas")}
            <div className="col-span-2">
              <Campo rotulo="Livros por nível (ex.: AA:2, D:1)">
                <input className={estiloInput} value={formulario.niveis_texto}
                       onChange={(e) => setFormulario({ ...formulario, niveis_texto: e.target.value })} />
              </Campo>
            </div>
            {numeroCampo("Tempo de leitura (min)", "tempo_leitura_min")}
            {numeroCampo("Questões (tentativas)", "questoes_tentativas")}
            {numeroCampo("Acertos", "questoes_acertos")}
          </div>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4">
            <Botao onClick={simular} disabled={ocupado || !formulario.ano_escolar}>
              <FlaskConical size={15} /> {ocupado ? "Calculando..." : "Simular nota"}
            </Botao>
          </div>
        </Card>

        <div className="space-y-4">
          {ocupado && <Carregando texto="Calculando..." />}
          {resultado && !ocupado && (
            <>
              <div className="grid grid-cols-3 gap-3">
                <Card className="p-4">
                  <p className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Matific</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{nota(resultado.matific.nota)}</p>
                </Card>
                <Card className="p-4">
                  <p className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Elefante</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{nota(resultado.elefante.nota)}</p>
                </Card>
                <Card className="border-indigo-200 p-4 dark:border-indigo-500/30">
                  <p className="text-xs uppercase tracking-wide text-indigo-600 dark:text-indigo-400">Geral</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{nota(resultado.geral.nota)}</p>
                </Card>
              </div>
              <Card className="p-4 text-sm">
                <p className="mb-2 font-medium">Como chegamos aqui</p>
                <ul className="space-y-1 text-zinc-600 dark:text-zinc-300">
                  {[...resultado.matific.indicadores, ...resultado.elefante.indicadores].map((linha) => (
                    <li key={linha.indicador} className="flex justify-between tabular-nums">
                      <span>{linha.indicador}</span>
                      <span>
                        {nota(linha.valor)} → {nota(linha.normalizado)} × {linha.peso}% ={" "}
                        <strong>{nota(linha.contribuicao)}</strong>
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-xs text-zinc-400">
                  Pontos de dificuldade: {nota(resultado.pontos_dificuldade)} · Normalização:{" "}
                  {resultado.modo_normalizacao === "auto" ? "automática" : "manual"}
                </p>
              </Card>
            </>
          )}
          {!resultado && !ocupado && (
            <Card className="p-8 text-center text-sm text-zinc-400">
              Preencha os indicadores e clique em “Simular nota”.
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
