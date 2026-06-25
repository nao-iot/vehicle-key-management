from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
templates = Jinja2Templates(
    directory="templates"
)
import sqlite3
from datetime import datetime, timedelta
import io
import csv
import json

app = FastAPI()



# ==================================================
# SQLite 接続
# ==================================================
conn = sqlite3.connect("keybox.db", check_same_thread=False)
cursor = conn.cursor()

# ==================================================
# RFID状態（追加）
# ==================================================
#last_rfid_user = None
#last_rfid_time = None
# 自動判定候補
#pending_action = None


# ==================================================
# テーブル作成
# ==================================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_name TEXT,
    key_status TEXT,
    pouch_status TEXT,
    user_name TEXT,
    updated_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_name TEXT,
    user_name TEXT,
    action TEXT,
    item_type TEXT,
    action_time TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sensor_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_name TEXT,
    last_value TEXT,
    updated_at TEXT
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

conn.commit()

# ==================================================
# 初期データ
# ==================================================
cursor.execute("SELECT COUNT(*) FROM items")
count = cursor.fetchone()[0]

if count == 0:
    vehicles = ["車両A", "車両B", "車両C"]

    for vehicle in vehicles:
        cursor.execute("""
        INSERT INTO items (
            vehicle_name,
            key_status,
            pouch_status,
            user_name,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            vehicle,
            "available",
            "available",
            "",
            ""
        ))

    conn.commit()

# ==================================================
# 共通関数
# ==================================================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def update_sensor(sensor_name, value):

    cursor.execute("""
    SELECT COUNT(*)
    FROM sensor_status
    WHERE sensor_name=?
    """, (sensor_name,))

    count = cursor.fetchone()[0]

    if count == 0:
        cursor.execute("""
        INSERT INTO sensor_status (
            sensor_name,
            last_value,
            updated_at
        )
        VALUES (?, ?, ?)
        """, (sensor_name, value, now_str()))
    else:
        cursor.execute("""
        UPDATE sensor_status
        SET last_value=?,
            updated_at=?
        WHERE sensor_name=?
        """, (value, now_str(), sensor_name))

    conn.commit()


def is_rfid_valid():

    time_str = get_state(
        "last_rfid_time"
    )

    if time_str is None:
        return False

    last_time = datetime.fromisoformat(
        time_str
    )

    return (
        datetime.now() - last_time
    ).total_seconds() < 10


def borrow_key_logic(
    vehicle,
    user_name,
    status,
    action_name
):

    now = now_str()

    update_key_status(
        vehicle,
        status,
        user_name,
        now
    )

    insert_log(
        vehicle,
        user_name,
        action_name,
        "鍵"
    )

    
    if action_name == "貸出":
        auth_type = "MANUAL"

    elif action_name == "貸出(RFID)":
        auth_type = "RFID"

    elif action_name == "貸出(自動)":
        auth_type = "RFID"

    elif action_name == "貸出(未認証)":
        auth_type = "UNAUTH"

    else:
        auth_type = "UNKNOWN"

    create_vehicle_usage(
        vehicle,
        user_name,
        auth_type
    )


def return_key_logic(
    vehicle,
    action_name
):

    cursor.execute("""
    UPDATE items
    SET key_status='available',
        user_name='',
        updated_at=''
    WHERE vehicle_name=?
    """, (vehicle,))

    conn.commit()

    insert_log(
        vehicle,
        "",
        action_name,
        "鍵"
    )

    finish_vehicle_usage(
        vehicle
    )



def create_vehicle_usage(
    vehicle_name,
    user_name,
    auth_type
):

    cursor.execute("""
    INSERT INTO vehicle_usage (
        vehicle_name,
        user_name,
        borrow_time,
        auth_type
    )
    VALUES (?, ?, ?, ?)
    """, (
        vehicle_name,
        user_name,
        now_str(),
        auth_type
    ))

    conn.commit()



def finish_vehicle_usage(
    vehicle_name
):

    cursor.execute("""
    UPDATE vehicle_usage
    SET return_time=?
    WHERE id=(
        SELECT id
        FROM vehicle_usage
        WHERE vehicle_name=?
          AND return_time IS NULL
        ORDER BY id DESC
        LIMIT 1
    )
    """, (
        now_str(),
        vehicle_name
    ))

    conn.commit()


# ==================================================
# DB関数
# ==================================================

def get_all_items():

    cursor.execute("""
    SELECT *
    FROM items
    """)

    return cursor.fetchall()


def get_item_by_id(item_id):

    cursor.execute("""
    SELECT *
    FROM items
    WHERE id=?
    """, (item_id,))

    return cursor.fetchone()


def get_item_by_vehicle(vehicle):

    cursor.execute("""
    SELECT *
    FROM items
    WHERE vehicle_name=?
    """, (vehicle,))

    return cursor.fetchone()


def get_vehicle_by_hook(hook_id):

    cursor.execute("""
    SELECT vehicle_name
    FROM items
    WHERE hook_id=?
    """, (hook_id,))

    row = cursor.fetchone()

    if row:
        return row[0]

    return None


def update_key_status(
    vehicle,
    status,
    user_name,
    updated_at
):

    cursor.execute("""
    UPDATE items
    SET key_status=?,
        user_name=?,
        updated_at=?
    WHERE vehicle_name=?
    """, (
        status,
        user_name,
        updated_at,
        vehicle
    ))

    conn.commit()


def insert_log(
    vehicle,
    user_name,
    action,
    item_type
):

    cursor.execute("""
    INSERT INTO logs (
        vehicle_name,
        user_name,
        action,
        item_type,
        action_time
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        vehicle,
        user_name,
        action,
        item_type,
        now_str()
    ))

    conn.commit()




