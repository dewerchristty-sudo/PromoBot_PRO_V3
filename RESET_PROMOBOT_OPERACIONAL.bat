@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0" || (
    echo ERRO: Nao foi possivel acessar a raiz do projeto.
    set "EXIT_CODE=3"
    goto :fim
)

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: Python do ambiente virtual nao encontrado.
    set "EXIT_CODE=9009"
    goto :fim
)

if /i "%~1"=="--restore" goto :restore
if not "%~1"=="" goto :argumento_invalido

echo Executando diagnostico seguro. Nenhum dado sera alterado.
call .venv\Scripts\python.exe scripts\reset_operacional.py --dry-run
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :erro

echo.
echo ATENCAO: a proxima etapa cria backup e altera somente estado operacional.
echo Digite exatamente: CONFIRMAR RESET OPERACIONAL
set "CONFIRMACAO="
set /p "CONFIRMACAO=> "
setlocal EnableDelayedExpansion
if not "!CONFIRMACAO!"=="CONFIRMAR RESET OPERACIONAL" (
    endlocal
    goto :cancelado
)
endlocal

call .venv\Scripts\python.exe scripts\reset_operacional.py --apply --confirm "CONFIRMAR RESET OPERACIONAL"
set "EXIT_CODE=%ERRORLEVEL%"
goto :fim

:cancelado
echo Reset cancelado. Nenhuma alteracao foi realizada.
set "EXIT_CODE=0"
goto :fim

:erro
echo Diagnostico falhou. Reset nao sera oferecido.
goto :fim

:restore
if "%~2"=="" (
    echo ERRO: Uso esperado: RESET_PROMOBOT_OPERACIONAL.bat --restore ^<pasta^>
    set "EXIT_CODE=64"
    goto :fim
)
if not "%~3"=="" goto :argumento_invalido
call .venv\Scripts\python.exe scripts\reset_operacional.py --restore "%~2"
set "EXIT_CODE=%ERRORLEVEL%"
goto :fim

:argumento_invalido
echo ERRO: Argumentos invalidos.
echo Uso: RESET_PROMOBOT_OPERACIONAL.bat
echo   ou RESET_PROMOBOT_OPERACIONAL.bat --restore ^<pasta^>
set "EXIT_CODE=64"

:fim
pause
endlocal & exit /b %EXIT_CODE%
