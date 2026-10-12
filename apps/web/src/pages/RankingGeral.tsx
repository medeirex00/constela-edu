/**
 * Aba "Desempenho" do Ranking (antes chamada "Geral") — a CLASSIFICAÇÃO
 * OFICIAL de uma matéria por vez, com um seletor de matéria (Leitura ·
 * Matemática) que só oferece os módulos contratados pela rede.
 *
 * POR QUE MUDOU (Decisão 1 do dono, 2026-10-12 — transição da `nota_geral`
 * para as notas por disciplina): esta aba mostrava a ORDEM ÚNICA da escola
 * (`GET /ranking` sem dimensão), ordenada pela nota geral, com a coluna
 * "Geral". Agora ela consulta SEMPRE `?dimensao=` (plano de retirada, item 1):
 * só quem é aferido na matéria, pela nota oficial dela (0–100), com o
 * denominador no cabeçalho e, logo abaixo, quem ainda não foi aferido — sem
 * 0,0 de ausência. A renderização é a de `components/DesempenhoDimensao`, a
 * MESMA do topo das abas Leitura e Matemática: uma regra, uma tela.
 *
 * A API continua servindo a ordem única (contrato do app em campo e do cartaz
 * geral); o web é que deixou de lê-la nesta aba.
 *
 * CARTAZ GERAL: o pôster da ordem única (`/ranking/cartaz` sem dimensão) segue
 * disponível para a gestão — o que o cartaz e a exportação PADRÃO passam a ser
 * é decisão própria do dono (plano, item 8), fora desta transição. O cartaz DA
 * MATÉRIA fica no cabeçalho da classificação.
 *
 * MATÉRIA na URL (`?materia=matematica`): o "ver classificação completa" do
 * painel abre direto na matéria certa, e o recarregar não perde a escolha.
 *
 * PERÍODO: a classificação é sempre a ACUMULADA do ano letivo. Com qualquer
 * outro período global escolhido, a tela avisa e oferece a aba Evolução (a
 * classificação por período). O seletor fica na tela porque o período é global
 * (segue o usuário para Leitura, Matemática, Evolução e Premiações).
 *
 * TURMA/SÉRIE e TURNO global: repassados à classificação — as duas consultas
 * dela (ranking e não aferidos) recebem o MESMO recorte. Com turno, a API
 * renumera as posições dentro do turno e carimba o denominador do recorte.
 */
