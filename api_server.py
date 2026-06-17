from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
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
last_rfid_user = None
last_rfid_time = None
# 自動判定候補（2026/05/10追加）
pending_action = None


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

# 2026/05/28追加
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


def status_text(status, user_name):

    if status == "available":
        return "使用可能"

    elif status == "using_authenticated":
        return f"({user_name}) 使用中"

    elif status == "using_unauthenticated":
        return "未認証貸出"

    else:
        return status


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


# 2026/06/07編集
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

    # vehicle_usage作成
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


# 2026/06/07編集
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


# 2026/06/07追加
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


# 2026/06/07追加
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
# DB関数(2026/05/26追加)
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

# 2026/05/30追加
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


def update_pouch_status(
    vehicle,
    status
):

    cursor.execute("""
    UPDATE items
    SET pouch_status=?
    WHERE vehicle_name=?
    """, (
        status,
        vehicle
    ))

    conn.commit()


def clear_user_if_returned(vehicle):

    cursor.execute("""
    SELECT key_status,
           pouch_status
    FROM items
    WHERE vehicle_name=?
    """, (vehicle,))

    row = cursor.fetchone()

    if (
        row[0] == "available"
        and
        row[1] == "available"
    ):

        cursor.execute("""
        UPDATE items
        SET user_name='',
            updated_at=''
        WHERE vehicle_name=?
        """, (vehicle,))

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


def get_all_sensors():

    cursor.execute("""
    SELECT sensor_name,
           last_value,
           updated_at
    FROM sensor_status
    ORDER BY sensor_name
    """)

    return cursor.fetchall()


# 2026/05/28追加
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


# 2026/05/28追加
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


# 2026/05/28追加
def set_pending_action(data):

    set_state(
        "pending_action",
        json.dumps(data)
    )

# 2026/05/28追加
def get_pending_action():

    value = get_state(
        "pending_action"
    )

    if value:
        return json.loads(value)

    return None


