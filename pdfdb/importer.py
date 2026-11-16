"""PDF 폴더를 훑어서 글자를 뽑아 DB에 넣습니다. 이미 넣은 파일은 바뀌지 않았으면 건너뜁니다."""
import os
import threading
import time
from pathlib import Path

from . import paths, store

try:
    import pymupdf  # PyMuPDF 1.24 이상
except ImportError:  # 예전 이름
    import fitz as pymupdf

_lock = threading.Lock()
status = {
    "running": False, "phase": "", "total": 0, "done": 0, "current": "",
    "added": 0, "updated": 0, "skipped": 0, "removed": 0, "scanned": 0,
    "failed": [], "finished_at": None, "message": "",
}


def extract_pages(path):
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise ValueError("PDF로 열 수 없습니다. 파일이 손상되었거나 PDF가 아닙니다")
    with doc:
        if doc.needs_pass:
            raise ValueError("암호가 걸린 PDF라 열 수 없습니다")
        out = []
        for page in doc:
            t = page.get_text("text") or ""
            out.append(t.replace("\x00", "").strip())
        if not out:
            raise ValueError("쪽이 하나도 없습니다. 손상된 PDF일 수 있습니다")
        return out


def find_pdfs(folder):
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__",)]
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("~$"):
                found.append(os.path.join(root, f))
    return found


def _norm(p):
    return str(Path(p).resolve())


def import_folders(folders, remove_missing=True):
    """폴더들을 가져옵니다. 이미 다른 작업이 돌고 있으면 False."""
    if not _lock.acquire(blocking=False):
        return False
    threading.Thread(target=_run, args=(folders, remove_missing), daemon=True).start()
    return True


def _run(folders, remove_missing):
    try:
        status.update(running=True, phase="파일 찾는 중", total=0, done=0, current="", added=0, updated=0,
                      skipped=0, removed=0, scanned=0, failed=[], finished_at=None, message="")
        files = []
        for f in folders:
            if os.path.isdir(f):
                files.extend(find_pdfs(f))
            elif os.path.isfile(f) and f.lower().endswith(".pdf"):
                files.append(f)
        files = sorted({_norm(f) for f in files})
        status.update(total=len(files), phase="글자 뽑는 중")

        with store.connect() as con:
            known = {r["path"]: r for r in con.execute("SELECT id, path, size, mtime FROM documents")}

        for i, f in enumerate(files):
            status.update(done=i, current=os.path.basename(f))
            try:
                st = os.stat(f)
                old = known.get(f)
                if old and old["size"] == st.st_size and abs((old["mtime"] or 0) - st.st_mtime) < 1:
                    status["skipped"] += 1
                    continue
                pages = extract_pages(f)
                store.save_document(f, os.path.basename(f), os.path.dirname(f), st.st_size, st.st_mtime, pages)
                total_chars = sum(len(p) for p in pages)
                if pages and total_chars < 30 * len(pages):
                    status["scanned"] += 1
                status["updated" if old else "added"] += 1
            except Exception as e:  # 깨진 파일 등은 기록만 하고 계속
                status["failed"].append({"file": os.path.basename(f), "path": f, "reason": str(e)[:200]})
        status["done"] = len(files)

        if remove_missing:
            status["phase"] = "지워진 파일 정리 중"
            roots = [_norm(f) for f in folders if os.path.isdir(f)]
            for path, row in known.items():
                if any(path.startswith(r) for r in roots) and not os.path.exists(path):
                    store.delete_document(row["id"])
                    status["removed"] += 1

        parts = [f"새로 추가 {status['added']}건", f"갱신 {status['updated']}건", f"그대로 {status['skipped']}건"]
        if status["removed"]:
            parts.append(f"삭제된 파일 정리 {status['removed']}건")
        if status["scanned"]:
            parts.append(f"스캔본(글자 없음) {status['scanned']}건")
        if status["failed"]:
            parts.append(f"실패 {len(status['failed'])}건")
        status["message"] = ", ".join(parts)
    except Exception as e:
        status["message"] = f"가져오기 중 오류: {e}"
    finally:
        status.update(running=False, phase="완료", current="", finished_at=time.strftime("%H:%M:%S"))
        _lock.release()


def rescan_all():
    """등록된 모든 폴더(+ PDF넣는곳, 업로드 폴더)를 다시 훑어 새 파일·바뀐 파일만 반영합니다."""
    folders = [s["path"] for s in store.list_sources()]
    for extra in (str(paths.INBOX_DIR), str(paths.UPLOAD_DIR)):
        if extra not in folders:
            folders.append(extra)
    return import_folders([f for f in folders if os.path.isdir(f)])
