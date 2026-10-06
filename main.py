# ============================================================
#   MZ HOSTING SARVER
#   Created by MZ MINHAZ
#   Master Node — Multi-User · Admin Tier · Auto-Fix Engine
# ============================================================

import os, sys, re, ast, json, time, shutil, zipfile, subprocess, threading
import io, traceback, platform, importlib.util, contextlib

# --- AUTO-INSTALLER FOR MASTER NODE ---
REQUIRED_PACKAGES = ["pyTelegramBotAPI", "requests", "psutil"]
for pkg in REQUIRED_PACKAGES:
    try:
        __import__("telebot" if pkg == "pyTelegramBotAPI" else pkg)
    except ImportError:
        print("Installing master dep: " + pkg)
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

import telebot
from telebot import types
import requests  # noqa
import psutil

# ============================================================
#                    MASTER CONFIG
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8762473527:AAHpo1XHQO4rCAkrtqZbqfMRHQYRPeOLqfA")
OWNER_ID  = int(os.environ.get("OWNER_ID", "8255204869"))

SERVER_NAME = "MZ HOSTING SARVER"
CREATED_BY  = "MZ MINHAZ"

MAX_AUTOFIX_RETRIES = 3   # per instance per crash cycle

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BOTS_DIR  = os.path.join(BASE_DIR, "bots")
LOGS_DIR  = os.path.join(BASE_DIR, "logs")
DATA_DIR  = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "users.json")
START_TIME = time.time()

for d in (BOTS_DIR, LOGS_DIR, DATA_DIR):
    os.makedirs(d, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
RUNNING_BOTS = {}   # key: "{uid}:{filename}"

# ============================================================
#                PERSISTENT USER DATABASE
# ============================================================
DATA_LOCK = threading.Lock()

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                d = json.load(f)
            d.setdefault("approved", [])
            d.setdefault("admins", [])
            d.setdefault("pending", {})
            return d
        except Exception:
            pass
    return {"approved": [], "admins": [], "pending": {}}

def save_data(d):
    with DATA_LOCK:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, DATA_FILE)

DATA = load_data()

# ============================================================
#                    ROLE CHECKS
# ============================================================
def is_owner(uid):    return uid == OWNER_ID
def is_admin(uid):    return is_owner(uid) or uid in DATA.get("admins", [])
def is_approved(uid): return is_owner(uid) or is_admin(uid) or uid in DATA.get("approved", [])
def is_authorized(uid): return is_approved(uid)

# ============================================================
#                       HELPERS
# ============================================================
MD_SPECIALS = "_*`[]()~>#+-=|{}.!"

def md_escape(s):
    return "".join("\\" + c if c in MD_SPECIALS else c for c in str(s))

