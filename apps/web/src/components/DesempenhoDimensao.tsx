/**
 * Classificação OFICIAL de uma matéria (Arquitetura 2): a lista dos alunos
 * AFERIDOS naquela matéria (têm dado da plataforma dela), ordenados pela nota
 * oficial (0–100) do ano letivo, com o denominador no cabeçalho e, logo abaixo,
 * a lista de quem "ainda não foi aferido". Quem não tem dado NÃO entra com 0,0:
 * sai do ranking e aparece na lista de ação, que é onde a coordenação precisa
 * vê-lo.
 *
 * Extraído do Ranking Geral (que agora fica só com a ordem única) para as abas
 * Leitura e Matemática, onde vive como seção SECUNDÁRIA recolhível (`recolhivel`):
 * o bloco principal da aba é o ranking do período, com o pódio. Os filtros
 * (turma/série e o turno global) chegam por props — a tela dona é quem tem os
 * seletores; aqui só se consulta. Recolhida, a seção continua montada (as
 * consultas e a lista de não aferidos seguem valendo) e o resumo fica à vista.
 *
 * Endpoints: `/ranking?dimensao=...` e `/nao-aferidos`, ambos com os mesmos
 * filtros (turma_id | ano_escolar, turno). O denominador exibido é o
 * `n_aferidos` carimbado pela API no conjunto filtrado.
 *
 * CARTAZ da matéria (gestão): `/ranking/cartaz?dimensao=...` — pôster em PDF
 * com os alunos aferidos naquela matéria na ESCOLA INTEIRA. Como o cartaz não
 * usa turma, série nem turno, o botão fica desabilitado (com o motivo) quando
 * algum desses filtros está aplicado, para não parecer que baixa o recorte.
 */
import { BookOpen, Calculator, Download, UserX } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { apiDownload } from "../lib/api";
import { nota, numero } from "../lib/formato";
import { TURNO_TODOS, aplicarTurno } from "../lib/turnos";
import type { Dimensao, NaoAferidos, RankingItem } from "../lib/types";
import { CelulaAluno, PosicaoRanking, SecaoRanking, tabelaRanking as t } from "./RankingUi";
import { TabelaRolavel } from "./TabelaRolavel";
import { Avatar, Botao, Card, Carregando, Chip, Erro, IconePastel, Mensagem, Vazio } from "./ui";

const MATERIAS: Record<Dimensao, { rotulo: string; dados: string; rotuloDados: string; plataforma: string }> = {
  leitura: { rotulo: "Leitura", dados: "livros_unicos", rotuloDados: "Livros", plataforma: "Elefante Letrado" },
  matematica: { rotulo: "Matemática", dados: "atividades", rotuloDados: "Atividades", plataforma: "Matific" },
};

/** Filtros da classificação: turma OU série (nunca os dois) + turno global. */
export interface FiltrosDimensao {
  turma_id?: string;
  ano_escolar?: string;
  /** Turno global já resolvido pela tela ("todos" | "" | código). */
  turno: string;
}

