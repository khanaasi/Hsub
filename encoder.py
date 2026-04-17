import os
import time
import asyncio
import pyrogram.utils

# Pyrogram bug fix
def patched_get_peer_type(peer_id: int) -> str:
    val = str(peer_id)
    if val.startswith("-100"): return "channel"
    elif val.startswith("-"): return "chat"
    else: return "user"

pyrogram.utils.get_peer_type = patched_get_peer_type

from pyrogram import Client

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

TASK_TYPE = os.getenv("TASK_TYPE")
VIDEO_ID = os.getenv("VIDEO_ID")
SUB_ID = os.getenv("SUB_ID")
CHAT_ID = int(os.getenv("CHAT_ID"))
RESO = os.getenv("RESOLUTION")
WM_ID = os.getenv("WM_ID")
WM_POS = os.getenv("WM_POS")
RENAME = os.getenv("RENAME")

# Clean Init (No stop/start tricks, pure client)
app = Client("encoder", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

last_edit_time = 0

async def progress_bar(current, total, msg_id, action_text):
    global last_edit_time
    now = time.time()
    if now - last_edit_time > 10 or current == total:
        try:
            percent = (current / total) * 100 if total > 0 else 0
            curr_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024) if total > 0 else 0
            await app.edit_message_text(CHAT_ID, msg_id, f"⚙️ Worker: {action_text}\n⏳ `{percent:.1f}%` ({curr_mb:.1f}MB / {tot_mb:.1f}MB)")
            last_edit_time = now
        except:
            pass

async def main():
    await app.start()
    status_msg = await app.send_message(CHAT_ID, "⚙️ Worker Started: Preparing...")
    msg_id = status_msg.id
    
    try:
        video_path = await app.download_media(VIDEO_ID, file_name="video.mp4", progress=progress_bar, progress_args=(msg_id, "📥 Downloading Video..."))
        output = RENAME if RENAME != "none" else "output.mp4"
        cmd = []

        if TASK_TYPE == "hsub":
            sub_path = await app.download_media(SUB_ID, progress=progress_bar, progress_args=(msg_id, "📥 Downloading Subtitle..."))
            abs_sub = os.path.abspath(sub_path).replace('\\', '/')
            
            if WM_ID != "none":
                wm_path = await app.download_media(WM_ID, file_name="wm.png", progress=progress_bar, progress_args=(msg_id, "📥 Downloading Watermark..."))
                overlay_pos = "20:20" if WM_POS == "TL" else "W-w-20:20"
                cmd = ["ffmpeg", "-y", "-i", video_path, "-i", wm_path, "-filter_complex", f"[0:v]subtitles='{abs_sub}':charenc=UTF-8[sub];[1:v]scale=200:-1[wm];[sub][wm]overlay={overlay_pos}"]
            else:
                cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"subtitles='{abs_sub}':charenc=UTF-8"]
            
            cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-tune", "fastdecode", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", output])
            
        elif TASK_TYPE == "resize":
            cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"scale=-2:{RESO}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", output]

        # 🔥 PING SYSTEM: Telegram ko zinda rakhne ke liye 🔥
        async def keep_alive():
            dots = 1
            while True:
                await asyncio.sleep(60) # Har 1 minute me ping karega
                try:
                    await app.edit_message_text(CHAT_ID, msg_id, f"🔥 Encoding in progress. Please wait {'.' * dots}")
                    dots = (dots % 3) + 1
                except:
                    pass

        # Background me ping shuru karo aur FFmpeg chalao
        ping_task = asyncio.create_task(keep_alive())
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        ping_task.cancel() # Encode khatam, ping band karo

        # 🔥 UPLOAD WITHOUT PROGRESS BAR 🔥
        if process.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 0:
            await app.edit_message_text(CHAT_ID, msg_id, "📤 Encoding Done! Uploading file...\n*(Progress tracking disabled to guarantee smooth upload without freeze)*")
            
            # Chup-chaap file bhejega, no freezing!
            await app.send_document(CHAT_ID, document=output, caption=f"✅ Completed: {output}")
            await app.delete_messages(CHAT_ID, msg_id)
        else:
            await app.edit_message_text(CHAT_ID, msg_id, f"❌ **FFmpeg Error:**\n`{stderr.decode()[-800:]}`")

    except Exception as e:
        await app.edit_message_text(CHAT_ID, msg_id, f"❌ **Script Error:**\n`{str(e)}`")

    finally:
        await app.stop()

asyncio.run(main())
