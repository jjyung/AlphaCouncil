import json
import logging
import os
import re
import datetime
import zoneinfo
from pathlib import Path

import requests
import feedparser
from bs4 import BeautifulSoup
from google.adk.agents.llm_agent import Agent

logger = logging.getLogger(__name__)

# Resolved at import time so it works regardless of cwd
_DATA_DIR = Path(__file__).parent.parent / "data" / "news"

_TZ_TW = zoneinfo.ZoneInfo("Asia/Taipei")

# ---------------------------------------------------------------------------
# Link-validation constants
# ---------------------------------------------------------------------------

# Soft-404 fingerprints – checked against lowercase response body (≤ 64 KB).
# Covers 繁中 site messages from UDN / Yahoo TW / 鉅亨.
_SOFT_404_TOKENS: frozenset[str] = frozenset(
    [
        "頁面不存在",
        "找不到頁面",
        "已不存在",
        "已移除",
        "無法找到",
        "此文章不存在",
        "內容已下架",
        "404 not found",
        "page not found",
        "we can't find that page",
    ]
)

# Browser-like UA avoids 403 from sites that block bots.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# How many bytes to read from the response body for soft-404 detection.
_READ_LIMIT = 65_536  # 64 KB


def _normalize_ticker(ticker: str) -> str:
    """Normalise ticker to a safe directory-name component.

    Examples:  2330.TW → 2330_TW   AAPL → AAPL
    """
    return re.sub(r"[^\w]", "_", ticker).strip("_")


# ---------------------------------------------------------------------------
# Link validator
# ---------------------------------------------------------------------------


def _check_link(
    url: str,
    session: requests.Session,
    cache: dict[str, str],
    timeout: int = 8,
) -> tuple[str, str]:
    """Validate a single URL.

    Strategy:
    1. HEAD with allow_redirects=True.
       - 404 / 410  →  "broken" immediately (no body needed).
       - 405        →  server does not support HEAD; skip to GET.
       - 200        →  still need body to detect soft-404; fall through to GET.
       - RequestException on HEAD  →  go straight to GET.
       - any other code  →  "unknown" (conservative).
    2. GET with stream=True; read at most _READ_LIMIT bytes.
       - 404 / 410  →  "broken".
       - 200 + soft-404 token  →  "soft404".
       - 200 clean  →  "ok".
       - other code  →  "unknown".

    Results are memoised in *cache* so the same URL is never fetched twice
    within a single get_news call.

    Returns:
        (link_status, note) where link_status ∈ {"ok", "broken", "soft404", "unknown"}
    """
    if url in cache:
        return cache[url], "cached"

    def _read_body(resp: requests.Response) -> str:
        """Stream and decode up to _READ_LIMIT bytes from *resp*."""
        buf = b""
        for chunk in resp.iter_content(chunk_size=4_096):
            buf += chunk
            if len(buf) >= _READ_LIMIT:
                break
        return buf.decode("utf-8", errors="replace").lower()

    def _soft404(text: str) -> str | None:
        for token in _SOFT_404_TOKENS:
            if token in text:
                return token
        return None

    try:
        # --- Step 1: HEAD ---
        head_code: int | None = None
        try:
            hr = session.head(url, allow_redirects=True, timeout=timeout)
            head_code = hr.status_code
        except requests.RequestException:
            head_code = None  # treat as HEAD unsupported → fall through

        if head_code in (404, 410):
            cache[url] = "broken"
            return "broken", f"HTTP {head_code}"

        if head_code is not None and head_code not in (200, 405):
            # Unexpected redirect result or server error after redirect.
            cache[url] = "unknown"
            return "unknown", f"HTTP {head_code}"

        # --- Step 2: GET (needed for soft-404 check or HEAD not usable) ---
        gr = session.get(url, allow_redirects=True, timeout=timeout, stream=True)
        get_code = gr.status_code

        if get_code in (404, 410):
            cache[url] = "broken"
            return "broken", f"HTTP {get_code}"

        if get_code == 200:
            text = _read_body(gr)
            hit = _soft404(text)
            if hit:
                cache[url] = "soft404"
                return "soft404", f"soft 404（token: {hit!r}）"
            cache[url] = "ok"
            return "ok", ""

        cache[url] = "unknown"
        return "unknown", f"HTTP {get_code}"

    except requests.RequestException as exc:
        cache[url] = "unknown"
        return "unknown", f"request error: {exc}"


