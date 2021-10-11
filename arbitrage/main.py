# Copyright (C) 2013, Maxime Biais <maxime@biais.org>

import time
import logging
import json
import threading
import sys
import os
from brownie import *
file_path = os.path.dirname(os.path.realpath(__file__))
parent_path = os.path.dirname(file_path)
sys.path.append(parent_path)
from config import *
from binancemarket import BinanceMarket, round_down
from dexswap import DexSwap
from concurrent.futures import ThreadPoolExecutor, wait
from logger import Logger
import func_timeout
from func_timeout import func_set_timeout

def get_valid_depth(depths, symbol):
    if symbol == 'DAIUSDT':
        symbol = 'USDTDAI'
    if symbol == 'USDTUSDT':
        return symbol
    if symbol not in depths:
        return None 
    depth = depths[symbol]
    if depth is None:
        return None
    if symbol == 'USDTDAI':
        new_depth = {}
        new_depth['asks'] = [[1 / float(d[0]), float(d[0]) * float(d[1])] for d in depth['bids']]
        new_depth['bids'] = [[1 / float(d[0]), float(d[0]) * float(d[1])] for d in depth['asks']]
        return new_depth
    cur_timestamp = int(time.time() * 1000)
    if symbol == 'BUSDUSDT' or symbol == 'BETHETH':
        return depth
    if cur_timestamp - depth['timestamp'] > 20 * 1000:
        return None
    return depth

def get_depth_volume_price(index, depth):
    if depth == 'USDTUSDT':
        return 1, 10 ** 10, 1, 10 ** 10
    buy_price = float(depth['asks'][index][0])
    sell_price = float(depth['bids'][index][0])
    buy_volume = 0
    for i in range(index + 1):
        buy_volume += float(depth["asks"][i][1])
    sell_volume = 0
    for i in range(index + 1):
        sell_volume += float(depth["bids"][i][1])
    return buy_price, buy_volume, sell_price, sell_volume


log = Logger('all.log',level='info')
dex_swap = DexSwap(log)
binance = BinanceMarket(log)


thread_count = 5
threadpool = ThreadPoolExecutor(max_workers=thread_count)
tasks = {}

total_profit = 0
avax_buy_price = 1

