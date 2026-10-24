@echo off
setlocal

REM ============================================================
REM  Routely - установка GNU Make для Windows (цель "make seed")
REM
REM  Что делает:
REM    1. Устанавливает GNU Make 4.4.1 через winget (ezwinports.make)
REM    2. Копирует make.exe в каталог %LOCALAPPDATA%\Microsoft\WinGet\Links
REM       (каталог уже добавлен winget в пользовательский PATH)
REM    3. Добавляет хук в ~/.bashrc, чтобы Git Bash находил make
REM       даже без перезапуска VSCode (см. .tools/make_bashrc_hook.txt)
REM
REM  Запуск (cmd или PowerShell):
REM    scripts\setup_make_windows.bat
REM
REM  После установки (Git Bash):
REM    make seed
REM    # или без make:
REM    npm run seed
REM ============================================================

echo [1/3] Установка GNU Make (winget: ezwinports.make)...
winget install --id ezwinports.make -e --accept-source-agreements --accept-package-agreements --silent
if errorlevel 1 (
    echo [!] Не удалось установить make через winget. Проверьте сеть и повторите.
    exit /b 1
)

echo [2/3] Создание make.exe в каталоге WinGet\Links...
set "PKG_DIR=%LOCALAPPDATA%\Microsoft\WinGet\Packages\ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe\bin"
if not exist "%PKG_DIR%\make.exe" (
    echo [!] make.exe не найден: %PKG_DIR%
    exit /b 1
)
if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Links" mkdir "%LOCALAPPDATA%\Microsoft\WinGet\Links"
copy /y "%PKG_DIR%\make.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\make.exe" >nul
if errorlevel 1 (
    echo [!] Не удалось скопировать make.exe.
    exit /b 1
)

echo [3/3] Настройка ~/.bashrc для Git Bash...
if not exist "%USERPROFILE%\.bashrc" type nul > "%USERPROFILE%\.bashrc"
findstr /C:"Routely: GNU Make" "%USERPROFILE%\.bashrc" >nul 2>&1
if errorlevel 1 type "%~dp0..\.tools\make_bashrc_hook.txt" >> "%USERPROFILE%\.bashrc"

echo.
echo Готово! GNU Make установлен.
echo.
echo Дальнейшие шаги:
echo   1. pip install -r scripts/requirements.txt   - зависимости для загрузки данных
echo   2. Откройте НОВЫЙ терминал (в старом PATH не обновится)
echo   3. В Git Bash выполните:  make seed
echo      Аналог без make:      npm run seed
echo.
endlocal
