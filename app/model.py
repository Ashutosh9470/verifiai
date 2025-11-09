# app/model.py
from google.cloud import language_v2 as language
import re
from functools import lru_cache
from typing import List, Dict, Any

SENSATIONAL = set("""
shocking unbelievable exposed scandal meltdown destroyed bombshell secretly banned miracle cure guaranteed instant
""".split())

@lru_cache(maxsize=1)
def _client():
    try:
        return language.LanguageServiceClient()
    except Exception as e:
        print(f"Failed to create Google Cloud Language client: {str(e)}")
        return None

def _split_sentences(text: str) -> List[str]:
    return re.split(r'(?<=[.!?])\s+', text.strip())

def _text_red_flags(text: str) -> float:
    caps_ratio = sum(1 for c in text if c.isupper()) / max(1, len(text))
    exclam = text.count("!")
    sensational_hits = sum(1 for w in re.findall(r"[a-zA-Z]+", text.lower()) if w in SENSATIONAL)
    penalty = 0.0
    if caps_ratio > 0.12: penalty += 0.2
    if exclam >= 3:      penalty += 0.15
    penalty += min(0.25, sensational_hits * 0.05)
    return min(0.6, penalty)

def _entity_quality(entities) -> float:
    score = 0.0
    for e in entities[:25]:
        md = getattr(e, "metadata", {}) or {}
        if ("wikipedia_url" in md) or ("mid" in md):
            score += 0.03
    return min(0.3, score)

def _analyze(text: str, language_code: str = "en"):
    client = _client()
    if not client:
        # Return empty results if client creation failed
        return None, [], []

    doc = {"content": text[:20000], "type_": language.Document.Type.PLAIN_TEXT, "language_code": language_code}
    enc = language.EncodingType.UTF8

    # sentiment with per-sentence magnitudes
    try:
        sresp = client.analyze_sentiment(document=doc, encoding_type=enc)
    except Exception as e:
        print(f"Failed to analyze sentiment: {str(e)}")
        try:
            auto_doc = {"content": text[:20000], "type_": language.Document.Type.PLAIN_TEXT}
            sresp = client.analyze_sentiment(document=auto_doc, encoding_type=enc)
        except Exception as e:
            print(f"Failed to analyze sentiment with auto-detection: {str(e)}")
            return None, [], []

    sentiment = sresp.document_sentiment
    sentences = [(s.text.content, float(getattr(s.sentiment, "magnitude", 0.0))) for s in sresp.sentences]

    # entities
    ent_resp = client.analyze_entities(document={"content": text[:20000], "type_": language.Document.Type.PLAIN_TEXT},
                                       encoding_type=enc)
    entities = ent_resp.entities

    # categories (best-effort)
    try:
        cat_resp = client.classify_text(document={"content": text[:20000], "type_": language.Document.Type.PLAIN_TEXT})
        categories = cat_resp.categories
    except Exception:
        categories = []

    return sentiment, sentences, entities, categories

def _collect_insights(text: str, sentences, entities) -> Dict[str, Any]:
    # top entities by salience
    key_entities = []
    for e in sorted(entities, key=lambda x: float(getattr(x, "salience", 0.0)), reverse=True)[:8]:
        md = getattr(e, "metadata", {}) or {}
        key_entities.append({
            "name": getattr(e, "name", ""),
            "type": str(getattr(e, "type_", "")),
            "salience": float(getattr(e, "salience", 0.0)),
            "wikipedia_url": md.get("wikipedia_url"),
            "mid": md.get("mid"),
        })

    # sensational words present
    words = re.findall(r"[a-zA-Z]+", text.lower())
    sensational_terms = sorted(list({w for w in words if w in SENSATIONAL}))[:10]

    # notable sentences by magnitude + shouty heuristics
    candidates = []
    for s, mag in sentences:
        caps_ratio = sum(1 for c in s if c.isupper()) / max(1, len(s))
        exclam = s.count("!")
        bonus = (0.8 if exclam >= 1 else 0.0) + (0.8 if caps_ratio > 0.12 else 0.0)
        candidates.append((mag + bonus, s.strip()))
    if not candidates:
        for s in _split_sentences(text)[:8]:
            caps_ratio = sum(1 for c in s if c.isupper()) / max(1, len(s))
            exclam = s.count("!")
            bonus = (0.8 if exclam >= 1 else 0.0) + (0.8 if caps_ratio > 0.12 else 0.0)
            candidates.append((bonus, s.strip()))
    notable_sentences = [s for _, s in sorted(candidates, key=lambda x: x[0], reverse=True)[:3] if s]

    return {
        "key_entities": key_entities,
        "sensational_terms": sensational_terms,
        "notable_sentences": notable_sentences,
    }

def classify_text(text: str, model_name: str = "gcp_nl", language_code: str = "en") -> dict:
    result = _analyze(text, language_code=language_code)
    if result is None or result[0] is None:
        # Fallback to basic heuristics if Google Cloud NLP fails
        penalty = _text_red_flags(text)
        return {
            "label": "uncertain",
            "score": 50,
            "confidence": 0.3,
            "features": {
                "sensational_penalty": penalty,
                "sentiment_magnitude": 0.0,
                "entity_wiki_hits": 0,
                "categories": []
            },
            "insights": {
                "key_entities": [],
                "sensational_terms": [w for w in re.findall(r"[a-zA-Z]+", text.lower()) if w in SENSATIONAL][:10],
                "notable_sentences": _split_sentences(text)[:2]
            }
        }
    
    sentiment, sentences, entities, categories = result
    score = 50.0
    if categories:
        catnames = [c.name.lower() for c in categories]
        if any(("news" in c) or ("law & government" in c) or ("business" in c) for c in catnames):
            score += 5

    score += _entity_quality(entities) * 100

    if sentiment:
        mag = float(getattr(sentiment, "magnitude", 0.0))
        score -= min(20.0, mag * 3.0)

    penalty = _text_red_flags(text)
    score -= penalty * 100

    score = max(0, min(100, round(score)))
    if score >= 70:
        label = "true"
    elif score <= 30:
        label = "fake"
    else:
        label = "uncertain"

    confidence = round(abs(score - 50) / 50, 2)

    insights = _collect_insights(text, sentences, entities)
    features = {
        "entity_wiki_hits": min(
            25,
            len([e for e in entities[:25]
                 if ("wikipedia_url" in (getattr(e, "metadata", {}) or {}))
                 or ("mid" in (getattr(e, "metadata", {}) or {}))])
        ),
        "sentiment_magnitude": float(getattr(sentiment, "magnitude", 0.0)) if sentiment else 0.0,
        "sensational_penalty": round(penalty, 3),
        "categories": [getattr(c, "name", "") for c in (categories or [])][:5],
    }

    return {
        "label": label,
        "score": score,
        "confidence": confidence,
        "features": features,
        "insights": insights,
    }
