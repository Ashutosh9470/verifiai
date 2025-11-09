import requests

API_KEY = "54bdf5db4b72433b9d65487144ae25f2"

# ✅ insert the API_KEY properly inside the f-string
url = f"https://newsapi.org/v2/top-headlines?language=en&pageSize=10&apiKey={API_KEY}"

response = requests.get(url)
data = response.json()

if data.get("status") == "ok":
    print("\n🔥 Trending News Topics:\n")
    for article in data["articles"]:
        title = article.get("title")
        link = article.get("url")
        if title and link:
            print(f"📰 {title}")
            print(f"   👉 {link}\n")
else:
    print("❌ Error fetching news:", data)
