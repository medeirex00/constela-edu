/** Simulador de pontuação (PRD §44): testa as regras atuais sem gravar nada. */
import { FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";

import { Botao, Campo, Card, Carregando, Mensagem, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nota } from "../lib/formato";
import type { LinhaCalculo, Turma } from "../lib/types";

/** Vocabulário OFICIAL de níveis do Elefante — o mesmo que o servidor valida e o
 *  mesmo de Elefante.tsx (ainda duplicado nas duas telas; ver pendências). */
const NIVEIS_OFICIAIS = new Set([
  "AA", "BB", "CC", "DD", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
  "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "Z+", "A+",
]);

/** Interpreta "AA:2, Z+:3". Cada pedaço precisa ser um nível oficial (AA…Z, Z+,
 *  A+) com contagem inteira; qualquer pedaço inválido devolve ERRO.
 *
 *  A regex anterior (`/([A-Za-z]{1,2})\s*[:=]\s*(\d+)/`) descartava Z+ e A+ em
 *  silêncio e transformava "pre_leitor" no nível inexistente "OR": o simulador
 *  calculava uma distribuição que ninguém digitou, e a nota saía menor sem
 *  aviso nenhum. Errar em voz alta é melhor do que simular outro aluno. */
function textoParaNiveis(texto: string): { niveis: Record<string, number> } | { erro: string } {
  const niveis: Record<string, number> = {};
  const invalidos: string[] = [];
  for (const pedaco of texto.split(/[,;\n]/).map((p) => p.trim()).filter(Boolean)) {
    const partes = /^([A-Za-z][A-Za-z0-9_]*\+?)\s*[:=]\s*(\d+)$/.exec(pedaco);
    const codigo = partes ? partes[1].toUpperCase() : "";
    if (!partes || !NIVEIS_OFICIAIS.has(codigo)) {
      invalidos.push(pedaco);
      continue;
    }
    niveis[codigo] = (niveis[codigo] ?? 0) + Number(partes[2]);
  }
  if (invalidos.length > 0) {
    return {
      erro:
        `Texto inválido: ${invalidos.map((p) => `“${p}”`).join(", ")}. Use níveis do Elefante ` +
        "(AA…Z, Z+, A+) no formato AA:2, D:1.",
    };
  }
  return { niveis };
}

interface Resultado {
  /** Régua que produziu esta simulação: a institucional da rede (padrão) ou a
   *  personalizada desta escola. No perfil institucional o motor IGNORA a
   *  configuração local de pesos/referências — e o simulador também. */
  perfil?: "institucional" | "personalizado";
  modo_normalizacao: string;
  pontos_dificuldade: number;
  matific: { indicadores: LinhaCalculo[]; nota: number };
  elefante: { indicadores: LinhaCalculo[]; nota: number };
  /** LEGADO: a composição entre matérias. `legado: true` vem do backend. */
  geral: { pesos: Record<string, number>; nota: number; legado?: boolean };
}

export default function Simulador() {
  const { escolaId } = useApp();
  // Turmas da escola (para popular a lista de séries) via hook padrão.
  const { dados: turmas, erro: erroTurmas } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);
  const [formulario, setFormulario] = useState({
    ano_escolar: "",
    atividades: 20,
    pontuacao_media: 4,
    estrelas: 100,
    niveis_texto: "AA:2, D:1",
    tempo_leitura_min: 120,
    questoes_tentativas: 20,
    questoes_acertos: 15,
  });
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  // Ao carregar as turmas, define a série padrão do formulário.
  useEffect(() => {
    if (!turmas) return;
    setFormulario((atual) => ({ ...atual, ano_escolar: atual.ano_escolar || turmas[0]?.ano_escolar || "" }));
  }, [turmas]);

  const series = Array.from(new Set((turmas ?? []).map((turma) => turma.ano_escolar))).sort();

  async function simular() {
    if (!escolaId || !formulario.ano_escolar) return;
    // Distribuição inválida não vira simulação: mostra o erro e NÃO chama a API
    // (simular com os níveis que sobraram seria simular outro aluno).
    const analise = textoParaNiveis(formulario.niveis_texto);
    if ("erro" in analise) {
      setErro(analise.erro);
      setResultado(null);
      return;
    }
    setOcupado(true);
    setErro("");
    try {
      setResultado(
        await api<Resultado>(`/escolas/${escolaId}/simulador`, {
          method: "POST",
          body: JSON.stringify({
            ano_escolar: formulario.ano_escolar,
            atividades: formulario.atividades,
            pontuacao_media: formulario.pontuacao_media,
            estrelas: formulario.estrelas,
            livros_por_nivel: analise.niveis,
            tempo_leitura_min: formulario.tempo_leitura_min,
            questoes_tentativas: formulario.questoes_tentativas,
            questoes_acertos: formulario.questoes_acertos,
          }),
        }),
      );
    } catch (excecao) {
      // ApiError carrega .status: 0 = falha de transporte (sem rede / servidor
      // reiniciando) → mostra a mensagem de conexão; >0 = erro do servidor →
      // mostra o código, para não mascarar um 4xx/5xx como "sem internet".
      const status = (excecao as { status?: number })?.status;
      const msg = excecao instanceof Error ? excecao.message : "Falha na simulação.";
      setErro(status ? `Erro ${status}: ${msg}` : msg);
    } finally {
      setOcupado(false);
    }
  }

  function numeroCampo(rotulo: string, chave: keyof typeof formulario, max?: number, step?: string) {
    return (
      <Campo rotulo={rotulo}>
        <input
          type="number" min={0} max={max} step={step} className={estiloInput}
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
        descricao="Calcule a nota de um aluno hipotético com a MESMA régua que o motor aplica nesta escola. Nada é gravado."
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
            {numeroCampo("Pontuação média (0 a 5)", "pontuacao_media", 5, "0.1")}
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
          {erroTurmas && (
            <div className="mt-3"><Mensagem tipo="erro">{erroTurmas.message}</Mensagem></div>
          )}
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
                {/* QUAL régua produziu estes números. No perfil institucional
                    (padrão) o motor ignora a configuração local de pesos e
                    referências — dizer "os pesos da escola" seria falso. */}
                <p className="mt-3 text-xs text-zinc-400">
                  Régua:{" "}
                  {resultado.perfil === "personalizado"
                    ? "personalizada desta escola, autorizada pela Constela"
                    : "Régua Padrão Constela — a mesma para toda a rede (a configuração local de pesos e referências não entra nesta conta)"}
                </p>
                <p className="mt-1 text-xs text-zinc-400">
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
