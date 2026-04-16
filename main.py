import os
import asyncio
import threading
import requests
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= CONFIGURATION =================
# Environment variables se token lena safe hai
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")  # Format: username/repo

PORT = 10000

# Permissions
OWNER_ID = 5351848105       
ALLOWED_USERS = [5344078567]             
ALLOWED_GROUPS = [-1003899919015] 

app = Client("ManagerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Global Variables
users_data = {}
BANNED_USERS = set()
user_strikes = {}
edit = "Maintanence by: @Sub_and_hardsub"

# ================= UTILS =================
def is_authorized(message: Message) -> bool:
    if not message.from_user: return False
    u_id = message.from_user.id    
    if u_id in BANNED_USERS: return False
    if u_id == OWNER_ID or u_id in ALLOWED_USERS or message.chat.id in ALLOWED_GROUPS:
        return True
    return False

# ================= GITHUB TRIGGER =================
def _send_to_github(task):
    """Internal function for GitHub API call"""
    url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/encode.yml/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    payload = {
        "ref": "main",
        "inputs": task
    }
    try:
        r = requests.post(url, headers=headers, json=payload)
        return r.status_code == 204
    except Exception as e:
        print(f"GitHub Trigger Error: {e}")
        return False

async def trigger_github(task):
    """Async wrapper to prevent Bot freezing during API call"""
    return await asyncio.to_thread(_send_to_github, task)

# ================= COMMANDS =================
@app.on_message(filters.command("start"))
async def start(client, message: Message):
    if not is_authorized(message): return
    await message.reply(
        f"<b>🔥 Hardsub Bot (GitHub Engine)</b>\n\n"
        f"/hsub - Add subtitle to video\n"
        f"/1080pdd, /720pdd, /480pdd - Resize Video\n"
        f"/cancel - Stop current task\n\n"
        f"{edit}"
    )

@app.on_message(filters.command(["cancel", "remm"]))
async def cancel_task(client, message: Message):
    if not is_authorized(message): return
    uid = message.from_user.id
    if uid in users_data:
        del users_data[uid]
        await message.reply("🛑 Setup process cancelled from bot memory.")
    else:
        await message.reply("❌ No active setup process running.")

@app.on_message(filters.command(["1080pdd", "720pdd", "480pdd"]))
async def resize_command(client, message: Message):
    if not is_authorized(message): return
    target = message.command[0].replace("pdd", "")
    
    replied = message.reply_to_message
    media = replied.video or replied.document if replied else None
    
    if not media: 
        return await message.reply("❌ Please reply to a video file.")

    status = await message.reply(f"⏳ Sending {target}p Resize Task to GitHub...")
    
    task = {
        "task_type": "resize",
        "video_id": media.file_id,
        "sub_id": "none",
        "chat_id": str(message.chat.id),
        "resolution": target
    }
    
    success = await trigger_github(task)
    if success:
        await status.edit(f"✅ **Task Sent!**\nGitHub is resizing your video to {target}p.\nWait a few minutes for the upload.")
    else:
        await status.edit("❌ **GitHub Trigger Failed!** Check REPO_NAME and GITHUB_TOKEN.")

@app.on_message(filters.command("hsub"))
async def hsub_cmd(client, message: Message):
    if not is_authorized(message): return
    
    replied = message.reply_to_message
    media = replied.video or replied.document if replied else None
    
    if not media: 
        return await message.reply("❌ Please reply to a video file.")

    users_data[message.from_user.id] = {
        "video_id": media.file_id,
        "chat_id": str(message.chat.id)
    }
    await message.reply("📄 Now send the Subtitle file (.srt/.ass)", reply_to_message_id=message.id)

@app.on_message(filters.document)
async def subtitle_received(client, message: Message):
    if not is_authorized(message): return
    uid = message.from_user.id
    
    # Agar user list me nahi hai, toh do nothing
    if uid not in users_data: return
    
    sub = message.document
    if not sub.file_name.endswith((".srt", ".ass")):
        return await message.reply("❌ Error: Please send a valid .srt or .ass file.")

    status = await message.reply("⏳ Sending Hardsub Task to GitHub...")

    task = {
        "task_type": "hsub",
        "video_id": users_data[uid]["video_id"],
        "sub_id": sub.file_id,
        "chat_id": users_data[uid]["chat_id"],
        "resolution": "none"
    }

    success = await trigger_github(task)
    if success:
        await status.edit("✅ **Task Sent!**\nGitHub has started processing the hardsub.\nVideo will be uploaded soon.")
    else:
        await status.edit("❌ **GitHub Trigger Failed!**")

    # Memory clean up after sending task
    users_data.pop(uid, None)

# ================= RENDER FREE TIER PORT SYSTEM =================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running")

async def main():
    # Protection loop just like your old code
    if edit != "Maintanence by: @Sub_and_hardsub": 
        print("Error: Credit string modified!")
        return
        
    await app.start()
    print("Bot started on PORT 10000 (Render Free Tier Safe)")
    await idle()

if __name__ == "__main__":
    # EXACT INLINE THREAD FROM YOUR OLD CODE
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
