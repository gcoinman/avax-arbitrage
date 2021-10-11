#encoding=‘utf-8’
import sys
import os
from os import path
parent_path = os.path.dirname(os.getcwd())
sys.path.append(parent_path)
from arbitrage.dexswap import DexSwap

dex_swap = DexSwap(None, False)
dex_swap.show_balances()