from playwright.sync_api import sync_playwright
import subprocess, time, sys

server = subprocess.Popen(
    [sys.executable, '-m', 'http.server', '9900', '--directory', r'D:\CODE\SSLAB-WWW\frontend'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(1)

JS = """
() => {
    var sheets = document.styleSheets;
    var info = [];
    for(var i=0;i<sheets.length;i++){
        var s = sheets[i];
        try { info.push(s.href + ' -> ' + s.cssRules.length + ' rules'); }
        catch(e) { info.push(s.href + ' -> ERROR: ' + e.message); }
    }
    // Also check if pull-left float applied
    var el = document.querySelector('.pull-left');
    if(el) {
        var cs = window.getComputedStyle(el);
        info.push('pull-left float: ' + cs.float);
    }
    return info;
}
"""

try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})

        responses = []
        page.on('response', lambda r: responses.append((r.url, r.status)) if 'css' in r.url else None)

        page.goto('http://localhost:9900/index.html', wait_until='networkidle')
        page.wait_for_timeout(500)

        for url, status in responses:
            print(f'CSS {status}: {url}')

        result = page.evaluate(JS)
        for r in result:
            print(r)

        browser.close()
finally:
    server.terminate()
