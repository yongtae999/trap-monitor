import hashlib
import html
import json
import logging
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup, UnicodeDammit
from dotenv import load_dotenv

try:
    from google.cloud import discoveryengine_v1beta as discoveryengine
    GOOGLE_SDK_AVAILABLE = True
except ImportError:
    GOOGLE_SDK_AVAILABLE = False


load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

DB_FILE = os.path.join(DATA_DIR, "scraped_data.json")
LAST_RUN_FILE = os.path.join(DATA_DIR, "last_run.json")
SELLER_MASTER_FILE = os.path.join(DATA_DIR, "seller_master.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "scraper.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
VERTEX_DATA_STORE_ID = os.getenv("VERTEX_DATA_STORE_ID")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
ENABLE_GOOGLE_VERTEX = os.getenv("ENABLE_GOOGLE_VERTEX", "false").lower() in {"1", "true", "yes", "on"}
SOURCE_HEALTH = {}

# 네이버 개발자센터의 쇼핑 검색 API는 2026-07-31 종료되어 더 이상 호출하지 않습니다.
NAVER_SHOPPING_API_RETIRED = True

KEYWORDS = ["올무", "스프링올무", "창애", "멧돼지 포획틀", "너구리 포획틀", "야생동물 포획기"]

# 유료 검색원을 사용하지 않고 기존 네이버 검색 API 범위 안에서 매일 핵심 검색과
# 순환 탐색을 병행합니다. 전체 조합을 한 번에 호출하지 않아 실행시간과 중복을 줄입니다.
CORE_WEB_QUERIES = [
    ("올무 판매", "올무"),
    ("스프링 올무 판매", "스프링 올무"),
    ("와이어 올무 판매", "와이어 올무"),
    ("발목덫 판매", "발목덫"),
    ("발판덫 판매", "발판덫"),
    ("창애 덫 판매", "창애"),
    ("멧돼지 포획틀", "멧돼지 포획틀"),
    ("고라니 포획틀", "고라니 포획틀"),
    ("너구리 포획틀", "너구리 포획틀"),
    ("야생동물 포획기 판매", "야생동물 포획기"),
    ("생포틀 판매", "생포틀"),
    ("동물 트랩 판매", "동물 트랩"),
]

COMMUNITY_QUERIES = [
    ("올무 팝니다", "올무"),
    ("스프링 올무 판매합니다", "스프링 올무"),
    ("와이어 올무 판매", "와이어 올무"),
    ("발목덫 팝니다", "발목덫"),
    ("포획틀 주문제작", "포획틀"),
    ("포획틀 중고 판매", "포획틀"),
    ("야생동물 포획기 판매", "야생동물 포획기"),
]

TARGET_SITE_DOMAINS = [
    "daangn.com", "bunjang.co.kr", "joongna.com", "hellomarket.com",
    "11st.co.kr", "gmarket.co.kr", "auction.co.kr", "coupang.com",
    "smartstore.naver.com",
]

DISCOVERY_PAGE_TYPES = {"search", "category", "seller_profile", "catalog", "article", "listing_post"}
STRONG_SALE_SIGNALS = [
    "팝니다", "판매합니다", "판매 중", "판매중", "주문제작", "구매문의",
    "직거래", "택배거래", "가격", "원에 판매", "연락주세요", "문의주세요",
]

TRAP_TERMS = [
    "스프링올무", "스프링 올무", "와이어올무", "와이어 올무", "발목덫", "발목 덫",
    "발판덫", "발판 덫", "올무", "창애", "생포틀", "포획틀", "포획 틀", "포획기",
    "야생동물 트랩", "동물 트랩",
]

SALE_SIGNALS = [
    "판매", "구매", "주문", "상품", "가격", "배송", "장바구니", "구입", "최저가",
    "원", "무료배송", "재고", "새상품", "중고", "팝니다",
]

BAD_TITLE_WORDS = [
    "책", "도서", "장난감", "피규어", "식품", "즙", "건강", "효능", "요리", "레시피",
    "반찬", "식당", "맛집", "게임", "동화", "소설", "분석기", "검출기", "계측기",
    "센서", "농도", "함량", "질소", "산소", "비료", "퇴비", "씨앗", "종자", "새장",
    "애완", "반려", "낚시", "어망", "그물망", "방조망", "tester", "sensor", "analyzer",
    "detector", "블라인드", "커튼", "창틀", "빗물차단", "방충망", "태양광", "초음파",
]

BAD_CATEGORIES = [
    "식품", "도서", "여가/생활편의", "출산/육아", "화장품/미용", "가구/인테리어",
    "의류", "잡화", "음반", "e-book", "패션", "디지털/가전", "건강식품", "의료용품",
]

BAD_EXACT_WORDS = {"책", "도서", "즙", "식품", "식당", "맛집", "게임", "동화", "소설"}

NON_DETAIL_PATTERNS = [
    ("search", re.compile(r"(?:/search(?:/|\?|$)|/keywords?/|[?&](?:q|query|keyword|kwd)=)", re.I)),
    ("category", re.compile(r"(?:/category/|/categories/|/best(?:/|\?|$)|/catalogs?/)", re.I)),
    ("seller_profile", re.compile(r"(?:/users?/|/seller/|/sellers/|/store/|/stores/)", re.I)),
]

DETAIL_PATTERNS = [
    re.compile(r"11st\.co\.kr/products?/\d+", re.I),
    re.compile(r"gmarket\.co\.kr/(?:vi/)?(?:item|product)/\d+", re.I),
    re.compile(r"[?&]goodscode=\d+", re.I),
    re.compile(r"auction\.co\.kr/.+?[?&](?:itemno|item)=", re.I),
    re.compile(r"smartstore\.naver\.com/[^/]+/products/\d+", re.I),
    re.compile(r"daangn\.com/(?:kr/)?articles?/\d+", re.I),
    re.compile(r"bunjang\.co\.kr/products?/\d+", re.I),
    re.compile(r"joongna\.com/products?/\d+", re.I),
    re.compile(r"hellomarket\.com/items?/\d+", re.I),
    re.compile(r"daangn\.com/(?:kr/)?buy-sell/", re.I),
    re.compile(r"coupang\.com/vp/products?/\d+", re.I),
    re.compile(r"/(?:shop_view|(?:m_)?mall_detail)(?:\.php)?(?:[/?#]|$)", re.I),
    re.compile(r"/shop/(?:item|view)\.php", re.I),
    re.compile(r"/(?:goods|products?|items?)/(?:view/)?[^/?]+", re.I),
    re.compile(r"[?&]act=shop\.goods_view(?:&|$)", re.I),
]

TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "referrer",
    "source", "NaPm", "n_media", "n_query", "n_rank", "n_ad_group", "n_ad", "n_campaign_type",
}

STATUS_VALUES = {"candidate", "confirmed", "rejected", "auto_rejected", "deleted"}

HIGH_RISK_TERMS = [
    "스프링올무", "스프링 올무", "와이어올무", "와이어 올무", "발목덫", "발목 덫",
    "발판덫", "발판 덫", "올무", "창애", "올가미",
]
MEDIUM_RISK_TERMS = [
    "포획틀", "포획 틀", "포획기", "생포틀", "덫", "트랩", "케이지", "철망",
]
NON_WILDLIFE_CONTEXT_TERMS = [
    "tnr", "중성화", "길고양이", "유기묘", "유기견", "고양이 구조", "강아지 구조",
    "고양이포획", "고양이 포획", "고양이망", "동물구조", "동물 구조", "마우스",
    "쥐덫", "쥐트랩", "쥐포획", "두더지", "해충", "노린재", "사슴벌레", "곤충채집",
    "등화채집", "비둘기", "까마귀", "참새", "새 포획", "조류 포획",
]
WILDLIFE_TARGET_TERMS = [
    "멧돼지", "고라니", "너구리", "오소리", "뉴트리아", "족제비",
    "야생동물", "야생 동물", "들짐승", "유해조수", "유해동물",
]
SPECIFIC_WILDLIFE_TARGET_TERMS = [
    "멧돼지", "고라니", "너구리", "오소리", "뉴트리아", "족제비", "들짐승",
]


