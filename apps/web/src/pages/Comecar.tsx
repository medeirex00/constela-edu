/**
 * Assistente de primeiros passos ("Comece aqui").
 *
 * Um fluxo ÚNICO que leva a escola do zero ao sistema funcionando em poucos
 * minutos: confirma a escola → importa turmas e alunos (Lista Piloto) →
 * conecta Matific/Elefante → conclui. Reaproveita os componentes já existentes
 * (ImportacaoMatriculas, CredenciaisForm) — o assistente só orquestra os passos
 * e sabe retomar de onde a escola parou (pelo /sync/status).
 *
 * Identidade v2: trilha de passos em pílulas (rótulo sempre visível, passo atual
 * com aria-current), cartões brancos com ícone em quadrado pastel e CTA violeta.
 * O fluxo e as regras (retomada, quem pode usar) não mudaram.
 */
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Calculator,
  Check,
  GraduationCap,
  PartyPopper,
  Plug,
  School,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import AcessoUsuariosDaEscola from "../components/AcessoUsuariosDaEscola";
import { CredenciaisForm } from "../components/CredenciaisForm";
import { Badge, Botao, Card, Carregando, IconePastel, Mensagem, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import ImportacaoMatriculas from "./ImportacaoMatriculas";

interface PlataformaStatus {
  plataforma: string; conectada: boolean; credencial_status: string;
}
interface EscolaStatus {
  // qtd_alunos e qtd_turmas são do ANO LETIVO ATIVO (como /alunos e /turmas).
  escola_id: number; escola_nome: string; qtd_alunos: number; qtd_turmas: number;
  plataformas: PlataformaStatus[]; lista_piloto_importada: boolean;
  integracao_configurada: boolean;
}

const NOME: Record<string, string> = { matific: "Matific", elefante: "Elefante Letrado" };
const ICONE_PLATAFORMA: Record<string, { icone: LucideIcon; tom: "violeta" | "teal" }> = {
  elefante: { icone: BookOpen, tom: "violeta" },
  matific: { icone: Calculator, tom: "teal" },
};
const PASSOS: { rotulo: string; icone: LucideIcon }[] = [
  { rotulo: "Escola", icone: School },
  { rotulo: "Turmas e alunos", icone: Users },
  { rotulo: "Integrações", icone: Plug },
  { rotulo: "Pronto", icone: PartyPopper },
];

const TITULO = "Comece aqui";

export default function Comecar() {
  const { escolaId, usuario } = useApp();
  const navigate = useNavigate();
  const base = escolaId ? `/escolas/${escolaId}/sync` : null;
  const status = useApi<EscolaStatus>(base ? `${base}/status` : null);

  const [passo, setPasso] = useState(1);
  const [retomado, setRetomado] = useState(false);

  const podeUsar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  // Retoma no passo certo conforme o progresso já feito (uma vez). Escola nova
  // (sem turmas) fica na boas-vindas para ler a introdução.
  useEffect(() => {
    if (retomado || !status.dados) return;
    const s = status.dados;
    if (s.integracao_configurada) setPasso(4);
    else if (s.lista_piloto_importada) setPasso(3);
    setRetomado(true);
  }, [status.dados, retomado]);

  if (!escolaId) {
    return (
      <div className="mx-auto max-w-3xl">
        <PageHeader titulo={TITULO} />
        <Card>
          <Vazio icone={School} titulo="Selecione uma escola"
                 descricao="Escolha uma escola no cartão Escola, no fim do menu lateral, para começar a configuração." />
        </Card>
      </div>
    );
  }
  if (!podeUsar) {
    return (
      <div className="mx-auto max-w-3xl">
        <PageHeader titulo={TITULO} />
        <Mensagem tipo="erro">Somente administradores e coordenadores podem configurar a escola.</Mensagem>
      </div>
    );
  }

  const s = status.dados;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        titulo={TITULO}
        descricao="Em poucos passos sua escola fica pronta: turmas, alunos e as plataformas conectadas para atualizar os dados sozinhas."
      />

      <Stepper atual={passo} concluidos={{
        1: true,
        2: Boolean(s?.lista_piloto_importada),
        3: Boolean(s?.integracao_configurada),
        4: false,
      }} />

      {/* Admin Global: Escola → Usuários (1º coordenador) antes da Lista Piloto. */}
      <AcessoUsuariosDaEscola />

      {status.carregando && !s && <Carregando texto="Carregando o estado da escola…" />}
      {status.erro && !s && (
        <Card>
          <Vazio titulo="Não foi possível carregar" descricao={status.erro.message}
            acao={<Botao variante="secundario" onClick={() => status.recarregar()}>Tentar de novo</Botao>} />
        </Card>
      )}

      {s && passo === 1 && (
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-5 p-6 sm:flex-row sm:items-start sm:p-7">
            <IconePastel icone={School} tom="violeta" tamanho="lg" />
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold tracking-tight text-zinc-900 dark:text-white">{s.escola_nome || "Sua escola"}</h2>
              <p className="mt-3 inline-flex flex-wrap items-center gap-2 rounded-full bg-indigo-50 px-3.5 py-1.5 text-sm font-medium text-indigo-800 tabular-nums dark:bg-indigo-500/15 dark:text-indigo-200">
                <GraduationCap size={15} aria-hidden />
                {s.qtd_turmas} turma(s) · {s.qtd_alunos} aluno(s) cadastrados no ano letivo atual.
              </p>
              <p className="mt-4 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
                Vamos importar a lista da escola (uma aba por turma), criar as turmas e
                matricular os alunos, e depois conectar Matific e Elefante Letrado para
                os relatórios chegarem automaticamente.
              </p>
              {usuario?.is_global && (
                <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                  Precisa cadastrar outra escola? Use a página{" "}
                  <Link to="/escolas" className="font-semibold text-indigo-600 underline underline-offset-2 dark:text-indigo-300">Escolas</Link>. O primeiro
                  usuário desta escola (coordenador) é criado em “Usuários”, acima.
                </p>
              )}
            </div>
          </div>
          <div className="flex justify-end border-t border-zinc-100 bg-zinc-50/60 px-6 py-4 dark:border-zinc-800 dark:bg-zinc-800/30">
            <Botao tamanho="lg" onClick={() => setPasso(2)}>
              Começar <ArrowRight size={16} aria-hidden />
            </Botao>
          </div>
        </Card>
      )}

      {s && passo === 2 && (
        <div className="space-y-4">
          <CabecalhoPasso icone={Users} titulo="Turmas e alunos (Lista Piloto)" />
          {s.lista_piloto_importada && (
            <Mensagem tipo="ok">
              Já há {s.qtd_turmas} turma(s) e {s.qtd_alunos} aluno(s) no ano letivo atual. Você pode importar
              outra planilha para complementar ou seguir para as integrações.
            </Mensagem>
          )}
          <ImportacaoMatriculas
            escolaId={escolaId}
            aoConcluir={() => status.recarregar()}
            aoAvancar={() => { status.recarregar(); setPasso(3); }}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Botao variante="secundario" onClick={() => setPasso(1)}>
              <ArrowLeft size={16} aria-hidden /> Voltar
            </Botao>
            {s.lista_piloto_importada && (
              <Botao variante="secundario" onClick={() => setPasso(3)}>
                Pular para integrações <ArrowRight size={16} aria-hidden />
              </Botao>
            )}
          </div>
        </div>
      )}

      {s && passo === 3 && (
        <div className="space-y-4">
          <CabecalhoPasso
            icone={Plug}
            titulo="Conectar as plataformas"
            descricao="Informe o acesso de cada plataforma. Salvar já valida a conexão — a senha é cifrada no servidor e nunca é exibida de novo. Basta conectar pelo menos uma para concluir; a outra pode ficar para depois."
          />
          {s.plataformas.map((p) => {
            const visual = ICONE_PLATAFORMA[p.plataforma] ?? { icone: Plug, tom: "violeta" as const };
            return (
              <Card key={p.plataforma} className="p-5 sm:p-6">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <h3 className="flex items-center gap-3 text-base font-semibold text-zinc-900 dark:text-white">
                    <IconePastel icone={visual.icone} tom={visual.tom} tamanho="sm" />
                    {NOME[p.plataforma] ?? p.plataforma}
                  </h3>
                  {p.conectada
                    ? <Badge tom="ok">✓ conectada</Badge>
                    : p.credencial_status === "ilegivel"
                      ? <Badge tom="alerta">recadastre o acesso</Badge>
                      : <Badge tom="neutro">não conectada</Badge>}
                </div>
                <CredenciaisForm base={base!} plataforma={p.plataforma}
                  nome={NOME[p.plataforma] ?? p.plataforma}
                  status={p.credencial_status} aoMudar={() => status.recarregar()} />
              </Card>
            );
          })}
          {/* Celular (< 640 px): botões empilhados em largura total — Concluir em cima,
              Configurar depois e Voltar embaixo (só a ordem VISUAL muda; no DOM e no Tab
              segue Voltar → Configurar depois → Concluir). A partir de 640 px, como antes:
              Voltar à esquerda e as outras ações à direita. */}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <Botao variante="secundario" onClick={() => setPasso(2)}>
              <ArrowLeft size={16} aria-hidden /> Voltar
            </Botao>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
              <Botao variante="secundario" onClick={() => setPasso(4)}>Configurar depois</Botao>
              <Botao disabled={!s.integracao_configurada} onClick={() => setPasso(4)}
                     aria-describedby={!s.integracao_configurada ? "motivo-concluir" : undefined}>
                Concluir <ArrowRight size={16} aria-hidden />
              </Botao>
            </div>
          </div>
          {!s.integracao_configurada && (
            <p id="motivo-concluir" className="text-center text-xs text-zinc-500 sm:text-right dark:text-zinc-400">
              “Concluir” libera quando pelo menos uma plataforma estiver conectada.
            </p>
          )}
        </div>
      )}

      {s && passo === 4 && (
        <Card className="relative overflow-hidden p-8 text-center">
          <span aria-hidden className="pointer-events-none absolute -top-16 left-1/2 h-40 w-72 -translate-x-1/2 rounded-full bg-indigo-100/70 blur-3xl dark:bg-indigo-500/10" />
          <div className="relative">
            <span aria-hidden className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-indigo-600 text-white shadow-pilula">
              <PartyPopper size={30} />
            </span>
            <h2 className="mt-4 text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">Escola pronta!</h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-zinc-600 dark:text-zinc-300">
              {s.qtd_turmas} turma(s) e {s.qtd_alunos} aluno(s) cadastrados no ano letivo atual
              {s.integracao_configurada
                ? " e as plataformas conectadas. As atualizações podem rodar automaticamente."
                : ". Você pode conectar as plataformas quando quiser em Integrações."}
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <Badge tom={s.lista_piloto_importada ? "ok" : "alerta"}>
                {s.lista_piloto_importada ? "✓ turmas e alunos" : "turmas pendentes"}
              </Badge>
              <Badge tom={s.integracao_configurada ? "ok" : "neutro"}>
                {s.integracao_configurada ? "✓ integração configurada" : "integração opcional"}
              </Badge>
            </div>
            <div className="mt-7 flex flex-wrap justify-center gap-2.5">
              <Botao tamanho="lg" onClick={() => navigate("/sincronizacao")}>
                Abrir Integrações
              </Botao>
              <Botao tamanho="lg" variante="secundario" onClick={() => navigate("/ranking")}>Ver ranking</Botao>
            </div>
            <p className="mt-5 text-xs text-zinc-500 dark:text-zinc-400">
              Se a sincronização não estiver disponível,{" "}
              <Link to="/importacoes" className="font-semibold text-indigo-600 underline underline-offset-2 hover:text-indigo-700 dark:text-indigo-300">
                envie o relatório manualmente
              </Link>.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}

function CabecalhoPasso({ icone, titulo, descricao }: { icone: LucideIcon; titulo: string; descricao?: string }) {
  return (
    <div className="flex items-start gap-3">
      <IconePastel icone={icone} tom="violeta" />
      <div className="min-w-0">
        <h2 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-white">{titulo}</h2>
        {descricao && <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
      </div>
    </div>
  );
}

/** Trilha dos passos: pílula violeta no atual, verde no concluído. O rótulo fica
 *  sempre visível e inteiro: no estreito a trilha quebra em duas linhas e, se ainda
 *  faltar largura, o rótulo quebra dentro da pílula (nunca "Turmas e alu…"). */
function Stepper({ atual, concluidos }: { atual: number; concluidos: Record<number, boolean> }) {
  return (
    <ol aria-label="Passos da configuração" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {PASSOS.map(({ rotulo, icone: Icone }, i) => {
        const n = i + 1;
        const ativo = n === atual;
        const feito = concluidos[n] && n !== atual;
        return (
          <li
            key={rotulo}
            aria-current={ativo ? "step" : undefined}
            className={`flex min-w-0 items-center gap-2.5 rounded-2xl border px-3 py-2.5 text-sm transition-colors ${
              ativo
                ? "border-transparent bg-indigo-600 text-white shadow-pilula"
                : feito
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200"
                  : "border-zinc-200 bg-white text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"}`}
          >
            <span
              aria-hidden
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${
                ativo
                  ? "bg-white/20 text-white"
                  : feito
                    ? "bg-emerald-500 text-white"
                    : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-300"}`}
            >
              {feito ? <Check size={14} /> : <Icone size={14} />}
            </span>
            {/* Quebra em duas linhas quando falta largura ("Turmas e / alunos"), em vez
                de cortar com reticências; o title fica com o rótulo completo. */}
            <span className="min-w-0 font-semibold leading-tight [overflow-wrap:anywhere]" title={rotulo}>
              <span className="sr-only">Passo {n}: </span>{rotulo}
              {feito && <span className="sr-only"> (concluído)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
