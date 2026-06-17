import RPi.GPIO as GPIO
import requests
import time

HOOKS = {
    "hook_1": 17
}

SERVER = "https://web.naoki-iot.xyz"

GPIO.setmode(GPIO.BCM)

for pin in HOOKS.values():

    GPIO.setup(
        pin,
        GPIO.IN,
        pull_up_down=GPIO.PUD_UP
    )

print("リードスイッチ監視開始")

stable_states = {}

for hook_id, pin in HOOKS.items():

    stable_states[hook_id] = GPIO.input(pin)

try:
    while True:

        for hook_id, pin in HOOKS.items():
        
            current = GPIO.input(pin)

            if current != stable_states[hook_id]:
            
                time.sleep(2)
            
                confirm = GPIO.input(pin)
            
                if confirm == current:
            
                    stable_states[hook_id] = current
            
                    # 鍵あり
                    if current == 0:
            
                        print(f"{hook_id} 鍵あり")
            
                        try:
            
                            response = requests.post(
                                f"{SERVER}/sensor/keyhook/attached/{hook_id}"
                            )
            
                            print(response.status_code)
                            print(response.text)
            
                        except Exception as e:
                            print(e)
            
                    # 鍵なし
                    else:
            
                        print(f"{hook_id} 鍵なし")
            
                        try:
            
                            response = requests.post(
                                f"{SERVER}/sensor/keyhook/removed/{hook_id}"
                            )
            
                            print(response.status_code)
                            print(response.text)
            
                        except Exception as e:
                            print(e)         

        time.sleep(0.1)

except KeyboardInterrupt:
    GPIO.cleanup()
