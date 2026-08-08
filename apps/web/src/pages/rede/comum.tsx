/**
 * Peças COMPARTILHADAS das telas de rede (Secretaria / Admin Global).
 *
 * Vive fora de `RedeDashboard.tsx` de propósito: aquele módulo importa o Leaflet
 * no topo (mapa das escolas), então qualquer tela que reusasse o envelope da rede
 * arrastaria o mapa junto — chunk maior e jsdom quebrando nos testes. Aqui só há
 * tipos + o resolvedor de `redeId`, sem dependência pesada.
 */
import { Settings2 } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { Botao, Carregando, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";

export const MEDALHAS = ["🥇", "🥈", "🥉"];

/** Cartão AGREGADO de uma escola da rede (nunca PII de criança). */
export interface EscolaCartao {
  escola_id: number;
  nome: string;
  cidade: string | null;
  status: string;
  latitude: number | null;
  longitude: number | null;
  total_turmas: number;
  total_professores: number;
  total_alunos: number;
  alunos_com_dados: number;
  adocao: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  // Totais brutos das plataformas (snapshot atual de cada aluno).
  livros: number;
  tempo_leitura_min: number;
  atividades: number;
  estrelas: number;
  ativos_matific: number;
  ativos_elefante: number;
  livros_por_aluno: number;
  // Per capita por MATRÍCULA (÷ total de alunos) — critério de ranking JUSTO entre
  // escolas de tamanhos diferentes (não favorece a escola grande pelo volume bruto).
  livros_por_matricula: number;
  estrelas_por_matricula: number;
  atividades_por_matricula: number;
  tempo_por_matricula_min: number;
  // Índice da REDE (0–1000): o per capita normalizado na régua da rede (melhor
  // escola = 1000). Comparável ENTRE escolas — ao contrário de media_* (0–100),
  // que é normalizada dentro da própria escola e serve ao ranking interno.
  pontuacao_leitura: number;
  pontuacao_matematica: number;
  pontuacao_geral: number;
  dimensoes_pontuadas: string[];
  precisa_atencao: boolean;
  motivo_atencao: string | null;
  posicao?: number;
}

export interface DashboardRede {
  rede_id: number;
  totais: {
    escolas: number;
    escolas_ativas: number;
    alunos: number;
    turmas: number;
    professores: number;
    alunos_com_dados: number;
    adocao: number;
    media_geral: number;
    media_matific: number;
    media_elefante: number;
    escolas_em_atencao: number;
    livros: number;
    tempo_leitura_min: number;
    atividades: number;
    estrelas: number;
    ativos_matific: number;
    ativos_elefante: number;
    livros_por_aluno: number;
    melhor_escola: { nome: string; media_geral: number } | null;
  };
  equidade: {
    gap_media: number;
    escola_maior_media: number;
    escola_menor_media: number;
    escolas_abaixo_da_media: number;
  };
  escolas: EscolaCartao[];
  atencao: EscolaCartao[];
}

/** Resolve a rede do usuário (Secretaria = a própria; Admin Global = a 1ª) e só
 *  então renderiza o conteúdo. Trata carregamento e o caso "sem rede". */
export function EnvolucroRede({ children }: { children: (redeId: number) => ReactNode }) {
  const { usuario } = useApp();
  const navegar = useNavigate();
  const redeDoUsuario = usuario?.rede_id ?? null;
  const { dados: redes, carregando } = useApi<{ id: number; nome: string }[]>(
    redeDoUsuario == null ? "/redes" : null,
  );
  const redeId = redeDoUsuario ?? redes?.[0]?.id ?? null;

  if (redeId == null) {
    if (carregando) return <Carregando texto="Carregando as redes..." />;
    // Admin global sem nenhuma rede: oferece criar a primeira (bootstrap).
    return (
      <div className="space-y-4">
        <Vazio
          titulo="Nenhuma rede disponível"
          descricao={usuario?.is_global
            ? "Ainda não há redes cadastradas. Crie a primeira para habilitar o painel da rede."
            : "Sua conta não está vinculada a uma rede/Secretaria."}
        />
        {usuario?.is_global && (
          <div className="flex justify-center">
            <Botao onClick={() => navegar("/rede/gerenciar")}>
              <Settings2 size={15} /> Gerenciar redes
            </Botao>
          </div>
        )}
      </div>
    );
  }
  return <>{children(redeId)}</>;
}
