import os
import asyncio
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
    
    print(f"📥 Downloading Video...")
    video = await app.download_media(VIDEO_ID, file_name="video.mp4")
    output = "output.mp4"
    
    cmd = ["ffmpeg", "-y", "-i", video]

    if TASK_TYPE == "hsub":
        print(f"📥 Downloading Subtitle...")
        sub_ext = ".ass" if "ass" in SUB_ID else ".srt"
        subtitle = await app.download_media(SUB_ID, file_name=f"sub{sub_ext}")
        
        # Hardsub filter + CRF 28 + Ultrafast + AAC Audio
        cmd.extend([
            "-vf", f"subtitles=sub{sub_ext}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "96k", output
        ])
        
    elif TASK_TYPE == "resize":
        # Resize filter
        cmd.extend([
            "-vf", f"scale=-2:{RESO}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "96k", output
        ])

    print("🔥 Starting FFmpeg...")
    process = await asyncio.create_subprocess_exec(*cmd)
    await process.wait()

    if os.path.exists(output) and os.path.getsize(output) > 0:
        print("📤 Uploading Result to Telegram...")
        caption = "✅ Hardsubbed" if TASK_TYPE == "hsub" else f"✅ Resized to {RESO}p"
        await app.send_document(CHAT_ID, document=output, caption=caption)
    else:
        print("❌ Encoding Failed!")

    await app.stop()

asyncio.run(main())
