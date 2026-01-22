import feedparser
import os
import asyncio
import edge_tts
import re
import glob
import requests
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

# VOICE: WanLung (Professional yet conversational)
VOICE = "zh-HK-WanLungNeural"

# NEWS SOURCES
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

# DEFAULT BGM (Royalty Free News Lo-Fi)
DEFAULT_BGM_URL = "https://github.com/hubchangit/daily-news-brief/raw/main/bgm.mp3" 
# ^ Note: If this 404s, the script tries to run without music. 
# Ideally, you should upload your own 'bgm.mp3' to your repo. 
# For now, I'll add a check to download a placeholder if missing.

# 2. AUDIO ENGINE (Natural Flow)
# -----------------------------
async def generate_line(text, filename):
    # Rate +0% is standard.
    # We rely on the script writing ("口語") to provide the casual feel.
    communicate = edge_tts.Communicate(text, VOICE, rate="+0%")
    await communicate.save(filename)

async def generate_monologue_audio(script_text, output_file):
    print("Generating Monologue...")
    
    # 1. Pre-processing: Remove AI artifacts
    clean_text = re.sub(r'\*+', '', script_text) # Remove bold stars
    clean_text = re.sub(r'\(.*?\)', '', clean_text) # Remove instructions in brackets
    
    # 2. Smart Splitting for Natural Pauses
    # Split by Full Stops (。) or Question Marks (？) or Exclamation (！)
    # We treat Commas (，) as part of the sentence flow, handled by TTS engine naturally.
    sentences = re.split(r'(?<=[。？！.?!])', clean_text)
    
    combined_audio = AudioSegment.empty()
    temp_files = []

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence: continue
        
        # Filter out "Speaker Name" tags if they exist
        text = re.sub(r'^.*?[:：]', '', sentence).strip()
        if len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        try:
            print(f"Speaking: {text[:15]}...")
            await generate_line(text, temp_filename)
            
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                
                # Dynamic Pause:
                # If the sentence was very short (< 2 sec), shorter pause.
                # If long, standard pause.
                pause_duration = 450 if len(segment) > 2000 else 300
                combined_audio += AudioSegment.silent(duration=pause_duration)
                
                temp_files.append(temp_filename)
        except Exception as e:
            print(f"Skipping line: {e}")
            continue

    if len(temp_files) == 0: raise Exception("Audio generation failed.")
    combined_audio.export(output_file, format="mp3")
    
    # Cleanup
    for f in temp_files:
        try: os.remove(f)
        except: pass

def ensure_bgm():
    # Helper to make sure we have music
    if os.path.exists("bgm.mp3"):
        return True
    
    print("bgm.mp3 not found. Downloading default...")
    try:
        # Using a reliable placeholder URL (You can change this)
        # This is a generic free jazz/news loop.
        url = "https://upload.wikimedia.org/wikipedia/commons/e/e7/News_Theme_Swish.wav" 
        # Note: Wav works too, pydub handles it.
        r = requests.get(url)
        with open("bgm.wav", "wb") as f:
            f.write(r.content)
        # Convert to mp3 for consistency
        AudioSegment.from_wav("bgm.wav").export("bgm.mp3", format="mp3")
        return True
    except Exception as e:
        print(f"Could not download BGM: {e}")
        return False

def mix_music(voice_file, output_file):
    print("Mixing music...")
    has_music = ensure_bgm()

    if not has_music:
        print("No music available. Exporting voice only.")
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)
        return

    try:
        voice = AudioSegment.from_mp3(voice_file)
        bgm = AudioSegment.from_mp3("bgm.mp3")
        
        # Tuning Volume:
        # Voice is usually loud, BGM needs to be background.
        bgm = bgm - 20 # Lower BGM by 20dB
        
        # Loop BGM
        looped_bgm = bgm * (len(voice) // len(bgm) + 1)
        
        # Trim to fit voice + 4 seconds intro/outro
        final_bgm = looped_bgm[:len(voice) + 4000].fade_out(3000)
        
        # Overlay: Start voice after 0.5s of music
        final_mix = final_bgm.overlay(voice, position=500)
        
        final_mix.export(output_file, format="mp3")
        if os.path.exists(voice_file): os.remove(voice_file)
    except Exception as e:
        print(f"Mixing failed ({e}). Exporting raw voice.")
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)

