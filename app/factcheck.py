from googleapiclient.discovery import build

def fact_check_search(query: str, lang: str = "en") -> list:
    """
    Search Google Fact Check Tools for claims related to a given query.
    Returns a list of claim results (if any).
    """
    try:
        svc = build("factchecktools", "v1alpha1", cache_discovery=False)
        res = svc.claims().search(query=query, languageCode=lang).execute()
        return res.get("claims", [])
    except Exception:
        return []

def summarize_claims(claims):
    """
    Summarize Fact Check results into a verdict and readable list.
    Returns:
        verdict: "true" | "fake" | "uncertain"
        summary: list of text lines explaining each claim review
    """
    if not claims:
        return None, []

    summary = []
    verdict = None

    for c in claims[:5]:
        for r in c.get("claimReview", []):
            publisher = r.get("publisher", {}).get("name", "Unknown")
            title = r.get("title", "")
            rating = (r.get("textRating") or "").lower()
            url = r.get("url", "")

            summary.append(f"{publisher}: {rating} — {title} ({url})")

            if any(x in rating for x in ["false", "fake", "pants on fire", "incorrect", "misleading"]):
                verdict = "fake"
            if any(x in rating for x in ["true", "correct", "mostly true", "accurate"]):
                verdict = verdict or "true"

    verdict = verdict or "uncertain"
    return verdict, summary
