import feedparser
import os
import asyncio
import edge_tts
import re
import glob
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from pydub import AudioSegment
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
try:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
except:
    pass

HKT = timezone(timedelta(hours=8))

# VOICES
# SOLO HOST: Dekisugi (WanLung) - Calm, professional, "News Anchor" tone.
VOICE = "zh-HK-WanLungNeural"

# NEWS SOURCES
# Added: Google Trends HK (Daily) to detect "Heat"
FEED_TRENDS = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=HK"

FEEDS_HK = [
    "https://www.scmp.com/rss/2/feed",
    "https://rss.stheadline.com/rss/realtime/hk.xml",
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
]
FEEDS_GLOBAL = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.theguardian.com/world/rss"
]
WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# 2. AUDIO ENGINE (Solo Host)
# -----------------------------
async def generate_line(text, filename):
    # Standard Speed (+0%) for professional delivery
    communicate = edge_tts.Communicate(text, VOICE, rate="+0%")
    await communicate.save(filename)

async def generate_monologue_audio(script_text, output_file):
    print("Generating Monologue...")
    # Clean up the script to remove any remaining "Name:" tags just in case
    clean_text = re.sub(r'^(出木杉|Dekisugi|電車少女|Girl|Anchor):', '', script_text)
    
    # Split by periods/punctuation to create natural pauses
    # We don't split by "|" anymore since it's a monologue, but we respect sentences.
    sentences = re.split(r'(?<=[.?!。？！])', script_text)
    
    combined_audio = AudioSegment.empty()
    temp_files = []

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence: continue
        
        # Remove markdown or speaker tags if the AI slipped them in
        text = re.sub(r'^\w+:', '', sentence) 
        text = re.sub(r'[^\w\s\u4e00-\u9fff,.?!，。？！a-zA-Z]', '', text)
        if len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        try:
            print(f"Speaking: {text[:15]}...")
            await generate_line(text, temp_filename)
            
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                # Add a breath pause (300ms) between sentences
                combined_audio += AudioSegment.silent(duration=350)
                temp_files.append(temp_filename)
        except Exception as e:
            print(f"Skipping line: {e}")
            continue

    if len(temp_files) == 0: raise Exception("Audio generation failed.")
    combined_audio.export(output_file, format="mp3")
    for f in temp_files:
        try: os.remove(f)
        except: pass

def mix_music(voice_file, output_file):
    print("Mixing music...")
    if not os.path.exists("bgm.mp3"):
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)
        return

    try:
        voice = AudioSegment.from_mp3(voice_file)
        # Lower BGM volume slightly more for solo voice clarity (-24dB)
        bgm = AudioSegment.from_mp3("bgm.mp3") - 24
        looped_bgm = bgm * (len(voice) // len(bgm) + 1)
        final_bgm = looped_bgm[:len(voice) + 4000].fade_out(3000)
        final_mix = final_bgm.overlay(voice, position=500)
        final_mix.export(output_file, format="mp3")
        if os.path.exists(voice_file): os.remove(voice_file)
    except:
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)

# 3. JANITOR
# -----------------------------
def run_janitor():
    now_hk = datetime.now(HKT)
    todays = f"brief_{now_hk.strftime('%Y%m%d')}.mp3"
    for f in glob.glob("brief_*.mp3"):
        if f != todays:
            try: os.remove(f)
            except: pass
    for pat in ["temp_*.mp3", "dialogue_raw.mp3"]:
        for f in glob.glob(pat):
            try: os.remove(f)
            except: pass

# 4. ROBUST AI BRAIN
# -----------------------------
def get_weather():
    try:
        f = feedparser.parse(WEATHER_URL)
        return f.entries[0].description.replace('<br/>', ' ')[:300] if f.entries else "N/A"
    except: return "N/A"

def get_trends():
    try:
        # Fetch Google Trends RSS
        f = feedparser.parse(FEED_TRENDS)
        trends = [item.title for item in f.entries[:8]] # Top 8 trends
        return ", ".join(trends)
    except:
        return "None"

