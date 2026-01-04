import feedparser
import os
import asyncio
import edge_tts
from datetime import datetime
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
HF_TOKEN = os.environ.get("HF_TOKEN")

FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",      # HK News
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # Global
    "https://www.theverge.com/rss/index.xml"                       # Tech
]

# 2. FETCH NEWS (MORE CONTENT)
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            # INCREASED: Take top 5 items from each source (Total ~15 stories)
            for item in feed.entries[:5]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:250]
                source = "Global News (English)" if "bbc" in url or "verge" in url else "HK News"
                full_text += f"[{source}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 3. AI SCRIPT WRITING (LONG FORM)
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    
    prompt = f"""
    You are "Tram Girl" (電車少女), a friendly podcaster.
    
    **Goal:** Create a **LONG (5-7 minute)** deep-dive news podcast script in Cantonese.
    
    **Instructions:**
    1. **Language:** FULL Cantonese (Colloquial/Spoken). Translate ALL English news into natural Cantonese.
    2. **Depth:** Do NOT be brief. We need to fill time. Pick the 3-4 most important stories and **explain them in detail**. Why do they matter? What is the background?
    3. **Speed:** The audio will be played fast, so write in long, smooth sentences.
    4. **Flow:** Use connecting phrases like "講開又講..." (Speaking of which), "大家可能留意到..." (You might have noticed).
    5. **Structure:**
       - **Intro:** Casual greeting, date, weather (guess).
       - **Deep Dive (HK):** Discuss 2-3 major HK stories in depth.
       - **Deep Dive (Global/Tech):** Discuss 2-3 major Global stories in depth.
       - **Lightning Round:** Quickly mention 2-3 other smaller headlines.
       - **Outro:** "好啦，今日講咗好多，希望大家鍾意呢個詳盡版。下次見！"

    **Raw News Data:**
    {raw_news}
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500, # INCREASED: Allow for a much longer script
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "哈囉，今日新聞太多，AI 處理唔切，請稍後再試。"

# 4. TEXT TO SPEECH (1.5x SPEED)
# -----------------------------
async def generate_audio(text, filename):
    # Rate set to +50% (which equals 1.5x speed)
    communicate = edge_tts.Communicate(text, "zh-HK-HiuGaaiNeural", rate="+50%") 
    await communicate.save(filename)

# 5. GENERATE PODCAST FEED
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if repo_name:
        base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"
    else:
        base_url = "http://localhost"

    p = Podcast(
        name="電車少女 (Tram Girl)",
        description="A daily, relaxing news deep dive in Cantonese. (Global & Local)",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    p.add_episode(Episode(
        title=f"電車日記 (加長版): {today_str}", # Added label for Long Version
        media=Media(f"{base_url}/{audio_filename}", 9000000, type="audio/mpeg"), # Increased est. file size
        summary=episode_text[:150] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    date_str = datetime.now().strftime('%Y%m%d')
    mp3_filename = f"brief_{date_str}.mp3"
    
    print("Fetching Extended News...")
    raw_news = get_news()
    
    print("Writing Long-Form Script...")
    script = write_script(raw_news)
    
    print(f"Generating Audio (1.5x Speed)...")
    asyncio.run(generate_audio(script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, script)
    print("Done!")
