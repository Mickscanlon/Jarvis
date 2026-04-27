@echo off
echo Starting llama.cpp server...
echo Model: Qwen2.5 7B
echo Port: 8080
echo.

REM ---- Edit the model filename below if yours is different ----
set MODEL=C:\Users\micha\jarvis\models\qwen2.5-7b-instruct.gguf

C:\Users\micha\jarvis\llama\llama-server.exe ^
  --model "%MODEL%" ^
  --ctx-size 8192 ^
  --n-gpu-layers 99 ^
  --port 8080 ^
  --host 0.0.0.0

pause