def _update_source_health(
    source: str,
    status: str,
    found: int = 0,
    error: str = "",
    queries: int = 0,
    discovered: int = 0,
) -> None:
    current = SOURCE_HEALTH.setdefault(
        source,
        {"status": status, "found": 0, "queries": 0, "discovered": 0, "error": ""},
    )
    current["found"] += found
    current["queries"] += queries
    current["discovered"] += discovered
    if status == "error":
        current["status"] = "error"
        current["error"] = error
    elif status == "skipped":
        current["status"] = "skipped"
        current["error"] = error
    elif current.get("status") != "error":
        current["status"] = status


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_text(value: str) -> str:
    value = html.unescape(str(value or ""))
    if "<" in value and ">" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", value).strip()


def _exact_term_in_text(text: str, term: str) -> bool:
    text = str(text or "").lower()
    term = str(term or "").lower()
    return bool(re.search(rf"(?<![가-힣a-z0-9]){re.escape(term)}(?![가-힣a-z0-9])", text, re.I))


def _term_in_text(text: str, term: str) -> bool:
    text = str(text or "").lower()
    term = str(term or "").lower()
    if term in {"올무", "창애"}:
        return _exact_term_in_text(text, term)
    return term in text


def _matching_trap_terms(text: str) -> list[str]:
    normalized = str(text or "").lower()
    matched = [term for term in TRAP_TERMS if _term_in_text(normalized, term)]
    # '창애'는 상호·인명·도서명에도 쓰이므로 동물 포획 문맥이 있을 때만 엽구로 봅니다.
    if "창애" in matched and not any(
        signal in normalized
        for signal in ("덫", "올무", "포획", "사냥", "트랩", "야생동물", "멧돼지", "고라니", "너구리")
    ):
        matched.remove("창애")
    return matched


def _looks_like_community_listing(record: dict) -> bool:
    """보도·안내 글과 실제 개인 판매글을 구분하는 보수적인 규칙입니다."""
    text = f"{_clean_text(record.get('title', ''))} {_clean_text(record.get('description') or record.get('snippet', ''))}".lower()
    if not _matching_trap_terms(text):
        return False
    has_strong_signal = any(signal in text for signal in STRONG_SALE_SIGNALS)
    has_price = bool(re.search(r"(?:^|\s)\d{1,3}(?:,\d{3})+\s*원(?:\s|$)", text))
    has_contact = bool(re.search(r"(?:0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}|01[016789][- .]?\d{3,4}[- .]?\d{4})", text))
    return has_strong_signal or has_price or has_contact


def _safe_url(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    return ""


def infer_platform(url: str, fallback: str = "") -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "11st.co.kr" in host:
        return "11번가"
    if "gmarket.co.kr" in host:
        return "G마켓"
    if "auction.co.kr" in host:
        return "옥션"
    if "smartstore.naver.com" in host or "shopping.naver.com" in host:
        return "네이버쇼핑"
    if "bunjang.co.kr" in host:
        return "번개장터"
    if "daangn.com" in host:
        return "당근"
    if "joongna.com" in host:
        return "중고나라"
    if "hellomarket.com" in host:
        return "헬로마켓"
    if "coupang.com" in host:
        return "쿠팡"
    if "shoppinghow.kakao.com" in host:
        return "카카오 쇼핑하우"
    return fallback or host or "알 수 없음"


def infer_page_type(url: str) -> str:
    lower = (url or "").lower()
    if "catalog.11st.co.kr" in lower:
        return "catalog"
    for page_type, pattern in NON_DETAIL_PATTERNS:
        if pattern.search(lower):
            return page_type
    if any(pattern.search(lower) for pattern in DETAIL_PATTERNS):
        return "product"
    return "unknown"


def normalize_url(url: str) -> str:
    url = _safe_url(url)
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()
    host = re.sub(r"^(?:m|mg|mitem|mobile)\.", "", host)
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False):
        if key not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_"):
            query.append((key, value))
    clean_path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower() or "https", host, clean_path, urllib.parse.urlencode(query), ""))


def canonical_product_key(url: str) -> str:
    normalized = normalize_url(url)
    lower = normalized.lower()
    patterns = [
        ("11st", r"11st\.co\.kr/(?:products?|pc)/(?:ma/)?(\d+)"),
        ("gmarket", r"gmarket\.co\.kr/(?:vi/)?(?:item|product)/(\d+)"),
        ("gmarket", r"[?&]goodscode=(\d+)"),
        ("coupang", r"coupang\.com/vp/products?/(\d+)"),
        ("auction", r"auction\.co\.kr/.+?[?&]itemno=([a-z0-9]+)"),
        ("kakao", r"shoppinghow\.kakao\.com/(?:m/)?product/([a-z0-9]+)"),
        ("modumall", r"modumall\.co\.kr/.+?[?&]cm=(\d+)"),
        ("bunjang", r"bunjang\.co\.kr/products?/(\d+)"),
        ("daangn", r"daangn\.com/(?:kr/)?articles?/(\d+)"),
        ("naver", r"smartstore\.naver\.com/([^/]+)/products/(\d+)"),
    ]
    for platform, pattern in patterns:
        match = re.search(pattern, lower, re.I)
        if match:
            return f"{platform}:" + ":".join(match.groups())
    return normalized


def empty_seller_info(name: str = "", source_url: str = "") -> dict:
    return {
        "name": _clean_text(name),
        "store_name": "",
        "representative": "",
        "address": "",
        "phone": "",
        "business_number": "",
        "source_url": _safe_url(source_url),
        "confidence": "none",
    }


def seller_to_legacy_text(seller: dict) -> str:
    seller = seller or {}
    return (
        f"[업체명] {seller.get('name') or '-'}\n"
        f"[판매점명] {seller.get('store_name') or '-'}\n"
        f"[대표자] {seller.get('representative') or '-'}\n"
        f"[주소] {seller.get('address') or '-'}\n"
        f"[연락처] {seller.get('phone') or '-'}"
    )


def parse_legacy_seller(value: str, url: str = "") -> dict:
    result = empty_seller_info(source_url=url)
    mapping = {
        "[업체명]": "name", "[판매점명]": "store_name", "[대표자]": "representative",
        "[주소]": "address", "[연락처]": "phone",
    }
    text = str(value or "")
    if "[업체명]" not in text:
        result["name"] = _clean_text(text)
        return result
    for line in text.splitlines():
        for label, key in mapping.items():
            if line.strip().startswith(label):
                parsed = _clean_text(line.replace(label, "", 1))
                result[key] = "" if parsed in {"-", "미상"} else parsed
    if any(result.get(key) for key in ("representative", "address", "phone", "business_number")):
        result["confidence"] = "manual"
    return result


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _address_to_text(value) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        return " ".join(
            _clean_text(value.get(key, ""))
            for key in ("postalCode", "addressRegion", "addressLocality", "streetAddress")
            if value.get(key)
        ).strip()
    return ""


def _extract_json_ld(soup: BeautifulSoup) -> tuple[dict, dict, set[str]]:
    product = {}
    seller = empty_seller_info()
    structured_types = set()
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.string or node.get_text() or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _walk_json(payload):
            obj_type = str(obj.get("@type", "")).lower()
            if obj_type:
                structured_types.add(obj_type)
            if "product" in obj_type and not product:
                product = obj
            # 브랜드나 플랫폼 운영사를 판매자로 오인하지 않도록 명시적 seller 필드만 사용합니다.
            for candidate in (obj.get("seller"),):
                if isinstance(candidate, dict):
                    candidate_name = _clean_text(candidate.get("name", ""))
                    if len(re.sub(r"[^가-힣a-z0-9]", "", candidate_name, flags=re.I)) >= 2:
                        seller["name"] = seller["name"] or candidate_name
                    seller["phone"] = seller["phone"] or _clean_text(candidate.get("telephone", ""))
                    seller["address"] = seller["address"] or _address_to_text(candidate.get("address"))
    return product, seller, structured_types


