import time
import json
import os
from datetime import datetime
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests

from google.cloud import discoveryengine_v1beta as discoveryengine

# Load environment variables from .env file if it exists
load_dotenv()

# API Keys & Config
NAVER_CLIENT_ID = os.getenv('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.getenv('NAVER_CLIENT_SECRET')

GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_DATA_STORE_ID = os.getenv('VERTEX_DATA_STORE_ID')

# --- 설정 및 경로 ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "scraped_data.json")

# 수집 키워드
KEYWORDS = ["올무", "스프링올무", "창애", "멧돼지 포획틀", "너구리 포획틀", "야생동물 포획기"]


def save_data(new_items):
    """새로 수집된 데이터를 기존 JSON에 병합 저장합니다. 중복은 URL 기준으로 제거합니다."""
    existing_data = []
    
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception as e:
            print(f"기존 DB 읽기 에러: {e}")
            existing_data = []
            
    # URL 기준 중복 제거 (기존 데이터에 없는 것만 추가)
    existing_urls = {item["url"] for item in existing_data}
    
    added_count = 0
    for item in new_items:
        if item["url"] not in existing_urls:
            existing_data.append(item)
            added_count += 1
            
    # 저장
    if added_count > 0:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)
        print(f"새로운 의심 게시글 {added_count}건 저장 완료.")
    else:
        print("새로운 적발 건이 없습니다.")

import random
from datetime import timedelta

def search_naver_shopping(keyword):
    """네이버 쇼핑 검색 API 연동 (API 키 필요)"""
    # 뉴스레이더 구동 방식과 동일하게 환경변수에서 키를 가져오거나 로컬 .env 활용 (python-dotenv 처리 필요시 차후 추가)
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("네이버 API 인증 정보가 없습니다. (환경변수 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 확인 요망)")
        print("임시로 1개의 더미 데이터를 반환합니다.")
        return [{
            "id": f"dummy_{int(time.time()*1000)}",
            "platform": "네이버쇼핑 (더미데이터)",
            "item": keyword,
            "seller": "[업체명] API연동필요\n[대표자] -\n[주소] -\n[연락처] -", 
            "url": "http://localhost",
            "date": datetime.now().isoformat()
        }]
        
    print(f"[네이버 쇼핑 API 검색 중...] 키워드: {keyword}")
    encText = urllib.parse.quote(keyword)
    url = f"https://openapi.naver.com/v1/search/shop.json?query={encText}&display=10&sort=date"
    
    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
    
    scraped_items = []
    
    try:
        response = urllib.request.urlopen(request)
        rescode = response.getcode()
        
        if rescode == 200:
            response_body = response.read()
            items = json.loads(response_body.decode('utf-8'))['items']
            
            for item in items:
                title = item['title'].replace("<b>", "").replace("</b>", "")
                link = item['link']
                mall_name = item.get('mallName', '네이버쇼핑')
                
                # 카테고리 메타데이터 추출
                category1 = item.get('category1', '')
                category2 = item.get('category2', '')
                
                # 1차 필터링: 무관한 카테고리(식품, 도서, 의류 등) 즉시 제외
                bad_categories = ["식품", "도서", "여가/생활편의", "출산/육아", "화장품/미용", "가구/인테리어", "의류", "잡화", "음반", "e-book", "패션", "디지털/가전"]
                if any(bad in category1 for bad in bad_categories):
                    continue
                
                # 2차 필터링: 생활/건강 하위의 무관한 카테고리(건강식품 등) 제외
                if category1 == "생활/건강" and any(bad in category2 for bad in ["건강식품", "의료용품", "화장품", "건강측정용품", "안마/찜질용품", "주방용품", "공구"]):
                    continue
                
                # 확실히 불법 엽구 키워드가 포함되어 있는지 이중 체크
                if any(k in title for k in KEYWORDS) or keyword in title:
                    # 3차 필터링: 제목에 포함된 불량 키워드(오인 검색 방지) 확인
                    bad_title_words = [
                        "책", "도서", "장난감", "피규어", "식품", "즙", "액", "환", "장떡", "건강", "효능", "먹는", "요리", "레시피", "반찬", "식당", "맛집", "키트", "DIY", "게임", "동화", "소설",
                        "분석기", "검출기", "계측기", "센서", "테스트", "농도", "함량", "질소", "산소", "측정", "tester", "sensor", "analyzer", "detector"
                    ]
                    if any(bad in title.lower() for bad in bad_title_words):
                        continue
                    
                    seller_formatted = f"[업체명] {mall_name}\n[대표자] API정보부족\n[주소] URL직접확인요망\n[연락처] URL직접확인요망"
                    
                    scraped_items.append({
                        "id": f"naverapi_{item.get('productId', int(time.time()*1000))}_{len(scraped_items)}",
                        "platform": f"네이버쇼핑",
                        "item": keyword,
                        "seller": seller_formatted, 
                        "url": link,
                        "date": datetime.now().isoformat()
                    })
        else:
            print(f"Error Code: {rescode}")
            
    except Exception as e:
        print(f"네이버 쇼핑 API 에러: {e}")
        
    return scraped_items


