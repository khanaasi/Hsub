import os
import requests
import asyncio
import threading
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= CONFIGURATION =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")
PORT = 10000 # Tumhara original port

OWNER_ID = 5351848105       
ALLOWED_USERS = [5344078567]             
ALLOWED_GROUPS = [-1003899919015] 

app = Client("ManagerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

users_data = {}
edit = "Maintanence by: @Sub_and_hardsub"

# ================= UTILS =================
def is_authorized(message: Message) -> bool:
    if not message.from_user: return False
    u_id = message.from_user.id    
    if u_id == OWNER_ID or u_id in ALLOWED_USERS or message.chat.id in ALLOWED_GROUPS:
        return True
    return False

# ================= GITHUB TRIGGER =================
def trigger_github(task):
    url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/encode.yml/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    payload = {
        "ref": "main",
        "inputs": {
            "task_type": task.get("task_type", "hsub"),
            "video_id": task["video"]["file_id"],
            "chat_id": str(task["chat_id"]),
            "sub_id": task.get("subtitle", {}).get("file_id", "") if task.get("subtitle") else "",
            "wm_id": task.get("watermark", {}).get("file_id", "") if task.get("watermark") else "",
            "wm_pos": task.get("wm_pos", ""),
            "target_res": str(task.get("target_res", "")),
            "rename_text": task.get("video", {}).get("file_name", "output.mp4")
        }
    }
    res = requests.post(url, headers=headers, json=payload)
    return res.status_code == 204

async def send_to_cloud(uid, msg):
    d = users_data.pop(uid)
    status = await msg.reply("⏳ Sending Task to GitHub Cloud...")
    task = {
        "task_type": "hsub",
        "video": d.get("video"),
        "subtitle": d.get("subtitle"),
        "watermark": d.get("watermark"),
        "wm_pos": d.get("wm_pos"),
        "chat_id": d.get("chat_id")
    }
    if trigger_github(task):
        await status.edit("✅ Hardsub Task Sent to GitHub!\nVideo will be uploaded here when done.")
    else:
        await status.edit("❌ Failed to trigger GitHub. Check settings.")

# ================= HANDLERS =================
@app.on_message(filters.command("start"))
async def start(client, message: Message):
    if not is_authorized(message): return
    await message.reply(f"<b>🔥 Hybrid Hardsub bot (Render + GitHub)</b>\n\n/hsub - Add subtitle\n/1080pdd, /720pdd, /480pdd - Resize\n\n{edit}")

@app.on_message(filters.command(["1080pdd", "720pdd", "480pdd"]))
async def resize_command(client, message: Message):
    if not is_authorized(message): return
    target = message.command[0].replace("pdd", "")
    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")
    
    status = await message.reply(f"⏳ Sending Resize {target}p Task to Cloud...")
    task = {
        "task_type": "resize",
        "video": {"file_id": media.file_id, "file_name": media.file_name or f"resized_{target}p.mp4"},
        "chat_id": message.chat.id,
        "target_res": target
    }
    
    if trigger_github(task):
        await status.edit("✅ Task successfully sent to GitHub!\nResult will arrive here.")
    else:
        await status.edit("❌ Failed to trigger GitHub.")

@app.on_message(filters.command("hsub"))
async def hsub_cmd(client, message: Message):
    if not is_authorized(message): return
    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")
    
    users_data[message.from_user.id] = {
        "video": {"file_id": media.file_id, "file_name": media.file_name or "video.mp4"}, 
        "chat_id": message.chat.id, 
        "state": "WAIT_SUB"
    }
    await message.reply("📄 Send Subtitle (.srt/.ass)", reply_to_message_id=message.id)

@app.on_message(filters.document | filters.video | filters.photo | filters.text)
async def handle_inputs(client, message: Message):
    if not is_authorized(message): return
    uid = message.from_user.id
    if uid not in users_data: return
    state = users_data[uid].get("state")
    
    if state == "WAIT_SUB" and message.document and message.document.file_name.endswith((".srt", ".ass")):
        users_data[uid]["subtitle"] = {"file_id": message.document.file_id, "file_name": message.document.file_name}
        users_data[uid]["state"] = "WAIT_WM_CHOICE"
        await message.reply("Add Watermark?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data="wm_yes"), InlineKeyboardButton("No", callback_data="wm_skip")]]), reply_to_message_id=message.id)
    
    elif state == "WAIT_WM_PIC" and message.photo:
        users_data[uid]["watermark"] = {"file_id": message.photo.file_id}
        users_data[uid]["state"] = "WAIT_WM_POS"
        await message.reply("Position:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Top-Left", callback_data="pos_TL"), InlineKeyboardButton("Top-Right", callback_data="pos_TR")]]), reply_to_message_id=message.id)
    
    elif state == "WAIT_RENAME_TEXT" and message.text:
        users_data[uid]["video"]["file_name"] = message.text.strip() + ".mp4" if not message.text.endswith(".mp4") else message.text.strip()
        await send_to_cloud(uid, message)

@app.on_callback_query()
async def callbacks(client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in users_data: return await query.answer("Ye aapka task nahi hai!", show_alert=True)
    d = query.data
    
    if d == "wm_yes":
        users_data[uid]["state"] = "WAIT_WM_PIC"
        await query.message.edit("🖼️ Send Photo.")
    elif d == "wm_skip":
        users_data[uid]["watermark"] = None
        users_data[uid]["state"] = "WAIT_RENAME_CHOICE"
        await ask_rename(query.message)
    elif d.startswith("pos_"):
        users_data[uid]["wm_pos"] = "TL" if d == "pos_TL" else "TR"
        users_data[uid]["state"] = "WAIT_RENAME_CHOICE"
        await ask_rename(query.message)
    elif d == "rn_yes":
        users_data[uid]["state"] = "WAIT_RENAME_TEXT"
        await query.message.edit("📝 Send new name.")
    elif d == "rn_skip":
        import os as os_mod
        users_data[uid]["video"]["file_name"] = os_mod.path.splitext(users_data[uid]["video"]["file_name"])[0] + ".mp4"
        await send_to_cloud(uid, query.message)

async def ask_rename(msg):
    await msg.edit("Rename file?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data="rn_yes"), InlineKeyboardButton("Skip", callback_data="rn_skip")]]))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bot is Running")

async def main():
    if edit != "Maintanence by: @Sub_and_hardsub": return
    await app.start()
    print("Hybrid Manager Bot Started!")
    await idle()

if __name__ == "__main__":
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