export function DesempenhoDimensao({ dimensao, filtros, recolhivel = false, aviso }: {
  dimensao: Dimensao;
  filtros: FiltrosDimensao;
  /** Seção secundária recolhível (fechada ao abrir a aba). Padrão: bloco aberto. */
  recolhivel?: boolean;
  /** Aviso da tela dona sobre os filtros (ex.: turma fora do cadastro). */
  aviso?: ReactNode;
}) {
  const { escolaId } = useApp();
  // O cartaz (pôster) é documento de vitrine — só gestão (admin/coordenador/
  // Admin Global), a mesma regra do cartaz do Ranking Geral.
  const { gestor } = usePerfil();
  const materia = MATERIAS[dimensao];
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");

  // Mesmos filtros nas duas consultas: quem está no ranking e quem ainda não
  // foi aferido são as duas metades do MESMO recorte.
  const parametros = new URLSearchParams();
  if (filtros.turma_id) parametros.set("turma_id", filtros.turma_id);
  if (filtros.ano_escolar) parametros.set("ano_escolar", filtros.ano_escolar);
  aplicarTurno(parametros, filtros.turno);
  const parametrosRanking = new URLSearchParams(parametros);
  parametrosRanking.set("dimensao", dimensao);

  const { dados: itens, erro, carregando, recarregar } = useApi<RankingItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking?${parametrosRanking}` : null,
  );
  // Visão OPERACIONAL: quem ainda NÃO foi aferido na matéria. Não é ranking (não
  // tem nota nem posição de propósito) — é a contrapartida obrigatória do corte
  // "ausência não é zero": ao sair da lista, a criança não pode sumir da tela.
  const { dados: naoAferidos } = useApi<NaoAferidos>(
    escolaId ? `/escolas/${escolaId}/nao-aferidos?${parametros}` : null,
  );
  const semDado = naoAferidos?.dimensoes.find((d) => d.dimensao === dimensao);
  const lista = itens ?? [];

  // O cartaz é sempre da escola inteira: com turma, série ou turno aplicado ele
  // NÃO corresponde à lista da tela, então o botão desabilita e diz por quê.
  const comFiltro = Boolean(filtros.turma_id || filtros.ano_escolar)
    || filtros.turno !== TURNO_TODOS;
  const cartazIndisponivel = comFiltro
    ? "O cartaz é da escola inteira: tire os filtros de turma, série e turno para baixar."
    : lista.length === 0
      ? `Ainda não há alunos aferidos em ${materia.rotulo} para o cartaz.`
      : "";
  // Um erro antigo do cartaz perde o contexto quando o filtro muda.
  const chaveFiltros = `${filtros.turma_id ?? ""}|${filtros.ano_escolar ?? ""}|${filtros.turno}`;
  useEffect(() => { setErroCartaz(""); }, [chaveFiltros, dimensao]);

  async function baixarCartaz() {
    if (!escolaId) return;
    setBaixandoCartaz(true);
    setErroCartaz("");
    try {
      await apiDownload(`/escolas/${escolaId}/ranking/cartaz?dimensao=${dimensao}`);
    } catch (excecao) {
      setErroCartaz(excecao instanceof Error ? excecao.message : "Não foi possível gerar o cartaz.");
    } finally {
      setBaixandoCartaz(false);
    }
  }

  const titulo = <>Classificação oficial — {materia.rotulo}</>;
  const icone = dimensao === "leitura" ? BookOpen : Calculator;
  const tom = dimensao === "leitura" ? "violeta" : "teal";
  // O DENOMINADOR precisa estar visível: sem ele, um "3º" em Leitura e um "3º" em
  // Matemática parecem comparáveis, e não são. Vem da API (conjunto filtrado).
  const denominador = !carregando && !erro && lista.length > 0
    ? <>{numero(lista[0]?.n_aferidos ?? lista.length)} alunos aferidos em {materia.rotulo}</>
    : null;
  const subtitulo = (
    <>
      Nota oficial (0–100) do ano letivo, só de quem tem dado do {materia.plataforma}
      {denominador && <> · <span className="font-semibold text-zinc-700 dark:text-zinc-200">{denominador}</span></>}
    </>
  );
  const cartaz = gestor && (
    <Botao
      variante="secundario"
      tamanho="sm"
      onClick={baixarCartaz}
      disabled={baixandoCartaz || cartazIndisponivel !== ""}
      title={cartazIndisponivel
        || `Gera um pôster em PDF com os alunos aferidos em ${materia.rotulo} na escola inteira`}
    >
      <Download size={14} aria-hidden />
      {baixandoCartaz ? "Gerando cartaz…" : `Baixar cartaz de ${materia.rotulo}`}
    </Botao>
  );

  const corpo = (
    <>
      {aviso}
      {erroCartaz && <div className="mb-3"><Mensagem tipo="erro">{erroCartaz}</Mensagem></div>}
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        Só entram os alunos com dado da plataforma de {materia.rotulo}; quem ainda não tem dado
        aparece abaixo, sem nota e sem posição. Não usa o período escolhido: é o ano letivo inteiro.
      </p>

      {carregando ? (
        <Carregando />
      ) : erro ? (
        <Erro titulo="Não foi possível carregar a classificação oficial" descricao={erro.message} aoTentar={recarregar} />
      ) : lista.length === 0 ? (
        <Vazio
          icone={icone}
          titulo={`Nenhum aluno aferido em ${materia.rotulo} ainda`}
          descricao="Importe ou sincronize os dados da plataforma para gerar a classificação."
        />
      ) : (
        // Celular: a NOTA (o que ordena) fica presa à direita; o cabeçalho dela quebra
        // em duas linhas ("Nota de / Matemática") para a coluna presa não cobrir o aluno.
        <TabelaRolavel rotulo={`Classificação oficial — ${materia.rotulo}: tabela completa`} className="-mx-5">
          <table className={t.tabela}>
            <thead className={t.thead}>
              <tr>
                <th className={t.th}>#</th>
                <th className={t.th}>Aluno</th>
                <th className={t.th}>Turma</th>
                <th className={`${t.thNum} ${t.thPresa} ${t.thQuebraCelular}`}>Nota de {materia.rotulo}</th>
                <th className={t.thNum}>{materia.rotuloDados}</th>
                <th className={t.thNum}>Adoção</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((item) => (
                <tr key={item.aluno_id} className={t.tr}>
                  <td className={t.td}><PosicaoRanking posicao={item.posicao} /></td>
                  <td className={t.td}>
                    <CelulaAluno nome={item.nome} href={`/alunos/${item.aluno_id}`} chave={item.aluno_id} />
                  </td>
                  <td className={t.tdCurto}>{item.turma ? <Chip>{item.turma}</Chip> : "—"}</td>
                  <td className={`${t.tdForte} ${t.tdPresa}`}>{nota(item.nota ?? 0)}</td>
                  <td className={t.tdNum}>{numero(item.dados?.[materia.dados] ?? 0)}</td>
                  <td className={`${t.tdNum} text-zinc-500 dark:text-zinc-400`}>
                    {item.adocao == null ? "—" : `${Math.round(item.adocao)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TabelaRolavel>
      )}

      {/* NÃO é rodapé decorativo: é a lista de ação da coordenação. Quem nunca
          foi alcançado deixou de aparecer em último lugar com 0,0 (a leitura
          mais injusta que o sistema produzia) e passa a aparecer aqui, sem nota
          e sem posição — porque não há o que medir, não porque foi mal. */}
      {semDado && semDado.alunos.length > 0 && (
        <Card className="mt-5 overflow-hidden bg-zinc-50/70 shadow-none dark:bg-zinc-800/30">
          <div className="flex items-start gap-3 border-b border-zinc-200/80 px-4 py-3 dark:border-zinc-800">
            <IconePastel icone={UserX} tom="ambar" tamanho="sm" />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-zinc-900 dark:text-white">
                Ainda não aferidos em {materia.rotulo} ({numero(semDado.alunos.length)})
              </h3>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                Sem dado importado desta plataforma. Não entram no ranking nem na
                média — ausência não é nota zero.
              </p>
            </div>
          </div>
          <ul className="grid grid-cols-1 gap-x-4 divide-y divide-zinc-200/70 px-4 sm:grid-cols-2 sm:divide-y-0 dark:divide-zinc-800">
            {semDado.alunos.map((aluno) => (
              <li key={aluno.aluno_id} className="flex min-w-0 items-center gap-2.5 py-2 text-sm">
                <Avatar nome={aluno.nome} chave={aluno.aluno_id} tamanho="sm" />
                <Link to={`/alunos/${aluno.aluno_id}`}
                      className="min-w-0 flex-1 truncate font-medium text-zinc-800 hover:text-indigo-700 hover:underline dark:text-zinc-100 dark:hover:text-indigo-300" title={aluno.nome}>
                  {aluno.nome}
                </Link>
                {aluno.turma && <Chip className="shrink-0 bg-white dark:bg-zinc-900">{aluno.turma}</Chip>}
                <span aria-hidden className="w-5 shrink-0 text-right text-zinc-400">—</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );

  if (recolhivel) {
    return (
      <SecaoRanking titulo={titulo} subtitulo={subtitulo} icone={icone} tom={tom} acoes={cartaz || undefined}>
        {corpo}
      </SecaoRanking>
    );
  }

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-start gap-3 px-5 py-4">
        <IconePastel icone={icone} tom={tom} />
        <div className="min-w-0 flex-1 basis-56">
          <h2 className="text-[15px] font-semibold leading-snug text-zinc-900 dark:text-white">{titulo}</h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{subtitulo}</p>
        </div>
        {cartaz}
      </div>
      <div className="border-t border-zinc-100 px-5 pb-5 pt-4 dark:border-zinc-800">{corpo}</div>
    </section>
  );
}
