import os
import asyncio
from pyrogram import Client

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

TASK_TYPE = os.environ.get("TASK_TYPE")
VIDEO_ID = os.environ.get("VIDEO_ID")
SUB_ID = os.environ.get("SUB_ID")
WM_ID = os.environ.get("WM_ID")
WM_POS = os.environ.get("WM_POS")
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TARGET_RES = os.environ.get("TARGET_RES")
RENAME_TEXT = os.environ.get("RENAME_TEXT", "output.mp4")

app = Client("Worker", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def encode():
    await app.start()
    status = await app.send_message(CHAT_ID, "⚙️ GitHub Server: Task Started!\n📥 Downloading video...")
    
    vid_path = await app.download_media(VIDEO_ID, file_name="video.mp4")
    out_path = f"out_{RENAME_TEXT}"
    
    if TASK_TYPE == "resize":
        await status.edit(f"🔄 Resizing to {TARGET_RES}p (Ultrafast, CRF 34)...")
        scale_filter = f"scale=-2:{TARGET_RES}"
        cmd = [
            "ffmpeg", "-y", "-i", vid_path, "-vf", scale_filter,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", out_path
        ]
        
    elif TASK_TYPE == "hsub":
        await status.edit("📥 Downloading Subtitle...")
        sub_path = await app.download_media(SUB_ID, file_name="sub.srt")
        abs_sub = os.path.abspath(sub_path).replace('\\', '/')
        sub_filter = f"subtitles='{abs_sub}':charenc=UTF-8"
        
        if WM_ID:
            await status.edit("📥 Downloading Watermark...")
            wm_path = await app.download_media(WM_ID, file_name="wm.jpg")
            overlay_pos = "20:20" if WM_POS == "TL" else "W-w-20:20"
            filter_complex = f"[0:v]{sub_filter}[sub];[1:v]scale=200:-1[wm];[sub][wm]overlay={overlay_pos}"
            
            await status.edit("🔥 Hardsubbing with Watermark (Ultrafast, CRF 34)...")
            cmd = [
                "ffmpeg", "-y", "-i", vid_path, "-i", wm_path, "-filter_complex", filter_complex,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-tune", "fastdecode",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", out_path
            ]
        else:
            await status.edit("🔥 Hardsubbing without Watermark (Ultrafast, CRF 34)...")
            cmd = [
                "ffmpeg", "-y", "-i", vid_path, "-vf", sub_filter,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-tune", "fastdecode",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", out_path
            ]
    
    # Run FFmpeg
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.wait()
    
    if os.path.exists(out_path):
        await status.edit("📤 Encoding Done! Uploading to Telegram...")
        await app.send_document(CHAT_ID, document=out_path, caption=RENAME_TEXT)
        await status.delete()
    else:
        await status.edit("❌ Encoding failed on GitHub Server.")

    await app.stop()

if __name__ == "__main__":
    asyncio.run(encode())
