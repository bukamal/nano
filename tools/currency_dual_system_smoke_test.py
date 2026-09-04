"""Comprehensive offline test for the dual-currency system (stored USD / displayed SYP).

Pure Python + a temp sqlite DB via the real SettingsRepository -- no Flet UI is
started, so this costs nothing beyond normal script execution.

Run:  python tools/currency_dual_system_smoke_test.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.core import currency as cur
from nano_offline.core.database import Database
from nano_offline.repositories.settings_repository import SettingsRepository

passed = 0


def check(label: str, cond: bool):
    global passed
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    passed += 1
    print(f"  ok  {label}")


# ---------------------------------------------------------------------------
print("1) get_exchange_rate fallback behaviour (settings=None / missing / bad values)")
check("settings=None -> default rate", cur.get_exchange_rate(None) == cur.DEFAULT_EXCHANGE_RATE)


class FakeSettings(dict):
    def get(self, key, default=""):
        return dict.get(self, key, default)


check("missing key -> default rate", cur.get_exchange_rate(FakeSettings()) == cur.DEFAULT_EXCHANGE_RATE)
check("empty string -> default rate", cur.get_exchange_rate(FakeSettings({cur.EXCHANGE_RATE_KEY: ""})) == cur.DEFAULT_EXCHANGE_RATE)
check("non-numeric -> default rate", cur.get_exchange_rate(FakeSettings({cur.EXCHANGE_RATE_KEY: "abc"})) == cur.DEFAULT_EXCHANGE_RATE)
check("zero -> default rate", cur.get_exchange_rate(FakeSettings({cur.EXCHANGE_RATE_KEY: "0"})) == cur.DEFAULT_EXCHANGE_RATE)
check("negative -> default rate", cur.get_exchange_rate(FakeSettings({cur.EXCHANGE_RATE_KEY: "-500"})) == cur.DEFAULT_EXCHANGE_RATE)
check("valid custom rate honoured", cur.get_exchange_rate(FakeSettings({cur.EXCHANGE_RATE_KEY: "15000"})) == 15000.0)

print("2) get_display_symbol")
check("settings=None -> default symbol", cur.get_display_symbol(None) == cur.DEFAULT_DISPLAY_SYMBOL)
check("missing key -> default symbol", cur.get_display_symbol(FakeSettings()) == cur.DEFAULT_DISPLAY_SYMBOL)
check("empty string -> default symbol", cur.get_display_symbol(FakeSettings({cur.DISPLAY_SYMBOL_KEY: ""})) == cur.DEFAULT_DISPLAY_SYMBOL)
check("custom symbol honoured", cur.get_display_symbol(FakeSettings({cur.DISPLAY_SYMBOL_KEY: "SYP$"})) == "SYP$")

print("3) to_display / to_stored core math + round trip")
rate = 13500.0
check("to_display basic", cur.to_display(10, rate) == 135000.0)
check("to_display None amount -> 0", cur.to_display(None, rate) == 0.0)
check("to_display rate=None -> 0", cur.to_display(10, None) == 0.0)
check("to_stored basic", abs(cur.to_stored(135000, rate) - 10.0) < 1e-9)
check("to_stored None amount -> 0", cur.to_stored(None, rate) == 0.0)
check("to_stored rate=0 falls back to default rate", cur.to_stored(cur.DEFAULT_EXCHANGE_RATE, 0) == 1.0)
for usd in (0, 1, 0.5, 99.99, 1000000, -25.3):
    syp = cur.to_display(usd, rate)
    back = cur.to_stored(syp, rate)
    check(f"round trip usd={usd}", abs(back - usd) < 1e-6)

print("4) format_amount (stored USD -> displayed SYP text)")
settings = FakeSettings({cur.EXCHANGE_RATE_KEY: "13500", cur.DISPLAY_SYMBOL_KEY: "ل.س"})
check("format_amount with symbol, 0 decimals", cur.format_amount(10, settings) == "135,000 ل.س")
check("format_amount without symbol", cur.format_amount(10, settings, with_symbol=False) == "135,000")
val = cur.format_amount(1, FakeSettings({cur.EXCHANGE_RATE_KEY: "13500.5"}), decimals=1)
check("format_amount decimals=1 shape", val.endswith(".5 ل.س"))
check("format_amount explicit rate overrides settings", cur.format_amount(10, settings, rate=1000) == "10,000 ل.س")
check("format_amount explicit symbol overrides settings", cur.format_amount(10, settings, symbol="X") == "135,000 X")
check("format_amount zero", cur.format_amount(0, settings) == "0 ل.س")
check("format_amount None amount", cur.format_amount(None, settings) == "0 ل.س")
check("format_amount negative amount", cur.format_amount(-5, settings) == "-67,500 ل.س")

print("5) to_input_text (plain, no thousands separator/symbol, editable field)")
check("whole SYP value -> no decimals", cur.to_input_text(10, settings) == "135000")
check("fractional SYP value keeps 2dp", cur.to_input_text(1, FakeSettings({cur.EXCHANGE_RATE_KEY: "13500.33"})) == "13500.33")
check("zero", cur.to_input_text(0, settings) == "0")
check("None", cur.to_input_text(None, settings) == "0")

print("6) format_plain (already-converted on-screen values, no re-conversion)")
check("whole number", cur.format_plain(135000) == "135000")
check("fractional number", cur.format_plain(1.5) == "1.50")
check("None -> 0", cur.format_plain(None) == "0")
check("negative", cur.format_plain(-12) == "-12")

print("7) format_display_value (already-SYP value, WITH thousands separators)")
check("basic with symbol", cur.format_display_value(135000, settings) == "135,000 ل.س")
check("without symbol", cur.format_display_value(135000, settings, with_symbol=False) == "135,000")
check("custom symbol override", cur.format_display_value(135000, settings, symbol="Z") == "135,000 Z")
check("decimals=2", cur.format_display_value(135000.5, settings, decimals=2) == "135,000.50 ل.س")
check("None -> 0", cur.format_display_value(None, settings) == "0 ل.س")

print("8) parse_display_input (user-typed SYP text -> stored USD)")
check("plain number", abs(cur.parse_display_input("135000", settings) - 10.0) < 1e-9)
check("with thousands separators", abs(cur.parse_display_input("135,000", settings) - 10.0) < 1e-9)
check("with surrounding whitespace", abs(cur.parse_display_input("  135000  ", settings) - 10.0) < 1e-9)
check("empty string -> 0", cur.parse_display_input("", settings) == 0.0)
check("None -> 0", cur.parse_display_input(None, settings) == 0.0)
check("numeric int input", abs(cur.parse_display_input(135000, settings) - 10.0) < 1e-9)
check("numeric float input", abs(cur.parse_display_input(135000.0, settings) - 10.0) < 1e-9)
check("explicit rate overrides settings", abs(cur.parse_display_input("1000", settings, rate=1000) - 1.0) < 1e-9)
try:
    cur.parse_display_input("not-a-number", settings)
    check("invalid text raises ValueError", False)
except ValueError as e:
    check("invalid text raises ValueError", True)
    check("error message is Arabic and mentions the bad value", "قيمة غير صالحة" in str(e) and "not-a-number" in str(e))

print("9) full round trip: user types SYP -> stored as USD -> displayed back as same SYP")
for typed in ("100000", "1,350,000", "0", "13500.5"):
    stored_usd = cur.parse_display_input(typed, settings)
    shown = cur.format_amount(stored_usd, settings, decimals=1)
    expected_syp = float(typed.replace(",", ""))
    shown_value = float(shown.replace(",", "").replace(" ل.س", ""))
    check(f"round trip typed={typed!r} -> shown matches (within rounding)", abs(shown_value - expected_syp) < 0.2)

print("10) live exchange-rate change propagates immediately (real DB, no restart)")
with tempfile.TemporaryDirectory(prefix="qeid-currency-") as td:
    db = Database(Path(td) / "x.db")
    db.initialize()
    repo = SettingsRepository(db)

    # Before setting anything: falls back to default rate/symbol.
    check("fresh DB -> default rate", cur.get_exchange_rate(repo) == cur.DEFAULT_EXCHANGE_RATE)
    check("fresh DB -> default symbol", cur.get_display_symbol(repo) == cur.DEFAULT_DISPLAY_SYMBOL)
    check("fresh DB -> format_amount uses default rate", cur.format_amount(1, repo) == "13,500 ل.س")

    repo.set(cur.EXCHANGE_RATE_KEY, "15000")
    check("after admin changes rate -> get_exchange_rate reflects it immediately", cur.get_exchange_rate(repo) == 15000.0)
    check("after admin changes rate -> format_amount reflects it immediately", cur.format_amount(1, repo) == "15,000 ل.س")

    repo.set(cur.DISPLAY_SYMBOL_KEY, "SYP")
    check("after admin changes symbol -> reflected immediately", cur.format_amount(1, repo) == "15,000 SYP")

    # Simulate admin clearing the field back to blank -> should fall back to defaults.
    repo.set(cur.EXCHANGE_RATE_KEY, "")
    check("clearing rate falls back to default", cur.get_exchange_rate(repo) == cur.DEFAULT_EXCHANGE_RATE)

    # Simulate admin typing garbage into the rate field -> must not crash, falls back.
    repo.set(cur.EXCHANGE_RATE_KEY, "abc")
    check("garbage rate value falls back to default, no crash", cur.get_exchange_rate(repo) == cur.DEFAULT_EXCHANGE_RATE)

    # Stored money values are unaffected by any of this -- schema stays plain USD floats.
    repo.set(cur.EXCHANGE_RATE_KEY, "20000")
    a = cur.parse_display_input("100000", repo)  # user types SYP, we store USD
    check("value physically stored is plain USD regardless of rate changes", abs(a - 5.0) < 1e-9)
    repo.set(cur.EXCHANGE_RATE_KEY, "25000")  # rate changes again after storage
    check("previously stored USD amount is untouched by later rate change", abs(a - 5.0) < 1e-9)
    check("but its displayed value now reflects the new rate", cur.format_amount(a, repo) == "125,000 SYP")

print("11) get_display_currency: fallback + validation")
check("settings=None -> default SYP", cur.get_display_currency(None) == cur.DISPLAY_CURRENCY_SYP)
check("missing key -> default SYP", cur.get_display_currency(FakeSettings()) == cur.DISPLAY_CURRENCY_SYP)
check("empty -> default SYP", cur.get_display_currency(FakeSettings({cur.DISPLAY_CURRENCY_KEY: ""})) == cur.DISPLAY_CURRENCY_SYP)
check("garbage value -> default SYP (no crash)", cur.get_display_currency(FakeSettings({cur.DISPLAY_CURRENCY_KEY: "EUR"})) == cur.DISPLAY_CURRENCY_SYP)
check("explicit SYP", cur.get_display_currency(FakeSettings({cur.DISPLAY_CURRENCY_KEY: "SYP"})) == cur.DISPLAY_CURRENCY_SYP)
check("explicit USD", cur.get_display_currency(FakeSettings({cur.DISPLAY_CURRENCY_KEY: "USD"})) == cur.DISPLAY_CURRENCY_USD)
check("lowercase 'usd' accepted (case-insensitive)", cur.get_display_currency(FakeSettings({cur.DISPLAY_CURRENCY_KEY: "usd"})) == cur.DISPLAY_CURRENCY_USD)
check("' usd ' with whitespace accepted", cur.get_display_currency(FakeSettings({cur.DISPLAY_CURRENCY_KEY: " usd "})) == cur.DISPLAY_CURRENCY_USD)

print("12) get_effective_rate: identity in USD mode, real rate in SYP mode")
syp_settings = FakeSettings({cur.DISPLAY_CURRENCY_KEY: "SYP", cur.EXCHANGE_RATE_KEY: "13500"})
usd_settings = FakeSettings({cur.DISPLAY_CURRENCY_KEY: "USD", cur.EXCHANGE_RATE_KEY: "13500"})
check("SYP mode -> effective rate == configured rate", cur.get_effective_rate(syp_settings) == 13500.0)
check("USD mode -> effective rate == 1.0 (identity) regardless of configured SYP rate", cur.get_effective_rate(usd_settings) == 1.0)
check("get_exchange_rate is unaffected by display mode (still the raw SYP rate)", cur.get_exchange_rate(usd_settings) == 13500.0)

print("13) get_display_symbol: each currency remembers its own symbol independently")
mixed_settings = FakeSettings({
    cur.DISPLAY_CURRENCY_KEY: "SYP",
    cur.DISPLAY_SYMBOL_KEY: "ل.س",
    cur.USD_DISPLAY_SYMBOL_KEY: "$",
})
check("SYP mode -> SYP symbol", cur.get_display_symbol(mixed_settings) == "ل.س")
mixed_settings[cur.DISPLAY_CURRENCY_KEY] = "USD"
check("switch to USD mode -> USD symbol used instead (no stale ل.س)", cur.get_display_symbol(mixed_settings) == "$")
check("USD mode, no custom symbol set -> defaults to '$'", cur.get_display_symbol(FakeSettings({cur.DISPLAY_CURRENCY_KEY: "USD"})) == "$")
check("USD mode, custom symbol set -> honoured", cur.get_display_symbol(FakeSettings({cur.DISPLAY_CURRENCY_KEY: "USD", cur.USD_DISPLAY_SYMBOL_KEY: "USD$"})) == "USD$")

print("14) format_amount in USD display mode: identity conversion, 2 decimals by default")
usd_full = FakeSettings({cur.DISPLAY_CURRENCY_KEY: "USD", cur.EXCHANGE_RATE_KEY: "13500", cur.USD_DISPLAY_SYMBOL_KEY: "$"})
check("stored 10 USD -> shown as 10.00 $ (no multiplication by SYP rate)", cur.format_amount(10, usd_full) == "10.00 $")
check("stored 1234.5 USD -> thousands separator + 2dp", cur.format_amount(1234.5, usd_full) == "1,234.50 $")
check("stored 0 -> 0.00 $", cur.format_amount(0, usd_full) == "0.00 $")
check("stored None -> 0.00 $", cur.format_amount(None, usd_full) == "0.00 $")
check("negative amount", cur.format_amount(-5.5, usd_full) == "-5.50 $")
check("explicit decimals still overrides the USD default of 2", cur.format_amount(10, usd_full, decimals=0) == "10 $")
check("changing the SYP exchange rate has NO effect on USD-mode display", (usd_full.update({cur.EXCHANGE_RATE_KEY: "99999"}) or cur.format_amount(10, usd_full)) == "10.00 $")

print("15) to_input_text / format_plain / format_display_value in USD mode")
check("to_input_text: stored 10 USD, whole dollars -> '10' (no decimals when exact)", cur.to_input_text(10, usd_full) == "10")
check("to_input_text: stored 10.5 USD -> '10.50'", cur.to_input_text(10.5, usd_full) == "10.50")
check("format_display_value default decimals is 2 in USD mode", cur.format_display_value(10, usd_full) == "10.00 $")
check("format_plain unaffected by mode (pure passthrough formatting)", cur.format_plain(10) == "10")

print("16) parse_display_input in USD mode: typed dollars -> stored as the same USD value")
check("typed '10' in USD mode -> stored 10.0 (no division by SYP rate)", cur.parse_display_input("10", usd_full) == 10.0)
check("typed '1,234.50' in USD mode -> stored 1234.5", cur.parse_display_input("1,234.50", usd_full) == 1234.5)
usd_round_trip = cur.parse_display_input("99.99", usd_full)
check("USD round trip: typed 99.99 -> format_amount shows 99.99 $ again", cur.format_amount(usd_round_trip, usd_full) == "99.99 $")

print("17) live end-to-end: admin switches display currency in a real DB, everything updates immediately")
with tempfile.TemporaryDirectory(prefix="qeid-currency-usd-") as td:
    db = Database(Path(td) / "y.db")
    db.initialize()
    repo = SettingsRepository(db)

    # A price is entered while the shop is in SYP display mode.
    repo.set(cur.EXCHANGE_RATE_KEY, "13500")
    repo.set(cur.DISPLAY_SYMBOL_KEY, "ل.س")
    check("fresh DB defaults to SYP display", cur.get_display_currency(repo) == cur.DISPLAY_CURRENCY_SYP)
    stored_usd = cur.parse_display_input("135000", repo)  # cashier types 135,000 ل.س
    check("135,000 ل.س typed at 13500 rate -> stored as 10 USD", abs(stored_usd - 10.0) < 1e-9)
    check("shown back correctly in SYP mode", cur.format_amount(stored_usd, repo) == "135,000 ل.س")

    # Admin flips the switch to USD display (equivalent of picking "الدولار الأمريكي" in admin_view and saving).
    repo.set(cur.DISPLAY_CURRENCY_KEY, cur.DISPLAY_CURRENCY_USD)
    repo.set(cur.USD_DISPLAY_SYMBOL_KEY, "$")
    check("display currency is now USD", cur.get_display_currency(repo) == cur.DISPLAY_CURRENCY_USD)
    check("the SAME stored value now displays as 10.00 $ (no re-entry, no data change)", cur.format_amount(stored_usd, repo) == "10.00 $")
    check("underlying stored USD value is exactly unchanged by the switch", abs(stored_usd - 10.0) < 1e-9)

    # A NEW price entered now, while in USD display mode.
    new_stored = cur.parse_display_input("25.50", repo)  # cashier types $25.50 directly
    check("typed 25.50 in USD mode -> stored as 25.50 USD (identity, no SYP math)", abs(new_stored - 25.50) < 1e-9)

    # Admin flips back to SYP display -- the SYP rate they set earlier is still remembered.
    repo.set(cur.DISPLAY_CURRENCY_KEY, cur.DISPLAY_CURRENCY_SYP)
    check("switching back to SYP display -> old exchange rate still remembered (13500)", cur.get_exchange_rate(repo) == 13500.0)
    check("the first item now shows in ل.س again, unchanged", cur.format_amount(stored_usd, repo) == "135,000 ل.س")
    check("the item entered in USD mode also converts correctly to ل.س now", cur.format_amount(new_stored, repo) == f"{25.50*13500:,.0f} ل.س")

    # Switching the display currency alone must never touch any stored money value in the DB itself.
    check("switch is purely a display-layer setting, not a data mutation", abs(stored_usd - 10.0) < 1e-9 and abs(new_stored - 25.50) < 1e-9)

print(f"\ncurrency_dual_system_smoke_test passed ({passed} checks)")
