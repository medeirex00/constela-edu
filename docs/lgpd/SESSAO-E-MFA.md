# Sessão do Edu (token no localStorage) e MFA para admin global e Secretaria — avaliação

Rodada de correção da auditoria de 20/10/2026, achado 5. **Só avaliação e plano**: nada
foi implementado, porque as duas mudanças alteram o login de todos os usuários
(decisão do dono). Estado descrito a partir do código do commit-base 5527983.

> **Atualização de 31/10/2026 (limitador do login):** o passo 1 do plano (§5) foi feito
> em parte — os tetos de falhas **por IP** e **global** do login do Edu passaram a ser
> persistentes, com a camada do Quest. Estado atual, configuração e o trade-off do
> teto global em §1.1. Cookie, CSP e MFA continuam só avaliação.

---

## 1. Como é hoje

- **Login:** `POST /api/v1/auth/login` (formulário OAuth2, e-mail ou @usuário + senha;
  bcrypt; limites por conta+IP e por conta em memória, por processo, e tetos de falhas
  por IP e global também no banco — ver §1.1) devolve um JWT
  HS256 assinado com `SECRET_KEY`, válido por **8 h** (`ACCESS_TOKEN_EXPIRE_MINUTES`), com
  `ver` = `usuarios.token_version` (trocar a senha derruba as sessões).
- **Onde o token fica:**
  - web e desktop (Tauri): `localStorage["sgpe_token"]` (`apps/web/src/lib/api.ts`);
  - celular: SecureStore (cifrado pelo sistema) — fora do escopo deste risco;
  - Quest (aluno): só em memória.
- **Como vai à API:** cabeçalho `Authorization: Bearer` em toda chamada
  (`packages/core/src/cliente.ts`). Sem cookie → não há CSRF hoje.
- **Topologia:** o web (`www.constelaedu.com`, Vercel) chama a API **direto** no domínio
  do Railway (`constelabackend-production.up.railway.app`, via `VITE_API_URL`): outro
  site (registrable domain diferente). Existe também `api.constelaedu.com` apontando
  para o mesmo serviço.
- **Defesas contra XSS já presentes:** CSP no Vercel com `script-src 'self'` (sem script
  inline nem de terceiros), React (escapa por padrão), `X-Content-Type-Options`,
  `X-Frame-Options`. Pontos fracos da CSP: `connect-src 'self' https:` (um script
  injetado pode mandar o token para qualquer host https) e `style-src 'unsafe-inline'`.
- **Sem MFA** para nenhum perfil. O admin global (`is_global`) vê todas as redes; a
  Secretaria (`rede_id` sem `is_global`) vê a rede inteira (agregados; o backend nega
  dado individual).

### 1.1 Limites de tentativas do login do Edu (atualizado em 31/10/2026)

| Limite | Padrão | Onde vive | Configurável |
|---|---|---|---|
| por (conta, IP) | 8 falhas em 5 min | memória, por processo | não |
| por conta | 20 falhas em 15 min | memória, por processo | não |
| falhas por IP, em qualquer conta (IPv6 pela rede /64) | 50 em 5 min | memória **e** banco: `quest_limites_acesso`, dimensão `edu_login_ip_falha` | `EDU_LOGIN_TETO_IP_FALHAS`, `EDU_LOGIN_TETO_IP_JANELA_S` |
| global (todos os IPs somados) | 400 em 5 min | memória **e** banco: dimensão `edu_login_global_falha` | `EDU_LOGIN_TETO_GLOBAL_FALHAS`, `EDU_LOGIN_TETO_GLOBAL_JANELA_S` |
| logins correndo ao mesmo tempo (desde 11/11/2026) | 8 por processo | memória, por processo (`portao_login`) | não |

- Os dois tetos persistentes valem entre os workers/réplicas e sobrevivem ao deploy; usam
  a tabela de limites do Quest (migração 0037) com dimensões próprias do Edu (prefixo
  `edu_login_`), e o IP só vai para o banco como HMAC. São conferidos **antes** de
  procurar a conta (a mesma resposta exista a conta ou não) e só **falhas** contam (o
  login certo não soma nem zera; o 429 não realimenta o contador).
- As variáveis são lidas no boot (mudar exige reiniciar o serviço); teto ≥ 1 e janela
  de 60 s a 1 h. Os limites por conta e por (conta, IP) seguem fixos e só em memória
  (zeram no restart e não valem entre réplicas).
- O teto por IP tem de ficar **abaixo** do global: com `EDU_LOGIN_TETO_IP_FALHAS` ≥
  `EDU_LOGIN_TETO_GLOBAL_FALHAS`, um IP só travaria o login de todos — o boot avisa em dev
  e recusa com `ENV=producao` (desde 01/11/2026).
