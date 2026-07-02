import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Botao, Card, Mensagem, PageHeader } from "../../components/ui";
import { PesosEditor } from "./Metricas";
import { useApp } from "../../context/AppContext";
import { api, ApiError } from "../../lib/api";

export default function Configuracoes() {
  const { escolaAtual, escolaId, recarregarEscolas } = useApp();
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
        <h2 className="mb-3 text-sm font-semibold">Critérios de avaliação</h2>
        <Card className="p-5 text-sm text-zinc-600 dark:text-zinc-300">
          Pesos por indicador, dificuldade por turma e referências de normalização ficam na tela{" "}
          <Link to="/metricas" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
            Métricas
          </Link>
          . Usuários, backup e aparência avançada chegam nas próximas fases (veja <code>docs/ROADMAP.md</code>).
        </Card>
      </section>
    </div>
  );
}
