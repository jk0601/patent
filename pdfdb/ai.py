"""외부 AI(Anthropic Claude) 연결. 설정에서 API 키를 넣었을 때만 사용합니다.
키가 없으면 이 파일의 기능은 쓰이지 않고, 프로그램은 Python만으로 동작합니다."""
import json
import os
import re

from . import paths

MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5 (가장 정확, 기본값)"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 (빠르고 저렴)"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5 (가장 저렴)"},
]
DEFAULT_MODEL = "claude-opus-5-5"
MAX_DOC_CHARS = 150_000  # 문서 요약 때 AI에 보내는 최대 글자 수

SYSTEM_RULES = """당신은 변리사협회 회원지원실 직원을 돕는 문서 정리 도우미입니다. 다음 원칙을 반드시 지킵니다.
1. 제공된 자료에 근거가 있는 내용만 씁니다. 자료에 없으면 "자료에서 확인되지 않음"이라고 씁니다.
2. 추정이 필요한 경우 문장 앞에 [추정]이라고 표시합니다.
3. 사실관계·날짜·금액·조항 번호·당사자 표현은 원문 표현을 그대로 씁니다. 과장하거나 바꾸어 말하지 않습니다.
4. 근거가 된 문서 이름과 쪽 번호를 (파일명 p.쪽) 형태로 붙입니다.
5. 한국어로, 실무자가 바로 쓸 수 있게 간결하게 씁니다."""


class AIError(Exception):
    pass


# ---------------------------------------------------------------- 설정

def load_settings():
    try:
        return json.loads(paths.SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(**kw):
    s = load_settings()
    s.update(kw)
    paths.SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def api_key():
    return (load_settings().get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def model():
    m = load_settings().get("model") or DEFAULT_MODEL
    return m if any(x["id"] == m for x in MODELS) else DEFAULT_MODEL


def enabled():
    return bool(api_key())


def masked_key():
    k = api_key()
    return (k[:7] + "…" + k[-4:]) if len(k) > 12 else ("설정됨" if k else "")


# ---------------------------------------------------------------- 호출

def _call(content, system=SYSTEM_RULES, max_tokens=16000):
    key = api_key()
    if not key:
        raise AIError("AI 키가 설정되지 않았습니다. 설정 화면에서 키를 넣어 주세요.")
    try:
        import anthropic
    except ImportError:
        raise AIError("anthropic 패키지가 설치되지 않았습니다. 시작 파일을 다시 실행해 주세요.")

    client = anthropic.Anthropic(api_key=key, timeout=600, max_retries=2)
    m = model()
    kwargs = dict(model=m, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": content}])
    try:
        try:
            # AI가 안전 정책으로 답을 거절하면 서버가 다른 모델로 자동 재시도하도록 요청 (Haiku는 미지원)
            extra = {} if "haiku" in m else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            with client.beta.messages.stream(**kwargs, **extra) as s:
                resp = s.get_final_message()
        except TypeError:  # 오래된 anthropic 패키지
            with client.messages.stream(**kwargs) as s:
                resp = s.get_final_message()
    except anthropic.AuthenticationError:
        raise AIError("AI 키가 올바르지 않습니다. 설정 화면에서 키를 확인해 주세요.")
    except anthropic.PermissionDeniedError:
        raise AIError("이 키로는 선택한 AI 모델을 쓸 수 없습니다. 다른 모델을 골라 보세요.")
    except anthropic.RateLimitError:
        raise AIError("AI 사용량 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.")
    except anthropic.APIConnectionError:
        raise AIError("AI 서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.")
    except anthropic.APIStatusError as e:
        raise AIError(f"AI 요청이 실패했습니다 (코드 {e.status_code}): {str(e)[:300]}")

    if resp.stop_reason == "refusal":
        raise AIError("AI가 이 요청에 답하지 않았습니다. 내용을 나누어 다시 시도해 보세요.")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    if resp.stop_reason == "max_tokens":
        text += "\n\n(답변이 길어 중간에 끊겼습니다.)"
    return text


def test_key():
    return _call("연결 확인입니다. '연결 성공'이라고만 답하세요.", system="짧게 답합니다.", max_tokens=200)


def summarize_document(filename, page_texts):
    joined, used = [], 0
    truncated = False
    for i, t in enumerate(page_texts, 1):
        block = f"\n--- p.{i} ---\n{t}"
        if used + len(block) > MAX_DOC_CHARS:
            truncated = True
            break
        joined.append(block)
        used += len(block)
    prompt = (
        f"아래는 '{filename}' 문서의 본문입니다(쪽 구분 표시 포함).\n"
        "다음 형식으로 정리해 주세요.\n"
        "## 한 줄 요약\n## 핵심 내용 (5개 이내, 각 항목 끝에 쪽 번호)\n"
        "## 등장 당사자·기관\n## 주요 날짜·기한\n## 관련 법령·조항\n## 확인이 필요한 점\n"
        "해당 내용이 없는 항목은 '없음'이라고 씁니다.\n\n<문서>" + "".join(joined) + "\n</문서>"
    )
    text = _call(prompt)
    if truncated:
        text = (f"※ 문서가 길어 앞부분 {len(joined)}쪽(약 {used:,}자)까지만 AI에 보내 요약했습니다.\n\n" + text)
    return text


def answer_question(question, contexts):
    """contexts: [(파일명, 쪽, 본문)] 검색으로 찾은 관련 대목."""
    blocks = "\n\n".join(f"<자료 파일='{fn}' 쪽='{p}'>\n{t}\n</자료>" for fn, p, t in contexts)
    prompt = (
        "아래 자료는 직원 PC의 PDF에서 검색으로 찾은 관련 대목입니다. 자료만 근거로 질문에 답하세요. "
        "자료로 답할 수 없으면 그렇다고 분명히 쓰고, 어떤 자료가 더 필요한지 적으세요.\n\n"
        f"{blocks}\n\n질문: {question}"
    )
    return _call(prompt)


def read_scanned_pdf(pdf_path):
    """글자가 없는 스캔본 PDF를 AI가 읽어 쪽별 글자로 돌려줍니다."""
    import base64
    size = os.path.getsize(pdf_path)
    if size > 30 * 1024 * 1024:
        raise AIError("파일이 30MB보다 커서 AI로 읽을 수 없습니다. PDF를 나누어 주세요.")
    data = base64.standard_b64encode(open(pdf_path, "rb").read()).decode("ascii")
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
        {"type": "text", "text": (
            "이 PDF는 스캔본입니다. 모든 쪽의 글자를 빠짐없이 그대로 옮겨 적어 주세요. 요약하거나 고치지 마세요. "
            "각 쪽은 반드시 '=== 페이지 N ===' 줄로 시작합니다. 읽을 수 없는 부분은 [판독 불가]로 표시합니다.")},
    ]
    text = _call(content, system="당신은 문서의 글자를 정확히 옮겨 적는 도우미입니다.", max_tokens=64000)
    parts = re.split(r"^=== ?페이지 ?(\d+) ?===\s*$", text, flags=re.M)
    pages = {}
    for i in range(1, len(parts) - 1, 2):
        pages[int(parts[i])] = parts[i + 1].strip()
    if not pages:
        return [text]
    return [pages.get(n, "") for n in range(1, max(pages) + 1)]
