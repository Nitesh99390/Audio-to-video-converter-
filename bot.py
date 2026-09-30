import os
import asyncio
import logging
import time
from pyrogram import Client, filters
from pyrogram.types import Message

# Logging setup (Kaggle console me status/errors dekhne ke liye)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Kaggle Environment Variables se credentials lena
# Agar value nahi milti, to bot start nahi hoga (Security ke liye best practice)
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
except TypeError:
    logger.error("Kaggle Secrets (Env variables) theek se set nahi hain!")
    exit(1)

bot = Client(
    "advance_audio_video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user_data = {}

# Progress update function (Flood errors se bachne ke liye 3 sec ka delay)
async def progress_bar(current, total, status_msg, action_text, start_time):
    now = time.time()
    if (now - start_time) > 3 or current == total:
        try:
            percent = round((current / total) * 100, 1)
            await status_msg.edit_text(f"{action_text}\nProgress: {percent}%")
        except Exception:
            pass # Ignore temporary flood errors

@bot.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    user_data[message.chat.id] = {}
    await message.reply_text(
        "🚀 **Video Maker Bot** me aapka swagat hai!\n\n"
        "🎬 Video banane ke liye:\n"
        "1️⃣ Pehle koi **Photo** bhejo.\n"
        "2️⃣ Uske baad ek **Audio** file bhejo."
    )

@bot.on_message(filters.photo)
async def photo_handler(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    status = await message.reply_text("📥 Photo download ho rahi hai...")
    start_time = time.time()
    
    try:
        photo_path = await message.download(
            file_name=f"downloads/photo_{chat_id}.jpg",
            progress=progress_bar,
            progress_args=(status, "📥 Photo downloading...", start_time)
        )
        user_data[chat_id]["photo"] = photo_path
        
        if "audio" in user_data[chat_id]:
            await status.edit_text("✅ Photo mil gayi! Processing shuru ho rahi hai...")
            await process_video(client, chat_id, message)
        else:
            await status.edit_text("✅ Photo save ho gayi! Ab apna **Audio** bhejo.")
    except Exception as e:
        logger.error(f"Photo download error: {e}")
        await status.edit_text("❌ Photo download karne me error aaya.")

@bot.on_message(filters.audio | filters.voice | filters.document)
async def audio_handler(client, message: Message):
    chat_id = message.chat.id
    
    # Document verify karein ki wo audio hai ya nahi
    if message.document and not message.document.mime_type.startswith("audio/"):
        return
        
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    status = await message.reply_text("📥 Audio download ho raha hai...")
    start_time = time.time()
    
    try:
        audio_path = await message.download(
            file_name=f"downloads/audio_{chat_id}.mp3",
            progress=progress_bar,
            progress_args=(status, "📥 Audio downloading...", start_time)
        )
        user_data[chat_id]["audio"] = audio_path
        
        if "photo" in user_data[chat_id]:
            await status.edit_text("✅ Audio mil gaya! Processing shuru ho rahi hai...")
            await process_video(client, chat_id, message)
        else:
            await status.edit_text("✅ Audio save ho gaya! Ab apni **Photo** bhejo.")
    except Exception as e:
        logger.error(f"Audio download error: {e}")
        await status.edit_text("❌ Audio download karne me error aaya.")

async def process_video(client, chat_id, message):
    photo = user_data[chat_id].get("photo")
    audio = user_data[chat_id].get("audio")
    output_video = f"downloads/video_{chat_id}.mp4"
    
    status_msg = await message.reply_text("⚙️ **Video Rendering...**\nIsme thoda waqt lag sakta hai, kripya intezar karein.")
    
    try:
        # Optimized FFmpeg command for Kaggle CPU
        cmd = (
            f'ffmpeg -y -loop 1 -framerate 1 -i "{photo}" -i "{audio}" '
            f'-c:v libx264 -tune stillimage -c:a aac -b:a 192k -pix_fmt yuv420p '
            f'-shortest -preset fast "{output_video}"'
        )
        
        logger.info(f"Running FFmpeg for chat {chat_id}")
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0 and os.path.exists(output_video):
            await status_msg.edit_text("📤 Video ban gaya! Upload ho raha hai...")
            start_time = time.time()
            
            await client.send_video(
                chat_id=chat_id,
                video=output_video,
                caption="🎬 Ye raha aapka video!",
                progress=progress_bar,
                progress_args=(status_msg, "📤 Uploading Video...", start_time)
            )
            await status_msg.delete()
        else:
            logger.error(f"FFmpeg Error: {stderr.decode()}")
            await status_msg.edit_text("❌ Video banane mein internal error aaya.")
            
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await status_msg.edit_text("❌ Server par kuch galat ho gaya.")
        
    finally:
        # Hamesha cache delete karein taaki Kaggle disk full na ho
        for f in [photo, audio, output_video]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        user_data[chat_id] = {}

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    logger.info("Bot is starting...")
    bot.run()
