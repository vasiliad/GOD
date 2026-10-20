@echo off
rem Перезапуск мозга GOD двойным кликом: убить сессию Kaggle, поднять свежую, дождаться онлайн.
cd /d "%~dp0.."
python brain\restart_brain.py
pause
