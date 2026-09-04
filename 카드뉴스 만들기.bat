@echo off
cd /d "%~dp0"
title 쿠팡 카드뉴스 만들기
echo.
echo   쿠팡 카드뉴스 만들기를 시작합니다...
echo   (이 창은 켜 둔 채로 두세요. 창을 닫으면 앱도 꺼집니다)
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "webapp\server.py"
) else (
  python "webapp\server.py"
)
echo.
echo   앱이 종료되었습니다.
pause