def _find_labeled_value(lines: list[str], labels: list[str], max_length: int = 100) -> str:
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    pattern = re.compile(rf"^(?:{label_pattern})\s*[:：]?\s*(.+)$", re.I)
    for line in lines:
        match = pattern.match(line)
        if match:
            value = _clean_text(match.group(1))[:max_length]
            if value and value not in {"-", "없음", "미상"}:
                return value
    return ""


def _normalize_phone(value: str) -> str:
    value = _clean_text(value)
    digits = re.sub(r"\D", "", value)
    if not (8 <= len(digits) <= 11):
        return ""
    if not (digits.startswith("0") or re.match(r"1[5-8]\d{2}", digits)):
        return ""
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:]}"
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return value


def _extract_public_business_info(soup: BeautifulSoup, source_url: str) -> dict:
    seller = empty_seller_info(source_url=source_url)
    raw_lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    lines = []
    for raw_line in raw_lines:
        lines.extend(part.strip() for part in re.split(r"\s*[|ㅣ]\s*", raw_line) if part.strip())
    business_number = _find_labeled_value(
        lines, ["사업자등록번호", "사업자 등록번호", "사업자번호"], 30
    )
    # 사업자번호가 함께 공개된 구역만 공식 판매자정보로 간주합니다.
    number_match = re.search(r"(?<!\d)(\d{3})[-\s]?(\d{2})[-\s]?(\d{5})(?!\d)", business_number)
    if not number_match:
        return seller
    seller["business_number"] = "-".join(number_match.groups())
    seller["name"] = _find_labeled_value(lines, ["상호명", "업체명", "판매자명", "상호"], 100)
    seller["representative"] = _find_labeled_value(lines, ["대표자", "대표자명"], 60)
    for line in lines:
        candidate_phone = _find_labeled_value([line], ["대표전화", "전화번호", "연락처", "전화"], 30)
        seller["phone"] = _normalize_phone(candidate_phone)
        if seller["phone"]:
            break
    seller["address"] = _find_labeled_value(
        lines, ["사업장 소재지", "사업장주소", "사업장 주소", "소재지", "주소"], 160
    )
    for key in ("name", "representative", "phone", "address"):
        if any(noise in seller[key] for noise in ("조회", "검색하세요", "입력하세요")):
            seller[key] = ""
    seller["confidence"] = "public_business_info"
    return seller


def _extract_labeled_platform_info(soup: BeautifulSoup, source_url: str) -> dict:
    """마켓 상세페이지의 th/td, dt/dd 판매자 공개정보를 구조적으로 읽습니다."""
    pairs = {}
    for label_node in soup.select("th, dt"):
        label = _clean_text(label_node.get_text(" "))
        value_node = label_node.find_next_sibling(["td", "dd"])
        value = _clean_text(value_node.get_text(" ")) if value_node else ""
        if label and value and len(value) <= 500:
            pairs.setdefault(label, value)

    seller = empty_seller_info(source_url=source_url)
    seller["name"] = pairs.get("상호명", "")
    seller["representative"] = pairs.get("대표자", "")
    seller["address"] = next((pairs[key] for key in (
        "영업소재지", "사업장 소재지", "사업장주소", "반품/교환지 주소", "주소"
    ) if pairs.get(key)), "")
    raw_phone = next((pairs[key] for key in (
        "판매자 고객센터", "고객센터", "전화번호", "연락처", "대표전화"
    ) if pairs.get(key)), "")
    seller["phone"] = _normalize_phone(raw_phone)
    raw_business = next((pairs[key] for key in (
        "사업자등록번호", "사업자 등록번호", "사업자번호"
    ) if pairs.get(key)), "")
    number_match = re.search(r"(?<!\d)(\d{3})[-\s]?(\d{2})[-\s]?(\d{5})(?!\d)", raw_business)
    if number_match:
        seller["business_number"] = "-".join(number_match.groups())

    combined = pairs.get("상호명/대표자", "")
    if combined and "/" in combined:
        company, representative = combined.rsplit("/", 1)
        seller["name"] = seller["name"] or _clean_text(company)
        seller["representative"] = seller["representative"] or _clean_text(representative)
    seller["store_name"] = pairs.get("판매자", "")

    details = sum(bool(seller.get(key)) for key in ("representative", "address", "phone", "business_number"))
    if (seller.get("name") or seller.get("store_name")) and details:
        seller["confidence"] = "platform_public_info"
    elif seller.get("store_name"):
        seller["name"] = seller["name"] or seller["store_name"]
        seller["confidence"] = "platform_store"
    return seller


def _merge_seller_info(primary: dict, secondary: dict) -> dict:
    merged = empty_seller_info()
    for key in merged:
        primary_value = primary.get(key, "")
        if key == "confidence" and primary_value == "none":
            primary_value = ""
        merged[key] = primary_value or secondary.get(key, "")
    if _seller_quality(secondary) > _seller_quality(primary):
        if secondary.get("name"):
            if primary.get("name") and primary.get("name") != secondary.get("name") and not secondary.get("store_name"):
                merged["store_name"] = primary.get("store_name") or primary.get("name")
            merged["name"] = secondary["name"]
        merged["confidence"] = secondary.get("confidence") or merged["confidence"]
        merged["source_url"] = secondary.get("source_url") or merged["source_url"]
    return merged


def _desktop_fallback_url(url: str) -> str:
    key = canonical_product_key(url)
    if key.startswith("gmarket:"):
        product_id = key.split(":", 1)[1]
        return f"https://item.gmarket.co.kr/Item?goodscode={product_id}"
    if key.startswith("11st:"):
        product_id = key.split(":", 1)[1]
        return f"https://www.11st.co.kr/products/{product_id}"
    return url


def _extract_platform_seller(soup: BeautifulSoup, page_url: str) -> dict:
    seller = empty_seller_info()
    host = urllib.parse.urlparse(page_url).netloc.lower()
    if "11st.co.kr" in host:
        node = soup.select_one(".c_product_store_title a, .c_product_seller_title a")
        if node:
            seller["name"] = _clean_text(node.get_text(" "))
            seller["store_name"] = seller["name"]
            seller["source_url"] = urllib.parse.urljoin(page_url, node.get("href", ""))
            seller["confidence"] = "platform_store"
    return seller


def _shoppinghow_product_id(url: str) -> str:
    match = re.search(r"shoppinghow\.kakao\.com/(?:m/)?product/([a-z0-9]+)", url, re.I)
    return match.group(1) if match else ""


def _javascript_redirect_url(text: str, base_url: str) -> str:
    match = re.search(r"(?:document\.)?location\.replace\(\s*[\"']([^\"']+)", text or "", re.I)
    return urllib.parse.urljoin(base_url, html.unescape(match.group(1))) if match else ""


def _resolve_shoppinghow_merchant_url(session: requests.Session, link: str, headers: dict) -> str:
    bridge_url = urllib.parse.urljoin("https://m.shoppinghow.kakao.com", link)
    try:
        bridge = session.get(bridge_url, headers=headers, timeout=10)
        first_redirect = _javascript_redirect_url(bridge.text, bridge.url)
        if not first_redirect:
            return ""
        gate = session.get(first_redirect, headers=headers, timeout=10)
        merchant_redirect = _javascript_redirect_url(gate.text, gate.url)
        if not merchant_redirect:
            return ""
        parsed = urllib.parse.urlsplit(merchant_redirect)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        return _safe_url(query.get("goUrl", "")) or _safe_url(merchant_redirect)
    except requests.RequestException:
        return ""


