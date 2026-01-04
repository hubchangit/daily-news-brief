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
    "https://www.hk01.com/rss",                                    # HK News
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # Global
    "https://www.theverge.com/rss/index.xml"                       # Tech
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for item in feed.entries[:2]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:150]
                source_name = "Global News" if "bbc" in url or "verge" in url else "HK News"
                full_text += f"[{source_name}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 3. AI SCRIPT WRITING (FUNNY MODE)
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    
    prompt = f"""
    You are "Ah-Fa" (阿發), a witty, sarcastic, and energetic Hong Kong YouTuber/Podcaster.
    
    Instructions:
    1. **Language:** Use very colloquial Cantonese (Oral/Spoken) with HK slang (e.g., "爆單嘢", "搞錯", "食花生").
    2. **Tone:** High energy, funny, and slightly mean/sarcastic.
    3. **Content:** Summarize the news, but add your own 1-sentence sarcastic reaction to each story.
    4. **Structure:**
       - Start: "喂各位早晨！又係我阿發講新聞時間。今日 {datetime.now().strftime('%m月%d日')}，睇下個世界發生咩事。"
       - Group HK news first, then Global news.
       - End: "好啦，講完收工！記得飲多杯水呀，拜拜！"
    5. **Format:** Pure text only. No emojis.

    Raw News:
    {raw_news}
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.85
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "各位早晨，阿發今日個腦實左少少，讀住標題先啦。"

# 4. TEXT TO SPEECH (FAST MODE)
# -----------------------------
async def generate_audio(text, filename):
    communicate = edge_tts.Communicate(text, "zh-HK-HiuGaaiNeural", rate="+10%")
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
        name="阿發講新聞 (Ah Fa Daily)",
        description="Daily sarcastic news briefing in Cantonese.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Ah Fa", "news@example.com")],
        owner=Person("Ah Fa", "news@example.com"),
        # FIXED LINE BELOW:
        category=Category("News", "Daily News"), 
    )
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    p.add_episode(Episode(
        title=f"阿發簡報: {today_str}",
        media=Media(f"{base_url}/{audio_filename}", 4000000, type="audio/mpeg"),
        summary=episode_text[:100] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    date_str = datetime.now().strftime('%Y%m%d')
    mp3_filename = f"brief_{date_str}.mp3"
    
    print("Fetching Global & HK news...")
    raw_news = get_news()
    
    print("Writing Witty Script...")
    script = write_script(raw_news)
    
    print(f"Generating Audio (Fast Mode)...")
    asyncio.run(generate_audio(script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, script)
    print("Done!")
