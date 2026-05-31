"""
使用 Microsoft Edge (headless) 将 manual.html 导出为 PDF
A4 尺寸，150 DPI 渲染质量
"""
import subprocess
import sys
import os
import time

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE  = os.path.join(SCRIPT_DIR, "manual.html")
PDF_FILE   = os.path.join(SCRIPT_DIR, "manual.pdf")

# file:/// URI (Windows 路径转换)
html_uri = "file:///" + HTML_FILE.replace("\\", "/")

# --force-device-scale-factor=1.5625 → 96 DPI × 1.5625 ≈ 150 DPI 渲染精度
cmd = [
    EDGE_PATH,
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--run-all-compositor-stages-before-draw",
    "--virtual-time-budget=5000",          # 等待页面渲染（ms）
    "--force-device-scale-factor=1.5625",  # 150 DPI
    f"--print-to-pdf={PDF_FILE}",
    "--print-to-pdf-no-header",
    html_uri,
]

print(f"[export_pdf] 输入: {HTML_FILE}")
print(f"[export_pdf] 输出: {PDF_FILE}")
print(f"[export_pdf] 启动 Edge headless ...")

try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0 and os.path.exists(PDF_FILE):
        size_kb = os.path.getsize(PDF_FILE) // 1024
        print(f"[export_pdf] ✅ PDF 生成成功！文件大小：{size_kb} KB")
        print(f"[export_pdf] 路径：{PDF_FILE}")
    else:
        print(f"[export_pdf] ❌ 生成失败，返回码: {result.returncode}")
        if result.stderr:
            print(f"[export_pdf] stderr: {result.stderr[:500]}")
        sys.exit(1)
except subprocess.TimeoutExpired:
    print("[export_pdf] ❌ 超时（60s），Edge 无响应")
    sys.exit(1)
except FileNotFoundError:
    print(f"[export_pdf] ❌ 找不到 Edge：{EDGE_PATH}")
    sys.exit(1)