# ==================================================
# 状態取得API（2026/05/24追加）
# ==================================================
@app.get("/api/status")
def api_status():

    cursor.execute("""
    SELECT *
    FROM items
    """)
    rows = cursor.fetchall()

    cursor.execute("""
    SELECT sensor_name, last_value, updated_at
    FROM sensor_status
    ORDER BY sensor_name
    """)
    sensors = cursor.fetchall()

    return {
        "items": rows,
        "sensors": sensors,
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
@app.get("/", response_class=HTMLResponse)
def dashboard(message: str = ""):
    rows = get_all_items()

    sensors = get_all_sensors()    
    
    # ===== RFID表示（追加分(2026/05/03)）=====
    # ===== RFID表示 =====
    
    rfid_user = get_state(
        "last_rfid_user"
    )   

    if rfid_user and is_rfid_valid():
        auth_text = f"認証中：{rfid_user}"
    else:
        auth_text = "未認証"


    # ===== 自動判定候補表示 =====
    pending_html = ""

    pending_action = get_pending_action()

    if pending_action:
    
        pending_html = f"""
        <div class="box">
            <h3>自動判定候補</h3>
    
            <b>
            {pending_action["user"]}
            →
            {pending_action["vehicle"]}
            ({pending_action["action"]})
            </b>

        </div>
        """
    html = f"""
    <html lang="ja">    
    <head>

        <meta charset="UTF-8">

        <meta name="google"
              content="notranslate">

        <title>鍵箱管理システム</title>

        <style>
            body {{
                font-family: Arial;
                text-align: center;
                background: #f5f5f5;
            }}

            table {{
                margin: auto;
                border-collapse: collapse;
                width: 95%;
                background: white;
            }}

            th, td {{
                border: 1px solid #ccc;
                padding: 8px;
            }}

            .available {{
                background: #ccffcc;
            }}

            .using_authenticated {{
                background: #ffcccc;
            }}

            .using_unauthenticated {{
                background: #fff0a0;
            }}

            .message {{
                color: red;
                font-weight: bold;
                margin: 10px;
            }}

            button {{
                padding: 6px 12px;
                margin: 2px;
                cursor: pointer;
            }}

            input {{
                padding: 5px;
                width: 110px;
            }}

            .box {{
                width: 95%;
                margin: auto;
                background: white;
                padding: 10px;
                margin-bottom: 20px;
                border: 1px solid #ccc;
            }}
        </style>
    </head>

    <body>

    <h1>鍵箱管理システム</h1>

    <div class="box">
        <b id="rfid-status">{auth_text}</b>
    </div>  

    <div id="pending-area">
        {pending_html}
    </div>

    <a href="/history"><button>履歴</button></a>
    <a href="/vehicle_history">
        <button>車両利用履歴</button>
    </a>
    <a href="/download"><button>CSV</button></a>
    <div class="message">{message}</div>

    <div class="box">
        <h3>センサー状態</h3>
        <table>
            <tr>
                <th>センサー</th>
                <th>値</th>
                <th>更新時刻</th>
            </tr>
    """

    for s in sensors:
        html += f"""
        <tr>
            <td>{s[0]}</td>
            <td>{s[1]}</td>
            <td>{s[2]}</td>
        </tr>
        """

    html += """
        </table>
    </div>

    <table>
        <tr>
            <th>車両</th>
            <th>鍵</th>
            <th>カード袋</th>
            <th>更新時刻</th>
            <th>操作</th>
        </tr>
    """

    for row in rows:

        row_id = row[0]
        vehicle = row[1]
        key_status = row[2]
        pouch_status = row[3]
        user_name = row[4]
        updated_at = row[5]

        html += f"""
        <tr>
            <td>{vehicle}</td>

            <td id="key-{vehicle}" class="{key_status}">
                {status_text(key_status, user_name)}
            </td>

            <td id="pouch-{vehicle}" class="{pouch_status}">
                {status_text(pouch_status, user_name)}
            </td>

            <td id="time-{vehicle}">{updated_at}</td>
            
            <td>

            <div id="key-action-{vehicle}">
        """

        # 鍵(2026/05/03変更)
        if key_status == "available":
            html += f"""
            <form action="/borrow_key/{row_id}" method="post">
                <input type="text" name="user_name" placeholder="名前" required>
                <button type="submit">鍵貸出</button>
            </form>

            """
        elif key_status == "using_unauthenticated":
            html += f"""
            <form action="/start_auth/{vehicle}" method="post">
                <button type="submit">
                    認証する
                </button>
            </form>
            """
        else:
            html += f"""
            <form action="/return_key/{row_id}" method="post">
                <button type="submit">鍵返却</button>
            </form>

            """
 
        html += f"""
        </div>

        <hr>

        <div id="pouch-action-{vehicle}">
        """

        # 袋
        if pouch_status == "available":
            html += f"""
            <form action="/borrow_pouch/{row_id}" method="post">
                <button type="submit">袋貸出</button>
            </form>
            """
        else:
            html += f"""
            <form action="/return_pouch/{row_id}" method="post">
                <button type="submit">袋返却</button>
            </form>
            """

        html += """
        </div>
        """
                
        html += """
            </td>
        </tr>
        """
     
    html += """

    <script>
    
    async function updateStatus() {
    
        const response = await fetch("/api/status");
        const data = await response.json();
    
        // RFID状態
        const rfid = document.getElementById("rfid-status");
    
        if (data.rfid_user) {
            rfid.innerText = "認証中：" + data.rfid_user;
        } else {
            rfid.innerText = "未認証";
        }
    
        // pending_action
        const pendingArea =
            document.getElementById("pending-area");
    
        if (data.pending_action) {
    
            pendingArea.innerHTML = `
            <div class="box">
                <h3>自動判定候補</h3>
    
                <b>
                ${data.pending_action.user}
                →
                ${data.pending_action.vehicle}
                (${data.pending_action.action})
                </b>
            </div>
            `;
    
        } else {
    
            pendingArea.innerHTML = "";
        }
    
        window.lastKeyStatus =
            window.lastKeyStatus || {};
        window.lastState =
            window.lastState || {};
        // items更新
        data.items.forEach(item => {
    
            const vehicle = item[1];
    
            const keyStatus = item[2];
            const pouchStatus = item[3];
            const userName = item[4];
            const updatedAt = item[5];
    
            // 鍵
            const keyCell =
                document.getElementById("key-" + vehicle);

            // 操作欄
            const keyAction =
                document.getElementById(
                    "key-action-" + vehicle
                );   

            if (keyStatus == "available") {
    
                keyCell.className = "available";
                keyCell.innerText = "使用可能";

                keyAction.innerHTML = `
                    <form action="/borrow_key/${item[0]}"
                          method="post">
                
                        <input type="text"
                               name="user_name"
                               placeholder="名前"
                               required>
                
                        <button type="submit">
                            鍵貸出
                        </button>
                
                    </form>
                    `;
    
            } else if (
                keyStatus == "using_authenticated"
            ) {
    
                keyCell.className =
                    "using_authenticated";
    
                keyCell.innerText =
                    "(" + userName + ") 使用中";

                keyAction.innerHTML = `
                <form action="/return_key/${item[0]}"
                      method="post">
            
                    <button type="submit">
                        鍵返却
                    </button>
            
                </form>
                `;
    
            } else {
    
                keyCell.className =
                    "using_unauthenticated";
    
                keyCell.innerText = "未認証貸出";

                keyAction.innerHTML = `
                <form action="/start_auth/${vehicle}"
                      method="post">
            
                    <button type="submit">
                        認証する
                    </button>
            
                </form>
                `;

            }
    
            // 袋
            const pouchCell =
                document.getElementById(
                    "pouch-" + vehicle
                );
    
            pouchCell.className = pouchStatus;
    
            if (pouchStatus == "available") {
    
                pouchCell.innerText = "使用可能";
    
            } else {
    
                pouchCell.innerText =
                    "(" + userName + ") 使用中";
            }
    
            // 時刻
            document.getElementById(
                "time-" + vehicle
            ).innerText = updatedAt;

                           
        });

    }
    
    // 1秒ごと更新
    setInterval(updateStatus, 1000);
    
    </script>    
    </body>
    </html>
    """

    return HTMLResponse(content=html)

# ==================================================
# 手動操作
# ==================================================
@app.post("/borrow_key/{item_id}")
def borrow_key(item_id: int, user_name: str = Form(...)):

    row = get_item_by_id(item_id)
    
    vehicle = row[1]
    now = now_str()

    
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
    pouch_status = row[1]

    return_key_logic(
        vehicle,
        "返却"
    )

    conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/borrow_pouch/{item_id}")
def borrow_pouch(item_id: int):

    cursor.execute("""
    SELECT vehicle_name, user_name
    FROM items
    WHERE id=?
    """, (item_id,))
    row = cursor.fetchone()

    vehicle = row[0]
    user_name = row[1]

    if user_name == "":
        return dashboard("先に鍵を貸出してください")

    cursor.execute("""
    UPDATE items
    SET pouch_status='using'
    WHERE id=?
    """, (item_id,))

    cursor.execute("""
    INSERT INTO logs (
        vehicle_name,user_name,action,item_type,action_time
    )
    VALUES (?, ?, ?, ?, ?)
    """, (vehicle, user_name, "貸出", "カード袋", now_str()))

    conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/return_pouch/{item_id}")
def return_pouch(item_id: int):

    cursor.execute("""
    SELECT vehicle_name, key_status
    FROM items
    WHERE id=?
    """, (item_id,))
    row = cursor.fetchone()

    vehicle = row[0]
    key_status = row[1]

    if key_status == "available":
        cursor.execute("""
        UPDATE items
        SET pouch_status='available',
            user_name='',
            updated_at=''
        WHERE id=?
        """, (item_id,))
    else:
        cursor.execute("""
        UPDATE items
        SET pouch_status='available'
        WHERE id=?
        """, (item_id,))

    cursor.execute("""
    INSERT INTO logs (
        vehicle_name,user_name,action,item_type,action_time
    )
    VALUES (?, ?, ?, ?, ?)
    """, (vehicle, "", "返却", "カード袋", now_str()))

    conn.commit()

    return RedirectResponse("/", status_code=303)

# ==================================================
# センサーAPI
# ==================================================

# RFID読取 変更(2026/05/03)
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

        # 2026/06/07追加
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


# 追加分(2026/05/03)
@app.post("/rfid_borrow/{item_id}")
def rfid_borrow(item_id: int):

    if not is_rfid_valid():
        return dashboard("カードをかざしてください")

    row = get_item_by_id(item_id)

    vehicle = row[1]
    
    now = now_str()

    borrow_key_logic(
        vehicle,
        get_state("last_rfid_user"),
        "using_authenticated",
        "貸出(RFID)"
    )

    conn.commit()

    return RedirectResponse("/", status_code=303)

# 追加分(2026/05/03)
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


# リードスイッチ制御(2026/05/14追加)
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

    now = now_str()

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

    get_state("last_rfid_user")

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

# 未認証登録の再認証（2026/05/24追加）
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
@app.get("/history", response_class=HTMLResponse)
def history(date: str = "", vehicle: str = "全体"):

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
    
    vehicle_options = """
    <option value="全体">
    全体
    </option>
    """
    for v in vehicles:
    
        name = v[0]
    
        selected = ""
    
        if vehicle == name:
            selected = "selected"
    
        vehicle_options += f"""
        <option value="{name}" {selected}>
            {name}
        </option>
        """

    html = f"""
    <html>
    <head>
        <title>履歴</title>
        <style>
            body {{
                font-family: Arial;
                text-align: center;
                background: #f5f5f5;
            }}

            table {{
                margin: auto;
                border-collapse: collapse;
                width: 95%;
                background: white;
            }}

            th, td {{
                border: 1px solid #ccc;
                padding: 8px;
            }}
        </style>
    </head>

    <body>

    <h1>貸出履歴</h1>

    <div>

        <a href="/history?date={prev_date}&vehicle={vehicle}">&lt;</a>

        <form action="/history" method="get" style="display:inline;">

            <input type="date"
                   name="date"
                   value="{target_date}"
                   onchange="this.form.submit()">

            <select name="vehicle"
                    onchange="this.form.submit()">

            {vehicle_options}

            </select>
        </form>

        <a href="/history?date={next_date}&vehicle={vehicle}">&gt;</a>

    </div>

    <br>

    <a href="/"><button>戻る</button></a>

    <table>
        <tr>
            <th>ID</th>
            <th>車両</th>
            <th>使用者</th>
            <th>操作</th>
            <th>種別</th>
            <th>時刻</th>
            <th>編集</th>
        </tr>
    """

    for row in rows:
        
        action_time = ""
        
        if row[5]:
            action_time = row[5][:16]

        html += f"""
        <tr>
            <td>{row[0]}</td>
            <td>{row[1]}</td>
            <td>{row[2]}</td>
            <td>{row[3]}</td>
            <td>{row[4]}</td>
            <td>{action_time}</td>
            <td>
                <a href="/edit_log/{row[0]}">
                    <button>編集</button>
                </a>
            </td>
        </tr>
        """

    html += """
    </table>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


# 2026/06/08追加
@app.get(
    "/vehicle_history",
    response_class=HTMLResponse
)

def vehicle_history(
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

    html = """
    <html lang="ja">
    <head>
    
    <meta charset="UTF-8">
    
    <meta name="google"
          content="notranslate">

        <title>車両利用履歴</title>

        <style>

        body {
            font-family: Arial;
            text-align: center;
            background: #f5f5f5;
        }

        table {
            margin: auto;
            border-collapse: collapse;
            width: 95%;
            background: white;
        }

        th, td {
            border: 1px solid #ccc;
            padding: 8px;
        }

        </style>
    </head>

    <body>

    <h1>車両利用履歴</h1>

    <a href="/">
        <button>戻る</button>
    </a>

    <br><br>
    """

    html += f"""
    <div>
    
        <a href="/vehicle_history?date={prev_date}&vehicle={vehicle}">
            &lt;
        </a>
    
        <form
            action="/vehicle_history"
            method="get"
            style="display:inline;"
        >
    
            <input
                type="date"
                name="date"
                value="{target_date}"
                onchange="this.form.submit()"
            >
    
            <select
                name="vehicle"
                onchange="this.form.submit()"
            >
    
                <option
                    {"selected" if vehicle=="全体" else ""}
                >
                    全体
                </option>
    """

    for v in vehicles:
    
        name = v[0]
    
        html += f"""
            <option
                {"selected" if vehicle==name else ""}
            >
                {name}
            </option>
        """
    
    html += f"""
            </select>
    
        </form>
    
        <a href="/vehicle_history?date={next_date}&vehicle={vehicle}">
            &gt;
        </a>
    
    </div>
    
    <br>
    """

    html += """
    <table>

        <tr>
            <th>車両</th>
            <th>使用者</th>
            <th>貸出時刻</th>
            <th>返却時刻</th>
            <th>指示数</th>
            <th>給油量</th>
            <th>使用目的</th>
            <th>編集</th>
        </tr>
    """

    for row in rows:

        usage_id = row[0]

        borrow_time = ""
        
        if row[3]:
            borrow_time = row[3][:16]
        
        return_time = ""
        
        if row[4]:
            return_time = row[4][:16]

        html += f"""
        <tr>
            <td>{row[1]}</td>
            <td>{row[2]}</td>
            <td>{borrow_time}</td>
            <td>{return_time}</td>            
            <td>{row[5] if row[5] is not None else ""}</td>
            <td>{row[6] if row[6] is not None else ""}</td>
            <td>{row[7] if row[7] is not None else ""}</td>
            <td>
                <a href="/edit_usage/{usage_id}">
                    <button>編集</button>
                </a>
            </td>
        </tr>
        """

    html += """
    </table>

    </body>
    </html>
    """

    return HTMLResponse(html)


# 2026/06/08追加
@app.get(
    "/edit_usage/{usage_id}",
    response_class=HTMLResponse
)
def edit_usage(usage_id: int):

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


    vehicle_options = ""
    
    for v in vehicles:
    
        name = v[0]
    
        selected = ""
    
        if name == row[1]:
    
            selected = "selected"
    
        vehicle_options += f"""
        <option value="{name}" {selected}>
            {name}
        </option>
        """

    html = f"""
    <html lang="ja">
    
    <head>
    <meta charset="UTF-8">
    <meta name="google"
          content="notranslate">
    </head>
    
    <body>

    <h2>車両利用履歴編集</h2>

    <form
        action="/update_usage/{usage_id}"
        method="post"
    >

        指示数<br>

        <input
            type="number"
            name="meter_value"
            value="{row[5] if row[5] else ''}"
        >

        <br><br>

        給油量(L)<br>

        <input
            type="number"
            step="0.1"
            name="fuel_amount"
            value="{row[6] if row[6] else ''}"
        >

        <br><br>
        
        車両<br>
        
        <select name="vehicle_name">
        
        {vehicle_options}
        
        </select>
        
        <br><br>

        使用者<br>
        
        <input
            type="text"
            name="user_name"
            value="{row[2] if row[2] else ''}"
        >
        
        <br><br>

        使用目的<br>

        <input
            type="text"
            name="purpose"
            value="{row[7] if row[7] else ''}"
        >

        <br><br>

        <button type="submit">
            保存
        </button>

    </form>

    <br>

    <a href="/vehicle_history">
        戻る
    </a>

    </body>
    </html>
    """

    return HTMLResponse(html)


# 2026/06/08追加
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


# 2026/05/31追加　貸出者編集
@app.get("/edit_log/{log_id}",
         response_class=HTMLResponse)
def edit_log(log_id: int):

    cursor.execute("""
    SELECT *
    FROM logs
    WHERE id=?
    """, (log_id,))

    row = cursor.fetchone()

    html = f"""
    <html>
    <body>

    <h2>履歴修正</h2>

    <form action="/update_log/{log_id}"
          method="post">

        使用者：

        <input
            type="text"
            name="user_name"
            value="{row[2]}"
        >

        <br><br>

        <button type="submit">
            保存
        </button>

    </form>

    <br>

    <a href="/history">
        戻る
    </a>

    </body>
    </html>
    """

    return HTMLResponse(html)


# 2026/05/31　追加
@app.post("/update_log/{log_id}")
def update_log(
    log_id: int,
    user_name: str = Form(...)
):

    cursor.execute("""
    UPDATE logs
    SET user_name=?
    WHERE id=?
    """, (
        user_name,
        log_id
    ))

    conn.commit()

    return RedirectResponse(
        "/history",
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



