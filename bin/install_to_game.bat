@echo off
setlocal enabledelayedexpansion

:: install_to_game.bat
:: Usage: install_to_game.bat "E:\Porn\pGames\FreshWomen"
::
:: Creates %1\game\renpy_cue\ with directory symlinks for:
::   audio  -> E:\Davinci Resolve Media\Sex Sounds
::   src    -> E:\Porn\pGames\renpy_cue\src

set "GAME_DIR=%~1"
if "%GAME_DIR%"=="" (
    echo ERROR: No game directory provided.
    echo Usage: install_to_game.bat "E:\Porn\pGames\FreshWomen"
    exit /b 1
)

if not exist "%GAME_DIR%" (
    echo ERROR: Game directory does not exist: %GAME_DIR%
    exit /b 1
)

set "CUE_DIR=%GAME_DIR%\game\renpy_cue"
set "AUDIO_SRC=E:\Davinci Resolve Media\Sex Sounds"
set "SRC_SRC=E:\Porn\pGames\renpy_cue\src"

echo Game dir : %GAME_DIR%
echo Cue dir  : %CUE_DIR%
echo.

:: Create game\renpy_cue if it doesn't exist
if not exist "%CUE_DIR%" (
    echo Creating %CUE_DIR% ...
    mkdir "%CUE_DIR%"
) else (
    echo Cue dir already exists: %CUE_DIR%
)

:: --- audio symlink ---
set "AUDIO_LINK=%CUE_DIR%\audio"
if exist "%AUDIO_LINK%" (
    echo Removing existing audio link/dir ...
    rmdir "%AUDIO_LINK%" 2>nul
    del "%AUDIO_LINK%" 2>nul
)
echo Linking audio ...
echo   %AUDIO_LINK%
echo   -^> %AUDIO_SRC%
mklink /D "%AUDIO_LINK%" "%AUDIO_SRC%"

:: --- src symlink ---
set "SRC_LINK=%CUE_DIR%\src"
if exist "%SRC_LINK%" (
    echo Removing existing src link/dir ...
    rmdir "%SRC_LINK%" 2>nul
    del "%SRC_LINK%" 2>nul
)
echo Linking src ...
echo   %SRC_LINK%
echo   -^> %SRC_SRC%
mklink /D "%SRC_LINK%" "%SRC_SRC%"

echo.
echo Done. Verify with: dir "%CUE_DIR%"
endlocal
