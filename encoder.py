import os
import time
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

# Pyrogram client ko thoda stable banaya
app = Client("encoder", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, max_concurrent_transmissions=3)

# Progress Bar Tracker
last_edit_time = 0

async def progress_bar(current, total, status_msg, action_text):
    global last_edit_time
    now = time.time()
    
    # Har 5 second me Telegram message update karo
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
        # Download Video
        video_path = await app.download_media(
            VIDEO_ID, 
            progress=progress_bar, 
            progress_args=(status_msg, "📥 Downloading Video...")
        )
        output = "output.mp4"
        
        cmd = ["ffmpeg", "-y", "-i", video_path]

        if TASK_TYPE == "hsub":
            sub_path = await app.download_media(
                SUB_ID, 
                progress=progress_bar, 
                progress_args=(status_msg, "📥 Downloading Subtitle...")
            )
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

        await status_msg.edit("🔥 Worker: Encoding Started... (Please wait)")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()

        # Encoding successful ya nahi?
        if process.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 0:
            caption = "✅ Hardsubbed by GitHub" if TASK_TYPE == "hsub" else f"✅ Resized to {RESO}p by GitHub"
            
            await status_msg.edit("📤 Worker: Starting Upload...")
            print("Upload process started...")

            try:
                # Direct file path bhej rahe hain taaki issue na aaye
                await app.send_document(
                    chat_id=CHAT_ID, 
                    document=output, 
                    caption=caption,
                    progress=progress_bar,
                    progress_args=(status_msg, "📤 Uploading Video...")
                )
                await status_msg.delete()
                print("Upload Success!")
            except Exception as upload_err:
                await status_msg.edit(f"❌ **Upload Failed:**\n`{str(upload_err)}`")

        else:
            error_text = stderr.decode()[-800:]  
            await status_msg.edit(f"❌ **FFmpeg Error:**\n`{error_text}`")

    except Exception as e:
        await status_msg.edit(f"❌ **Script Error:**\n`{str(e)}`")

    finally:
        await app.stop()

asyncio.run(main())
