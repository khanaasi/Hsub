import os
import json
import asyncio
import threading
import time
import logging
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")          # format: "username/repo"
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", ".github/workflows/encode.yml")
PORT = int(os.getenv("PORT", "10000"))

OWNER_ID = 5351848105
ALLOWED_USERS = [5344078567]
ALLOWED_GROUPS = [-1003899919015]

app = Client("HybridBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= GLOBAL STATE =================
user_data = {}               # temporary data while collecting video/subtitle
task_queue = deque()         # waiting tasks
processing = set()           # user_ids currently being processed (to avoid duplicates)
cancelled = set()            # user_ids cancelled
workflow_run_ids = {}        # user_id -> run_id (to cancel later)
strikes = {}                 # user_id -> strike count
banned_users = set()

# ================= HELPERS =================
def is_authorized(m: Message) -> bool:
    if not m.from_user:
        return False
    uid = m.from_user.id
    if uid in banned_users:
        return False
    return uid == OWNER_ID or uid in ALLOWED_USERS or m.chat.id in ALLOWED_GROUPS

async def check_size(m: Message, size_bytes: int) -> bool:
    if size_bytes > 1073741824:   # 1 GB
        uid = m.from_user.id
        strikes[uid] = strikes.get(uid, 0) + 1
        if strikes[uid] >= 3:
            banned_users.add(uid)
            await m.reply("🚫 You are **banned** for uploading >1GB three times.")
        else:
            await m.reply(f"⚠️ **Warning ({strikes[uid]}/3)**\nFile >1GB not allowed.")
        return False
    return True

def trigger_github_workflow(task: dict) -> tuple:
    """Returns (success, run_id)"""
    url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "main",
        "inputs": {
            "task_type": task.get("task_type", "hsub"),
            "video_id": task["video_id"],
            "sub_id": task.get("sub_id", ""),
            "wm_id": task.get("wm_id", ""),
            "wm_pos": task.get("wm_pos", ""),
            "target_res": str(task.get("target_res", "")),
            "chat_id": str(task["chat_id"]),
            "rename_text": task.get("rename_text", "output.mp4")
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        logger.info(f"github trigger status: {resp.status_code} - {resp.text}")
        if resp.status_code == 204:
            # fetch latest run id (optional)
            runs_url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}/runs"
            runs_resp = requests.get(runs_url, headers=headers)
            if runs_resp.status_code == 200:
                runs = runs_resp.json().get("workflow_runs", [])
                if runs:
                    return True, runs[0]["id"]
            return True, None
        else:
            return False, None
    except Exception as e:
        logger.error(f"github trigger error: {e}")
        return False, None

async def cancel_workflow(user_id: int, run_id: int):
    if not run_id:
        return
    url = f"https://api.github.com/repos/{REPO_NAME}/actions/runs/{run_id}/cancel"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        resp = requests.post(url, headers=headers, timeout=10)
        logger.info(f"cancel workflow {run_id} -> {resp.status_code}")
    except Exception as e:
        logger.error(f"cancel error: {e}")

# ================= QUEUE WORKER =================
async def queue_worker():
    while True:
        if not task_queue:
            await asyncio.sleep(2)
            continue
        task = task_queue.popleft()
        uid = task["user_id"]
        if uid in cancelled:
            cancelled.discard(uid)
            processing.discard(uid)
            continue
        processing.add(uid)
        status_msg = await app.send_message(task["chat_id"], "⏳ Sending task to GitHub...")
        try:
            # Prepare github inputs
            github_task = {
                "task_type": task["task_type"],
                "video_id": task["video_id"],
                "sub_id": task.get("sub_id", ""),
                "wm_id": task.get("wm_id", ""),
                "wm_pos": task.get("wm_pos", ""),
                "target_res": task.get("target_res", ""),
                "chat_id": task["chat_id"],
                "rename_text": task.get("rename_text", "output.mp4")
            }
            success, run_id = trigger_github_workflow(github_task)
            if success:
                workflow_run_ids[uid] = run_id
                await status_msg.edit("✅ Task sent to GitHub! Encoding will start soon.\nResult will be delivered here.")
            else:
                await status_msg.edit("❌ Failed to trigger GitHub. Please try again later.")
        except Exception as e:
            logger.exception("queue worker error")
            await status_msg.edit(f"❌ Error: {str(e)[:100]}")
        finally:
            processing.discard(uid)
            if uid in workflow_run_ids:
                del workflow_run_ids[uid]

# ================= BOT COMMANDS =================
@app.on_message(filters.command("start"))
async def start_cmd(_, m: Message):
    if not is_authorized(m):
        return
    await m.reply(
        "🔥 **Hybrid Hardsub Bot (Render + GitHub)**\n\n"
        "Send video → use /hsub → send subtitle → done.\n"
        "Or reply to video with /1080pdd, /720pdd, /480pdd\n\n"
        "/cancel – cancel your current task\n"
        f"Maintained by @Sub_and_hardsub"
    )

@app.on_message(filters.command("cancel"))
async def cancel_cmd(_, m: Message):
    if not is_authorized(m):
        return
    uid = m.from_user.id
    cancelled.add(uid)
    # remove from queue
    new_queue = deque()
    for t in task_queue:
        if t["user_id"] != uid:
            new_queue.append(t)
    task_queue.clear()
    task_queue.extend(new_queue)
    # cancel if workflow already running
    run_id = workflow_run_ids.get(uid)
    if run_id:
        await cancel_workflow(uid, run_id)
        workflow_run_ids.pop(uid, None)
    # clear user_data
    user_data.pop(uid, None)
    processing.discard(uid)
    await m.reply("🛑 Your task has been cancelled (if any).")

@app.on_message(filters.command(["1080pdd", "720pdd", "480pdd"]))
async def resize_cmd(_, m: Message):
    if not is_authorized(m):
        return
    target = m.command[0].replace("pdd", "")
    replied = m.reply_to_message
    if not replied or not (replied.video or replied.document):
        return await m.reply("❌ Reply to a video file.")
    media = replied.video or replied.document
    if not await check_size(m, media.file_size):
        return
    uid = m.from_user.id
    if uid in processing or any(t["user_id"] == uid for t in task_queue):
        return await m.reply("⚠️ You already have a pending task. Use /cancel first.")
    task = {
        "user_id": uid,
        "task_type": "resize",
        "video_id": media.file_id,
        "target_res": target,
        "chat_id": m.chat.id,
        "rename_text": f"resized_{target}p.mp4"
    }
    task_queue.append(task)
    await m.reply(f"✅ Resize to {target}p added to queue.\nPosition: {len(task_queue)}")

@app.on_message(filters.command("hsub"))
async def hsub_cmd(_, m: Message):
    if not is_authorized(m):
        return
    replied = m.reply_to_message
    if not replied or not (replied.video or replied.document):
        return await m.reply("❌ Reply to a video.")
    media = replied.video or replied.document
    if not await check_size(m, media.file_size):
        return
    uid = m.from_user.id
    if uid in processing or any(t["user_id"] == uid for t in task_queue):
        return await m.reply("⚠️ You already have a pending task. Use /cancel first.")
    user_data[uid] = {
        "video_id": media.file_id,
        "chat_id": m.chat.id,
        "rename_text": media.file_name or "video.mp4",
        "state": "wait_sub"
    }
    await m.reply("📄 Now send me the **subtitle file** (.srt or .ass)")

# ================= HANDLE SUBTITLE, WATERMARK =================
@app.on_message(filters.document | filters.photo)
async def handle_media(_, m: Message):
    if not is_authorized(m):
        return
    uid = m.from_user.id
    if uid not in user_data:
        return
    state = user_data[uid].get("state")
    if state == "wait_sub" and m.document and m.document.file_name.endswith((".srt", ".ass")):
        user_data[uid]["sub_id"] = m.document.file_id
        user_data[uid]["state"] = "wait_wm_choice"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Yes", callback_data="wm_yes"),
            InlineKeyboardButton("No", callback_data="wm_no")
        ]])
        await m.reply("Add a watermark image?", reply_markup=kb)
    elif state == "wait_wm_pic" and m.photo:
        user_data[uid]["wm_id"] = m.photo.file_id
        user_data[uid]["state"] = "wait_wm_pos"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Top Left", callback_data="pos_TL"),
            InlineKeyboardButton("Top Right", callback_data="pos_TR")
        ]])
        await m.reply("Select watermark position:", reply_markup=kb)
    else:
        await m.reply("❌ Unexpected file. Use /hsub again.")

