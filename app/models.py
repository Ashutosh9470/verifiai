from pydantic import BaseModel
from typing import Optional, List

class VerifyIn(BaseModel):
    input: str  # URL or plain text

class VerifyOut(BaseModel):
    article_id: Optional[str] = None
    score: int
    label: str              # "true" | "fake" | "uncertain"
    confidence: float       # 0..1
    explanation: List[str] = []

class ReportIn(BaseModel):
    url_or_text: str
    note: Optional[str] = None
