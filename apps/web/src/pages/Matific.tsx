/** Módulo Matific (PRD §55): dados atuais por aluno com edição manual auditada. */
import { Calculator, Pencil, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

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
import { dataHora, nota, numero } from "../lib/formato";
import type { MatificAluno } from "../lib/types";

/** Células da tabela de alunos: no celular (< 640 px) um pouco mais justas, para o nome
 *  e as Atividades caberem ao lado da Média presa à direita. */
const TH = `${classesTabela.th} max-sm:px-3`;
const TD = `${classesTabela.td} max-sm:px-3`;

/** Escala da média do Matific (a mesma do Placar da Escola) — o servidor recusa
 *  acima disso (`MatificEdicao.pontuacao_media`, ge=0 le=5). */
const MEDIA_MAXIMA = 5;

/**
 * Modal de edição isolado: o estado do formulário vive AQUI, não no componente
 * da tabela. Assim, digitar re-renderiza só o modal — e não a tabela inteira
 * (não paginada) de alunos por baixo dele. Fica montado o tempo todo; quando
 * `linha` é null o Modal não aparece, e o efeito re-semeia os campos a cada
 * abertura.
 */
function ModalEditarMatific({
  linha,
  escolaId,
  aoFechar,
  aoSalvo,
}: {
  linha: MatificAluno | null;
  escolaId: number | null;
  aoFechar: () => void;
  aoSalvo: () => void;
}) {
  const [form, setForm] = useState({ atividades: 0, estrelas: 0, pontuacao_media: 0, motivo: "" });
  // Média COMO ESTAVA ao abrir: é o que distingue "não mexi nisso" de "digitei".
  const [mediaOriginal, setMediaOriginal] = useState(0);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (linha) {
      setForm({
        atividades: linha.atividades,
        estrelas: linha.estrelas,
        pontuacao_media: linha.pontuacao_media,
        motivo: "",
      });
      setMediaOriginal(linha.pontuacao_media);
      setErro("");
    }
  }, [linha]);

  const mediaMudou = form.pontuacao_media !== mediaOriginal;
  // Registro antigo fora da escala atual (edição gravada quando o limite era
  // 100, ou base de demonstração): reenviá-lo daria 422 e travaria a correção
  // de atividades/estrelas.
  const mediaForaDaEscala = mediaOriginal > MEDIA_MAXIMA;

  async function salvar() {
    if (!escolaId || !linha) return;
    // Barra no cliente, em português: o 422 do servidor chega em inglês e sem
    // dizer qual é a escala.
    if (mediaMudou && (form.pontuacao_media < 0 || form.pontuacao_media > MEDIA_MAXIMA)) {
      setErro(`A média do Matific vai de 0 a ${MEDIA_MAXIMA} (a mesma escala do Placar da Escola).`);
      return;
    }
    setSalvando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/matific/${linha.aluno_id}`, {
        method: "PUT",
        body: JSON.stringify({
          atividades: form.atividades,
          estrelas: form.estrelas,
          motivo: form.motivo || null,
          // A média só viaja quando foi EDITADA: ausente, o servidor preserva a
          // gravada. É o que mantém editável um registro fora da escala, sem
          // obrigar ninguém a inventar um número de 0 a 5 no lugar do medido.
          ...(mediaMudou ? { pontuacao_media: form.pontuacao_media } : {}),
        }),
      });
      aoSalvo();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Modal titulo={`Editar Matific — ${linha?.nome ?? ""}`} aberto={linha !== null} aoFechar={aoFechar}>
      <div className="space-y-4">
        <Campo rotulo="Atividades finalizadas">
          <input
            type="number" min={0} className={estiloInput} value={form.atividades}
            onChange={(e) => setForm({ ...form, atividades: Number(e.target.value) })}
          />
        </Campo>
        <Campo rotulo="Estrelas">
          <input
            type="number" min={0} className={estiloInput} value={form.estrelas}
            onChange={(e) => setForm({ ...form, estrelas: Number(e.target.value) })}
          />
        </Campo>
        <Campo rotulo="Pontuação média (0 a 5)">
          <input
            type="number" min={0} max={MEDIA_MAXIMA} step="0.1" className={estiloInput}
            value={form.pontuacao_media}
            onChange={(e) => setForm({ ...form, pontuacao_media: Number(e.target.value) })}
          />
          {mediaForaDaEscala && (
            <p className="mt-1.5 text-xs text-ouro-700 dark:text-ouro-300">
              Este registro tem média {nota(mediaOriginal)}, fora da escala atual (0 a {MEDIA_MAXIMA}).
              Deixe como está para preservar o valor medido, ou digite um número de 0 a {MEDIA_MAXIMA}
              {" "}para corrigi-lo.
            </p>
          )}
        </Campo>
        <Campo rotulo="Motivo da edição (fica no histórico de alterações)">
          <input
            className={estiloInput} placeholder="Ex.: correção de erro do relatório"
            value={form.motivo}
            onChange={(e) => setForm({ ...form, motivo: e.target.value })}
          />
        </Campo>
        {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
        <div className="flex justify-end gap-2.5 pt-1">
          <Botao variante="secundario" onClick={aoFechar} disabled={salvando}>Cancelar</Botao>
          <Botao onClick={salvar} disabled={salvando}>{salvando ? "Salvando..." : "Salvar e recalcular"}</Botao>
        </div>
      </div>
    </Modal>
  );
}

export default function Matific() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const {
    dados: linhas,
    erro: erroLinhas,
    carregando,
    recarregar,
  } = useApi<MatificAluno[]>(escolaId ? `/escolas/${escolaId}/matific` : null);
  const [editando, setEditando] = useState<MatificAluno | null>(null);
  const filtro = useFiltroAlunos(linhas);

  return (
    <div>
      <PageHeader
        titulo="Matific"
        descricao="Estado atual de cada aluno na plataforma. Edições manuais geram novo registro e ficam no histórico de alterações."
      />
      <Card className="overflow-hidden">
        {/* Spinner só na PRIMEIRA carga: ao recarregar depois de salvar, a tabela
            fica na tela (antes ela sumia e a rolagem pulava). */}
        {carregando && !linhas ? (
          <div className="space-y-3 p-6" aria-busy="true">
            <p className="sr-only" role="status">Carregando...</p>
            <Skeleton className="h-10 w-64" />
            {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-11" />)}
          </div>
        ) : erroLinhas && !linhas ? (
          <Erro descricao={erroLinhas.message} aoTentar={recarregar} />
        ) : (linhas ?? []).length === 0 ? (
          <Vazio icone={Calculator} titulo="Nenhum aluno ativo" descricao="Cadastre alunos ou importe um relatório da Matific." />
        ) : (
          <>
            {erroLinhas && (
              <div className="px-6 pt-5">
                <Mensagem tipo="erro">Não foi possível atualizar a lista: {erroLinhas.message}</Mensagem>
              </div>
            )}
            <BarraFiltroAlunos
              plataforma="matific"
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
              // escondida. No celular a Média (a nota) fica presa à direita (presa-celular)
              // e Estrelas e Editar vêm deslizando.
              <TabelaRolavel rotulo="Alunos do Matific: tabela completa">
                <table className={classesTabela.tabela}>
                  <thead>
                    <tr>
                      <th className={TH}>Aluno</th>
                      <th className={`${TH} text-right`}>Atividades</th>
                      <th className={`${TH} text-right`}>Estrelas</th>
                      <th className={`${TH} presa-celular text-right`}>Média</th>
                      <th className={`hidden lg:table-cell ${TH}`}>Atualizado em</th>
                      {podeEditar && <th className={`${classesTabela.th} max-sm:px-2`}><span className="sr-only">Ações</span></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {filtro.filtradas.map((linha) => (
                      <tr key={linha.aluno_id} className={classesTabela.tr}>
                        <td className={TD}>
                          {/* A turma vai no chip sob o nome (era uma coluna que sumia abaixo de
                              768 px; uma vez só no DOM, como em Turmas e Usuários). No celular o
                              avatar decorativo sai e o nome fica com até duas linhas. */}
                          <div className="flex min-w-[11rem] items-center gap-3 max-sm:min-w-[9rem]">
                            <Avatar nome={linha.nome} chave={linha.aluno_id} tamanho="sm" className="max-sm:hidden" />
                            <div className="min-w-0">
                              <Link to={`/alunos/${linha.aluno_id}`} className="font-semibold text-zinc-900 hover:text-teal-700 dark:text-zinc-100 dark:hover:text-teal-300">
                                {linha.nome}
                              </Link>
                              {linha.turma && <div className="mt-1"><Chip>{linha.turma}</Chip></div>}
                            </div>
                          </div>
                        </td>
                        <td className={`${TD} text-right text-[15px] font-bold tabular-nums text-zinc-900 dark:text-white`}>
                          {numero(linha.atividades)}
                        </td>
                        <td className={`${TD} text-right tabular-nums`}>{numero(linha.estrelas)}</td>
                        <td className={`${TD} presa-celular text-right tabular-nums`}>{nota(linha.pontuacao_media)}</td>
                        <td className={`hidden lg:table-cell ${TD} whitespace-nowrap text-xs text-zinc-500 dark:text-zinc-400`}>
                          {dataHora(linha.data_referencia)}
                        </td>
                        {podeEditar && (
                          <td className={`${classesTabela.td} text-right max-sm:px-2`}>
                            <BotaoIcone
                              rotulo={`Editar dados de ${linha.nome}`}
                              className="h-9 w-9 max-sm:h-10 max-sm:w-10"
                              onClick={() => setEditando(linha)}
                            >
                              <Pencil size={15} aria-hidden />
                            </BotaoIcone>
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

      <ModalEditarMatific
        linha={editando}
        escolaId={escolaId}
        aoFechar={() => setEditando(null)}
        aoSalvo={() => {
          setEditando(null);
          recarregar();
        }}
      />
    </div>
  );
}
