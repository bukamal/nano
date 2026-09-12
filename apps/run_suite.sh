#!/usr/bin/env bash
# تشغيل أحد تطبيقات نانو المنفصلة مع قاعدة بيانات مشتركة.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export NANO_SHARED_DATA_DIR="${NANO_SHARED_DATA_DIR:-$HOME/.nano}"

APP="${1:-}"
case "$APP" in
  accounting|acc|محاسبة)
    exec python "$ROOT/apps/nano_accounting/main.py"
    ;;
  inventory|inv|مستودع|warehouse)
    exec python "$ROOT/apps/nano_inventory/main.py"
    ;;
  pos|بيع|point)
    exec python "$ROOT/apps/nano_pos/main.py"
    ;;
  full|كامل|"")
    exec python "$ROOT/src/main.py"
    ;;
  *)
    echo "الاستخدام: $0 [accounting|inventory|pos|full]"
    echo "  accounting  → نانو المحاسبة"
    echo "  inventory   → نانو المستودع"
    echo "  pos         → نانو نقطة البيع"
    echo "  full        → التطبيق الكامل الأصلي"
    exit 1
    ;;
esac