def user_bots_dir(uid):
    p = os.path.join(BOTS_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p

def user_logs_dir(uid):
    p = os.path.join(LOGS_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p

def safe_filename(name):
    return os.path.basename(name or "")

def safe_extract(zf, dest):
    dest_abs = os.path.abspath(dest)
    for member in zf.namelist():
        target = os.path.abspath(os.path.join(dest_abs, member))
        if not target.startswith(dest_abs + os.sep) and target != dest_abs:
            raise ValueError("Zip slip blocked: " + member)
    zf.extractall(dest_abs)

# ============================================================
#          AUTO-DEPENDENCY SCANNER FOR UPLOADED BOTS
# ============================================================
PIP_ALIASES = {
    "telebot":      "pyTelegramBotAPI",
    "telegram":     "python-telegram-bot",
    "PIL":          "Pillow",
    "cv2":          "opencv-python",
    "dotenv":       "python-dotenv",
    "bs4":          "beautifulsoup4",
    "yaml":         "PyYAML",
    "sklearn":      "scikit-learn",
    "telethon":     "telethon",
    "pyaes":        "pyaes",
    "rsa":          "rsa",
    "Crypto":       "pycryptodome",
    "Cryptodome":   "pycryptodomex",
    "OpenSSL":      "pyOpenSSL",
    "serial":       "pyserial",
    "usb":          "pyusb",
    "pkg_resources": None,
    "google":       "google-api-python-client",
    "mysql":        "mysql-connector-python",
    "MySQLdb":      "mysqlclient",
    "psycopg2":     "psycopg2-binary",
    "win32com":     None,   # windows only, skip on linux
    "fcntl":        None,   # stdlib posix
    "termios":      None,
}

SKIP_MODULES = {
    "os", "sys", "time", "json", "math", "random", "re", "io", "ast",
    "logging", "asyncio", "threading", "subprocess", "shutil", "zipfile",
    "pathlib", "datetime", "collections", "itertools", "functools",
    "typing", "abc", "base64", "hashlib", "hmac", "secrets", "uuid",
    "urllib", "http", "socket", "ssl", "email", "smtplib", "sqlite3",
    "csv", "xml", "html", "struct", "pickle", "copy", "glob", "tempfile",
    "traceback", "platform", "importlib", "contextlib", "warnings",
    "argparse", "configparser", "string", "textwrap", "unicodedata",
    "concurrent", "multiprocessing", "queue", "signal", "errno",
    "inspect", "types", "weakref", "dataclasses",
    "enum", "statistics", "decimal", "fractions", "numbers", "array",
    "bisect", "heapq", "operator", "pprint", "reprlib", "gc", "atexit",
    "builtins", "__future__", "site", "sysconfig", "typing_extensions",
    "fcntl", "termios", "pwd", "grp", "resource", "select", "mmap",
}

def scan_imports(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src)
    except Exception:
        return set()
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
    return mods

def pip_install(pkg, extra=None):
    """Install a package. Retries with --break-system-packages on managed-env refusal."""
    cmd = [sys.executable, "-m", "pip", "install", pkg]
    if extra:
        cmd += extra
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if p.returncode == 0:
            return True, ""
        err = (p.stderr or "") + (p.stdout or "")
        if "externally-managed-environment" in err or "PEP 668" in err:
            cmd2 = cmd + ["--break-system-packages"]
            p2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=240)
            if p2.returncode == 0:
                return True, ""
            return False, (p2.stderr or "")[-400:]
        return False, err[-400:]
    except subprocess.TimeoutExpired:
        return False, "pip timed out"
    except Exception as e:
        return False, str(e)

def ensure_deps_for_file(py_path, progress=None):
    mods = scan_imports(py_path)
    if not mods:
        return [], []
    try:
        stdlib = set(sys.stdlib_module_names)
    except AttributeError:
        stdlib = SKIP_MODULES
    stdlib = stdlib | SKIP_MODULES

    installed, failed = [], []
    for m in sorted(mods):
        if m in stdlib or m.startswith("_"):
            continue
        if importlib.util.find_spec(m) is not None:
            continue
        pip_name = PIP_ALIASES.get(m, m)
        if pip_name is None:
            continue
        if progress:
            try: progress("Installing `{}`...".format(md_escape(pip_name)))
            except Exception: pass
        ok, err = pip_install(pip_name)
        if ok:
            installed.append(pip_name)
        else:
            failed.append((pip_name, err))
    return installed, failed

# ============================================================
#              AUTO-FIX ENGINE (error parser + fixer)
# ============================================================
def parse_error(text):
    """
    Match the last traceback against known fixable signatures.
    Returns dict or None.
    """
    if not text:
        return None
    tail = text[-8000:]

    # 1) ModuleNotFoundError / ImportError: No module named 'X'
    m = re.search(r"No module named ['\"]?([\w\.]+)['\"]?", tail)
    if m:
        return {"type": "missing_module", "module": m.group(1).split(".")[0]}

    # 2) ImportError: cannot import name 'Y' from 'X'
    m = re.search(r"cannot import name ['\"]?(\w+)['\"]? from ['\"]?([\w\.]+)['\"]?", tail)
    if m:
        return {"type": "missing_attr", "name": m.group(1),
                "module": m.group(2).split(".")[0]}

    # 3) AttributeError: module 'X' has no attribute 'Y'
    m = re.search(r"module ['\"]?([\w\.]+)['\"]? has no attribute ['\"]?(\w+)['\"]?", tail)
    if m:
        return {"type": "missing_attr", "module": m.group(1).split(".")[0],
                "name": m.group(2)}

    # 4) setuptools / distutils / pkg_resources
    if re.search(r"No module named ['\"]?(distutils|pkg_resources|setuptools)['\"]?", tail):
        return {"type": "setuptools_missing"}

    # 5) aiohttp / telebot compat
    if "aiohttp" in tail and ("AttributeError" in tail or "TypeError" in tail):
        return {"type": "aiohttp_compat"}

    # 6) telebot version mismatch
    if "telebot" in tail and ("has no attribute" in tail or "cannot import" in tail):
        return {"type": "telebot_compat"}

    return None

def apply_fix(err):
    """Return (fixed: bool, action_text: str)."""
    if not err:
        return False, ""

    t = err.get("type")

    if t == "missing_module":
        mod = err["module"]
        pkg = PIP_ALIASES.get(mod, mod)
        if pkg is None:
            return False, ""
        ok, e = pip_install(pkg)
        return (True, "Installed `{}`".format(pkg)) if ok else (False, "pip failed: " + e)

    if t == "missing_attr":
        mod = err["module"]
        pkg = PIP_ALIASES.get(mod, mod)
        if pkg is None:
            return False, ""
        ok, e = pip_install(pkg, ["--upgrade"])
        if ok:
            return True, "Upgraded `{}`".format(pkg)
        ok, e = pip_install(pkg, ["--force-reinstall"])
        if ok:
            return True, "Reinstalled `{}`".format(pkg)
        return False, "pip failed: " + e

    if t == "setuptools_missing":
        ok, e = pip_install("setuptools")
        if ok:
            ok2, _ = pip_install("wheel")
            return True, "Installed setuptools+wheel"
        return False, "pip failed: " + e

    if t == "aiohttp_compat":
        ok, e = pip_install("aiohttp", ["--upgrade"])
        return (True, "Upgraded aiohttp") if ok else (False, e)

    if t == "telebot_compat":
        ok, e = pip_install("pyTelegramBotAPI", ["--upgrade"])
        return (True, "Upgraded pyTelegramBotAPI") if ok else (False, e)

    return False, ""

# ============================================================
#              SUPERVISOR (per-instance, handles crashes)
# ============================================================
def _launch_process(uid, fname, log_path, tag="boot"):
    d = user_bots_dir(uid)
    script_path = os.path.join(d, fname)
    log_file = open(log_path, "a", buffering=1)
    log_file.write("\n--- {} at {} ---\n".format(tag, time.ctime()))
    proc = subprocess.Popen(
        [sys.executable, script_path],
        stdout=log_file, stderr=subprocess.STDOUT, cwd=d
    )
    return proc, log_file

def supervisor(uid, fname):
    """
    Owns the instance lifecycle. Waits for exit. If crash → autofix → restart.
    Gives up after MAX_AUTOFIX_RETRIES and notifies the owner.
    """
    key = "{}:{}".format(uid, fname)
    log_path = os.path.join(user_logs_dir(uid), fname + ".log")
    attempts = 0

    while True:
        data = RUNNING_BOTS.get(key)
        if not data:
            return

        proc = data["process"]
        try:
            proc.wait()
        except Exception:
            pass

        # user stop or delete?
        data = RUNNING_BOTS.get(key)
        if not data or data.get("user_stopped"):
            try: data["log"].close()
            except Exception: pass
            RUNNING_BOTS.pop(key, None)
            return

        # clean exit — nothing to fix
        if proc.returncode == 0:
            try: data["log"].close()
            except Exception: pass
            RUNNING_BOTS.pop(key, None)
            return

        # crashed. read tail.
        try:
            with open(log_path, "r", errors="ignore") as f:
                tail = f.read()[-8000:]
        except Exception:
            tail = ""

        if attempts >= MAX_AUTOFIX_RETRIES:
            try:
                bot.send_message(uid,
                    "⚠️ *Autofix gave up* after {} attempts on `{}`\n\n"
                    "Last output:\n```\n{}\n```".format(
                        MAX_AUTOFIX_RETRIES, md_escape(fname), tail[-1200:]),
                    parse_mode="Markdown")
            except Exception:
                pass
            try: data["log"].close()
            except Exception: pass
            RUNNING_BOTS.pop(key, None)
            return

        # try to fix
        err = parse_error(tail)
        fixed, action = (False, "")

        if err:
            fixed, action = apply_fix(err)
        else:
            # fallback: rescan imports in case a new dep appeared
            script_path = os.path.join(user_bots_dir(uid), fname)
            inst, _fail = ensure_deps_for_file(script_path)
            if inst:
                fixed, action = True, "Installed " + ", ".join(inst)

        if not fixed:
            try:
                bot.send_message(uid,
                    "⚠️ *Crash — no autofix available* for `{}`\n\n"
                    "Last output:\n```\n{}\n```".format(
                        md_escape(fname), tail[-1500:]),
                    parse_mode="Markdown")
            except Exception:
                pass
            try: data["log"].close()
            except Exception: pass
            RUNNING_BOTS.pop(key, None)
            return

        attempts += 1
        try:
            bot.send_message(uid,
                "🔧 *Autofix #{}* on `{}`\n┗ {}".format(
                    attempts, md_escape(fname), md_escape(action)),
                parse_mode="Markdown")
        except Exception:
            pass

        # restart
        try:
            new_proc, log_file = _launch_process(
                uid, fname, log_path, tag="autofix restart #{}".format(attempts))
            RUNNING_BOTS[key] = {
                "process": new_proc,
                "start_time": time.time(),
                "log": log_file,
                "uid": uid,
                "file": fname,
                "autofix": True,
            }
        except Exception as e:
            try:
                bot.send_message(uid,
                    "⚠️ Autofix restart failed on `{}`: `{}`".format(
                        md_escape(fname), md_escape(str(e))),
                    parse_mode="Markdown")
            except Exception:
                pass
            return

def start_instance(uid, fname):
    key = "{}:{}".format(uid, fname)
    d = user_bots_dir(uid)
    script_path = os.path.join(d, fname)
    log_path = os.path.join(user_logs_dir(uid), fname + ".log")

    if not os.path.exists(script_path):
        return False, "Script missing."

    # pre-flight: scan imports and install whatever is missing
    try:
        ensure_deps_for_file(script_path)
    except Exception:
        pass

    try:
        proc, log_file = _launch_process(uid, fname, log_path, tag="boot")
    except Exception as e:
        return False, str(e)

    RUNNING_BOTS[key] = {
        "process": proc,
        "start_time": time.time(),
        "log": log_file,
        "uid": uid,
        "file": fname,
        "autofix": True,
    }
    threading.Thread(target=supervisor, args=(uid, fname), daemon=True).start()
    return True, "Started."

def stop_instance(key):
    if key not in RUNNING_BOTS:
        return False
    RUNNING_BOTS[key]["user_stopped"] = True
    try:
        RUNNING_BOTS[key]["process"].terminate()
    except Exception:
        pass
    return True

def kill_instance(key):
    if key not in RUNNING_BOTS:
        return False
    RUNNING_BOTS[key]["user_stopped"] = True
    try:
        RUNNING_BOTS[key]["process"].kill()
    except Exception:
        pass
    return True

# ============================================================
#                       MENUS
# ============================================================
def owner_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🖥 My Bots", "📤 Upload Bot")
    kb.add("👑 Admin Panel", "📦 Pip Manager")
    kb.add("⚡ Server Ping", "📱 System Status")
    kb.add("🛠 Help & All Commands")
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🖥 My Bots", "📤 Upload Bot")
    kb.add("👑 Admin Panel", "📦 Pip Manager")
    kb.add("⚡ Server Ping", "📱 System Status")
    kb.add("🛠 Help")
    return kb

def user_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🖥 My Bots", "📤 Upload Bot")
    kb.add("⚡ Server Ping", "📱 System Status")
    kb.add("🛠 Help")
    return kb

# ============================================================
#                       /start
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id

    if is_owner(uid):
        bot.send_message(uid,
            "👑 *{}*\n_created by {}_\n\n"
            "Welcome back, Master.\n"
            "Full control unlocked.".format(SERVER_NAME, CREATED_BY),
            reply_markup=owner_menu())
        return

    if is_admin(uid):
        bot.send_message(uid,
            "🛡 *{}*\n_created by {}_\n\n"
            "Welcome, Admin.\n"
            "Admin Panel unlocked.".format(SERVER_NAME, CREATED_BY),
            reply_markup=admin_menu())
        return

    if uid in DATA["approved"]:
        bot.send_message(uid,
            "*{}*\n_created by {}_\n\n"
            "✅ Access granted.\n"
            "Tap *🖥 My Bots* to begin.".format(SERVER_NAME, CREATED_BY),
            reply_markup=user_menu())
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔓 Request Access", callback_data="req_access"))
    bot.send_message(uid,
        "*{}*\n_created by {}_\n\n"
        "🔒 Access is restricted.\n"
        "Tap below to request hosting access.\n"
        "Admin approval required.".format(SERVER_NAME, CREATED_BY),
        reply_markup=kb)

# ============================================================
#              ACCESS REQUEST + APPROVAL FLOW
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data == "req_access")
def cb_req_access(call):
    uid = call.from_user.id
    if is_approved(uid):
        bot.answer_callback_query(call.id, "Already approved.")
        return
    if str(uid) in DATA["pending"]:
        bot.answer_callback_query(call.id, "Already pending. Wait for admin.", show_alert=True)
        return

    DATA["pending"][str(uid)] = {
        "username": call.from_user.username or "",
        "name":     call.from_user.full_name or "",
        "at":       time.ctime()
    }
    save_data(DATA)

    u = call.from_user
    notify = ("🔔 *New Access Request*\n\n"
              "👤 Name: `{}`\n"
              "🆔 ID: `{}`\n"
              "📛 Username: `{}`\n"
              "⏰ Time: `{}`").format(
        md_escape(u.full_name or "-"), uid,
        md_escape("@" + u.username if u.username else "-"),
        md_escape(time.ctime()))

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Approve", callback_data="appr_{}".format(uid)),
        types.InlineKeyboardButton("❌ Reject",  callback_data="rej_{}".format(uid))
    )

    targets = set([OWNER_ID] + list(DATA.get("admins", [])))
    for t in targets:
        try: bot.send_message(t, notify, reply_markup=kb)
        except Exception: pass

    bot.answer_callback_query(call.id, "✅ Request sent to admins.", show_alert=True)
    bot.send_message(uid, "⏳ Your request was sent. Wait for approval.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("appr_") or c.data.startswith("rej_"))
def cb_approval(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin or Owner only.", show_alert=True)
        return

    action, uid_str = call.data.split("_", 1)
    try:
        target = int(uid_str)
    except Exception:
        bot.answer_callback_query(call.id, "Bad id.")
        return

    if action == "appr":
        DATA["pending"].pop(str(target), None)
        if target not in DATA["approved"]:
            DATA["approved"].append(target)
        save_data(DATA)
        try:
            bot.edit_message_text(
                (call.message.text or "") + "\n\n✅ *APPROVED by {}*".format(
                    md_escape(call.from_user.first_name or "admin")),
                call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(target,
                "✅ *Access approved!*\nWelcome to *{}*.\nTap /start to open the panel."
                .format(SERVER_NAME), reply_markup=user_menu())
        except Exception:
            pass
    else:
        DATA["pending"].pop(str(target), None)
        save_data(DATA)
        try:
            bot.edit_message_text(
                (call.message.text or "") + "\n\n❌ *REJECTED*",
                call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try: bot.send_message(target, "❌ Access request denied.")
        except Exception: pass
    bot.answer_callback_query(call.id, "Done.")

# ============================================================
#                    ADMIN PANEL (BUTTON)
# ============================================================
@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel")
def cmd_admin_panel(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "⛔ Admin access required.")
        return

    role = "👑 OWNER" if is_owner(uid) else "🛡 ADMIN"
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("👥 Pending Approvals", callback_data="apanel_pending"),
        types.InlineKeyboardButton("🌐 All Instances",     callback_data="apanel_all"),
        types.InlineKeyboardButton("✅ Approved Users",    callback_data="apanel_users"),
    )
    if is_owner(uid):
        kb.add(
            types.InlineKeyboardButton("👤 Manage Admins",   callback_data="apanel_admins"),
            types.InlineKeyboardButton("🧹 Clean Dead",      callback_data="apanel_clean"),
        )
    kb.add(types.InlineKeyboardButton("🔙 Close", callback_data="apanel_close"))

    bot.send_message(message.chat.id,
        "🎛 *{}*\n*Role:* {}\n\nChoose an action below.".format(SERVER_NAME, role),
        reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("apanel_"))
def cb_admin_panel(call):
    uid = call.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return

    data    = call.data
    chat_id = call.message.chat.id
    msg_id  = call.message.message_id
    role    = "👑 OWNER" if is_owner(uid) else "🛡 ADMIN"

    if data == "apanel_close":
        try: bot.delete_message(chat_id, msg_id)
        except Exception: pass
        bot.answer_callback_query(call.id)
        return

    if data == "apanel_pending":
        if not DATA["pending"]:
            bot.answer_callback_query(call.id, "No pending requests.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "👥 *Pending Approvals* — {}".format(len(DATA["pending"])))
        for pid, info in list(DATA["pending"].items()):
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅ Approve", callback_data="appr_{}".format(pid)),
                types.InlineKeyboardButton("❌ Reject",  callback_data="rej_{}".format(pid))
            )
            txt = ("👤 `{}`\n🆔 `{}`\n📛 `{}`").format(
                md_escape(info.get("name", "-")), pid,
                md_escape("@" + info.get("username", "") if info.get("username") else "-"))
            bot.send_message(chat_id, txt, reply_markup=kb)
        return

    if data == "apanel_all":
        if not RUNNING_BOTS:
            bot.answer_callback_query(call.id, "No running instances.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        lines = ["🌐 *ALL RUNNING INSTANCES*\n━━━━━━━━━━━━━━━━"]
        for key, item in list(RUNNING_BOTS.items()):
            proc = item["process"]
            if proc.poll() is None:
                owner_uid, fname = key.split(":", 1)
                up = int(time.time() - item["start_time"])
                lines.append("🟢 `{}` · uid `{}`\n┗ PID `{}` · up `{}s`".format(
                    md_escape(fname), owner_uid, proc.pid, up))
        lines.append("\nKill with `/kill uid:file.py`")
        bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
        return

    if data == "apanel_users":
        if not DATA["approved"]:
            bot.answer_callback_query(call.id, "No approved users.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        lines = ["✅ *Approved Users* — {}".format(len(DATA["approved"]))]
        for auid in DATA["approved"]:
            lines.append("• `{}`".format(auid))
        bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
        return

    if data == "apanel_admins":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "⛔ Owner only.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        admins = DATA.get("admins", [])
        lines = ["👤 *ADMIN MANAGEMENT*\n*Role:* {}".format(role)]
        if not admins:
            lines.append("_No admins added._")
        else:
            lines.append("")
            for aid in admins:
                lines.append("🛡 `{}`".format(aid))
        lines.append("")
        lines.append("*Add:*  reply to a user + `/addadmin`")
        lines.append("*Add:*  `/addadmin [uid]`")
        lines.append("*Remove:*  `/removeadmin [uid]`")
        bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")

        if admins:
            kb = types.InlineKeyboardMarkup(row_width=1)
            for aid in admins:
                kb.add(types.InlineKeyboardButton(
                    "❌ Remove {}".format(aid),
                    callback_data="rmadmin_{}".format(aid)))
            bot.send_message(chat_id, "Tap to remove an admin:", reply_markup=kb)
        return

    if data == "apanel_clean":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "⛔ Owner only.", show_alert=True)
            return
        cleaned = 0
        for key, item in list(RUNNING_BOTS.items()):
            if item["process"].poll() is not None:
                try: item["log"].close()
                except Exception: pass
                RUNNING_BOTS.pop(key, None)
                cleaned += 1
        bot.answer_callback_query(call.id,
            "🧹 Cleaned {} dead instances.".format(cleaned), show_alert=True)
        return

    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rmadmin_"))
def cb_remove_admin(call):
    uid = call.from_user.id
    if not is_owner(uid):
        bot.answer_callback_query(call.id, "⛔ Owner only.", show_alert=True)
        return
    target_str = call.data.split("_", 1)[1]
    try:
        target = int(target_str)
    except Exception:
        bot.answer_callback_query(call.id, "Bad id.")
        return
    if target in DATA["admins"]:
        DATA["admins"].remove(target)
        save_data(DATA)
        bot.answer_callback_query(call.id, "✅ Removed {}.".format(target), show_alert=True)
        try:
            bot.edit_message_text("❌ Removed admin `{}`.".format(target),
                call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        except Exception: pass
        try: bot.send_message(target, "ℹ️ Your admin role has been removed.")
        except Exception: pass
    else:
        bot.answer_callback_query(call.id, "Not an admin.")

# ============================================================
#              OWNER-ONLY: ADD / REMOVE ADMIN COMMANDS
# ============================================================
@bot.message_handler(commands=["addadmin"])
def cmd_addadmin(message):
    uid = message.from_user.id
    if not is_owner(uid):
        bot.reply_to(message, "⛔ Only the Owner can add admins.")
        return

    target = None
    if message.reply_to_message:
        target = message.reply_to_message.from_user.id
    else:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            try:
                target = int(parts[1].strip())
            except ValueError:
                bot.reply_to(message, "⚠️ Invalid user ID.")
                return

    if target is None:
        bot.reply_to(message,
            "⚠️ *Usage*\n"
            "• Reply to a user's message with `/addadmin`\n"
            "• Or `/addadmin [user_id]`")
        return

    if target == OWNER_ID:
        bot.reply_to(message, "👑 Owner already has all powers.")
        return

    if target in DATA["admins"]:
        bot.reply_to(message, "ℹ️ `{}` is already an admin.".format(target))
        return

    DATA["admins"].append(target)
    if target not in DATA["approved"]:
        DATA["approved"].append(target)
    DATA["pending"].pop(str(target), None)
    save_data(DATA)

    bot.reply_to(message, "🛡 *New Admin:* `{}`".format(target))
    try:
        bot.send_message(target,
            "🛡 *You have been promoted to ADMIN*\n"
            "Server: *{}*\n"
            "Tap /start to open the Admin Panel.".format(SERVER_NAME),
            reply_markup=admin_menu())
    except Exception:
        pass

@bot.message_handler(commands=["removeadmin"])
def cmd_removeadmin(message):
    uid = message.from_user.id
    if not is_owner(uid):
        bot.reply_to(message, "⛔ Only the Owner can remove admins.")
        return

    target = None
    if message.reply_to_message:
        target = message.reply_to_message.from_user.id
    else:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            try:
                target = int(parts[1].strip())
            except ValueError:
                bot.reply_to(message, "⚠️ Invalid user ID.")
                return

    if target is None:
        bot.reply_to(message,
            "⚠️ *Usage*\n"
            "• Reply to a message with `/removeadmin`\n"
            "• Or `/removeadmin [user_id]`")
        return

    if target == OWNER_ID:
        bot.reply_to(message, "👑 Cannot remove Owner.")
        return

    if target not in DATA["admins"]:
        bot.reply_to(message, "ℹ️ `{}` is not an admin.".format(target))
        return

    DATA["admins"].remove(target)
    save_data(DATA)
    bot.reply_to(message, "❌ *Removed Admin:* `{}`".format(target))
    try:
        bot.send_message(target,
            "ℹ️ Your admin role on *{}* has been removed.".format(SERVER_NAME),
            reply_markup=user_menu())
    except Exception:
        pass

# ============================================================
#                  SYSTEM STATUS / PING / HELP
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📱 System Status")
def cmd_status(message):
    uid = message.from_user.id
    if not is_authorized(uid): return

    t0 = time.time()
    uptime = int(time.time() - START_TIME)
    h, r = divmod(uptime, 3600); mn, s = divmod(r, 60)
    cpu = psutil.cpu_percent(interval=0.4)
    ram = psutil.virtual_memory().percent
    osinfo = "{} {}".format(platform.system(), platform.release())
    ping = int((time.time() - t0) * 1000)
    role = "👑 OWNER" if is_owner(uid) else ("🛡 ADMIN" if is_admin(uid) else "👤 USER")

    bot.reply_to(message,
        "💻 *{}*\n_created by {}_\n\n"
        "🏓 *Ping:* `{}ms`\n"
        "⏱ *Uptime:* `{}:{:02d}:{:02d}`\n"
        "🖥 *CPU:* `{}%`\n"
        "💾 *RAM:* `{}%`\n"
        "⚙️ *OS:* `{}`\n"
        "🎭 *Role:* {}\n"
        "🔧 *Autofix:* enabled (max {} retries)".format(
            SERVER_NAME, CREATED_BY, ping, h, mn, s, cpu, ram,
            md_escape(osinfo), role, MAX_AUTOFIX_RETRIES))

@bot.message_handler(func=lambda m: m.text == "⚡ Server Ping")
def cmd_ping(message):
    if not is_authorized(message.from_user.id): return
    t0 = time.time()
    msg = bot.reply_to(message, "📡 Pinging...")
    ping = round((time.time() - t0) * 1000)
    bot.edit_message_text("⚡ *Ping:* `{} ms`".format(ping),
                          msg.chat.id, msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["help"])
@bot.message_handler(func=lambda m: m.text in ("🛠 Help", "🛠 Help & All Commands"))
def cmd_help(message):
    uid = message.from_user.id
    if not is_authorized(uid): return

    base = ("🛠 *{} — CONTROL CENTER*\n_created by {}_\n\n"
            "📂 *BUTTONS*\n"
            "• 🖥 My Bots — manage your instances\n"
            "• 📤 Upload Bot — send `.py` or `.zip`\n"
            "• ⚡ Server Ping — latency\n"
            "• 📱 System Status — CPU / RAM / uptime\n"
            "• 📦 Pip Manager — install packages\n\n"
            "🔧 *AUTO-FIX ENGINE*\n"
            "If a running bot crashes, the master reads the traceback,\n"
            "auto-installs / upgrades whatever is missing, and restarts it.\n"
            "Up to *{} retries* per crash cycle.\n\n").format(
                SERVER_NAME, CREATED_BY, MAX_AUTOFIX_RETRIES)

    if is_admin(uid):
        base += ("🛡 *ADMIN COMMANDS*\n"
                 "• 👑 Admin Panel — full control panel\n"
                 "• `/addadmin` *(owner only)*\n"
                 "• `/removeadmin` *(owner only)*\n"
                 "• `/kill [uid:file.py]` — kill an instance\n"
                 "• `/users` — role list\n\n")

    if is_owner(uid):
        base += ("👑 *OWNER COMMANDS*\n"
                 "• `/sh [cmd]` — shell\n"
                 "• `/eval [code]` — python\n"
                 "• `/backup` — zip all bots\n"
                 "• `/restartnode` — reboot master\n"
                 "• `/pip install [pkg]` — install\n")

    bot.reply_to(message, base)

# ============================================================
#               OWNER COMMANDS: sh / eval / backup
# ============================================================
@bot.message_handler(commands=["sh"])
def cmd_sh(message):
    if not is_owner(message.from_user.id): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: `/sh [command]`")
        return
    command = parts[1].strip()
    try:
        proc = subprocess.Popen(command, shell=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        try:
            out, _ = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            out = (out or "") + "\n[timeout — killed]"
        if not out:
            out = "Success. No output."
        if len(out) > 3500:
            out = out[:3500] + "\n...[Truncated]"
        bot.reply_to(message, "💻 *Output:*\n```bash\n{}\n```".format(out))
    except Exception as e:
        bot.reply_to(message, "❌ *Error:*\n```text\n{}\n```".format(str(e)))

@bot.message_handler(commands=["eval"])
def cmd_eval(message):
    if not is_owner(message.from_user.id): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: `/eval [python]`")
        return
    code = parts[1].strip()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(code, {"bot": bot, "message": message, "RUNNING_BOTS": RUNNING_BOTS,
                        "DATA": DATA, "OWNER_ID": OWNER_ID, "os": os, "sys": sys,
                        "time": time, "subprocess": subprocess,
                        "parse_error": parse_error, "apply_fix": apply_fix})
        out = buf.getvalue() or "✅ Executed."
    except Exception:
        out = traceback.format_exc()
    if len(out) > 3500:
        out = out[:3500] + "\n...[Truncated]"
    bot.reply_to(message, "🐍 *Result:*\n```python\n{}\n```".format(out))

@bot.message_handler(commands=["backup"])
def cmd_backup(message):
    if not is_owner(message.from_user.id): return
    msg = bot.reply_to(message, "📦 Zipping...")
    try:
        zip_base = os.path.join(BASE_DIR, "mz_backup")
        shutil.make_archive(zip_base, "zip", BOTS_DIR)
        with open(zip_base + ".zip", "rb") as f:
            bot.send_document(message.chat.id, f,
                              caption="📦 *Backup of {}*".format(SERVER_NAME))
        os.remove(zip_base + ".zip")
        bot.delete_message(message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text("❌ Failed: `{}`".format(md_escape(str(e))),
                              msg.chat.id, msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["users"])
def cmd_users(message):
    if not is_admin(message.from_user.id): return
    owner_line = "👑 Owner: `{}`".format(OWNER_ID)
    admin_lines = ["🛡 Admins:"] + (["• `{}`".format(a) for a in DATA.get("admins", [])] or ["_none_"])
    user_lines  = ["✅ Approved:"] + (["• `{}`".format(u) for u in DATA["approved"]] or ["_none_"])
    bot.reply_to(message, "\n".join([owner_line, ""] + admin_lines + [""] + user_lines),
                 parse_mode="Markdown")

@bot.message_handler(commands=["kill"])
def cmd_kill(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage: `/kill [uid:file.py]`")
        return
    key = parts[1].strip()
    if kill_instance(key):
        bot.reply_to(message, "💥 Killed `{}`".format(md_escape(key)))
    else:
        bot.reply_to(message, "⚠️ No such instance.")

@bot.message_handler(commands=["restartnode"])
def cmd_restart(message):
    if not is_owner(message.from_user.id): return
    bot.reply_to(message, "🔄 Rebooting master...")
    for d in list(RUNNING_BOTS.values()):
        try:
            d["user_stopped"] = True
            d["process"].terminate()
        except Exception:
            pass
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ============================================================
#                       PIP MANAGER
# ============================================================
@bot.message_handler(commands=["pip"])
def cmd_pip(message):
    if not is_owner(message.from_user.id): return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or parts[1].lower() != "install":
        bot.reply_to(message, "⚠️ Usage: `/pip install [package]`")
        return
    pkg = parts[2].strip()
    msg = bot.reply_to(message, "⚙️ Installing `{}`...".format(md_escape(pkg)))
    ok, err = pip_install(pkg)
    if ok:
        bot.edit_message_text("✅ Installed `{}`.".format(md_escape(pkg)),
                              msg.chat.id, msg.message_id, parse_mode="Markdown")
    else:
        bot.edit_message_text("❌ Failed:\n```\n{}\n```".format(err),
                              msg.chat.id, msg.message_id, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📦 Pip Manager")
def cmd_pip_menu(message):
    if not is_authorized(message.from_user.id): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📚 Install Common Pack", callback_data="pip_basic"))
    if is_owner(message.from_user.id):
        kb.add(types.InlineKeyboardButton("⚡ Force Reinstall pip", callback_data="pip_force"))
    bot.reply_to(message,
                 "📦 *Dependency Manager*\nOwner can also use `/pip install [name]`.",
                 reply_markup=kb)

# ============================================================
#                       UPLOAD
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📤 Upload Bot")
def cmd_upload_tip(message):
    if not is_authorized(message.from_user.id): return
    bot.reply_to(message,
                 "📤 Send a `.py` file or `.zip` archive.\n"
                 "Dependencies will be auto-detected and installed.\n"
                 "Runtime errors will be auto-fixed on launch.")

@bot.message_handler(content_types=["document"])
def handle_upload(message):
    uid = message.from_user.id
    if not is_authorized(uid):
        bot.reply_to(message, "⛔ Not authorized. Send /start.")
        return

    fname = safe_filename(message.document.file_name)
    lower = fname.lower()
    is_py  = lower.endswith(".py")
    is_zip = lower.endswith(".zip")
    if not (is_py or is_zip):
        bot.reply_to(message, "❌ Only `.py` or `.zip` accepted.")
        return

    msg = bot.reply_to(message, "📥 Downloading `{}`...".format(md_escape(fname)))
    target_dir = user_bots_dir(uid)
    save_path  = os.path.join(target_dir, fname)

    try:
        info = bot.get_file(message.document.file_id)
        blob = bot.download_file(info.file_path)
        with open(save_path, "wb") as f:
            f.write(blob)

        installed, failed = [], []

        if is_zip:
            bot.edit_message_text("📦 Extracting ZIP...",
                                  msg.chat.id, msg.message_id, parse_mode="Markdown")
            try:
                with zipfile.ZipFile(save_path) as zf:
                    safe_extract(zf, target_dir)
            finally:
                if os.path.exists(save_path):
                    os.remove(save_path)
            py_files = []
            for root, _, files in os.walk(target_dir):
                for fn in files:
                    if fn.lower().endswith(".py"):
                        py_files.append(os.path.join(root, fn))
        else:
            py_files = [save_path]

        if py_files:
            bot.edit_message_text("🔎 Scanning imports...",
                                  msg.chat.id, msg.message_id, parse_mode="Markdown")

            def prog(line):
                try:
                    bot.edit_message_text("⚙️ " + line, msg.chat.id, msg.message_id,
                                          parse_mode="Markdown")
                except Exception:
                    pass

            for pf in py_files:
                inst, fail = ensure_deps_for_file(pf, progress=prog)
                installed += inst
                failed += fail

        lines = ["✅ *Upload complete*"]
        if is_zip:
            lines.append("Extracted into your sandbox.")
        else:
            lines.append("File: `{}`".format(md_escape(fname)))
        if installed:
            lines.append("📦 Installed: " + ", ".join("`{}`".format(md_escape(p)) for p in installed))
        if failed:
            lines.append("⚠️ Failed: " + ", ".join("`{}`".format(md_escape(p[0])) for p in failed))
        lines.append("Tap *🖥 My Bots* to launch.")
        bot.edit_message_text("\n".join(lines),
                              msg.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text("❌ Failed: `{}`".format(md_escape(str(e))),
                              msg.chat.id, msg.message_id, parse_mode="Markdown")

# ============================================================
#                   BOT LIST + INSTANCE MENU
# ============================================================
@bot.message_handler(commands=["mybots"])
@bot.message_handler(func=lambda m: m.text == "🖥 My Bots")
def cmd_mybots(message):
    uid = message.from_user.id
    if not is_authorized(uid): return
    send_bots_menu(uid, message.chat.id)

def send_bots_menu(uid, chat_id, edit_msg_id=None):
    kb = types.InlineKeyboardMarkup(row_width=1)
    d = user_bots_dir(uid)
    try:
        scripts = sorted(f for f in os.listdir(d) if f.lower().endswith(".py"))
    except Exception:
        scripts = []

    if not scripts:
        text = "👑 *No scripts yet.*\nUpload one with 📤."
    else:
        for s in scripts:
            key = "{}:{}".format(uid, s)
            running = key in RUNNING_BOTS and RUNNING_BOTS[key]["process"].poll() is None
            icon = "🟢" if running else "🔴"
            kb.add(types.InlineKeyboardButton("{} {}".format(icon, s),
                                              callback_data="menu_{}".format(s)))
        text = "👑 *Your Instances*"

    if edit_msg_id:
        try:
            bot.edit_message_text(text, chat_id, edit_msg_id,
                                  reply_markup=kb, parse_mode="Markdown")
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

def show_instance_menu(call, uid, fname):
    key = "{}:{}".format(uid, fname)
    running = key in RUNNING_BOTS and RUNNING_BOTS[key]["process"].poll() is None

    kb = types.InlineKeyboardMarkup(row_width=3)
    status_line = ""
    if running:
        up = int(time.time() - RUNNING_BOTS[key]["start_time"])
        status_line = "\n⏱ Uptime: `{}s`".format(up)
        kb.add(
            types.InlineKeyboardButton("🛑 Stop",    callback_data="stop_{}".format(fname)),
            types.InlineKeyboardButton("🔄 Restart", callback_data="restart_{}".format(fname))
        )
        status = "🟢 Running"
    else:
        status = "🔴 Offline"
        kb.add(types.InlineKeyboardButton("▶️ Start", callback_data="start_{}".format(fname)))

    kb.add(
        types.InlineKeyboardButton("📄 Logs",     callback_data="log_{}".format(fname)),
        types.InlineKeyboardButton("🧹 Clear",    callback_data="clearlog_{}".format(fname))
    )
    kb.add(
        types.InlineKeyboardButton("🔄 Refresh",  callback_data="menu_{}".format(fname)),
        types.InlineKeyboardButton("🗑 Delete",   callback_data="del_{}".format(fname))
    )
    kb.add(types.InlineKeyboardButton("🔙 Back",  callback_data="back_main"))

    txt = "⚙️ *Instance:* `{}`\n*Status:* {}{}".format(md_escape(fname), status, status_line)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id,
                          reply_markup=kb, parse_mode="Markdown")

# ============================================================
#                       CALLBACK ROUTER
# ============================================================
@bot.callback_query_handler(func=lambda call: True)
def cb_router(call):
    uid = call.from_user.id
    data = call.data

    if (data.startswith("appr_") or data.startswith("rej_")
        or data == "req_access"
        or data.startswith("apanel_")
        or data.startswith("rmadmin_")):
        return

    if not is_authorized(uid):
        bot.answer_callback_query(call.id, "⛔ Not authorized.", show_alert=True)
        return

    chat_id = call.message.chat.id
    msg_id  = call.message.message_id

    if data == "pip_basic":
        bot.edit_message_text("⚙️ Installing common pack...", chat_id, msg_id, parse_mode="Markdown")
        ok_all = True
        for pkg in ["requests", "python-dotenv", "aiohttp", "flask", "psutil", "beautifulsoup4"]:
            ok, err = pip_install(pkg)
            if not ok:
                ok_all = False
                break
        if ok_all:
            bot.edit_message_text("✅ Pack installed.", chat_id, msg_id, parse_mode="Markdown")
        else:
            bot.edit_message_text("❌ Failed:\n```\n{}\n```".format(err),
                                  chat_id, msg_id, parse_mode="Markdown")
        return

    if data == "pip_force":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "Owner only.", show_alert=True)
            return
        bot.edit_message_text("⚙️ Upgrading pip...", chat_id, msg_id, parse_mode="Markdown")
        ok, err = pip_install("pip", ["--upgrade"])
        if ok:
            bot.edit_message_text("✅ pip upgraded.", chat_id, msg_id, parse_mode="Markdown")
        else:
            bot.edit_message_text("❌ `{}`".format(md_escape(err)),
                                  chat_id, msg_id, parse_mode="Markdown")
        return

    if data == "back_main":
        send_bots_menu(uid, chat_id, msg_id)
        return

    if "_" not in data:
        return

    action, fname = data.split("_", 1)
    key = "{}:{}".format(uid, fname)
    script_path = os.path.join(user_bots_dir(uid), fname)
    log_path    = os.path.join(user_logs_dir(uid), fname + ".log")

    if action == "menu":
        show_instance_menu(call, uid, fname)
        return

    if action == "start":
        if key in RUNNING_BOTS and RUNNING_BOTS[key]["process"].poll() is None:
            bot.answer_callback_query(call.id, "Already running.")
        else:
            ok, msg = start_instance(uid, fname)
            bot.answer_callback_query(call.id, "✅ Booted." if ok else ("❌ " + msg))
        show_instance_menu(call, uid, fname)

    elif action == "stop":
        if key in RUNNING_BOTS and RUNNING_BOTS[key]["process"].poll() is None:
            stop_instance(key)
            bot.answer_callback_query(call.id, "🛑 Stopped (autofix suppressed).")
        else:
            bot.answer_callback_query(call.id, "Already offline.")
        show_instance_menu(call, uid, fname)

    elif action == "restart":
        if key in RUNNING_BOTS:
            stop_instance(key)
            time.sleep(1)
        ok, msg = start_instance(uid, fname)
        bot.answer_callback_query(call.id, "🔄 Restarted." if ok else ("❌ " + msg))
        show_instance_menu(call, uid, fname)

    elif action == "log":
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", errors="ignore") as f:
                    lines = f.readlines()[-8:]
                tail = "".join(lines).strip() or "(empty)"
            except Exception as e:
                tail = "Read error: " + str(e)
        else:
            tail = "No log yet."
        bot.send_message(chat_id, "📄 *Logs — {}*\n```\n{}\n```".format(
            md_escape(fname), tail[:3500]), parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    elif action == "clearlog":
        try:
            with open(log_path, "w") as f:
                f.write("--- Cleared at {} ---\n".format(time.ctime()))
        except Exception:
            pass
        bot.answer_callback_query(call.id, "🧹 Cleared.")
        show_instance_menu(call, uid, fname)

    elif action == "del":
        if key in RUNNING_BOTS:
            kill_instance(key)
            time.sleep(0.5)
        try:
            if os.path.exists(script_path): os.remove(script_path)
            if os.path.exists(log_path):    os.remove(log_path)
        except Exception:
            pass
        bot.answer_callback_query(call.id, "🗑 Deleted.")
        send_bots_menu(uid, chat_id, msg_id)

# ============================================================
#              SAFETY REAPER (safety net only)
# ============================================================
def safety_reaper():
    """Backup cleanup for any orphan entries. Supervisor normally handles this."""
    while True:
        try:
            for key, data in list(RUNNING_BOTS.items()):
                proc = data.get("process")
                if proc and proc.poll() is not None and not data.get("user_stopped"):
                    # supervisor should own this — wait a tick then clean if stuck
                    pass
        except Exception:
            pass
        time.sleep(30)

threading.Thread(target=safety_reaper, daemon=True).start()

# ============================================================
#                       BOOT
# ============================================================
print("⚡ {} booted · by {}".format(SERVER_NAME, CREATED_BY))
print("🔧 Auto-fix engine: max {} retries".format(MAX_AUTOFIX_RETRIES))

while True:
    try:
        bot.infinity_polling(timeout=15, long_polling_timeout=10)
    except Exception as e:
        print("poll err:", e)
        time.sleep(3)