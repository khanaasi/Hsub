import os
import asyncio
from pyrogram import Client

# GitHub Secrets se uthayega (Publicly nahi dikhega)
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

TASK_TYPE = os.environ.get("TASK_TYPE")
VIDEO_ID = os.environ.get("VIDEO_ID")
SUB_ID = os.environ.get("SUB_ID")
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TARGET_RES = os.environ.get("TARGET_RES")
RENAME_TEXT = os.environ.get("RENAME_TEXT", "output.mp4")

app = Client("Worker", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def encode():
    await app.start()
    status = await app.send_message(CHAT_ID, "⚙️ GitHub Worker Started!\n📥 Downloading video...")
    
    vid_path = await app.download_media(VIDEO_ID, file_name="video.mp4")
    out_path = f"out_{RENAME_TEXT}"
    
    if TASK_TYPE == "resize":
        await status.edit(f"🔄 Resizing to {TARGET_RES}p (Ultrafast preset)...")
        cmd = [
            "ffmpeg", "-y", "-i", vid_path, "-vf", f"scale=-2:{TARGET_RES}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            "-c:a", "copy", out_path
        ]
        
    elif TASK_TYPE == "hsub":
        await status.edit("📥 Downloading Subtitle...")
        sub_path = await app.download_media(SUB_ID, file_name="sub.srt")
        abs_sub = os.path.abspath(sub_path).replace('\\', '/')
        await status.edit("🔥 Burning Subtitles (Ultrafast preset)...")
        cmd = [
            "ffmpeg", "-y", "-i", vid_path, "-vf", f"subtitles='{abs_sub}'",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            "-c:a", "copy", out_path
        ]
    
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.wait()
    
    if os.path.exists(out_path):
        await status.edit("📤 Encoding done. Uploading to Telegram...")
        await app.send_document(CHAT_ID, document=out_path, caption=RENAME_TEXT)
        await status.delete()
    else:
        await status.edit("❌ Encoding failed on GitHub.")

    await app.stop()

if __name__ == "__main__":
    asyncio.run(encode())
