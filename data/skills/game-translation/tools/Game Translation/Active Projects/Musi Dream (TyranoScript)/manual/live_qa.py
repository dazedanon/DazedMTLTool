"""Explicit local CDP test actions; receives JavaScript on stdin to avoid shell quoting."""
import json
import sys
from cdp_client import CDPClient

with CDPClient(timeout=25) as cdp:
    if sys.argv[1] == 'eval':
        result = cdp.evaluate(sys.stdin.read())
    elif sys.argv[1] == 'screenshot':
        result = str(cdp.screenshot(sys.argv[2]))
    else:
        try:
            result = cdp.call(sys.argv[1])
        except ConnectionError:
            if sys.argv[1] != 'Browser.close':
                raise
            result = {'closed': True}
    print(json.dumps(result, ensure_ascii=True, indent=2))
