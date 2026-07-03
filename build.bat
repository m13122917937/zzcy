@echo off

set PYTHON=C:\Users\lenovo\.conda\envs\apple_code\python.exe

if not exist "%PYTHON%" (
    echo ERROR: Python not found at %PYTHON%
    pause
    exit /b 1
)

echo ========================================
echo   Nuitka Build - Apple Query Tool
echo ========================================
echo.

%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    --enable-plugin=pyqt6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=honor_logo.ico ^
    --include-data-file=honor_logo.ico=honor_logo.ico ^
    --include-data-file=honor_logo.png=honor_logo.png ^
    --include-package=curl_cffi ^
    --include-package=curl_cffi.requests ^
    --include-package=PIL ^
    --include-package=PIL._imaging ^
    --include-package=psutil ^
    --include-package=openpyxl ^
    --include-package=pandas ^
    --include-module=environment_config ^
    --include-module=apple_search_api ^
    --no-prefer-source-code ^
    --output-filename=AppleQueryTool.exe ^
    --output-dir=dist ^
    --assume-yes-for-downloads ^
    --show-progress ^
    --show-modules ^
    main.py

echo.
if exist "dist\AppleQueryTool.exe" (
    echo [OK] Output: dist\AppleQueryTool.exe
    for %%A in ("dist\AppleQueryTool.exe") do echo [Size] %%~zA bytes
) else (
    echo [FAIL] Build failed, check errors above
)
echo.
pause
