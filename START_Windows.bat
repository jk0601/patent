@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title PDF 자료 검색기

echo.
echo  ============================================
echo    PDF 자료 검색기를 준비합니다
echo  ============================================
echo.

rem ---- 1. Python 찾기 ---------------------------------------
set "PY="
set "PYARG="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul && (set "PY=py" & set "PYARG=-3")
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  for %%V in (313 312 311 310) do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
  )
)

if not defined PY (
  echo  [안내] 이 PC에 Python이 없습니다. 자동으로 설치합니다. 5분 정도 걸립니다.
  echo         설치 중 확인 창이 뜨면 "예"를 눌러 주세요.
  echo.
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

if not defined PY (
  echo.
  echo  [안내] Python 자동 설치에 실패했습니다.
  echo         곧 열리는 웹페이지에서 노란 Download Python 버튼을 눌러 설치한 뒤,
  echo         설치 첫 화면에서 "Add python.exe to PATH"에 체크하고 Install Now를 누르세요.
  echo         설치가 끝나면 이 파일을 다시 두 번 클릭하세요.
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)

rem ---- 2. 프로그램 전용 환경 만들기 (처음 한 번만) -------------
if not exist ".venv\Scripts\python.exe" (
  echo  [1/2] 프로그램 전용 환경을 만드는 중...
  "%PY%" %PYARG% -m venv .venv
  if errorlevel 1 goto :fail
)

rem ---- 3. 필요한 부품 설치 (처음 한 번, 또는 부품 목록이 바뀌었을 때) --
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  echo  [2/2] 필요한 부품을 설치하는 중... 처음 한 번만 1~3분 걸립니다.
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :fail
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

rem ---- 4. 실행 ---------------------------------------------
echo.
echo  준비 완료! 잠시 후 브라우저가 열립니다.
echo  이 검은 창은 닫지 마세요. 창을 닫으면 프로그램이 꺼집니다.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo  [오류] 준비 중 문제가 생겼습니다. 위의 메시지를 사진으로 찍어 담당자에게 보내 주세요.
echo         인터넷 연결을 확인한 뒤 이 파일을 다시 실행하면 해결되는 경우가 많습니다.
pause
exit /b 1