def main_new_arbitrage(dex_side, base_asset, quote_asset, amount_in, output_amount, dexname):
    global total_profit
    global avax_buy_price
    gasfee = 0
    try:
        if dex_side == 'buy':
            ret, real_output_amount, gasfee = dex_swap.buy(base_asset, quote_asset+dexname, amount_in, output_amount)
            if not ret:
                binance.bal_reduced[base_asset] -= output_amount / 10 ** 18
                dex_swap.bal_reduced[quote_asset] -= amount_in	            
                total_profit -= gasfee * avax_buy_price
                log.logger.info('{} dex buy fail, gasfee is {:.4f}, total_profit is {:.4f}'.format(dexname, gasfee * avax_buy_price, total_profit))
                return
            cex_token_sell_amount = output_amount / 10 ** 18
            quote_token_buy_amount = amount_in / 10 ** 18
            base_symbol = base_asset+'USDT'
            base_depth = get_valid_depth(binance.depths, base_symbol)
            _, _, cex_sell_price, _ = get_depth_volume_price(4, base_depth)
            if base_symbol != 'USDTUSDT' and base_symbol != 'DAIUSDT' and base_symbol != 'USDCUSDT':
                binance.sell(base_asset, cex_token_sell_amount, cex_sell_price)
            quote_symbol = quote_asset+'USDT'
            quote_depth = get_valid_depth(binance.depths, quote_symbol)
            quote_buy_price, _, _, _ = get_depth_volume_price(4, quote_depth)
            if quote_symbol != 'USDTUSDT' and quote_symbol != 'DAIUSDT' and quote_symbol != 'USDCUSDT':
                binance.buy(quote_asset, quote_token_buy_amount, quote_buy_price)
            profit = cex_token_sell_amount * cex_sell_price * (1 - fee) - quote_token_buy_amount * quote_buy_price - gasfee * avax_buy_price
            binance.bal_reduced[base_asset] -= output_amount / 10 ** 18
            total_profit += profit
        elif dex_side == 'sell':
            ret, real_output_amount, gasfee = dex_swap.sell(base_asset, quote_asset+dexname, amount_in, output_amount)
            if not ret:
                binance.bal_reduced[quote_asset] -= output_amount / 10 ** 18
                dex_swap.bal_reduced[base_asset] -= amount_in
                total_profit -= gasfee * avax_buy_price
                log.logger.info('{} dex sell fail, gasfee is {:.4f}, total_profit is {:.4f}'.format(dexname, gasfee * avax_buy_price, total_profit))                        
                return
            cex_token_buy_amount = amount_in / 10 ** 18
            quote_token_sell_amount = output_amount / 10 ** 18
            base_symbol = base_asset+'USDT'
            base_depth = get_valid_depth(binance.depths, base_symbol)
            cex_buy_price, _, _, _ = get_depth_volume_price(3, base_depth)
            if base_symbol != 'USDTUSDT' and base_symbol != 'DAIUSDT' and base_symbol != 'USDCUSDT':
                binance.buy(base_asset, cex_token_buy_amount, cex_buy_price)
            quote_symbol = quote_asset+'USDT'
            quote_depth = get_valid_depth(binance.depths, quote_symbol)
            _, _, quote_sell_price, _ = get_depth_volume_price(3, quote_depth)
            if quote_symbol != 'USDTUSDT' and quote_symbol != 'DAIUSDT' and quote_symbol != 'USDCUSDT':
                binance.sell(quote_asset, quote_token_sell_amount, quote_sell_price)
            profit = quote_token_sell_amount * quote_sell_price - cex_token_buy_amount * cex_buy_price * (1 + fee) - gasfee * avax_buy_price
            binance.bal_reduced[quote_asset] -= quote_token_sell_amount
            total_profit += profit
            
        gas_info = 'gasfee: {}'.format(gasfee * avax_buy_price)
        print(gas_info)
        log.logger.info(gas_info)
        profit_info = 'this arbitrage profit is: {0:.4f} USDT, total profit is: {1:.4f} USDT'.format(profit, total_profit)
        print(profit_info)
        log.logger.info(profit_info)
        print('{} dex {} end'.format(base_asset+quote_asset, dex_side))
    except func_timeout.exceptions.FunctionTimedOut:
        print('main_new_arbitrage time out')
    except Exception as e:
        print(e)

def clear_complete_task(tasks):
    for key in list(tasks.keys()):
        if tasks[key].done():
            del tasks[key]
    return len(list(tasks.keys()))

