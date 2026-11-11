/**
 * Chamadas da API do Quest. Reusa o cliente do @constela/core (base da API,
 * armazenamento de token e reação a 401 são adaptadores injetados pelo app
 * via configurarApi — ver packages/core/src/cliente.ts).
 */
import { api, ApiError, baseDaApi, obterToken } from "@constela/core";

import type {
  AcessoAluno,
  Avatar,
  ConferirResultado,
  ConquistasDoAluno,
  MissaoJogavel,
  MissaoResumo,
  MundoResumo,
  PerfilQuest,
  PersonagemBase,
  Preferencias,
  Quem,
  RespostaEnvio,
  Resultado,
  SessaoQuest,
} from "./tipos";

/** Erro de rede (fetch rejeitou: sem conexão/DNS) — diferente de resposta
 * HTTP de erro. Permite ao app distinguir "Wi-Fi caiu" de "código errado". */
export class ErroDeRede extends Error {
  constructor() {
    super("Sem conexão. Verifique a internet e tente de novo!");
  }
}

export function ehErroDeAutenticacao(erro: unknown): boolean {
  return erro instanceof ApiError && (erro.status === 401 || erro.status === 403);
}

// ---------------------------------------------------------------------------
// Entrada da criança (rotas públicas — sem token)
// ---------------------------------------------------------------------------

async function publica<T>(caminho: string, corpo: unknown): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${baseDaApi()}${caminho}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
  } catch {
    throw new ErroDeRede();
  }
  if (!resposta.ok) {
    throw new ApiError(resposta.status, await detalheDoErro(resposta, "Algo deu errado. Tente de novo!"));
  }
  return resposta.json() as Promise<T>;
}

/** A mensagem que a API mandou (`detail` em texto), ou `padrao` (corpo não-JSON, outro
 *  formato). */
async function detalheDoErro(resposta: Response, padrao: string): Promise<string> {
  try {
    const json = await resposta.json();
    if (typeof json?.detail === "string" && json.detail.trim()) return json.detail;
  } catch {
    /* corpo não-JSON */
  }
  return padrao;
}

/** Etapa 1 do login: "É você?" */
export function quemE(codigo: string): Promise<Quem> {
  return publica<Quem>("/quest/auth/quem", { codigo });
}

/** Etapa 2: entrar — o código é a credencial (sem senha). */
export function entrar(codigo: string): Promise<SessaoQuest> {
  return publica<SessaoQuest>("/quest/auth/entrar", { codigo });
}

/** Login por QR (o token vem na URL do cartão). */
export function entrarPorQr(qrToken: string): Promise<SessaoQuest> {
  return publica<SessaoQuest>("/quest/auth/entrar-qr", { qr_token: qrToken });
}

// ---------------------------------------------------------------------------
// Perfil do astronauta (rotas autenticadas — papel aluno)
// ---------------------------------------------------------------------------

export function meuPerfil(): Promise<PerfilQuest> {
  return api<PerfilQuest>("/quest/perfil");
}

/** Conquistas de aprendizado do PRÓPRIO aluno. O backend resolve o aluno pela
 *  SESSÃO (nunca por id do cliente) e é a fonte da verdade — o app só lê. */
export function minhasConquistas(): Promise<ConquistasDoAluno> {
  return api<ConquistasDoAluno>("/quest/conquistas");
}

export function coresDoTraje(): Promise<string[]> {
  return api<string[]>("/quest/perfil/cores");
}

/** Catálogo do vestiário: opções válidas por slot. */
export function catalogoAparencia(): Promise<Record<string, string[]>> {
  return api<Record<string, string[]>>("/quest/perfil/aparencia");
}

/** Os 6 personagens-base (presets gratuitos). */
export function personagensBase(): Promise<Record<string, PersonagemBase>> {
  return api<Record<string, PersonagemBase>>("/quest/perfil/personagens");
}

/**
 * Equipa um ou mais slots do avatar. Aceita QUALQUER slot de `Avatar`
 * (pele, cabelo, top, baixo, chapéu, costas, aura, pet, veículo…) — o
 * antigo `Pick` só admitia 4 slots (e citava `rosto`, que nem existe mais
 * no tipo), rejeitando no compilador trocas que o backend aceita.
 */
export function trocarAvatar(mudancas: Partial<Avatar>): Promise<PerfilQuest> {
  return api<PerfilQuest>("/quest/perfil/avatar", {
    method: "PATCH",
    body: JSON.stringify(mudancas),
  });
}

/** Cerimônia da primeira vez: como a criança quer ser chamada. */
export function escolherNome(nome: string): Promise<PerfilQuest> {
  return api<PerfilQuest>("/quest/perfil/nome", {
    method: "PATCH",
    body: JSON.stringify({ nome }),
  });
}

