"""PDF 자료 검색기 - 실행 파일.

START_Windows.bat(윈도우) 또는 START_Mac.command(맥)를 두 번 클릭하면 이 파일이 실행됩니다.
이 PC 안에서만 열리는 웹 화면(http://127.0.0.1:포트)을 띄우고 브라우저를 자동으로 엽니다.
"""
import csv
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from pdfdb import VERSION, ai, importer, paths, store, textutil

app = Flask(__name__, static_folder=str(paths.APP_DIR / "web"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 업로드 최대 2GB
app.json.ensure_ascii = False


def ok(**kw):
    return jsonify({"ok": True, **kw})


def fail(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


def norm(p):
    return str(Path(os.path.expanduser(p.strip().strip('"'))).resolve())


# ---------------------------------------------------------------- 화면

@app.get("/")
def index():
    return send_from_directory(paths.APP_DIR / "web", "index.html")


@app.get("/api/ping")
def ping():
    return ok(app="pdf-search-app", version=VERSION)


@app.get("/api/stats")
def api_stats():
    s = store.stats()
    s.update(ai_enabled=ai.enabled(), inbox=str(paths.INBOX_DIR), sources=store.list_sources(),
             version=VERSION)
    return ok(**s)


# ---------------------------------------------------------------- 가져오기

@app.post("/api/pick-folder")
def pick_folder():
    """이 PC의 폴더 선택 창을 띄웁니다(서버가 사용자 PC에서 돌기 때문에 가능)."""
    code = (
        "import tkinter as t, tkinter.filedialog as f\n"
        "r=t.Tk(); r.withdraw()\n"
        "try: r.attributes('-topmost', True)\n"
        "except Exception: pass\n"
        "p=f.askdirectory(title='PDF가 들어 있는 폴더를 고르세요', mustexist=True)\n"
        "print(p or '')\n"
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           encoding="utf-8", timeout=900, env=env)
        path = (r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else ""
        if r.returncode != 0 and not path:
            return fail("폴더 선택 창을 열 수 없습니다. 폴더 주소를 직접 붙여 넣어 주세요.")
        return ok(path=norm(path) if path else "")
    except Exception:
        return fail("폴더 선택 창을 열 수 없습니다. 폴더 주소를 직접 붙여 넣어 주세요.")


@app.post("/api/import")
def api_import():
    folder = (request.json or {}).get("folder", "")
    if not folder.strip():
        return fail("폴더를 먼저 골라 주세요.")
    folder = norm(folder)
    if not os.path.isdir(folder):
        return fail(f"폴더를 찾을 수 없습니다: {folder}")
    store.add_source(folder)
    if not importer.import_folders([folder]):
        return fail("이미 가져오기가 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
    return ok(folder=folder)


@app.post("/api/rescan")
def api_rescan():
    if not importer.rescan_all():
        return fail("이미 가져오기가 진행 중입니다.")
    return ok()


@app.get("/api/import/status")
def import_status():
    return ok(**importer.status)


@app.post("/api/upload")
def upload():
    files = request.files.getlist("files")
    saved = []
    for f in files:
        name = os.path.basename(f.filename or "")
        if not name.lower().endswith(".pdf"):
            continue
        dest = paths.UPLOAD_DIR / name
        stem, n = dest.stem, 1
        while dest.exists():
            dest = paths.UPLOAD_DIR / f"{stem} ({n}).pdf"
            n += 1
        f.save(dest)
        saved.append(str(dest))
    if not saved:
        return fail("PDF 파일이 없습니다.")
    if not importer.import_folders([str(paths.UPLOAD_DIR)]):
        return ok(saved=len(saved), note="다른 가져오기가 끝나면 '새 파일 확인'을 눌러 주세요.")
    return ok(saved=len(saved))


@app.post("/api/sources/remove")
def remove_source():
    path = (request.json or {}).get("path", "")
    n = store.remove_source(path, drop_documents=True)
    return ok(removed=n)


@app.post("/api/open-folder")
def open_folder():
    which = (request.json or {}).get("which", "inbox")
    target = {"inbox": paths.INBOX_DIR, "organized": paths.ORGANIZED_DIR, "data": paths.DATA_DIR}.get(which)
    if target is None:
        return fail("알 수 없는 폴더")
    target.mkdir(parents=True, exist_ok=True)
    _open_in_os(str(target))
    return ok(path=str(target))


def _open_in_os(p):
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


# ---------------------------------------------------------------- 문서

@app.get("/api/documents")
def documents():
    a = request.args
    docs = store.list_documents(category=a.get("category") or None, name=a.get("name") or None,
                                scanned=a.get("scanned") == "1", sort=a.get("sort", "recent"))
    return ok(documents=docs)


@app.get("/api/documents/<int:doc_id>")
def document(doc_id):
    d = store.get_document(doc_id)
    if not d:
        return fail("문서를 찾을 수 없습니다.", 404)
    d["exists"] = os.path.exists(d["path"])
    return ok(document=d)


@app.post("/api/documents/<int:doc_id>/category")
def change_category(doc_id):
    cat = ((request.json or {}).get("category") or "").strip()
    if not cat:
        return fail("분류를 골라 주세요.")
    store.set_category(doc_id, cat)
    return ok()


@app.get("/api/documents/<int:doc_id>/summary")
def local_summary(doc_id):
    pages = store.document_text(doc_id)
    full = "\n".join(pages)
    if len(full.strip()) < 30:
        return fail("글자가 없는 문서(스캔본)라 요약할 수 없습니다.")
    sents = textutil.extractive_summary(full, n=6)
    # 문장이 몇 쪽에 있는지 찾아 붙이기
    out = []
    for s in sents:
        page = next((i + 1 for i, t in enumerate(pages) if s[:25] in " ".join(t.split())), None)
        out.append({"sentence": s, "page": page})
    return ok(sentences=out, keywords=textutil.top_keywords(full, 12), dates=textutil.find_dates(full, 10))


@app.post("/api/documents/<int:doc_id>/ai-summary")
def ai_summary(doc_id):
    d = store.get_document(doc_id)
    if not d:
        return fail("문서를 찾을 수 없습니다.", 404)
    if d["chars"] < 30:
        return fail("글자가 없는 스캔본입니다. 먼저 'AI로 글자 읽기'를 해 주세요.")
    try:
        text = ai.summarize_document(d["filename"], d["page_texts"])
    except ai.AIError as e:
        return fail(str(e))
    store.set_ai_summary(doc_id, text)
    return ok(summary=text)


@app.post("/api/documents/<int:doc_id>/ai-ocr")
def ai_ocr(doc_id):
    d = store.get_document(doc_id, with_pages=False)
    if not d:
        return fail("문서를 찾을 수 없습니다.", 404)
    if not os.path.exists(d["path"]):
        return fail("원본 파일이 옮겨졌거나 지워졌습니다.")
    try:
        pages = ai.read_scanned_pdf(d["path"])
    except ai.AIError as e:
        return fail(str(e))
    store.replace_pages(doc_id, pages, text_source="ai")
    return ok(pages=len(pages))


@app.get("/api/file/<int:doc_id>")
def open_file(doc_id):
    d = store.get_document(doc_id, with_pages=False)
    if not d or not os.path.exists(d["path"]):
        return fail("원본 파일이 옮겨졌거나 지워졌습니다.", 404)
    return send_file(d["path"], mimetype="application/pdf", download_name=d["filename"])


# ---------------------------------------------------------------- 검색·분석·질문

@app.get("/api/search")
def search():
    a = request.args
    res = store.search(a.get("q", ""), category=a.get("category") or None,
                       require_all=a.get("mode", "all") == "all")
    return ok(**res)


@app.get("/api/keywords")
def keywords():
    return ok(keywords=store.keyword_stats(request.args.get("category") or None))


@app.post("/api/ask")
def ask():
    q = ((request.json or {}).get("question") or "").strip()
    if not q:
        return fail("질문을 입력해 주세요.")
    terms = textutil.query_terms(q) or q.split()
    res = store.search("", terms=terms, require_all=False, limit=6)
    contexts, sources = [], []
    for r in res["results"]:
        page_nos = [h["page"] for h in r["hits"][:3]]
        for p, t in store.pages_for_context(r["id"], page_nos):
            contexts.append((r["filename"], p, t))
        sources.append({"id": r["id"], "filename": r["filename"], "pages": page_nos, "hits": r["hits"][:3],
                        "category": r["category"]})
    if not ai.enabled():
        return ok(mode="offline", terms=terms, answer=None, sources=sources)
    if not contexts:
        return ok(mode="ai", terms=terms, answer="관련 자료를 찾지 못했습니다. 다른 단어로 질문해 보세요.",
                  sources=[])
    try:
        answer = ai.answer_question(q, contexts)
    except ai.AIError as e:
        return ok(mode="offline", terms=terms, answer=None, sources=sources, ai_error=str(e))
    return ok(mode="ai", terms=terms, answer=answer, sources=sources)


@app.get("/api/export/documents.csv")
def export_csv():
    docs = store.list_documents(sort="name")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["번호", "파일명", "분류", "문서 날짜", "쪽수", "글자수", "스캔본", "주요 단어", "폴더", "전체 경로"])
    for i, d in enumerate(docs, 1):
        w.writerow([i, d["filename"], d["category"], d["doc_date"] or "", d["pages"], d["chars"],
                    "예" if d["is_scanned"] else "", ", ".join(d["keywords"][:10]), d["folder"], d["path"]])
    data = "﻿" + buf.getvalue()  # 엑셀에서 한글이 깨지지 않도록 BOM 추가
    return Response(data.encode("utf-8"), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%EB%AC%B8%EC%84%9C%EB%AA%A9%EB%A1%9D.csv"})


@app.post("/api/organize")
def organize():
    """분류 결과대로 '분류별_정리' 폴더에 PDF 사본을 만듭니다. 원본은 건드리지 않습니다."""
    copied, missing = 0, 0
    for d in store.list_documents():
        if not os.path.exists(d["path"]):
            missing += 1
            continue
        safe_cat = "".join(c for c in d["category"] if c not in '<>:"/\\|?*')
        dest_dir = paths.ORGANIZED_DIR / safe_cat
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / d["filename"]
        if dest.exists() and dest.stat().st_size == d["size"]:
            continue
        stem, n = dest.stem, 1
        while dest.exists():
            dest = dest_dir / f"{stem} ({n}).pdf"
            n += 1
        shutil.copy2(d["path"], dest)
        copied += 1
    _open_in_os(str(paths.ORGANIZED_DIR))
    return ok(copied=copied, missing=missing, path=str(paths.ORGANIZED_DIR))


# ---------------------------------------------------------------- 설정

@app.get("/api/settings")
def get_settings():
    return ok(ai_enabled=ai.enabled(), key_masked=ai.masked_key(), model=ai.model(), models=ai.MODELS,
              categories=store.load_categories(), data_dir=str(paths.DATA_DIR))


@app.post("/api/settings/ai")
def set_ai():
    body = request.json or {}
    if body.get("clear"):
        ai.save_settings(api_key="")
        return ok(ai_enabled=ai.enabled())
    if "model" in body:
        ai.save_settings(model=body["model"])
    key = (body.get("api_key") or "").strip()
    previous = ai.load_settings().get("api_key", "")
    if key:
        ai.save_settings(api_key=key)
    if body.get("test"):
        try:
            ai.test_key()
        except ai.AIError as e:
            if key:
                ai.save_settings(api_key=previous)  # 확인에 실패한 키는 저장하지 않음
            return fail(str(e))
    return ok(ai_enabled=ai.enabled(), key_masked=ai.masked_key())


@app.post("/api/settings/categories")
def set_categories():
    cats = (request.json or {}).get("categories") or []
    clean = []
    for c in cats:
        name = (c.get("name") or "").strip()
        kws = [k.strip() for k in c.get("keywords", []) if k.strip()]
        if name and name != "미분류":
            clean.append({"name": name, "keywords": kws})
    if not clean:
        return fail("분류를 하나 이상 입력해 주세요.")
    store.save_categories(clean)
    changed = store.reclassify_all()
    return ok(changed=changed)


@app.post("/api/settings/categories/reset")
def reset_categories():
    shutil.copy(paths.DEFAULT_CATEGORIES_PATH, paths.CATEGORIES_PATH)
    return ok(changed=store.reclassify_all())


# ---------------------------------------------------------------- 실행

def already_running():
    """이미 켜져 있으면 그 주소를 돌려줍니다(두 번 실행해도 창만 다시 열기)."""
    try:
        info = json.loads(paths.SERVER_INFO.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{info['port']}"
        with urllib.request.urlopen(url + "/api/ping", timeout=1.5) as r:
            if b"pdf-search-app" in r.read():
                return url
    except Exception:
        pass
    return None


def free_port(preferred=8765):
    for port in [preferred] + list(range(8766, 8800)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    paths.ensure_dirs()
    url = already_running()
    if url:
        print(f"이미 실행 중입니다. 브라우저에서 엽니다: {url}")
        webbrowser.open(url)
        return

    store.init()
    port = int(os.environ.get("PDFDB_PORT") or free_port())
    paths.SERVER_INFO.write_text(json.dumps({"port": port}), encoding="utf-8")
    url = f"http://127.0.0.1:{port}"

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    try:
        import flask.cli
        flask.cli.show_server_banner = lambda *a, **k: None
    except Exception:
        pass

    line = "=" * 60
    print(line)
    print(f"  PDF 자료 검색기 {VERSION}")
    print(f"  주소: {url}")
    print(f"  PDF 넣는 곳: {paths.INBOX_DIR}")
    print(f"  AI 기능: {'켜짐' if ai.enabled() else '꺼짐 (Python만으로 동작)'}")
    print("  이 창을 닫으면 프로그램이 종료됩니다.")
    print(line)

    importer.rescan_all()  # 등록된 폴더의 새 파일·바뀐 파일을 자동 반영
    if os.environ.get("PDFDB_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
