import unittest
from datetime import datetime

from bs4 import BeautifulSoup

import scraper


class ScraperRuleTests(unittest.TestCase):
    def test_non_detail_pages_are_rejected(self):
        self.assertEqual(
            scraper.infer_page_type("https://m.bunjang.co.kr/keywords/%EC%98%AC%EB%AC%B4"),
            "search",
        )
        self.assertEqual(scraper.infer_page_type("https://catalog.11st.co.kr/pc/482118941"), "catalog")

    def test_mobile_and_desktop_gmarket_urls_share_a_key(self):
        mobile = "https://m.gmarket.co.kr/vi/product/2219208860"
        legacy = "https://mg.gmarket.co.kr/Item?goodscode=2219208860"
        self.assertEqual(scraper.canonical_product_key(mobile), scraper.canonical_product_key(legacy))

    def test_mobile_and_desktop_store_urls_share_product_keys(self):
        modumall_pc = "https://www.modumall.co.kr/?act=shop.goods_view&CM=2483"
        modumall_mobile = "https://www.modumall.co.kr/m/?act=shop.goods_view&CM=2483&page=1"
        self.assertEqual(
            scraper.canonical_product_key(modumall_pc),
            scraper.canonical_product_key(modumall_mobile),
        )
        self.assertEqual(
            scraper.canonical_product_key("https://www.11st.co.kr/products/9466019163"),
            scraper.canonical_product_key("http://m.11st.co.kr/products/ma/9466019163"),
        )

    def test_duplicates_are_merged_within_one_run(self):
        records = [
            {"url": "https://m.gmarket.co.kr/vi/product/2219208860", "item": "포획틀"},
            {"url": "https://mg.gmarket.co.kr/Item?goodscode=2219208860", "item": "포획틀"},
        ]
        self.assertEqual(len(scraper.deduplicate_records(records)), 1)

    def test_ambiguous_changae_blind_is_not_a_trap_match(self):
        record = {
            "url": "https://www.11st.co.kr/products/2117469460",
            "page_type": "product",
            "query": "창애",
            "title": "창애드림 창틀용 블라인드 빗물차단",
            "description": "가격 39,800원 배송",
            "price": "39800",
        }
        result = scraper.score_relevance(record)
        self.assertEqual(result["suggested_status"], "auto_rejected")
        self.assertEqual(result["relevance_score"], 0)

    def test_explicit_snare_sale_remains_a_candidate(self):
        record = {
            "url": "https://www.11st.co.kr/products/123456",
            "page_type": "product",
            "query": "올무",
            "title": "스프링 올무 야생동물 포획용 판매",
            "description": "가격 및 배송 안내",
            "price": "15000",
        }
        result = scraper.score_relevance(record)
        self.assertEqual(result["suggested_status"], "candidate")
        self.assertGreaterEqual(result["relevance_score"], 70)

    def test_article_is_not_treated_as_a_sale_listing(self):
        result = scraper.score_relevance({
            "url": "https://example.com/news/123",
            "page_type": "article",
            "query": "올무",
            "title": "온라인 올무 판매 적발 보도",
            "description": "수사 결과를 알리는 기사",
        })
        self.assertEqual(result["suggested_status"], "auto_rejected")

    def test_generic_shop_urls_can_be_product_pages(self):
        self.assertEqual(scraper.infer_page_type("https://gardian.kr/shop_view/?idx=31"), "product")
        self.assertEqual(
            scraper.infer_page_type("https://safe.onoffmarket.com/shop/item.php?it_id=1768547683"),
            "product",
        )
        self.assertEqual(
            scraper.infer_page_type("https://modumall.co.kr/?act=shop.goods_view&CM=2483"),
            "product",
        )

    def test_product_url_without_trap_evidence_is_rejected(self):
        result = scraper.score_relevance({
            "url": "https://m.gmarket.co.kr/vi/product/123",
            "page_type": "product",
            "query": "올무",
            "title": "",
            "description": "",
        })
        self.assertEqual(result["suggested_status"], "auto_rejected")

    def test_standalone_changae_name_is_not_a_trap(self):
        result = scraper.score_relevance({
            "url": "https://example.com/products/123",
            "page_type": "product",
            "query": "창애",
            "title": "창애 맛의 창고 식탁 선물세트",
            "description": "배송 상품",
        })
        self.assertEqual(result["matched_terms"], [])
        self.assertEqual(result["suggested_status"], "auto_rejected")

    def test_unknown_information_page_needs_stronger_evidence(self):
        result = scraper.score_relevance({
            "url": "https://example.org/policy/read/1",
            "page_type": "unknown",
            "query": "올무",
            "title": "올무 판매는 불법입니다",
            "description": "법률 안내문입니다",
        })
        self.assertEqual(result["suggested_status"], "auto_rejected")

    def test_island_shipping_does_not_trigger_book_penalty(self):
        result = scraper.score_relevance({
            "url": "https://example.com/shop_view/?idx=22",
            "page_type": "product",
            "query": "멧돼지 포획틀",
            "title": "조립식 멧돼지포획틀",
            "description": "주문제작 상품, 도서지역 배송 불가",
            "price": "1600000",
        })
        self.assertEqual(result["suggested_status"], "candidate")
        self.assertGreaterEqual(result["relevance_score"], 80)

    def test_risk_grade_separates_snare_and_capture_cage(self):
        high = scraper.assess_risk({
            "status": "candidate",
            "page_type": "product",
            "title": "멧돼지 스프링올무 발목트랩",
        })
        medium = scraper.assess_risk({
            "status": "candidate",
            "page_type": "product",
            "title": "유기견 구조용 철망 포획틀 케이지",
        })
        self.assertEqual(high["risk_level"], "high")
        self.assertEqual(medium["risk_level"], "medium")

    def test_verified_seller_information_is_reused(self):
        verified = {
            "url": "https://shop.example.com/products/1",
            "last_seen": "2026-08-05T09:00:00",
            "seller_info": {
                "name": "산들상회",
                "representative": "홍길동",
                "address": "서울시 중구",
                "phone": "02-123-4567",
                "business_number": "123-45-67890",
                "source_url": "https://shop.example.com/stores/77?product=1",
                "confidence": "manual",
            },
        }
        master = scraper.build_seller_master([verified])
        reused = scraper.apply_seller_master_to_record({
            "url": "https://shop.example.com/products/2",
            "seller_info": {
                "name": "산들상회",
                "representative": "",
                "address": "",
                "phone": "",
                "business_number": "",
                "source_url": "https://shop.example.com/stores/77?product=2",
                "confidence": "platform_store",
            },
        }, master)
        self.assertEqual(reused["seller_info"]["representative"], "홍길동")
        self.assertEqual(reused["seller_info"]["business_number"], "123-45-67890")
        self.assertTrue(reused["seller_master_id"].startswith("seller_"))

    def test_mirrored_listing_titles_form_a_cluster(self):
        records = [
            {
                "id": "a", "status": "candidate", "canonical_key": "a", "price": "48500",
                "title": "멧돼지포획트랩 유해동물 포획용 스프링올무 발목트랩 제작 - 온오프안전",
            },
            {
                "id": "b", "status": "candidate", "canonical_key": "b", "price": "48500",
                "title": "멧돼지포획트랩 유해동물 포획용 스프링올무 발목트랩 제작 - 온오프스마트",
            },
        ]
        clustered = scraper.assign_duplicate_clusters(records)
        self.assertEqual(clustered[0]["cluster_id"], clustered[1]["cluster_id"])
        self.assertEqual(clustered[0]["duplicate_count"], 2)

    def test_inline_footer_business_information_is_parsed(self):
        soup = BeautifulSoup("""
            <footer>
              <div>상품 옵션 ㅣ 전화 : 부스</div>
              <div>상호 : (주)온오프마켓 ㅣ 대표자명 : 이현정, 신건수 ㅣ 사업자등록번호 : 105-88-05007</div>
              <div>전화 : 1544-5269 ㅣ 주소 : 경기도 고양시 일산동구 백마로 195</div>
            </footer>
        """, "html.parser")
        seller = scraper._extract_public_business_info(soup, "https://shop.example.com/item/1")
        self.assertEqual(seller["name"], "(주)온오프마켓")
        self.assertEqual(seller["representative"], "이현정, 신건수")
        self.assertEqual(seller["business_number"], "105-88-05007")
        self.assertEqual(seller["phone"], "1544-5269")

    def test_platform_table_seller_information_is_parsed(self):
        soup = BeautifulSoup("""
            <table>
              <tr><th>판매자</th><td>산들스토어</td></tr>
              <tr><th>상호명</th><td>산들무역 주식회사</td></tr>
              <tr><th>대표자</th><td>홍길동</td></tr>
              <tr><th>반품/교환지 주소</th><td>서울시 중구</td></tr>
            </table>
        """, "html.parser")
        seller = scraper._extract_labeled_platform_info(soup, "https://market.example.com/products/1")
        self.assertEqual(seller["name"], "산들무역 주식회사")
        self.assertEqual(seller["store_name"], "산들스토어")
        self.assertEqual(seller["representative"], "홍길동")
        self.assertEqual(seller["confidence"], "platform_public_info")

    def test_mobile_11st_uses_desktop_page_for_seller_details(self):
        self.assertEqual(
            scraper._desktop_fallback_url("http://m.11st.co.kr/products/ma/9466019163"),
            "https://www.11st.co.kr/products/9466019163",
        )

    def test_javascript_redirect_target_is_extracted(self):
        target = scraper._javascript_redirect_url(
            'location.replace("https://shop.example.com/item/7?from=compare");',
            "https://compare.example.com/go",
        )
        self.assertEqual(target, "https://shop.example.com/item/7?from=compare")

    def test_free_search_plan_rotates_sources_without_paid_google(self):
        plan = scraper.build_free_search_plan(datetime(2026, 8, 5))
        self.assertEqual(len(plan), 29)
        self.assertEqual({item["source"] for item in plan}, {"naver_web", "naver_blog", "naver_cafe"})
        self.assertTrue(any("site:" in item["query"] for item in plan))
        self.assertTrue(any(item["sort"] == "date" for item in plan))

    def test_public_cafe_sale_post_can_become_a_candidate(self):
        record = {
            "source": "naver_cafe",
            "url": "https://cafe.naver.com/example/123",
            "page_type": "listing_post",
            "query": "스프링 올무",
            "title": "야생동물용 스프링 올무 팝니다",
            "description": "가격 30,000원, 택배거래 가능합니다",
        }
        self.assertTrue(scraper._looks_like_community_listing(record))
        self.assertEqual(scraper.score_relevance(record)["suggested_status"], "candidate")

    def test_blog_enforcement_article_is_not_a_sale_listing(self):
        record = {
            "source": "naver_blog",
            "url": "https://blog.naver.com/example/123",
            "page_type": "article",
            "query": "올무",
            "title": "온라인 올무 판매 적발 사례",
            "description": "불법 판매 단속 결과를 안내합니다",
        }
        self.assertFalse(scraper._looks_like_community_listing(record))
        self.assertEqual(scraper.score_relevance(record)["suggested_status"], "auto_rejected")

    def test_category_page_can_yield_product_detail_links(self):
        soup = BeautifulSoup("""
            <div class="item">
              <a href="/products/12345">스프링 올무 판매 상품</a>
            </div>
            <a href="/category/traps">전체 카테고리</a>
        """, "html.parser")
        parent = {
            "source": "naver_web", "query": "스프링 올무", "item": "스프링 올무",
            "title": "스프링 올무 상품 검색", "description": "판매 결과",
        }
        found = scraper._extract_discovered_product_records(
            soup, "https://shop.example.com/search?q=trap", parent,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://shop.example.com/products/12345")
        self.assertEqual(found[0]["discovered_from"], "https://shop.example.com/search?q=trap")

    def test_rodent_or_tnr_cage_without_wildlife_target_is_rejected(self):
        for title in (
            "길고양이 TNR 중성화 구조용 포획틀 케이지",
            "쥐포획 케이지 재사용 쥐덫 포획틀",
            "사슴벌레 등화채집 장비 포획틀",
            "마우스 동물 트랩 및 케이지",
        ):
            result = scraper.score_relevance({
                "url": "https://shop.example.com/products/1",
                "page_type": "product",
                "query": "포획틀",
                "title": title,
                "description": "가격 30,000원 배송 상품",
                "price": "30000",
            })
            self.assertEqual(result["suggested_status"], "auto_rejected", title)

    def test_wildlife_capture_cage_remains_for_review(self):
        result = scraper.score_relevance({
            "url": "https://shop.example.com/products/2",
            "page_type": "product",
            "query": "포획틀",
            "title": "멧돼지 고라니 야생동물 포획틀",
            "description": "가격 및 배송 안내",
            "price": "150000",
        })
        self.assertEqual(result["suggested_status"], "candidate")

    def test_domestic_business_number_is_actionable(self):
        result = scraper.normalize_record({
            "url": "https://market.example.com/products/10",
            "title": "스프링 올무 판매",
            "seller_info": {
                "name": "산들상회", "business_number": "123-45-67890",
                "address": "", "phone": "", "confidence": "manual",
            },
        })
        self.assertEqual(result["seller_jurisdiction"], "domestic")
        self.assertEqual(result["enforcement_status"], "actionable")
        self.assertIn("사업자등록번호", result["jurisdiction_reasons"][0])

    def test_foreign_seller_on_korean_market_is_excluded(self):
        result = scraper.normalize_record({
            "url": "https://www.11st.co.kr/products/8886185964",
            "title": "멧돼지 덫 올무 포획 트랩",
            "seller_info": {
                "name": "Dalian Junyouqi Department Store Co., Ltd",
                "address": "Dalian, Liaoning, 116000 China",
                "phone": "", "business_number": "", "confidence": "platform_public_info",
            },
        })
        self.assertEqual(result["seller_jurisdiction"], "foreign")
        self.assertEqual(result["enforcement_status"], "excluded_foreign")

    def test_domestic_purchase_agent_remains_actionable(self):
        result = scraper.normalize_record({
            "url": "https://www.11st.co.kr/products/8744871620",
            "title": "멧돼지 올무 [해외구매]",
            "seller_info": {
                "name": "티에스이커머스",
                "address": "경기도 화성시 동탄기흥로 602",
                "phone": "", "business_number": "", "confidence": "platform_public_info",
            },
        })
        self.assertEqual(result["seller_jurisdiction"], "domestic")
        self.assertEqual(result["enforcement_status"], "actionable")

    def test_marketplace_name_alone_does_not_prove_jurisdiction(self):
        result = scraper.normalize_record({
            "url": "https://m.shoppinghow.kakao.com/m/product/E5274406319/",
            "title": "너구리 포획틀 [해외구매]",
            "seller_info": {
                "name": "옥션", "address": "", "phone": "", "business_number": "",
                "confidence": "comparison_merchant",
            },
        })
        self.assertEqual(result["seller_jurisdiction"], "unknown")
        self.assertEqual(result["enforcement_status"], "seller_verification_needed")

    def test_manual_jurisdiction_override_is_preserved(self):
        result = scraper.normalize_record({
            "url": "https://market.example.com/products/11",
            "title": "스프링 올무 판매",
            "seller_jurisdiction_override": "foreign",
            "seller_info": {
                "name": "판매자", "address": "서울특별시 중구", "confidence": "manual",
            },
        })
        self.assertEqual(result["seller_jurisdiction"], "foreign")
        self.assertEqual(result["jurisdiction_confidence"], "manual")

    def test_report_filter_keeps_only_confirmed_domestic_sellers(self):
        import app as app_module

        rows = [
            {
                "url": "https://shop.example.com/products/1", "status": "confirmed",
                "title": "스프링 올무 판매",
                "seller_info": {"name": "국내상회", "address": "서울특별시 중구"},
            },
            {
                "url": "https://shop.example.com/products/2", "status": "confirmed",
                "title": "스프링 올무 판매",
                "seller_info": {"name": "Foreign Store", "address": "Dalian, Liaoning, China"},
            },
            {
                "url": "https://shop.example.com/products/3", "status": "candidate",
                "title": "스프링 올무 판매",
                "seller_info": {"name": "국내상회", "address": "경기도 수원시"},
            },
        ]
        filtered = app_module._filter_enforceable_report_records(rows)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["seller_info"]["name"], "국내상회")


if __name__ == "__main__":
    unittest.main()