def common_pair_arbitrage(dexname):
    global avax_buy_price
    try:
        avax_depth = get_valid_depth(binance.depths, 'AVAXUSDT')
        if avax_depth is None:
            return
        avax_buy_price, _, _, _ = get_depth_volume_price(4, avax_depth)
        real_pairs = []
        if dexname == 'PANGOLIN':
            real_pairs = pangolin_pairs
        elif dexname == 'JOEXYZ':
            real_pairs = joexyz_pairs

        for s_pair in real_pairs:
            org_pair = s_pair
            s_pair = s_pair.replace(dexname, '')
            symbols = s_pair.split("_")
            base_depth = get_valid_depth(binance.depths, symbols[0]+'USDT')
            quote_depth = get_valid_depth(binance.depths, symbols[1]+'USDT')
            if base_depth is None or quote_depth is None:
                print(symbols)
                print('{} base or quote depth is none'.format(dexname))
                continue
            base_buy_price, base_buy_volume, base_sell_price, base_sell_volume = get_depth_volume_price(4, base_depth)
            quote_buy_price, quote_buy_volume, quote_sell_price, quote_sell_volume = get_depth_volume_price(4, quote_depth)
            # 同一个交易对只能有一个线程，防止重复交易
            l = clear_complete_task(tasks)
            # 超过10个线程后，会有线程被阻塞，影响实时成交，降低成功率
            if l > thread_count:
                print('working task > {}'.format(thread_count))
                return
            if s_pair in tasks:
                continue
            min_profit = min_profit1
            base_min_amount = 200 / base_buy_price
            quote_min_amount = 200 / quote_buy_price
            dex_buy_price = dex_swap.get_price(symbols[0], symbols[1]+dexname, 'buy', quote_min_amount * 10 ** 18, dexname)
            dex_sell_price = dex_swap.get_price(symbols[0], symbols[1]+dexname, 'sell', base_min_amount * 10 ** 18, dexname)
            cex_buy_price = base_buy_price / quote_sell_price
            cex_sell_price = base_sell_price / quote_buy_price
            if cex_sell_price > dex_buy_price * (1 + price_percent_difference_threshold):
                dex_quote_bal = dex_swap.asset_balance(symbols[1])
                dex_base_bal = dex_swap.asset_balance(symbols[0])
                if symbols[0] in max_on_chain_balances and max_on_chain_balances[symbols[0]] < dex_base_bal / 10 ** 18:
                    print('{} dex balance={}, exceed max cap, dex cannot buy it'.format(symbols[0], dex_base_bal / 10 ** 18))
                    continue
                cex_base_bal = binance.get_balance_with_borrow(symbols[0])
                max_quote_trade_amount = max_usdt_trade_amount / quote_buy_price
                dex_trade_amount = min(10 ** 18 * max_quote_trade_amount, dex_quote_bal, 10 ** 18 * min(cex_base_bal, base_sell_volume) * cex_sell_price, 10 ** 18 * quote_buy_volume) * 98 / 100  
                price_limit = (cex_sell_price / (1 + price_percent_difference_threshold))
                if dex_trade_amount * quote_buy_price < 40 * 10 ** 18:
                    continue
                price, dex_quote_trade_amount = dex_swap.binary_search(symbols[0], symbols[1]+dexname, dex_trade_amount, 'buy', price_limit, dexname)
                cex_base_sell_amount = dex_swap.extGetOutputAmount(dex_quote_trade_amount, symbols[1], symbols[0], dexname) / 10 ** 18
                cex_quote_buy_amount = dex_quote_trade_amount / 10 ** 18
                profit = cex_base_sell_amount * base_sell_price * (1 - fee) - cex_quote_buy_amount * quote_buy_price * (1 + fee)
                if profit < min_profit:
                    # print('{} {} trade amount is {:.4f}, profit is {:.4f} USDT, too low!'.format(dexname, s_pair, cex_quote_buy_amount, profit))
                    continue
                print('\n', '-'*30, '\n{} {} arbitrage profit is {:.4f}, cex sell price is {:.4f}, amount is {:.4f}, dex buy price is {:.4f}'.format(dexname, s_pair, profit, cex_sell_price, cex_base_sell_amount, price))
                binance.bal_reduced[symbols[0]] += cex_base_sell_amount * 1.01
                dex_swap.bal_reduced[symbols[1]] += dex_trade_amount * 1.01
                # main_new_arbitrage('buy', symbols[0], symbols[1], dex_quote_trade_amount,  cex_base_sell_amount * 10 ** 18, dexname)
                tasks[s_pair] = threadpool.submit(main_new_arbitrage, 'buy', symbols[0], symbols[1], dex_quote_trade_amount,  cex_base_sell_amount * 10 ** 18, dexname)
                continue
            elif cex_buy_price < dex_sell_price / (1 + price_percent_difference_threshold):
                dex_base_bal = dex_swap.asset_balance(symbols[0])
                cex_quote_bal = binance.get_balance_with_borrow(symbols[1])
                max_base_trade_amount = max_usdt_trade_amount / base_buy_price
                dex_trade_amount = min(dex_base_bal, 10 ** 18 * max_base_trade_amount, 10 ** 18 * min(cex_quote_bal, quote_sell_volume) * quote_sell_price / base_buy_price, 10 ** 18 * base_buy_volume) * 98 / 100
                price_limit = cex_buy_price * (1 + price_percent_difference_threshold)
                if dex_trade_amount * base_buy_price < 40 * 10 ** 18:
                    continue
                price, dex_base_trade_amount = dex_swap.binary_search(symbols[0], symbols[1]+dexname, dex_trade_amount, 'sell', price_limit, dexname)
                cex_quote_sell_amount = dex_swap.extGetOutputAmount(dex_base_trade_amount, symbols[0], symbols[1], dexname) / 10 ** 18
                cex_base_buy_amount = dex_base_trade_amount / 10 ** 18
                profit = cex_quote_sell_amount * quote_sell_price * (1 - fee) - cex_base_buy_amount * base_buy_price * (1 + fee)
                if profit < min_profit:
                    # print('{} {} trade amount is {:.4f}, profit is {:.4f} USDT, too low!'.format(dexname, s_pair, cex_quote_sell_amount, profit))
                    continue
                print('\n', '-'*30, '\n{} {} arbitrage profit is {:.4f}, cex buy price is {:.4f}, amount is {:.4f}, dex sell price is {:.4f}'.format(dexname, s_pair, profit, cex_buy_price, cex_base_buy_amount, dex_sell_price))
                binance.bal_reduced[symbols[1]] += cex_quote_sell_amount * 1.01
                dex_swap.bal_reduced[symbols[0]] += dex_trade_amount * 1.01
                # main_new_arbitrage('sell', symbols[0], symbols[1], dex_base_trade_amount, cex_quote_sell_amount * 10 ** 18, dexname)
                tasks[s_pair] = threadpool.submit(main_new_arbitrage, 'sell', symbols[0], symbols[1], dex_base_trade_amount, cex_quote_sell_amount * 10 ** 18, dexname)
                continue
    except func_timeout.exceptions.FunctionTimedOut:
        print('main_pair_arbitrage time out')
    except Exception as e:
        print(e)


