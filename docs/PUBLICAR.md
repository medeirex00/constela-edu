# Publicar o Constela Edu na internet — passo a passo

Ao final deste guia, **qualquer pessoa** acessa o sistema pelo navegador em
`https://SEU-DOMINIO` — iPhone, Android, Windows, macOS, Linux, tablet, TV.
Os aplicativos instaláveis (desktop e celular) são um extra opcional no fim.

**Custos:** um servidor VPS (~R$ 25–40/mês) e um domínio (~R$ 40/ano).
**Tempo:** 1 a 2 horas na primeira vez.

---

## Passo 1 — Colocar o código no GitHub (uma vez)

O servidor vai baixar o projeto do GitHub (e o CI passa a rodar sozinho).

1. Crie uma conta em https://github.com (grátis).
2. Crie um repositório **privado** chamado `constela-edu`
   (botão "New repository" → marque *Private* → *Create*).
3. No computador, no PowerShell, dentro da pasta do projeto:

   ```powershell
   git remote add origin https://github.com/SEU-USUARIO/constela-edu.git
   git push -u origin main
   ```

   (O Git vai abrir o navegador para você autorizar.)

## Passo 2 — Alugar um servidor (VPS)

Qualquer provedor serve. Sugestões com bom custo no Brasil:

| Provedor | Plano suficiente | Observação |
|---|---|---|
| Hetzner | CX22 (~€4,5/mês) | Melhor custo-benefício, datacenter fora do BR |
| DigitalOcean | Basic 2 GB (~US$ 12/mês) | Interface simples |
| Hostinger / Locaweb / KingHost | VPS 2 GB | Datacenter no Brasil, suporte em português |

Na criação, escolha:
- **Sistema**: Ubuntu 24.04 LTS
- **Tamanho**: 2 GB de RAM é confortável para começar (milhares de
  usuários de escola não são milhares de acessos simultâneos; dá para
  crescer depois sem mudar nada no sistema)
- Anote o **IP** do servidor e a senha/chave de acesso.

## Passo 3 — Comprar o domínio e apontar para o servidor

1. Registre um domínio: https://registro.br (para `.com.br`, ~R$ 40/ano)
   ou Cloudflare/Namecheap para `.com`.
2. No painel DNS do domínio, crie um registro:

   ```
   Tipo: A    Nome: constela    Valor: IP-DO-SERVIDOR
   ```

   Isso faz `constela.seudominio.com.br` apontar para o servidor.
   (Pode levar até 1h para propagar.)

## Passo 4 — Preparar o servidor (copiar e colar)

Conecte no servidor (o provedor mostra como; em geral
`ssh root@IP-DO-SERVIDOR` no PowerShell) e cole, uma linha por vez:

```bash
# Docker (instalador oficial)
curl -fsSL https://get.docker.com | sh

# Firewall: só web e ssh
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable

# Baixar o projeto (o GitHub vai pedir usuário + token de acesso)
git clone https://github.com/SEU-USUARIO/constela-edu.git
cd constela-edu

# Configuração
cp .env.example .env
nano .env
```

No editor que abre (`nano`), preencha e salve (Ctrl+O, Enter, Ctrl+X):

```
POSTGRES_PASSWORD=uma-senha-forte-e-unica
SECRET_KEY=outra-chave-longa-e-aleatoria-diferente
DOMINIO=constela.seudominio.com.br
PUBLIC_BASE_URL=https://constela.seudominio.com.br
WEB_BIND=127.0.0.1
AI_PROVIDER=local
```

> Para gerar chaves fortes: `openssl rand -hex 32` (rode duas vezes).
> O sistema **recusa subir em produção** com a `SECRET_KEY` de exemplo — isso
> é proposital.
>
> **`WEB_BIND=127.0.0.1` é importante com HTTPS:** o Docker abre portas
> publicadas *antes* do `ufw`, então sem essa linha a porta 8080 ficaria
> acessível em HTTP puro na internet, contornando o firewall e o TLS do
> Caddy. Com o bind em loopback, só o Caddy (pela rede interna) alcança o
> site, e todo o tráfego externo passa por HTTPS.

## Passo 5 — Ligar o sistema

```bash
docker compose --profile https up -d --build
```

