@echo off
cd /d "%~dp0"
title 쿠팡 카드뉴스 - 설치하기
echo.
echo  ============================================
echo    쿠팡 카드뉴스 만들기 - 설치
echo  ============================================
echo.
echo    처음 한 번만 하면 됩니다. 5~10분 걸려요.
echo    설치가 끝날 때까지 이 창을 닫지 마세요.
echo.

echo    [1/4] 파이썬이 깔려 있는지 확인합니다...
python --version
if errorlevel 1 goto NOPYTHON
echo.

echo    [2/4] 작업 공간을 만듭니다... (1분쯤)
python -m venv .venv
if errorlevel 1 goto FAIL
echo.

echo    [3/4] 필요한 부품을 받습니다... (2~3분)
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install playwright pillow jinja2
if errorlevel 1 goto FAIL
echo.

echo    [4/4] 크롤링용 브라우저를 받습니다... (3~5분, 제일 오래 걸립니다)
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto FAIL
echo.

echo  ============================================
echo    설치 완료!
echo.
echo    이제 "카드뉴스 만들기" 를 더블클릭하세요.
echo  ============================================
echo.
pause
exit /b

:NOPYTHON
echo.
echo    [!] 파이썬이 없습니다. 먼저 설치해 주세요.
echo.
echo      1) https://www.python.org/downloads/  접속
echo      2) 노란 "Download Python" 버튼 클릭
echo      3) 설치 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크!
echo         (이걸 안 하면 설치해도 인식이 안 됩니다)
echo      4) 설치가 끝나면 이 파일을 다시 더블클릭
echo.
pause
exit /b

:FAIL
echo.
echo    [!] 설치 중 문제가 생겼습니다.
echo        위에 빨간 글씨가 있으면 그대로 캡처해서 문의해 주세요.
echo.
pause
