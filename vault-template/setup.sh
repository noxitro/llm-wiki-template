#!/bin/sh
# LLM Wiki の setup: この vault を作業ディレクトリに紐づける。引数は scripts/setup.py にそのまま渡す。
#   ./setup.sh ~/src/myapp
#   ./setup.sh ~/src/myapp --unlink
dir=$(cd "$(dirname "$0")" && pwd)
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    exec "$candidate" "$dir/scripts/setup.py" "$@"
  fi
done
echo "setup: Python 3.9 以上が見つからない" >&2
exit 1
