#!/bin/zsh
cd "${0:A:h}"
if [[ ! -x .runtime/bin/python ]]; then
  python3 -m venv .runtime
  .runtime/bin/python -m pip install -r requirements.txt || exit 1
fi
(sleep 1; open http://localhost:8765) &
exec .runtime/bin/python server.py
