"""인터넷 없이 Python만으로 하는 글자 처리: 날짜 찾기, 자주 나오는 단어, 간단 요약."""
import math
import re
from collections import Counter

# 한국어 조사·어미를 대충 떼어 내기 위한 목록 (긴 것부터 검사)
_SUFFIXES = sorted("""
이었나요 였나요 었나요 인가요 습니까 입니까 하였는지 하였으며 되었으며 하였다 하여야 되었다 이었다 하는지 나요 인지 는지 였다 었다
으로부터 에서부터 에게서 이라는 으로는 으로서 으로써 에서는 에서도 에게는 까지는 이라고 라고
에서 에게 으로 부터 까지 이라 하는 하여 하고 하며 하였 했다 한다 된다 되는 되어 됩니다 합니다 입니다
있는 있다 없는 없다 이나 이며 와의 과의 에는 에도 로서 로써 보다 처럼 마다 이고
은 는 이 가 을 를 의 에 와 과 도 만 로 께 나 며 고
""".split(), key=len, reverse=True)

STOPWORDS = set("""
있다 있는 없는 없다 하는 한다 된다 되는 대한 위한 관한 따라 경우 그리고 또는 및 등 이를 이에 그 이 저 것 수 때
해당 관련 통해 위해 대하여 관하여 따른 의한 의하여 같은 다음 각 동 본 위 아래 기타 사항 내용 부분 이상 이하 이내
합니다 있습니다 됩니다 입니다 하였습니다 하였다 하여 하고 하며 그러나 다만 또한 이후 이전 현재 당시 관련하여
등의 따른다 대해 있으며 없이 모든 어느 이번 해당하는 경우에는
페이지 page the and for of to in on is are with by this that from
""".split())

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9\-]{2,}")
_DATE_RE = re.compile(r"(19[89]\d|20[0-4]\d)\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def find_dates(text, limit=20):
    """본문에서 2023. 3. 15 / 2023-03-15 / 2023년 3월 15일 형태의 날짜를 찾습니다."""
    out = []
    for m in _DATE_RE.finditer(text or ""):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            s = f"{y:04d}-{mo:02d}-{d:02d}"
            if s not in out:
                out.append(s)
            if len(out) >= limit:
                break
    return out


def strip_suffix(word):
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            return word[: -len(suf)]
    return word


def tokens(text):
    out = []
    for raw in _TOKEN_RE.findall(text or ""):
        w = strip_suffix(raw) if raw[0] >= "가" else raw.lower()
        if 2 <= len(w) <= 15 and w not in STOPWORDS and not w.isdigit():
            out.append(w)
    return out


def top_keywords(text, n=15):
    return [w for w, _ in Counter(tokens(text)).most_common(n)]


def query_terms(question):
    """자연어 질문에서 검색에 쓸 단어를 뽑습니다."""
    seen = []
    for w in tokens(question):
        if w not in seen and w not in {"알려", "알려줘", "무엇", "어떤", "어떻게", "정리", "요약", "찾아", "주세요"}:
            seen.append(w)
    return seen[:8]


_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)|\n{1,}")


def split_sentences(text):
    sents = []
    for s in _SENT_SPLIT.split(text or ""):
        s = re.sub(r"\s+", " ", s).strip()
        if 15 <= len(s) <= 400:
            sents.append(s)
    return sents


def extractive_summary(text, n=6):
    """AI 없이 만드는 요약: 문서 전체에서 중요한 단어가 많이 들어간 문장을 골라 원래 순서대로 보여 줍니다.
    원문 문장을 그대로 가져오므로 표현이 바뀌지 않습니다."""
    sents = split_sentences(text)
    if len(sents) < n:  # 짧은 문서: 줄 단위로 보충
        for line in (text or "").splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) >= 8 and line not in sents:
                sents.append(line)
    if not sents:
        return []
    freq = Counter(tokens(text))
    if not freq:
        return sents[:n]
    top = dict(freq.most_common(40))
    scored = []
    for i, s in enumerate(sents):
        toks = tokens(s)
        if not toks:
            continue
        score = sum(top.get(t, 0) for t in toks) / math.sqrt(len(toks))
        if i < 3:  # 앞부분 문장(제목·개요)에 약간 가산점
            score *= 1.15
        scored.append((score, i, s))
    best = sorted(scored, reverse=True)[:n]
    chosen, seen = [], set()
    for _, i, s in sorted(best, key=lambda x: x[1]):
        if s not in seen:
            chosen.append(s)
            seen.add(s)
    return chosen


def snippet(text, terms, before=60, after=140):
    """검색어가 처음 나오는 곳 주변의 글을 잘라 냅니다."""
    flat = re.sub(r"\s+", " ", text or "")
    low = flat.lower()
    pos = -1
    for t in terms:
        p = low.find(t.lower())
        if p >= 0 and (pos < 0 or p < pos):
            pos = p
    if pos < 0:
        return flat[: before + after]
    start = max(0, pos - before)
    end = min(len(flat), pos + after)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")