- **Rajada de logins não para a API (desde 11/11/2026, auditoria G_CARGA-1).** Até então
  cada falha era contada no banco dentro da transação do login, e a linha do teto global
  (uma só para a API inteira) ficava presa por várias idas ao banco (~195 ms cada em
  produção): todas as falhas passavam em fila por ela, cada pedido esperando com uma
  thread e uma conexão do worker, e 240 logins errados — abaixo dos tetos — deixavam as
  sessões já abertas esperando até 75 s por requisição. Agora: (1) a falha é contada numa
  única instrução atômica, em AUTOCOMMIT e fora da transação do login, e a linha fica
  presa só durante essa instrução; (2) a instrução desiste da linha presa por outra
  transação depois de 0,5 s (`lock_timeout`) e a falha fica só na memória do processo,
  com um aviso no log (`limites.contagem_sem_trava`); (3) cada processo deixa correr no
  máximo **8 logins ao mesmo tempo**: quem chega com os 8 ocupados recebe na hora o 429
  "Muitas pessoas estão entrando ao mesmo tempo. Aguarde alguns segundos e tente
  novamente.", sem nenhuma ida ao banco (aviso no log `login.simultaneos_no_teto`, no
  máximo um por minuto). Com isso a rajada usa no máximo 8 das 40 threads e 8 das 30
  conexões de cada worker. O login por código do Quest conta as falhas do mesmo jeito
  (1) e (2); o portão (3) não vale para ele (ver o trade-off abaixo).

**Trade-off do teto global (aceito, o mesmo do login por código do Quest).** Ao chegar no
teto, o `/auth/login` responde 429 para **todas** as contas até o fim do bloqueio (uma
janela: 5 min no padrão) e sai um log de alerta (`login.limite_global_atingido`, sem IP
nem conta). Como o teto por IP para cada endereço em 50 falhas, bastam **poucos IPs** (no
padrão, 8 IPs — ou redes IPv6 /64 — com 50 falhas cada) para travar o login de todo mundo,
e o atacante pode repetir a cada janela: um bloqueio do login em blocos de 5 min. As
**sessões já abertas seguem válidas** (o JWT não passa pelo limitador): sente só quem
precisa entrar naquele intervalo. Se o uso real chegar perto do teto, ou diante de um
ataque desse tipo, o valor pode **subir em produção** pela variável
`EDU_LOGIN_TETO_GLOBAL_FALHAS` (reinício do serviço, sem mudar código) — ao custo de
deixar passar mais palpites distribuídos antes do corte.

**Trade-off do portão de logins simultâneos (11/11/2026).** Durante uma rajada, quem tenta
entrar também pode receber o 429 "Muitas pessoas estão entrando ao mesmo tempo" e precisa
tentar de novo em alguns segundos; as **sessões já abertas seguem sendo atendidas** (antes
da correção, elas também paravam). No uso real o portão não aparece: um login leva ~1–2 s
em produção e a equipe raramente tem mais de 8 entrando no mesmo instante em cada
processo. O login por código do Quest ficou **sem** portão: as crianças de uma turma
entram juntas no começo da aula, e um teto mal escolhido as mandaria esperar — decisão
pendente do dono. Sem ele, uma rajada contra o Quest ainda disputa as threads do worker
(as sessões abertas ficam mais lentas por alguns segundos), mas não volta à fila da linha
global.

## 2. Riscos

1. **XSS lê o token.** Qualquer script que rode na origem do web (dependência
   comprometida no build, falha de sanitização futura, extensão maliciosa do navegador)
   lê o `localStorage` e leva o token: o atacante usa a sessão de outro lugar por até
   8 h, sem a vítima perceber. Com a CSP atual a injeção é difícil, mas a exfiltração,
   uma vez dentro, é fácil (`connect-src https:`).
2. **Token não é revogável por sessão.** Só por `token_version` (derruba TODAS as sessões
   da conta) ou esperando expirar. Não há "sair de todos os aparelhos" seletivo nem lista
   de sessões.
3. **Conta privilegiada só com senha.** Um vazamento de senha do admin global ou de uma
   Secretaria (phishing, reuso de senha) dá acesso à rede inteira. Os limites de login
   por conta e por (conta, IP) são por processo (zeram no restart, não valem entre
   réplicas); desde 31/10/2026 os tetos de falhas por IP e global têm a camada
   persistente do Quest (§1.1), mas a trava de UMA conta específica segue só em memória.
4. **Computador compartilhado** (sala dos professores): o token sobrevive ao fechar a aba
   (`localStorage`) até expirar.

## 3. Alternativas

### 3.1 Sessão em cookie `HttpOnly` (o token deixa de ser legível por JavaScript)

- Cookie `HttpOnly; Secure; SameSite=Lax` (ou `Strict`), emitido pela API no login;
  o front para de guardar o token.
- **CSRF:** com cookie, o navegador manda a credencial sozinho. Mitigação: `SameSite=Lax`
  + token anti-CSRF (padrão "double submit": cookie legível `csrf` + cabeçalho
  `X-CSRF-Token` igual em todo método que muda estado) + checagem de `Origin`/`Referer`
  contra `CORS_ORIGINS`.
- **Pré-requisito de topologia:** com o web em `www.constelaedu.com` e a API em
  `*.up.railway.app`, o cookie é de **terceiro** — o Safari (ITP) bloqueia e o Chrome
  restringe. É preciso que o web chame a API no **mesmo site**: `api.constelaedu.com`
  (cookie `Domain=api.constelaedu.com`, `SameSite=Lax` funciona por ser o mesmo
  registrable domain) ou um proxy `/api/*` no Vercel para o Railway (primeira parte).
