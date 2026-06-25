import os
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import yt_dlp
from telegram import Bot
import tempfile
import logging

app = FastAPI()
logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
    logging.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID not set. Uploads will fail.")

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

# In-memory cache to map youtube_id -> telegram file_id
cache = {}

class SearchResult(BaseModel):
    id: str
    title: str
    artist: str
    thumbnail: str

class StreamResult(BaseModel):
    title: str
    artist: str
    thumbnail: str
    file_id: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/search")
def search(q: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'extract_flat': True,
        'default_search': 'ytsearch10',
        'quiet': True,
        'extractor_args': {'youtube': {'player-client': ['web_embedded', 'web', 'tv']}}
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch10:{q}", download=False)
            results = []
            if 'entries' in info:
                for entry in info['entries']:
                    results.append(SearchResult(
                        id=entry.get('id'),
                        title=entry.get('title', 'Unknown Title'),
                        artist=entry.get('uploader', 'Unknown Artist'),
                        thumbnail=entry.get('thumbnails', [{'url': ''}])[0].get('url', '') if entry.get('thumbnails') else ''
                    ))
            return results
        except Exception as e:
            logging.error(f"Search error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

async def download_and_upload(yt_id: str, title: str):
    url = f"https://www.youtube.com/watch?v={yt_id}"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        filename = os.path.join(tmpdir, f"{yt_id}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio',
            'outtmpl': filename,
            'quiet': True,
            'extractor_args': {'youtube': {'player-client': ['web_embedded', 'web', 'tv']}}
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            import asyncio
            await asyncio.to_thread(ydl.download, [url])
        
        downloaded_files = os.listdir(tmpdir)
        if not downloaded_files:
            raise Exception("No audio file downloaded by yt-dlp")
        
        final_filename = os.path.join(tmpdir, downloaded_files[0])
        
        # Upload to Telegram
        if bot and TELEGRAM_CHANNEL_ID:
            with open(final_filename, 'rb') as audio_file:
                message = await bot.send_audio(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    audio=audio_file,
                    title=title,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )
                file_id = message.audio.file_id
                cache[yt_id] = file_id
                return file_id
        else:
            return "dummy_file_id_no_telegram_token"

@app.get("/stream", response_model=StreamResult)
async def stream(id: str):
    # If cached, just return file_id
    # Otherwise we need metadata first
    url = f"https://www.youtube.com/watch?v={id}"
    ydl_opts = {
        'quiet': True, 
        'noplaylist': True,
        'extractor_args': {'youtube': {'player-client': ['web_embedded', 'web', 'tv']}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown Title')
            artist = info.get('uploader', 'Unknown Artist')
            thumbnail = info.get('thumbnails', [{'url': ''}])[0].get('url', '') if info.get('thumbnails') else ''
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch metadata: {str(e)}")
        
    if id in cache:
        file_id = cache[id]
    else:
        try:
            file_id = await download_and_upload(id, title)
        except Exception as e:
            logging.error(f"Download/Upload error: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to process audio: {str(e)}")
            
    return StreamResult(
        title=title,
        artist=artist,
        thumbnail=thumbnail,
        file_id=file_id
    )
