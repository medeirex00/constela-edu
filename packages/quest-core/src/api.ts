/**
 * Chamadas da API do Quest. Reusa o cliente do @constela/core (base da API,
 * armazenamento de token e reação a 401 são adaptadores injetados pelo app
 * via configurarApi — ver packages/core/src/cliente.ts).
 */
import { api, ApiError, baseDaApi, obterToken } from "@constela/core";

import type {
  AcessoAluno,
  Figura,
  PerfilQuest,
  Preferencias,
  Quem,
  SessaoQuest,
} from "./tipos";

// ---------------------------------------------------------------------------
// Entrada da criança (rotas públicas — sem token)
// ---------------------------------------------------------------------------

async function publica<T>(caminho: string, corpo: unknown): Promise<T> {
  const resposta = await fetch(`${baseDaApi()}${caminho}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo),
  });
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

export function obterFiguras(): Promise<Figura[]> {
  return api<Figura[]>("/quest/auth/figuras");
}

/** Etapa 1 do login: "É você?" */
export function quemE(codigo: string): Promise<Quem> {
  return publica<Quem>("/quest/auth/quem", { codigo });
}

/** Etapa 2: código + as 4 figuras do PIN, em ordem. */
export function entrar(codigo: string, pin: string[]): Promise<SessaoQuest> {
  return publica<SessaoQuest>("/quest/auth/entrar", { codigo, pin });
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

/** Gera as credenciais da turma e baixa o PDF dos cartões (POST: é uma
 * escrita — o apiBlob do core cobre apenas GET). */
export async function baixarCartoesDaTurma(
  escolaId: number,
  turmaId: number,
  regenerar = false,
): Promise<{ blob: Blob; nomeArquivo: string }> {
  const token = await obterToken();
  const resposta = await fetch(
    `${baseDaApi()}/escolas/${escolaId}/quest/turmas/${turmaId}/cartoes` +
      `?regenerar=${regenerar}`,
    {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!resposta.ok) {
    throw new ApiError(resposta.status, "Não foi possível gerar os cartões.");
  }
  const disposicao = resposta.headers.get("Content-Disposition") ?? "";
  const nomeArquivo =
    /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? "cartoes-quest.pdf";
  return { blob: await resposta.blob(), nomeArquivo };
}
