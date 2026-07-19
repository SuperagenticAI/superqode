#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -e . pyinstaller pyinstaller-hooks-contrib

pyinstaller -y superqode.spec
ln -sfn superqode dist/superqode/sq

echo "Built binaries: dist/superqode/superqode and dist/superqode/sq"
