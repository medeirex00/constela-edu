/**
 * Ações de gestão de UM aluno, reutilizáveis em qualquer tela (lista de
 * Alunos, ficha do aluno): menu ⋮ com Visualizar, Editar dados (nome,
 * nº de chamada, nascimento, observações E turma), Arquivar/Reativar,
 * Marcar como transferido (saiu da escola — o histórico fica preservado),
 * Excluir (reversível) e Excluir permanentemente (dupla confirmação; só o
 * Admin Global — D19).
 * Usa os endpoints já existentes do painel da turma.
 */
import {
  Archive,
  Eye,
  LogOut,
  Merge,
  Pencil,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api, ApiError } from "../lib/api";
import type { Aluno, PaginaAlunos, Turma } from "../lib/types";
import LeiturasRepetidas, { type ResumoLeiturasRepetidas } from "./LeiturasRepetidas";
import MenuSuspenso, { ItemMenu } from "./MenuSuspenso";
import { AvatarAluno } from "./PessoasUi";
import { Botao, Campo, Mensagem, Modal, estiloInput } from "./ui";

type Janela = "editar" | "fundir" | "excluir" | "permanente" | null;

export default function AcoesAluno({ aluno, escolaId, aoMudar, aoExcluir, mostrarVisualizar = true }: {
  aluno: Aluno;
  escolaId: number;
  /** Chamado após qualquer alteração (para a tela recarregar os dados). Se a
   *  resposta trouxer avisos, só depois que o usuário fechar a janela deles. */
  aoMudar: () => void;
  /** Chamado após exclusão (ex.: sair da ficha do aluno) — mesma regra dos avisos. */
  aoExcluir?: () => void;
  mostrarVisualizar?: boolean;
}) {
  const navegar = useNavigate();
  const { usuario } = useApp();
  // Secretaria (rede vinculada, não-global): só visualiza — sem ações de escrita
  // (editar, transferir turma, fundir, arquivar, excluir). O backend também barra.
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  // Exclusão FÍSICA do aluno (apaga a ficha e todos os dados) é exclusiva do
  // Admin Global (D19 — a API responde 403 para os demais): para admin e
  // coordenação da escola o menu não oferece “Excluir permanentemente”.
  const podeApagarAlunos = usuario?.is_global === true;
  const [janela, setJanela] = useState<Janela>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  // Erro de Arquivar/Reativar: essas ações partem direto do menu, sem modal,
  // então precisam de um lugar PRÓPRIO para aparecer — senão a falha some.
  const [erroAcao, setErroAcao] = useState("");
  // Avisos da ação concluída (D10: o Admin Global tirou de "excluído" uma ficha
  // cuja conta da plataforma vale em outra escola) — nunca silenciosos.
  const [avisosAcao, setAvisosAcao] = useState<string[]>([]);
  // Com aviso, a tela só é avisada (aoMudar/aoExcluir) quando o usuário FECHA a
  // janela: quem recarrega pode desmontar este componente — o PerfilAluno troca
  // o conteúdo por <Carregando/> — e o aviso sumiria junto, sem ser lido.
  const concluirAoFecharAvisos = useRef<(() => void) | null>(null);
  const inativo = aluno.status !== "ativo";

  function fecharAvisos() {
    setAvisosAcao([]);
    const concluir = concluirAoFecharAvisos.current;
    concluirAoFecharAvisos.current = null;
    concluir?.();
  }

  async function acaoStatus(acao: "arquivar" | "reativar" | "excluir" | "marcar_transferido") {
    // Defensivo: uma ação nova com o aviso anterior ainda aberto (o menu atrás
    // da janela segue alcançável pelo teclado) conclui o anterior antes.
    if (concluirAoFecharAvisos.current) fecharAvisos();
    setOcupado(true);
    setErro("");
    setErroAcao("");
    try {
      const r = await api<{ avisos?: string[] }>(`/escolas/${escolaId}/alunos/acoes`, {
        method: "POST",
        body: JSON.stringify({ aluno_ids: [aluno.id], acao }),
      });
      setJanela(null);
      const concluir = () => {
        if (acao === "excluir") aoExcluir?.();
        aoMudar();
      };
      if (r?.avisos?.length) {
        concluirAoFecharAvisos.current = concluir;
        setAvisosAcao(r.avisos);
      } else {
        concluir();
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Não foi possível concluir a ação.";
      // "excluir" roda dentro do modal (que mostra `erro`); arquivar/reativar
      // não têm modal → vão para o aviso dedicado.
      if (acao === "excluir") setErro(msg);
      else setErroAcao(msg);
    } finally {
      setOcupado(false);
    }
  }

  async function excluirPermanente(confirmacao: string) {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/excluir-permanente`, {
        method: "POST",
        body: JSON.stringify({ aluno_ids: [aluno.id], confirmacao }),
      });
      setJanela(null);
      aoExcluir?.();
      aoMudar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível excluir.");
    } finally {
      setOcupado(false);
    }
  }

  // Secretaria sem sequer "Visualizar" não teria nenhuma ação → não mostra o menu.
  if (secretaria && !mostrarVisualizar) return null;

  return (
    <>
      <MenuSuspenso ariaLabel={`Ações de ${aluno.nome}`}>
        {(fechar) => {
          const escolher = (agir: () => void) => () => { fechar(); agir(); };
          return (
            <>
              {mostrarVisualizar && (
                <ItemMenu icone={<Eye size={15} />} rotulo="Visualizar"
                          onClick={escolher(() => navegar(`/alunos/${aluno.id}`))} />
              )}
              {!secretaria && (
                <>
                  <ItemMenu icone={<Pencil size={15} />} rotulo="Editar dados"
                            onClick={escolher(() => setJanela("editar"))} />
                  {/* Fundir só entre alunos ativos (o backend também recusa inativos). */}
                  {!inativo && (
                    <ItemMenu icone={<Merge size={15} />} rotulo="Fundir com outro aluno"
                              onClick={escolher(() => setJanela("fundir"))} />
                  )}
                  {inativo ? (
                    <ItemMenu icone={<RotateCcw size={15} />} rotulo="Reativar"
                              onClick={escolher(() => acaoStatus("reativar"))} />
                  ) : (
                    <>
                      <ItemMenu icone={<Archive size={15} />} rotulo="Arquivar"
                                onClick={escolher(() => acaoStatus("arquivar"))} />
                      {/* Saiu da escola: some das visões, o histórico fica, e a
                          reimportação da Lista Piloto não o traz de volta sozinha. */}
                      <ItemMenu icone={<LogOut size={15} />} rotulo="Marcar como transferido"
                                onClick={escolher(() => acaoStatus("marcar_transferido"))} />
                    </>
                  )}
                  <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
                  <ItemMenu icone={<Trash2 size={15} />} rotulo="Excluir" destrutiva
                            onClick={escolher(() => setJanela("excluir"))} />
                  {podeApagarAlunos && (
                    <ItemMenu icone={<TriangleAlert size={15} />} rotulo="Excluir permanentemente" destrutiva
                              onClick={escolher(() => setJanela("permanente"))} />
                  )}
                </>
              )}
            </>
          );
        }}
      </MenuSuspenso>

      {janela === "editar" && (
        <ModalEditarAluno
          aluno={aluno}
          escolaId={escolaId}
          aoFechar={() => setJanela(null)}
          aoSalvo={() => { setJanela(null); aoMudar(); }}
        />
      )}

      {janela === "fundir" && (
        <ModalFundir
          aluno={aluno}
          escolaId={escolaId}
          aoFechar={() => setJanela(null)}
          aoConcluir={(removeuAtual) => {
            setJanela(null);
            if (removeuAtual) aoExcluir?.();
            aoMudar();
          }}
        />
      )}

      {janela === "excluir" && (
        <Modal titulo="Excluir aluno" aberto aoFechar={() => setJanela(null)}>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Tem certeza de que deseja excluir <strong>{aluno.nome}</strong>? O aluno sai
            das listas e rankings; os dados são mantidos e podem ser restaurados depois.
            {podeApagarAlunos
              ? " Para apagar tudo de vez, use “Excluir permanentemente”."
              : " Apagar tudo de vez é exclusivo do Admin Global."}
          </p>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-6 flex justify-end gap-2.5">
            <Botao variante="secundario" onClick={() => setJanela(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao variante="perigo" disabled={ocupado}
                   onClick={() => acaoStatus("excluir")}>
              {ocupado ? "Excluindo..." : "Excluir"}
            </Botao>
          </div>
        </Modal>
      )}

      {janela === "permanente" && podeApagarAlunos && (
        <ModalPermanenteUm
          nome={aluno.nome}
          ocupado={ocupado}
          erro={erro}
          aoFechar={() => setJanela(null)}
          aoConfirmar={excluirPermanente}
        />
      )}

      {/* Falha de Arquivar/Reativar (ações diretas, sem modal próprio): nunca
          silenciosa — mostra o motivo e deixa tentar de novo. */}
      {erroAcao && (
        <Modal titulo="Não foi possível concluir a ação" aberto aoFechar={() => setErroAcao("")}>
          <Mensagem tipo="erro">{erroAcao}</Mensagem>
          <div className="mt-6 flex justify-end">
            <Botao variante="secundario" onClick={() => setErroAcao("")}>Fechar</Botao>
          </div>
        </Modal>
      )}

      {/* Ação concluída COM aviso (ex.: a conta da plataforma desta ficha continua
          valendo em outra escola): fica aberto até o usuário fechar, e só então
          a tela recarrega (fecharAvisos → aoMudar). */}
      {avisosAcao.length > 0 && (
        <Modal titulo="Ação concluída — atenção" aberto aoFechar={fecharAvisos}>
          <div className="space-y-2">
            {avisosAcao.map((a) => (
              <p key={a} className="flex gap-2.5 rounded-xl bg-amber-50 px-3.5 py-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
                <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
                <span>{a}</span>
              </p>
            ))}
          </div>
          <div className="mt-6 flex justify-end">
            <Botao variante="secundario" onClick={fecharAvisos}>Entendi</Botao>
          </div>
        </Modal>
      )}
    </>
  );
}

/** Edição COMPLETA do cadastro: nome, nº de chamada, nascimento, observações e
 *  TURMA (trocar a turma transfere a matrícula do ano ativo). */
export function ModalEditarAluno({ aluno, escolaId, aoFechar, aoSalvo }: {
  aluno: Aluno;
  escolaId: number;
  aoFechar: () => void;
  aoSalvo: () => void;
}) {
  const [nome, setNome] = useState(aluno.nome);
  const [chamada, setChamada] = useState(aluno.numero_chamada?.toString() ?? "");
  const [nascimento, setNascimento] = useState(aluno.data_nascimento ?? "");
  const [observacoes, setObservacoes] = useState(aluno.observacoes ?? "");
  const { dados: turmas, erro: erroTurmas } = useApi<Turma[]>(`/escolas/${escolaId}/turmas`);
  const [turmaId, setTurmaId] = useState<number | "">("");
  const [turmaOriginal, setTurmaOriginal] = useState<number | "">("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  // Quando as turmas chegam, pré-seleciona a turma atual do aluno.
  useEffect(() => {
    if (!turmas) return;
    const atual = turmas.find((t) => t.nome === aluno.turma)?.id ?? "";
    setTurmaId(atual);
    setTurmaOriginal(atual);
  }, [turmas, aluno.turma]);

  async function salvar() {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/${aluno.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          nome: nome.trim(),
          numero_chamada: chamada ? Number(chamada) : null,
          data_nascimento: nascimento || null,
          observacoes: observacoes.trim() || null,
        }),
      });
      // Turma mudou → transfere a matrícula do ano ativo.
      if (turmaId !== "" && turmaId !== turmaOriginal) {
        await api(`/escolas/${escolaId}/alunos/acoes`, {
          method: "POST",
          body: JSON.stringify({ aluno_ids: [aluno.id], acao: "transferir", turma_id: turmaId }),
        });
      }
      aoSalvo();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível salvar.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo="Editar aluno" aberto aoFechar={aoFechar}>
      <div className="space-y-4">
        <Campo rotulo="Nome">
          <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} />
        </Campo>
        <div className="grid grid-cols-2 gap-3">
          <Campo rotulo="Nº de chamada">
            <input className={estiloInput} inputMode="numeric" value={chamada}
                   onChange={(e) => setChamada(e.target.value.replace(/\D/g, ""))} />
          </Campo>
          <Campo rotulo="Data de nascimento">
            <input type="date" className={estiloInput} value={nascimento}
                   onChange={(e) => setNascimento(e.target.value)} />
          </Campo>
        </div>
        <Campo rotulo="Turma">
          <select className={estiloInput} value={turmaId}
                  onChange={(e) => setTurmaId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">— sem turma —</option>
            {(turmas ?? []).map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
          </select>
        </Campo>
        {/* Não engole o erro: avisa se as turmas não puderam ser carregadas. */}
        {erroTurmas && (
          <Mensagem tipo="erro">Não foi possível carregar as turmas: {erroTurmas.message}</Mensagem>
        )}
        <Campo rotulo="Observações">
          <textarea className={`${estiloInput} min-h-[70px]`} value={observacoes}
                    onChange={(e) => setObservacoes(e.target.value)} />
        </Campo>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || nome.trim().length < 2} onClick={salvar}>
          {ocupado ? "Salvando..." : "Salvar"}
        </Botao>
      </div>
    </Modal>
  );
}

/** Confirmação extra quando o motor de identidade prova conflito (o backend
 *  responde 409 e exige exatamente esta frase). */
const CONFIRMA_CONFLITO = "FUNDIR MESMO COM CONFLITO";

/** Prévia só leitura da fusão (`GET /alunos/fundir/previa`), NESTA direção. */
interface PreviaFusao {
  manter: { id: number; nome: string };
  remover: { id: number; nome: string };
  /** Qual ficha deveria ficar: a mesma regra da fusão em lote. */
  sugestao?: { manter_id: number; remover_id: number; motivo: string };
  /** Esta direção deixa um nome abreviado na ficha que fica? */
  nome?: { mantem_abreviado: boolean; fica: string; sai: string };
  leituras: ResumoLeiturasRepetidas;
  /** O que acontece com o Constela Quest: fica o progresso e o cartão que a
   *  criança usa; as duas fichas com progresso, o servidor recusa (``conflito``). */
  quest?: { tem_quest: boolean; conflito: boolean; texto: string | null };
  /** Por que o servidor vai recusar esta fusão (o MESMO texto do 409): contas
   *  diferentes da mesma plataforma, ou as duas fichas com progresso no Quest. */
  recusa?: string | null;
}

const MOTIVO_PRINCIPAL: Record<string, string> = {
  lista_piloto: "é a ficha da Lista Piloto, o cadastro oficial",
  nome_mais_completo: "tem o nome mais completo",
  cadastro_mais_antigo: "é o cadastro mais antigo",
};

/** Funde dois cadastros do MESMO aluno (duplicados). Busca o outro cadastro,
 *  SUGERE qual fica como principal (a mesma regra da fusão em lote: Lista
 *  Piloto, depois o nome mais completo, depois o mais antigo), avisa quando a
 *  escolha deixa um nome abreviado e combina Matific + Elefante + leituras num
 *  só. A sugestão não trava: "trocar" continua valendo. Irreversível →
 *  confirmação "FUNDIR". */
export function ModalFundir({ aluno, escolaId, aoFechar, aoConcluir }: {
  aluno: Aluno;
  escolaId: number;
  aoFechar: () => void;
  /** removeuAtual = true quando o aluno aberto foi o absorvido (sai da tela). */
  aoConcluir: (removeuAtual: boolean) => void;
}) {
  const [busca, setBusca] = useState("");
  const [buscaAtrasada, setBuscaAtrasada] = useState("");
  const [outro, setOutro] = useState<Aluno | null>(null);
  const [manterAtual, setManterAtual] = useState(true); // qual fica como principal
  const [confirmacao, setConfirmacao] = useState("");
  // O backend só revela a divergência de identidade quando a fusão é tentada
  // (409): a tela não tem nascimento nem RA para conferir sozinha. Quando isso
  // acontece, a mensagem NOMEIA o conflito e pedimos uma 2ª confirmação.
  const [conflito, setConflito] = useState(false);
  const [confirmaConflito, setConfirmaConflito] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  // Atrasa (debounce) a busca para não consultar a API a cada tecla.
  useEffect(() => {
    const t = window.setTimeout(() => setBuscaAtrasada(busca.trim()), 250);
    return () => window.clearTimeout(t);
  }, [busca]);

  // Só busca com termo válido e enquanto nenhum cadastro foi escolhido.
  const buscaAtiva = !outro && buscaAtrasada.length >= 2;
  const { dados: pagina, erro: erroBusca, carregando: carregandoBusca } = useApi<PaginaAlunos>(
    buscaAtiva
      ? `/escolas/${escolaId}/alunos?busca=${encodeURIComponent(buscaAtrasada)}&por_pagina=8`
      : null,
  );
  const resultados = buscaAtiva ? (pagina?.itens ?? []).filter((a) => a.id !== aluno.id) : [];

  const principal = manterAtual ? aluno : outro;
  const absorvido = manterAtual ? outro : aluno;
  // O que a fusão faz com os livros que estão nas duas fichas, NESTA direção
  // (fica a data da principal). Trocar a principal refaz a consulta.
  const previa = useApi<PreviaFusao>(
    principal && absorvido
      ? `/escolas/${escolaId}/alunos/fundir/previa?manter_id=${principal.id}&remover_id=${absorvido.id}`
      : null,
  );
  // A resposta só vale para a direção que está na tela (a anterior pode chegar depois).
  const previaAtual = previa.dados && principal && previa.dados.manter.id === principal.id
    && previa.dados.remover.id === absorvido?.id ? previa.dados : null;
  // Enquanto confere, não deixa fundir; se a conferência falhar, avisa e não bloqueia.
  const conferindo = Boolean(outro) && !previaAtual && !previa.erro;
  // A ficha aberta não é, por si, a melhor para ficar: na 1ª resposta para cada
  // cadastro escolhido, a tela adota a sugestão do backend. Depois disso quem
  // manda é o "trocar" (a consulta da outra direção não reaplica nada).
  const sugestaoAplicada = useRef<number | null>(null);
  useEffect(() => {
    if (!outro || !previaAtual?.sugestao || sugestaoAplicada.current === outro.id) return;
    sugestaoAplicada.current = outro.id;
    setManterAtual(previaAtual.sugestao.manter_id === aluno.id);
  }, [outro, previaAtual, aluno.id]);
  const sugerido = previaAtual?.sugestao
    ? (previaAtual.sugestao.manter_id === aluno.id ? aluno : outro) : null;
  const contraSugestao = Boolean(sugerido && principal && sugerido.id !== principal.id);
  // Fusão que o servidor recusa (409: contas diferentes da mesma plataforma, ou
  // as duas fichas com progresso no Constela Quest): a tela avisa antes e não
  // libera o botão.
  const recusa = previaAtual?.recusa ?? null;
  const liberado = outro && !conferindo && !recusa
    && confirmacao.trim().toUpperCase() === "FUNDIR"
    && (!conflito || confirmaConflito.trim().toUpperCase() === CONFIRMA_CONFLITO);

  async function fundir() {
    if (!principal || !absorvido) return;
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/fundir`, {
        method: "POST",
        body: JSON.stringify({
          manter_id: principal.id, remover_id: absorvido.id,
          confirmacao: confirmacao.trim(),
          confirmar_conflito: confirmaConflito.trim(),
        }),
      });
      aoConcluir(absorvido.id === aluno.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflito(true);
      setErro(e instanceof ApiError ? e.message : "Não foi possível fundir.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo="Fundir aluno duplicado" aberto aoFechar={aoFechar}>
      <p className="text-sm text-zinc-600 dark:text-zinc-300">
        Encontre o outro cadastro da <strong>mesma pessoa</strong>. Os dados dos
        dois (Matific, Elefante Letrado, leituras e matrículas) serão combinados
        em <strong>um só</strong>, e o cadastro absorvido será removido.
      </p>

      {!outro ? (
        <div className="mt-3">
          <div className="relative">
            <Search size={15} aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              aria-label="Buscar o cadastro duplicado pelo nome"
              className={`${estiloInput} pl-10`}
              placeholder="Buscar o cadastro duplicado pelo nome..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              autoFocus
            />
          </div>
          {resultados.length > 0 && (
            <ul className="mt-2 max-h-56 divide-y divide-zinc-100 overflow-y-auto rounded-2xl border border-zinc-200/80 dark:divide-zinc-800 dark:border-zinc-700">
              {resultados.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-sm transition-colors hover:bg-indigo-50/60 dark:hover:bg-zinc-800"
                    onClick={() => setOutro(a)}
                  >
                    <AvatarAluno nome={a.nome} chave={a.id} foto={a.foto_url} tamanho="sm" />
                    <span className="min-w-0 flex-1 truncate font-semibold" title={a.nome}>{a.nome}</span>
                    <span className="shrink-0 text-xs text-zinc-500 dark:text-zinc-400">{a.turma ?? "sem turma"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {/* Não engole o erro: mostra a falha da busca em vez de "nada encontrado". */}
          {erroBusca && (
            <div className="mt-2"><Mensagem tipo="erro">Não foi possível buscar: {erroBusca.message}</Mensagem></div>
          )}
          {buscaAtiva && !carregandoBusca && !erroBusca && resultados.length === 0 && (
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">Nenhum outro aluno encontrado.</p>
          )}
        </div>
      ) : (
        <>
          <div className="mt-3 space-y-2 rounded-2xl border border-zinc-200/80 bg-zinc-50/60 p-4 dark:border-zinc-700 dark:bg-zinc-800/40">
            <div className="flex items-center justify-between gap-2 text-sm">
              <span>
                <span className="text-zinc-500 dark:text-zinc-400">Fica como principal: </span>
                <strong>{principal?.nome}</strong>
                {principal?.turma && <span className="text-zinc-500 dark:text-zinc-400"> · {principal.turma}</span>}
              </span>
              <button type="button" className="text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-300"
                      onClick={() => setManterAtual((v) => !v)}>
                trocar
              </button>
            </div>
            <div className="text-sm">
              <span className="text-zinc-500 dark:text-zinc-400">Será absorvido e removido: </span>
              <strong>{absorvido?.nome}</strong>
              {absorvido?.turma && <span className="text-zinc-500 dark:text-zinc-400"> · {absorvido.turma}</span>}
            </div>
            <button type="button" className="text-xs font-medium text-zinc-600 hover:underline dark:text-zinc-300"
                    onClick={() => {
                      setOutro(null); setConfirmacao(""); setManterAtual(true);
                      setConflito(false); setConfirmaConflito(""); setErro("");
                      sugestaoAplicada.current = null;
                    }}>
              ← escolher outro cadastro
            </button>
          </div>
          <div className="mt-3 space-y-2" aria-live="polite">
            {sugerido && previaAtual?.sugestao && (
              contraSugestao ? (
                <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
                  O sistema sugere manter <strong>{sugerido.nome}</strong>:{" "}
                  {MOTIVO_PRINCIPAL[previaAtual.sugestao.motivo] ?? "é o melhor cadastro"}.
                  Você escolheu o contrário — confira antes de fundir.
                </p>
              ) : (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Sugestão do sistema: manter este cadastro, porque ele{" "}
                  {MOTIVO_PRINCIPAL[previaAtual.sugestao.motivo] ?? "é o melhor cadastro"}.
                </p>
              )
            )}
            {previaAtual?.nome?.mantem_abreviado && (
              <div role="note" aria-label="Atenção: nome abreviado"
                   className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100">
                <p className="font-semibold">
                  Atenção: o nome que fica é “{previaAtual.nome.fica}”, abreviado ou incompleto.
                </p>
                <p className="mt-1 text-xs">
                  A fusão não muda nomes: é este nome que vai sair no certificado e nos
                  relatórios, e “{previaAtual.nome.sai}” será apagado. Se não for isso, clique
                  em “trocar” — ou, se mantiver, corrija o nome depois em Editar dados.
                </p>
              </div>
            )}
            {conferindo && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">Conferindo as leituras das duas fichas…</p>
            )}
            {previa.erro && (
              <Mensagem tipo="erro">
                Não foi possível conferir as leituras repetidas antes da fusão ({previa.erro.message}).
                A fusão continua possível; se o aluno tem livros nas duas fichas, fica a data da principal.
              </Mensagem>
            )}
            {recusa ? (
              <div role="note" aria-label="Atenção: esta fusão não é feita"
                   className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100">
                {recusa}
              </div>
            ) : previaAtual?.quest?.texto && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">{previaAtual.quest.texto}</p>
            )}
            {previaAtual && principal && absorvido && (
              <LeiturasRepetidas
                resumo={previaAtual.leituras}
                nomeFica={principal.nome}
                nomeSai={absorvido.nome}
                dica="Se a data certa é a da outra ficha, clique em “trocar” para que ela fique como principal."
              />
            )}
          </div>
          <div className="mt-3">
            <Campo rotulo="Digite FUNDIR para confirmar">
              <input className={estiloInput} value={confirmacao} autoComplete="off"
                     placeholder="FUNDIR"
                     onChange={(e) => setConfirmacao(e.target.value)} />
            </Campo>
          </div>
          {conflito && (
            <div className="mt-3">
              <Campo rotulo={`Há sinal de serem crianças diferentes — digite ${CONFIRMA_CONFLITO}`}>
                <input className={estiloInput} value={confirmaConflito} autoComplete="off"
                       placeholder={CONFIRMA_CONFLITO}
                       onChange={(e) => setConfirmaConflito(e.target.value)} />
              </Campo>
            </div>
          )}
        </>
      )}

      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || !liberado} onClick={fundir}>
          <Merge size={15} aria-hidden /> {ocupado ? "Fundindo..." : "Fundir cadastros"}
        </Botao>
      </div>
    </Modal>
  );
}

function ModalPermanenteUm({ nome, ocupado, erro, aoFechar, aoConfirmar }: {
  nome: string;
  ocupado: boolean;
  erro: string;
  aoFechar: () => void;
  aoConfirmar: (confirmacao: string) => void;
}) {
  const [texto, setTexto] = useState("");
  const liberado = texto.trim().toUpperCase() === "EXCLUIR";
  return (
    <Modal titulo="Excluir permanentemente" aberto aoFechar={aoFechar}>
      <div className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
        <TriangleAlert size={18} aria-hidden className="mt-0.5 shrink-0" />
        <div>
          <p className="font-semibold">Esta ação é irreversível.</p>
          <p className="mt-1">
            <strong>{nome}</strong> será removido por completo: cadastro, histórico,
            leituras, dados do Matific e do Elefante Letrado, rankings, XP e conquistas.
          </p>
          {/* A conta na plataforma continua existindo: o Constela passa a ignorá-la
              nas coletas (marca de esquecimento), mas só a plataforma a encerra — e
              uma linha sem a conta (só o nome) não tem como ser reconhecida. */}
          <p className="mt-2">
            Se a criança ainda tiver conta no Matific ou no Elefante Letrado, peça o
            encerramento dela na plataforma. Até lá, o Constela ignora nas próximas coletas
            as contas ligadas a este cadastro. Um relatório ou planilha que traga só o nome,
            sem a conta da plataforma, pode cadastrar a criança de novo.
          </p>
        </div>
      </div>
      <div className="mt-4">
        <Campo rotulo="Digite EXCLUIR para confirmar">
          <input className={estiloInput} value={texto} onChange={(e) => setTexto(e.target.value)}
                 placeholder="EXCLUIR" autoComplete="off" />
        </Campo>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao variante="perigo" disabled={ocupado || !liberado}
               onClick={() => aoConfirmar(texto.trim())}>
          <TriangleAlert size={15} aria-hidden /> {ocupado ? "Excluindo..." : "Excluir para sempre"}
        </Botao>
      </div>
    </Modal>
  );
}
