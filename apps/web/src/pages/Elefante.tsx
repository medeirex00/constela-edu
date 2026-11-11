/** Módulo Elefante Letrado (PRD §56): leitura, questões e níveis por aluno. */
import { BookOpen, Layers, Pencil, Search, SlidersHorizontal, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { AbasLigadas } from "../components/AbasLigadas";
import { BarraFiltroAlunos, useFiltroAlunos } from "../components/FiltroAlunosPlataforma";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  Botao,
  BotaoIcone,
  Campo,
  Card,
  Chip,
  Erro,
  Mensagem,
  Modal,
  PageHeader,
  Skeleton,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { dataHora, numero, tempoLeitura } from "../lib/formato";
import type { ElefanteAluno, Nivel } from "../lib/types";
import { AvisoSemNiveis, EditorNiveis, PontuacaoPorTurma } from "./configuracoes/dificuldade";

// Sub-abas do módulo: os alunos e a configuração de dificuldade (níveis +
// pontuação por turma) num só lugar — cadastrar os níveis vem ANTES de pontuar.
// As duas sub-abas de configuração são exclusivas do Admin Global: a escola usa
// o Constela e não administra a régua (no perfil institucional o motor nem lê
// esses valores). Para os demais perfis só "Alunos" existe.
const SUBABAS = [
  ["alunos", "Alunos"],
  ["niveis", "Níveis de dificuldade"],
  ["pontuacao", "Dificuldade por turma"],
] as const;
type SubAba = (typeof SUBABAS)[number][0];
const SUBABAS_ESCOLA = SUBABAS.filter(([chave]) => chave === "alunos");
const ICONE_SUBABA: Record<SubAba, LucideIcon> = {
  alunos: Users,
  niveis: Layers,
  pontuacao: SlidersHorizontal,
};

/** Vocabulário OFICIAL de níveis do Elefante — o mesmo que o servidor valida. */
const NIVEIS_OFICIAIS = new Set([
  "AA", "BB", "CC", "DD", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
  "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "Z+", "A+",
]);
const CONTAGEM_MAXIMA = 10000;
/** Maior número que o servidor grava (coluna INTEGER): acima disso, 422. */
const INTEIRO_MAXIMO = 2_147_483_647;
const MOTIVO_MINIMO = 5;
/** Células da tabela de alunos: mais justas abaixo de 1280 px (tablet e notebook com a
 *  gaveta), para os dois botões de ação de cada linha caberem sem rolagem lateral. */
const TH = classesTabela.th.replace("px-4", "px-3 xl:px-4");
const TD = classesTabela.td.replace("px-4", "px-3 xl:px-4");
const MSG_MOTIVO = `Informe o motivo do ajuste (pelo menos ${MOTIVO_MINIMO} caracteres) — ele fica no histórico de alterações.`;

/** O ajuste manual é a fonte do dado só ENQUANTO a escola não recebe o Elefante
 *  da plataforma. Assim que o dado oficial chega (integração, importação ou
 *  sincronização), a manutenção passa a ser do Admin Global — e desligar a
 *  integração depois não reabre a edição, porque o dado recebido continua
 *  valendo. A trava é do servidor; aqui o gestor só não é pego de surpresa. */
const NOTA_AJUSTE_MANUAL =
  "Este ajuste existe enquanto a escola não recebe o Elefante Letrado da plataforma. " +
  "Depois que o dado oficial chega, a correção passa a ser do Admin Global — desligar a " +
  "integração não reabre a edição.";

function niveisParaTexto(niveis: Record<string, number>): string {
  return Object.entries(niveis)
    .map(([codigo, quantidade]) => `${codigo}:${quantidade}`)
    .join(", ");
}

/** Interpreta "AA:2, D:1, pre_leitor:3". Cada pedaço precisa ser um nível oficial
 *  (AA…Z, Z+, A+) ou uma faixa cadastrada, com contagem inteira de 0 a 10.000.
 *  Qualquer pedaço inválido devolve ERRO — nunca uma distribuição parcial ou
 *  vazia que apagaria os livros do aluno. */
function textoParaNiveis(
  texto: string,
  faixas: string[],
): { niveis: Record<string, number> } | { erro: string } {
  const niveis: Record<string, number> = {};
  const invalidos: string[] = [];
  const pedacos = texto.split(/[,;\n]/).map((p) => p.trim()).filter(Boolean);
  for (const pedaco of pedacos) {
    const partes = /^([A-Za-z][A-Za-z0-9_]*\+?)\s*[:=]\s*(\d+)$/.exec(pedaco);
    if (!partes) {
      invalidos.push(pedaco);
      continue;
    }
    const [, bruto, quantidade] = partes;
    const letra = bruto.toUpperCase();
    const faixa = faixas.find((f) => f.toLowerCase() === bruto.toLowerCase());
    const chave = NIVEIS_OFICIAIS.has(letra) ? letra : faixa;
    const n = Number(quantidade);
    if (!chave || n > CONTAGEM_MAXIMA) {
      invalidos.push(pedaco);
      continue;
    }
    niveis[chave] = (niveis[chave] ?? 0) + n;
  }
  if (invalidos.length > 0) {
    return {
      erro:
        `Texto inválido: ${invalidos.map((p) => `“${p}”`).join(", ")}. Use níveis do Elefante ` +
        "(AA…Z, Z+, A+) ou faixas cadastradas, no formato AA:2, D:1.",
    };
  }
  return { niveis };
}

/** Livros de uma faixa a partir da distribuição: valor direto da faixa OU a
 *  soma dos códigos de letra que pertencem a ela. */
function contarFaixa(faixa: Nivel, distribuicao: Record<string, number>): number {
  if (faixa.codigo && distribuicao[faixa.codigo] != null) return distribuicao[faixa.codigo];
  return (faixa.codigos ?? []).reduce((soma, c) => soma + (distribuicao[c] ?? 0), 0);
}

export default function Elefante() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const subabas = usuario?.is_global ? SUBABAS : SUBABAS_ESCOLA;
  const idBase = useId();

  const {
    dados: linhas,
    erro: erroLinhas,
    carregando,
    recarregar: recarregarLinhas,
  } = useApi<ElefanteAluno[]>(escolaId ? `/escolas/${escolaId}/elefante` : null);
  const { dados: dadosDificuldade, erro: erroNiveis, recarregar: recarregarNiveis } =
    useApi<{ niveis: Nivel[] }>(
      escolaId ? `/escolas/${escolaId}/configuracoes/dificuldade` : null,
    );
  const niveis = dadosDificuldade?.niveis ?? [];
  const codigosFaixa = niveis.map((n) => n.codigo).filter((c): c is string => Boolean(c));

  const [aba, setAba] = useState<SubAba>("alunos");
  const [editando, setEditando] = useState<ElefanteAluno | null>(null);
  const [formulario, setFormulario] = useState({
    tempo_leitura_min: 0,
    questoes_tentativas: 0,
    questoes_acertos: 0,
    niveis_texto: "",
    motivo: "",
  });
  // Entrada por faixa (livros por nível de dificuldade)
  const [faixasDe, setFaixasDe] = useState<ElefanteAluno | null>(null);
  const [faixasForm, setFaixasForm] = useState<Record<string, number>>({});
  const [faixasMotivo, setFaixasMotivo] = useState("");
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  function abrirEdicao(linha: ElefanteAluno) {
    setEditando(linha);
    setFormulario({
      tempo_leitura_min: linha.tempo_leitura_min,
      questoes_tentativas: linha.questoes_tentativas,
      questoes_acertos: linha.questoes_acertos,
      niveis_texto: niveisParaTexto(linha.livros_por_nivel),
      motivo: "",
    });
    setErro("");
  }

  function abrirFaixas(linha: ElefanteAluno) {
    const inicial: Record<string, number> = {};
    for (const faixa of niveis) {
      if (faixa.codigo) inicial[faixa.codigo] = contarFaixa(faixa, linha.livros_por_nivel);
    }
    setFaixasForm(inicial);
    setFaixasMotivo("");
    setErro("");
    setFaixasDe(linha);
  }

  async function salvar() {
    if (!escolaId || !editando) return;
    // Validação ANTES de enviar: texto inválido nunca vira {} no servidor.
    const interpretado = textoParaNiveis(formulario.niveis_texto, codigosFaixa);
    if ("erro" in interpretado) {
      setErro(interpretado.erro);
      return;
    }
    if (
      Object.keys(interpretado.niveis).length === 0 &&
      Object.keys(editando.livros_por_nivel ?? {}).length > 0
    ) {
      setErro("Informe os livros por nível (ex.: AA:2, D:1) — deixar em branco apagaria a distribuição atual.");
      return;
    }
    for (const [rotulo, valor] of [
      ["O tempo de leitura", formulario.tempo_leitura_min],
      ["O número de questões", formulario.questoes_tentativas],
      ["O número de acertos", formulario.questoes_acertos],
    ] as const) {
      if (valor > INTEIRO_MAXIMO) {
        setErro(`${rotulo} é grande demais. Confira o valor digitado.`);
        return;
      }
    }
    if (formulario.motivo.trim().length < MOTIVO_MINIMO) {
      setErro(MSG_MOTIVO);
      return;
    }
    setSalvando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/elefante/${editando.aluno_id}`, {
        method: "PUT",
        body: JSON.stringify({
          tempo_leitura_min: formulario.tempo_leitura_min,
          questoes_tentativas: formulario.questoes_tentativas,
          questoes_acertos: formulario.questoes_acertos,
          livros_por_nivel: interpretado.niveis,
          motivo: formulario.motivo.trim(),
        }),
      });
      setEditando(null);
      recarregarLinhas();
    } catch (excecao) {
      // Inclui o 403 da governança (integração ativa): a mensagem do servidor aparece.
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  async function salvarFaixas() {
    if (!escolaId || !faixasDe) return;
    if (faixasMotivo.trim().length < MOTIVO_MINIMO) {
      setErro(MSG_MOTIVO);
      return;
    }
    setSalvando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/elefante/${faixasDe.aluno_id}/niveis`, {
        method: "PUT",
        body: JSON.stringify({ faixas: faixasForm, motivo: faixasMotivo.trim() }),
      });
      setFaixasDe(null);
      recarregarLinhas();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  const totalFaixas = Object.values(faixasForm).reduce((s, n) => s + (Number(n) || 0), 0);
  const filtro = useFiltroAlunos(linhas);

  const listaAlunos = (
    <>
      <Card className="overflow-hidden">
        {/* Spinner só na PRIMEIRA carga: ao recarregar depois de salvar, a tabela
            fica na tela (antes ela sumia e a rolagem pulava a cada ajuste). */}
        {carregando && !linhas ? (
          <div className="space-y-3 p-6" aria-busy="true">
            <p className="sr-only" role="status">Carregando...</p>
            <Skeleton className="h-10 w-64" />
            {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-11" />)}
          </div>
        ) : erroLinhas && !linhas ? (
          <Erro descricao={erroLinhas.message} aoTentar={recarregarLinhas} />
        ) : (linhas ?? []).length === 0 ? (
          <Vazio icone={BookOpen} titulo="Nenhum aluno ativo" descricao="Cadastre alunos ou importe um relatório do Elefante Letrado." />
        ) : (
          <>
            {erroLinhas && (
              <div className="px-6 pt-5">
                <Mensagem tipo="erro">Não foi possível atualizar a lista: {erroLinhas.message}</Mensagem>
              </div>
            )}
            <BarraFiltroAlunos
              plataforma="elefante"
              total={(linhas ?? []).length}
              visiveis={filtro.filtradas.length}
              busca={filtro.busca}
              aoBuscar={filtro.setBusca}
              turma={filtro.turma}
              aoMudarTurma={filtro.setTurma}
              turmas={filtro.turmas}
            />
            {filtro.filtradas.length === 0 ? (
              <Vazio
                icone={Search}
                titulo="Nenhum aluno com esses filtros"
                acao={<Botao variante="secundario" onClick={filtro.limpar}>Limpar filtros</Botao>}
              />
            ) : (
              // O aviso "Deslize a tabela..." aparece ACIMA da tabela quando há coluna
              // escondida (no celular: Tempo, Questões, Acertos e as ações vêm deslizando).
              <TabelaRolavel rotulo="Alunos do Elefante Letrado: tabela completa">
                <table className={classesTabela.tabela}>
                  <thead>
                    <tr>
                      <th className={TH}>Aluno</th>
                      <th className={`${TH} text-right`}>Livros</th>
                      <th className={`${TH} text-right`}>Tempo</th>
                      <th className={`${TH} text-right`}>Questões</th>
                      <th className={`${TH} text-right`}>Acertos</th>
                      <th className={`hidden lg:table-cell ${TH}`}>Atualizado em</th>
                      {podeEditar && <th className={TH}><span className="sr-only">Ações</span></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {filtro.filtradas.map((linha) => (
                      <tr key={linha.aluno_id} className={classesTabela.tr}>
                        <td className={TD}>
                          {/* A turma vai no chip sob o nome (era uma coluna que sumia abaixo de
                              768 px; uma vez só no DOM, como em Turmas e Usuários). No celular o
                              avatar decorativo sai: o nome fica com os 9rem e quebra em até duas
                              linhas, não mais uma palavra por linha. */}
                          <div className="flex min-w-[9rem] items-center gap-3 xl:min-w-[11rem]">
                            <Avatar nome={linha.nome} chave={linha.aluno_id} tamanho="sm" className="max-sm:hidden" />
                            <div className="min-w-0">
                              <Link to={`/alunos/${linha.aluno_id}`} className="font-semibold text-zinc-900 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-400">
                                {linha.nome}
                              </Link>
                              {linha.turma && <div className="mt-1"><Chip>{linha.turma}</Chip></div>}
                            </div>
                          </div>
                        </td>
                        <td className={`${TD} text-right text-[15px] font-bold tabular-nums text-zinc-900 dark:text-white`}>
                          {numero(linha.livros_unicos)}
                        </td>
                        <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>{tempoLeitura(linha.tempo_leitura_min)}</td>
                        <td className={`${TD} text-right tabular-nums`}>{numero(linha.questoes_tentativas)}</td>
                        <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>
                          {numero(linha.questoes_acertos)}
                          {linha.questoes_tentativas > 0 && (
                            <span className="ml-1 text-xs text-zinc-500 dark:text-zinc-400">
                              ({Math.round((linha.questoes_acertos / linha.questoes_tentativas) * 100)}%)
                            </span>
                          )}
                        </td>
                        <td className={`hidden lg:table-cell ${TD} whitespace-nowrap text-xs text-zinc-500 dark:text-zinc-400`}>
                          {dataHora(linha.data_referencia)}
                        </td>
                        {podeEditar && (
                          <td className="py-3.5 pl-1 pr-2 xl:px-4">
                            {/* No celular os dois botões têm 40 px e 8 px entre eles (alvo de toque). */}
                            <div className="flex justify-end gap-1 max-sm:gap-2 xl:gap-1.5">
                              <BotaoIcone
                                rotulo={`Informar livros por nível de ${linha.nome}`}
                                className="h-9 w-9 max-sm:h-10 max-sm:w-10"
                                onClick={() => abrirFaixas(linha)}
                              >
                                <Layers size={15} aria-hidden />
                              </BotaoIcone>
                              <BotaoIcone
                                rotulo={`Editar dados de ${linha.nome}`}
                                className="h-9 w-9 max-sm:h-10 max-sm:w-10"
                                onClick={() => abrirEdicao(linha)}
                              >
                                <Pencil size={15} aria-hidden />
                              </BotaoIcone>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TabelaRolavel>
            )}
          </>
        )}
      </Card>

      {/* --- Livros por nível de dificuldade (entrada amigável por faixa) --- */}
      <Modal
        titulo={`Livros por nível — ${faixasDe?.nome ?? ""}`}
        aberto={faixasDe !== null}
        aoFechar={() => setFaixasDe(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Informe quantos livros o aluno concluiu em cada nível. O total e os pontos de
            dificuldade são calculados automaticamente pela régua Constela.
          </p>
          <p className="rounded-xl bg-zinc-50 px-3 py-2.5 text-xs text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300">{NOTA_AJUSTE_MANUAL}</p>
          {erroNiveis ? (
            <Mensagem tipo="erro">{erroNiveis.message}</Mensagem>
          ) : niveis.length === 0 ? (
            <div className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
              <AvisoSemNiveis aoCriar={recarregarNiveis} />
              {usuario?.is_global && (
                <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
                  Ou cadastre manualmente na aba <strong>Níveis de dificuldade</strong>.
                </p>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {niveis.map((faixa) => (
                <Campo key={faixa.id} rotulo={faixa.nome}>
                  <input
                    type="number"
                    min={0}
                    max={CONTAGEM_MAXIMA}
                    className={estiloInput}
                    value={faixa.codigo ? faixasForm[faixa.codigo] ?? 0 : 0}
                    onChange={(e) =>
                      faixa.codigo &&
                      setFaixasForm({
                        ...faixasForm,
                        [faixa.codigo]: Math.min(CONTAGEM_MAXIMA, Math.max(0, Math.trunc(Number(e.target.value) || 0))),
                      })
                    }
                  />
                </Campo>
              ))}
            </div>
          )}
          <p className="flex items-center gap-2 rounded-xl bg-indigo-50 px-3 py-2.5 text-sm font-semibold text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-200">
            <BookOpen size={15} aria-hidden />
            Total: {numero(totalFaixas)} livro{totalFaixas === 1 ? "" : "s"}
          </p>
          <Campo rotulo="Motivo (obrigatório — fica no histórico de alterações)">
            <input
              className={estiloInput}
              placeholder="Ex.: dados informados pela professora"
              value={faixasMotivo}
              onChange={(e) => setFaixasMotivo(e.target.value)}
            />
          </Campo>
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <div className="flex justify-end gap-2.5 pt-1">
            <Botao variante="secundario" onClick={() => setFaixasDe(null)} disabled={salvando}>Cancelar</Botao>
            <Botao onClick={salvarFaixas} disabled={salvando || niveis.length === 0}>
              {salvando ? "Salvando..." : "Salvar e recalcular"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Edição de tempo, questões e níveis por código de letra --- */}
      <Modal titulo={`Editar Elefante Letrado — ${editando?.nome ?? ""}`} aberto={editando !== null} aoFechar={() => setEditando(null)}>
        <div className="space-y-4">
          <Campo rotulo="Livros por código de nível (ex.: AA:2, D:1) — os livros únicos são a soma">
            <input
              className={estiloInput} placeholder="AA:2, D:1"
              value={formulario.niveis_texto}
              onChange={(e) => setFormulario({ ...formulario, niveis_texto: e.target.value })}
            />
          </Campo>
          <Campo rotulo="Tempo de leitura (minutos)">
            <input
              type="number" min={0} max={INTEIRO_MAXIMO} className={estiloInput} value={formulario.tempo_leitura_min}
              onChange={(e) => setFormulario({ ...formulario, tempo_leitura_min: Number(e.target.value) })}
            />
          </Campo>
          <div className="grid grid-cols-2 gap-3">
            <Campo rotulo="Questões (tentativas)">
              <input
                type="number" min={0} max={INTEIRO_MAXIMO} className={estiloInput} value={formulario.questoes_tentativas}
                onChange={(e) => setFormulario({ ...formulario, questoes_tentativas: Number(e.target.value) })}
              />
            </Campo>
            <Campo rotulo="Acertos">
              <input
                type="number" min={0} max={INTEIRO_MAXIMO} className={estiloInput} value={formulario.questoes_acertos}
                onChange={(e) => setFormulario({ ...formulario, questoes_acertos: Number(e.target.value) })}
              />
            </Campo>
          </div>
          <Campo rotulo="Motivo da edição (obrigatório — fica no histórico de alterações)">
            <input
              className={estiloInput} placeholder="Ex.: correção de erro do relatório"
              value={formulario.motivo}
              onChange={(e) => setFormulario({ ...formulario, motivo: e.target.value })}
            />
          </Campo>
          <p className="rounded-xl bg-zinc-50 px-3 py-2.5 text-xs text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300">{NOTA_AJUSTE_MANUAL}</p>
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <div className="flex justify-end gap-2.5 pt-1">
            <Botao variante="secundario" onClick={() => setEditando(null)} disabled={salvando}>Cancelar</Botao>
            <Botao onClick={salvar} disabled={salvando}>{salvando ? "Salvando..." : "Salvar e recalcular"}</Botao>
          </div>
        </div>
      </Modal>
    </>
  );

  return (
    <div>
      <PageHeader
        titulo="Elefante Letrado"
        descricao="Livros por nível de dificuldade, tempo de leitura e questões por aluno. Releituras nunca pontuam novamente."
      />

      {/* Com uma única sub-aba (perfis de escola) a barra some — o conteúdo é a
          própria lista de alunos. */}
      {subabas.length > 1 ? (
        <>
          <AbasLigadas
            itens={subabas.map(([chave, rotulo]) => ({ valor: chave, rotulo, icone: ICONE_SUBABA[chave] }))}
            valor={aba}
            aoMudar={setAba}
            rotulo="Partes do Elefante Letrado"
            idDaAba={(chave) => `${idBase}-aba-${chave}`}
            idPainel={`${idBase}-painel`}
            className="mb-6"
          />
          <div role="tabpanel" id={`${idBase}-painel`} aria-labelledby={`${idBase}-aba-${aba}`}>
            {aba === "niveis" && usuario?.is_global && (
              <div className="max-w-3xl">
                <EditorNiveis aoMudar={recarregarNiveis} />
              </div>
            )}
            {aba === "pontuacao" && usuario?.is_global && <PontuacaoPorTurma />}
            {aba === "alunos" && listaAlunos}
          </div>
        </>
      ) : (
        listaAlunos
      )}
    </div>
  );
}