def multi_hop_new_arbitrage(dex_side, base_asset, mid_asset, quote_asset, amount_in, output_amount, dexname):
    global total_profit
    global avax_buy_price
    gasfee = 0
    try:
        if dex_side == 'buy':
            ret, real_output_amount, gasfee = dex_swap.buy_multi_hop(base_asset, mid_asset, quote_asset + dexname, amount_in, output_amount)
            if not ret:
                binance.bal_reduced[base_asset] -= output_amount / 10 ** 18
                dex_swap.bal_reduced[quote_asset] -= amount_in	            
                total_profit -= gasfee * avax_buy_price
                log.logger.info('{} dex buy fail, gasfee is {:.4f}, total_profit is {:.4f}'.format(dexname, gasfee * avax_buy_price, total_profit))
                return
            cex_token_sell_amount = output_amount / 10 ** 18
            quote_token_buy_amount = amount_in / 10 ** 18
            base_symbol = base_asset+'USDT'
            base_depth = get_valid_depth(binance.depths, base_symbol)
            _, _, cex_sell_price, _ = get_depth_volume_price(4, base_depth)
            if base_symbol != 'USDTUSDT' and base_symbol != 'DAIUSDT' and base_symbol != 'USDCUSDT':
                binance.sell(base_asset, cex_token_sell_amount, cex_sell_price)
            quote_symbol = quote_asset+'USDT'
            quote_depth = get_valid_depth(binance.depths, quote_symbol)
            quote_buy_price, _, _, _ = get_depth_volume_price(4, quote_depth)
            if quote_symbol != 'USDTUSDT' and quote_symbol != 'DAIUSDT' and quote_symbol != 'USDCUSDT':
                binance.buy(quote_asset, quote_token_buy_amount, quote_buy_price)
            profit = cex_token_sell_amount * cex_sell_price * (1 - fee) - quote_token_buy_amount * quote_buy_price - gasfee * avax_buy_price
            binance.bal_reduced[base_asset] -= output_amount / 10 ** 18
            total_profit += profit
        elif dex_side == 'sell':
            ret, real_output_amount, gasfee = dex_swap.sell_multi_hop(base_asset, mid_asset, quote_asset + dexname, amount_in, output_amount)
            if not ret:
                binance.bal_reduced[quote_asset] -= output_amount / 10 ** 18
                dex_swap.bal_reduced[base_asset] -= amount_in
                total_profit -= gasfee * avax_buy_price
                log.logger.info('{} dex sell fail, gasfee is {:.4f}, total_profit is {:.4f}'.format(dexname, gasfee * avax_buy_price, total_profit))                        
                return
            cex_token_buy_amount = amount_in / 10 ** 18
            quote_token_sell_amount = output_amount / 10 ** 18
            base_symbol = base_asset+'USDT'
            base_depth = get_valid_depth(binance.depths, base_symbol)
            cex_buy_price, _, _, _ = get_depth_volume_price(3, base_depth)
            if base_symbol != 'USDTUSDT' and base_symbol != 'DAIUSDT' and base_symbol != 'USDCUSDT':
                binance.buy(base_asset, cex_token_buy_amount, cex_buy_price)
            quote_symbol = quote_asset+'USDT'
            quote_depth = get_valid_depth(binance.depths, quote_symbol)
            _, _, quote_sell_price, _ = get_depth_volume_price(3, quote_depth)
            if quote_symbol != 'USDTUSDT' and quote_symbol != 'DAIUSDT' and quote_symbol != 'USDCUSDT':
                binance.sell(quote_asset, quote_token_sell_amount, quote_sell_price)
            profit = quote_token_sell_amount * quote_sell_price - cex_token_buy_amount * cex_buy_price * (1 + fee) - gasfee * avax_buy_price
            binance.bal_reduced[quote_asset] -= quote_token_sell_amount
            total_profit += profit
            
        gas_info = 'gasfee: {}'.format(gasfee * avax_buy_price)
        print(gas_info)
        log.logger.info(gas_info)
        profit_info = 'this arbitrage profit is: {0:.4f} USDT, total profit is: {1:.4f} USDT'.format(profit, total_profit)
        print(profit_info)
        log.logger.info(profit_info)
        print('{} dex {} end'.format(base_asset+quote_asset, dex_side))
    except func_timeout.exceptions.FunctionTimedOut:
        print('main_new_arbitrage time out')
    except Exception as e:
        print(e)

