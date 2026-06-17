from mfrc522 import SimpleMFRC522
import requests
import RPi.GPIO as GPIO
import time
import json

reader = SimpleMFRC522()

# ★ここを変更（あなたの環境）
SERVER = "https://web.naoki-iot.xyz"

# ★ユーザマッピング（おすすめ）
with open("users.json", "r", encoding="utf-8") as f:
    USER_MAP = json.load(f)

try:
    while True:
        print("カードをかざしてください")

        id, text = reader.read()

        # 名前変換（なければID）
        user_name = USER_MAP.get(str(id), str(id))

        print("認識:", user_name)

        url = f"{SERVER}/sensor/rfid/{user_name}"

        try:
            res = requests.post(url)
            print("送信成功:", res.status_code)
        except Exception as e:
            print("送信失敗:", e)

        # 連続読み取り防止
        time.sleep(3)

except KeyboardInterrupt:
    GPIO.cleanup()
