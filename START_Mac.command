#!/bin/bash
# PDF 자료 검색기 - 맥(macOS)용 시작 파일. 두 번 클릭하면 실행됩니다.
cd "$(dirname "$0")" || exit 1
echo ""
echo " ============================================"
echo "   PDF 자료 검색기를 준비합니다"
echo " ============================================"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo ""
  echo " [안내] Python이 없습니다. 열리는 웹페이지에서 macOS용 Python을 내려받아 설치한 뒤"
  echo "        이 파일을 다시 두 번 클릭하세요."
  open "https://www.python.org/downloads/macos/"
  read -n 1 -s -r -p " 아무 키나 누르면 창이 닫힙니다."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo " [1/2] 프로그램 전용 환경을 만드는 중..."
  "$PY" -m venv .venv || { echo " [오류] 환경을 만들지 못했습니다."; read -n 1 -s -r; exit 1; }
fi

if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  echo " [2/2] 필요한 부품을 설치하는 중... 처음 한 번만 1~3분 걸립니다."
  .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || {
    echo " [오류] 부품 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행해 주세요."; read -n 1 -s -r; exit 1; }
  cp requirements.txt .venv/installed-requirements.txt
fi

echo ""
echo " 준비 완료! 잠시 후 브라우저가 열립니다."
echo " 이 창은 닫지 마세요. 창을 닫으면 프로그램이 꺼집니다."
echo ""
.venv/bin/python app.py
