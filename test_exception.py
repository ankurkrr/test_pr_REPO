# test_exception.py

import json


def parse_json(data):

    try:
        return json.loads(data)

    except:
        # Catching everything is dangerous
        return {}