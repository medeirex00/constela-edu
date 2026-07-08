/** Relatórios (PRD §86–§103): exportação CSV/Excel/PDF e certificados. */
import { Award, FileDown, FileSpreadsheet, FileText } from "lucide-react";
import { useEffect, useState } from "react";

import { Botao, Campo, Card, Mensagem, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api, apiDownload } from "../lib/api";
import type { PaginaAlunos } from "../lib/types";

const RELATORIOS = [
  { tipo: "ranking", nome: "Ranking Geral", descricao: "Posição e notas de todos os alunos do ano letivo." },
  { tipo: "alunos", nome: "Lista de Alunos", descricao: "Alunos ativos com turma, série e número de chamada." },
  { tipo: "livros", nome: "Catálogo de Livros", descricao: "Acervo com níveis e total de leituras registradas." },
];

const FORMATOS = [
  { formato: "pdf", rotulo: "PDF", icone: FileText },
  { formato: "xlsx", rotulo: "Excel", icone: FileSpreadsheet },
  { formato: "csv", rotulo: "CSV", icone: FileDown },
];

export default function Relatorios() {
  const { escolaId, usuario } = useApp();
  // Professor exporta só o superficial (ranking e alunos das turmas dele);
  // o backend também recusa os demais tipos.
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const relatorios = gestor
    ? RELATORIOS
    : RELATORIOS.filter((r) => r.tipo === "ranking" || r.tipo === "alunos");
  const [alunos, setAlunos] = useState<{ id: number; nome: string }[]>([]);
  const [alunoId, setAlunoId] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState("");

  useEffect(() => {
    if (!escolaId) return;
    api<PaginaAlunos>(`/escolas/${escolaId}/alunos?por_pagina=100`)
      .then((pagina) => setAlunos(pagina.itens.map((aluno) => ({ id: aluno.id, nome: aluno.nome }))))
      .catch(() => setAlunos([]));
  }, [escolaId]);

  async function baixar(caminho: string, chave: string) {
    if (!escolaId) return;
    setOcupado(chave);
    setErro("");
    try {
      await apiDownload(caminho);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao gerar o arquivo.");
    } finally {
      setOcupado("");
    }
  }

  return (
    <div>
      <PageHeader
        titulo="Relatórios"
        descricao="Exportações com a identidade visual da escola. Uma cópia de cada arquivo fica registrada em /exports."
      />
      {erro && <div className="mb-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}

      <div className="grid gap-4 lg:grid-cols-3">
        {relatorios.map((relatorio) => (
          <Card key={relatorio.tipo} className="flex flex-col p-5">
            <h3 className="text-sm font-semibold">{relatorio.nome}</h3>
            <p className="mt-1 flex-1 text-sm text-zinc-500 dark:text-zinc-400">{relatorio.descricao}</p>
            <div className="mt-4 flex gap-2">
              {FORMATOS.map(({ formato, rotulo, icone: Icone }) => (
                <Botao
                  key={formato}
                  variante="neutro"
                  disabled={ocupado !== ""}
                  onClick={() =>
                    baixar(`/escolas/${escolaId}/relatorios/${relatorio.tipo}?formato=${formato}`,
                           `${relatorio.tipo}-${formato}`)
                  }
                >
                  <Icone size={14} />
                  {ocupado === `${relatorio.tipo}-${formato}` ? "Gerando..." : rotulo}
                </Botao>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-8 max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Certificados</h2>
        <Card className="p-5">
          <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
            Certificado individual em PDF com nome, turma, nota geral e posição no ranking (PRD §99).
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1">
              <Campo rotulo="Aluno">
                <select className={estiloInput} value={alunoId} onChange={(e) => setAlunoId(e.target.value)}>
                  <option value="">Selecione…</option>
                  {alunos.map((aluno) => (
                    <option key={aluno.id} value={aluno.id}>{aluno.nome}</option>
                  ))}
                </select>
              </Campo>
            </div>
            <Botao
              disabled={!alunoId || ocupado !== ""}
              onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}`, "certificado")}
            >
              <Award size={15} /> {ocupado === "certificado" ? "Gerando..." : "Emitir certificado"}
            </Botao>
          </div>
        </Card>
      </div>
    </div>
  );
}
