import feedparser
import os
import asyncio
import edge_tts
from datetime import datetime
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
REPO_ID = "mistralai/Mistral-7B-Instruct-v0.3"
HF_TOKEN = os.environ.get("HF_TOKEN")

FEEDS = [
    "https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml"
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        feed = feedparser.parse(url)
        for item in feed.entries[:3]:
            clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:200]
            full_text += f"- {item.title}: {clean_desc}\n"
    return full_text

# 3. AI SCRIPT WRITING
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    prompt = f"""
    You are a professional news anchor. Summarize these headlines into a 2-minute spoken script.
    Hong Kong news first, then Global. Plain text only. No markdown.
    Start: "Good morning. Here is the daily brief for {datetime.now().strftime('%A, %B %d')}."
    End: "That is the news."
    
    News:
    {raw_news}
    """
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "Good morning. Here are the headlines. " + raw_news

# 4. TEXT TO SPEECH
# -----------------------------
async def generate_audio(text, filename="episode.mp3"):
    communicate = edge_tts.Communicate(text, "en-GB-SoniaNeural")
    await communicate.save(filename)

# 5. GENERATE PODCAST FEED (FIXED FOR APPLE)
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if repo_name:
        base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"
    else:
        base_url = "http://localhost"

    p = Podcast(
        name="HK Daily Brief",
        description="Daily AI-generated news for Hong Kong.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png", # GENERIC ICON
        language="en",
        authors=[Person("AI News Bot", "news@example.com")], # REQUIRED BY APPLE
        owner=Person("My News Bot", "news@example.com"),     # REQUIRED BY APPLE
        category=Category("News", "Daily News"),             # REQUIRED BY APPLE
        withhold_from_itunes=True                            # Tells Apple this is private (optional)
    )
    
    p.add_episode(Episode(
        title=f"Briefing: {datetime.now().strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 4000000, type="audio/mpeg"),
        summary=episode_text[:200] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    raw_news = get_news()
    script = write_script(raw_news)
    asyncio.run(generate_audio(script, "daily_brief.mp3"))
    update_rss("daily_brief.mp3", script)
