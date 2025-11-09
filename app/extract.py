import requests
from bs4 import BeautifulSoup
from readability import Document
from urllib.parse import urlparse

def extract_from_url(url: str):
    """Fetch and extract clean article text from a given URL."""
    resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    doc = Document(resp.text)
    title = doc.short_title()
    html = doc.summary()

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n")
    source = urlparse(url).netloc

    return {
        "title": (title or "").strip(),
        "text": (text or "").strip(),
        "url": url,
        "source": source
    }
