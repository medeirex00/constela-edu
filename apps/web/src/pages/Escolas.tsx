/**
 * Escolas (administrador GLOBAL): todas as escolas da rede num lugar só —
 * criar, renomear e adicionar de uma vez a rede municipal de Caraguatatuba
 * (unidades com 1º ao 5º ano). Os nomes vêm curtos (ex.: "DEBORA PILON");
 * é só renomear os que não agradarem.
 */
import { Building2, CheckCircle2, PauseCircle, Pencil, Power, School, Search, UserCog } from "lucide-react";
import { useState } from "react";

import { TabelaRolavel } from "../components/TabelaRolavel";
import UsuariosDaEscola from "../components/UsuariosDaEscola";
import {
  Botao,
  Campo,
  Card,
  Carregando,
  Chip,
  Confirmacao,
  Erro,
  IconePastel,
  Mensagem,
  Modal,
  PageHeader,
  StatCard,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
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
  // Inclui as inativas: sem isso, uma escola desativada sumiria da tela
  // sem caminho de volta.
  const {
    dados: escolas,
    erro: erroLista,
    carregando,
    recarregar: carregar,
  } = useApi<Escola[]>("/escolas?incluir_inativas=true");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const [novo, setNovo] = useState(false);
  const [nome, setNome] = useState("");
  const [renomear, setRenomear] = useState<Escola | null>(null);
  const [confirmarRede, setConfirmarRede] = useState(false);
  // Desativar pede confirmação (a escola some das listas e o telão para de abrir);
  // reativar não. `alternandoId` marca a linha cuja (des)ativação está rodando.
  const [paraDesativar, setParaDesativar] = useState<Escola | null>(null);
  const [alternandoId, setAlternandoId] = useState<number | null>(null);
  // Escola "aberta": mostra a seção Usuários dela logo abaixo da lista. NÃO
  // depende de turmas, alunos, Lista Piloto ou integrações — é justamente o
  // caminho para criar o primeiro coordenador de uma escola recém-cadastrada.
  const [escolaAberta, setEscolaAberta] = useState<Escola | null>(null);
  // Busca só filtra o que se VÊ: a checagem da rede (faltantes) usa a lista inteira.
  const [busca, setBusca] = useState("");

  if (!usuario?.is_global) {
    return (
      <div>
        <PageHeader titulo="Escolas" />
        <Card>
          <Vazio icone={Building2} titulo="Somente o administrador global"
                 descricao="A gestão de escolas é exclusiva da conta global da rede." />
        </Card>
      </div>
    );
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
      const criada = await criar({ nome: nome.trim() });
      setMensagem({
        tipo: "ok",
        texto: `Escola “${nome.trim()}” criada. Agora adicione o primeiro usuário (coordenador ou diretor) na seção abaixo.`,
      });
      setNovo(false);
      setNome("");
      setEscolaAberta(criada);   // passo 2 do onboarding: criar o coordenador
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
    setAlternandoId(escola.id);
    try {
      const novoStatus = escola.status === "ativa" ? "inativa" : "ativa";
      await api(`/escolas/${escola.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: novoStatus }),
      });
      setMensagem({ tipo: "ok", texto: `Escola ${novoStatus === "ativa" ? "reativada" : "desativada"}.` });
      // Desativou a escola aberta: fecha a seção de usuários dela.
      if (novoStatus === "inativa" && escolaAberta?.id === escola.id) setEscolaAberta(null);
      carregar();
      recarregarEscolas?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível alterar." });
    } finally {
      setOcupado(false);
      setAlternandoId(null);
    }
  }

  async function confirmarDesativacao() {
    if (!paraDesativar) return;
    await alternarStatus(paraDesativar);
    setParaDesativar(null);
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

  const lista = escolas ?? [];
  const ativas = lista.filter((e) => e.status === "ativa").length;
  const alvoBusca = normalizar(busca.trim());
  const visiveis = alvoBusca ? lista.filter((e) => normalizar(e.nome).includes(alvoBusca)) : lista;
  // Celular (< 640 px): células mais justas; botões da linha com 40 px (alvo de toque).
  const th = `${classesTabela.th} max-sm:px-3`;
  const td = "px-4 py-3 max-sm:px-3";
  const botaoCelular = "max-sm:h-10 max-sm:w-10 max-sm:justify-center max-sm:p-0";

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Escolas"
        // Na v2 o seletor saiu do topo: é o cartão "Escola" no fim do menu lateral
        // (abaixo da largura da barra fixa, dentro do menu que abre pelo botão ☰).
        descricao="Todas as escolas da rede. Troque de escola a qualquer momento pelo cartão “Escola”, no fim do menu lateral."
        acoes={
          <>
            {faltantes.length > 0 && (
              <Botao variante="secundario" onClick={() => setConfirmarRede(true)}>
                <School size={15} aria-hidden /> Adicionar rede de Caraguatatuba ({faltantes.length})
              </Botao>
            )}
            <Botao onClick={() => { setNome(""); setNovo(true); }}>
              <Building2 size={15} aria-hidden /> Nova escola
            </Botao>
          </>
        }
      />

      {/* Contadores reais da lista carregada (inclui as inativas). */}
      {carregou && lista.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2">
          <StatCard icone={<Building2 size={20} />} tom="violeta" rotulo="Escolas cadastradas" valor={String(lista.length)} detalhe="ativas e inativas" />
          <StatCard icone={<CheckCircle2 size={20} />} tom="verde" rotulo="Em funcionamento" valor={String(ativas)} detalhe="situação ativa" />
          <StatCard icone={<PauseCircle size={20} />} tom="neutro" rotulo="Desativadas" valor={String(lista.length - ativas)} detalhe="podem ser reativadas" />
        </div>
      )}

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}

      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
            <IconePastel icone={School} tom="violeta" tamanho="sm" />
            Escolas da rede
          </h2>
          {carregou && lista.length > 0 && (
            <div className="relative w-full sm:ml-auto sm:w-64">
              <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                aria-label="Buscar escola"
                className={`${estiloInput} pl-9`}
                placeholder="Buscar escola…"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
            </div>
          )}
        </div>
        {carregando ? (
          <Carregando />
        ) : erroLista ? (
          <Erro titulo="Não foi possível carregar as escolas" descricao={erroLista.message} aoTentar={carregar} />
        ) : !escolas || escolas.length === 0 ? (
          <Vazio icone={Building2} titulo="Nenhuma escola" descricao="Crie a primeira escola da rede." />
        ) : visiveis.length === 0 ? (
          <Vazio icone={Search} titulo="Nenhuma escola encontrada" descricao="Nenhum nome corresponde à busca." />
        ) : (
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela, e as ações (Usuários, Renomear, Desativar) ficam presas à
          // direita (`presa-celular`). O ícone decorativo some no celular para dar espaço
          // ao nome; cidade, ano letivo e situação vêm com a rolagem.
          <TabelaRolavel rotulo="Escolas da rede: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th scope="col" className={th}>Nome</th>
                  <th scope="col" className={th}>Cidade</th>
                  <th scope="col" className={th}>Ano letivo</th>
                  <th scope="col" className={th}>Situação</th>
                  <th scope="col" className={`${th} presa-celular`}><span className="sr-only">Ações</span></th>
                </tr>
              </thead>
              <tbody>
                {visiveis.map((escola) => {
                  const ativa = escola.status === "ativa";
                  const aberta = escolaAberta?.id === escola.id;
                  const alternando = alternandoId === escola.id;
                  return (
                    <tr key={escola.id} className={classesTabela.tr}>
                      <td className={td}>
                        <div className="flex items-center gap-3">
                          <IconePastel icone={Building2} tom={ativa ? "violeta" : "neutro"} tamanho="sm" className="hidden sm:grid" />
                          {/* Celular: base de 8,5rem — o nome quebra em poucas linhas, não uma
                              palavra por linha. */}
                          <span className="font-semibold text-zinc-900 max-sm:min-w-[8.5rem] dark:text-zinc-100">{escola.nome}</span>
                        </div>
                      </td>
                      <td className={td}>
                        {escola.cidade
                          ? <Chip>{escola.cidade}{escola.estado ? ` / ${escola.estado}` : ""}</Chip>
                          : <span className="text-zinc-500">—</span>}
                      </td>
                      <td className={`${td} tabular-nums text-zinc-700 dark:text-zinc-200`}>{escola.ano_letivo_ativo}</td>
                      <td className={td}>
                        {/* Rótulo humano (antes, o enum cru "ativa"/"inativa"). */}
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
                          ativa
                            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                            : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"}`}>
                          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${ativa ? "bg-emerald-500" : "bg-zinc-400"}`} />
                          {ativa ? "Ativa" : "Inativa"}
                        </span>
                      </td>
                      <td className="presa-celular px-4 py-3 max-sm:px-1.5">
                        {/* Abaixo de 1024 px os botões ficam só com o ícone (o nome completo
                            continua no aria-label e no title): com o texto, a tabela passava
                            da borda do cartão e o "Desativar" aparecia cortado. Nada sai. */}
                        <div className="flex items-center justify-end gap-1 whitespace-nowrap max-sm:gap-0.5">
                          <button
                            type="button"
                            aria-label={`Usuários de ${escola.nome}`}
                            title="Usuários"
                            aria-pressed={aberta}
                            disabled={ocupado}
                            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${botaoCelular} ${
                              aberta
                                ? "bg-indigo-600 text-white shadow-pilula"
                                : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
                            }`}
                            onClick={() => setEscolaAberta(aberta ? null : escola)}
                          >
                            <UserCog size={15} aria-hidden /> <span className="sr-only lg:not-sr-only">Usuários</span>
                          </button>
                          <button
                            type="button"
                            aria-label={`Renomear ${escola.nome}`}
                            title="Renomear"
                            disabled={ocupado}
                            className={`rounded-lg p-2 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 disabled:opacity-50 max-sm:inline-flex max-sm:items-center ${botaoCelular} dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100`}
                            onClick={() => { setNome(escola.nome); setRenomear(escola); }}
                          >
                            <Pencil size={15} aria-hidden />
                          </button>
                          <button
                            type="button"
                            aria-label={ativa ? `Desativar ${escola.nome}` : `Reativar ${escola.nome}`}
                            title={ativa ? "Desativar a escola" : "Reativar a escola"}
                            disabled={ocupado}
                            aria-busy={alternando}
                            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${botaoCelular} ${
                              ativa
                                ? "text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-500/10"
                                : "text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-500/10"}`}
                            onClick={() => (ativa ? setParaDesativar(escola) : void alternarStatus(escola))}
                          >
                            <Power size={14} aria-hidden />{" "}
                            <span className="sr-only lg:not-sr-only">
                              {alternando
                                ? (ativa ? "Desativando..." : "Reativando...")
                                : (ativa ? "Desativar" : "Reativar")}
                            </span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>

      {/* --- Usuários da escola aberta (antes de turmas/alunos/Lista Piloto) --- */}
      {escolaAberta && (
        <UsuariosDaEscola
          escola={escolas?.find((e) => e.id === escolaAberta.id) ?? escolaAberta}
          aoFechar={() => setEscolaAberta(null)}
        />
      )}

      {/* --- Nova escola --- */}
      <Modal titulo="Nova escola" aberto={novo} aoFechar={() => setNovo(false)}>
        <div className="space-y-4">
          <Campo rotulo="Nome da escola">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <div className="flex justify-end gap-2.5 pt-1">
            <Botao variante="secundario" onClick={() => setNovo(false)} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado || nome.trim().length < 2} onClick={criarUma}>
              {ocupado ? "Criando..." : "Criar escola"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Renomear --- */}
      <Modal titulo={`Renomear ${renomear?.nome ?? ""}`} aberto={renomear !== null} aoFechar={() => setRenomear(null)}>
        <div className="space-y-4">
          <Campo rotulo="Novo nome">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <div className="flex justify-end gap-2.5 pt-1">
            <Botao variante="secundario" onClick={() => setRenomear(null)} disabled={ocupado}>Cancelar</Botao>
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
        <ul className="mt-3 max-h-64 space-y-1.5 overflow-y-auto text-sm">
          {faltantes.map((escola) => (
            <li key={escola.nome} className="flex flex-col rounded-xl bg-zinc-50 px-3 py-2 dark:bg-zinc-800/60">
              <span className="font-semibold">{escola.nome}</span>
              <span className="text-xs text-zinc-500 dark:text-zinc-400">{escola.completo}</span>
            </li>
          ))}
        </ul>
        <div className="mt-5 flex justify-end gap-2.5">
          <Botao variante="secundario" onClick={() => setConfirmarRede(false)} disabled={ocupado}>Cancelar</Botao>
          <Botao disabled={ocupado || faltantes.length === 0} onClick={criarRede}>
            <School size={15} aria-hidden /> {ocupado ? "Criando..." : `Criar ${faltantes.length} escolas`}
          </Botao>
        </div>
      </Modal>

      {/* --- Desativar uma escola (reativar não pede confirmação) --- */}
      <Confirmacao
        titulo="Desativar a escola?"
        aberto={paraDesativar !== null}
        aoFechar={() => setParaDesativar(null)}
        aoConfirmar={() => void confirmarDesativacao()}
        rotuloConfirmar={ocupado ? "Desativando..." : "Desativar escola"}
        variante="perigo"
        ocupado={ocupado}
      >
        {paraDesativar && (
          <>
            <p>
              <strong className="text-zinc-800 dark:text-zinc-100">{paraDesativar.nome}</strong> deixa
              de aparecer no seletor de escolas e na vitrine pública da rede, e o telão dela
              (Painel Público) para de abrir.
            </p>
            <p>
              Nenhum dado é apagado e a escola pode ser reativada aqui mesmo. Desativar a escola
              não bloqueia o acesso de quem já tem conta nela: para isso, desative os usuários
              dela em “Usuários”.
            </p>
          </>
        )}
      </Confirmacao>
    </div>
  );
}