def get_feeds(urls):
    content = ""
    count = 0
    for url in urls:
        if count >= 8: break # Fetch more items to give the AI more choices to sort
        try:
            f = feedparser.parse(url)
            for item in f.entries:
                if count >= 8: break
                desc = getattr(item, 'summary', getattr(item, 'description', ''))
                desc = re.sub('<[^<]+?>', '', desc)[:150] 
                content += f"- {item.title} (Context: {desc})\n"
                count += 1
        except: pass
    return content

def generate_script_robust(prompt):
    # PHASE 1: GOOGLE GEMINI
    gemini_models = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-pro"]
    for m in gemini_models:
        try:
            print(f"🤖 Attempting Google Model: {m}...")
            model = genai.GenerativeModel(m)
            response = model.generate_content(prompt)
            text = response.text.replace("\n", " ").replace("**", "")
            return text + " 本節目由 Google Gemini 支援製作。"
        except Exception as e:
            print(f"⚠️ Google {m} failed: {e}")
            continue

    # PHASE 2: HUGGING FACE FALLBACK
    print("🚨 Switching to Hugging Face Backup...")
    try:
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token: raise Exception("No HF_TOKEN")
        client = InferenceClient(api_key=hf_token)
        messages = [{"role": "user", "content": prompt}]
        response = client.chat_completion(
            model="Qwen/Qwen2.5-72B-Instruct", 
            messages=messages, 
            max_tokens=1500
        )
        text = response.choices[0].message.content.replace("\n", " ").replace("**", "")
        return text + " 本節目由 Hugging Face Qwen 支援製作。"
    except Exception as e:
        print(f"❌ Hugging Face failed: {e}")
        return "今日系統故障，請稍後再試。"

def write_script(hk_news, global_news, weather, trends):
    prompt = f"""
    You are "出木杉" (Dekisugi), a professional, calm, and intelligent News Anchor for Hong Kong.
    
    **Your Goal:** Select and read the top 3-4 news stories. 
    **Crucial Sorting Rule:** You MUST prioritize news stories that match the following "Trending Keywords" (Social Heat):
    [{trends}]
    
    If a news story matches a trending keyword, put it FIRST and discuss it in more depth. If no news matches the trends, select the most significant political or social headlines.

    **Format:**
    - Monologue (Single speaker).
    - Authentic Hong Kong Cantonese (廣東話口語).
    - Tone: Professional, analytical, but accessible (like a prime-time news anchor).
    - No "Name:" tags needed, just write the script as a continuous flow.

    **Structure:**
    1. **Intro:** "早晨，歡迎收聽香港早晨。我是出木杉。"
    2. **Weather:** Brief update ({weather}).
    3. **Top Story (Trending/Popular):** Deep dive into the most discussed topic.
    4. **Other News:** 2-3 quick headlines.
    5. **English Corner:** Pick ONE useful English idiom related to the top story. Explain it clearly in Cantonese.
    6. **Outro:** "多謝收聽，聽朝見。"

    **Source Data:**
    HK News: {hk_news}
    Global News: {global_news}
    """
    return generate_script_robust(prompt)

def update_rss(audio_file, script):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    p = Podcast(
        name="香港早晨",
        description="HK News Analysis (Powered by AI).",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Dekisugi", "news@ex.com")],
        owner=Person("Dekisugi", "news@ex.com"),
        category=Category("News"),
    )
    
    now = datetime.now(HKT)
    p.add_episode(Episode(
        title=f"晨早新聞: {now.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_file}", 9000000, type="audio/mpeg"),
        summary=script[:500],
        publication_date=now,
    ))
    p.rss_file('feed.xml')

# 5. MAIN
# -----------------------------
if __name__ == "__main__":
    run_janitor()
    
    now_str = datetime.now(HKT).strftime('%Y%m%d')
    final_mp3 = f"brief_{now_str}.mp3"
    
    print("Fetching news & trends...")
    hk = get_feeds(FEEDS_HK)
    gl = get_feeds(FEEDS_GLOBAL)
    we = get_weather()
    tr = get_trends()
    
    print(f"Top Trends today: {tr}")
    
    print("Generating monologue script...")
    script = write_script(hk, gl, we, tr)
    
    try:
        asyncio.run(generate_monologue_audio(script, "dialogue_raw.mp3"))
        mix_music("dialogue_raw.mp3", final_mp3)
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        exit(1)
