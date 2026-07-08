/**
 * Escolas (administrador GLOBAL): todas as escolas da rede num lugar só —
 * criar, renomear e adicionar de uma vez a rede municipal de Caraguatatuba
 * (unidades com 1º ao 5º ano). Os nomes vêm curtos (ex.: "DEBORA PILON");
 * é só renomear os que não agradarem.
 */
import { Building2, Pencil, Power, School } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { ApiError, api } from "../lib/api";
import { normalizar } from "../lib/nomes";
import type { Escola } from "../lib/types";

/** Rede municipal de Caraguatatuba — unidades com ensino fundamental ANOS
 *  INICIAIS (1º–5º ano), conforme a relação oficial da Secretaria de
 *  Educação (out/2025). Nome curto no padrão da casa ("JORGE PASSOS"). */
const REDE_CARAGUA: { nome: string; completo: string }[] = [
  { nome: "ADOLFINA", completo: "CIEFI Prof.ª Adolfina Leonor Soares dos Santos — Sumaré" },
  { nome: "AIDA GRAZIOLI", completo: "EMEI/EMEF Prof.ª Aida de Almeida Castro Grazioli — Rio do Ouro" },
  { nome: "ALAOR JUNQUEIRA", completo: "EMEI/EMEF Prof. Alaor Xavier Junqueira — Travessão" },
  { nome: "ANTONIA RIBEIRO", completo: "CIEFI Prof.ª Antonia Ribeiro da Silva — Jd. Califórnia" },
  { nome: "AURACY MANSANO", completo: "EMEF Prof. Auracy Mansano — Jetuba" },
  { nome: "BENEDITO SOARES", completo: "EMEI/EMEF Benedito Inácio Soares — Massaguaçu" },
  { nome: "BERNARDO LOUZADA", completo: "EMEI/EMEF Prof. Bernardo Ferreira Louzada — Rio do Ouro" },
  { nome: "ORTEGA", completo: "EMEI/EMEF Carlos Altero Ortega — Morro do Algodão" },
  { nome: "CARLOS RODRIGUES", completo: "EMEF Dr. Carlos de Almeida Rodrigues — Indaiá" },
  { nome: "DEBORA PILON", completo: "EMEF Prof.ª Débora Valle da Silva Pilon — Travessão" },
  { nome: "EUCLYDES FERREIRA", completo: "EMEF Prof. Euclydes Ferreira — Perequê-Mirim" },
  { nome: "GERALDO DE LIMA", completo: "EMEF Prof. Geraldo de Lima — Perequê-Mirim" },
  { nome: "JANE FOCESI", completo: "EMEF Prof.ª Jane Urbano Focesi — Perequê-Mirim" },
  { nome: "GARDELIN", completo: "EMEI/EMEF Prof. João Baptista Gardelin — Poiares" },
  { nome: "JOAO MARCONDES", completo: "EMEI/EMEF Prof. João Benedito Marcondes — Barranco Alto" },
  { nome: "JOAO THIMOTEO", completo: "EMEI/EMEF João Thimóteo do Rosário — Canta Galo" },
  { nome: "LUCIO JACINTO", completo: "EMEI/EMEF Prof. Lúcio Jacinto dos Santos — Tinga" },
  { nome: "LUIZ SILVAR", completo: "EMEF Prof. Luiz Silvar do Prado — Casa Branca" },
  { nome: "MARIA CARVALHO", completo: "EMEF Prof.ª Maria Aparecida de Carvalho — Tinga" },
  { nome: "MARIA UJIO", completo: "EMEF Prof.ª Maria Aparecida Ujio — Porto Novo" },
  { nome: "MARIA MORAES", completo: "EMEF Prof.ª Maria Moraes de Oliveira — Jd. Gaivotas (4º–9º)" },
  { nome: "MARIA THEREZA", completo: "EMEI/EMEF Prof.ª Maria Thereza de Souza Castro — Jetuba" },
  { nome: "MASAKO SONE", completo: "EMEI/EMEF Masako Sone — Pegorelli" },
  { nome: "OSWALDO FERREIRA", completo: "EMEF Prof. Oswaldo Ferreira — Casa Branca" },
  { nome: "PEDRO JOAO", completo: "EMEI/EMEF Pedro João de Oliveira — Tabatinga" },
  { nome: "SAMMARCO SERRA", completo: "EMEFEBS Prof. Ricardo Luques Sammarco Serra — Praia das Palmeiras" },
  { nome: "YASUTADA NASU", completo: "EMEI/EMEF Prof. Yasutada Nasu — Perequê-Mirim" },
];

