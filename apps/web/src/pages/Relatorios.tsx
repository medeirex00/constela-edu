/** Relatórios (PRD §86–§103): exportação CSV/Excel/PDF e certificados. */
import { Award, BookOpen, Calculator, FileDown, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";

import { Botao, Campo, Card, Mensagem, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
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

/** Bimestre pelo calendário escolar — o MESMO mapa do backend
 *  (`relatorios._bimestre_por_mes`): fev–abr=1, mai–jul=2, ago–set=3, out–dez=4,
 *  jan cai no 1º. Duplicado aqui só para o seletor abrir no número de hoje. */
export function bimestreDoMes(d: Date): number {
  return [1, 1, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4][d.getMonth() + 1];
}

export default function Relatorios() {
  const { escolaId, usuario } = useApp();
  // Professor exporta só o superficial (ranking e alunos das turmas dele);
  // o backend também recusa os demais tipos.
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const relatorios = gestor
    ? RELATORIOS
    : RELATORIOS.filter((r) => r.tipo === "ranking" || r.tipo === "alunos");
  // Lista de alunos para o seletor de certificados (leitura via useApi).
  const { dados: paginaAlunos, erro: erroAlunos } = useApi<PaginaAlunos>(
    escolaId ? `/escolas/${escolaId}/alunos?por_pagina=100` : null,
  );
  const alunos = (paginaAlunos?.itens ?? []).map((aluno) => ({ id: aluno.id, nome: aluno.nome }));
  const [alunoId, setAlunoId] = useState("");
  // Bimestre IMPRESSO na arte da plataforma. O backend cai no bimestre do MÊS de
  // emissão quando não recebe o parâmetro — e aí o mesmo aluno, com o mesmo dado,
  // recebe "3" num dia e "4" no seguinte se a entrega atravessa a virada. Quem
  // emite escolhe; o padrão é o bimestre de hoje, para a tela não mudar nada
  // para quem não liga para isso.
  const [bimestre, setBimestre] = useState(String(bimestreDoMes(new Date())));
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState("");

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
            Escolha o aluno e emita o certificado em PDF de alta resolução. Todos os campos
            (instituição, nome do aluno, bimestre e data) são preenchidos <strong>automaticamente</strong>.
            O <strong>Geral</strong> traz turma, nota e posição; os de <strong>Elefante Letrado</strong> e
            <strong> Matific</strong> usam a arte oficial da plataforma.
          </p>
          {erroAlunos && (
            <div className="mb-4"><Mensagem tipo="erro">Não foi possível carregar os alunos: {erroAlunos.message}</Mensagem></div>
          )}
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
            <div className="w-40">
              <Campo rotulo="Bimestre (arte da plataforma)">
                <select className={estiloInput} value={bimestre}
                        onChange={(e) => setBimestre(e.target.value)}>
                  {[1, 2, 3, 4].map((b) => (
                    <option key={b} value={b}>{b}º bimestre</option>
                  ))}
                </select>
              </Campo>
            </div>
            <div className="flex flex-wrap gap-2">
              <Botao
                variante="neutro"
                disabled={!alunoId || ocupado !== ""}
                onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}`, "cert-geral")}
              >
                <Award size={15} /> {ocupado === "cert-geral" ? "Gerando..." : "Geral"}
              </Botao>
              <Botao
                disabled={!alunoId || ocupado !== ""}
                onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}?modelo=elefante&bimestre=${bimestre}`, "cert-elefante")}
              >
                <BookOpen size={15} /> {ocupado === "cert-elefante" ? "Gerando..." : "Elefante Letrado"}
              </Botao>
              <Botao
                disabled={!alunoId || ocupado !== ""}
                onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}?modelo=matific&bimestre=${bimestre}`, "cert-matific")}
              >
                <Calculator size={15} /> {ocupado === "cert-matific" ? "Gerando..." : "Matific"}
              </Botao>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
