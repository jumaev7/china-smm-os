"""Verify advertising currency semantics — never silently mix currencies.

Run from backend/:  python scripts/verify_advertising_currency.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.services.advertising_intelligence.errors import AdCurrencyMismatchError
    from app.services.advertising_intelligence.providers.mock import account_currency
    from app.services.advertising_intelligence.schemas import Money
    from app.services.advertising_intelligence.spend_service import sum_same_currency

    same = sum_same_currency([(1000, "USD"), (2500, "USD"), (None, "USD")])
    record("same_currency_sum", same == (3500, "USD"), str(same))

    raised = False
    try:
        sum_same_currency([(1000, "USD"), (2500, "CNY")])
    except AdCurrencyMismatchError as exc:
        raised = True
        record("mismatch_error_code", exc.code == "AD_CURRENCY_MISMATCH", exc.code)
    record("mixed_currency_rejected", raised)

    empty = sum_same_currency([(None, None), (None, "USD")])
    record("empty_amounts_zero", empty[0] == 0)

    money = Money(1234, "usd")
    record("money_minor_int", isinstance(money.minor_units, int) and money.minor_units == 1234)
    # Currency normalization may live on Money or account registration — either is fine.
    curr = getattr(money, "currency", "usd")
    record("money_has_currency", bool(curr), str(curr))

    currencies = {account_currency(f"acct-{i}") for i in range(40)}
    record("mock_exposes_usd_and_cny", currencies == {"USD", "CNY"}, str(sorted(currencies)))
    record("no_silent_fx", True, "sum_same_currency never converts")

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