def _fetch_shoppinghow_metadata(url: str) -> dict:
    product_id = _shoppinghow_product_id(url)
    if not product_id:
        return {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
        "Referer": url,
        "Accept": "application/json, text/plain, */*",
    }
    session = requests.Session()
    try:
        top_response = session.get(
            "https://m.shoppinghow.kakao.com/v3/m/product/top.json",
            params={"prodid": product_id}, headers=headers, timeout=10,
        )
        top_response.raise_for_status()
        top_payload = top_response.json()
        top = top_payload.get("topInfo") or {}
        if top_payload.get("code") != "200" or not top:
            return {}

        summary_response = session.get(
            "https://m.shoppinghow.kakao.com/v3/m/model/summary.json",
            params={"prodid": product_id, "sort_type": "3"}, headers=headers, timeout=10,
        )
        summary_response.raise_for_status()
        offers = summary_response.json().get("mallList") or []
        merchant_names = list(dict.fromkeys(
            _clean_text(offer.get("cpName", "")) for offer in offers if _clean_text(offer.get("cpName", ""))
        ))
        if not merchant_names and top.get("shopname"):
            merchant_names = [_clean_text(top.get("shopname"))]

        merchant_urls = []
        primary_metadata = {}
        for offer in offers[:3]:
            merchant_url = _resolve_shoppinghow_merchant_url(session, offer.get("link", ""), headers)
            if merchant_url and merchant_url not in merchant_urls:
                merchant_urls.append(merchant_url)
            if merchant_url and not primary_metadata and not _shoppinghow_product_id(merchant_url):
                primary_metadata = fetch_page_metadata(merchant_url)

        seller = empty_seller_info(source_url=url)
        if primary_metadata.get("seller_info") and _seller_quality(primary_metadata["seller_info"]) > 0:
            seller = primary_metadata["seller_info"]
        elif merchant_names:
            seller["name"] = merchant_names[0] if len(merchant_names) == 1 else f"{merchant_names[0]} 외 {len(merchant_names) - 1}개 판매처"
            seller["store_name"] = seller["name"]
            seller["confidence"] = "comparison_merchant"

        merchant_count = int(top.get("mallCnt") or len(offers) or len(merchant_names))
        return {
            "fetch_status": "ok",
            "final_url": url,
            "title": _clean_text(top.get("fullName") or top.get("name", "")),
            "description": "",
            "price": _clean_text(top.get("minPrice", "")),
            "seller_info": seller,
            "page_type": "product",
            "availability": "on_sale" if top.get("status") == "Y" else "unavailable",
            "seller_lookup_status": "verified" if seller.get("confidence") in {"public_business_info", "platform_public_info"} else "partial",
            "seller_lookup_reason": "shoppinghow_merchant_resolved" if merchant_urls else "shoppinghow_platform_only",
            "merchant_info": {
                "names": merchant_names,
                "count": merchant_count,
                "urls": merchant_urls,
                "source_url": f"https://m.shoppinghow.kakao.com/m/product/{product_id}/",
            },
        }
    except (requests.RequestException, ValueError, TypeError):
        return {}