# ---------------------------------------------------------------------------
# Cache helpers (Req 6)
# ---------------------------------------------------------------------------

# Required fields for a cache entry to be considered valid.
# validate_links and link_validation are included so that a cache produced
# without link validation (all "skipped") cannot satisfy a request that
# needs validated links (Method A of the validate_links consistency fix).
_CACHE_REQUIRED_FIELDS = {
    "ticker",
    "date",
    "market",
    "source_status",
    "articles",
    "link_validation",   # stats dict; must be present
    "validate_links",    # bool stored at save time (Method A)
}


def _load_valid_cache(
    raw_path: Path,
    ticker: str,
    date: str,
    market: str,
    validate_links: bool,
) -> dict | None:
    """Return parsed cache dict if news_raw.json is valid for this request, else None.

    Valid cache conditions (ALL must hold):
    1. File exists and is valid JSON.
    2. All required top-level fields are present
       (ticker, date, market, source_status, articles, link_validation, validate_links).
    3. Stored date == requested date.
    4. Stored market == requested market (case-insensitive).
    5. Stored ticker == requested ticker (normalised: ignores .TW suffix).
    6. validate_links consistency (Method A):
       - If request needs validated links (validate_links=True),
         the cache must also have been built with validate_links=True.
       - If request does NOT need validation (validate_links=False),
         any cache (validated or not) is acceptable.
    """
    if not raw_path.exists():
        logger.debug("Cache miss (no file): %s", raw_path)
        return None

    try:
        data: dict = json.loads(raw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache corrupt (%s): %s — will re-fetch.", raw_path, exc)
        return None

    missing = _CACHE_REQUIRED_FIELDS - data.keys()
    if missing:
        logger.warning(
            "Cache missing required fields %s in %s — will re-fetch.", missing, raw_path
        )
        return None

    if data.get("date") != date:
        logger.debug("Cache miss (date mismatch): stored=%s requested=%s", data.get("date"), date)
        return None
    if data.get("market", "").upper() != market.upper():
        logger.debug("Cache miss (market mismatch): stored=%s requested=%s", data.get("market"), market)
        return None

    # Normalise ticker for comparison (strip ".TW" suffix)
    def _norm(t: str) -> str:
        return re.sub(r"\.TW$", "", t.strip(), flags=re.IGNORECASE)

    if _norm(data.get("ticker", "")) != _norm(ticker):
        logger.debug("Cache miss (ticker mismatch): stored=%s requested=%s", data.get("ticker"), ticker)
        return None

    # validate_links consistency check (Method A)
    cached_validated: bool = bool(data.get("validate_links"))
    if validate_links and not cached_validated:
        logger.info(
            "Cache miss (validate_links mismatch): request needs validated links "
            "but cache was built with validate_links=False — will re-fetch."
        )
        return None

    logger.info(
        "Cache hit: ticker=%s date=%s market=%s validate_links=%s (cached=%s)",
        ticker, date, market, validate_links, cached_validated,
    )
    return data


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------


def get_news(
    ticker: str,
    date: str = "",
    market: str = "",
    validate_links: bool = True,
) -> str:
    """Fetch news for a given stock, optionally validate every article link,
    save raw data locally, and return a JSON summary for model consumption.

    Args:
        ticker:         Stock ticker, e.g. "2330", "2330.TW".
        date:           Reference date in YYYY-MM-DD format.
                        Pass "" (empty string) to default to today in Asia/Taipei timezone.
        market:         Must be "TW" (US not yet supported).
                        Pass "" (empty string) to default to "TW".
        validate_links: When True (default), each non-empty link is checked
                        with HEAD→GET; broken / soft-404 links are flagged.
                        Override globally with env var NEWS_VALIDATE_LINKS=0.

    Returns:
        JSON string with source_status, link_validation stats, up to 30
        article objects (each with link_status), and the saved raw file path.
    """
    # ------------------------------------------------------------------ defaults
    # Req 5: Apply Taiwan-timezone defaults for date and market when not supplied.
    if not date or not date.strip():
        date = datetime.datetime.now(_TZ_TW).strftime("%Y-%m-%d")
        logger.info("get_news: date defaulted to today (TW timezone): %s", date)
    if not market or not market.strip():
        market = "TW"
        logger.info("get_news: market defaulted to TW")

    # Env-var can globally disable validation (useful in CI / offline tests).
    if os.environ.get("NEWS_VALIDATE_LINKS", "1").lower() in ("0", "false", "no"):
        validate_links = False

    market = market.upper().strip()
    normalized = _normalize_ticker(ticker)
    save_dir = _DATA_DIR / f"{normalized}_{date}"
    save_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ cache check
    # Req 6: Return cached data if same ticker/date/market/validate_links already fetched.
    raw_path = save_dir / "news_raw.json"
    cached = _load_valid_cache(raw_path, ticker, date, market, validate_links)
    if cached is not None:
        summary = {
            **cached,
            "total_articles": len(cached.get("articles", [])),
            "raw_file": str(raw_path),
            "cache_hit": True,
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)
    logger.info(
        "get_news: fetching ticker=%s date=%s market=%s validate_links=%s",
        ticker, date, market, validate_links,
    )

    articles: list[dict] = []
    source_status: dict[str, str] = {}

    _FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaCouncil/1.0)"}

    # ------------------------------------------------------------------
    # Early exit for unsupported markets
    # ------------------------------------------------------------------
    if market != "TW":
        source_status["market"] = (
            "目前僅支援 TW；請使用台股代號（如 2330、2330.TW）並將 market 設為 TW。"
        )
        raw_data = {
            "ticker": ticker,
            "date": date,
            "market": market,
            "validate_links": validate_links,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source_status": source_status,
            "link_validation": {"validated": 0, "ok": 0, "broken": 0, "soft404": 0, "unknown": 0, "skipped": 0},
            "articles": [],
        }
        raw_path.write_text(
            json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary = {**raw_data, "total_articles": 0, "raw_file": str(raw_path)}
        return json.dumps(summary, ensure_ascii=False, indent=2)

    ticker_clean = ticker.replace(".TW", "")

    # ------------------------------------------------------------------
    # 1. 經濟日報 RSS  — polls candidate URLs in order; stops at first with
    #    entries > 0.  If every URL returns HTTP 200 but 0 entries, the
    #    source is reported as an error rather than "ok(0 items)".
    # ------------------------------------------------------------------
    _ED_RSS_CANDIDATES = [
        "https://money.udn.com/rssfeed/news/1001/5591/5595/6649?ch=money",   # 台股即時
        "https://money.udn.com/rssfeed/news/1001/5591?ch=money",             # 股市大盤
        "https://money.udn.com/rssfeed/news/1001?ch=money",                  # 財經首頁
        "https://udn.com/rssfeed/news/2/6649?ch=news2",                      # 財經產業
    ]
    try:
        items: list[dict] = []
        _ed_tried: list[str] = []
        _ed_success_url: str | None = None

        for _ed_url in _ED_RSS_CANDIDATES:
            _ed_tried.append(_ed_url)
            _ed_feed = feedparser.parse(_ed_url)
            if not _ed_feed.entries:
                continue  # 0 entries → try next candidate
            # Found a live feed — build article list and stop
            _ed_success_url = _ed_url
            for entry in _ed_feed.entries[:20]:
                title = entry.get("title", "")
                if ticker_clean in title or ticker in title or not items:
                    items.append(
                        {
                            "title": title,
                            "link": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "summary": entry.get("summary", ""),
                            "source": "經濟日報",
                        }
                    )
            # No ticker hits in the matched pass → fall back to top-10 general
            if not any(ticker_clean in i["title"] or ticker in i["title"] for i in items):
                items = [
                    {
                        "title": e.get("title", ""),
                        "link": e.get("link", ""),
                        "published": e.get("published", ""),
                        "summary": e.get("summary", ""),
                        "source": "經濟日報",
                    }
                    for e in _ed_feed.entries[:10]
                ]
            break  # successful feed found; don't try remaining candidates

        if _ed_success_url is None:
            # Every candidate returned HTTP 200 but 0 entries
            source_status["經濟日報_RSS"] = (
                f"error: 所有 {len(_ed_tried)} 個 RSS 候選 URL 均回傳 0 則內容"
                f"（tried: {', '.join(_ed_tried)}）"
            )
        else:
            articles.extend(items)
            source_status["經濟日報_RSS"] = (
                f"ok ({len(items)} items, url={_ed_success_url})"
            )
    except Exception as exc:
        source_status["經濟日報_RSS"] = f"error: {exc}"

    # ------------------------------------------------------------------
    # 2. Yahoo Finance Taiwan RSS
    # ------------------------------------------------------------------
    try:
        yf_tw_url = "https://tw.news.yahoo.com/rss/finance"
        feed = feedparser.parse(yf_tw_url)
        matched: list[dict] = []
        fallback: list[dict] = []
        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            item = {
                "title": title,
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "source": "Yahoo Finance TW",
            }
            if ticker_clean in title or ticker in title:
                matched.append(item)
            elif len(fallback) < 10:
                fallback.append(item)
        items = matched if matched else fallback
        articles.extend(items)
        source_status["Yahoo_Finance_TW_RSS"] = f"ok ({len(items)} items)"
    except Exception as exc:
        source_status["Yahoo_Finance_TW_RSS"] = f"error: {exc}"

    # ------------------------------------------------------------------
    # 3. 鉅亨網 HTML (BeautifulSoup)
    # ------------------------------------------------------------------
    try:
        cnyes_url = (
            f"https://news.cnyes.com/news/cat/tw_stock_news?keyword={ticker_clean}"
        )
        resp = requests.get(cnyes_url, headers=_FETCH_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        raw_items: list[dict] = []
        for a_tag in soup.select("a[href*='/news/id/']")[:20]:
            title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            if not href.startswith("http"):
                href = "https://news.cnyes.com" + href
            if title:
                raw_items.append(
                    {
                        "title": title,
                        "link": href,
                        "published": "",
                        "summary": "",
                        "source": "鉅亨網",
                    }
                )
        # De-duplicate by title
        seen: set[str] = set()
        items = []
        for item in raw_items:
            if item["title"] not in seen:
                seen.add(item["title"])
                items.append(item)
        items = items[:15]
        articles.extend(items)
        source_status["鉅亨網_HTML"] = f"ok ({len(items)} items)"
    except Exception as exc:
        source_status["鉅亨網_HTML"] = f"error: {exc}"

    # ------------------------------------------------------------------
    # Link validation
    # ------------------------------------------------------------------
    lv_counts: dict[str, int] = {
        "validated": 0, "ok": 0, "broken": 0, "soft404": 0, "unknown": 0, "skipped": 0,
    }

    if validate_links:
        val_session = requests.Session()
        val_session.headers.update({"User-Agent": _BROWSER_UA})
        link_cache: dict[str, str] = {}

        for article in articles:
            url = article.get("link", "").strip()
            if not url:
                article["link_status"] = "skipped"
                lv_counts["skipped"] += 1
                continue

            status, note = _check_link(url, val_session, link_cache)
            lv_counts["validated"] += 1

            # Normalise "soft404" into the broken bucket for the model's
            # purposes, but keep it distinguishable in the raw data.
            article["link_status"] = "broken" if status == "soft404" else status
            if note and note != "cached":
                article["link_validation_note"] = note
            if status in lv_counts:
                lv_counts[status] += 1
            else:
                lv_counts["unknown"] += 1
    else:
        for article in articles:
            article["link_status"] = "skipped"
            lv_counts["skipped"] += 1

    # ------------------------------------------------------------------
    # Save raw data
    # ------------------------------------------------------------------
    raw_data = {
        "ticker": ticker,
        "date": date,
        "market": market,
        "validate_links": validate_links,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_status": source_status,
        "link_validation": lv_counts,
        "articles": articles,
    }
    raw_path.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ------------------------------------------------------------------
    # Return summary (cap articles at 30 to keep model context manageable)
    # ------------------------------------------------------------------
    summary = {
        "ticker": ticker,
        "date": date,
        "market": market,
        "source_status": source_status,
        "link_validation": lv_counts,
        "total_articles": len(articles),
        "articles": articles[:30],
        "raw_file": str(raw_path),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

news_analyst = Agent(
    model="gemini-2.5-flash",
    name="news_analyst",
    description="新聞分析師：以 get_news 取得原始列表，依證據分級寫出精準、可核對的 news_report。",
    tools=[get_news],
    output_key="news_report",
    instruction="""你是「台股個股新聞分析助手」，任務是根據單次 `get_news` 工具回傳資料，生成高可追溯、低幻覺的 `news_report`。

--------------------------------
零、工具呼叫優先級（最高強制規則 — 必須在所有輸出之前執行）
--------------------------------
1. 使用者訊息中只要有可辨識的股票代號（例如 2330、台積電、TSMC、AAPL），你必須「立即呼叫 `get_news`」，禁止先向使用者要求補充日期或市場。
2. 使用者未提供 `date` → 傳 date=""（工具會自動以台灣時區今日為基準）。
3. 使用者未提供 `market` → 傳 market=""（工具會自動預設為 "TW"）。
4. 你不得輸出「請提供查詢日期」或「請告訴我市場」之類的文字；若使用者根本沒給日期和市場，仍必須直接用空字串呼叫工具。
5. 如果你使用了預設日期／市場，可在最終 news_report 開頭加一行說明，例如：「本次使用預設：日期=今日(Asia/Taipei)、市場=TW」。
6. 唯一允許追問的情況：ticker 完全缺漏、無法解析、或使用者在同一訊息中混提多個不同標的且意圖不明。
7. 確認呼叫 `get_news` 後，再依下方【輸入資料】至【固定輸出格式】撰寫完整 news_report。

【輸入資料】
你會收到以下 JSON 結構（單次結果）：
- ticker
- date
- market
- fetched_at
- source_status
- link_validation
- articles[]，每筆含：
  - title
  - link
  - published
  - summary
  - source
  - link_status (ok / unknown / broken / soft404 / skipped)
  - link_validation_note (optional)

--------------------------------
一、最高優先硬規則（違反任一條即視為失敗）
--------------------------------
1) 僅能使用「本次輸入 JSON」中的資料，禁止引用任何歷史回合、記憶、外部知識或其他 ticker/date 的內容。
2) 每一則輸出新聞都必須來自本次 `articles[]`。
3) 每一則輸出新聞的 `title`、`link`、`published`、`source` 必須逐字保留原值，不可改寫、不可重編碼、不可縮網址、不可替換字詞。
4) 若某則新聞的 link 不存在於本次 `articles[].link`，該則不得輸出（防跨批次混入）。
5) 不得捏造任何未出現在輸入資料中的公司、數字、事件、時間、來源、連結。
6) 若證據不足，必須明說「無法判定」或「直接關聯有限」，不得硬推論。

--------------------------------
二、分類規則（嚴格）
--------------------------------
A. 【直接相關】
- 定義：標題或摘要明確點名目標標的（如 2330/台積電、2317/鴻海）且其為主要敘事主體。
- 若只是順帶提及（大盤、盤勢、族群文章附帶提到），降級為【產業關聯】。
- 上限：最多 3 則，可為 0。

B. 【產業關聯】
- 定義：半導體、AI伺服器、電子供應鏈、記憶體、代工、出口結構等可能影響標的所處產業，但未直接以標的為主體。
- 上限：最多 3 則。

B-2.【泛財經／宏觀】
- 定義：地緣政治、油價、匯率、總體市場、非核心產業消息，僅作背景。
- 上限：最多 2 則。

--------------------------------
三、link_status 使用規則（必須執行）
--------------------------------
1) ok：可正常列入 A/B。
2) unknown：可列入，但該條目末尾必須加註「（連結狀態未知）」。
3) broken 或 soft404：
   - 不得列入 A/B 主清單
   - 必須在 E.資料限制中統計並說明排除數量
4) skipped：預設不列入；若要提及，僅能在 E 說明。

--------------------------------
四、發布時間與日期對齊規則
--------------------------------
1) `published` 若為空字串，顯示：
   「發布時間：未提供（來源未附時間）」
2) 不可把 `date` 當成文章發布日；`date` 是本次抓取基準日。
3) 在 E 段必須提示：RSS/HTML 快照不保證覆蓋完整當日事件。

--------------------------------
五、影響評估語氣規則（保守）
--------------------------------
1) 只能用「可能、或、尚待確認、潛在」等保守措辭。
2) 禁止確定式語句：例如「必然上漲」「確定受惠」「將大幅衝擊」。
3) C 段每個判斷都必須附「證據：<已列出的原始標題>」。
4) 若 A 為 0，C 段需明確說明：結論主要依產業/宏觀外溢推估，可信度較低。
5) 關聯性指標（如定期定額戶數增長等）只能寫「可視為投資人關注度指標之一」，
   不得直接等同基本面結論（如「代表長期信心」「確定利多」）。

--------------------------------
六、輸出前自我檢查（先做再輸出）
--------------------------------
請在心中完成以下檢查：
- [ ] 所有引用 link 都存在於本次 articles[]
- [ ] title/link/published/source 無任何改寫
- [ ] A/B/宏觀數量符合上限
- [ ] unknown 條目有加註
- [ ] broken/soft404 未進 A/B，且已在 E 統計
- [ ] 若直接相關為 0，A 段有明確聲明
- [ ] C 段無過度確定語氣
- [ ] E 段包含 source_status、link_validation、時間對齊說明

若任一項不通過，先修正再輸出最終答案。

--------------------------------
七、固定輸出格式（嚴格照排版）
--------------------------------
### news_report

本次抓取直接相關：X 則；產業關聯：Y 則；泛財經：Z 則

**A. 標的新聞（Direct）**
- 若 X=0，僅輸出：
  「本次抓取無直接點名標的之報導。」
- 若 X>0，每則使用：

【直接相關】<1句保守摘要>
原始標題：<title>
來源：<source>
連結：<link>
發布時間：<published 或 未提供（來源未附時間）>

**B. 產業與外溢（Indirect）**

【產業關聯】
（最多3則；每則模板同上，前綴改【產業關聯】）

【泛財經／宏觀】
（最多2則；每則模板同上，前綴改【泛財經／宏觀】）

**C. 對標的之影響評估（保守）**
可能利多：
- <最多2點，且每點附證據>

情緒中性：
- <最多2點，且每點附證據>

可能利空：
- <最多2點，且每點附證據>

**D. 新聞情緒（僅針對本次列表）**
- 只能擇一：正面 / 中性偏正 / 中性 / 中性偏負 / 負面
- 用1~2句說明依據（僅引用 A/B 已列內容）

**E. 資料限制**
- source_status 摘要：<逐項>
- link_validation 摘要：validated/ok/unknown/broken/soft404/skipped
- 被排除條目數：<broken + soft404>
- unknown 條目數：<unknown>；並說明處置方式：
  - 若有納入 A/B 主清單者，寫「已納入者均加註（連結狀態未知）」
  - 若全部 unknown 均未納入，寫「主清單未納入 unknown 條目」
- 時間對齊說明：RSS/HTML 快照限制、published 缺失狀況
- 關聯性聲明：
  - 若 A=0，寫「與標的直接關聯有限」
  - 若 A>0 但直接相關則數佔比偏低，寫「直接關聯有但比例仍偏低」
  - 若 A 達上限（3則），可省略此聲明

本輸出僅供研究整理，不構成投資建議。
""",
)
