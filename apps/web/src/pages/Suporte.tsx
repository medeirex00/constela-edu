/**
 * Suporte — a ajuda do Constela DENTRO do sistema (antes o item do menu só
 * abria a pasta dos guias no Google Drive).
 *
 * Para o perfil de quem abre: o guia em PDF do perfil, as dúvidas mais comuns,
 * a regra da nota COMO O MOTOR A APLICA nesta escola (lida de
 * `GET /configuracoes/pontuacao/regra` — nenhum número da fórmula mora aqui), o
 * exemplo interativo da conta (o mesmo da Pontuação, calculado pelo servidor) e
 * o que fazer quando os dados parecem desatualizados.
 */
import { BookOpen, Calculator, CircleHelp, FileText, LifeBuoy, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import ExemploPontuacao from "../components/ExemploPontuacao";
import { Card, Carregando, Mensagem, PageHeader, SecaoRecolhivel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import {
  FAQ_COORDENACAO,
  FAQ_PROFESSOR,
  FAQ_SECRETARIA,
  SINCRONIZACAO_GESTAO,
  SINCRONIZACAO_LEITURA,
  type Pergunta,
} from "./suporteConteudo";

// Guias em PDF: pastas da pasta "Constela Edu" do Google Drive (a mesma que o
// item Suporte abria). Link de PASTA, não de arquivo: o guia atualizado entra no
// lugar do anterior sem mudar o link.
const DRIVE = "https://drive.google.com/drive/folders/";
export const PASTAS_GUIAS = {
  todos: `${DRIVE}1kbDGPRSsh7TOb6nk6smwXNyAJPkySk-i`,
  coordenacao: `${DRIVE}166WOuY7cdPfZc2_9-AMPpOUgfHGxJADg`,
  professor: `${DRIVE}16rRU9rSohX2Ky4sjvM0mknQPrTBcl4Ge`,
  secretaria: `${DRIVE}1MugoOUvDf9G2rOiUjQOpv9zagqbYp6yf`,
} as const;

/** A regra da nota desta escola, como o servidor a devolve. */
export interface RegraPontuacao {
  perfil: "institucional" | "personalizado";
  versoes: { composicao: string; dificuldade: string; dificuldade_da_rede: string };
  dimensoes: Array<{
    dimensao: "leitura" | "matematica";
    plataforma: string;
    contratada: boolean;
    pesos: Record<string, number>;
    subpesos_questoes?: Record<string, number>;
  }>;
  normalizacao: {
    modo: "auto" | "manual";
    percentil_referencia: number;
    minimo_alunos_percentil: number;
    indicadores_volume: string[];
  };
}

// Nome de cada indicador como a tela "Como funciona?" já o chama.
const NOME_INDICADOR: Record<string, string> = {
  livros: "livros únicos",
  dificuldade: "dificuldade dos livros",
  questoes: "questões",
  tempo: "tempo de leitura",
  tentativas: "questões respondidas",
  acertos: "acertos",
  atividades: "atividades finalizadas",
  media: "pontuação média",
  estrelas: "estrelas",
};

const NOME_DIMENSAO: Record<string, string> = {
  leitura: "Leitura (Elefante Letrado)",
  matematica: "Matemática (Matific)",
};

// Versões conhecidas em linguagem de gente; o código técnico aparece ao lado
// para quem precisa conferir.
const NOME_VERSAO: Record<string, string> = {
  por_dimensao_v1: "uma nota por matéria, sem nota única misturando as duas",
  elefante_dificuldade_v2: "régua de dificuldade dos livros da rede, versão 2",
  elefante_dificuldade_v1: "régua de dificuldade dos livros da rede, versão 1",
  escola_legada_v0: "régua própria da escola, por faixa de nível",
};

const formatoPeso = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

function Pesos({ pesos }: { pesos: Record<string, number> }) {
  return (
    <ul className="mt-1 space-y-0.5">
      {Object.entries(pesos).map(([chave, valor]) => (
        <li key={chave} className="flex justify-between gap-4 tabular-nums">
          <span>{NOME_INDICADOR[chave] ?? chave}</span>
          <span className="font-medium">{formatoPeso.format(valor)}%</span>
        </li>
      ))}
    </ul>
  );
}

function RegraDaNota({ escolaId }: { escolaId: number }) {
  const { dados, erro, carregando } = useApi<RegraPontuacao>(
    `/escolas/${escolaId}/configuracoes/pontuacao/regra`);
  if (carregando) return <Carregando texto="Carregando a regra desta escola..." />;
  if (erro || !dados) {
    return <Mensagem tipo="erro">Não foi possível carregar a regra da nota agora. Tente de novo em instantes.</Mensagem>;
  }
  const { normalizacao: n } = dados;
  const volume = n.indicadores_volume.map((i) => NOME_INDICADOR[i] ?? i).join(", ");
  return (
    <div className="space-y-4 text-sm text-zinc-700 dark:text-zinc-300">
      <p>
        Cada aluno tem uma nota de 0 a 100 <strong>por matéria</strong>, calculada pelo Constela a cada
        atualização dos dados. Nada é digitado à mão, e a nota de uma matéria só usa dados da plataforma
        dela.
        {dados.perfil === "institucional"
          ? " Esta escola usa a régua da rede: os mesmos pesos e a mesma régua para todas as escolas."
          : " Esta escola usa uma régua própria, autorizada pela administração do Constela; por isso os pesos abaixo podem ser diferentes dos de outras escolas."}
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        {dados.dimensoes.map((d) => (
          <Card key={d.dimensao} className="p-3">
            <p className="font-medium text-zinc-900 dark:text-zinc-100">{NOME_DIMENSAO[d.dimensao]}</p>
            {d.contratada ? (
              <>
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Quanto cada indicador pesa:</p>
                <Pesos pesos={d.pesos} />
                {d.subpesos_questoes && (
                  <>
                    <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">Dentro de “questões”:</p>
                    <Pesos pesos={d.subpesos_questoes} />
                  </>
                )}
              </>
            ) : (
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Esta matéria não faz parte do plano da rede: não há nota dela.
              </p>
            )}
          </Card>
        ))}
      </div>

      <div className="space-y-1">
        <p className="font-medium text-zinc-900 dark:text-zinc-100">Como o aluno é comparado</p>
        {n.modo === "auto" ? (
          <p>
            Cada indicador vira um número de 0 a 100 comparando o aluno com a própria escola. O 100 é o
            valor de quem está no percentil {n.percentil_referencia} — assim um único aluno muito acima
            dos outros não define a régua sozinho — quando a matéria tem pelo menos{" "}
            {n.minimo_alunos_percentil} alunos com dado; com menos, o 100 é o maior valor da escola. Em{" "}
            {volume}, cada unidade a mais vale um pouco menos que a anterior: dobrar a quantidade não
            dobra a nota.
          </p>
        ) : (
          <p>
            Esta escola usa referências fixas definidas pela administração do Constela (modo manual): o
            100 de cada indicador é o valor dessa referência.
          </p>
        )}
      </div>

      <div className="space-y-1">
        <p className="font-medium text-zinc-900 dark:text-zinc-100">Quando falta dado</p>
        <p>
          Aluno sem dado de uma plataforma fica <strong>fora do ranking daquela matéria</strong> — não
          entra com zero. Quem já tem dado da plataforma, mas ainda não fez nada, entra com 0 e aparece no
          fim da lista. Livro sem nível de dificuldade conhecido conta como livro lido, mas não soma
          pontos de dificuldade.
        </p>
      </div>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Versão da regra: {NOME_VERSAO[dados.versoes.composicao] ?? dados.versoes.composicao}{" "}
        <code>({dados.versoes.composicao})</code>; {NOME_VERSAO[dados.versoes.dificuldade] ?? dados.versoes.dificuldade}{" "}
        <code>({dados.versoes.dificuldade})</code>.
      </p>
    </div>
  );
}

function ListaPerguntas({ perguntas }: { perguntas: Pergunta[] }) {
  return (
    <dl className="space-y-3 text-sm">
      {perguntas.map((p) => (
        <div key={p.pergunta}>
          <dt className="font-medium text-zinc-900 dark:text-zinc-100">{p.pergunta}</dt>
          <dd className="mt-0.5 text-zinc-700 dark:text-zinc-300">{p.resposta}</dd>
        </div>
      ))}
    </dl>
  );
}

function LinkExterno({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
       className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
      {children}
    </a>
  );
}

export default function Suporte() {
  const { escolaId } = useApp();
  const { global, secretaria, gestor } = usePerfil();
  // Perfil para o conteúdo: Admin Global vê o da coordenação (opera escolas).
  const perfil = secretaria ? "secretaria" : gestor || global ? "coordenacao" : "professor";
  const perguntas = perfil === "secretaria" ? FAQ_SECRETARIA
    : perfil === "coordenacao" ? FAQ_COORDENACAO : FAQ_PROFESSOR;
  const guia = perfil === "secretaria" ? "Guia da Secretaria"
    : perfil === "coordenacao" ? "Guia da Coordenação" : "Guia do Professor";
  // O exemplo da conta é das telas de gestão (o servidor libera admin,
  // coordenação e Secretaria); o professor fica com a explicação.
  const mostraExemplo = gestor && escolaId != null;

  return (
    <div className="space-y-4">
      <PageHeader
        titulo="Suporte"
        descricao="Respostas rápidas, como a nota é calculada e o guia completo do seu perfil."
      />

      <SecaoRecolhivel titulo="Guia completo em PDF" icone={<FileText size={16} aria-hidden />}>
        <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
          <p>
            O <strong>{guia}</strong> explica cada tela passo a passo. Ele fica numa pasta do Google
            Drive e abre em outra aba.
          </p>
          <p className="flex flex-wrap gap-x-4 gap-y-1">
            <LinkExterno href={PASTAS_GUIAS[perfil]}>Abrir o {guia}</LinkExterno>
            <LinkExterno href={PASTAS_GUIAS.todos}>Ver todos os guias</LinkExterno>
          </p>
        </div>
      </SecaoRecolhivel>

      <SecaoRecolhivel titulo="Perguntas frequentes" icone={<CircleHelp size={16} aria-hidden />}>
        <ListaPerguntas perguntas={perguntas} />
      </SecaoRecolhivel>

      <SecaoRecolhivel titulo="Como a nota é calculada" icone={<Calculator size={16} aria-hidden />}>
        {escolaId != null ? (
          <div className="space-y-4">
            <RegraDaNota escolaId={escolaId} />
            {mostraExemplo && <ExemploPontuacao escolaId={escolaId} />}
          </div>
        ) : (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Selecione uma escola no topo para ver a regra da nota dela.
          </p>
        )}
      </SecaoRecolhivel>

      <SecaoRecolhivel titulo="Os dados estão atualizados?" icone={<RefreshCw size={16} aria-hidden />}>
        <ListaPerguntas perguntas={perfil === "coordenacao" ? SINCRONIZACAO_GESTAO : SINCRONIZACAO_LEITURA} />
        {perfil === "coordenacao" && (
          <p className="mt-3 text-sm">
            <Link to="/sincronizacao" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
              Abrir Integrações
            </Link>
          </p>
        )}
      </SecaoRecolhivel>

      <SecaoRecolhivel titulo="Ainda precisa de ajuda?" icone={<LifeBuoy size={16} aria-hidden />}>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {perfil === "professor"
            ? "Fale com a coordenação da sua escola: ela acompanha as integrações e as revisões de identidade."
            : perfil === "coordenacao"
              ? "Fale com a Secretaria de Educação ou com a equipe que implantou o Constela na rede. Conte o que tentou, a tela e o horário — isso agiliza a resposta."
              : "Fale com a equipe que implantou o Constela na rede. Conte o que tentou, a tela e o horário — isso agiliza a resposta."}
        </p>
        <p className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <BookOpen size={14} aria-hidden /> O guia em PDF tem o passo a passo de cada tela.
        </p>
      </SecaoRecolhivel>
    </div>
  );
}