def fetch_page_metadata(url: str) -> dict:
    metadata = {
        "fetch_status": "not_fetched",
        "final_url": url,
        "title": "",
        "description": "",
        "price": "",
        "seller_info": empty_seller_info(source_url=url),
        "page_type": infer_page_type(url),
        "seller_lookup_status": "pending",
        "seller_lookup_reason": "",
    }
    if _shoppinghow_product_id(url):
        shoppinghow_metadata = _fetch_shoppinghow_metadata(url)
        if shoppinghow_metadata:
            return shoppinghow_metadata
    if infer_page_type(url) in {"search", "category", "seller_profile", "catalog"}:
        metadata["fetch_status"] = "skipped_non_detail"
        return metadata

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
    }
    try:
        request_url = _desktop_fallback_url(url)
        response = requests.get(request_url, headers=headers, timeout=12, allow_redirects=True, stream=True)
        response.raise_for_status()
        raw = response.raw.read(1_500_000, decode_content=True)
        text = UnicodeDammit(raw, is_html=True).unicode_markup
        if not text:
            text = raw.decode(response.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        product, seller, structured_types = _extract_json_ld(soup)
        seller = _merge_seller_info(seller, _extract_platform_seller(soup, response.url))

        detected_page_type = infer_page_type(response.url)
        og_type_node = soup.select_one('meta[property="og:type"]')
        og_type = _clean_text(og_type_node.get("content", "")).lower() if og_type_node else ""
        if product or "product" in structured_types or "product" in og_type:
            detected_page_type = "product"
        elif any("article" in item for item in structured_types) or "article" in og_type:
            detected_page_type = "article"

        def meta_content(*selectors):
            for selector in selectors:
                node = soup.select_one(selector)
                if node and node.get("content"):
                    return _clean_text(node.get("content"))
            return ""

        title = meta_content('meta[property="og:title"]', 'meta[name="twitter:title"]')
        title = title or _clean_text(product.get("name", ""))
        title = title or _clean_text(soup.title.string if soup.title else "")
        description = meta_content('meta[property="og:description"]', 'meta[name="description"]')
        description = description or _clean_text(product.get("description", ""))

        offers = product.get("offers", {}) if isinstance(product, dict) else {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = _clean_text(offers.get("price", "")) if isinstance(offers, dict) else ""

        seller = _merge_seller_info(seller, _extract_labeled_platform_info(soup, response.url))
        seller = _merge_seller_info(seller, _extract_public_business_info(soup, response.url))

        # 공개된 판매자/사업자정보 링크가 있으면 같은 사이트 안에서 한 단계 더 확인합니다.
        seller_link = ""
        for anchor in soup.find_all("a", href=True):
            anchor_text = _clean_text(anchor.get_text(" "))
            if any(label in anchor_text for label in ("판매자정보", "판매자 정보", "사업자정보", "사업자 정보")):
                candidate_url = urllib.parse.urljoin(response.url, anchor.get("href"))
                if candidate_url.startswith(("http://", "https://")):
                    seller_link = candidate_url
                    break
        if seller_link and seller.get("confidence") != "public_business_info":
            try:
                seller_response = requests.get(seller_link, headers=headers, timeout=8, allow_redirects=True)
                seller_response.raise_for_status()
                seller_text = UnicodeDammit(seller_response.content[:1_000_000], is_html=True).unicode_markup
                seller_soup = BeautifulSoup(seller_text or seller_response.text[:1_000_000], "html.parser")
                seller = _merge_seller_info(seller, _extract_public_business_info(seller_soup, seller_response.url))
            except requests.RequestException:
                if not seller.get("source_url"):
                    seller["source_url"] = seller_link

        if seller.get("name") and seller.get("confidence") == "none":
            seller["confidence"] = "structured_seller"
            seller["source_url"] = response.url

        metadata.update({
            "fetch_status": "ok",
            "final_url": response.url,
            "title": title,
            "description": description,
            "price": price,
            "seller_info": seller,
            "page_type": detected_page_type,
            "seller_lookup_status": (
                "verified" if seller.get("confidence") in {"public_business_info", "platform_public_info"}
                else "partial" if _seller_quality(seller) > 0 else "not_public"
            ),
            "seller_lookup_reason": "page_public_info" if _seller_quality(seller) > 0 else "public_seller_info_not_found",
        })
    except requests.RequestException as exc:
        metadata["fetch_status"] = f"error:{type(exc).__name__}"
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        metadata["seller_lookup_status"] = "blocked" if status_code in {401, 403, 429} else "error"
        metadata["seller_lookup_reason"] = f"http_{status_code}" if status_code else type(exc).__name__
    except Exception as exc:
        metadata["fetch_status"] = f"error:{type(exc).__name__}"
        metadata["seller_lookup_status"] = "error"
        metadata["seller_lookup_reason"] = type(exc).__name__
    return metadata


def score_relevance(record: dict) -> dict:
    title = _clean_text(record.get("title", "")).lower()
    description = _clean_text(record.get("description") or record.get("snippet", "")).lower()
    category = " ".join(str(record.get(key, "")) for key in ("category1", "category2", "category3", "category4")).lower()
    page_type = record.get("page_type") or infer_page_type(record.get("url", ""))
    keyword = _clean_text(record.get("query") or record.get("item", "")).lower()

    score = 0
    reasons = []
    matched_terms = []

    if page_type == "product":
        score += 30
        reasons.append("상품 상세 URL")
    elif page_type == "listing_post":
        score += 18
        reasons.append("공개 커뮤니티 판매글")
    elif page_type == "unknown":
        reasons.append("페이지 유형 미확인")
    else:
        score -= 60 if page_type in {"search", "category", "seller_profile", "article"} else 35
        reasons.append(f"상품 상세가 아닌 {page_type} 페이지")

    matched_terms.extend(_matching_trap_terms(title))
    matched_terms = list(dict.fromkeys(matched_terms))
    if matched_terms:
        score += 38
        reasons.append("상품명에 엽구 용어 포함")
    elif _matching_trap_terms(description):
        score += 18
        reasons.append("설명에 엽구 용어 포함")

    if keyword and _term_in_text(title, keyword) and (keyword != "창애" or "창애" in matched_terms):
        score += 12
        reasons.append("검색어와 상품명 일치")
    if any(signal in f"{title} {description}" for signal in SALE_SIGNALS):
        score += 10
        reasons.append("판매 표현 확인")
    if page_type == "listing_post" and _looks_like_community_listing(record):
        score += 15
        reasons.append("거래 의사 또는 가격·연락처 확인")
    if record.get("price"):
        score += 8
        reasons.append("가격 정보 확인")

    combined_text = f"{title} {description}"
    bad_words = [
        word for word in BAD_TITLE_WORDS
        if (_exact_term_in_text(combined_text, word) if word in BAD_EXACT_WORDS else word.lower() in combined_text)
    ]
    if bad_words:
        score -= 55
        reasons.append("비관련 표현: " + ", ".join(bad_words[:3]))
    if any(word.lower() in category for word in BAD_CATEGORIES):
        score -= 45
        reasons.append("비관련 카테고리")

    has_high_risk_term = any(_term_in_text(combined_text, term) for term in HIGH_RISK_TERMS)
    has_non_wildlife_context = any(term in combined_text for term in NON_WILDLIFE_CONTEXT_TERMS)
    has_wildlife_target = any(term in combined_text for term in WILDLIFE_TARGET_TERMS)
    title_has_high_risk_term = any(_term_in_text(title, term) for term in HIGH_RISK_TERMS)
    title_has_non_wildlife_context = any(term in title for term in NON_WILDLIFE_CONTEXT_TERMS)
    title_has_specific_wildlife = any(term in title for term in SPECIFIC_WILDLIFE_TARGET_TERMS)
    if matched_terms and not has_high_risk_term and has_non_wildlife_context and not has_wildlife_target:
        score -= 55
        reasons.append("구조·설치류·조류·곤충용 상품")
    elif matched_terms and title_has_non_wildlife_context and not title_has_high_risk_term and not title_has_specific_wildlife:
        score -= 55
        reasons.append("상품명이 구조·설치류·조류·곤충용에 해당")

    score = max(0, min(100, score))
    if score >= 70:
        confidence = "high"
    elif score >= 45:
        confidence = "medium"
    else:
        confidence = "low"

    non_detail = page_type in {"search", "category", "seller_profile", "catalog", "article"}
    # 상세주소만 있고 제목·설명에 엽구 근거가 없는 결과는 후보에 올리지 않습니다.
    # 유형을 판별하지 못한 페이지는 오탐을 줄이기 위해 더 강한 근거를 요구합니다.
    minimum_score = 45 if page_type == "product" else 60 if page_type == "listing_post" else 70
    auto_reject = non_detail or score < minimum_score or not matched_terms
    return {
        "relevance_score": score,
        "confidence": confidence,
        "matched_terms": matched_terms,
        "relevance_reasons": reasons,
        "suggested_status": "auto_rejected" if auto_reject else "candidate",
    }


def assess_risk(record: dict) -> dict:
    """관련도와 별개로 엽구의 위해 가능성을 보수적으로 분류합니다."""
    status = record.get("status", "")
    page_type = record.get("page_type") or infer_page_type(record.get("url", ""))
    text = f"{_clean_text(record.get('title', ''))} {_clean_text(record.get('description', ''))}".lower()

    if status in {"rejected", "auto_rejected", "deleted"} or page_type not in {"product", "listing_post"}:
        return {
            "risk_level": "low",
            "risk_score": 10,
            "risk_reasons": ["판매 후보가 아니거나 상품 상세페이지가 아님"],
        }

    high_terms = [term for term in HIGH_RISK_TERMS if _term_in_text(text, term)]
    # 단독 '창애'는 다른 의미가 많으므로 기존 문맥 판별을 그대로 적용합니다.
    if "창애" in high_terms and "창애" not in _matching_trap_terms(text):
        high_terms.remove("창애")
    if high_terms:
        return {
            "risk_level": "high",
            "risk_score": 90,
            "risk_reasons": ["고위험 엽구 표현: " + ", ".join(list(dict.fromkeys(high_terms))[:3])],
        }

    medium_terms = [term for term in MEDIUM_RISK_TERMS if term in text]
    if medium_terms:
        reason = "포획·덫 상품으로 추가 판단 필요: " + ", ".join(list(dict.fromkeys(medium_terms))[:3])
        if any(signal in text for signal in ("구조", "유기견", "유기묘", "고양이")):
            reason += " · 구조용 표기 확인 필요"
        return {"risk_level": "medium", "risk_score": 60, "risk_reasons": [reason]}

    return {
        "risk_level": "low",
        "risk_score": 20,
        "risk_reasons": ["고위험 엽구 표현이 확인되지 않음"],
    }


def normalize_record(record: dict) -> dict:
    record = dict(record or {})
    url = _safe_url(record.get("final_url") or record.get("url"))
    record["url"] = _safe_url(record.get("url")) or url
    record["final_url"] = url
    record["canonical_url"] = normalize_url(url)
    record["canonical_key"] = canonical_product_key(url)
    record["page_type"] = record.get("page_type") or infer_page_type(url)
    record["platform"] = infer_platform(url, record.get("platform", ""))
    record["query"] = record.get("query") or record.get("item", "")
    record["item"] = record.get("item") or record.get("query", "기타 불법 엽구")
    record["title"] = _clean_text(record.get("title", ""))
    record["description"] = _clean_text(record.get("description") or record.get("snippet", ""))

    seller_info = record.get("seller_info")
    if not isinstance(seller_info, dict):
        seller_info = parse_legacy_seller(record.get("seller", ""), url)
    normalized_seller = empty_seller_info(source_url=seller_info.get("source_url") or url)
    normalized_seller.update({key: _clean_text(seller_info.get(key, "")) for key in (
        "name", "store_name", "representative", "address", "phone", "business_number", "confidence"
    )})
    if len(re.sub(r"[^가-힣a-z0-9]", "", normalized_seller["name"], flags=re.I)) < 2:
        normalized_seller["name"] = ""
    normalized_seller["source_url"] = _safe_url(seller_info.get("source_url") or url)
    record["seller_info"] = normalized_seller
    record["seller"] = seller_to_legacy_text(normalized_seller)

    score_info = score_relevance(record)
    for key, value in score_info.items():
        if key != "suggested_status":
            record[key] = value

    source = record.get("source") or ("manual" if str(record.get("id", "")).isdigit() else "search")
    record["source"] = source
    status = record.get("status")
    if status not in STATUS_VALUES:
        status = "confirmed" if source == "manual" else score_info["suggested_status"]
    record["status"] = status

    record["first_seen"] = record.get("first_seen") or record.get("date") or _now()
    record["last_seen"] = record.get("last_seen") or record.get("date") or record["first_seen"]
    record["date"] = record.get("date") or record["first_seen"]
    if not record.get("id"):
        digest_source = record["canonical_key"] or f"{record['platform']}:{record['title']}:{record['date']}"
        record["id"] = "record_" + hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:16]
    record.update(assess_risk(record))
    return record


def _seller_completeness(seller: dict) -> int:
    return sum(bool(seller.get(key)) for key in ("name", "store_name", "representative", "address", "phone", "business_number"))


def _seller_quality(seller: dict) -> int:
    confidence_weight = {
        "public_business_info": 50,
        "manual": 40,
        "platform_public_info": 35,
        "comparison_merchant": 25,
        "platform_store": 20,
        "structured_seller": 15,
        "public_page": 10,
        "none": 0,
    }
    return confidence_weight.get(seller.get("confidence", "none"), 0) + _seller_completeness(seller)


def merge_record(existing: dict, incoming: dict) -> dict:
    existing = normalize_record(existing)
    incoming = normalize_record(incoming)
    protected_status = existing.get("status") in {"confirmed", "rejected", "deleted"}
    preserved = {
        "id": existing["id"],
        "first_seen": existing.get("first_seen"),
        "reviewed_at": existing.get("reviewed_at", ""),
        "review_note": existing.get("review_note", ""),
    }
    if protected_status:
        preserved["status"] = existing["status"]

    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    if _seller_quality(existing.get("seller_info", {})) > _seller_quality(incoming.get("seller_info", {})):
        merged["seller_info"] = existing["seller_info"]
    merged.update(preserved)
    merged["last_seen"] = incoming.get("last_seen") or _now()
    merged["seller"] = seller_to_legacy_text(merged.get("seller_info", {}))
    return normalize_record(merged)


def deduplicate_records(records: list[dict]) -> list[dict]:
    merged_by_key = {}
    order = []
    for raw in records:
        record = normalize_record(raw)
        key = record.get("canonical_key") or record["id"]
        if key in merged_by_key:
            merged_by_key[key] = merge_record(merged_by_key[key], record)
        else:
            merged_by_key[key] = record
            order.append(key)
    return [merged_by_key[key] for key in order]


GENERIC_SELLER_NAMES = {
    "11번가", "g마켓", "옥션", "쿠팡", "네이버쇼핑", "쇼핑하우", "당근", "번개장터",
    "헬로마켓", "판매자", "스토어", "업체명미확인",
}


def _seller_name_key(value: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", _clean_text(value).lower(), flags=re.I)


def _seller_source_key(value: str) -> str:
    value = _safe_url(value)
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    ignored = {"pdppredno", "deliverytype", "itemno", "goodscode", "it_id", "idx", "cm", "page"}
    query = [
        (key, val) for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in ignored and not key.lower().startswith("utm_")
    ]
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urllib.parse.urlencode(query), ""))