def common_multi_hop_arbitrage(dexname):
    global avax_buy_price
    try:
        avax_depth = get_valid_depth(binance.depths, 'AVAXUSDT')
        if avax_depth is None:
            return
        real_multi_pairs = []
        if dexname == 'PANGOLIN':
            real_multi_pairs = dex_swap.pangolin_multi_pairs
        elif dexname == 'JOEXYZ':
            real_multi_pairs = dex_swap.joexyz_multi_pairs

        avax_buy_price, _, _, _ = get_depth_volume_price(4, avax_depth)
        for s_pair in real_multi_pairs:
            symbols = s_pair.split("_")
            base_depth = get_valid_depth(binance.depths, symbols[0]+'USDT')
            quote_depth = get_valid_depth(binance.depths, symbols[2]+'USDT')
            if base_depth is None or quote_depth is None:
                print('{} depth is none'.format(s_pair))
                continue
            base_buy_price, base_buy_volume, base_sell_price, base_sell_volume = get_depth_volume_price(4, base_depth)
            quote_buy_price, quote_buy_volume, quote_sell_price, quote_sell_volume = get_depth_volume_price(4, quote_depth)
            # 同一个交易对只能有一个线程，防止重复交易
            l = clear_complete_task(tasks)
            # 超过10个线程后，会有线程被阻塞，影响实时成交，降低成功率
            if l > thread_count:
                print('working task > {}'.format(thread_count))
                return
            if s_pair in tasks:
                continue
            min_profit = min_profit1
            base_min_amount = 200 / base_buy_price
            quote_min_amount = 200 / quote_buy_price
            dex_buy_price = dex_swap.get_price_multi_hop(symbols[0], symbols[1], symbols[2]+dexname, 'buy', quote_min_amount * 10 ** 18, dexname)
            dex_sell_price = dex_swap.get_price_multi_hop(symbols[0], symbols[1], symbols[2]+dexname, 'sell', base_min_amount * 10 ** 18, dexname)
            cex_buy_price = base_buy_price / quote_sell_price
            cex_sell_price = base_sell_price / quote_buy_price
            if cex_sell_price > dex_buy_price * (1 + price_percent_difference_threshold):
                dex_quote_bal = dex_swap.asset_balance(symbols[2])
                dex_base_bal = dex_swap.asset_balance(symbols[0])
                if symbols[0] in max_on_chain_balances and max_on_chain_balances[symbols[0]] < dex_base_bal / 10 ** 18:
                    print('{} dex balance={}, exceed max cap, dex cannot buy it use {}'.format(symbols[0], dex_base_bal / 10 ** 18, symbols[2]))
                    continue
                cex_base_bal = binance.get_balance_with_borrow(symbols[0])
                max_quote_trade_amount = max_usdt_trade_amount / quote_buy_price
                dex_trade_amount = min(10 ** 18 * max_quote_trade_amount, dex_quote_bal, 10 ** 18 * min(cex_base_bal, base_sell_volume) * cex_sell_price, 10 ** 18 * quote_buy_volume) * 98 / 100  
                price_limit = (cex_sell_price / (1 + price_percent_difference_threshold))
                if dex_trade_amount * quote_buy_price < 100 * 10 ** 18:
                    continue
                price, dex_quote_trade_amount = dex_swap.binary_search_multi_hop(symbols[0], symbols[1], symbols[2]+dexname, dex_trade_amount, 'buy', price_limit, dexname)
                cex_base_sell_amount = dex_swap.extGetOutputAmountMultiHop(dex_quote_trade_amount, symbols[2], symbols[1], symbols[0], dexname) / 10 ** 18
                cex_quote_buy_amount = dex_quote_trade_amount / 10 ** 18
                profit = cex_base_sell_amount * base_sell_price * (1 - fee) - cex_quote_buy_amount * quote_buy_price * (1 + fee)
                if profit < min_profit:
                    # print('{} {} trade amount is {:.4f}, profit is {:.4f} USDT, too low!'.format(dexname, s_pair, cex_quote_buy_amount, profit))
                    continue
                print('\n', '-'*30, '\n{} {} arbitrage profit is {:.4f}, cex sell price is {:.4f}, amount is {:.4f}, dex buy price is {:.4f}'.format(dexname, s_pair, profit, cex_sell_price, cex_base_sell_amount, price))
                binance.bal_reduced[symbols[0]] += cex_base_sell_amount * 1.01
                dex_swap.bal_reduced[symbols[2]] += dex_trade_amount * 1.01
                # multi_hop_new_arbitrage('buy', symbols[0], symbols[1], symbols[2], dex_quote_trade_amount, cex_base_sell_amount * 10 ** 18, dexname)
                tasks[s_pair] = threadpool.submit(multi_hop_new_arbitrage, 'buy', symbols[0], symbols[1], symbols[2], dex_quote_trade_amount, cex_base_sell_amount * 10 ** 18, dexname)
                continue
            elif cex_buy_price < dex_sell_price / (1 + price_percent_difference_threshold):
                dex_base_bal = dex_swap.asset_balance(symbols[0])
                dex_quote_bal = dex_swap.asset_balance(symbols[2])
                if symbols[2] in max_on_chain_balances and max_on_chain_balances[symbols[2]] < dex_quote_bal / 10 ** 18:
                    print('{} dex balance={}, exceed max cap, dex cannot buy it use {}'.format(symbols[2], dex_quote_bal / 10 ** 18, symbols[0]))
                    continue
                cex_quote_bal = binance.get_balance_with_borrow(symbols[2])
                max_base_trade_amount = max_usdt_trade_amount / base_buy_price
                dex_trade_amount = min(dex_base_bal, 10 ** 18 * max_base_trade_amount, 10 ** 18 * min(cex_quote_bal, quote_sell_volume) * quote_sell_price / base_buy_price, 10 ** 18 * base_buy_volume) * 98 / 100
                price_limit = cex_buy_price * (1 + price_percent_difference_threshold)
                if dex_trade_amount * base_buy_price < 100 * 10 ** 18:
                    continue
                price, dex_base_trade_amount = dex_swap.binary_search_multi_hop(symbols[0], symbols[1], symbols[2]+dexname, dex_trade_amount, 'sell', price_limit, dexname)
                cex_quote_sell_amount = dex_swap.extGetOutputAmountMultiHop(dex_base_trade_amount, symbols[0], symbols[1], symbols[2], dexname) / 10 ** 18
                cex_base_buy_amount = dex_base_trade_amount / 10 ** 18
                profit = cex_quote_sell_amount * quote_sell_price * (1 - fee) - cex_base_buy_amount * base_buy_price * (1 + fee)
                if profit < min_profit:
                    # print('{} {} trade amount is {:.4f}, profit is {:.4f} USDT, too low!'.format(dexname, s_pair, cex_quote_sell_amount, profit))
                    continue
                print('\n', '-'*30, '\n{} {} arbitrage profit is {:.4f}, cex buy price is {:.4f}, amount is {:.4f}, dex sell price is {:.4f}'.format(dexname, s_pair, profit, cex_buy_price, cex_base_buy_amount, dex_sell_price))
                binance.bal_reduced[symbols[2]] += cex_quote_sell_amount * 1.01
                dex_swap.bal_reduced[symbols[0]] += dex_trade_amount * 1.01
                # multi_hop_new_arbitrage('sell', symbols[0], symbols[1], symbols[2], dex_base_trade_amount, cex_quote_sell_amount * 10 ** 18, dexname)
                tasks[s_pair] = threadpool.submit(multi_hop_new_arbitrage, 'sell', symbols[0], symbols[1], symbols[2], dex_base_trade_amount, cex_quote_sell_amount * 10 ** 18, dexname)
                continue
    except func_timeout.exceptions.FunctionTimedOut:
        print('main_pair_arbitrage time out')
    except Exception as e:
        print(e)

