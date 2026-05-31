import time, os, threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

class CSSHandler(SimpleHTTPRequestHandler):
    def guess_type(self, path):
        if str(path).endswith(".css"):
            return "text/css; charset=utf-8"
        return super().guess_type(path)
    def log_message(self, *args):
        pass

def run_server():
    os.chdir(r"D:\CODE\SSLAB-WWW\frontend")
    httpd = HTTPServer(("localhost", 9900), CSSHandler)
    httpd.serve_forever()

t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(0.8)

OUT_DIR = r"D:\CODE\SSLAB-WWW\docs\screenshots"
os.makedirs(OUT_DIR, exist_ok=True)

BASE_INJECT = """() => {
    document.querySelectorAll(".status-badge.disconnected").forEach(el => {
        el.textContent = "已连接";
        el.classList.remove("disconnected");
        el.classList.add("connected");
    });
    var v = document.getElementById("realVoltageDiv");
    if(v) v.textContent = "12.05 V";
    var c = document.getElementById("realCurrentDiv");
    if(c) c.textContent = "1.23 A";
    var vIn = document.getElementById("LowDYSZ");
    if(vIn) vIn.value = "12.0";
    var cIn = document.getElementById("LowDLSZ");
    if(cIn) cIn.value = "2.0";
    var conn = document.getElementById("connStatus");
    if(conn) { conn.style.display="block"; conn.textContent="系统在线"; conn.className="system-status online"; }
    document.querySelectorAll(".hidden-tab").forEach(function(el) { el.classList.remove("hidden-tab"); });
}"""

def switch_tab(page, tab_id):
    page.evaluate("""(tabId) => {
        // deactivate all tabs and panes
        document.querySelectorAll(".tabs-ul li").forEach(li => li.classList.remove("active"));
        document.querySelectorAll(".tab-pane").forEach(pane => {
            pane.classList.remove("active", "in");
        });
        // activate target
        var link = document.querySelector("a[href='#" + tabId + "']");
        if(link) link.parentElement.classList.add("active");
        var pane = document.getElementById(tabId);
        if(pane) { pane.classList.add("active", "in"); }
    }""", tab_id)
    page.wait_for_timeout(300)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://localhost:9900/index.html", wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.evaluate(BASE_INJECT)
    page.wait_for_timeout(500)

    switch_tab(page, "home")
    page.screenshot(path=os.path.join(OUT_DIR, "tab1_power.png"))
    print("Saved tab1_power.png")

    switch_tab(page, "profile")
    page.screenshot(path=os.path.join(OUT_DIR, "tab2_env.png"))
    print("Saved tab2_env.png")

    switch_tab(page, "messages")
    page.screenshot(path=os.path.join(OUT_DIR, "tab3_interact.png"))
    print("Saved tab3_interact.png")

    switch_tab(page, "settings")
    page.screenshot(path=os.path.join(OUT_DIR, "tab4_settings.png"))
    print("Saved tab4_settings.png")

    browser.close()

print("Done")
