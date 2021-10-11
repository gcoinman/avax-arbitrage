import pytest
import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__)))+'/arbitrage')
from arbitrage.binancemargin import BinanceMargin

@pytest.mark.skip
def test_get_precision():
    market = BinanceMargin()
    response = market.get_precision()
    print(response)

@pytest.mark.skip
def test_borrow_limit():
    market = BinanceMargin()
    response = market.get_borrow_limit('XTZ')
    print(response)

@pytest.mark.skip
def test_margin_borrow():
    market = BinanceMargin()
    market.borrow_asset('TRX', 500)

@pytest.mark.skip
def test_margin_buy():
    market = BinanceMargin()
    market.buy('BCHUSDT', 1, 200)

@pytest.mark.skip
def test_margin_sell():
    market = BinanceMargin()
    market.sell('BCHUSDT', 1, 300)

@pytest.mark.skip
def test_margin_getbalances():
    market = BinanceMargin()
    response = market.get_balances()
    print(response)


if __name__ == '__main__':
    pytest.main(["-s", "./tests/test_binance.py"]) # 调用pytest的main函数执行测试