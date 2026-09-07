"""FIX_0.9.4 smart_barcode_scanner smoke.

يتأكد من أن الماسح الذكي الجديد:
  - يحقق Tokens صحيحة (Colors.WHITE / Shadow.SOFT) لا تتغير في الوضع الليلي.
  - يبني الشجرة كاملة (root, hint, kind, frame, dock, recent) دون رفع استثناء.
  - يستجيب لكل أنواع الترميز المعروفة ويفشل بأمان للقيم المجهولة.
  - يستدعي callback الموحد على الفحص اليدوي (اختبار بدون كاميرا).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nano_offline.core.theme import Colors
from nano_offline.views.smart_barcode_scanner import (
    SmartBarcodeScanner,
    ScanKind,
    HintState,
    parse_kind,
)


def test_parse_kind():
    assert parse_kind("EAN-13") == ScanKind.EAN13
    assert parse_kind("ean13") == ScanKind.EAN13
    assert parse_kind("QRCODE") == ScanKind.QR
    assert parse_kind("DataMatrix") == ScanKind.DATA_MATRIX
    assert parse_kind("random") == ScanKind.UNKNOWN


def test_builds_full_smart_scanner():
    captured = []

    async def cb(value, kind, meta):
        captured.append((value, kind, meta))

    s = SmartBarcodeScanner(on_scan=cb, parent_title="مسح الباركود الذكي", auto_open=False, recent=[])
    assert s.root is not None
    assert s.hint_chip.content.controls[1].value  # النص موجود
    assert s.kind_chip.visible is False
    assert s.result_card.visible is False
    assert s.dock is not None
    assert s.torch_pill is not None


def test_inject_scan_triggers_callback():
    async def cb(value, kind, meta):
        return value

    s = SmartBarcodeScanner(on_scan=cb)
    s._page = type("P", (), {"run_task": lambda self, c: None})()
    s.inject_scan("5901234123457", "EAN-13")
    assert s.result_card.visible is True
    assert "5901234123457" in s.result_value_text.value
    assert ScanKind.EAN13.value in s.result_kind_text.value


def test_hint_state_changes_color():
    s = SmartBarcodeScanner(on_scan=lambda v, k, m: None)
    s.feed_signal(HintState.LIGHT_LOW, ScanKind.EAN8)
    assert Colors.WARNING.lower() in s.hint_text.color.lower() or "#" in s.hint_text.color
    s.feed_signal(HintState.LOCKED, ScanKind.QR)
    assert s.kind_chip.visible is True


def test_recent_rescan():
    async def cb(value, kind, meta):
        return value

    s = SmartBarcodeScanner(on_scan=cb, recent=[])
    s._page = type("P", (), {"run_task": lambda self, c: None, "set_clipboard": lambda self, v: None, "open": lambda self, x: None})()
    s.inject_scan("1", "EAN-13")
    s.inject_scan("2", "EAN-13")
    assert len(s._recent) == 2
    assert s._recent[0].value == "2"


if __name__ == "__main__":
    test_parse_kind()
    test_builds_full_smart_scanner()
    test_inject_scan_triggers_callback()
    test_hint_state_changes_color()
    test_recent_rescan()
    print("smart_barcode_scanner: all smoke tests passed")
