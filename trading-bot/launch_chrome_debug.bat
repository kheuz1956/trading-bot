@echo off
:: Lance Chrome avec le port de debug pour que le bot Playwright puisse s'y connecter
:: Garder XStation5 ouvert dans cette fenetre Chrome

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
set PROFILE=%TEMP%\xtb_chrome_debug

echo Lancement de Chrome avec debug port 9222...
%CHROME% --remote-debugging-port=9222 --user-data-dir="%PROFILE%" https://xstation5.xtb.com/?branch=int#/_/login

pause
