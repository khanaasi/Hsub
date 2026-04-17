import os
import time
import asyncio
import pyrogram.utils

# Pyrogram long ID bug fix
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

app = Client("encoder", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

last_edit_time = 0

async def progress_bar(current, total, status_msg, action_text):
    global last_edit_time
    now = time.time()
    if now - last_edit_time > 5 or current == total:
        try:
            percent = (current / total) * 100
            curr_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            await status_msg.edit(f"⚙️ Worker: {action_text}\n⏳ `{percent:.1f}%` ({curr_mb:.1f}MB / {tot_mb:.1f}MB)")
            last_edit_time = now
        except:
            pass

async def main():
    await app.start()
    status_msg = await app.send_message(CHAT_ID, "⚙️ Worker Started: Preparing...")
    
    try:
        video_path = await app.download_media(VIDEO_ID, progress=progress_bar, progress_args=(status_msg, "📥 Downloading Video..."))
        output = RENAME if RENAME != "none" else "output.mp4"
        
        cmd = []

        if TASK_TYPE == "hsub":
            sub_path = await app.download_media(SUB_ID, progress=progress_bar, progress_args=(status_msg, "📥 Downloading Subtitle..."))
            abs_sub = os.path.abspath(sub_path).replace('\\', '/')
            
            if WM_ID != "none":
                wm_path = await app.download_media(WM_ID, progress=progress_bar, progress_args=(status_msg, "📥 Downloading Watermark..."))
                overlay_pos = "20:20" if WM_POS == "TL" else "W-w-20:20"
                filter_complex = f"[0:v]subtitles='{abs_sub}':charenc=UTF-8[sub];[1:v]scale=200:-1[wm];[sub][wm]overlay={overlay_pos}"
                cmd = ["ffmpeg", "-y", "-i", video_path, "-i", wm_path, "-filter_complex", filter_complex]
            else:
                cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"subtitles='{abs_sub}':charenc=UTF-8"]
            
            cmd.extend([
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-tune", "fastdecode",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", output
            ])
            
        elif TASK_TYPE == "resize":
            await status_msg.edit(f"⚙️ Worker: Applying {RESO}p Resize...")
            cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"scale=-2:{RESO}"]
            cmd.extend([
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", output
            ])

        await status_msg.edit("🔥 Worker: Encoding & Compressing... (Please wait)")
        
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 0:
            await status_msg.edit("📤 Worker: Network Secure, Starting Upload...")
            await asyncio.sleep(2)
            caption = f"✅ Completed: {output}"
            
            await app.send_document(
                CHAT_ID, 
                document=output, 
                caption=caption,
                progress=progress_bar,
                progress_args=(status_msg, "📤 Uploading Video...")
            )
            await status_msg.delete()
        else:
            error_text = stderr.decode()[-800:]  
            await status_msg.edit(f"❌ **FFmpeg Error:**\n`{error_text}`")

    except Exception as e:
        await status_msg.edit(f"❌ **Script Error:**\n`{str(e)}`")

    finally:
        await app.stop()

asyncio.run(main())
