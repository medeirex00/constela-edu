/**
 * Dados INVENTADOS para os testes de responsividade das telas públicas.
 *
 * Nada aqui é real: nomes de escola fictícios (40–55 caracteres, em maiúsculas e
 * com o prefixo comum "EMEI/EMEF PROF…" — o pior caso para distinguir escolas),
 * valores per capita de 1 a 4 dígitos com decimal ("1.234,5") e alunos com nome
 * já reduzido como o servidor manda por padrão ("Ana B."). O formato espelha os
 * payloads de GET /api/v1/publico/rede/{token} e GET /api/v1/publico/{token}/painel.
 */
import path from "node:path";

import type { Page, Route } from "@playwright/test";

/** Onde as capturas ficam (fora do repositório; test-results/ é ignorado). */
export const PASTA_CAPTURAS = process.env.CAPTURAS_PUBLICO
  || path.join(__dirname, "..", "test-results", "capturas-publico");

export interface Tela { largura: number; altura: number; movel?: boolean }

/** Larguras do contrato + zoom de 200% num notebook 1366×768 (= 683×384) + um
 *  celular grande deitado (932×430, fica no modo celular, não no modo TV) +
 *  projetor SVGA 800×600 e painel 854×480 (modo TV a partir de 800 px) +
 *  notebook 1440×900 + totens em retrato (1080×1920 e 4K 2160×3840). */
export const TELAS: Tela[] = [
  { largura: 320, altura: 568, movel: true },
  { largura: 375, altura: 812, movel: true },
  { largura: 667, altura: 375, movel: true },
  { largura: 844, altura: 390, movel: true },
  { largura: 932, altura: 430, movel: true },
  { largura: 683, altura: 384 },
  { largura: 768, altura: 1024, movel: true },
  { largura: 800, altura: 600 },
  { largura: 854, altura: 480 },
  { largura: 1024, altura: 768 },
  { largura: 1280, altura: 720 },
  { largura: 1366, altura: 768 },
  { largura: 1440, altura: 900 },
  { largura: 960, altura: 540 },
  { largura: 1920, altura: 1080 },
  { largura: 3840, altura: 2160 },
  { largura: 1080, altura: 1920 },
  { largura: 2160, altura: 3840 },
];

/** Resoluções de TV/projetor/totem em que a vitrine inteira (5 + 5) cabe sem rolar. */
export const TELAS_TV = new Set(["800x600", "854x480", "960x540", "1024x768", "1280x720", "1366x768",
  "1440x900", "1920x1080", "3840x2160", "1080x1920", "2160x3840"]);

/** TVs/projetores em que o telão da escola mostra CADA slide sem nada escondido
 *  na rolagem invisível do palco (a lista corta no que cabe, com a linha "+ N"). */
export const TELAS_TELAO_TV = new Set(["960x540", "1024x768", "1280x720", "1366x768", "1440x900",
  "1920x1080", "3840x2160"]);

/** Telão da escola: modo TV com ≥ 640 × 500 px (mesma condição de
 *  MEDIA_TELAO_TV no PainelPublico.tsx e no index.css). Fora dela — celular em
 *  pé ou deitado, e também 683×384 e 854×480 — o telão é página rolável. */
export const MEDIA_TELAO_TV = "(min-width: 640px) and (min-height: 500px)";
export const ehTelaoCelular = (t: Tela) => !(t.largura >= 640 && t.altura >= 500);

/** Celulares do contrato da página rolável do telão (em pé e deitados). */
export const TELAS_TELAO_CELULAR = new Set(["320x568", "375x812", "667x375", "844x390", "932x430"]);

export const nomeDaTela = (t: Tela) => `${t.largura}x${t.altura}`;

/** Modo TV da vitrine: paisagem ≥ 800 × 440 px (mesma media query do index.css). */
export const MEDIA_MODO_TV = "(orientation: landscape) and (min-width: 800px) and (min-height: 440px)";
export const ehModoTv = (t: Tela) => t.largura > t.altura && t.largura >= 800 && t.altura >= 440;

/** Totem da vitrine: retrato ≥ 1000 × 1500 px (mesma media query do index.css). */
export const MEDIA_TOTEM = "(orientation: portrait) and (min-width: 1000px) and (min-height: 1500px)";
export const ehTotem = (t: Tela) => t.altura > t.largura && t.largura >= 1000 && t.altura >= 1500;