def set_state(key, value):

    cursor.execute("""
    INSERT OR REPLACE INTO system_state (
        key,
        value
    )
    VALUES (?, ?)
    """, (
        key,
        value
    ))

    conn.commit()



def get_state(key):

    cursor.execute("""
    SELECT value
    FROM system_state
    WHERE key=?
    """, (key,))

    row = cursor.fetchone()

    if row:
        return row[0]

    return None



def set_pending_action(data):

    set_state(
        "pending_action",
        json.dumps(data)
    )


def get_pending_action():

    value = get_state(
        "pending_action"
    )

    if value:
        return json.loads(value)

    return None


# ==================================================
# 状態取得API
# ==================================================
@app.get("/api/status")
def api_status():

    cursor.execute("""
    SELECT *
    FROM items
    """)
    rows = cursor.fetchall()
    
    return {
        "items": rows,
        "rfid_user":
            get_state("last_rfid_user")
            if is_rfid_valid()
            else None,
        "pending_action": 
            get_pending_action()
    }

# ==================================================
# メイン画面
# ==================================================
@app.get("/")
def dashboard(request: Request):

    rfid_user = get_state("last_rfid_user")

    if rfid_user and is_rfid_valid():
        auth_text = f"認証中：{rfid_user}"
    else:
        auth_text = "未認証"

    pending_action = get_pending_action()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": "鍵箱管理システム",
            "rows": get_all_items(),
            "auth_text": auth_text,
            "pending_action": pending_action
        }
    )


# ==================================================
# 手動操作
# ==================================================
@app.post("/borrow_key/{item_id}")
def borrow_key(item_id: int, user_name: str = Form(...)):

    row = get_item_by_id(item_id)
    
    vehicle = row[1]
    
    borrow_key_logic(
        vehicle,
        user_name,
        "using_authenticated",
        "貸出"
    )

    conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/return_key/{item_id}")
def return_key(item_id: int):

    cursor.execute("""
    SELECT vehicle_name, pouch_status
    FROM items
    WHERE id=?
    """, (item_id,))
    row = cursor.fetchone()

    vehicle = row[0]

    return_key_logic(
        vehicle,
        "返却"
    )

    conn.commit()

    return RedirectResponse("/", status_code=303)


# ==================================================
# センサーAPI
# ==================================================

