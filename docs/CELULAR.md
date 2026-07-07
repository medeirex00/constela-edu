# Constela Edu no celular — guia prático

Três caminhos, do mais rápido ao definitivo. Em todos, o celular precisa
alcançar o servidor (mesma rede Wi-Fi em desenvolvimento, ou um servidor
publicado na internet em produção).

> O IP da máquina de desenvolvimento atual é **192.168.15.30** (confira com
> `ipconfig` se mudar de rede).

---

## Caminho 1 — Testar AGORA com o Expo Go (≈10 minutos, sem build)

1. **No celular**: instale o app **Expo Go** (Play Store / App Store).
2. **No computador** (dois terminais):

   ```powershell
   # Terminal 1 — API acessível pela rede local
   cd backend
   .venv\Scripts\activate
   uvicorn app.main:app --host 0.0.0.0 --port 8000

   # Terminal 2 — app mobile apontando para o IP da máquina
   $env:EXPO_PUBLIC_API_URL = "http://192.168.15.30:8000/api/v1"
   npm run dev:mobile
   ```

3. O terminal mostra um **QR code** → escaneie com o Expo Go (Android) ou
   com a câmera (iPhone). O app abre no aparelho.
4. Entre com `admin@constela.local` e a senha que o seed exibiu no console.

Requisitos: celular e computador na **mesma rede Wi-Fi**; se não conectar,
libere a porta 8000 no Firewall do Windows
(`New-NetFirewallRule -DisplayName "Constela API" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).

---

## Caminho 2 — APK instalável no Android (sem loja)

Gera um aplicativo de verdade, que instala pelo arquivo e funciona sem o
Expo Go. Precisa de uma conta gratuita em https://expo.dev.

```powershell
npm install -g eas-cli
eas login                       # sua conta Expo
cd apps/mobile
eas init                        # cria o projectId e preenche o app.json
eas build -p android --profile preview
```

Antes do build, edite `apps/mobile/eas.json` e troque
`EXPO_PUBLIC_API_URL` do perfil `preview` pela URL real da sua API
(em teste na rede local: `http://192.168.15.30:8000/api/v1`).

Ao final, o EAS mostra um **link com QR code para baixar o APK** — abra no
celular e instale (autorize "instalar apps de fontes desconhecidas").
É esse link que você pode encaminhar para outras pessoas da escola.

Para iPhone sem loja é necessário conta Apple Developer (US$ 99/ano) com
distribuição ad-hoc/TestFlight: `eas build -p ios --profile preview`.

---

## Caminho 3 — Publicar nas lojas (produção)

1. Publique o servidor (VPS com `docker compose up -d` + domínio HTTPS).
2. Ajuste `EXPO_PUBLIC_API_URL` do perfil `producao` no `eas.json`.
3. Contas de desenvolvedor: Google Play (US$ 25 única) e/ou Apple (US$ 99/ano).
4. Build + envio:

   ```bash
   eas build -p android --profile producao
   eas submit -p android
   eas build -p ios --profile producao
   eas submit -p ios
   ```

Push em produção: o `projectId` criado pelo `eas init` já habilita as
notificações via Expo — nenhuma configuração extra no backend.

---

## Alternativa sem instalar nada: o site no celular

O web app é responsivo. Com o backend + web rodando (dev: `npm run dev:web`
com `--host`, ou produção: `docker compose up -d`), basta abrir no navegador
do celular:

- Desenvolvimento: `http://192.168.15.30:5173` — o `npm run dev:web` já
  expõe na rede (ou simplesmente dê dois cliques em `iniciar-celular.bat`
  na raiz do projeto, que liga API e site de uma vez)
- Produção (Docker): `http://SEU-SERVIDOR:8080`

O **Painel Público** (`/p/{token}`) também funciona direto no celular, sem
login — é o mesmo QR code impresso pela escola.
