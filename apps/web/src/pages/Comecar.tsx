/**
 * Assistente de primeiros passos ("Comece aqui").
 *
 * Um fluxo ÚNICO que leva a escola do zero ao sistema funcionando em poucos
 * minutos: confirma a escola → importa turmas e alunos (Lista Piloto) →
 * conecta Matific/Elefante → conclui. Reaproveita os componentes já existentes
 * (ImportacaoMatriculas, CredenciaisForm) — o assistente só orquestra os passos
 * e sabe retomar de onde a escola parou (pelo /sync/status).
 */
import {
  ArrowLeft,
  ArrowRight,
  Check,
  PartyPopper,
  Plug,
  School,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { CredenciaisForm } from "../components/CredenciaisForm";
import { Badge, Botao, Card, Carregando, Mensagem, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import ImportacaoMatriculas from "./ImportacaoMatriculas";

interface PlataformaStatus {
  plataforma: string; conectada: boolean; credencial_status: string;
}
interface EscolaStatus {
  escola_id: number; escola_nome: string; qtd_alunos: number; qtd_turmas: number;
  plataformas: PlataformaStatus[]; lista_piloto_importada: boolean;
  integracao_configurada: boolean;
}

const NOME: Record<string, string> = { matific: "Matific", elefante: "Elefante Letrado" };
const PASSOS = ["Escola", "Turmas e alunos", "Integrações", "Pronto"];

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
    return <Vazio titulo="Selecione uma escola" descricao="Escolha uma escola no topo para começar a configuração." />;
  }
  if (!podeUsar) {
    return <Mensagem tipo="erro">Somente administradores e coordenadores podem configurar a escola.</Mensagem>;
  }

  const s = status.dados;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Comece aqui</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Em poucos passos sua escola fica pronta: turmas, alunos e as plataformas
          conectadas para atualizar os dados sozinhas.
        </p>
      </div>

      <Stepper atual={passo} concluidos={{
        1: true,
        2: Boolean(s?.lista_piloto_importada),
        3: Boolean(s?.integracao_configurada),
        4: false,
      }} />

      {status.carregando && !s && <Carregando texto="Carregando o estado da escola…" />}
      {status.erro && !s && (
        <Vazio titulo="Não foi possível carregar" descricao={status.erro.message}
          acao={<Botao variante="neutro" onClick={() => status.recarregar()}>Tentar de novo</Botao>} />
      )}

      {s && passo === 1 && (
        <Card className="p-6">
          <div className="flex items-start gap-3">
            <School size={22} className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <div>
              <h2 className="text-base font-semibold tracking-tight">{s.escola_nome || "Sua escola"}</h2>
              <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                {s.qtd_turmas} turma(s) · {s.qtd_alunos} aluno(s) cadastrados.
              </p>
              <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-300">
                Vamos importar a lista da escola (uma aba por turma), criar as turmas e
                matricular os alunos, e depois conectar Matific e Elefante Letrado para
                os relatórios chegarem automaticamente.
              </p>
              {usuario?.is_global && (
                <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                  Precisa cadastrar outra escola? Use a página{" "}
                  <Link to="/escolas" className="font-medium underline">Escolas</Link>.
                </p>
              )}
            </div>
          </div>
          <div className="mt-5 flex justify-end">
            <Botao onClick={() => setPasso(2)}>
              Começar <ArrowRight size={16} />
            </Botao>
          </div>
        </Card>
      )}

      {s && passo === 2 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Users size={16} className="text-indigo-600 dark:text-indigo-400" />
            Turmas e alunos (Lista Piloto)
          </div>
          {s.lista_piloto_importada && (
            <Mensagem tipo="ok">
              Já há {s.qtd_turmas} turma(s) e {s.qtd_alunos} aluno(s). Você pode importar
              outra planilha para complementar ou seguir para as integrações.
            </Mensagem>
          )}
          <ImportacaoMatriculas
            escolaId={escolaId}
            aoConcluir={() => status.recarregar()}
            aoAvancar={() => { status.recarregar(); setPasso(3); }}
          />
          <div className="flex items-center justify-between">
            <Botao variante="neutro" onClick={() => setPasso(1)}>
              <ArrowLeft size={16} /> Voltar
            </Botao>
            {s.lista_piloto_importada && (
              <Botao variante="neutro" onClick={() => setPasso(3)}>
                Pular para integrações <ArrowRight size={16} />
              </Botao>
            )}
          </div>
        </div>
      )}

      {s && passo === 3 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Plug size={16} className="text-indigo-600 dark:text-indigo-400" />
            Conectar as plataformas
          </div>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Informe o acesso de cada plataforma. Salvar já valida a conexão — a senha é
            cifrada no servidor e nunca é exibida de novo. Basta conectar pelo menos uma
            para concluir; a outra pode ficar para depois.
          </p>
          {s.plataformas.map((p) => (
            <Card key={p.plataforma} className="p-5">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold">{NOME[p.plataforma] ?? p.plataforma}</h3>
                {p.conectada
                  ? <Badge tom="ok">✓ conectada</Badge>
                  : <Badge tom="neutro">não conectada</Badge>}
              </div>
              <CredenciaisForm base={base!} plataforma={p.plataforma}
                nome={NOME[p.plataforma] ?? p.plataforma}
                status={p.credencial_status} aoMudar={() => status.recarregar()} />
            </Card>
          ))}
          <div className="flex items-center justify-between">
            <Botao variante="neutro" onClick={() => setPasso(2)}>
              <ArrowLeft size={16} /> Voltar
            </Botao>
            <div className="flex gap-2">
              <Botao variante="neutro" onClick={() => setPasso(4)}>Configurar depois</Botao>
              <Botao disabled={!s.integracao_configurada} onClick={() => setPasso(4)}>
                Concluir <ArrowRight size={16} />
              </Botao>
            </div>
          </div>
        </div>
      )}

      {s && passo === 4 && (
        <Card className="p-6 text-center">
          <PartyPopper size={32} className="mx-auto text-indigo-600 dark:text-indigo-400" />
          <h2 className="mt-3 text-lg font-semibold tracking-tight">Escola pronta!</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-zinc-500 dark:text-zinc-400">
            {s.qtd_turmas} turma(s) e {s.qtd_alunos} aluno(s) cadastrados
            {s.integracao_configurada
              ? " e as plataformas conectadas. As atualizações podem rodar automaticamente."
              : ". Você pode conectar as plataformas quando quiser no painel de sincronização."}
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <Badge tom={s.lista_piloto_importada ? "ok" : "alerta"}>
              {s.lista_piloto_importada ? "✓ turmas e alunos" : "turmas pendentes"}
            </Badge>
            <Badge tom={s.integracao_configurada ? "ok" : "neutro"}>
              {s.integracao_configurada ? "✓ integração configurada" : "integração opcional"}
            </Badge>
          </div>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            <Botao onClick={() => navigate("/sincronizacao")}>
              Abrir painel de sincronização
            </Botao>
            <Botao variante="neutro" onClick={() => navigate("/ranking")}>Ver ranking</Botao>
            <Botao variante="neutro" onClick={() => navigate("/importacoes")}>Importar relatório manual</Botao>
          </div>
        </Card>
      )}
    </div>
  );
}

function Stepper({ atual, concluidos }: { atual: number; concluidos: Record<number, boolean> }) {
  return (
    <ol className="flex items-center gap-2">
      {PASSOS.map((rotulo, i) => {
        const n = i + 1;
        const ativo = n === atual;
        const feito = concluidos[n] && n !== atual;
        return (
          <li key={rotulo} className="flex flex-1 items-center gap-2">
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
              ativo ? "bg-indigo-600 text-white"
                : feito ? "bg-emerald-500 text-white"
                  : "bg-zinc-200 text-zinc-500 dark:bg-zinc-700 dark:text-zinc-300"}`}>
              {feito ? <Check size={14} /> : n}
            </span>
            <span className={`hidden text-xs font-medium sm:inline ${
              ativo ? "text-zinc-900 dark:text-zinc-100" : "text-zinc-500 dark:text-zinc-400"}`}>
              {rotulo}
            </span>
            {i < PASSOS.length - 1 && (
              <span className="mx-1 h-px flex-1 bg-zinc-200 dark:bg-zinc-700" />
            )}
          </li>
        );
      })}
    </ol>
  );
}