# RFID読取 
@app.post("/sensor/rfid/{user_name}")
def sensor_rfid(user_name: str):

    set_state(
        "last_rfid_user",
        user_name
    )

    rfid_user = get_state(
        "last_rfid_user"
    )

    waiting_vehicle = get_state(
        "waiting_auth_vehicle"
    ) 

    # 認証待ち車両がある場合
    if waiting_vehicle:
    
        now = now_str()
    
        cursor.execute("""
        UPDATE items
        SET key_status='using_authenticated',
            user_name=?,
            updated_at=?
        WHERE vehicle_name=?
        """, (
            rfid_user,
            now,
            waiting_vehicle
        ))
    
        cursor.execute("""
        INSERT INTO logs (
            vehicle_name,
            user_name,
            action,
            item_type,
            action_time
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            waiting_vehicle,
            rfid_user,
            "後付け認証",
            "鍵",
            now
        ))


        cursor.execute("""
        UPDATE vehicle_usage
        SET user_name=?,
            auth_type='POST_AUTH'
        WHERE vehicle_name=?
          AND return_time IS NULL
        """, (
            rfid_user,
            waiting_vehicle
        ))

        conn.commit()
    
        set_state(
            "waiting_auth_vehicle",
            ""
        )

    set_state(
        "last_rfid_time",
        str(datetime.now())
    )    

    update_sensor("RFID", user_name)

    return {"result": "ok", "user": user_name}



@app.post("/rfid_borrow/{item_id}")
def rfid_borrow(item_id: int):

    if not is_rfid_valid():
        return dashboard("カードをかざしてください")

    row = get_item_by_id(item_id)

    vehicle = row[1]

    borrow_key_logic(
        vehicle,
        get_state("last_rfid_user"),
        "using_authenticated",
        "貸出(RFID)"
    )

    conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/rfid_return/{item_id}")
def rfid_return(item_id: int):

    row = get_item_by_id(item_id)
    
    vehicle = row[1]
   
    return_key_logic(
        vehicle,
        "返却(RFID)"
    )

    conn.commit()

    return RedirectResponse("/", status_code=303)



# 鍵返却
@app.post("/sensor/key_returned/{vehicle}")
def key_returned(vehicle: str):

    return_key_logic(
        vehicle,
        "返却(センサー)"
    )

    conn.commit()

    update_sensor("KEY_" + vehicle, "returned")

    return {"result": "ok"}


# リードスイッチ制御
@app.post("/sensor/keyhook/attached/{hook_id}")
def key_attached(hook_id: str):

    update_sensor(
        hook_id,
        "attached"
    )

    vehicle = get_vehicle_by_hook(hook_id)

    if vehicle is None:
        return {
            "error": f"unknown hook : {hook_id}"
        }


    # DB更新＆履歴
    return_key_logic(
        vehicle,
        "返却(自動)"
    )
    
    conn.commit()

    set_pending_action ({
        "vehicle": vehicle,
        "user": "",
        "action": "return"
    })

    return {"result": "ok"}

@app.post("/sensor/keyhook/removed/{hook_id}")
def keyhook_removed(hook_id: str):

    update_sensor(
        hook_id,
        "removed"
    )

    vehicle = get_vehicle_by_hook(hook_id)

    if vehicle is None:
        return {
            "error": f"unknown hook : {hook_id}"
        }

    now = now_str()

    # RFID認証あり
    if is_rfid_valid():

        status = "using_authenticated"
        user_name = get_state(
            "last_rfid_user"
        )       
        action_name = "貸出(自動)"

    # RFIDなし
    else:

        status = "using_unauthenticated"
        user_name = ""
        action_name = "貸出(未認証)"

    # DB更新＆履歴
    borrow_key_logic(
        vehicle,
        user_name,
        status,
        action_name
    )



    conn.commit()

    # 候補表示
    set_pending_action ({
        "vehicle": vehicle,
        "user": user_name if user_name else "未認証",
        "action": "borrow"
    })

    return {"result": "ok"}

# 未認証登録の再認証
@app.post("/start_auth/{vehicle}")
def start_auth(vehicle: str):
    set_state(
        "waiting_auth_vehicle",
        vehicle
    )
    return RedirectResponse("/", status_code=303)

# ==================================================
# 履歴画面
# ==================================================
@app.get("/history")
def history(
    request: Request,
    date: str = "",
    vehicle: str = "全体"
):

    if date == "":
        target_date = datetime.now().strftime("%Y-%m-%d")
    else:
        target_date = date

    dt = datetime.strptime(target_date, "%Y-%m-%d")

    prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

    if vehicle == "全体":
        cursor.execute("""
        SELECT *
        FROM logs
        WHERE action_time LIKE ?
        ORDER BY id DESC
        """, (target_date + "%",))
    else:
        cursor.execute("""
        SELECT *
        FROM logs
        WHERE action_time LIKE ?
          AND vehicle_name=?
        ORDER BY id DESC
        """, (target_date + "%", vehicle))

    rows = cursor.fetchall()

    cursor.execute("""
    SELECT vehicle_name
    FROM items
    ORDER BY id
    """)
    
    vehicles = cursor.fetchall()
       
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "target_date": target_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "vehicle": vehicle,
            "vehicles": vehicles,
            "rows": rows
        }
    )



@app.get(
    "/vehicle_history"
)

def vehicle_history(
    request: Request,
    date: str = "",
    vehicle: str = "全体"
):

    if date == "":
        target_date = datetime.now().strftime("%Y-%m-%d")
    else:
        target_date = date
    
    cursor.execute("""
    SELECT vehicle_name
    FROM items
    ORDER BY id
    """)

    vehicles = cursor.fetchall()

    query = """
    SELECT
        id,
        vehicle_name,
        user_name,
        borrow_time,
        return_time,
        meter_value,
        fuel_amount,
        purpose,
        auth_type
    FROM vehicle_usage
    WHERE 1=1
    """
    
    params = []

    query += """
    AND DATE(borrow_time) = ?
    """
    params.append(target_date)

    if vehicle != "全体":
    
        query += """
        AND vehicle_name = ?
        """
    
        params.append(vehicle)

    query += """
    ORDER BY id DESC
    """
    
    cursor.execute(
        query,
        params
    )
   
    rows = cursor.fetchall()

    current_date = datetime.strptime(
        target_date,
        "%Y-%m-%d"
    )
    
    prev_date = (
        current_date - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    
    next_date = (
        current_date + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    return templates.TemplateResponse(
        request=request,
        name="vehicle_history.html",
        context={
            "target_date": target_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "vehicle": vehicle,
            "vehicles": vehicles,
            "rows": rows
        }
    )




@app.get(
    "/edit_usage/{usage_id}"
)
def edit_usage(
    request: Request,
    usage_id: int
):

    cursor.execute("""
    SELECT *
    FROM vehicle_usage
    WHERE id=?
    """, (usage_id,))

    row = cursor.fetchone()

    cursor.execute("""
    SELECT vehicle_name
    FROM items
    ORDER BY id
    """)
    
    vehicles = cursor.fetchall()

    return templates.TemplateResponse(
        request=request,
        name="edit_usage.html",
        context={
            "usage_id": usage_id,
            "row": row,
            "vehicles": vehicles
        }
    )




@app.post("/update_usage/{usage_id}")
def update_usage(

    usage_id: int,

    meter_value: int = Form(None),

    fuel_amount: float = Form(None),

    vehicle_name: str = Form(""),
    
    user_name: str = Form(""),

    purpose: str = Form("")

):
    cursor.execute("""
    UPDATE vehicle_usage
    SET
        vehicle_name=?,
        meter_value=?,
        fuel_amount=?,
        user_name=?,
        purpose=?
    WHERE id=?
    """, (

        vehicle_name,

        meter_value,

        fuel_amount,

        user_name,

        purpose,

        usage_id

    ))

    conn.commit()

    return RedirectResponse(
        "/vehicle_history",
        status_code=303
    )


# ==================================================
# CSV出力
# ==================================================
@app.get("/download")
def download():

    cursor.execute("SELECT * FROM logs")
    rows = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "車両",
        "使用者",
        "操作",
        "種別",
        "時刻"
    ])

    writer.writerows(rows)

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=logs.csv"
        }
    )


