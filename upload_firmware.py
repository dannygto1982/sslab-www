"""上传固件到管理平台"""
import urllib.request
import urllib.error
import json
import os
import sys

ADMIN_SERVER = "http://49.234.204.200"
ADMIN_USER = "admin"
ADMIN_PASS = "Danny486020!!&&"

def upload_firmware(apk_path, version_code, version_name, changelog="", set_inactive=False, min_version_code=0):
    # 1. 登录获取 token
    login_data = json.dumps({"username": ADMIN_USER, "password": ADMIN_PASS}).encode()
    req = urllib.request.Request(
        ADMIN_SERVER + "/api/auth/login",
        data=login_data,
        headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req, timeout=10)
    token = json.loads(resp.read())["token"]
    print(f"Login OK, token: {token[:20]}...")

    # 2. 构建 multipart/form-data
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    body_parts = []

    def field(name, value):
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body_parts.append(field("version_code", str(version_code)))
    body_parts.append(field("version_name", version_name))
    body_parts.append(field("changelog", changelog))
    body_parts.append(field("min_version_code", str(min_version_code)))

    # File part
    filename = os.path.basename(apk_path)
    with open(apk_path, "rb") as f:
        file_data = f.read()

    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/vnd.android.package-archive\r\n\r\n"
    ).encode("utf-8")
    body_parts.append(file_header + file_data + b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(body_parts)
    print(f"Uploading {filename} ({len(file_data)//1024}KB)...")

    req2 = urllib.request.Request(
        ADMIN_SERVER + "/api/firmware/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
    )
    resp2 = urllib.request.urlopen(req2, timeout=120)
    result = json.loads(resp2.read())
    print(f"Upload OK: {result}")

    # 3. 如果需要，上传后立即设为不激活（防止旧设备自动更新）
    if set_inactive:
        fw_id = result["id"]
        toggle_data = json.dumps({"active": False}).encode()
        req3 = urllib.request.Request(
            ADMIN_SERVER + f"/api/firmware/{fw_id}/toggle",
            data=toggle_data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )
        resp3 = urllib.request.urlopen(req3, timeout=10)
        print(f"Set inactive OK (id={fw_id}): {json.loads(resp3.read())}")

    return result

if __name__ == "__main__":
    apk = r"d:\CODE\SSLAB-WWW\android\platforms\android\app\build\outputs\apk\debug\app-debug.apk"
    result = upload_firmware(
        apk, 20002, "2.0.1",
        changelog="V2.0.1: 加入远程self_uninstall命令，修夎各细节",
        set_inactive=False,
        min_version_code=20000  # 仅 v2.x 以上设备才收到此更新，v1.x 设备不受影响
    )
    print("Done:", result)