# 3. JANITOR (AGGRESSIVE CLEANUP)
# -----------------------------
def run_janitor():
    print("🧹 Janitor starting cleanup...")
    now_hk = datetime.now(HKT)
    todays_file = f"brief_{now_hk.strftime('%Y%m%d')}.mp3"
    
    # 1. Clean up old episodes (Delete anything that isn't TODAY's brief)
    # We look for ANY mp3 starting with 'brief_'
    for f in glob.glob("brief_*.mp3"):
        if f != todays_file:
            try:
                os.remove(f)
                print(f"Deleted old episode: {f}")
            except Exception as e:
                print(f"Failed to delete {f}: {e}")

    # 2. Clean up temp junk
    # Delete anything matching the temp patterns
    junk_patterns = ["temp_line_*.mp3", "dialogue_raw.mp3", "bgm.wav"]
    for pattern in junk_patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                print(f"Deleted junk: {f}")
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
        f = feedparser.parse(FEED_TRENDS)
        trends = [item.title for item in f.entries[:8]]
        return ", ".join(trends)
    except: return "None"

def get_feeds(urls):
    content = ""
    count = 0
    for url in urls:
        if count >= 8: break
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
            return text
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
        return text
    except Exception as e:
        print(f"❌ Hugging Face failed: {e}")
        return "各位早晨，今日系統出現咗少少故障，請原諒。我地聽日再見。"

def write_script(hk_news, global_news, weather, trends):
    # STRONG INSTRUCTIONS FOR CANTONESE COLLOQUIALISM
    prompt = f"""
    You are "出木杉" (Dekisugi), a friendly Hong Kong News Podcaster.
    
    **CRITICAL LANGUAGE REQUIREMENT:**
    - You MUST speak in **Authentic Hong Kong Cantonese Colloquialism (廣東話口語)**.
    - **DO NOT** use Written Chinese (書面語).
    - **DO NOT** use phrases like "是", "的", "今天", "早上好".
    - **USE** phrases like "係", "嘅", "今日", "早晨", "搞掂", "睇下", "話時話".
    - Make it sound like a friend chatting, not a robot reading a press release.

    **Task:**
    Create a news podcast script based on the trending topics and news below.

    **Priorities:**
    1. Check these **Trending Keywords**: [{trends}]. If any news matches these, talk about it FIRST.
    2. Then cover 2-3 other major headlines.
    
    **Script Structure (Continuous Monologue):**
    1. **Intro:** Casual energetic greeting (e.g., "哈囉大家好，又係我出木杉陪大家睇新聞...").
    2. **Weather:** Quick check ({weather}).
    3. **Deep Dive:** The hottest trending topic. Explain it simply.
    4. **Roundup:** Quick fire other news.
    5. **English Corner:** Teach one ONE slang/idiom related to the news. Explain it in Cantonese.
    6. **Outro:** "好啦，今日講住咁多先，聽朝見！"

    **News Data:**
    HK News: {hk_news}
    Global News: {global_news}
    """
    return generate_script_robust(prompt)

def update_rss(audio_file, script):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    p = Podcast(
        name="香港早晨 (HK Morning)",
        description="Daily Cantonese News Briefing (AI Generated).",
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
    
    print("Generating colloquial script...")
    script = write_script(hk, gl, we, tr)
    
    try:
        asyncio.run(generate_monologue_audio(script, "dialogue_raw.mp3"))
        mix_music("dialogue_raw.mp3", final_mp3)
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        exit(1)