A primeira vez demora alguns minutos (baixa e monta tudo). O certificado
HTTPS é emitido automaticamente (Let's Encrypt) — sem nenhum passo manual.

Crie a escola e o usuário inicial (SEM dados de demonstração):

```bash
docker compose exec backend python scripts/seed.py
```

> **Anote a senha exibida no console.** O seed gera uma senha aleatória para
> o administrador inicial e a imprime uma única vez. (Para automatizar, defina
> `ADMIN_INITIAL_PASSWORD` no ambiente antes de rodar o seed.)

## Passo 6 — Primeiro acesso e segurança

1. Abra `https://constela.seudominio.com.br` em qualquer aparelho.
2. Entre com `admin@constela.local` e a senha que o seed mostrou no console.
3. **Imediatamente**: menu **Usuários** → crie o SEU usuário admin com
   e-mail real e senha forte → saia → entre com ele → desative ou
   redefina a senha do `admin@constela.local`.
4. Em **Configurações**, ajuste os dados da escola.
5. Crie os usuários dos professores/coordenadores em **Usuários** —
   é assim que "qualquer usuário" passa a ter acesso, cada um com seu
   papel e senha.

**Pronto.** A partir daqui, todo mundo acessa de qualquer aparelho pelo
navegador. O Painel Público (`/p/{token}` + QR code) funciona sem login.

---

## Rotina e manutenção

```bash
# Atualizar o sistema quando houver novidades no GitHub
cd constela-edu && git pull && docker compose --profile https up -d --build

# Ver se está tudo de pé (a coluna STATUS mostra "healthy")
docker compose ps
```

### Backup automático (recomendado)

O jeito mais simples é ligar o serviço de backup embutido — ele faz um
`pg_dump` **e** um arquivo dos uploads todo dia, guardando 14 dias em
`./backups`:

```bash
docker compose --profile https --profile backup up -d
```

Depois, **copie a pasta `backups/` para fora do servidor** com regularidade
(um `rclone`/`rsync` para Google Drive, S3, Backblaze etc.) — backup no mesmo
servidor não protege contra perda do servidor.

> O backup JSON pela interface (em **Configurações**) é útil para mover dados
> de uma escola, mas **não substitui** o `pg_dump`: ele não inclui contas de
> usuário nem os arquivos enviados.

### Escala horizontal e limite de tentativas (quando o Redis passa a ser necessário)

O limitador de tentativas de login — a trava contra força-bruta de senhas de
adultos e de códigos das crianças — guarda os contadores **em memória, por
processo**. Isso é adequado (e é o recomendado) para o cenário deste guia:

* **uma única instância** do backend (um servidor), com um ou poucos *workers*.
  Os contadores são consistentes o bastante para frear ataques online de
  dicionário, e o uso de memória é **limitado** — há teto rígido de chaves, então
  tentativas com usuários/códigos aleatórios não esgotam a RAM (não há vetor de
  DoS por memória).

**O momento em que isso deixa de bastar — e o Redis passa a ser necessário:**

* Quando você rodar **mais de uma instância/réplica do backend** atrás de um
  balanceador de carga (escala **horizontal**). Cada réplica passa a ter o seu
  próprio contador, e eles **não se enxergam**: o orçamento efetivo de tentativas
  por conta fica multiplicado pelo número de réplicas, enfraquecendo a trava na
  mesma proporção.
* Ou quando os logs de auditoria mostrarem um ataque de **força-bruta
  distribuído** real (muitos IPs contra uma mesma conta) que o limite atual não
  esteja contendo.

Enquanto o sistema roda em **uma instância** (crescendo **verticalmente** — mais
CPU/RAM no mesmo servidor, que atende milhares de alunos de escola sem problema),
**nada precisa mudar**. Ao migrar para **várias réplicas**, troque o
armazenamento do limitador por um **contador compartilhado** entre instâncias
(ex.: Redis com `INCR`+`EXPIRE`). A interface do limitador em
`backend/app/core/rate_limit.py` (`bloqueado` / `registrar_falha` / `limpar`) foi
mantida pequena de propósito justamente para permitir essa troca sem tocar no
restante do sistema.

---

## Extras opcionais (depois que o site estiver no ar)

### Aplicativo de celular (Android/iOS) apontando para o domínio

No computador: edite `apps/mobile/eas.json` e troque a URL do perfil
desejado por `https://constela.seudominio.com.br/api/v1`, depois:

```powershell
eas build -p android --profile preview   # APK por link, sem loja
# ou os perfis "producao" + eas submit para publicar nas lojas
```

Detalhes em `docs/CELULAR.md`.

### Aplicativo de computador (Windows/macOS/Linux)

No GitHub: em *Settings → Secrets and variables → Actions*, crie os
segredos `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
(gerados com `npm run tauri -w @constela/desktop signer generate`) e
`VITE_API_URL` = `https://constela.seudominio.com.br/api/v1`. Depois:

```powershell
git tag v1.0.0 && git push origin v1.0.0
```

O GitHub compila sozinho os instaladores para os três sistemas e publica
um *release* com os arquivos para download.
