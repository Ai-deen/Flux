@echo off
:: EngMemory / Flux - One-Click Launcher
:: Double-click this file to install and start EngMemory
:: Microsoft Build AI Hackathon 2026

title EngMemory / Flux Installer
echo.
echo   Starting EngMemory installer...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"

pause
