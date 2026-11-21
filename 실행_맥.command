#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python이 없습니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행해 주세요."
  read -n 1 -s -r -p "아무 키나 누르면 닫힙니다"
  exit 1
fi
python3 app.py
