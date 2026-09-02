from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import yt_dlp
import requests
from bs4 import BeautifulSoup
import json
import re

app = FastAPI(title="Universal Downloader")
templates = Jinja2Templates(directory="templates")

def clean_url(url: str) -> str:
    url = url.strip()
    if "youtube.com/watch" in url:
        m = re.search(r"v=([a-zA-Z0-9_-]+)", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    elif "tiktok.com" in url or "instagram.com" in url:
        return url.split("?")[0]
    return url

# --- 1. ENGINE TIKTOK ---
def extract_tiktok_direct(url: str):
    try:
        res = requests.post("https://www.tikwm.com/api/", data={"url": url}, timeout=12).json()
        if res.get("code") == 0:
            d = res.get("data", {})
            return {
                "status": "success",
                "title": d.get("title", "TikTok Media"),
                "thumbnail": d.get("cover"),
                "platform": "TikTok",
                "video_url": d.get("play"),
                "audio_url": d.get("music"),
                "photos": d.get("images", [])
            }
    except Exception:
        pass
    return None

# --- 2. ENGINE INSTAGRAM ---
def extract_instagram_media(url: str):
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = "Instagram Media"
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]

            video_url = None
            og_video = soup.find("meta", property="og:video") or soup.find("meta", property="og:video:secure_url")
            if og_video and og_video.get("content"):
                video_url = og_video["content"]

            photos = []
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                photos.append(og_image["content"])

            if video_url or photos:
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": photos[0] if photos else None,
                    "platform": "Instagram",
                    "video_url": video_url,
                    "audio_url": None,
                    "photos": photos
                }
    except Exception:
        pass
    return None

# --- 3. ENGINE FACEBOOK ---
def extract_facebook_media(url: str):
    clean_fb_url = url.replace("www.facebook.com", "mbasic.facebook.com")
    clean_fb_url = clean_fb_url.replace("web.facebook.com", "mbasic.facebook.com")
    clean_fb_url = clean_fb_url.replace("m.facebook.com", "mbasic.facebook.com")

    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        resp = requests.get(clean_fb_url, headers=headers, timeout=12, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = "Facebook Media"
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]

            og_video = soup.find("meta", property="og:video") or soup.find("meta", property="og:video:secure_url")
            if og_video and og_video.get("content"):
                thumb = soup.find("meta", property="og:image")
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": thumb["content"] if thumb else None,
                    "platform": "Facebook (Video)",
                    "video_url": og_video["content"],
                    "audio_url": None,
                    "photos": []
                }

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                img_url = og_image["content"]
                if "static.xx.fbcdn.net" not in img_url:
                    return {
                        "status": "success",
                        "title": title,
                        "thumbnail": img_url,
                        "platform": "Facebook (Photo)",
                        "video_url": None,
                        "audio_url": None,
                        "photos": [img_url]
                    }
    except Exception:
        pass
    return None

# --- 4. ENGINE TỔNG QUAN (YT-DLP) ---
def extract_ytdlp_engine(url: str):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and (f.get('vcodec') == 'none' or 'audio only' in f.get('format', '').lower())]
        audio_url = audio_formats[-1].get('url') if audio_formats else None

        video_url = info.get('url')
        if not video_url and formats:
            combined = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            video_url = combined[-1].get('url') if combined else formats[-1].get('url')

        photos = []
        if 'entries' in info:
            for item in info['entries']:
                if item.get('url'):
                    photos.append(item.get('url'))

        return {
            "status": "success",
            "title": info.get('title', 'Unknown Media'),
            "thumbnail": info.get('thumbnail'),
            "platform": info.get('extractor_key'),
            "video_url": video_url,
            "audio_url": audio_url,
            "photos": photos
        }

# --- ROUTE HIỂN THỊ FILE HTML ---
@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- API BÓC TÁCH LINK ---
@app.post("/api/extract")
async def extract_media(raw_request: Request):
    try:
        body_bytes = await raw_request.body()
        body_str = body_bytes.decode("utf-8", errors="ignore")
        body_str = re.sub(r'[\x00-\x1F\x7F]', ' ', body_str)
        payload = json.loads(body_str)
        target_url = payload.get("url", "")
    except Exception:
        raise HTTPException(status_code=400, detail="Định dạng JSON gửi lên không hợp lệ")

    target_url = clean_url(target_url)
    if not target_url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp URL")
    
    if "tiktok.com" in target_url:
        res = extract_tiktok_direct(target_url)
        if res: return res

    if "instagram.com" in target_url:
        res = extract_instagram_media(target_url)
        if res: return res

    if any(fb in target_url for fb in ["facebook.com", "fb.watch", "fb.com"]):
        res = extract_facebook_media(target_url)
        if res: return res

    try:
        return extract_ytdlp_engine(target_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi trích xuất: {str(e)}")
