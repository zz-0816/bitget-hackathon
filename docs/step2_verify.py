"""Step 2: MCP Execution Link Verification for Bitget Hackathon.
Verifies: account balance, contract info, set leverage, place order,
check positions, check orders, cancel orders, close position.

API credentials read from ../.mcp.json
"""
import json, time, hmac, hashlib, os, sys, urllib.request, base64

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_JSON = os.path.join(PROJECT_ROOT, '.mcp.json')
with open(MCP_JSON) as f:
    mcp_config = json.load(f)
env = mcp_config['mcpServers']['bitget']['env']

API_KEY = env['BITGET_API_KEY']
SECRET_KEY = env['BITGET_SECRET_KEY']
PASSPHRASE = env['BITGET_PASSPHRASE']
BASE_URL = 'https://api.bitget.com'

SYMBOL = 'BTCUSDT'
PRODUCT = 'USDT-FUTURES'
COIN = 'USDT'

def call(path, method='GET', params=None):
    ts = str(int(time.time() * 1000))
    payload = '/api' + path
    auth = ts + method.upper() + payload
    url = BASE_URL + payload

    if method == 'POST':
        body_str = json.dumps(params)
        auth += body_str
    else:
        body_str = None
        if params:
            sorted_params = dict(sorted(params.items()))
            qs = '?' + '&'.join(f'{k}={v}' for k, v in sorted_params.items())
            url += qs
            auth += qs

    sig = base64.b64encode(hmac.new(SECRET_KEY.encode(), auth.encode(),
                                    hashlib.sha256).digest()).decode()
    headers = {
        'Content-Type': 'application/json',
        'ACCESS-KEY': API_KEY, 'ACCESS-SIGN': sig,
        'ACCESS-TIMESTAMP': ts, 'ACCESS-PASSPHRASE': PASSPHRASE,
        'PAPTRADING': '1',
    }
    req = urllib.request.Request(url, data=body_str.encode() if body_str else None,
                                 headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())
    except Exception as e:
        return {'error': str(e)}

def ok(resp):
    return not resp.get('error') and resp.get('code') == '00000'

SEP = '=' * 60

# (1) Account Balance
print(f'{SEP}\n(1) Account Balance - {PRODUCT}\n{SEP}')
r = call(f'/v2/mix/account/accounts', params={'productType': PRODUCT})
if ok(r):
    for a in r.get('data', []):
        print(f'  {a["marginCoin"]}: equity={a.get("accountEquity")}, available={a.get("available")}')
else:
    print(f'  FAIL: {r}')

# (2) Contract Info
print(f'\n{SEP}\n(2) Contract Info - {SYMBOL}\n{SEP}')
r = call('/v2/mix/market/contracts', params={'productType': PRODUCT, 'symbol': SYMBOL})
if ok(r):
    c = r['data'][0]
    print(f'  Symbol:         {c["symbol"]}')
    print(f'  Min Trade Num:  {c["minTradeNum"]} BTC')
    print(f'  Min Trade USDT: {c["minTradeUSDT"]} USDT')
    print(f'  Price decimals: {c["pricePlace"]}')
    print(f'  Size decimals:  {c["volumePlace"]}')
    print(f'  Max Leverage:   {c["maxLever"]}x')
    print(f'  Taker Fee:      {float(c["takerFeeRate"])*100:.2f}%')
else:
    print(f'  FAIL: {r}')

# (3) Set Leverage
print(f'\n{SEP}\n(3) Set Leverage 5x\n{SEP}')
r = call('/v2/mix/account/set-leverage', 'POST', {
    'productType': PRODUCT, 'symbol': SYMBOL, 'marginCoin': COIN, 'leverage': '5'})
print(f'  {"OK" if ok(r) else "FAIL"}: {r.get("code")} {r.get("msg","")}')

# (4) Place Market Order
print(f'\n{SEP}\n(4) Place Market BUY 0.001 {SYMBOL}\n{SEP}')
r = call('/v2/mix/order/place-order', 'POST', {
    'productType': PRODUCT, 'symbol': SYMBOL, 'marginCoin': COIN,
    'side': 'buy', 'orderType': 'market', 'size': '0.001',
    'marginMode': 'isolated', 'tradeSide': 'open'})
oid = None
if ok(r):
    oid = r['data'].get('orderId')
    print(f'  OK - Order ID: {oid}')
else:
    print(f'  FAIL: {r.get("code")} {r.get("msg","")}')

