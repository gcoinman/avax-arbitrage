import time
import base64
import hmac
import urllib.request
import urllib.parse
import urllib.error
import urllib.request
import urllib.error
import urllib.parse
import hashlib
import threading
import sys
import os
import json
import math
import requests
file_path = os.path.dirname(os.path.realpath(__file__))
parent_path = os.path.dirname(file_path)
sys.path.append(parent_path)
from arbitrage.config import *
from binance.client import Client
from unicorn_binance_websocket_api.unicorn_binance_websocket_api_manager import BinanceWebSocketApiManager
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from arbitrage.logger import Logger
from Crypto.Cipher import AES
from binascii import b2a_hex, a2b_hex
import getpass
from decimal import *

def round_down(n, precision=0):
    if precision > 0.99999:
        precision = int(precision)
    return float(Decimal(str(n)).quantize(Decimal(str(precision))))
    
class BinanceMarket(object):
    def __init__(self, _log):
        super().__init__()
        self.log = _log
        self.create_client()
        self.precisions = self.get_precision()
        self.markets = [asset + 'USDT' for asset in assets if asset != 'USDT' and asset != 'DAI']
        self.markets += ['USDTDAI']
        self.depths = {}
        self.init_borrow_limit()
        self.bal_reduced = {}
        self.reset_bal_reduce()
        self.last_spot_balance_update_time = 0
        self.last_margin_balance_update_time = 0
        self.spot_balances = {}
        self.margin_balances = {}

    def init_borrow_limit(self):
        self.borrow_limits = {}
        self.last_reset_update_times = {}
        for asset in assets:
            if asset in spot_assets:
                continue
            self.borrow_limits[asset] = 0
            self.last_reset_update_times[asset] = 0

    def reset_bal_reduce(self):
        for asset in assets:
            self.bal_reduced[asset] = 0
        self.bal_reduced['AAVX'] = 20000

    def get_precision(self):
        precisions = {}
        exinfo = self.client.get_exchange_info()
        for asset in assets:
            if asset == 'USDT':
                continue
            pair = asset+'USDT'
            for info in exinfo["symbols"]:
                if pair == info['symbol']:
                    ticksize = float(info["filters"][0]['tickSize'])
                    minqty = float(info["filters"][2]['minQty'])
                    precisions[pair] = [ticksize, minqty]
        return precisions


    def create_client(self):
        self.public = 'Jw3uUtZjmoye0Fs01lyTY9QxO59RmSN200KAZGxLEXMFDSAaXZDM4TtOs5Ewuxey'
        self.secret = 'AaXfunWRnJTPKqeWHuDf4E5QvbVFCN7YuQocd0nANRqEvl5rRPQxhO1NJNhP1mmE'
        self.client = Client(self.public, self.secret)

    def margin_get_borrow_limit(self, asset):
        current_reset_update_time = time.time()
        if current_reset_update_time - self.last_reset_update_times[asset] < 20:
            return self.borrow_limits[asset]
        self.last_reset_update_times[asset] = current_reset_update_time
        response = self.client.get_max_margin_loan(
            asset=asset,
            timestamp=self._timestamp()
        )
        self.borrow_limits[asset] = float(response['amount'])
        return self.borrow_limits[asset]

    def margin_borrow_asset(self, asset, amount):
        try:
            response = self.client.create_margin_loan(
                asset=asset,
                amount=amount,
                timestamp=self._timestamp()
            )
            self.log.logger.info('Loan tranId='+str(response['tranId'])+',amount='+str(amount))
            return True
        except Exception as e:
            print('margin borrow exception: {}'.format(str(e)))
            return False

    def margin_buy(self, asset, amount, price):
        buy_action = 'buy {}, amount {}, price {}'.format(asset, amount, price)
        order = None
        try:
            precis = self.precisions[asset + 'USDT']
            price = round_down(price, precis[0])
            amount = round_down(amount, precis[1])
            free_bal = self.margin_get_balance('USDT')
            usdt_needed = round_down(amount * price * 1.003, 1) + 1
            if free_bal < usdt_needed:
                bamount = usdt_needed - free_bal
                if bamount < 5:
                    amount = round_down(free_bal * 0.997 / price, precis[1])
                else:
                    if not self.margin_borrow_asset('USDT', bamount):
                        raise Exception('margin borrow USDT failed')
            order = self.client.create_margin_order(
                symbol=asset + 'USDT',
                side=self.client.SIDE_BUY,
                type=self.client.ORDER_TYPE_LIMIT,
                timeInForce=self.client.TIME_IN_FORCE_GTC,
                quantity=amount,
                price=price,
                timestamp=self._timestamp())
        except Exception as e:
            self.log.logger.info('xxxxx--cex buy exception: {}'.format(str(e)))
            self.log.logger.info('xxxxx--cex buy exception: {}'.format(buy_action))
        finally:
            if order is None or "clientOrderId" not in order:
                self.log.logger.info('margin {}: order is none buy clientOrderId not in order'.format(buy_action))
                time.sleep(2)
                return self.margin_buy(asset, amount, price)
            self.log.logger.info('cex {} succeed'.format(buy_action))

    def margin_sell(self, asset, amount, price):
        sell_action = 'sell {}, amount {}, price {}'.format(asset, amount, price)
        order = None
        failed = False
        try:
            precis = self.precisions[asset + 'USDT']
            price = round_down(price, precis[0])
            amount = round_down(amount, precis[1])
            free_bal = self.margin_get_balance(asset)
            if free_bal < amount * 1.003:
                bamount = round_down(amount * 1.01 - free_bal, precis[1])
                if bamount * price < 5:
                    amount = round_down(free_bal, precis[1])
                else:
                    if not self.margin_borrow_asset(asset, bamount):
                        self.log.logger.info('margin borrow {} failed'.format(asset))
                        failed = True
                        return
                        # raise Exception('margin borrow {} failed'.format(asset))
            order = self.client.create_margin_order(
                symbol=asset + 'USDT',
                side=self.client.SIDE_SELL,
                type=self.client.ORDER_TYPE_LIMIT,
                timeInForce=self.client.TIME_IN_FORCE_GTC,
                quantity=amount,
                price=price,
                timestamp=self._timestamp())
        except Exception as e:
            self.log.logger.info('xxxxx--cex sell exception: {}'.format(str(e)))
            self.log.logger.info('xxxxx--cex sell exception: {}'.format(sell_action))
        finally:
            if failed:
                return
            if order is None or "clientOrderId" not in order:
                self.log.logger.info('margin {}: order is none or sell clientOrderId not in order'.format(sell_action))
                time.sleep(2)
                return self.margin_sell(asset, amount, price)
            self.log.logger.info('cex {} succeed'.format(sell_action))

    def _timestamp(self):
        return int(time.time() * 1000)

    def margin_get_balances(self):
        response = self.client.get_margin_account()
        margin_balances_info = response['userAssets']
        for asset_info in margin_balances_info:
            self.margin_balances[asset_info['asset']] = float(asset_info['free'])

    def margin_get_balance_with_borrow(self, asset):
        current_reset_update_time = time.time()
        if current_reset_update_time - self.last_margin_balance_update_time > 20:
            self.margin_get_balances()
            self.last_margin_balance_update_time = current_reset_update_time
        borrow_limit = self.margin_get_borrow_limit(asset)
        reduce = 0
        if asset in self.bal_reduced:
            reduce = self.bal_reduced[asset]
        return (self.margin_balances[asset] + borrow_limit) * 0.95 - reduce

    def margin_get_balance(self, asset):
        if asset in self.margin_balances:
            return self.margin_balances[asset]
        return 0

    def spot_get_balances(self):
        response = self.client.get_account()
        spot_balances_info = response['balances']
        for asset_info in spot_balances_info:
            self.spot_balances[asset_info['asset']] = float(asset_info['free'])

    def spot_get_balance(self, asset):
        current_reset_update_time = time.time()
        if current_reset_update_time - self.last_spot_balance_update_time > 20:
            self.spot_get_balances()
            self.last_spot_balance_update_time = current_reset_update_time
        reduce = 0
        if asset in self.bal_reduced:
            reduce = self.bal_reduced[asset]
        if asset in self.spot_balances:
            return self.spot_balances[asset] * 99 / 100 - reduce
        return 0

    def spot_buy(self, asset, amount, price):
        buy_action = 'buy {}, amount {}, price {}'.format(asset, amount, price)
        order = None
        org_amount = amount
        org_price = price
        try:
            symbol=asset + 'USDT'
            side=self.client.SIDE_BUY
            precis = self.precisions[symbol]
            price = round_down(price, precis[0])
            amount = round_down(amount, precis[1])
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=self.client.ORDER_TYPE_LIMIT,
                timeInForce=self.client.TIME_IN_FORCE_GTC,
                quantity=amount,
                price=price,
                timestamp=self._timestamp())
        except Exception as e:
            self.log.logger.info('xxxxx--cex buy exception: {}'.format(str(e)))
            self.log.logger.info('xxxxx--cex buy exception: {}'.format(buy_action))
        finally:
            if order is None or "clientOrderId" not in order:
                self.log.logger.info('spot {}: order is none or clientOrderId not in order'.format(buy_action))
                time.sleep(2)
                return self.spot_buy(asset, amount, price)
            self.log.logger.info('cex {} succeed'.format(buy_action))

    def spot_sell(self, asset, amount, price):
        sell_action = 'sell {}, amount {}, price {}'.format(asset, amount, price)
        order = None
        org_price = price
        try:
            balance = self.spot_get_balance(asset)
            new_amount = balance * 0.999
            if new_amount < amount and new_amount > amount * 0.85:
                amount = new_amount
            symbol=asset + 'USDT'
            side=self.client.SIDE_SELL
            precis = self.precisions[symbol]
            price = round_down(price, precis[0])
            amount = round_down(amount, precis[1])
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=self.client.ORDER_TYPE_LIMIT,
                timeInForce=self.client.TIME_IN_FORCE_GTC,
                quantity=amount,
                price=price,
                timestamp=self._timestamp())
        except Exception as e:
            self.log.logger.info('xxxxx--cex sell exception: {}'.format(str(e)))
            self.log.logger.info('xxxxx--cex sell exception: {}'.format(sell_action))
        finally:
            if order is None or "clientOrderId" not in order:
                self.log.logger.info('spot {}: order is none or clientOrderId not in order'.format(sell_action))
                time.sleep(2)
                return self.spot_sell(asset, amount, price)
            self.log.logger.info('cex {} succeed'.format(sell_action))

    def get_balance_with_borrow(self, asset):
        if asset == 'DAI':
            return 10 ** 18
        if asset not in spot_assets:
            return self.margin_get_balance_with_borrow(asset)
        else:
            return self.spot_get_balance(asset)

    def buy(self, asset, amount, price):
        if asset not in spot_assets:
            self.margin_buy(asset, amount, price)
        else:
            self.spot_buy(asset, amount, price)
    
    def sell(self, asset, amount, price):
        if asset not in spot_assets:
            self.margin_sell(asset, amount, price)
        else:
            self.spot_sell(asset, amount, price)


    def start_update_depth(self):
        self.binance_websocket_api_manager = BinanceWebSocketApiManager()
        self.binance_websocket_api_manager.create_stream(["depth5"], self.markets)
        worker_thread = threading.Thread(target=self.get_stream_data_from_stream_buffer, args=(self.binance_websocket_api_manager,))
        worker_thread.start()

    def get_stream_data_from_stream_buffer(self, binance_websocket_api_manager):
        while True:
            if binance_websocket_api_manager.is_manager_stopping():
                sys.exit(0)
            stream_data = binance_websocket_api_manager.pop_stream_data_from_stream_buffer()
            if stream_data is False:
                time.sleep(0.01)
            else:
                try:
                    # remove # to activate the print function:
                    stream = json.loads(stream_data)
                    if 'stream' in stream:
                        symbol = stream['stream'].replace("@depth5", "").upper();
                        self.depths[symbol] = {'timestamp': self._timestamp(), 'bids': stream['data']['bids'], 'asks': stream['data']['asks']}
                        # print(self.depths)
                except KeyError:
                    pass


    def spot_stream_data_from_stream_buffer(self, binance_websocket_api_manager):
        while True:
            if binance_websocket_api_manager.is_manager_stopping():
                exit(0)
            oldest_stream_data_from_stream_buffer = binance_websocket_api_manager.pop_stream_data_from_stream_buffer()
            if oldest_stream_data_from_stream_buffer is False:
                time.sleep(0.01)
            else:
                # print(oldest_stream_data_from_stream_buffer)
                stream = json.loads(oldest_stream_data_from_stream_buffer)
                if 'e' in stream and stream['e'] == 'outboundAccountPosition':
                    for bal in stream['B']:
                        self.spot_balances[bal['a']] = float(bal['f'])

    def update_spot_userdata(self):
        binance_com_websocket_api_manager = BinanceWebSocketApiManager(exchange="binance.com",
                                                               throw_exception_if_unrepairable=True)
        binance_com_user_data_stream_id = binance_com_websocket_api_manager.create_stream('arr', '!userData',
                                                                                  api_key=self.public,
                                                                                  api_secret=self.secret)
        # start a worker process to move the received stream_data from the stream_buffer to a print function
        worker_thread = threading.Thread(target=self.spot_stream_data_from_stream_buffer, args=(binance_com_websocket_api_manager,))
        worker_thread.start()

    def margin_stream_data_from_stream_buffer(self, binance_websocket_api_manager):
        while True:
            if binance_websocket_api_manager.is_manager_stopping():
                exit(0)
            oldest_stream_data_from_stream_buffer = binance_websocket_api_manager.pop_stream_data_from_stream_buffer()
            if oldest_stream_data_from_stream_buffer is False:
                time.sleep(0.01)
            else:
                # print(oldest_stream_data_from_stream_buffer)
                stream = json.loads(oldest_stream_data_from_stream_buffer)
                if 'e' in stream and stream['e'] == 'outboundAccountPosition':
                    for bal in stream['B']:
                        self.margin_balances[bal['a']] = float(bal['f'])

    def update_margin_userdata(self):
        binance_com_websocket_api_manager = BinanceWebSocketApiManager(exchange="binance.com-margin",
                                                               throw_exception_if_unrepairable=True)
        binance_com_user_data_stream_id = binance_com_websocket_api_manager.create_stream('arr', '!userData',
                                                                                  api_key=self.public,
                                                                                  api_secret=self.secret)
        # start a worker process to move the received stream_data from the stream_buffer to a print function
        worker_thread = threading.Thread(target=self.margin_stream_data_from_stream_buffer, args=(binance_com_websocket_api_manager,))
        worker_thread.start()

if __name__ == "__main__":
    log = Logger('all.log',level='debug')
    binance = BinanceMarket(log)
    binance.update_spot_userdata()
    binance.update_margin_userdata()
    time.sleep(1000)
 