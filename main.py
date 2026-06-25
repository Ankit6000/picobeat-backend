import os
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import yt_dlp
from telegram import Bot
import tempfile
import logging
import urllib.request
import urllib.parse
import json

app = FastAPI()
logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
    logging.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID not set. Uploads will fail.")

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

# In-memory cache to map jiosaavn_id -> telegram file_id
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

@app.get("/debug")
def debug():
    import subprocess
    try:
        node_ver = subprocess.check_output(["node", "-v"], stderr=subprocess.STDOUT).decode().strip()
    except Exception as e:
        node_ver = f"Error: {e}"
    return {"node": node_ver}

@app.get("/search")
def search(q: str):
    try:
        req = urllib.request.Request(
            f'https://www.jiosaavn.com/api.php?__call=autocomplete.get&query={urllib.parse.quote(q)}&_format=json&_marker=0&ctx=android',
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        res = json.loads(urllib.request.urlopen(req).read().decode())
        results = []
        if 'songs' in res and 'data' in res['songs']:
            for entry in res['songs']['data']:
                song_url = entry.get('url', '')
                song_id = song_url.split('/')[-1] if '/' in song_url else song_url
                artist = 'Unknown Artist'
                if 'more_info' in entry and 'primary_artists' in entry['more_info']:
                    artist = entry['more_info']['primary_artists']
                elif 'description' in entry:
                    artist = entry['description'].split(' · ')[0].strip() if ' · ' in entry['description'] else entry['description']
                
                results.append(SearchResult(
                    id=song_id,
                    title=entry.get('title', 'Unknown Title'),
                    artist=artist,
                    thumbnail=entry.get('image', '').replace('50x50', '500x500')
                ))
        return results
    except Exception as e:
        logging.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def download_and_upload(song_id: str, title: str):
    url = f"https://www.jiosaavn.com/song/track/{song_id}"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        filename = os.path.join(tmpdir, f"{song_id}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': filename,
            'quiet': True
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
                cache[song_id] = file_id
                return file_id
        else:
            return "dummy_file_id_no_telegram_token"

@app.get("/stream", response_model=StreamResult)
async def stream(id: str):
    # If cached, just return file_id
    url = f"https://www.jiosaavn.com/song/track/{id}"
    ydl_opts = {
        'quiet': True,
        'format': 'bestaudio'
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown Title')
            artist = info.get('artist', 'Unknown Artist')
            thumbnail = info.get('thumbnail', '')
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
