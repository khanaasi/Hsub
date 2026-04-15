import os
import requests
import asyncio
import threading
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from http.server import HTTPServer, BaseHTTPRequestHandler

# API Keys aur Tokens (Render Dashboard se uthayega)
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")
PORT = int(os.getenv("PORT", 10000))

# Security
OWNER_ID = 5351848105       
ALLOWED_USERS = [5344078567]             
ALLOWED_GROUPS = [-1003899919015] 

app = Client("ManagerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
users_data = {}

def is_authorized(message: Message) -> bool:
    if not message.from_user: return False
    u_id = message.from_user.id    
    if u_id == OWNER_ID or u_id in ALLOWED_USERS or message.chat.id in ALLOWED_GROUPS:
        return True
    return False

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
            "target_res": str(task.get("target_res", "")),
            "rename_text": task.get("video", {}).get("file_name", "output.mp4")
        }
    }
    res = requests.post(url, headers=headers, json=payload)
    return res.status_code == 204

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    if not is_authorized(message): return
    await message.reply("<b>🔥 Hybrid Bot Running</b>\n/hsub - Add subtitle\n/1080pdd, /720pdd, /480pdd - Resize")

@app.on_message(filters.command(["1080pdd", "720pdd", "480pdd"]))
async def resize_command(client, message: Message):
    if not is_authorized(message): return
    target = message.command[0].replace("pdd", "")
    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")
    
    status = await message.reply(f"⏳ Sending Resize {target}p Task to GitHub...")
    task = {
        "task_type": "resize",
        "video": {"file_id": media.file_id, "file_name": media.file_name or "video.mp4"},
        "chat_id": message.chat.id,
        "target_res": target
    }
    
    if trigger_github(task):
        await status.edit("✅ Task sent to GitHub Server!\nEncoding will happen in background.")
    else:
        await status.edit("❌ Failed to trigger GitHub.")

@app.on_message(filters.command("hsub"))
async def hsub_cmd(client, message: Message):
    if not is_authorized(message): return
    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")
    
    users_data[message.from_user.id] = {
        "task_type": "hsub",
        "video": {"file_id": media.file_id, "file_name": media.file_name or "video.mp4"}, 
        "chat_id": message.chat.id, 
        "state": "WAIT_SUB"
    }
    await message.reply("📄 Send Subtitle (.srt/.ass)", reply_to_message_id=message.id)

@app.on_message(filters.document)
async def handle_inputs(client, message: Message):
    if not is_authorized(message): return
    uid = message.from_user.id
    if uid not in users_data: return
    state = users_data[uid].get("state")
    
    if state == "WAIT_SUB" and message.document.file_name.endswith((".srt", ".ass")):
        users_data[uid]["subtitle"] = {"file_id": message.document.file_id, "file_name": message.document.file_name}
        users_data[uid]["state"] = "WAIT_RENAME_TEXT"
        await message.reply("📝 Send new name for output file (or type 'skip').", reply_to_message_id=message.id)

@app.on_message(filters.text)
async def handle_text(client, message: Message):
    uid = message.from_user.id
    if uid in users_data and users_data[uid].get("state") == "WAIT_RENAME_TEXT":
        if message.text.lower() != "skip":
            users_data[uid]["video"]["file_name"] = message.text.strip() + ".mp4" if not message.text.endswith(".mp4") else message.text.strip()
        
        task = users_data.pop(uid)
        status = await message.reply("⏳ Sending Hardsub Task to GitHub...")
        if trigger_github(task):
            await status.edit("✅ Hardsub Task sent to GitHub!\nCheck chat after few minutes.")
        else:
            await status.edit("❌ Failed to trigger GitHub.")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bot is Running")

async def main():
    await app.start()
    print("Manager Bot Started!")
    await idle()

if __name__ == "__main__":
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
