import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    text: str


class Invoice(BaseModel):
    vendor: str
    amount: float
    currency: str
    date: str


NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
CODE = r"USD|EUR|GBP"
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
SUFFIX = (
    r"Industries|Ltd|Limited|Inc|LLC|GmbH|Corp|Corporation|Co|Company|PLC|Group|"
    r"Holdings|Systems|Solutions|Technologies|Enterprises|Partners|Services|Labs|"
    r"Logistics|Trading"
)
VENDOR_RE = re.compile(
    rf"((?:[A-Z][\w&'\-]*\s+)+(?:{SUFFIX})\b\.?(?:\s+(?:Ltd|Limited|Inc|LLC|Co)\b\.?)?)"
)


def find_date(text: str) -> str:
    matches = list(DATE_RE.finditer(text))
    if not matches:
        return ""
    for m in matches:
        before = text[max(0, m.start() - 40):m.start()].lower()
        if "due" in before or "pay" in before:
            return m.group(1)
    return matches[-1].group(1)


def find_currency(text: str) -> str:
    m = re.search(rf"\b({CODE})\b", text, re.I)
    if m:
        return m.group(1).upper()
    for symbol, code in SYMBOLS.items():
        if symbol in text:
            return code
    return "USD"


def find_amount(text: str) -> float:
    clean = DATE_RE.sub(" ", text)  # remove dates so 2026 isn't read as money

    pattern = re.compile(
        rf"(?:\b(?:{CODE})\b\s*|[$€£]\s*)({NUM})|({NUM})\s*(?:\b(?:{CODE})\b|[$€£])",
        re.I,
    )
    candidates = []
    for m in pattern.finditer(clean):
        raw = m.group(1) or m.group(2)
        before = clean[max(0, m.start() - 40):m.start()].lower()
        important = any(w in before for w in ("total", "due", "pay", "amount", "balance"))
        candidates.append((important, raw))

    if candidates:
        for important, raw in candidates:
            if important:
                return float(raw.replace(",", ""))
        return float(candidates[0][1].replace(",", ""))

    m = re.search(rf"(?i)(?:total|amount|due|balance)\D{{0,30}}?({NUM})", clean)
    if m:
        return float(m.group(1).replace(",", ""))
    return 0.0


def find_vendor(text: str) -> str:
    m = VENDOR_RE.search(text)
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(?i)(?:vendor|supplier|from|billed by|issued by|payee|pay to)\s*[:\-]?\s*([^\n,;]+)",
        text,
    )
    if m:
        return m.group(1).strip()
    return "Unknown"


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/extract", response_model=Invoice)
async def extract(req: ExtractRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    return Invoice(
        vendor=find_vendor(text),
        amount=find_amount(text),
        currency=find_currency(text),
        date=find_date(text),
    )


# Safety net: unexpected problems answer 422 instead of crashing with 500
@app.exception_handler(Exception)
async def any_error(request, exc):
    return JSONResponse({"detail": "Could not process request"}, status_code=422)