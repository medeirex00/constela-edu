/**
 * Chamadas da API do Quest. Reusa o cliente do @constela/core (base da API,
 * armazenamento de token e reação a 401 são adaptadores injetados pelo app
 * via configurarApi — ver packages/core/src/cliente.ts).
 */
import { api, ApiError, baseDaApi, obterToken } from "@constela/core";

import type {
  AcessoAluno,
  Aparencia,
  Avatar,
  PerfilQuest,
  Preferencias,
  Quem,
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
    let detalhe = "Algo deu errado. Tente de novo!";
    try {
      const json = await resposta.json();
      if (typeof json.detail === "string") detalhe = json.detail;
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(resposta.status, detalhe);
  }
  return resposta.json() as Promise<T>;
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

export function coresDoTraje(): Promise<string[]> {
  return api<string[]>("/quest/perfil/cores");
}

/** Catálogo do vestiário: opções válidas por slot. */
export function catalogoAparencia(): Promise<Aparencia> {
  return api<Aparencia>("/quest/perfil/aparencia");
}

/** Equipa um ou mais slots do avatar (cor, rosto, chapéu, veículo). */
export function trocarAvatar(
  mudancas: Partial<Pick<Avatar, "cor" | "rosto" | "chapeu" | "veiculo">>,
): Promise<PerfilQuest> {
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

async function baixarPdf(caminho: string, nomePadrao: string) {
  const token = await obterToken();
  const resposta = await fetch(`${baseDaApi()}${caminho}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resposta.ok) {
    throw new ApiError(resposta.status, "Não foi possível gerar o PDF.");
  }
  const disposicao = resposta.headers.get("Content-Disposition") ?? "";
  const nomeArquivo =
    /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? nomePadrao;
  return { blob: await resposta.blob(), nomeArquivo };
}

/** Gera as credenciais da turma e baixa o PDF dos cartões (+ página do
 * professor com a tabela nome → código). */
export function baixarCartoesDaTurma(
  escolaId: number,
  turmaId: number,
  regenerar = false,
): Promise<{ blob: Blob; nomeArquivo: string }> {
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
): Promise<{ blob: Blob; nomeArquivo: string }> {
  return baixarPdf(
    `/escolas/${escolaId}/quest/alunos/${alunoId}/cartao?regenerar=${regenerar}`,
    "cartao-quest.pdf",
  );
}
