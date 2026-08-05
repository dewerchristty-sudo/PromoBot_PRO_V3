@echo off
cd /d C:\Users\sipolatti\OneDrive\Desktop\PromoBot_PRO_V3
call .venv\Scripts\activate.bat

echo.
echo ============================================================
echo   PromoBot PRO V3 - Ambiente de Producao
echo   Live Delivery: DESATIVADO
echo ============================================================
echo.

set PROMOTION_HUNTER_LIVE_DELIVERY=false

python main.py

pause