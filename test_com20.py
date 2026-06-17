import urllib.request, json, time

seen = set()
print('持续监控中，你发数据后会立即显示新日志...')
for _ in range(60):
    try:
        req = urllib.request.urlopen('http://192.168.0.101/api/status', timeout=3)
        data = json.loads(req.read())
        for l in data.get('logs', []):
            key = l.get('timestamp','') + l.get('message','')[:30]
            if key not in seen:
                seen.add(key)
                ts = l.get('timestamp','')
                lvl = l.get('level','')
                msg = l.get('message','')
                print('[NEW]', ts, '['+lvl+']', msg)
    except Exception as e:
        print('ERR:', e)
    time.sleep(1)
print('监控结束')
