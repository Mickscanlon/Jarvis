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

REM Start FastAPI backend — /k keeps the window open if it crashes so you can read the error
start "JARVIS-Backend" cmd /k "cd /d C:\Users\micha\jarvis && call venv\Scripts\activate.bat && python src\server.py"
timeout /t 3 /nobreak > nul

REM Start frontend dev server
start "JARVIS-Frontend" /min cmd /c "cd /d C:\Users\micha\jarvis\frontend && npm run dev"
timeout /t 4 /nobreak > nul

REM Open browser
start chrome http://localhost:5173

echo JARVIS is starting. Check the backend window for logs.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo.
pause