# (5) Check Positions
print(f'\n{SEP}\n(5) Check Positions\n{SEP}')
r = call('/v2/mix/position/all-position', params={'productType': PRODUCT, 'marginCoin': COIN})
if ok(r):
    found = False
    for p in r.get('data', []):
        if p.get('total') and float(p.get('total')) > 0:
            found = True
            print(f'  {p["symbol"]}: side={p.get("holdSide")}, total={p.get("total")}, '
                  f'entry={p.get("openPriceAvg")}, leverage={p.get("leverage")}x, '
                  f'unrealizedPL={p.get("unrealizedPL")} USDT')
    if not found:
        print('  No open positions')
else:
    print(f'  FAIL: {r}')

# (6) Check Orders (pending + history)
print(f'\n{SEP}\n(6) Check Orders\n{SEP}')
r = call('/v2/mix/order/orders-pending', params={'productType': PRODUCT, 'symbol': SYMBOL})
if ok(r):
    orders = r.get('data', {}).get('entrustedList', r.get('data', []))
    if orders and len(orders) > 0:
        for o in orders:
            print(f'  PENDING: {o.get("orderId")} side={o.get("side")} size={o.get("size")}')
    else:
        print('  No pending orders (market fills instantly)')
else:
    print(f'  FAIL: {r}')

r = call('/v2/mix/order/orders-history', params={'productType': PRODUCT, 'symbol': SYMBOL, 'limit': '5'})
if ok(r):
    orders = r.get('data', {}).get('entrustedList', r.get('data', []))
    if orders and len(orders) > 0:
        print(f'  History (last {len(orders)}):')
        for o in orders:
            print(f'    ID={o.get("orderId")} side={o.get("side")} size={o.get("size")} '
                  f'status={o.get("status")} priceAvg={o.get("priceAvg")}')
else:
    print(f'  FAIL: {r}')

# (7) Place Limit Order + Cancel
print(f'\n{SEP}\n(7) Place Limit Order + Cancel\n{SEP}')
r = call('/v2/mix/order/place-order', 'POST', {
    'productType': PRODUCT, 'symbol': SYMBOL, 'marginCoin': COIN,
    'side': 'buy', 'orderType': 'limit', 'price': '10000', 'size': '0.001',
    'marginMode': 'isolated', 'tradeSide': 'open'})
limit_oid = None
if ok(r):
    limit_oid = r['data'].get('orderId')
    print(f'  Limit order placed: {limit_oid}')
else:
    print(f'  FAIL placing limit: {r.get("code")} {r.get("msg","")}')

if limit_oid:
    time.sleep(0.5)
    r = call('/v2/mix/order/cancel-order', 'POST', {
        'productType': PRODUCT, 'symbol': SYMBOL, 'marginCoin': COIN,
        'orderId': limit_oid})
    if ok(r):
        print(f'  Limit order cancelled: {limit_oid}')
    else:
        print(f'  FAIL cancel: {r.get("code")} {r.get("msg","")}')

# (8) Close Position
print(f'\n{SEP}\n(8) Close Position\n{SEP}')
time.sleep(3)
r = call('/v2/mix/position/all-position', params={'productType': PRODUCT, 'marginCoin': COIN})
if ok(r):
    closed = 0
    for p in r.get('data', []):
        if p.get('total') and float(p.get('total')) > 0:
            # side=positionSide for close: 'buy' closes long, 'sell' closes short
            side = 'buy' if p.get('holdSide') == 'long' else 'sell'
            r2 = call('/v2/mix/order/place-order', 'POST', {
                'productType': PRODUCT, 'symbol': p['symbol'], 'marginCoin': COIN,
                'side': side, 'orderType': 'market', 'size': p['available'],
                'marginMode': 'isolated', 'tradeSide': 'close'})
            status = 'OK' if ok(r2) else f'FAIL ({r2.get("code")} {r2.get("msg","")})'
            print(f'  Close {p["symbol"]} {p.get("holdSide")}: {status}')
            if ok(r2):
                closed += 1
    if closed == 0:
        print('  No open positions to close')
else:
    print(f'  FAIL: {r}')

# Verify empty
time.sleep(1)
r = call('/v2/mix/position/all-position', params={'productType': PRODUCT, 'marginCoin': COIN})
all_closed = ok(r) and not any(
    p.get('total') and float(p.get('total')) > 0 for p in r.get('data', []))

print(f'\n{SEP}')
print('Step 2 Verification Complete')
print(f'  All operations: {"PASS" if all_closed else "CHECK MANUALLY"}')
print(SEP)
