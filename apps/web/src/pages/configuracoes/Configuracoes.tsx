import { Download, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import ConfigAssistenteIA from "../../components/ConfigAssistenteIA";
import { Botao, Card, Mensagem, PageHeader } from "../../components/ui";
import { PesosEditor } from "./Metricas";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, ApiError, apiDownload, apiUpload } from "../../lib/api";

interface AparenciaDados {
  cor_primaria: string;
  brasao_data_uri?: string;
  prefeitura_data_uri?: string;
}

/** Um "slot" de logo da cidade (brasão ou prefeitura): prévia + enviar + remover.
 * A imagem sobe para a escola e passa a aparecer no topo dos PDFs (certificado,
 * cartaz, lista de alunos, catálogo). Sem envio, o PDF usa o logo padrão. */
function LogoUploader({
  escolaId, tipo, titulo, atual, onMudou, editavel,
}: {
  escolaId: number;
  tipo: "brasao" | "prefeitura";
  titulo: string;
  atual?: string;
  onMudou: () => Promise<unknown> | void;
  editavel: boolean;
}) {
  const arquivoRef = useRef<HTMLInputElement | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  async function enviar(arquivo: File) {
    setOcupado(true);
    setErro("");
    try {
      const dados = new FormData();
      dados.append("arquivo", arquivo);
      await apiUpload(`/escolas/${escolaId}/aparencia/logo?tipo=${tipo}`, dados);
      await onMudou();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao enviar a imagem.");
    } finally {
      setOcupado(false);
      if (arquivoRef.current) arquivoRef.current.value = "";
    }
  }

  async function remover() {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/aparencia/logo?tipo=${tipo}`, { method: "DELETE" });
      await onMudou();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao remover.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="flex items-center gap-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded bg-zinc-50 dark:bg-zinc-900">
        {atual ? (
          <img src={atual} alt={titulo} className="max-h-14 max-w-[3.5rem] object-contain" />
        ) : (
          <span className="text-[10px] text-zinc-400">padrão</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{titulo}</p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {atual ? "Enviado por esta escola." : "Usando o logo padrão do sistema."}
        </p>
        {erro && <p className="mt-1 text-xs text-rose-600">{erro}</p>}
      </div>
      {editavel && (
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Botao variante="neutro" disabled={ocupado} onClick={() => arquivoRef.current?.click()}>
            <UploadCloud size={14} /> {atual ? "Trocar" : "Enviar"}
          </Botao>
          {atual && (
            <button
              type="button"
              onClick={remover}
              disabled={ocupado}
              className="text-xs text-zinc-500 hover:text-rose-600 disabled:opacity-50"
            >
              Remover
            </button>
          )}
          <input
            ref={arquivoRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(evento) => {
              const arquivo = evento.target.files?.[0];
              if (arquivo) enviar(arquivo);
            }}
          />
        </div>
      )}
    </div>
  );
}

/** Aparência (PRD §18): cor primária e logos da cidade usados nos PDFs. */
function Aparencia() {
  const { escolaId, usuario } = useApp();
  const ehAdmin = usuario?.is_global || usuario?.cargo === "admin";
  const [cor, setCor] = useState("#1B2A4A");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // A cor é estado editável (color picker + PUT); buscamos a salva e semeamos o input.
  const { dados: aparencia, erro: erroAparencia, recarregar } = useApi<AparenciaDados>(
    escolaId ? `/escolas/${escolaId}/aparencia` : null,
  );

  useEffect(() => {
    if (aparencia) setCor(aparencia.cor_primaria);
  }, [aparencia]);

  async function salvar() {
    if (!escolaId) return;
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/aparencia`, {
        method: "PUT",
        body: JSON.stringify({ cor_primaria: cor, mostrar_fotos: true }),
      });
      setMensagem({ tipo: "ok", texto: "Aparência salva. Relatórios e certificados usarão a nova cor." });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha ao salvar." });
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-3 text-sm">
          <span className="font-medium">Cor primária da escola</span>
          <input
            type="color"
            aria-label="Cor primária"
            className="h-9 w-14 cursor-pointer rounded border border-zinc-300 bg-transparent dark:border-zinc-700"
            value={cor}
            onChange={(evento) => setCor(evento.target.value.toUpperCase())}
            disabled={!ehAdmin}
          />
          <code className="text-xs text-zinc-500">{cor}</code>
        </label>
        {ehAdmin && <Botao onClick={salvar}>Salvar aparência</Botao>}
      </div>
      <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
        Aplicada no cabeçalho dos relatórios em PDF/Excel e nos certificados.
      </p>

      {escolaId && (
        <div className="mt-5 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <p className="text-sm font-medium">Logos da cidade nos documentos</p>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Aparecem no topo dos certificados e relatórios em PDF, ao lado da marca
            Constela (brasão à esquerda, prefeitura à direita). PNG com fundo
            transparente fica melhor. Sem envio, o sistema usa o logo padrão.
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <LogoUploader
              escolaId={escolaId}
              tipo="brasao"
              titulo="Brasão da cidade"
              atual={aparencia?.brasao_data_uri}
              onMudou={recarregar}
              editavel={!!ehAdmin}
            />
            <LogoUploader
              escolaId={escolaId}
              tipo="prefeitura"
              titulo="Logo da prefeitura"
              atual={aparencia?.prefeitura_data_uri}
              onMudou={recarregar}
              editavel={!!ehAdmin}
            />
          </div>
        </div>
      )}

      {erroAparencia && (
        <div className="mt-3">
          <Mensagem tipo="erro">Não foi possível carregar a aparência salva: {erroAparencia.message}</Mensagem>
        </div>
      )}
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Card>
  );
}

