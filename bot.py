import os
import asyncio
import logging
import time
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Kaggle Secrets Check
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
except TypeError:
    logger.error("Kaggle Secrets (Env variables) set nahi hain!")
    exit(1)

bot = Client(
    "superfast_audio_video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user_data = {}

# Advanced Progress Bar (Telegram flood limit se bachne ke liye)
async def progress_bar(current, total, status_msg, action_text, start_time):
    now = time.time()
    if (now - start_time) > 3 or current == total:
        try:
            percent = round((current / total) * 100, 1)
            await status_msg.edit_text(f"⏳ **{action_text}**\n🔄 Progress: {percent}%")
        except Exception:
            pass 

@bot.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    user_data[message.chat.id] = {}
    await message.reply_text(
        "🚀 **Superfast Video Maker Bot** me aapka swagat hai!\n\n"
        "⚡️ Yeh bot bina quality loss ke seconds me video banata hai.\n\n"
        "🛠 **Process:**\n"
        "1️⃣ Pehle ek **Photo** bhejo.\n"
        "2️⃣ Phir apna **Audio** file bhejo."
    )

@bot.on_message(filters.photo)
async def photo_handler(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    status = await message.reply_text("📥 Photo download ho rahi hai...")
    start_time = time.time()
    
    # Har photo ke liye unique ID taaki files mix na hon
    task_id = str(uuid.uuid4())[:8]
    file_path = f"downloads/photo_{chat_id}_{task_id}.jpg"
    
    try:
        photo_path = await message.download(
            file_name=file_path,
            progress=progress_bar,
            progress_args=(status, "Photo Downloading...", start_time)
        )
        user_data[chat_id]["photo"] = photo_path
        
        if "audio" in user_data[chat_id]:
            await status.edit_text("✅ Photo mil gayi! Superfast Processing shuru...")
            await process_video(client, chat_id, message)
        else:
            await status.edit_text("✅ Photo save ho gayi! 🎵 Ab apna **Audio** bhejo.")
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await status.edit_text("❌ Photo download me error aaya.")

@bot.on_message(filters.audio | filters.voice | filters.document)
async def audio_handler(client, message: Message):
    chat_id = message.chat.id
    
    if message.document and not message.document.mime_type.startswith("audio/"):
        await message.reply_text("⚠️ Kripya sirf Audio file bhejein.")
        return
        
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    status = await message.reply_text("📥 Audio download ho raha hai...")
    start_time = time.time()
    
    # Smart Audio Extension Extractor
    ext = ".mp3"
    if message.audio and message.audio.file_name:
        ext = os.path.splitext(message.audio.file_name)[1]
        
    task_id = str(uuid.uuid4())[:8]
    file_path = f"downloads/audio_{chat_id}_{task_id}{ext}"
    
    try:
        audio_path = await message.download(
            file_name=file_path,
            progress=progress_bar,
            progress_args=(status, "Audio Downloading...", start_time)
        )
        user_data[chat_id]["audio"] = audio_path
        
        if "photo" in user_data[chat_id]:
            await status.edit_text("✅ Audio mil gaya! Superfast Processing shuru...")
            await process_video(client, chat_id, message)
        else:
            await status.edit_text("✅ Audio save ho gaya! 🖼 Ab apni **Photo** bhejo.")
    except Exception as e:
        logger.error(f"Audio error: {e}")
        await status.edit_text("❌ Audio download me error aaya.")

async def process_video(client, chat_id, message):
    photo = user_data[chat_id].get("photo")
    audio = user_data[chat_id].get("audio")
    
    task_id = str(uuid.uuid4())[:8]
    output_video = f"downloads/video_{chat_id}_{task_id}.mp4"
    
    status_msg = await message.reply_text("⚡️ **Superfast Rendering...**\nIsme lagbhag 5-10 seconds lagenge!")
    
    try:
        # Ultra Fast FFmpeg command with Direct Copy
        cmd = (
            f'ffmpeg -y -loop 1 -framerate 1 -i "{photo}" -i "{audio}" '
            f'-c:v libx264 -tune stillimage -preset ultrafast -c:a copy '
            f'-shortest "{output_video}"'
        )
        
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0 and os.path.exists(output_video):
            await status_msg.edit_text("📤 Video seconds me ban gaya! Ab Upload ho raha hai...")
            start_time = time.time()
            
            await client.send_video(
                chat_id=chat_id,
                video=output_video,
                caption="🎬 Ye raha aapka Superfast Video!",
                progress=progress_bar,
                progress_args=(status_msg, "Uploading Video...", start_time)
            )
            await status_msg.delete()
        else:
            logger.error(f"FFmpeg Error: {stderr.decode()}")
            await status_msg.edit_text("❌ Video nahi ban paya. Audio format copy ko support nahi kar raha hoga.")
            
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await status_msg.edit_text("❌ Server error.")
        
    finally:
        # Storage clean karna
        for f in [photo, audio, output_video]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        user_data[chat_id] = {}

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    logger.info("⚡️ Superfast Bot is starting...")
    bot.run()
