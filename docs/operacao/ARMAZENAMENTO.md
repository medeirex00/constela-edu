# Armazenamento em disco da API: inventário e volume no Railway

Data: 20/10/2026. Nada foi alterado no Railway. Hoje o serviço do backend **não tem
volume** (`volumeMounts` vazio): tudo o que a API grava em disco vai para o sistema de
arquivos do contêiner e **some a cada deploy ou reinício**.

## 1. Inventário: tudo o que grava arquivo

Levantado por busca em `backend/app` e `backend/scripts` (`UPLOADS_DIR`, `EXPORTS_DIR`,
`open(..., "w")`, `write_bytes`, `write_text`, `tempfile`, `mkdir`, `shutil.move`,
`.save(`, downloads do Playwright).

| # | Onde (código) | O que grava | Caminho | Classe | Se sumir num deploy |
|---|---|---|---|---|---|
| 1 | `routers/importacoes.py` `_guardar_temporario` (também usado por `sync/orchestrator.py`) | original do relatório (PDF/XLSX) entre "analisar" e "confirmar" | `UPLOADS_DIR/temporarios/<uuid>.pdf\|xlsx` | **temporário** (expira em 24 h; limpo a cada análise) | a confirmação segue; só não arquiva o original (`origem.exists()` falso) |
| 2 | `routers/importacoes.py` `_confirmar_sem_commit` (rota "confirmar") | o mesmo original, movido para o arquivo definitivo | `UPLOADS_DIR/<plataforma>/<AAAAMMDD_HHMMSS>_<nome>`; o caminho vai em `importacoes.arquivo_original` | **deveria persistir** (evidência da importação) — mas a API **nunca relê** esse arquivo e nenhuma tela o mostra | perde-se a evidência; nada quebra |
| 3 | `routers/relatorios.py` `_arquivar_copia` | cópia de cada relatório exportado (CSV/XLSX/PDF, com nomes de alunos) | `EXPORTS_DIR/<nome>` | **cópia descartável** (retenção `EXPORTS_RETENCAO_DIAS=7`; o download nunca depende dela) | nada (LGPD até prefere) |
| 4 | Starlette `UploadFile` | corpo de upload acima de 1 MB | temporário do sistema (`/tmp`) | temporário do processo | nada |
| 5 | `sync/connectors/navegador.py` (Playwright `download.path()`) | relatório baixado pelo robô, lido para a memória | pasta temporária do Playwright | temporário do navegador | nada |
| 6 | Playwright / `HOME=/home/app` | navegador e cache | `/ms-playwright` (imagem), `/home/app` | da imagem / cache | nada |
| 7 | `core/config.py` (SQLite padrão) | banco | `database/sgpe.db` | só desenvolvimento (produção recusa SQLite) | — |
| — | `services/indicadores/preparar.py --saida`, `scripts/auditar_notas_elefante.py --json`, `scripts/gerar_catalogo_elefante.py` | pacotes/relatórios de linha de comando | onde o operador mandar | ferramenta local, **não** roda na API | — |
| — | logs | — | **stdout** (sem arquivo; quem guarda é o Railway, pelo prazo do plano) | — | — |

Logs não ficam no disco, mas ficam guardados fora dele (Railway). Até este pacote, a
linha de acesso do uvicorn levava a URL crua — token do painel público, token do link
de redefinição de senha, `?busca=` com nome de criança — para o log do Railway. Este
pacote desliga essa linha no próprio app (`configurar_logging`), esconde os parâmetros
das exceções de banco (`hide_parameters`) e redige os valores que o PostgreSQL copia no
`DETAIL` do erro; o log do app grava só o modelo da rota. O `--no-access-log` no comando
de partida continua como reforço e é o único fechamento para o código de hoje, antes do
deploy. Ver `PRODUCAO-ENV-E-MIGRACOES.md`, passo 0a.

