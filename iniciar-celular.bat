@echo off
REM ============================================================
REM  Constela Edu — iniciar para acesso pelo celular
REM  Dê dois cliques neste arquivo. Ele abre duas janelas:
REM    1) API (backend)  2) Site (frontend)
REM  Depois, no celular (mesmo Wi-Fi), abra:  http://SEU-IP:5173
REM  (o IP aparece na janela do site, na linha "Network")
REM ============================================================
cd /d "%~dp0"

start "Constela Edu - API" cmd /k "cd backend && .venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"

start "Constela Edu - Site" cmd /k "npm run dev:web"

echo.
echo  Duas janelas foram abertas (API e Site). Aguarde ~10 segundos.
echo  No celular, abra o endereco que aparece como "Network" na janela do Site.
echo  Para desligar, feche as duas janelas.
echo.
pause