def search_google_vertex(keyword):
    """구글 Vertex AI Search 연동 (쇼ピング몰 및 지정 사이트 타겟팅)"""
    if not GOOGLE_CLOUD_PROJECT or not VERTEX_DATA_STORE_ID:
        print(f"Vertex AI 설정(Project/DataStore ID) 누락. 검색 건너뜀 (키워드: {keyword})")
        return []
        
    print(f"[구글 Vertex AI 검색 중...] 키워드: {keyword}")
    scraped_items = []
    
    try:
        # 인증 방식 설정: 로컬에 키 파일이 있으면 사용, 없으면 기본 인증 시도
        key_path = os.path.join(os.path.dirname(__file__), "google_service_account.json")
        
        if os.path.exists(key_path):
            client = discoveryengine.SearchServiceClient.from_service_account_json(key_path)
        else:
            client = discoveryengine.SearchServiceClient()
        
        # 검색 환경설정 경로 구성
        serving_config = client.serving_config_path(
            project=GOOGLE_CLOUD_PROJECT,
            location="global",
            data_store=VERTEX_DATA_STORE_ID,
            serving_config="default_search",
        )
        
        # 검색 요청 생성
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=keyword,
            page_size=10,
        )
        
        # 결과 호출
        page = client.search(request)
        
        for idx, result in enumerate(page.results):
            data = result.document.derived_struct_data
            title = data.get('title', '제목 없음')
            link = data.get('link', '')
            snippet = data.get('snippets', [{}])[0].get('snippet', '') if data.get('snippets') else ''
            
            # 도메인 추출
            domain_name = "구글 검색몰"
            if link:
                try:
                    domain_name = urllib.parse.urlparse(link).netloc
                except:
                    pass
            
            # 필터링 로직 (무관한 키워드)
            bad_words = [
                "책", "도서", "장난감", "피규어", "식품", "즙", "액", "환", "장떡", "건강", "효능", "먹는", "요리", "레시피", "반찬", "식당", "맛집", "키트", "DIY", "게임", "동화", "소설",
                "분석기", "검출기", "계측기", "센서", "테스트", "농도", "함량", "질소", "산소", "측정", "tester", "sensor", "analyzer", "detector"
            ]
            
            # 검색결과 페이지 필터링 (개별 상품 페이지가 아닌 쇼핑몰 자체 검색결과 페이지 제외)
            search_patterns = ["/search", "search?", "keyword=", "kwd=", "total-search", "q=", "query="]
            
            if any(bad in title.lower() for bad in bad_words) or any(bad in snippet.lower() for bad in bad_words):
                continue
            
            if any(p in link.lower() for p in search_patterns):
                continue
            
            seller_formatted = f"[업체명] {domain_name}\n[대표자] 웹에서확인\n[주소] 웹에서확인\n[연락처] 웹에서확인"
            
            scraped_items.append({
                "id": f"googleapi_{int(time.time()*1000)}_{idx}",
                "platform": f"구글AI검색 ({domain_name})",
                "item": keyword,
                "seller": seller_formatted, 
                "url": link,
                "date": datetime.now().isoformat()
            })
            
    except Exception as e:
        print(f"구글 Vertex AI 검색 에러: {e}")
        print("💡 팁: 'gcloud auth application-default login' 명령어로 구글 인증이 필요할 수 있습니다.")
        
    return scraped_items

def run_scraper():
    print("--- 엽구 불법 판매 온라인 감시 시작 ---")
    all_new_items = []
    
    for kw in KEYWORDS:
        # 네이버 쇼핑 검색 결과 취합
        naver_results = search_naver_shopping(kw)
        all_new_items.extend(naver_results)

        
        # 구글 Vertex AI 검색 결과 취합
        google_results = search_google_vertex(kw)
        all_new_items.extend(google_results)
        
        time.sleep(1) # API Rate limit 방지
        
    save_data(all_new_items)
    print("--- 감시 작업 종료 ---")

if __name__ == "__main__":
    # 단독 실행 시 바로 수집 프로세스 구동
    run_scraper()
