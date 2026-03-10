# test_crypto.py

import random


def generate_token():

    token = ""

    for i in range(32):
        token += str(random.randint(0, 9))

    return token