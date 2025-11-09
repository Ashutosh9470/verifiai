# app/main.py
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Dict, Any, List, Optional

from .config import settings
from .firebase import get_db
from .model import classify_text
from .factcheck import fact_check_search, summarize_claims
from .models import VerifyIn, VerifyOut, ReportIn
from google.cloud import firestore as gcf

app = FastAPI(title="VerifiAI Backend (Text-only + Explainable Insights)")

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions ---
def save_article(db, meta: Dict[str, Any]) -> Optional[str]:
    data = {
        "title": meta.get("title"),
        "text": meta["text"],
        "url": None,
        "source": None,
        "created_at": datetime.utcnow(),
    }
    # get the DocumentReference (index 0), not the write time
    doc_ref, _ = db.collection("articles").add(data)
    return doc_ref.id


def save_verification(db, article_id: Optional[str], result: Dict[str, Any], explanation: List[str]):
    doc = {
        "article_id": article_id,
        "score": result["score"],
        "label": result["label"],
        "confidence": result["confidence"],
        "explanation": explanation,
        "created_at": datetime.utcnow(),
    }
    db.collection("verifications").add(doc)


# --- Routes ---

@app.get("/health")
def health():
    db = get_db()
    return {"ok": True, "model": settings.MODEL_NAME, "db": True}


@app.post("/verify", response_model=VerifyOut)
def verify(payload: VerifyIn = Body(...)):
    """
    Text-only verification with Explainable AI:
    - Uses Google Cloud NLP for credibility scoring
    - Adds insights from sentiment, entities, sensational terms, etc.
    - Optionally runs Google Fact Check Tools
    """
    db = get_db()
    text = payload.input.strip()
    title = text[:120]
    lang = getattr(payload, "language", "en")

    # Step 1: Run NLP model (returns features + insights)
    result = classify_text(title + ". " + text, settings.MODEL_NAME, language_code=lang)

    # Step 2: Build explainable reasons (clean + deduped)
    explanation: List[str] = []
    f = (result.get("features") or {})
    i = (result.get("insights") or {})

    pen = float(f.get("sensational_penalty", 0.0))
    mag = float(f.get("sentiment_magnitude", 0.0))
    wiki_hits = int(f.get("entity_wiki_hits", 0))

    # categories: take from features/insights, dedupe, keep 3, shorten nicely
    raw_cats = (i.get("categories") or f.get("categories") or [])
    cats = []
    seen_cat = set()
    for c in raw_cats:
        if not c:
            continue
        # shorten "/A/B/C" → "C"
        short = c.split("/")[-1] if "/" in c else c
        key = short.lower()
        if key not in seen_cat:
            seen_cat.add(key)
            cats.append(short)
        if len(cats) >= 3:
            break

    # sensational terms: dedupe + keep 6
    terms = list(dict.fromkeys((i.get("sensational_terms") or [])))
    terms = terms[:6]

    # key entities: dedupe by lowercase name, mark wiki, keep 4
    ke = i.get("key_entities") or []
    names = []
    seen = set()
    for e in ke:
        nm = (e or {}).get("name")
        if not nm:
            continue
        k = nm.strip().lower()
        if k in seen:
            continue
        seen.add(k)
        if (e or {}).get("wikipedia_url"):
            nm = f"{nm} (wiki)"
        names.append(nm)
        if len(names) >= 4:
            break

    # notables: dedupe, keep 1–2
    notables = []
    seen_lines = set()
    for s in (i.get("notable_sentences") or []):
        s = (s or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen_lines:
            continue
        seen_lines.add(k)
        notables.append(s)
        if len(notables) >= 2:
            break

    # build explanation list (lenient but tidy)
    if pen > 0:
        explanation.append(f"Sensational writing patterns detected (penalty {pen:.2f})")
    if mag >= 1.0:
        explanation.append(f"High emotional tone (sentiment magnitude ≈ {mag:.2f})")
    if wiki_hits > 0:
        explanation.append(f"Grounded entities found: {wiki_hits} linked to Wikipedia/Knowledge Graph")
    if cats:
        explanation.append("Topical category hints: " + ", ".join(cats))
    if names:
        explanation.append("Key entities: " + ", ".join(names))
    if terms:
        explanation.append("Sensational terms in text: " + ", ".join(terms))
    for s in notables:
        snippet = s[:160] + ("…" if len(s) > 160 else "")
        explanation.append(f'Notable line: "{snippet}"')

    if not explanation:
        explanation.append("Computed from entity grounding, sentiment magnitude, and sensational-text heuristics.")

    # Step 3: Fact Check (optional, best-effort)
    try:
        claims = fact_check_search(title)
        fc_verdict, fc_summary = summarize_claims(claims)
    except Exception:
        fc_verdict, fc_summary = None, []

    # Step 4: Merge Fact Check verdict with model score
    if fc_verdict and fc_verdict in ["true", "fake"]:
        result["label"] = fc_verdict
        result["score"] = 85 if fc_verdict == "true" else 15
        result["confidence"] = 0.9
        explanation.insert(0, f"Fact Check verdict: {fc_verdict}")

    if fc_summary:
        explanation.extend(fc_summary[:3])

    if not explanation:
        explanation.append("Computed from entity grounding, sentiment magnitude, and sensational-text heuristics.")

    # Step 5: Save safely to Firestore
    article_id: Optional[str] = None
    try:
        meta = {"title": text[:100], "text": text}
        article_id = save_article(db, meta)
        save_verification(db, article_id, result, explanation)
    except Exception as e:
        explanation.append(f"(Note: DB save skipped: {e.__class__.__name__})")

    # Step 6: Return explainable output
    return {
        "article_id": article_id,
        "score": result["score"],
        "label": result["label"],
        "confidence": result["confidence"],
        "explanation": explanation,
        "features": result.get("features"),
        "insights": result.get("insights"),
    }


@app.get("/recent")
def recent(limit: int = 20):
    db = get_db()
    docs = (
        db.collection("verifications")
        .order_by("created_at", direction=gcf.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    items = []
    for d in docs:
        it = d.to_dict()
        it["id"] = d.id
        it["article_id"] = it.get("article_id")
        items.append(it)
    return {"items": items}


@app.get("/articles/{id}")
def get_article(id: str):
    db = get_db()
    art_ref = db.collection("articles").document(id).get()
    if not art_ref.exists:
        return {"article": None, "verifications": []}

    article = art_ref.to_dict()
    article["id"] = id

    vers = (
        db.collection("verifications")
        .where("article_id", "==", id)
        .order_by("created_at", direction=gcf.Query.DESCENDING)
        .stream()
    )
    vlist = []
    for v in vers:
        d = v.to_dict()
        d["id"] = v.id
        vlist.append(d)

    return {"article": article, "verifications": vlist}


@app.post("/report")
def report(payload: ReportIn):
    db = get_db()
    res = db.collection("reports").add({
        "url_or_text": payload.url_or_text,
        "note": payload.note,
        "status": "new",
        "created_at": datetime.utcnow()
    })[1]
    return {"ok": True, "id": res.id}