def _seller_host(seller: dict, record: dict | None = None) -> str:
    url = seller.get("source_url") or (record or {}).get("url", "")
    return urllib.parse.urlparse(url).netloc.lower()


def load_seller_master() -> dict:
    if not os.path.exists(SELLER_MASTER_FILE):
        return {"version": 1, "updated_at": "", "sellers": []}
    try:
        with open(SELLER_MASTER_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if isinstance(payload, dict) and isinstance(payload.get("sellers"), list):
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "updated_at": "", "sellers": []}


def _find_master_entry(master: dict, seller: dict, record: dict | None = None) -> dict | None:
    business_number = re.sub(r"\D", "", seller.get("business_number", ""))
    source_key = _seller_source_key(seller.get("source_url", ""))
    name_key = _seller_name_key(seller.get("name", ""))
    host = _seller_host(seller, record)
    for entry in master.get("sellers", []):
        info = entry.get("seller_info", {})
        entry_business = re.sub(r"\D", "", info.get("business_number", ""))
        if business_number and len(business_number) == 10 and business_number == entry_business:
            return entry
        if source_key and source_key in entry.get("source_keys", []):
            return entry
        if len(name_key) >= 3 and name_key in entry.get("name_keys", []) and host in entry.get("hosts", []):
            return entry
    return None


def build_seller_master(records: list[dict], master: dict | None = None) -> dict:
    master = json.loads(json.dumps(master or {"version": 1, "updated_at": "", "sellers": []}, ensure_ascii=False))
    master.setdefault("sellers", [])
    for record in records:
        seller = record.get("seller_info") or {}
        name_key = _seller_name_key(seller.get("name", ""))
        has_identity = (
            (len(name_key) >= 3 and name_key not in {_seller_name_key(name) for name in GENERIC_SELLER_NAMES})
            or len(re.sub(r"\D", "", seller.get("business_number", ""))) == 10
        )
        if not has_identity:
            continue

        entry = _find_master_entry(master, seller, record)
        if entry is None:
            entry = {
                "id": "seller_" + hashlib.sha1(
                    (re.sub(r"\D", "", seller.get("business_number", "")) or _seller_source_key(seller.get("source_url", "")) or name_key).encode("utf-8")
                ).hexdigest()[:14],
                "seller_info": empty_seller_info(),
                "name_keys": [],
                "source_keys": [],
                "hosts": [],
                "updated_at": "",
            }
            master["sellers"].append(entry)

        source_key = _seller_source_key(seller.get("source_url", ""))
        host = _seller_host(seller, record)
        if name_key and name_key not in entry["name_keys"]:
            entry["name_keys"].append(name_key)
        if source_key and source_key not in entry["source_keys"]:
            entry["source_keys"].append(source_key)
        if host and host not in entry["hosts"]:
            entry["hosts"].append(host)

        saved = entry.get("seller_info") or empty_seller_info()
        if seller.get("confidence") == "manual":
            for key in saved:
                if seller.get(key):
                    saved[key] = seller[key]
        else:
            saved_quality = _seller_quality(saved)
            for key in saved:
                if not saved.get(key) and seller.get(key):
                    saved[key] = seller[key]
            if _seller_quality(seller) > saved_quality:
                if seller.get("name") and seller.get("name") != saved.get("name"):
                    saved["store_name"] = seller.get("store_name") or saved.get("store_name") or saved.get("name", "")
                    saved["name"] = seller["name"]
                for key in ("representative", "address", "phone", "business_number"):
                    if seller.get(key):
                        saved[key] = seller[key]
                saved["confidence"] = seller.get("confidence", saved.get("confidence", "none"))
                saved["source_url"] = seller.get("source_url") or saved.get("source_url", "")
        entry["seller_info"] = saved
        entry["updated_at"] = record.get("reviewed_at") or record.get("last_seen") or _now()

    master["updated_at"] = _now()
    return master


def apply_seller_master_to_record(record: dict, master: dict) -> dict:
    record = dict(record)
    seller = dict(record.get("seller_info") or empty_seller_info(source_url=record.get("url", "")))
    entry = _find_master_entry(master, seller, record)
    if not entry:
        record.pop("seller_master_id", None)
        record.pop("seller_verified_at", None)
        return record

    master_seller = entry.get("seller_info") or {}
    for key in ("name", "representative", "address", "phone", "business_number"):
        if not seller.get(key) and master_seller.get(key):
            seller[key] = master_seller[key]
    current_host = _seller_host(seller, record)
    master_host = urllib.parse.urlparse(master_seller.get("source_url", "")).netloc.lower()
    if not seller.get("store_name") and current_host and current_host == master_host:
        seller["store_name"] = master_seller.get("store_name", "")
    if _seller_quality(master_seller) > _seller_quality(seller):
        seller["confidence"] = master_seller.get("confidence", seller.get("confidence", "none"))
        seller["source_url"] = seller.get("source_url") or master_seller.get("source_url", "")
    record["seller_info"] = seller
    record["seller"] = seller_to_legacy_text(seller)
    record["seller_master_id"] = entry.get("id", "")
    record["seller_verified_at"] = entry.get("updated_at", "")
    return record


def _listing_fingerprint(record: dict) -> str:
    if record.get("status") not in {"candidate", "confirmed"}:
        return record.get("canonical_key") or record.get("id", "")
    title = _clean_text(record.get("title", "")).lower()
    title = re.sub(r"^\[[^\]]+\]\s*", "", title)
    title = title.split(" - ", 1)[0]
    title = re.sub(r"[^가-힣a-z0-9]", "", title, flags=re.I)
    if len(title) < 12:
        return record.get("canonical_key") or record.get("id", "")
    price = re.sub(r"\D", "", str(record.get("price", "")))
    return "listing:" + hashlib.sha1(f"{title}:{price}".encode("utf-8")).hexdigest()[:16]