export const VITRINE = {
  rede_nome: "Rede Municipal de Ensino de Vila Constelação do Sul",
  top_leitura: [
    { nome: "EMEI/EMEF PROFª ANASTÁCIA MIRANDA DE OLIVEIRA CAMPOS", valor: 12.4 },
    { nome: "EMEI/EMEF PROF. BALTAZAR QUINTINO DA SILVEIRA LUZ", valor: 9.85 },
    { nome: "EMEF PROFª CELESTINA ARAÚJO VALADARES DO NASCIMENTO", valor: 7.3 },
    { nome: "EMEI/EMEF PROF. DORIVAL ESTEVES MACHADO DE ANDRADE", valor: 3.1 },
    { nome: "ESCOLA MUNICIPAL ESTRELA GUIA DO BAIRRO JARDIM AURORA", valor: 1.5 },
  ],
  top_matematica: [
    { nome: "EMEF PROFª FLORIPES BITENCOURT GUIMARÃES DE SOUZA", valor: 1234.5 },
    { nome: "EMEI/EMEF PROFª ANASTÁCIA MIRANDA DE OLIVEIRA CAMPOS", valor: 987.6 },
    { nome: "EMEI/EMEF PROF. GERALDINO TAVARES ROCHA FILHO", valor: 456.25 },
    { nome: "EMEI/EMEF PROFª HORTÊNCIA LIMA BARROS DE ALBUQUERQUE", valor: 78.9 },
    { nome: "EMEF RECANTO DAS ACÁCIAS DO MORRO DO CRUZEIRO NOVO", valor: 6.5 },
  ],
  unidade_leitura: "livros por aluno",
  unidade_matematica: "estrelas por aluno",
};

const ALUNOS = ["Ana B.", "Bruno C.", "Carla D.", "Davi E.", "Elisa F.",
  "Fábio G.", "Gabriela H.", "Heitor I.", "Iara J.", "Joaquim K."];

export const PAINEL = {
  escola: { nome: "EMEI/EMEF PROFª ANASTÁCIA MIRANDA DE OLIVEIRA CAMPOS", cor_primaria: "#5B6EE1" },
  slides: ["ranking", "evolucao", "destaques", "mural"],
  // Intervalo longo: o carrossel não troca de slide no meio da medição.
  intervalo_s: 120,
  ranking: ALUNOS.map((nome, i) => ({
    posicao: i + 1, aluno_id: 900 + i, nome, turma: null, nota_geral: 98.5 - i * 7.25,
  })),
  evolucao: ALUNOS.map((nome, i) => ({
    posicao: i + 1, aluno_id: 900 + i, nome, turma: null, nota_evolucao: 31.5 - i * 2.5,
  })),
  destaques: {
    dia: { aluno_id: 901, nome: "Bruno C.", turma: null, nota_evolucao: 12.5,
      ganhos: { atividades: 41, estrelas: 120, livros: 3 } },
    semana: { aluno_id: 902, nome: "Carla D.", turma: null, nota_evolucao: 22.75,
      ganhos: { atividades: 87, estrelas: 230, livros: 5 } },
    mes: { aluno_id: 903, nome: "Davi E.", turma: null, nota_evolucao: 41.25,
      ganhos: { atividades: 312, estrelas: 901, livros: 11 } },
  },
  estatisticas: { alunos: 1234, atividades: 123456789, estrelas: 98765432, livros: 54321 },
  mural: ALUNOS.map((nome) => ({ icone: "🏅", texto: `${nome} desbloqueou “Leitor da Constelação”` })),
};

// Raiz real dos pacotes de fonte (resolve a junção do node_modules, se houver).
const PASTA_FONTSOURCE = path.dirname(path.dirname(require.resolve("@fontsource/poppins/package.json")));

/**
 * Toda chamada a /api/** sem simulação explícita responde 404 (nada sai da
 * máquina). E as fontes self-host (@fontsource) são entregues do disco: num
 * worktree cujo node_modules é junção para fora da raiz, o Vite recusa servi-las
 * (fs.allow) e a página cairia na fonte do sistema — medidas falsas.
 */
async function prepararPagina(page: Page) {
  await page.route((url) => url.pathname.startsWith("/api/"), (rota: Route) =>
    rota.fulfill({ status: 404, json: { detail: "não simulado no teste" } }));
  await page.route((url) => /\/@fontsource\/[\w-]+\/files\/[\w.-]+\.woff2?$/.test(url.pathname), (rota: Route) => {
    const caminho = decodeURIComponent(new URL(rota.request().url()).pathname);
    const relativo = caminho.slice(caminho.indexOf("@fontsource/") + "@fontsource/".length);
    return rota.fulfill({ path: path.join(PASTA_FONTSOURCE, relativo) });
  });
}

export async function simularVitrine(page: Page, corpo: unknown = VITRINE) {
  await prepararPagina(page);
  await page.route((url) => /^\/api\/v1\/publico\/rede\/[^/]+$/.test(url.pathname), (rota: Route) =>
    rota.fulfill({ json: corpo, headers: { "Cache-Control": "no-store" } }));
}

export async function simularPainel(page: Page, corpo: unknown = PAINEL) {
  await prepararPagina(page);
  await page.route((url) => /^\/api\/v1\/publico\/[^/]+\/painel$/.test(url.pathname), (rota: Route) =>
    rota.fulfill({ json: corpo, headers: { "Cache-Control": "no-store" } }));
}

/** Retângulos [esquerda, topo, direita, base] se cruzam (com folga de 0,5 px). */
export function cruzam(
  a: { left: number; top: number; right: number; bottom: number },
  b: { left: number; top: number; right: number; bottom: number },
): boolean {
  return a.left < b.right - 0.5 && b.left < a.right - 0.5
    && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
}
