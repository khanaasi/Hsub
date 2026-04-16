import os
import asyncio
import pyrogram.utils

# ================= FIX PYROGRAM BUG FOR NEW LONG IDs =================
def patched_get_peer_type(peer_id: int) -> str:
    val = str(peer_id)
    if val.startswith("-100"): return "channel"
    elif val.startswith("-"): return "chat"
    else: return "user"

pyrogram.utils.get_peer_type = patched_get_peer_type
# =====================================================================

from pyrogram import Client

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

TASK_TYPE = os.getenv("TASK_TYPE")
VIDEO_ID = os.getenv("VIDEO_ID")
SUB_ID = os.getenv("SUB_ID")
CHAT_ID = int(os.getenv("CHAT_ID"))
RESO = os.getenv("RESOLUTION")

app = Client("encoder", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def main():
    await app.start()
    
    # Ab yeh line bina kisi error ke tumhare group me message bhej degi!
    status_msg = await app.send_message(CHAT_ID, "⚙️ Worker Started: 📥 Downloading Video...")
    
    try:
        video_path = await app.download_media(VIDEO_ID)
        output = "output.mp4"
        
        cmd = ["ffmpeg", "-y", "-i", video_path]

        if TASK_TYPE == "hsub":
            await status_msg.edit("⚙️ Worker: 📥 Downloading Subtitle...")
            
            sub_path = await app.download_media(SUB_ID)
            abs_sub = os.path.abspath(sub_path).replace('\\', '/')
            
            cmd.extend([
                "-vf", f"subtitles='{abs_sub}'",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "96k", output
            ])
            
        elif TASK_TYPE == "resize":
            await status_msg.edit(f"⚙️ Worker: Applying {RESO}p Resize...")
            cmd.extend([
                "-vf", f"scale=-2:{RESO}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "96k", output
            ])

        await status_msg.edit("🔥 Worker: Encoding Started... (It may take a few minutes)")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 0:
            await status_msg.edit("📤 Worker: Uploading Result to Telegram...")
            caption = "✅ Hardsubbed by GitHub" if TASK_TYPE == "hsub" else f"✅ Resized to {RESO}p by GitHub"
            
            await app.send_document(CHAT_ID, document=output, caption=caption)
            await status_msg.delete()
        else:
            error_text = stderr.decode()[-800:]  
            await status_msg.edit(f"❌ **FFmpeg Error:**\n`{error_text}`")

    except Exception as e:
        await status_msg.edit(f"❌ **Script Error:**\n`{str(e)}`")

    finally:
        await app.stop()

asyncio.run(main())