def set_working_flag(status: str):
    file_path =  os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + '/tools/flag'
    with open(file_path, 'w') as f:
        f.write(status)

def wait_for_withdraw_complete(wid):
    while(True):
        try:
            print('\nwait for AVAX withdraw to dex complete, pending id:\n')
            print(wid)
            withdraw_list = binance.client.get_withdraw_history(status=2)
            withdraw_list += binance.client.get_withdraw_history(status=4)
            withdraw_list += binance.client.get_withdraw_history(status=6)
            find_item = False
            for item in withdraw_list:
                if item['id'] != wid:
                    continue
                find_item = True
                if 'txId' not in item:
                    continue
                txid = item['txId']
                tx = chain.get_transaction(txid)
                while(tx==None or tx.status==None or tx.status < 0):
                    print('withdraw tx status is {}'.format(tx.status))
                    time.sleep(0.3)
                if tx.status == 1:
                    print('{} withdraw succeed, amount={}, txid={}'.format(item['coin'], item['amount'], txid))
                    return
                else:
                    print('txid={} status={}'.format(txid, tx.status))
                break
            if not find_item:
                print('Cannot find AVAX withdraw ID!')
   
            withdraw_list = binance.client.get_withdraw_history(status=3)
            withdraw_list += binance.client.get_withdraw_history(status=5)
            print('get completed withdraw history')
            for item in withdraw_list:
                if item['id'] == wid:
                    print('AVAX withdraw complete')
                    return
        except Exception as e:
            print('wait_for_withdraw_complete exception')
            log.logger.info('wait_for_withdraw_complete exception: {}'.format(str(e)))
        finally:
            time.sleep(3)


