@echo off
cd /d C:\Users\sipolatti\OneDrive\Desktop\PromoBot_PRO_V3
call .venv\Scripts\activate.bat

echo.
echo ============================================================
echo   PromoBot PRO V3 - Hunter Automatico
echo   Modo: analise de ofertas (analysis-only por padrao)
echo   Mercado Livre: busca automatica com intervalos controlados
echo ============================================================
echo.

echo Verificando configuracoes...
python -c "from src.promotion_hunter.config import *; print(f'scheduler={SCHEDULER_ENABLED}'); print(f'intervalo={INTERVAL_MINUTES}min'); print(f'janela={ALLOWED_START_HOUR:02d}h-{ALLOWED_END_HOUR:02d}h'); print(f'max_messages_por_exec={MAX_MESSAGES_PER_RUN}')"
echo.

python scripts/run_hunter_auto.py

pause