Conclusão: **nada que a API precisa para funcionar depende do disco persistir**. Com o
volume, o que passa a sobreviver ao deploy é o arquivo dos originais importados (#2) e
as cópias de relatório (#3, até a retenção). Ambos contêm nomes de crianças.

## 2. Configuração (já no código)

- Base das pastas: `UPLOADS_DIR`/`EXPORTS_DIR` explícitos > `DADOS_DIR` >
  `RAILWAY_VOLUME_MOUNT_PATH` (o Railway injeta quando há volume) > raiz do repositório
  (desenvolvimento). As subpastas continuam `uploads/` e `exports/`.
- A imagem Docker define `DADOS_DIR=/dados`: os caminhos efetivos seguem
  **`/dados/uploads` e `/dados/exports`**, os mesmos de antes. Nenhum arquivo muda de
  formato nem de lugar.
- `GET /api/v1/sistema/diagnostico` (admin global), bloco `armazenamento`:
  `persistente` (`true` = pastas dentro do volume; `false` = no Railway sem volume ou
  fora dele; `null` = fora do Railway, não dá para saber), `volume`, e por pasta
  `caminho`, `existe`, `gravavel`, `no_volume`, mais `avisos`.

## 3. Como anexar o volume (dono, no painel do Railway)

1. Serviço do backend → **Volumes** → criar volume com **mount path `/dados`** (o mesmo
   da imagem; montar em outro caminho exige `DADOS_DIR=<caminho>`).
2. **Permissão (decisão do dono).** A imagem roda como o usuário sem privilégios `app`
   (uid 1001), e o volume do Railway é montado como root — a doc do Railway diz que
   imagens não-root "will have permissions issues" e sugere `RAILWAY_RUN_UID=0`. Opções:
   - `RAILWAY_RUN_UID=0`: o contêiner passa a rodar como **root** (pior isolamento, mas é
     o caminho documentado);
   - manter não-root: o volume fica sem escrita, a API segue (tudo é melhor esforço) e o
     diagnóstico mostra `gravavel: false` — o volume não serve para nada;
   - (código, não feito) um passo de partida como root que faz `chown` em `/dados` e
     desce para o usuário `app` — exige mudar a imagem e o comando de partida.
3. Deploy. **Restrição: uma réplica só** — a doc do Railway: "Replicas cannot be used with
   volumes". E há um pequeno downtime a cada redeploy com volume, mesmo com healthcheck
   (dois deployments não montam o mesmo volume ao mesmo tempo).
4. O pre-deploy (`python -m scripts.migrate`) roda **sem** o volume (doc do Railway) —
   não importa: a migração não usa disco.

## 4. Teste de persistência (depois de anexar)

1. Diagnóstico como admin global: `armazenamento.persistente == true`,
   `pastas.uploads.gravavel == true`, `avisos == []`.
2. Faça uma importação de teste (relatório pequeno, de uma turma de teste) até
   "confirmar"; anote o `arquivo_original` gravado na importação
   (`uploads/<plataforma>/<data>_<nome>`).
3. Redeploy do mesmo código.
4. Confira que o arquivo continua lá: hoje a API **não tem rota de download** do
   original, então a conferência é pelo console do serviço (`ls /dados/uploads/<plataforma>`)
   ou pelo backup do volume. Para um teste sem console, exporte um relatório (vai para
   `/dados/exports`) e, depois do redeploy, confira pelo diagnóstico que a pasta `exports`
   continua `existe: true` (indício fraco; o console é a prova).

## 5. Perguntas para o dono

- Os originais importados (#2) devem ser guardados? Hoje só são escritos, nunca lidos,
  e não têm expurgo: num volume, acumulam PII de crianças sem prazo. Definir retenção
  (como a das cópias de relatório) ou desligar o arquivamento.
- As cópias de relatório (#3) têm utilidade? O download não depende delas; persistir
  só aumenta a PII guardada.
- `RAILWAY_RUN_UID=0` (root) é aceitável, ou prefere o passo de `chown` + descida de
  privilégio na imagem?
