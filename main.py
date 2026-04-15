import os
import requests
import asyncio
import threading
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")

PORT = 10000

OWNER_ID = 5351848105
ALLOWED_USERS = [5344078567]
ALLOWED_GROUPS = [-1003899919015]

app = Client(
    "ManagerBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

users_data = {}

edit = "Maintanence by: @Sub_and_hardsub"

# ================= UTILS =================

def is_authorized(message: Message) -> bool:
    if not message.from_user:
        return False

    uid = message.from_user.id

    if (
        uid == OWNER_ID
        or uid in ALLOWED_USERS
        or message.chat.id in ALLOWED_GROUPS
    ):
        return True

    return False

# ================= GITHUB TRIGGER =================

def trigger_github(task):

    url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/encode.yml/dispatches"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    payload = {
        "ref": "main",
        "inputs": {

            "task_type": task.get("task_type", "hsub"),

            "video_id": task["video"]["file_id"],

            "chat_id": str(task["chat_id"]),

            "sub_id":
            task.get("subtitle", {}).get("file_id", "")
            if task.get("subtitle")
            else "",

            "wm_id":
            task.get("watermark", {}).get("file_id", "")
            if task.get("watermark")
            else "",

            "wm_pos": task.get("wm_pos", ""),

            "target_res":
            str(task.get("target_res", "")),

            "rename_text":
            task.get("video", {}).get(
                "file_name",
                "output.mp4"
            )
        }
    }

    try:

        res = requests.post(
            url,
            headers=headers,
            json=payload
        )

        print("GitHub Response:",
              res.status_code,
              res.text)

        return res.status_code == 204

    except Exception as e:

        print("GitHub Trigger Error:", e)

        return False

# ================= SEND TASK =================

async def send_to_cloud(uid, msg):

    data = users_data.pop(uid)

    status = await msg.reply(
        "⏳ Sending Task to GitHub Cloud..."
    )

    task = {

        "task_type": "hsub",

        "video": data.get("video"),

        "subtitle": data.get("subtitle"),

        "watermark": data.get("watermark"),

        "wm_pos": data.get("wm_pos"),

        "chat_id": data.get("chat_id")
    }

    ok = trigger_github(task)

    if ok:

        await status.edit(
            "✅ Task sent to GitHub!\n"
            "Result will come here."
        )

    else:

        await status.edit(
            "❌ Failed to trigger GitHub.\n"
            "Check token or repo."
        )

# ================= START =================

@app.on_message(filters.command("start"))
async def start(client, message: Message):

    if not is_authorized(message):
        return

    await message.reply(

        f"<b>🔥 Hybrid Hardsub Bot</b>\n\n"

        "/hsub — Add Subtitle\n"

        "/1080pdd /720pdd /480pdd — Resize\n\n"

        f"{edit}"

    )

# ================= RESIZE =================

@app.on_message(
    filters.command(
        ["1080pdd", "720pdd", "480pdd"]
    )
)
async def resize_command(client, message: Message):

    if not is_authorized(message):
        return

    media = None

    if message.reply_to_message:

        media = (
            message.reply_to_message.video
            or
            message.reply_to_message.document
        )

    if not media:

        return await message.reply(
            "❌ Reply to video."
        )

    target = message.command[0].replace(
        "pdd",
        ""
    )

    status = await message.reply(
        f"⏳ Sending Resize {target}p..."
    )

    task = {

        "task_type": "resize",

        "video": {

            "file_id": media.file_id,

            "file_name":
            media.file_name
            or
            f"resize_{target}.mp4"
        },

        "chat_id": message.chat.id,

        "target_res": target
    }

    ok = trigger_github(task)

    if ok:

        await status.edit(
            "✅ Resize Task Sent!"
        )

    else:

        await status.edit(
            "❌ GitHub Trigger Failed."
        )

# ================= HSUB =================

@app.on_message(filters.command("hsub"))
async def hsub_cmd(client, message: Message):

    if not is_authorized(message):
        return

    media = None

    if message.reply_to_message:

        media = (
            message.reply_to_message.video
            or
            message.reply_to_message.document
        )

    if not media:

        return await message.reply(
            "❌ Reply to video."
        )

    users_data[
        message.from_user.id
    ] = {

        "video": {

            "file_id": media.file_id,

            "file_name":
            media.file_name
            or
            "video.mp4"
        },

        "chat_id": message.chat.id,

        "state": "WAIT_SUB"
    }

    await message.reply(
        "📄 Send Subtitle (.srt/.ass)"
    )

# ================= HANDLE INPUT =================

@app.on_message(
    filters.document
    | filters.video
    | filters.photo
    | filters.text
)
async def handle_inputs(client, message: Message):

    if not is_authorized(message):
        return

    uid = message.from_user.id

    if uid not in users_data:
        return

    state = users_data[uid].get("state")

    # Subtitle

    if (
        state == "WAIT_SUB"
        and message.document
    ):

        if message.document.file_name.endswith(
            (".srt", ".ass")
        ):

            users_data[uid][
                "subtitle"
            ] = {

                "file_id":
                message.document.file_id,

                "file_name":
                message.document.file_name
            }

            users_data[uid][
                "state"
            ] = "WAIT_WM"

            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "Add Watermark",
                    callback_data="wm_yes"
                ),

                InlineKeyboardButton(
                    "Skip",
                    callback_data="wm_skip"
                )
            ]])

            await message.reply(
                "Add Watermark?",
                reply_markup=btn
            )

    # Watermark

    elif (
        state == "WAIT_WM_PIC"
        and message.photo
    ):

        users_data[uid][
            "watermark"
        ] = {

            "file_id":
            message.photo.file_id
        }

        users_data[uid][
            "state"
        ] = "WAIT_POS"

        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "Top Left",
                callback_data="pos_TL"
            ),

            InlineKeyboardButton(
                "Top Right",
                callback_data="pos_TR"
            )
        ]])

        await message.reply(
            "Select Position:",
            reply_markup=btn
        )

# ================= CALLBACK =================

@app.on_callback_query()
async def callbacks(
    client,
    query: CallbackQuery
):

    uid = query.from_user.id

    if uid not in users_data:

        return await query.answer(
            "Not your task",
            show_alert=True
        )

    d = query.data

    if d == "wm_yes":

        users_data[uid][
            "state"
        ] = "WAIT_WM_PIC"

        await query.message.edit(
            "Send watermark photo."
        )

    elif d == "wm_skip":

        users_data[uid][
            "watermark"
        ] = None

        await send_to_cloud(
            uid,
            query.message
        )

    elif d.startswith("pos_"):

        users_data[uid][
            "wm_pos"
        ] = "TL" if d == "pos_TL" else "TR"

        await send_to_cloud(
            uid,
            query.message
        )

# ================= HEALTH =================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.end_headers()

        self.wfile.write(
            b"Bot is Running"
        )

# ================= MAIN =================

async def main():

    await app.start()

    print("Hybrid Manager Bot Started!")

    await idle()

if __name__ == "__main__":
    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(),
        daemon=True
    ).start()

    asyncio.run(main())
