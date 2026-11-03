/**
 * Competição escolar OFICIAL de leitura, dividida por TURNO (`Turma.turno`).
 *
 * Dentro de cada turno competem TODOS os alunos do 1º ao 5º ano juntos, pela
 * MESMA `nota_elefante` (régua única da escola). Os turnos e seus rótulos vêm do
 * backend (`/ranking/leitura/turnos`) — nada de "Manhã"/"Tarde" hardcoded aqui.
 * A série aparece só como informação ao lado do aluno, nunca na pontuação.
 *
 * NÃO confundir com o "Ranking de Leitura" por período (pontos brutos), que é
 * outra tela: este é a competição 0–100 oficial.
 *
 * Identidade visual v2: abas segmentadas por turno (pílula violeta; setas ←/→
 * trocam de aba), posição em pílula de medalha, aluno com avatar e turma em chip.
 * Só o turno ativo entra no DOM.
 */
import { Trophy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota as fmtNota, numero } from "../lib/formato";
import { TURNO_TODOS, chaveTurno as chave } from "../lib/turnos";
import type { RankingTurno } from "../lib/types";
import { ABAS_CELULAR, CelulaAluno, PosicaoRanking, tabelaRanking as t } from "./RankingUi";
import { TabelaRolavel } from "./TabelaRolavel";
import { Carregando, Chip, Erro, IconePastel, Vazio } from "./ui";

export function CompeticaoLeituraTurno() {
  const { escolaId, turno: turnoGlobal } = useApp();
  const { dados, erro, carregando, recarregar } = useApi<RankingTurno[]>(
    escolaId ? `/escolas/${escolaId}/ranking/leitura/turnos` : null,
  );
  // Turno selecionado AQUI (aba). `null` = o usuário ainda NÃO escolheu → mostra
  // o turno GLOBAL, se ele for um dos grupos; senão o primeiro grupo. NÃO dá
  // para usar o próprio valor do turno como "não escolhido", porque `turno`
  // pode ser `null` de verdade (turma sem turno) — usar `null` como sentinela
  // selecionaria o grupo "Sem turno" por engano.
  const [sel, setSel] = useState<{ turno: string | null } | null>(null);
  // Trocar o turno global (seletor da tela) volta a aba para ele.
  useEffect(() => { setSel(null); }, [turnoGlobal]);
  const abas = useRef<(HTMLButtonElement | null)[]>([]);

  if (carregando) return <Carregando />;
  if (erro) return <Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} />;

  const grupos = dados ?? [];
  if (grupos.length === 0) {
    return (
      <Vazio
        icone={Trophy}
        titulo="Competição de leitura ainda vazia"
        descricao="Assim que os alunos tiverem leituras aferidas no Elefante Letrado, o ranking por turno aparece aqui."
      />
    );
  }

  const doGlobal = turnoGlobal !== TURNO_TODOS
    ? grupos.find((g) => chave(g.turno) === turnoGlobal) : undefined;
  const atual =
    (sel && grupos.find((g) => chave(g.turno) === chave(sel.turno))) ?? doGlobal ?? grupos[0];
  const indiceAtual = grupos.indexOf(atual);

  // Setas ←/→, Home e End trocam de turno (foco itinerante, como as outras abas).
  const aoTecla = (evento: ReactKeyboardEvent<HTMLButtonElement>) => {
    let alvo = -1;
    if (evento.key === "ArrowRight") alvo = (indiceAtual + 1) % grupos.length;
    else if (evento.key === "ArrowLeft") alvo = (indiceAtual - 1 + grupos.length) % grupos.length;
    else if (evento.key === "Home") alvo = 0;
    else if (evento.key === "End") alvo = grupos.length - 1;
    if (alvo < 0) return;
    evento.preventDefault();
    setSel({ turno: grupos[alvo].turno });
    abas.current[alvo]?.focus();
  };

  return (
    <div>
      {grupos.length > 1 && (
        <div
          role="tablist"
          // Nome próprio: "Turno" é o rótulo do seletor GLOBAL na mesma tela.
          aria-label="Turno da competição"
          // Celular: duas colunas iguais em vez de pílulas soltas de larguras diferentes.
          className={`mb-4 inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-zinc-200/80 bg-white p-1 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900 ${ABAS_CELULAR.grade}`}
        >
          {grupos.map((g, i) => {
            const ativa = chave(atual.turno) === chave(g.turno);
            return (
              <button
                key={chave(g.turno) || "_sem"}
                ref={(el) => {
                  abas.current[i] = el;
                }}
                type="button"
                role="tab"
                aria-selected={ativa}
                tabIndex={ativa ? 0 : -1}
                onClick={() => setSel({ turno: g.turno })}
                onKeyDown={aoTecla}
                className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors max-sm:min-h-10 max-sm:justify-center ${
                  ativa
                    ? "bg-indigo-600 text-white shadow-pilula"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
                }`}
              >
                {g.turno_rotulo}
                <span className={`text-xs font-medium ${ativa ? "text-white" : "text-zinc-500 dark:text-zinc-400"}`}>
                  ({g.total})
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Celular: a caixa vai de borda a borda do cartão (sem a moldura arredondada e
          sem o respiro da seção), para a coluna presa da nota não cobrir o aluno. */}
      <div className="overflow-hidden rounded-2xl border border-zinc-200/80 max-sm:-mx-5 max-sm:rounded-none max-sm:border-x-0 dark:border-zinc-800">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3">
          <IconePastel icone={Trophy} tom="ambar" tamanho="sm" />
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-white">
            Ranking de Leitura — {atual.turno_rotulo}
          </h3>
          <span className="ml-auto text-xs text-zinc-500 dark:text-zinc-400">
            {numero(atual.total)} aluno(s) · 1º ao 5º ano juntos
          </span>
        </div>

        {atual.alunos.length === 0 ? (
          <Vazio icone={Trophy} titulo="Sem alunos aferidos neste turno" />
        ) : (
          <TabelaRolavel rotulo={`Ranking de Leitura — ${atual.turno_rotulo}: tabela completa`}>
            <table className={t.tabela}>
              <thead className={t.thead}>
                <tr>
                  <th scope="col" className={t.th}>#</th>
                  <th scope="col" className={t.th}>Aluno</th>
                  <th scope="col" className={t.th}>Série</th>
                  <th scope="col" className={t.th}>Turma</th>
                  <th scope="col" className={`${t.thNum} ${t.thPresa} ${t.thQuebraCelular}`}>Nota de Leitura</th>
                </tr>
              </thead>
              <tbody>
                {atual.alunos.map((item) => (
                  <tr key={item.aluno_id} className={t.tr}>
                    <td className={t.td}><PosicaoRanking posicao={item.posicao} /></td>
                    <td className={t.td}>
                      <CelulaAluno nome={item.nome} href={`/alunos/${item.aluno_id}`} chave={item.aluno_id} />
                    </td>
                    <td className={`${t.td} text-zinc-500 dark:text-zinc-400`}>{item.ano_escolar ?? "—"}</td>
                    <td className={t.tdCurto}>{item.turma ? <Chip>{item.turma}</Chip> : "—"}</td>
                    <td className={`${t.tdForte} ${t.tdPresa}`}>
                      {/* A rota exige o módulo Leitura, então a nota nunca vem
                          nula aqui (nula = módulo fora do plano da rede). */}
                      {fmtNota(item.nota_elefante ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </div>
    </div>
  );
}
