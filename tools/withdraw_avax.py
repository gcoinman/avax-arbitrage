import sys
import os
from os import path
parent_path = os.path.dirname(os.getcwd())
sys.path.append(parent_path)
from arbitrage.config import *
from arbitrage.key import *
from binance.client import Client
import time
public = key_public
secret = key_secret
client = Client(public, secret)

wallet = 'X-avax109720ndy68598nrpdz2h5h677v39spgh66r4sf'

def withdrow(amount):
    return client.withdraw(
        coin='AVAX',
        address=wallet,
        amount=amount,
        network='AVAX')

if __name__ == "__main__":
    withdraw_amount_str = input("input withdraw amount:")
    withdraw_amount2_str = input("input withdraw amount again:")
    withdraw_amount = float(withdraw_amount_str)
    withdraw_amount2 = float(withdraw_amount2_str)
    withdrow(withdraw_amount)
                    