- **Impacto:** troca o `VITE_API_URL` do web; o CORS já está com `allow_credentials=True`
  e lista explícita de origens (`app/main.py`), e TEM de continuar sem curinga (com cookie,
  origem curinga abriria a sessão a qualquer site); o desktop Tauri (`tauri://localhost`, outra origem)
  e o celular continuam com Bearer (o backend aceita os dois durante a transição); todo
  mundo faz login de novo uma vez; testes de UI que leem o token do `localStorage` mudam.
- **Não resolve sozinho** o XSS: o script injetado ainda age **na** sessão enquanto a aba
  estiver aberta — só não consegue levar o token embora. Por isso a CSP mais estrita
  (abaixo) continua valendo.

### 3.2 Endurecer sem trocar o mecanismo (baixo impacto)

- CSP: `connect-src 'self' https://api.constelaedu.com https://constelabackend-production.up.railway.app`
  (e o que mais o web precisar, ex.: tiles do mapa só em `img-src`) — fecha a
  exfiltração para hosts arbitrários; remover `'unsafe-inline'` de `style-src` quando
  possível.
- `sessionStorage` no lugar de `localStorage` para perfis privilegiados: o token some ao
  fechar a aba (reduz o risco 4; não o 1).
- Sessão mais curta para admin global/Secretaria (ex.: 2 h) com renovação.
- Limitador de login persistente (mesmo desenho de `quest_limites_acesso`). Feito em
  31/10/2026 para os tetos de falhas por IP e global (§1.1); faltam os limites por conta
  e por (conta, IP).

### 3.3 MFA para admin global e Secretaria — TOTP

- **TOTP (RFC 6238)** — app autenticador (Google Authenticator, Microsoft Authenticator,
  Aegis). Sem custo, sem SMS (SIM swap), funciona offline. Dependência: `pyotp` (ou
  implementação própria de ~30 linhas sobre `hmac`), QR de cadastro (já há geração de QR
  no projeto).
- Dados: `usuarios.mfa_segredo_cifrado` (Fernet com `DATA_ENCRYPTION_KEY`, como os
  outros segredos em repouso), `mfa_ativado_em`, códigos de recuperação (só hash,
  uso único) e um contador anti-replay do último passo usado.
- Fluxo: login com senha → se o perfil exige MFA, a API devolve um token de **etapa**
  (curto, ~5 min, papel `mfa_pendente`, que nenhuma rota aceita) → `POST /auth/mfa` com
  o código de 6 dígitos → sessão normal. Limitador persistente na etapa do código.
- Recuperação: códigos de recuperação impressos no cadastro; reset do MFA de uma
  Secretaria só pelo admin global (auditado); do admin global, procedimento fora da
  aplicação (registrado).
- WebAuthn/passkeys é mais forte (resistente a phishing), mas exige mais trabalho de
  front e suporte a aparelhos da Prefeitura — boa segunda etapa.

## 4. Impacto no login dos usuários

| Mudança | Quem sente | O quê |
|---|---|---|
| Cookie HttpOnly | todos do web | um novo login; nada muda no dia a dia |
| CSP `connect-src` restrita | ninguém (se a lista estiver completa) | erro de rede se faltar um host — testar no staging |
| `sessionStorage` p/ privilegiados | admin global, Secretaria | login a cada aba nova |
| Sessão curta p/ privilegiados | admin global, Secretaria | login mais frequente |
| MFA TOTP | admin global, Secretaria | cadastro único do app + código a cada login; perder o celular = códigos de recuperação |

## 5. Plano incremental sugerido (cada passo reversível; só o 1 começou, em 31/10/2026)

1. **Limitador de login persistente** no Edu (reaproveita o desenho do Quest). Sem
   impacto visível no uso normal (sob ataque, ver o trade-off do teto global em §1.1).
   **Em parte feito (31/10/2026):** tetos de falhas por IP e global no
   banco, configuráveis (§1.1); faltam o por conta e o por (conta, IP).
2. **CSP `connect-src` restrita** aos hosts da API (staging primeiro).
3. **Web chama a API em `api.constelaedu.com`** (mesmo site) — pré-requisito do cookie.
4. **Cookie HttpOnly + CSRF** atrás de uma configuração, aceitando Bearer e cookie em
   paralelo; o web passa a usar cookie; desktop/celular seguem com Bearer.
5. **MFA TOTP opcional** para admin global e Secretaria (cadastro voluntário) →
   **obrigatório** depois de um prazo comunicado.
6. Lista de sessões ativas e "sair dos outros aparelhos" (exige identificador de sessão
   no token e tabela de sessões).

## 6. Perguntas ao dono

1. Aprovar a troca para cookie HttpOnly (com o novo login único de todos) e o uso de
   `api.constelaedu.com` pelo web?
2. MFA obrigatório para admin global e Secretaria? Para coordenadores também?
3. Duração da sessão para perfis privilegiados?
4. Procedimento de recuperação de MFA do admin global (quem autoriza)?