import { Download, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DesempenhoDimensao } from "../components/DesempenhoDimensao";
import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo } from "../components/SeletorPeriodo";
import { SeletorTurno } from "../components/SeletorTurno";
import { Botao, Card, Mensagem, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { apiDownload } from "../lib/api";
import { turnoEfetivo } from "../lib/turnos";
import type { Dimensao, Turma } from "../lib/types";

/** As matérias, na ordem de apresentação (a mesma das abas do Ranking). */
const MATERIAS: { chave: Dimensao; rotulo: string }[] = [
  { chave: "leitura", rotulo: "Leitura" },
  { chave: "matematica", rotulo: "Matemática" },
];

export default function RankingGeral({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId, usuario, periodo, definirPeriodo, turno, definirTurno } = useApp();
  const { tem } = useModulos();
  const [params, setParams] = useSearchParams();
  const [alvo, setAlvo] = useState<AlvoRanking>({});
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");

  // O cartaz (pôster) é documento de vitrine — só gestão (admin/coordenador/rede).
  const gestor = Boolean(usuario?.is_global) || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  // Período ≠ ano letivo: a classificação por período é a aba Evolução.
  const porPeriodo = periodo.preset !== "ano_letivo";

  // Matéria que a rede não contratou NÃO aparece — nem como opção, nem como
  // lista vazia. Um `?materia=` de matéria fora do plano cai na primeira
  // contratada (em vez de consultar uma dimensão que a API recusaria com 403).
  const materias = MATERIAS.filter((m) => tem(m.chave));
  const materia = materias.find((m) => m.chave === params.get("materia")) ?? materias[0];

  // Cache curto: a lista de turmas do dropdown de filtro muda raramente e é
  // invalidada em Turmas.tsx ao criar/editar/excluir (limparCacheApi).
  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  // Turno persistido que não existe nesta escola conta como "todos" na
  // consulta (sem sobrescrever a escolha guardada).
  const turnoAtivo = turnoEfetivo(turno, turmas);

  // O cartaz geral é sempre da escola inteira; ao mudar período/filtro, um erro
  // antigo dele perde o contexto — limpa para não ficar pendurado na tela.
  useEffect(() => { setErroCartaz(""); }, [periodo, alvo, turnoAtivo]);

  // Escolha de matéria vai para a URL (deep-link do painel), sem empilhar
  // histórico e mantendo os demais parâmetros (`?ver=` da tela de Rankings).
  function escolherMateria(chave: string) {
    const prox = new URLSearchParams(params);
    prox.set("materia", chave);
    setParams(prox, { replace: true });
  }

  // Troca para a aba Evolução mantendo os demais parâmetros da URL (a tela
  // vive embutida em Rankings.tsx, que deriva a aba de `?ver=`).
  function irParaEvolucao() {
    const prox = new URLSearchParams(params);
    prox.set("ver", "evolucao");
    setParams(prox);
  }

  // Baixa o cartaz GERAL (ordem única, PDF de vitrine com TODOS os alunos).
  async function baixarCartaz() {
    if (!escolaId) return;
    setBaixandoCartaz(true);
    setErroCartaz("");
    try {
      await apiDownload(`/escolas/${escolaId}/ranking/cartaz`);
    } catch (excecao) {
      setErroCartaz(excecao instanceof Error ? excecao.message : "Não foi possível gerar o cartaz.");
    } finally {
      setBaixandoCartaz(false);
    }
  }

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Desempenho por matéria"
          descricao="Classificação oficial do ano letivo em cada matéria, só com os alunos que têm dado da plataforma. Filtre por turma, série ou turno."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        {/* Uma matéria só contratada: não há o que escolher. */}
        {materias.length > 1 && materia && (
          <select
            aria-label="Matéria"
            className={`${estiloInput} w-auto font-medium`}
            value={materia.chave}
            onChange={(e) => escolherMateria(e.target.value)}
          >
            {materias.map((m) => <option key={m.chave} value={m.chave}>{m.rotulo}</option>)}
          </select>
        )}
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
        {gestor && (
          <Botao
            variante="neutro"
            onClick={baixarCartaz}
            // O cartaz geral é sempre da escola inteira (ordem única do ano);
            // não depende dos filtros de matéria, turma, série ou turno.
            disabled={baixandoCartaz}
            title="Pôster em PDF do Ranking Geral (Leitura e Matemática numa ordem só) com todos os alunos da escola; não usa os filtros. O cartaz de cada matéria fica na classificação abaixo."
            className="ml-auto"
          >
            <Download size={15} /> {baixandoCartaz ? "Gerando cartaz…" : "Baixar cartaz geral"}
          </Botao>
        )}
      </Card>

      {erroCartaz && <div className="mb-4"><Mensagem tipo="erro">{erroCartaz}</Mensagem></div>}

      {/* Período ≠ ano letivo: a classificação continua a do ano; o aviso
          aponta para a aba que classifica por período. */}
      {porPeriodo && (
        <div
          role="status"
          className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100"
        >
          <span>
            A classificação por matéria é a acumulada do ano letivo.
            A classificação por período fica na aba Evolução.
          </span>
          <Botao variante="neutro" onClick={irParaEvolucao} className="ml-auto">
            <TrendingUp size={15} /> Ver a aba Evolução
          </Botao>
        </div>
      )}

      {materia ? (
        <DesempenhoDimensao dimensao={materia.chave} filtros={{ ...alvo, turno: turnoAtivo }} />
      ) : (
        <Card>
          <Vazio
            titulo="Nenhuma matéria contratada"
            descricao="A rede não tem Leitura nem Matemática no plano: não há classificação a mostrar." />
        </Card>
      )}
    </div>
  );
}
