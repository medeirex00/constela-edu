import { Download, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import ConfigAssistenteIA from "../../components/ConfigAssistenteIA";
import { Botao, Card, Mensagem, PageHeader } from "../../components/ui";
import { PesosEditor } from "./Metricas";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, ApiError, apiDownload, apiUpload } from "../../lib/api";

/** Aparência (PRD §18): cor primária usada nos relatórios e certificados. */
function Aparencia() {
  const { escolaId, usuario } = useApp();
  const ehAdmin = usuario?.is_global || usuario?.cargo === "admin";
  const [cor, setCor] = useState("#1B2A4A");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // A cor é estado editável (color picker + PUT); buscamos a salva e semeamos o input.
  const { dados: aparencia, erro: erroAparencia } = useApi<{ cor_primaria: string }>(
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
      {erroAparencia && (
        <div className="mt-3">
          <Mensagem tipo="erro">Não foi possível carregar a cor salva: {erroAparencia.message}</Mensagem>
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
