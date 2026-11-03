/**
 * Simulador de pontuação (PRD §44): testa as regras atuais sem gravar nada.
 *
 * Identidade visual v2: os indicadores do aluno HIPOTÉTICO ficam agrupados por
 * plataforma (Leitura · Elefante Letrado e Matemática · Matific; a que a rede não
 * contratou não aparece — useModulos), o resultado vem em cartões com o número
 * grande e a conta de cada indicador ganha uma barra. TODOS os números do
 * resultado vêm do POST /escolas/{id}/simulador (a régua EFETIVA da escola); a
 * tela não refaz conta nenhuma. O corpo do POST não muda.
 */
import { BookOpen, Calculator, FlaskConical, GraduationCap, School } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { CabecalhoCartao } from "../components/CriteriosVisuais";
import {
  BarraProgresso,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  PageHeader,
  StatCard,
  Vazio,
  estiloInput,
  type TomPastel,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
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

/** Cartão de um grupo de campos (ícone pastel + título + campos em grade). */
function GrupoCampos({
  icone,
  tom,
  titulo,
  subtitulo,
  children,
}: {
  icone: LucideIcon;
  tom: TomPastel;
  titulo: string;
  subtitulo?: string;
  children: ReactNode;
}) {
  return (
    <Card className="p-5 sm:p-6">
      <CabecalhoCartao icone={icone} tom={tom} titulo={titulo} subtitulo={subtitulo} />
      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>
    </Card>
  );
}

/** A conta de cada indicador de uma matéria, como o backend a devolveu. */
function ContaDaMateria({
  titulo,
  tom,
  linhas,
}: {
  titulo: string;
  tom: "violeta" | "teal";
  linhas: LinhaCalculo[];
}) {
  if (linhas.length === 0) return null;
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">{titulo}</p>
      <ul className="mt-2 space-y-3">
        {linhas.map((linha) => (
          <li key={linha.indicador}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-sm tabular-nums">
              <span className="font-medium text-zinc-800 dark:text-zinc-100">{linha.indicador}</span>
              <span className="text-zinc-600 dark:text-zinc-300">
                {nota(linha.valor)} → {nota(linha.normalizado)} × {linha.peso}% ={" "}
                <strong className="text-zinc-900 dark:text-white">{nota(linha.contribuicao)}</strong>
              </span>
            </div>
            {/* Quanto do 100 o aluno atingiu neste indicador (o "normalizado" da API). */}
            <BarraProgresso valor={linha.normalizado} tom={tom} className="mt-1.5" />
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Simulador() {
  const { escolaId } = useApp();
  const idDicaNiveis = useId();
  const { leitura, matematica } = useModulos();
  // Turmas da escola (para popular a lista de séries) via hook padrão.
  const { dados: turmas, erro: erroTurmas, carregando: carregandoTurmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null,
  );
  // Valores INICIAIS de um aluno hipotético (editáveis) — não são dado de aluno.
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
          type="number" min={0} max={max} step={step} className={`${estiloInput} tabular-nums`}
          value={formulario[chave] as number}
          onChange={(e) => setFormulario({ ...formulario, [chave]: Number(e.target.value) })}
        />
      </Campo>
    );
  }

  if (!escolaId) {
    return (
      <div>
        <PageHeader titulo="Simulador de Pontuação" />
        <Card>
          <Vazio icone={School} titulo="Selecione uma escola no topo" descricao="O simulador usa a régua da escola escolhida." />
        </Card>
      </div>
    );
  }

  const semTurmas = !carregandoTurmas && !erroTurmas && series.length === 0;

  return (
    <div>
      <PageHeader
        titulo="Simulador de Pontuação"
        descricao="Calcule a nota de um aluno hipotético com a mesma régua que o Constela usa nesta escola. Nada é gravado."
      />

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        {/* --- Os indicadores do aluno hipotético, por plataforma --- */}
        <div className="space-y-6">
          <GrupoCampos
            icone={GraduationCap}
            tom="neutro"
            titulo="Aluno hipotético"
            subtitulo="Os números abaixo são só um ponto de partida: troque à vontade."
          >
            <Campo rotulo="Série (dificuldade por turma)">
              <select
                className={estiloInput}
                value={formulario.ano_escolar}
                onChange={(e) => setFormulario({ ...formulario, ano_escolar: e.target.value })}
              >
                {series.length === 0 && (
                  <option value="">{carregandoTurmas ? "Carregando turmas..." : "Nenhuma turma"}</option>
                )}
                {series.map((serie) => <option key={serie} value={serie}>{serie}</option>)}
              </select>
            </Campo>
            {semTurmas && (
              <p className="self-end text-xs text-zinc-500 dark:text-zinc-400 sm:pb-3">
                Cadastre turmas para simular: a série decide a dificuldade dos livros.
              </p>
            )}
          </GrupoCampos>

          {leitura && (
            <GrupoCampos
              icone={BookOpen}
              tom="violeta"
              titulo="Leitura · Elefante Letrado"
              subtitulo="Livros, tempo e questões do aluno."
            >
              <div className="sm:col-span-2">
                <Campo rotulo="Livros por nível">
                  <input className={estiloInput} value={formulario.niveis_texto}
                         aria-describedby={idDicaNiveis}
                         onChange={(e) => setFormulario({ ...formulario, niveis_texto: e.target.value })} />
                </Campo>
                {/* O formato explicado em linguagem simples (antes o rótulo só dizia
                    "ex.: AA:2, D:1", um código sem explicação). */}
                <p id={idDicaNiveis} className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                  Escreva o nível do Elefante Letrado, dois-pontos e quantos livros, separando com vírgula.
                  Exemplo: “AA:2, D:1” são 2 livros do nível AA e 1 do nível D.
                </p>
              </div>
              {numeroCampo("Tempo de leitura (min)", "tempo_leitura_min")}
              {numeroCampo("Questões (tentativas)", "questoes_tentativas")}
              {numeroCampo("Acertos", "questoes_acertos")}
            </GrupoCampos>
          )}

          {matematica && (
            <GrupoCampos
              icone={Calculator}
              tom="teal"
              titulo="Matemática · Matific"
              subtitulo="Atividades, média e estrelas do aluno."
            >
              {numeroCampo("Atividades (Matific)", "atividades")}
              {numeroCampo("Pontuação média (0 a 5)", "pontuacao_media", 5, "0.1")}
              {numeroCampo("Estrelas", "estrelas")}
            </GrupoCampos>
          )}

          {erroTurmas && <Mensagem tipo="erro">{erroTurmas.message}</Mensagem>}
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <div className="flex flex-wrap items-center gap-3">
            <Botao tamanho="lg" onClick={simular} disabled={ocupado || !formulario.ano_escolar}>
              <FlaskConical size={16} aria-hidden /> {ocupado ? "Calculando..." : "Simular nota"}
            </Botao>
            <span className="text-sm text-zinc-500 dark:text-zinc-400">Nada é gravado.</span>
          </div>
        </div>

        {/* --- O resultado (todos os números vêm da API) --- */}
        <div className="space-y-6 xl:sticky xl:top-6">
          {ocupado && (
            <Card>
              <Carregando texto="Calculando..." />
            </Card>
          )}
          {resultado && !ocupado && (
            <>
              <div className={`grid gap-4 ${leitura && matematica ? "sm:grid-cols-2" : ""}`}>
                {leitura && (
                  <StatCard
                    icone={<BookOpen size={20} aria-hidden />}
                    tom="violeta"
                    rotulo="Leitura · Elefante"
                    valor={nota(resultado.elefante.nota)}
                    detalhe="nota de 0 a 100"
                  />
                )}
                {matematica && (
                  <StatCard
                    icone={<Calculator size={20} aria-hidden />}
                    tom="teal"
                    rotulo="Matemática · Matific"
                    valor={nota(resultado.matific.nota)}
                    detalhe="nota de 0 a 100"
                  />
                )}
              </div>

              <Card className="p-5 sm:p-6">
                <p className="text-[17px] font-semibold text-zinc-900 dark:text-white">Como chegamos aqui</p>
                <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">
                  Cada indicador: valor → nota de 0 a 100 × peso = quanto ele soma na nota.
                </p>
                <div className="mt-5 space-y-6">
                  {leitura && (
                    <ContaDaMateria titulo="Leitura · Elefante Letrado" tom="violeta" linhas={resultado.elefante.indicadores} />
                  )}
                  {matematica && (
                    <ContaDaMateria titulo="Matemática · Matific" tom="teal" linhas={resultado.matific.indicadores} />
                  )}
                </div>

                <div className="mt-6 space-y-1 border-t border-zinc-100 pt-4 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  {/* QUAL régua produziu estes números. No perfil institucional
                      (padrão) o motor ignora a configuração local de pesos e
                      referências — dizer "os pesos da escola" seria falso. */}
                  <p>
                    Régua:{" "}
                    {resultado.perfil === "personalizado"
                      ? "personalizada desta escola, autorizada pela Constela"
                      : "Régua Padrão Constela — a mesma para toda a rede (a configuração local de pesos e referências não entra nesta conta)"}
                  </p>
                  <p>
                    Pontos de dificuldade: {nota(resultado.pontos_dificuldade)} · Normalização:{" "}
                    {resultado.modo_normalizacao === "auto" ? "automática" : "manual"}
                  </p>
                  {/* LEGADO: a Nota Geral junta as matérias e só ordena o Ranking
                      Geral, o certificado "Geral" e as vitrines — fica em segundo plano. */}
                  <p>
                    Nota Geral (legado): <span className="tabular-nums">{nota(resultado.geral.nota)}</span> — ordena só
                    o Ranking Geral, o certificado “Geral” e as vitrines.
                  </p>
                </div>
              </Card>
            </>
          )}
          {!resultado && !ocupado && (
            <Card>
              <Vazio
                icone={FlaskConical}
                titulo="Preencha os indicadores e clique em “Simular nota”."
                descricao="O resultado aparece aqui, com a conta de cada indicador."
              />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
