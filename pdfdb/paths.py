"""프로그램이 쓰는 폴더 위치를 한곳에서 정합니다. 모두 프로그램 폴더 안에 만들어집니다."""
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"                # DB, 설정, 업로드한 파일
DB_PATH = DATA_DIR / "pdf_db.sqlite3"
SETTINGS_PATH = DATA_DIR / "settings.json"
CATEGORIES_PATH = DATA_DIR / "categories.json"
DEFAULT_CATEGORIES_PATH = APP_DIR / "default_categories.json"
UPLOAD_DIR = DATA_DIR / "uploaded"         # 웹 화면에서 끌어다 놓은 PDF 보관
INBOX_DIR = APP_DIR / "PDF넣는곳"           # 여기에 PDF를 넣으면 자동으로 들어감
ORGANIZED_DIR = APP_DIR / "분류별_정리"      # '분류별 폴더로 정리' 결과
SERVER_INFO = DATA_DIR / "server.json"     # 실행 중인 포트 기록


def ensure_dirs():
    for d in (DATA_DIR, UPLOAD_DIR, INBOX_DIR):
        d.mkdir(parents=True, exist_ok=True)
