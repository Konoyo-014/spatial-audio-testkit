#!/bin/zsh
set -euo pipefail
cd -- "$(dirname -- "$0")"
/usr/bin/python3 scripts/verify.py
print '\n检查完成。详细结果保存在 validation/report.md。'
read -r '?按回车关闭。'