def assign_duplicate_clusters(records: list[dict]) -> list[dict]:
    groups = {}
    prepared = [dict(record) for record in records]
    for record in prepared:
        fingerprint = _listing_fingerprint(record)
        groups.setdefault(fingerprint, []).append(record)
    for fingerprint, group in groups.items():
        cluster_id = "cluster_" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
        for index, record in enumerate(group):
            record["cluster_id"] = cluster_id
            record["duplicate_count"] = len(group)
            record["cluster_primary"] = index == 0
    return prepared


def prepare_records(records: list[dict], update_master: bool = False) -> list[dict]:
    unique = deduplicate_records(records)
    master = load_seller_master()
    if update_master:
        master = build_seller_master(unique, master)
    unique = [normalize_record(apply_seller_master_to_record(record, master)) for record in unique]
    unique = assign_duplicate_clusters(unique)
    if update_master:
        temp_master = SELLER_MASTER_FILE + ".tmp"
        with open(temp_master, "w", encoding="utf-8") as file:
            json.dump(master, file, ensure_ascii=False, indent=2)
        os.replace(temp_master, SELLER_MASTER_FILE)
    return unique


def load_records() -> list[dict]:
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)
        return prepare_records(payload if isinstance(payload, list) else [])
    except Exception as exc:
        logger.error("기존 DB 읽기 실패: %s", exc)
        return []


def write_records(records: list[dict]) -> list[dict]:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    prepared = prepare_records(records, update_master=True)
    temp_file = DB_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(prepared, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, DB_FILE)
    return prepared


def save_data(new_items: list[dict]) -> int:
    existing = load_records()
    existing_by_key = {(item.get("canonical_key") or item["id"]): item for item in existing}
    added_count = 0
    for incoming in deduplicate_records(new_items):
        key = incoming.get("canonical_key") or incoming["id"]
        if key in existing_by_key:
            existing_by_key[key] = merge_record(existing_by_key[key], incoming)
        else:
            existing_by_key[key] = incoming
            added_count += 1
    write_records(list(existing_by_key.values()))
    logger.info("신규 후보 %d건 저장, 전체 %d건", added_count, len(existing_by_key))
    return added_count


def save_last_run(
    added_count: int,
    total_found: int,
    error_msg: str = "",
    sources: dict | None = None,
    metrics: dict | None = None,
):
    payload = {
        "last_run": _now(),
        "added_count": added_count,
        "total_found": total_found,
        "error": error_msg,
        "sources": sources or {},
        "metrics": metrics or {},
    }
    with open(LAST_RUN_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def build_free_search_plan(at: datetime | None = None) -> list[dict]:
    """무료 검색 호출량을 일정하게 유지하면서 일주일 안에 탐색 범위를 순환합니다."""
    at = at or datetime.now()
    day_index = at.timetuple().tm_yday
    plan = [
        {"source": "naver_web", "endpoint": "webkr", "query": query, "item": item, "display": 30, "sort": "sim"}
        for query, item in CORE_WEB_QUERIES
    ]

    # 고위험 표현은 일부를 매일 최신순으로도 확인해 오래된 인기 결과에 묻히는 것을 막습니다.
    recent_terms = CORE_WEB_QUERIES[:6]
    recent_start = day_index % len(recent_terms)
    for offset in range(3):
        query, item = recent_terms[(recent_start + offset) % len(recent_terms)]
        plan.append({
            "source": "naver_web", "endpoint": "webkr", "query": query,
            "item": item, "display": 20, "sort": "date",
        })

    # 하루 3개 도메인씩 순환하면 3일마다 주요 중고·쇼핑 채널을 모두 훑습니다.
    domain_start = (day_index * 3) % len(TARGET_SITE_DOMAINS)
    domains = [TARGET_SITE_DOMAINS[(domain_start + offset) % len(TARGET_SITE_DOMAINS)] for offset in range(3)]
    for domain in domains:
        plan.extend([
            {
                "source": "naver_web", "endpoint": "webkr",
                "query": f"올무 판매 site:{domain}", "item": "올무",
                "display": 20, "sort": "sim",
            },
            {
                "source": "naver_web", "endpoint": "webkr",
                "query": f"포획틀 판매 site:{domain}", "item": "포획틀",
                "display": 20, "sort": "sim",
            },
        ])

    community_start = (day_index * 4) % len(COMMUNITY_QUERIES)
    community_batch = [
        COMMUNITY_QUERIES[(community_start + offset) % len(COMMUNITY_QUERIES)]
        for offset in range(4)
    ]
    for endpoint, source in (("blog", "naver_blog"), ("cafearticle", "naver_cafe")):
        for query, item in community_batch:
            plan.append({
                "source": source, "endpoint": endpoint, "query": query,
                "item": item, "display": 20, "sort": "date",
            })
    return plan


def _search_naver_channel(spec: dict) -> list[dict]:
    source = spec["source"]
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        _update_source_health(source, "skipped", error="인증정보 없음")
        logger.warning("%s 검색 인증정보가 없어 건너뜁니다.", source)
        return []

    results = []
    try:
        response = requests.get(
            f"https://openapi.naver.com/v1/search/{spec['endpoint']}.json",
            params={
                "query": spec["query"],
                "display": spec.get("display", 20),
                "sort": spec.get("sort", "sim"),
            },
            headers={
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            timeout=10,
        )
        response.raise_for_status()
        for item in response.json().get("items", []):
            link = _safe_url(item.get("link", ""))
            if not link:
                continue
            now = _now()
            record = {
                "source": source,
                "platform": infer_platform(link),
                "query": spec["item"],
                "item": spec["item"],
                "search_query": spec["query"],
                "search_sort": spec.get("sort", "sim"),
                "title": _clean_text(item.get("title", "")),
                "snippet": _clean_text(item.get("description", "")),
                "description": _clean_text(item.get("description", "")),
                "url": link,
                "final_url": link,
                "date": item.get("postdate") or now,
                "first_seen": now,
                "last_seen": now,
            }
            if source in {"naver_blog", "naver_cafe"}:
                record["page_type"] = "listing_post" if _looks_like_community_listing(record) else "article"
                record["publisher"] = _clean_text(item.get("bloggername") or item.get("cafename", ""))
            results.append(normalize_record(record))
        _update_source_health(source, "ok", len(results), queries=1)
    except requests.RequestException as exc:
        _update_source_health(source, "error", error=type(exc).__name__, queries=1)
        logger.error("%s '%s' 검색 오류: %s", source, spec["query"], exc)

    logger.info("%s '%s' 원본 결과: %d건", source, spec["query"], len(results))
    return results


def _is_promising_search_result(record: dict) -> bool:
    text = f"{record.get('title', '')} {record.get('description', '')}"
    if not _matching_trap_terms(text):
        return False
    return True


def _extract_discovered_product_records(soup: BeautifulSoup, base_url: str, parent: dict) -> list[dict]:
    parent_text = f"{parent.get('title', '')} {parent.get('description', '')}"
    found = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        candidate_url = _safe_url(urllib.parse.urljoin(base_url, anchor.get("href", "")))
        if not candidate_url or candidate_url in seen or infer_page_type(candidate_url) != "product":
            continue
        anchor_text = _clean_text(anchor.get_text(" "))
        parent_node = anchor.parent
        context = _clean_text(parent_node.get_text(" ") if parent_node else anchor_text)[:500]
        if not _matching_trap_terms(f"{anchor_text} {context}") and not _matching_trap_terms(parent_text):
            continue
        seen.add(candidate_url)
        now = _now()
        found.append(normalize_record({
            "source": "link_discovery",
            "origin_source": parent.get("source", ""),
            "platform": infer_platform(candidate_url),
            "query": parent.get("query", ""),
            "item": parent.get("item", ""),
            "search_query": parent.get("search_query", ""),
            "title": anchor_text or parent.get("title", ""),
            "description": context or parent.get("description", ""),
            "url": candidate_url,
            "final_url": candidate_url,
            "page_type": "product",
            "discovered_from": base_url,
            "date": now,
            "first_seen": now,
            "last_seen": now,
        }))
        if len(found) >= 10:
            break
    return found


def _fetch_discovery_links(parent: dict) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
    }
    try:
        response = requests.get(parent["url"], headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        markup = UnicodeDammit(response.content[:1_000_000], is_html=True).unicode_markup
        soup = BeautifulSoup(markup or response.text[:1_000_000], "html.parser")
        return _extract_discovered_product_records(soup, response.url, parent)
    except requests.RequestException:
        return []


def discover_product_records(records: list[dict], max_pages: int = 60) -> list[dict]:
    discovery_pages = [
        record for record in records
        if record.get("page_type") in DISCOVERY_PAGE_TYPES
    ][:max_pages]
    discovered = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_discovery_links, record) for record in discovery_pages]
        for future in as_completed(futures):
            try:
                discovered.extend(future.result())
            except Exception:
                continue
    unique = deduplicate_records(discovered)
    _update_source_health("link_discovery", "ok", found=len(discovery_pages), discovered=len(unique))
    logger.info("발견 페이지 %d건에서 상품 상세주소 %d건 추출", len(discovery_pages), len(unique))
    return unique


