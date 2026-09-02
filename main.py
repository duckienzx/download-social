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

# --- 1. TIKTOK ENGINE ---
def extract_tiktok_direct(url: str):
    try:
        res = requests.post("https://www.tikwm.com/api/", data={"url": url}, timeout=12).json()
        if res.get("code") == 0:
            d = res.get("data", {})
            formats = []
            if d.get("hdplay"):
                formats.append({"quality": "HD (Gốc)", "url": d.get("hdplay"), "ext": "mp4"})
            if d.get("play"):
                formats.append({"quality": "SD (Tiêu chuẩn)", "url": d.get("play"), "ext": "mp4"})

            return {
                "status": "success",
                "title": d.get("title", "TikTok Media"),
                "thumbnail": d.get("cover"),
                "duration": d.get("duration"),
                "platform": "TikTok",
                "video_formats": formats,
                "audio_url": d.get("music"),
                "photos": d.get("images", [])
            }
    except Exception:
        pass
    return None

# --- 2. INSTAGRAM ENGINE ---
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

            formats = [{"quality": "HD Gốc", "url": video_url, "ext": "mp4"}] if video_url else []

            if video_url or photos:
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": photos[0] if photos else None,
                    "platform": "Instagram",
                    "video_formats": formats,
                    "audio_url": None,
                    "photos": photos
                }
    except Exception:
        pass
    return None

# --- 3. FACEBOOK ENGINE ---
def extract_facebook_media(url: str):
    clean_fb = url.replace("www.facebook.com", "mbasic.facebook.com").replace("web.facebook.com", "mbasic.facebook.com")
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(clean_fb, headers=headers, timeout=12, allow_redirects=True)
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
                    "platform": "Facebook",
                    "video_formats": [{"quality": "Chất lượng cao (MP4)", "url": og_video["content"], "ext": "mp4"}],
                    "audio_url": None,
                    "photos": []
                }

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content") and "static.xx.fbcdn.net" not in og_image["content"]:
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": og_image["content"],
                    "platform": "Facebook",
                    "video_formats": [],
                    "audio_url": None,
                    "photos": [og_image["content"]]
                }
    except Exception:
        pass
    return None

# --- 4. YOUTUBE & ENGINE KHÁC (Bóc tách độ phân giải) ---
def extract_ytdlp_engine(url: str):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        
        # Lọc Audio
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and (f.get('vcodec') == 'none' or 'audio' in f.get('format', '').lower())]
        audio_url = audio_formats[-1].get('url') if audio_formats else None

        # Lọc Video theo độ phân giải (1080p, 720p, 480p, 360p...)
        seen_res = set()
        video_list = []
        for f in reversed(formats):
            height = f.get('height')
            v_url = f.get('url')
            if height and v_url and height not in seen_res and f.get('vcodec') != 'none':
                seen_res.add(height)
                video_list.append({
                    "quality": f"{height}p",
                    "url": v_url,
                    "ext": f.get('ext', 'mp4')
                })

        # Sắp xếp độ phân giải từ cao xuống thấp
        video_list.sort(key=lambda x: int(re.sub(r'\D', '', x['quality']) or 0), reverse=True)

        return {
            "status": "success",
            "title": info.get('title', 'Unknown Media'),
            "thumbnail": info.get('thumbnail'),
            "duration": info.get('duration'),
            "platform": info.get('extractor_key', 'Unknown'),
            "video_formats": video_list[:5], # Giữ lại tối đa 5 mức chất lượng tốt nhất
            "audio_url": audio_url,
            "photos": []
        }

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/extract")
async def extract_media(raw_request: Request):
    try:
        body_bytes = await raw_request.body()
        body_str = re.sub(r'[\x00-\x1F\x7F]', ' ', body_bytes.decode("utf-8", errors="ignore"))
        payload = json.loads(body_str)
        target_url = clean_url(payload.get("url", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Dữ liệu gửi lên không đúng chuẩn JSON")

    if not target_url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp link cần tải")

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