@app.on_callback_query()
async def handle_cb(_, cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in user_data:
        return await cb.answer("No active session", show_alert=True)
    data = cb.data
    if data == "wm_yes":
        user_data[uid]["state"] = "wait_wm_pic"
        await cb.message.edit("Send me the **watermark image** (photo).")
    elif data == "wm_no":
        user_data[uid]["wm_id"] = ""
        user_data[uid]["state"] = "final"
        await finalize_task(uid, cb.message)
    elif data.startswith("pos_"):
        user_data[uid]["wm_pos"] = "TL" if data == "pos_TL" else "TR"
        user_data[uid]["state"] = "final"
        await finalize_task(uid, cb.message)
    await cb.answer()

async def finalize_task(uid, msg):
    data = user_data.pop(uid)
    if uid in processing or any(t["user_id"] == uid for t in task_queue):
        await msg.edit("⚠️ You already have a task in queue. Use /cancel first.")
        return
    task = {
        "user_id": uid,
        "task_type": "hsub",
        "video_id": data["video_id"],
        "sub_id": data.get("sub_id", ""),
        "wm_id": data.get("wm_id", ""),
        "wm_pos": data.get("wm_pos", ""),
        "chat_id": data["chat_id"],
        "rename_text": data.get("rename_text", "output.mp4")
    }
    task_queue.append(task)
    await msg.edit(f"✅ Hardsub task added to queue.\nPosition: {len(task_queue)}")

# ================= HEALTH CHECK SERVER =================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

# ================= MAIN =================
async def main():
    await app.start()
    logger.info("Hybrid Bot Started on Render")
    asyncio.create_task(queue_worker())
    await idle()

if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(main())