export function trocarCorDoTraje(cor: string): Promise<PerfilQuest> {
  return api<PerfilQuest>("/quest/perfil/avatar", {
    method: "PATCH",
    body: JSON.stringify({ cor }),
  });
}

export function trocarPreferencias(
  mudancas: Preferencias,
): Promise<PerfilQuest> {
  return api<PerfilQuest>("/quest/perfil/preferencias", {
    method: "PATCH",
    body: JSON.stringify(mudancas),
  });
}

// ---------------------------------------------------------------------------
// Jogo — loop jogável (rotas autenticadas — papel aluno)
// ---------------------------------------------------------------------------

/** Matérias (planetas) com conteúdo para a série do aluno, com progresso. */
export function mundosDisponiveis(): Promise<MundoResumo[]> {
  return api<MundoResumo[]>("/quest/jogar/mundos");
}

/** Trilho de missões publicadas do planeta, para a série do aluno. */
export function missoesDoPlaneta(mundoSlug: string): Promise<MissaoResumo[]> {
  return api<MissaoResumo[]>(`/quest/jogar/mundos/${mundoSlug}/missoes`);
}

/** Feedback imediato de uma questão (acerto/erro + explicação). Não pontua. */
export function conferirResposta(
  desafioId: number,
  resposta: string,
): Promise<ConferirResultado> {
  return api<ConferirResultado>("/quest/jogar/conferir", {
    method: "POST",
    body: JSON.stringify({ desafio_id: desafioId, resposta }),
  });
}

/** Abre a missão: as questões SEM gabarito. */
export function abrirMissao(missaoId: number): Promise<MissaoJogavel> {
  return api<MissaoJogavel>(`/quest/jogar/missoes/${missaoId}`);
}

/** Envia as respostas; o servidor corrige e devolve XP/estrela + perfil novo. */
export function responderMissao(
  missaoId: number,
  respostas: RespostaEnvio[],
  tempoSeg?: number,
): Promise<Resultado> {
  return api<Resultado>("/quest/jogar/tentativas", {
    method: "POST",
    body: JSON.stringify({
      missao_id: missaoId,
      respostas,
      tempo_seg: tempoSeg,
    }),
  });
}

// ---------------------------------------------------------------------------
// Professor (consumido pelo Edu web)
// ---------------------------------------------------------------------------

export function acessosDaTurma(
  escolaId: number,
  turmaId: number,
): Promise<AcessoAluno[]> {
  return api<AcessoAluno[]>(
    `/escolas/${escolaId}/quest/turmas/${turmaId}/acessos`,
  );
}

/** O PDF de cartões do Quest. `revogado`: a API só revogou o cartão (204, ficha inativa:
 *  sem cartão novo) e `blob` é `null` — a tela não depende do tamanho do arquivo. */
export interface PdfDoQuest {
  blob: Blob | null;
  nomeArquivo: string;
  revogado: boolean;
}

async function baixarPdf(caminho: string, nomePadrao: string): Promise<PdfDoQuest> {
  const token = await obterToken();
  let resposta: Response;
  try {
    resposta = await fetch(`${baseDaApi()}${caminho}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    // Falha de rede: pt-BR para o professor, nunca o "Failed to fetch" cru.
    throw new ErroDeRede();
  }
  if (!resposta.ok) {
    // A mensagem da API (ex.: módulo fora do plano, aluno de outra turma), não só a
    // genérica — o professor precisa saber o porquê.
    throw new ApiError(resposta.status, await detalheDoErro(resposta, "Não foi possível gerar o PDF."));
  }
  if (resposta.status === 204) return { blob: null, nomeArquivo: nomePadrao, revogado: true };
  const disposicao = resposta.headers.get("Content-Disposition") ?? "";
  const nomeArquivo =
    /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? nomePadrao;
  return { blob: await resposta.blob(), nomeArquivo, revogado: false };
}

/** Gera as credenciais da turma e baixa o PDF dos cartões (+ página do
 * professor com a tabela nome → código). */
export function baixarCartoesDaTurma(
  escolaId: number,
  turmaId: number,
  regenerar = false,
): Promise<PdfDoQuest> {
  return baixarPdf(
    `/escolas/${escolaId}/quest/turmas/${turmaId}/cartoes?regenerar=${regenerar}`,
    "cartoes-quest.pdf",
  );
}

/** Cartão de UM aluno (perdeu o cartão → não derruba a turma inteira). */
export function baixarCartaoDoAluno(
  escolaId: number,
  alunoId: number,
  regenerar = false,
): Promise<PdfDoQuest> {
  return baixarPdf(
    `/escolas/${escolaId}/quest/alunos/${alunoId}/cartao?regenerar=${regenerar}`,
    "cartao-quest.pdf",
  );
}