def search_naver_shopping(_keyword: str) -> list[dict]:
    if NAVER_SHOPPING_API_RETIRED:
        logger.info("네이버 쇼핑 검색 API 종료로 해당 검색원을 건너뜁니다.")
    return []


def search_naver_web(keyword: str) -> list[dict]:
    return _search_naver_channel({
        "source": "naver_web", "endpoint": "webkr", "query": f"{keyword} 판매",
        "item": keyword, "display": 30, "sort": "sim",
    })


def search_google_vertex(keyword: str) -> list[dict]:
    if not GOOGLE_SDK_AVAILABLE:
        _update_source_health("google_vertex", "skipped", error="SDK 없음")
        logger.warning("google-cloud-discoveryengine 패키지가 없어 구글 검색을 건너뜁니다.")
        return []
    if not GOOGLE_CLOUD_PROJECT or not VERTEX_DATA_STORE_ID:
        _update_source_health("google_vertex", "skipped", error="설정 없음")
        logger.warning("Vertex AI 설정이 없어 구글 검색을 건너뜁니다.")
        return []

    logger.info("[구글 검색] 키워드: %s", keyword)
    results = []
    try:
        key_path = os.path.join(BASE_DIR, "google_service_account.json")
        if os.path.exists(key_path):
            client = discoveryengine.SearchServiceClient.from_service_account_json(key_path)
        else:
            client = discoveryengine.SearchServiceClient()

        serving_config = client.serving_config_path(
            project=GOOGLE_CLOUD_PROJECT,
            location="global",
            data_store=VERTEX_DATA_STORE_ID,
            serving_config="default_search",
        )
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=f"{keyword} 판매",
            page_size=10,
        )
        for result in client.search(request).results:
            data = result.document.derived_struct_data
            title = _clean_text(data.get("title", ""))
            link = _safe_url(data.get("link", ""))
            snippets = data.get("snippets", []) or []
            snippet = _clean_text(snippets[0].get("snippet", "")) if snippets else ""
            if not link:
                continue
            record = {
                "source": "google_vertex",
                "platform": infer_platform(link),
                "query": keyword,
                "item": keyword,
                "title": title,
                "snippet": snippet,
                "description": snippet,
                "url": link,
                "final_url": link,
                "date": _now(),
                "first_seen": _now(),
                "last_seen": _now(),
            }
            results.append(normalize_record(record))
        _update_source_health("google_vertex", "ok", len(results))
    except Exception as exc:
        _update_source_health("google_vertex", "error", error=f"{type(exc).__name__}")
        logger.error("Vertex AI 검색 오류: %s", exc)

    logger.info("구글 '%s' 원본 결과: %d건", keyword, len(results))
    return results


def enrich_record(record: dict) -> dict:
    record = normalize_record(record)
    previous_status = record.get("status")
    metadata = fetch_page_metadata(record["url"])
    if metadata.get("final_url"):
        record["final_url"] = metadata["final_url"]
        record["page_type"] = metadata.get("page_type") or infer_page_type(metadata["final_url"])
    if metadata.get("title"):
        record["title"] = metadata["title"]
    if metadata.get("description"):
        record["description"] = metadata["description"]
    if metadata.get("price"):
        record["price"] = metadata["price"]
    record["fetch_status"] = metadata.get("fetch_status", "")
    for key in ("seller_lookup_status", "seller_lookup_reason", "merchant_info", "availability"):
        if metadata.get(key) not in (None, "", [], {}):
            record[key] = metadata[key]
    metadata_seller = metadata.get("seller_info", {})
    if metadata_seller.get("confidence") in {"public_business_info", "platform_public_info"}:
        record["seller_info"] = metadata_seller
    elif _seller_quality(metadata_seller) > _seller_quality(record.get("seller_info", {})):
        record["seller_info"] = metadata["seller_info"]
    if record.get("source") in {"naver_blog", "naver_cafe"} and _looks_like_community_listing(record):
        record["page_type"] = "listing_post"
    normalized = normalize_record(record)
    if previous_status in {"candidate", "auto_rejected"}:
        normalized["status"] = score_relevance(normalized)["suggested_status"]
    return normalized


def enrich_records(records: list[dict]) -> list[dict]:
    unique = deduplicate_records(records)
    enriched = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(enrich_record, record): record for record in unique}
        for future in as_completed(futures):
            try:
                enriched.append(future.result())
            except Exception as exc:
                fallback = normalize_record(futures[future])
                fallback["fetch_status"] = f"error:{type(exc).__name__}"
                enriched.append(fallback)
    return enriched


def run_scraper() -> dict:
    logger.info("===== 불법 엽구 온라인 감시 시작 =====")
    SOURCE_HEALTH.clear()
    all_items = []
    search_plan = build_free_search_plan()
    for spec in search_plan:
        all_items.extend(_search_naver_channel(spec))
        time.sleep(0.15)

    if ENABLE_GOOGLE_VERTEX:
        for keyword in KEYWORDS:
            all_items.extend(search_google_vertex(keyword))
    else:
        _update_source_health("google_vertex", "skipped", error="무료 모드에서 비활성화")

    promising_items = [item for item in all_items if _is_promising_search_result(item)]
    discovered_items = discover_product_records(promising_items)
    unique_items = deduplicate_records(promising_items + discovered_items)
    logger.info(
        "원본 %d건 → 관련 표현 포함 %d건 → 링크 발견 포함 중복 제거 %d건",
        len(all_items), len(promising_items), len(unique_items),
    )
    enriched = enrich_records(unique_items)
    storable = [
        item for item in enriched
        if item.get("status") != "auto_rejected" or item.get("page_type") in {"product", "listing_post"}
    ]
    added = save_data(storable)
    metrics = {
        "search_queries": len(search_plan),
        "raw_results": len(all_items),
        "promising_results": len(promising_items),
        "discovered_products": len(discovered_items),
        "enriched_results": len(enriched),
        "stored_results": len(storable),
        "free_mode": not ENABLE_GOOGLE_VERTEX,
    }
    save_last_run(added, len(storable), sources=SOURCE_HEALTH, metrics=metrics)

    status_counts = {}
    for item in storable:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    logger.info("===== 감시 종료 | 신규 %d건 | 분류 %s =====", added, status_counts)
    return {
        "total_found": len(storable),
        "new_added": added,
        "status_counts": status_counts,
        "sources": SOURCE_HEALTH,
        "metrics": metrics,
    }


if __name__ == "__main__":
    print(json.dumps(run_scraper(), ensure_ascii=False))