export default function Escolas() {
  const { usuario, recarregarEscolas } = useApp();
  const [escolas, setEscolas] = useState<Escola[] | null>(null);
  const [erroLista, setErroLista] = useState(false);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const [novo, setNovo] = useState(false);
  const [nome, setNome] = useState("");
  const [renomear, setRenomear] = useState<Escola | null>(null);
  const [confirmarRede, setConfirmarRede] = useState(false);

  const carregar = useCallback(() => {
    // Inclui as inativas: sem isso, uma escola desativada sumiria da tela
    // sem caminho de volta.
    api<Escola[]>("/escolas?incluir_inativas=true")
      .then((lista) => { setEscolas(lista); setErroLista(false); })
      .catch(() => { setEscolas([]); setErroLista(true); });
  }, []);
  useEffect(carregar, [carregar]);

  if (!usuario?.is_global) {
    return <Vazio titulo="Somente o administrador global"
                  descricao="A gestão de escolas é exclusiva da conta global da rede." />;
  }

  // Uma escola da rede conta como existente se TODOS os tokens do nome curto
  // aparecem em alguma escola cadastrada — renomear "ORTEGA" para
  // "CARLOS ALTERO ORTEGA" não pode fazer o botão oferecer criá-la de novo.
  const nomesExistentes = (escolas ?? []).map((e) =>
    new Set(normalizar(e.nome).split(" ").filter(Boolean)));
  const jaExiste = (curto: string) => {
    const tokens = normalizar(curto).split(" ").filter(Boolean);
    return nomesExistentes.some((nome) => tokens.every((t) => nome.has(t)));
  };
  // Só oferece o botão com a lista CARREGADA: com o GET falhando, a tela
  // pareceria vazia e um clique criaria a rede inteira em duplicata.
  const carregou = escolas !== null && !erroLista;
  const faltantes = carregou ? REDE_CARAGUA.filter((e) => !jaExiste(e.nome)) : [];

  async function criar(dados: { nome: string }) {
    return api<Escola>("/escolas", {
      method: "POST",
      body: JSON.stringify({ nome: dados.nome, cidade: "Caraguatatuba", estado: "SP" }),
    });
  }

  async function criarUma() {
    if (nome.trim().length < 2) return;
    setOcupado(true);
    try {
      await criar({ nome: nome.trim() });
      setMensagem({ tipo: "ok", texto: `Escola “${nome.trim()}” criada.` });
      setNovo(false);
      setNome("");
      carregar();
      recarregarEscolas?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível criar." });
    } finally {
      setOcupado(false);
    }
  }

  async function criarRede() {
    setOcupado(true);
    let criadas = 0;
    let falhas = 0;
    for (const escola of faltantes) {
      try {
        await criar(escola);
        criadas += 1;
      } catch {
        falhas += 1;
      }
    }
    setMensagem({
      tipo: falhas ? "erro" : "ok",
      texto: `${criadas} escola(s) da rede criadas` + (falhas ? `; ${falhas} falharam.` : "."),
    });
    setConfirmarRede(false);
    setOcupado(false);
    carregar();
    recarregarEscolas?.();
  }

  async function alternarStatus(escola: Escola) {
    setOcupado(true);
    try {
      const novoStatus = escola.status === "ativa" ? "inativa" : "ativa";
      await api(`/escolas/${escola.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: novoStatus }),
      });
      setMensagem({ tipo: "ok", texto: `Escola ${novoStatus === "ativa" ? "reativada" : "desativada"}.` });
      carregar();
      recarregarEscolas?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível alterar." });
    } finally {
      setOcupado(false);
    }
  }

  async function salvarNome() {
    if (!renomear || nome.trim().length < 2) return;
    setOcupado(true);
    try {
      await api(`/escolas/${renomear.id}`, {
        method: "PATCH",
        body: JSON.stringify({ nome: nome.trim() }),
      });
      setMensagem({ tipo: "ok", texto: "Escola renomeada." });
      setRenomear(null);
      carregar();
      recarregarEscolas?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível renomear." });
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div>
      <PageHeader
        titulo="Escolas"
        descricao="Todas as escolas da rede. Troque de escola a qualquer momento pelo seletor no topo da tela."
        acoes={
          <div className="flex flex-wrap gap-2">
            {faltantes.length > 0 && (
              <Botao variante="neutro" onClick={() => setConfirmarRede(true)}>
                <School size={15} /> Adicionar rede de Caraguatatuba ({faltantes.length})
              </Botao>
            )}
            <Botao onClick={() => { setNome(""); setNovo(true); }}>
              <Building2 size={15} /> Nova escola
            </Botao>
          </div>
        }
      />

      {mensagem && (
        <div className="mb-4">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}

      <Card>
        {escolas === null ? (
          <Carregando />
        ) : erroLista ? (
          <Vazio titulo="Não foi possível carregar as escolas"
                 descricao="Verifique a conexão e recarregue a página." />
        ) : escolas.length === 0 ? (
          <Vazio titulo="Nenhuma escola" descricao="Crie a primeira escola da rede." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Nome</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Cidade</th>
                  <th className="px-4 py-2 font-medium">Ano letivo</th>
                  <th className="px-4 py-2 font-medium">Situação</th>
                  <th className="w-12 px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {escolas.map((escola) => (
                  <tr key={escola.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5 font-medium">{escola.nome}</td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {escola.cidade ?? "—"}{escola.estado ? ` / ${escola.estado}` : ""}
                    </td>
                    <td className="px-4 py-2.5">{escola.ano_letivo_ativo}</td>
                    <td className="px-4 py-2.5">
                      <Badge tom={escola.status === "ativa" ? "ok" : "neutro"}>{escola.status}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        aria-label={`Renomear ${escola.nome}`}
                        className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                        onClick={() => { setNome(escola.nome); setRenomear(escola); }}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        aria-label={escola.status === "ativa" ? `Desativar ${escola.nome}` : `Reativar ${escola.nome}`}
                        title={escola.status === "ativa" ? "Desativar" : "Reativar"}
                        className="ml-1 rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                        onClick={() => alternarStatus(escola)}
                      >
                        <Power size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* --- Nova escola --- */}
      <Modal titulo="Nova escola" aberto={novo} aoFechar={() => setNovo(false)}>
        <div className="space-y-3">
          <Campo rotulo="Nome da escola">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="neutro" onClick={() => setNovo(false)} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado || nome.trim().length < 2} onClick={criarUma}>
              {ocupado ? "Criando..." : "Criar escola"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Renomear --- */}
      <Modal titulo={`Renomear ${renomear?.nome ?? ""}`} aberto={renomear !== null} aoFechar={() => setRenomear(null)}>
        <div className="space-y-3">
          <Campo rotulo="Novo nome">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="neutro" onClick={() => setRenomear(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado || nome.trim().length < 2} onClick={salvarNome}>
              {ocupado ? "Salvando..." : "Salvar"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Adicionar a rede municipal --- */}
      <Modal titulo="Adicionar a rede de Caraguatatuba" aberto={confirmarRede} aoFechar={() => setConfirmarRede(false)}>
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Serão criadas <strong>{faltantes.length}</strong> escolas da rede municipal com
          ensino fundamental do 1º ao 5º ano (nomes curtos — renomeie as que quiser depois):
        </p>
        <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto text-sm">
          {faltantes.map((escola) => (
            <li key={escola.nome} className="flex flex-col rounded-md bg-zinc-50 px-3 py-1.5 dark:bg-zinc-800/60">
              <span className="font-medium">{escola.nome}</span>
              <span className="text-xs text-zinc-500 dark:text-zinc-400">{escola.completo}</span>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex justify-end gap-2">
          <Botao variante="neutro" onClick={() => setConfirmarRede(false)} disabled={ocupado}>Cancelar</Botao>
          <Botao disabled={ocupado || faltantes.length === 0} onClick={criarRede}>
            <School size={15} /> {ocupado ? "Criando..." : `Criar ${faltantes.length} escolas`}
          </Botao>
        </div>
      </Modal>
    </div>
  );
}
