@echo off
echo =========================================
echo   JARVIS Starting...
echo =========================================
echo.

REM Activate venv
call C:\Users\micha\jarvis\venv\Scripts\activate.bat

REM Start llama.cpp server in background (optional local model)
start "JARVIS-LLM" /min cmd /c "C:\Users\micha\jarvis\start_llama.bat"
timeout /t 4 /nobreak > nul

REM Start FastAPI backend
start "JARVIS-Backend" /min cmd /c "cd C:\Users\micha\jarvis && python src\server.py"
timeout /t 3 /nobreak > nul

REM Start frontend dev server
start "JARVIS-Frontend" /min cmd /c "cd C:\Users\micha\jarvis\frontend && npm run dev"
timeout /t 4 /nobreak > nul

REM Open browser
start chrome http://localhost:5173

echo JARVIS is starting. Check the browser window.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo Close this window to stop watching logs.
pause
