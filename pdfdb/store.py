"""로컬 데이터베이스(SQLite). 파일 하나(data/pdf_db.sqlite3)에 모든 내용이 들어갑니다."""
import json
import shutil
import sqlite3
import threading
from collections import Counter, defaultdict
from datetime import datetime

from . import paths, textutil

_write_lock = threading.RLock()
FTS = False  # SQLite 전문 검색(trigram) 사용 가능 여부. init()에서 정해집니다.

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  filename TEXT, folder TEXT,
  category TEXT DEFAULT '미분류',
  category_locked INTEGER DEFAULT 0,
  size INTEGER, mtime REAL,
  pages INTEGER DEFAULT 0, chars INTEGER DEFAULT 0,
  is_scanned INTEGER DEFAULT 0,
  text_source TEXT DEFAULT 'pdf',
  doc_date TEXT, dates TEXT, keywords TEXT,
  summary_ai TEXT, error TEXT,
  added_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS pages(
  doc_id INTEGER NOT NULL, page_no INTEGER NOT NULL, text TEXT,
  PRIMARY KEY(doc_id, page_no)
);
CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY, added_at TEXT);
CREATE INDEX IF NOT EXISTS idx_doc_cat ON documents(category);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    con = sqlite3.connect(str(paths.DB_PATH), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init():
    global FTS
    paths.ensure_dirs()
    with connect() as con:
        con.executescript(SCHEMA)
        try:
            con.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5("
                "text, doc_id UNINDEXED, page_no UNINDEXED, tokenize='trigram')"
            )
            FTS = True
        except sqlite3.OperationalError:
            FTS = False  # 오래된 SQLite: 일반 검색(LIKE)으로 동작
    if not paths.CATEGORIES_PATH.exists():
        shutil.copy(paths.DEFAULT_CATEGORIES_PATH, paths.CATEGORIES_PATH)


# ---------------------------------------------------------------- 분류 규칙

def load_categories():
    try:
        data = json.loads(paths.CATEGORIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = json.loads(paths.DEFAULT_CATEGORIES_PATH.read_text(encoding="utf-8"))
    return [c for c in data.get("categories", []) if c.get("name")]


def save_categories(cats):
    payload = {"_설명": "분류 이름과 그 분류를 알아보는 단어들입니다.", "categories": cats}
    paths.CATEGORIES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def classify(filename, text, cats=None):
    """파일 이름과 앞부분 본문에 분류별 단어가 몇 번 나오는지 세어 가장 많은 분류를 고릅니다."""
    cats = cats or load_categories()
    head = (text or "")[:20000].lower()
    name = (filename or "").lower()
    best, best_score = "미분류", 0
    for c in cats:
        score = 0
        for kw in c.get("keywords", []):
            k = kw.strip().lower()
            if not k:
                continue
            score += min(head.count(k), 15)
            if k in name:
                score += 10  # 파일 이름에 들어 있으면 강한 신호
        if score > best_score:
            best, best_score = c["name"], score
    return best if best_score >= 2 else "미분류"


# ---------------------------------------------------------------- 저장·삭제

def get_doc_by_path(con, path):
    return con.execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()


def save_document(path, filename, folder, size, mtime, page_texts, error=None, text_source="pdf"):
    full = "\n".join(page_texts)
    chars = len(full.replace(" ", "").replace("\n", ""))
    n = len(page_texts)
    is_scanned = 1 if n > 0 and chars < 30 * n else 0
    dates = textutil.find_dates(full)
    keywords = textutil.top_keywords(full, 15)
    with _write_lock, connect() as con:
        old = get_doc_by_path(con, path)
        category = classify(filename, full)
        if old and old["category_locked"]:
            category = old["category"]
        if old:
            doc_id = old["id"]
            con.execute(
                """UPDATE documents SET filename=?, folder=?, category=?, size=?, mtime=?, pages=?, chars=?,
                   is_scanned=?, text_source=?, doc_date=?, dates=?, keywords=?, error=?, updated_at=?,
                   summary_ai=NULL WHERE id=?""",
                (filename, folder, category, size, mtime, n, chars, is_scanned, text_source,
                 dates[0] if dates else None, json.dumps(dates, ensure_ascii=False),
                 json.dumps(keywords, ensure_ascii=False), error, now(), doc_id),
            )
            _delete_pages(con, doc_id)
        else:
            cur = con.execute(
                """INSERT INTO documents(path, filename, folder, category, size, mtime, pages, chars, is_scanned,
                   text_source, doc_date, dates, keywords, error, added_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (path, filename, folder, category, size, mtime, n, chars, is_scanned, text_source,
                 dates[0] if dates else None, json.dumps(dates, ensure_ascii=False),
                 json.dumps(keywords, ensure_ascii=False), error, now(), now()),
            )
            doc_id = cur.lastrowid
        rows = [(doc_id, i + 1, t) for i, t in enumerate(page_texts)]
        con.executemany("INSERT INTO pages(doc_id, page_no, text) VALUES(?,?,?)", rows)
        if FTS:
            con.executemany("INSERT INTO pages_fts(doc_id, page_no, text) VALUES(?,?,?)", rows)
        return doc_id


def _delete_pages(con, doc_id):
    con.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
    if FTS:
        con.execute("DELETE FROM pages_fts WHERE doc_id=?", (doc_id,))


def delete_document(doc_id):
    with _write_lock, connect() as con:
        _delete_pages(con, doc_id)
        con.execute("DELETE FROM documents WHERE id=?", (doc_id,))


def set_category(doc_id, category):
    with _write_lock, connect() as con:
        con.execute("UPDATE documents SET category=?, category_locked=1 WHERE id=?", (category, doc_id))


def reclassify_all():
    cats = load_categories()
    changed = 0
    with _write_lock, connect() as con:
        docs = con.execute("SELECT id, filename, category, category_locked FROM documents").fetchall()
        for d in docs:
            text = "\n".join(r["text"] or "" for r in con.execute(
                "SELECT text FROM pages WHERE doc_id=? ORDER BY page_no", (d["id"],)))
            kws = json.dumps(textutil.top_keywords(text, 15), ensure_ascii=False)
            con.execute("UPDATE documents SET keywords=? WHERE id=?", (kws, d["id"]))
            if d["category_locked"]:
                continue
            new = classify(d["filename"], text, cats)
            if new != d["category"]:
                con.execute("UPDATE documents SET category=? WHERE id=?", (new, d["id"]))
                changed += 1
    return changed


def set_ai_summary(doc_id, text):
    with _write_lock, connect() as con:
        con.execute("UPDATE documents SET summary_ai=? WHERE id=?", (text, doc_id))


# ---------------------------------------------------------------- 폴더 목록

def add_source(path):
    with _write_lock, connect() as con:
        con.execute("INSERT OR IGNORE INTO sources(path, added_at) VALUES(?,?)", (path, now()))


def list_sources():
    with connect() as con:
        rows = con.execute("SELECT path, added_at FROM sources ORDER BY added_at").fetchall()
        out = []
        for r in rows:
            prefix = r["path"].rstrip("/\\")
            cnt = con.execute(
                "SELECT COUNT(*) FROM documents WHERE path LIKE ? ESCAPE '!'",
                (_like_escape(prefix) + "%",),
            ).fetchone()[0]
            out.append({"path": r["path"], "added_at": r["added_at"], "documents": cnt})
        return out


def remove_source(path, drop_documents=True):
    with _write_lock, connect() as con:
        con.execute("DELETE FROM sources WHERE path=?", (path,))
        ids = []
        if drop_documents:
            prefix = path.rstrip("/\\")
            ids = [r[0] for r in con.execute(
                "SELECT id FROM documents WHERE path LIKE ? ESCAPE '!'", (_like_escape(prefix) + "%",))]
    for i in ids:
        delete_document(i)
    return len(ids)


def _like_escape(s):
    return s.replace("!", "!!").replace("%", "!%").replace("_", "!_")


# ---------------------------------------------------------------- 조회

def _doc_dict(r, full=False):
    d = dict(r)
    for k in ("dates", "keywords"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    if not full:
        d.pop("summary_ai", None)
    return d


def list_documents(category=None, name=None, scanned=None, sort="recent"):
    sql = "SELECT * FROM documents WHERE 1=1"
    args = []
    if category:
        sql += " AND category=?"
        args.append(category)
    if name:
        sql += " AND filename LIKE ? ESCAPE '!'"
        args.append(f"%{_like_escape(name)}%")
    if scanned:
        sql += " AND is_scanned=1"
    order = {
        "recent": "added_at DESC, id DESC",
        "name": "filename COLLATE NOCASE",
        "date": "COALESCE(doc_date, '') DESC",
    }.get(sort, "added_at DESC")
    sql += f" ORDER BY {order}"
    with connect() as con:
        return [_doc_dict(r) for r in con.execute(sql, args)]


def get_document(doc_id, with_pages=True):
    with connect() as con:
        r = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not r:
            return None
        d = _doc_dict(r, full=True)
        if with_pages:
            d["page_texts"] = [p["text"] or "" for p in con.execute(
                "SELECT text FROM pages WHERE doc_id=? ORDER BY page_no", (doc_id,))]
        return d


def document_text(doc_id):
    with connect() as con:
        return [p["text"] or "" for p in con.execute(
            "SELECT text FROM pages WHERE doc_id=? ORDER BY page_no", (doc_id,))]


def stats():
    with connect() as con:
        total = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(pages),0) p, COALESCE(SUM(is_scanned),0) s, "
            "COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END),0) e FROM documents").fetchone()
        cats = con.execute(
            "SELECT category, COUNT(*) n FROM documents GROUP BY category ORDER BY n DESC").fetchall()
        years = con.execute(
            "SELECT substr(doc_date,1,4) y, COUNT(*) n FROM documents WHERE doc_date IS NOT NULL "
            "GROUP BY y ORDER BY y").fetchall()
        no_date = con.execute("SELECT COUNT(*) FROM documents WHERE doc_date IS NULL").fetchone()[0]
    return {
        "documents": total["n"], "pages": total["p"], "scanned": total["s"], "errors": total["e"],
        "categories": [{"name": r["category"], "count": r["n"]} for r in cats],
        "years": [{"year": r["y"], "count": r["n"]} for r in years],
        "no_date": no_date, "fts": FTS,
    }


def keyword_stats(category=None, n=40):
    counter = Counter()
    sql = "SELECT keywords FROM documents" + (" WHERE category=?" if category else "")
    with connect() as con:
        for r in con.execute(sql, (category,) if category else ()):
            try:
                for w in json.loads(r["keywords"] or "[]"):
                    counter[w] += 1
            except Exception:
                pass
    return [{"word": w, "docs": c} for w, c in counter.most_common(n)]


# ---------------------------------------------------------------- 검색

def search(query, category=None, require_all=True, limit=60, terms=None):
    """검색어가 들어 있는 문서와 쪽을 찾습니다.
    require_all=True 이면 모든 검색어가 (어느 쪽에든) 들어 있는 문서만 보여 줍니다."""
    terms = terms or [t for t in (query or "").split() if t.strip()]
    terms = [t.strip().strip('"') for t in terms if t.strip().strip('"')]
    if not terms:
        return {"terms": [], "results": [], "total": 0}
    lows = [t.lower() for t in terms]

    with connect() as con:
        if FTS and all(len(t) >= 3 for t in terms):
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
            rows = con.execute(
                "SELECT CAST(doc_id AS INTEGER) doc_id, CAST(page_no AS INTEGER) page_no, text "
                "FROM pages_fts WHERE pages_fts MATCH ? LIMIT 5000", (match,)).fetchall()
        else:
            where = " OR ".join("text LIKE ? ESCAPE '!'" for _ in terms)
            rows = con.execute(
                f"SELECT doc_id, page_no, text FROM pages WHERE {where} LIMIT 5000",
                [f"%{_like_escape(t)}%" for t in terms]).fetchall()
        name_where = " OR ".join("filename LIKE ? ESCAPE '!'" for _ in terms)
        name_hits = {r[0] for r in con.execute(
            f"SELECT id FROM documents WHERE {name_where}", [f"%{_like_escape(t)}%" for t in terms])}
        docs = {r["id"]: r for r in con.execute("SELECT * FROM documents")}

    per_doc = defaultdict(lambda: {"pages": [], "found": set(), "score": 0})
    for r in rows:
        text = r["text"] or ""
        low = text.lower()
        counts = [low.count(t) for t in lows]
        if not any(counts):
            continue
        entry = per_doc[r["doc_id"]]
        entry["score"] += sum(counts)
        entry["found"].update(t for t, c in zip(lows, counts) if c)
        entry["pages"].append((sum(counts), r["page_no"], text))
    for did in name_hits:
        entry = per_doc[did]
        name = (docs[did]["filename"] or "").lower() if did in docs else ""
        entry["found"].update(t for t in lows if t in name)
        entry["score"] += 20

    results = []
    for did, e in per_doc.items():
        d = docs.get(did)
        if not d:
            continue
        if category and d["category"] != category:
            continue
        if require_all and len(e["found"]) < len(lows):
            continue
        pages = sorted(e["pages"], key=lambda x: (-x[0], x[1]))
        hits = [{"page": p, "count": c, "snippet": textutil.snippet(t, terms)} for c, p, t in pages[:4]]
        results.append({
            "id": did, "filename": d["filename"], "category": d["category"], "doc_date": d["doc_date"],
            "pages": d["pages"], "score": e["score"] + 5 * len(e["found"]), "matched_pages": len(pages),
            "hits": hits,
        })
    results.sort(key=lambda x: -x["score"])
    return {"terms": terms, "results": results[:limit], "total": len(results)}


def pages_for_context(doc_id, page_nos, max_chars=3500):
    with connect() as con:
        out = []
        for p in page_nos:
            r = con.execute("SELECT text FROM pages WHERE doc_id=? AND page_no=?", (doc_id, p)).fetchone()
            if r:
                out.append((p, (r["text"] or "")[:max_chars]))
        return out


def replace_pages(doc_id, page_texts, text_source):
    """AI로 읽어 낸 글자로 문서의 본문을 바꿉니다(스캔본용)."""
    d = get_document(doc_id, with_pages=False)
    if not d:
        return
    save_document(d["path"], d["filename"], d["folder"], d["size"], d["mtime"], page_texts,
                  text_source=text_source)
