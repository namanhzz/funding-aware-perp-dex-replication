from perp_mm_funding.backtest.accounting import Account


def test_accounting_funding_payment_sign_for_long_inventory():
    account = Account(cash=0.0, inventory=2.0)
    payment = account.apply_funding(mid_price=100.0, funding_rate=0.001)
    assert payment == 0.2
    assert account.cash == -0.2

