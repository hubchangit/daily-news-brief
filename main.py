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
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # Global (English)
    "https://www.theverge.com/rss/index.xml"                       # Tech (English)
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            # Take top 2 items from each source
            for item in feed.entries[:2]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:200]
                source = "Global News (English)" if "bbc" in url or "verge" in url else "HK News"
                full_text += f"[{source}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 3. AI SCRIPT WRITING (NOTEBOOKLM STYLE)
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    
    # This prompt is the key to the "NotebookLM" feel.
    # We ask for a "Deep Dive" explanation, not a news reading.
    prompt = f"""
    You are "Tram Girl" (電車少女), a friendly and intelligent podcaster from Hong Kong.
    
    **Goal:** Take the raw news list below and turn it into a **casual, storytelling-style deep dive**. 
    Do NOT just read the headlines. Explain the stories like you are chatting with a friend on a tram ride.
    
    **Strict Rules:**
    1. **Language:** FULL Cantonese (Colloquial/Spoken). **Translate ALL English news into natural Cantonese.**
    2. **Tone:** Relaxed, natural, and warm. (Think: "NotebookLM Audio Overview" style).
    3. **No "Reactions":** Do not say things like "Wow!" or "My opinion is..." just explain the news naturally.
    4. **Flow:** Use connecting phrases like "講開又講..." (Speaking of which...), "其實即係..." (Basically it means...), "另外有單幾特別..." (Another interesting one is...).
    
    **Structure:**
    - **Intro:** "哈囉大家好，我又係電車少女。今日係 {datetime.now().strftime('%m月%d日')}，陪大家遊車河講新聞。"
    - **Body:** Weave the HK and Global news together naturally.
    - **Outro:** "好啦，今日講住咁多先。電車到站啦，下次見！"

    **Raw News Data:**
    {raw_news}
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, # Increased specifically for "storytelling"
            temperature=0.7  # Lowered slightly to keep translation accurate but natural
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "哈囉，今日連線有啲問題，大家睇住標題先啦。"

# 4. TEXT TO SPEECH (NATURAL PACING)
# -----------------------------
async def generate_audio(text, filename):
    # REMOVED "rate=+10%". To sound like NotebookLM (conversational), 
    # we need normal speed so the listener can process the "story".
    # "HiuGaai" is still the best female voice for this friendly tone.
    communicate = edge_tts.Communicate(text, "zh-HK-HiuGaaiNeural") 
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
        name="電車少女 (Tram Girl)", # Renamed
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
        title=f"電車日記: {today_str}", # Renamed Episode Title
        media=Media(f"{base_url}/{audio_filename}", 4000000, type="audio/mpeg"),
        summary=episode_text[:150] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    date_str = datetime.now().strftime('%Y%m%d')
    mp3_filename = f"brief_{date_str}.mp3"
    
    print("Fetching News (English & Chinese)...")
    raw_news = get_news()
    
    print("Writing Storytelling Script (Tram Girl)...")
    script = write_script(raw_news)
    
    print(f"Generating Audio (Natural Speed)...")
    asyncio.run(generate_audio(script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, script)
    print("Done!")