/** Backup e restauração por escola (PRD §18). */
function Backup() {
  const { escolaId, usuario } = useApp();
  const ehAdmin = usuario?.is_global || usuario?.cargo === "admin";
  const arquivoRef = useRef<HTMLInputElement | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  if (!ehAdmin) return null;

  async function baixar() {
    if (!escolaId) return;
    setOcupado(true);
    setMensagem(null);
    try {
      await apiDownload(`/escolas/${escolaId}/backup`);
      setMensagem({ tipo: "ok", texto: "Backup gerado. Guarde o arquivo em local seguro." });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha no backup." });
    } finally {
      setOcupado(false);
    }
  }

  async function restaurar(arquivo: File) {
    if (!escolaId) return;
    const confirmado = window.confirm(
      "ATENÇÃO: a restauração SUBSTITUI todos os dados pedagógicos desta escola " +
      "pelos do arquivo (alunos, turmas, notas, importações, configurações). " +
      "Usuários e senhas não são alterados. Deseja continuar?",
    );
    if (!confirmado) return;
    setOcupado(true);
    setMensagem(null);
    try {
      const dados = new FormData();
      dados.append("arquivo", arquivo);
      const resposta = await apiUpload<{ mensagem: string }>(`/escolas/${escolaId}/restaurar`, dados);
      setMensagem({ tipo: "ok", texto: resposta.mensagem });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha na restauração." });
    } finally {
      setOcupado(false);
      if (arquivoRef.current) arquivoRef.current.value = "";
    }
  }

  return (
    <Card className="p-5">
      <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-300">
        O backup é um arquivo JSON com todos os dados pedagógicos desta escola
        (funciona em SQLite e PostgreSQL). Usuários e senhas ficam de fora, por segurança.
      </p>
      <div className="flex flex-wrap gap-2">
        <Botao onClick={baixar} disabled={ocupado}>
          <Download size={15} /> Baixar backup
        </Botao>
        <Botao
          variante="neutro"
          disabled={ocupado}
          onClick={() => arquivoRef.current?.click()}
        >
          <UploadCloud size={15} /> Restaurar de um arquivo…
        </Botao>
        <input
          ref={arquivoRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={(evento) => {
            const arquivo = evento.target.files?.[0];
            if (arquivo) restaurar(arquivo);
          }}
        />
      </div>
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Card>
  );
}

export default function Configuracoes() {
  const { escolaAtual, escolaId, recarregarEscolas, usuario } = useApp();
  const ehAdminIA = Boolean(usuario?.is_global) || usuario?.cargo === "admin";
  const [nome, setNome] = useState("");
  const [cidade, setCidade] = useState("");
  const [estado, setEstado] = useState("");
  const [anoLetivo, setAnoLetivo] = useState(2026);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (!escolaAtual) return;
    setNome(escolaAtual.nome);
    setCidade(escolaAtual.cidade ?? "");
    setEstado(escolaAtual.estado ?? "");
    setAnoLetivo(escolaAtual.ano_letivo_ativo);
    setMensagem(null);
  }, [escolaAtual]);

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    if (!escolaId) return;
    setSalvando(true);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}`, {
        method: "PATCH",
        body: JSON.stringify({
          nome,
          cidade: cidade || null,
          estado: estado || null,
          ano_letivo_ativo: anoLetivo,
        }),
      });
      await recarregarEscolas();
      setMensagem({ tipo: "ok", texto: "Dados da escola atualizados." });
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader titulo="Configurações" descricao="Dados da escola e regras gerais do sistema." />

      <section className="max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Escola</h2>
        <Card className="p-5">
          <form onSubmit={salvar} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block font-medium">Nome</span>
              <input
                required
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950"
                value={nome}
                onChange={(evento) => setNome(evento.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Cidade</span>
              <input
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950"
                value={cidade}
                onChange={(evento) => setCidade(evento.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Estado (UF)</span>
              <input
                maxLength={2}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 uppercase dark:border-zinc-700 dark:bg-zinc-950"
                value={estado}
                onChange={(evento) => setEstado(evento.target.value.toUpperCase())}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Ano letivo ativo</span>
              <input
                type="number"
                min={2024}
                max={2100}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
                value={anoLetivo}
                onChange={(evento) => setAnoLetivo(Number(evento.target.value))}
              />
            </label>
            <div className="sm:col-span-2">
              <Botao type="submit" disabled={salvando}>
                {salvando ? "Salvando..." : "Salvar dados da escola"}
              </Botao>
            </div>
          </form>
          {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
        </Card>
      </section>

      <section className="max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Pesos do Ranking Geral</h2>
        <PesosEditor
          namespace="geral"
          rotulos={{ matific: "Matific", elefante: "Elefante Letrado" }}
          descricao="Como as notas dos módulos se combinam no Ranking Geral (PRD §41)."
        />
      </section>

      <section className="max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Aparência</h2>
        <Aparencia />
      </section>

      {ehAdminIA && (
        <section className="max-w-2xl">
          <h2 className="mb-3 text-sm font-semibold">Assistente de IA</h2>
          <ConfigAssistenteIA />
        </section>
      )}

      <section className="max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Backup e restauração</h2>
        <Backup />
      </section>

      <section className="max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Conquistas</h2>
        <Card className="p-5 text-sm text-zinc-600 dark:text-zinc-300">
          Crie e ajuste as medalhas da escola — critérios, XP, raridade, ordem e
          ativação — na tela{" "}
          <Link
            to="/configuracoes/conquistas"
            className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Configurações → Conquistas
          </Link>
          . As mudanças valem imediatamente para todos os alunos.
        </Card>
      </section>

      <section className="max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Critérios de avaliação</h2>
        <Card className="p-5 text-sm text-zinc-600 dark:text-zinc-300">
          Pesos por indicador, dificuldade por turma e referências de normalização ficam na tela{" "}
          <Link to="/metricas" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
            Métricas
          </Link>
          . Contas de acesso ficam na tela{" "}
          <Link to="/usuarios" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
            Usuários
          </Link>
          .
        </Card>
      </section>
    </div>
  );
}