def wait_for_deposit_complete(txid):
    while(True):
        try:
            print('\nwait for AVAX deposit to cex complete, pending txid:\n')
            print(txid)
            deposit_list = binance.client.get_deposit_history(status=1)
            for item in deposit_list:
                if item['txId'] == txid:
                    print('{} deposit succeed, amount is {}'.format(item['coin'], item['amount']))
                    return
        finally:
            time.sleep(3)

def get_asset_info(**params):
    return binance.client._request_margin_api('get', 'capital/config/getall', True, data=params)

def is_withdraw_enable(assets_info):
    for asset_info in assets_info:
        if asset_info['coin'].upper() == 'AVAX':
            for network in asset_info['networkList']:
                if network['network'] == 'AVAXC':
                    return network['withdrawEnable']
    return False

def is_deposit_enable(assets_info):
    for asset_info in assets_info:
        if asset_info['coin'].upper() == 'AVAX':
            for network in asset_info['networkList']:
                if network['network'] == 'AVAXC':
                    return network['depositEnable']
    return False

def check_avax_balance():
    while(True):
        try:
            spot_avax_bal = binance.spot_get_balance('AVAX')
            assets_info = get_asset_info(timestamp = int(time.time() * 1000))
            dex_avax_bal = dex_swap.asset_balance('AVAX') / 10 ** 18
            withdraw_amount = 2000
            if dex_avax_bal < 1500 and is_withdraw_enable(assets_info):
                print('AVAX withdraw to dex wallet')
                binance.client.transfer_margin_to_spot(
                        asset='AVAX',
                        amount=withdraw_amount)
                time.sleep(1)
                resp = binance.client.withdraw(
                    coin='AVAX',
                    address='0x20243F4081b0F777166F656871b61c2792FB4124',
                    amount=withdraw_amount,
                    network='AVAXC')
                wait_for_withdraw_complete(resp['id'])
            if dex_avax_bal > 9000 and is_deposit_enable(assets_info):
                deposit_amount = dex_avax_bal - 8000
                print('AVAX deposit to cex amount is {}'.format(deposit_amount))
                txid = dex_swap.transfer_avax(deposit_amount * 10 ** 18)
                if txid is None:
                    time.sleep(3)
                    continue
                wait_for_deposit_complete(txid)
        except func_timeout.exceptions.FunctionTimedOut:
            print('check_avax_balance time out')
        except Exception as e:
            print(e)
        finally:
            time.sleep(10)

def main():
    binance.start_update_depth()
    binance.update_spot_userdata()
    binance.update_margin_userdata()
    dex_swap.update_information()
    t = threading.Thread(target=check_avax_balance)
    t.start()
    while True:
        try:
            dex_swap.check_status()
            dex_swap.update_information()
            l = clear_complete_task(tasks)
            if l == 0:
                dex_swap.reset_bal_reduce()
                binance.reset_bal_reduce()

            common_pair_arbitrage('PANGOLIN')
            common_pair_arbitrage('JOEXYZ')
            common_multi_hop_arbitrage('PANGOLIN')
            common_multi_hop_arbitrage('JOEXYZ')

            l = clear_complete_task(tasks)
            if l > 0:
                set_working_flag('true')
            else:
                set_working_flag('false')
        except func_timeout.exceptions.FunctionTimedOut:
            print('update_information time out')
        except Exception as e:
            print(e)
        finally:
            time.sleep(0.5)

if __name__ == '__main__':
    main()
