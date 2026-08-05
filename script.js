const LEGACY_DB_KEY = 'trap_monitor_data';
const MIGRATION_KEY = 'trap_monitor_server_migrated_v2';

let records = [];
let activeFilter = 'candidate';
let activeRiskFilter = 'all';

const STATUS_META = {
    candidate: { label: '검토 대기', className: 'status-candidate' },
    confirmed: { label: '확정', className: 'status-confirmed' },
    rejected: { label: '검토 제외', className: 'status-rejected' },
    auto_rejected: { label: '자동 제외', className: 'status-auto-rejected' },
};

const PAGE_TYPE_LABELS = {
    product: '상품 상세',
    search: '검색 결과',
    category: '카테고리',
    catalog: '가격비교·카탈로그',
    seller_profile: '판매자 프로필',
    article: '기사·정보 문서',
    listing_post: '공개 판매글',
    unknown: '유형 미확인',
};

const SOURCE_LABELS = {
    naver_web: '네이버 웹문서',
    naver_blog: '네이버 블로그',
    naver_cafe: '네이버 공개 카페',
    link_discovery: '상세링크 추가 발견',
    google_vertex: 'Google 검색',
    manual: '수동 등록',
    search: '기존 자동검색',
};

const RISK_META = {
    high: { label: '고위험', className: 'risk-high' },
    medium: { label: '검토 필요', className: 'risk-medium' },
    low: { label: '낮음', className: 'risk-low' },
};

async function api(path, options = {}) {
    const response = await fetch(path, {
        ...options,
        headers: {
            ...(options.body ? { 'Content-Type': 'application/json' } : {}),
            ...(options.headers || {}),
        },
    });
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
        const message = typeof payload === 'object' ? payload.message : payload;
        throw new Error(message || `서버 오류 (${response.status})`);
    }
    return payload;
}

function formatDate(dateString) {
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return '-';
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function formatMonth(dateString) {
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return '';
    return `${date.getFullYear()}년 ${date.getMonth() + 1}월`;
}

function sellerCompleteness(seller = {}) {
    return ['name', 'store_name', 'representative', 'address', 'phone', 'business_number']
        .filter(key => String(seller[key] || '').trim()).length;
}

function appendText(parent, tagName, text, className = '') {
    const element = document.createElement(tagName);
    element.textContent = text;
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
}

async function migrateLegacyBrowserData() {
    if (localStorage.getItem(MIGRATION_KEY)) return;
    const legacy = JSON.parse(localStorage.getItem(LEGACY_DB_KEY) || '[]');
    const realRecords = legacy.filter(item => item && item.url !== 'https://daangn.com/articles/12345');
    if (realRecords.length) {
        const normalized = realRecords.map(item => ({
            ...item,
            source: item.source || (/^(?:google|naver)_/.test(String(item.id || '')) ? 'search' : 'manual'),
        }));
        await api('/api/records/import', {
            method: 'POST',
            body: JSON.stringify({ records: normalized }),
        });
    }
    localStorage.setItem(MIGRATION_KEY, new Date().toISOString());
}

async function loadRecords() {
    const payload = await api(`/api/records?t=${Date.now()}`);
    records = payload.records || [];
    renderDashboard();
    initReportTab();
}

function renderStats() {
    const now = new Date();
    const confirmedThisMonth = records.filter(record => {
        const date = new Date(record.reviewed_at || record.date);
        return record.status === 'confirmed'
            && date.getFullYear() === now.getFullYear()
            && date.getMonth() === now.getMonth();
    }).length;
    const candidateCount = records.filter(record => record.status === 'candidate').length;
    const excludedCount = records.filter(record => ['rejected', 'auto_rejected'].includes(record.status)).length;
    const sellerMissingCount = records.filter(record =>
        ['candidate', 'confirmed'].includes(record.status) && sellerCompleteness(record.seller_info) < 3
    ).length;
    const highRiskCount = records.filter(record =>
        record.status === 'candidate' && record.risk_level === 'high'
    ).length;
    const duplicateClusters = new Set(records
        .filter(record => ['candidate', 'confirmed'].includes(record.status) && Number(record.duplicate_count || 1) > 1)
        .map(record => record.cluster_id)
        .filter(Boolean));

    document.getElementById('highRiskCount').textContent = highRiskCount;
    document.getElementById('candidateCount').textContent = candidateCount;
    document.getElementById('confirmedCount').textContent = confirmedThisMonth;
    document.getElementById('sellerMissingCount').textContent = sellerMissingCount;
    document.getElementById('excludedCount').textContent = excludedCount;
    document.getElementById('duplicateClusterCount').textContent = duplicateClusters.size;
}

function matchesFilter(record) {
    const statusMatches = activeFilter === 'all'
        || (activeFilter === 'rejected' && ['rejected', 'auto_rejected'].includes(record.status))
        || record.status === activeFilter;
    if (!statusMatches) return false;
    if (activeRiskFilter === 'all') return true;
    if (activeRiskFilter === 'duplicates') return Number(record.duplicate_count || 1) > 1;
    return record.risk_level === activeRiskFilter;
}

function createStatusBadge(record) {
    const meta = STATUS_META[record.status] || STATUS_META.candidate;
    const badge = document.createElement('span');
    badge.className = `status-badge ${meta.className}`;
    badge.textContent = meta.label;
    return badge;
}

function createSellerCell(record) {
    const cell = document.createElement('td');
    const seller = record.seller_info || {};
    const completeness = sellerCompleteness(seller);
    appendText(cell, 'strong', seller.name || seller.store_name || '업체명 미확인');
    const details = [
        seller.store_name && seller.store_name !== seller.name ? `판매점 ${seller.store_name}` : '',
        seller.representative ? `대표자 ${seller.representative}` : '',
        seller.phone ? `연락처 ${seller.phone}` : '',
        seller.business_number ? `사업자번호 ${seller.business_number}` : '',
        seller.address || '',
    ].filter(Boolean);
    if (details.length) appendText(cell, 'p', details.join(' · '), 'cell-subtext');
    const merchants = record.merchant_info || {};
    if (Array.isArray(merchants.names) && merchants.names.length) {
        appendText(cell, 'p', `가격비교 판매처 ${merchants.count || merchants.names.length}곳 · ${merchants.names.join(', ')}`, 'cell-subtext');
    }
    if (seller.confidence === 'public_business_info') {
        appendText(cell, 'span', '공개 사업자정보 자동확인', 'seller-complete');
    } else if (seller.confidence === 'platform_public_info') {
        appendText(cell, 'span', '플랫폼 공개 판매자정보 확인', 'seller-complete');
    } else if (seller.confidence === 'comparison_merchant') {
        appendText(cell, 'span', '가격비교 판매처 확인', 'seller-partial');
    } else if (seller.confidence === 'platform_store') {
        appendText(cell, 'span', '판매점명 자동확인', 'seller-complete');
    } else if (record.seller_lookup_status === 'blocked') {
        appendText(cell, 'span', '플랫폼 접근 제한', 'seller-blocked');
    } else if (record.seller_lookup_status === 'not_public') {
        appendText(cell, 'span', '공개 판매자정보 미제공', 'seller-missing');
    } else if (completeness < 3) {
        appendText(cell, 'span', '정보 보완 필요', 'seller-missing');
    } else {
        appendText(cell, 'span', '판매자정보 확인', 'seller-complete');
    }
    if (record.seller_master_id) {
        const verified = record.seller_verified_at ? ` · ${formatDate(record.seller_verified_at)}` : '';
        appendText(cell, 'span', `판매자 마스터 연결${verified}`, 'seller-master-badge');
    }
    if (seller.source_url) {
        const sourceLink = document.createElement('a');
        sourceLink.href = seller.source_url;
        sourceLink.target = '_blank';
        sourceLink.rel = 'noopener noreferrer';
        sourceLink.className = 'seller-source-link';
        sourceLink.textContent = '정보 출처';
        cell.appendChild(sourceLink);
    }
    return cell;
}

function createListingCell(record) {
    const cell = document.createElement('td');
    appendText(cell, 'strong', record.title || `${record.query || record.item} 검색 결과`, 'listing-title');
    const metaParts = [
        record.item || '-',
        PAGE_TYPE_LABELS[record.page_type] || record.page_type || '유형 미확인',
        SOURCE_LABELS[record.source] || record.source || '검색원 미확인',
    ];
    if (record.price) {
        const numericPrice = Number(String(record.price).replace(/[^0-9.]/g, ''));
        metaParts.push(Number.isFinite(numericPrice) ? `${numericPrice.toLocaleString('ko-KR')}원` : String(record.price));
    }
    const meta = metaParts.join(' · ');
    appendText(cell, 'p', meta, 'cell-subtext');
    if (Number(record.duplicate_count || 1) > 1) {
        appendText(cell, 'span', `유사상품 ${record.duplicate_count}건`, 'duplicate-badge');
    }
    if (record.description) {
        const clipped = record.description.length > 110 ? `${record.description.slice(0, 110)}…` : record.description;
        appendText(cell, 'p', clipped, 'listing-description');
    }
    return cell;
}

function createScoreCell(record) {
    const cell = document.createElement('td');
    const score = Number(record.relevance_score || 0);
    const scoreBadge = appendText(cell, 'span', `${score}점`, `score-badge score-${record.confidence || 'low'}`);
    scoreBadge.title = (record.relevance_reasons || []).join('\n');
    const reason = (record.relevance_reasons || [])[0] || '판정 근거 없음';
    appendText(cell, 'p', reason, 'cell-subtext');
    const risk = RISK_META[record.risk_level] || RISK_META.low;
    const riskBadge = appendText(cell, 'span', risk.label, `risk-badge ${risk.className}`);
    riskBadge.title = (record.risk_reasons || []).join('\n');
    return cell;
}

function createActionCell(record) {
    const cell = document.createElement('td');
    const reviewButton = document.createElement('button');
    reviewButton.type = 'button';
    reviewButton.className = 'btn btn-primary btn-sm';
    reviewButton.textContent = record.status === 'confirmed' ? '정보 수정' : '검토';
    reviewButton.addEventListener('click', () => openReviewModal(record.id));
    cell.appendChild(reviewButton);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'btn-icon-delete';
    deleteButton.title = '목록에서 삭제';
    deleteButton.innerHTML = '<i class="fa-solid fa-trash"></i>';
    deleteButton.addEventListener('click', () => deleteRecord(record.id));
    cell.appendChild(deleteButton);
    return cell;
}

function renderMonitoringList() {
    const tbody = document.getElementById('monitoringList');
    tbody.replaceChildren();
    const riskOrder = { high: 3, medium: 2, low: 1 };
    const visible = records
        .filter(matchesFilter)
        .sort((a, b) => {
            const riskDifference = (riskOrder[b.risk_level] || 0) - (riskOrder[a.risk_level] || 0);
            if (riskDifference) return riskDifference;
            return new Date(b.last_seen || b.date) - new Date(a.last_seen || a.date);
        });

    if (!visible.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'empty-state';
        cell.textContent = activeFilter === 'candidate' ? '현재 검토 대기 후보가 없습니다.' : '해당 상태의 자료가 없습니다.';
        row.appendChild(cell);
        tbody.appendChild(row);
        return;
    }

    visible.forEach(record => {
        const row = document.createElement('tr');
        const statusCell = document.createElement('td');
        statusCell.appendChild(createStatusBadge(record));
        row.appendChild(statusCell);
        appendText(row, 'td', record.platform || '알 수 없음', 'platform-cell');
        row.appendChild(createListingCell(record));
        row.appendChild(createScoreCell(record));
        row.appendChild(createSellerCell(record));

        const linkCell = document.createElement('td');
        const link = document.createElement('a');
        link.href = record.final_url || record.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'external-link';
        link.textContent = '게시물 열기';
        linkCell.appendChild(link);
        row.appendChild(linkCell);

        appendText(row, 'td', formatDate(record.first_seen || record.date));
        row.appendChild(createActionCell(record));
        tbody.appendChild(row);
    });
}

function renderDashboard() {
    renderStats();
    renderMonitoringList();
}

function setActiveFilter(filter) {
    activeFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(button => {
        button.classList.toggle('active', button.dataset.filter === filter);
    });
    renderMonitoringList();
}

function setRiskFilter(filter) {
    activeRiskFilter = filter;
    renderMonitoringList();
}

function openReviewModal(recordId) {
    const record = records.find(item => item.id === recordId);
    if (!record) return;
    const seller = record.seller_info || {};
    const risk = RISK_META[record.risk_level] || RISK_META.low;
    const riskSummary = document.getElementById('review_risk_summary');
    riskSummary.textContent = `${risk.label} · ${(record.risk_reasons || ['판정 근거 없음'])[0]}`;
    riskSummary.className = `risk-badge ${risk.className}`;
    const clusterSummary = document.getElementById('review_cluster_summary');
    clusterSummary.textContent = Number(record.duplicate_count || 1) > 1
        ? `같은 상품으로 추정되는 URL ${record.duplicate_count}건` : '단일 상품 URL';
    document.getElementById('review_record_id').value = record.id;
    document.getElementById('review_title').value = record.title || '';
    const itemSelect = document.getElementById('review_item');
    const desiredItem = record.item && record.item.includes('올무') ? '올무 (스프링올무 포함)' : record.item;
    itemSelect.value = [...itemSelect.options].some(option => option.value === desiredItem)
        ? desiredItem : '기타 불법 엽구';
    document.getElementById('review_seller_name').value = seller.name || '';
    document.getElementById('review_seller_store_name').value = seller.store_name || '';
    document.getElementById('review_seller_rep').value = seller.representative || '';
    document.getElementById('review_seller_phone').value = seller.phone || '';
    document.getElementById('review_business_number').value = seller.business_number || '';
    document.getElementById('review_seller_address').value = seller.address || '';
    document.getElementById('review_seller_source').value = seller.source_url || record.url || '';
    document.getElementById('review_note').value = record.review_note || '';
    document.getElementById('reviewModal').classList.add('open');
    document.getElementById('reviewModal').setAttribute('aria-hidden', 'false');
}

function closeReviewModal() {
    document.getElementById('reviewModal').classList.remove('open');
    document.getElementById('reviewModal').setAttribute('aria-hidden', 'true');
}

function reviewPayload(status) {
    return {
        id: document.getElementById('review_record_id').value,
        status,
        title: document.getElementById('review_title').value.trim(),
        item: document.getElementById('review_item').value,
        review_note: document.getElementById('review_note').value.trim(),
        seller_info: {
            name: document.getElementById('review_seller_name').value.trim(),
            store_name: document.getElementById('review_seller_store_name').value.trim(),
            representative: document.getElementById('review_seller_rep').value.trim(),
            phone: document.getElementById('review_seller_phone').value.trim(),
            business_number: document.getElementById('review_business_number').value.trim(),
            address: document.getElementById('review_seller_address').value.trim(),
            source_url: document.getElementById('review_seller_source').value.trim(),
            confidence: 'manual',
        },
    };
}

async function saveReview(status) {
    await api('/api/records/review', {
        method: 'POST',
        body: JSON.stringify(reviewPayload(status)),
    });
    closeReviewModal();
    await loadRecords();
}

async function deleteRecord(id) {
    if (!confirm('이 자료를 목록에서 삭제할까요? 보고서에서도 제외됩니다.')) return;
    await api('/api/records/delete', {
        method: 'POST',
        body: JSON.stringify({ id }),
    });
    await loadRecords();
}

function setupTabs() {
    document.querySelectorAll('.nav-item').forEach(tab => {
        tab.addEventListener('click', event => {
            event.preventDefault();
            document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            tab.classList.add('active');
            const targetId = `tab-${tab.dataset.tab}`;
            document.getElementById(targetId).classList.add('active');
            if (targetId === 'tab-dashboard') renderDashboard();
            if (targetId === 'tab-report-export') initReportTab();
        });
    });
}

function setupManualForm() {
    document.getElementById('recordForm').addEventListener('submit', async event => {
        event.preventDefault();
        const payload = {
            platform: document.getElementById('platform').value.trim(),
            title: document.getElementById('listing_title').value.trim(),
            item: document.getElementById('item').value,
            url: document.getElementById('url').value.trim(),
            seller_info: {
                name: document.getElementById('seller_name').value.trim(),
                representative: document.getElementById('seller_rep').value.trim(),
                address: document.getElementById('seller_address').value.trim(),
                phone: document.getElementById('seller_phone').value.trim(),
                business_number: document.getElementById('seller_business_number').value.trim(),
                source_url: document.getElementById('url').value.trim(),
                confidence: 'manual',
            },
        };
        try {
            await api('/api/records/manual', { method: 'POST', body: JSON.stringify(payload) });
            event.target.reset();
            await loadRecords();
            document.querySelector('.nav-item[data-tab="dashboard"]').click();
            setActiveFilter('confirmed');
        } catch (error) {
            alert(`등록 실패: ${error.message}`);
        }
    });
    document.getElementById('clearFormBtn').addEventListener('click', () => document.getElementById('recordForm').reset());
}

function confirmedRecords() {
    return records.filter(record => record.status === 'confirmed');
}

function initReportTab() {
    const select = document.getElementById('reportMonth');
    const months = [...new Set(confirmedRecords().map(item => formatMonth(item.date)).filter(Boolean))].sort().reverse();
    const currentValue = select.value;
    select.replaceChildren();
    if (!months.length) {
        const option = new Option('확정 데이터 없음', '');
        select.appendChild(option);
    } else {
        months.forEach(month => select.appendChild(new Option(month, month)));
        if (months.includes(currentValue)) select.value = currentValue;
    }
    renderReportList();
}

function renderReportList() {
    const selectedMonth = document.getElementById('reportMonth').value;
    const filtered = confirmedRecords().filter(item => formatMonth(item.date) === selectedMonth);
    const tbody = document.getElementById('hwpTableBody');
    tbody.replaceChildren();

    let snareCount = 0;
    let trapCount = 0;
    let otherCount = 0;
    filtered.forEach(record => {
        if ((record.item || '').includes('올무') || (record.item || '').includes('창애')) snareCount++;
        else if ((record.item || '').includes('포획틀')) trapCount++;
        else otherCount++;
        const seller = record.seller_info || {};
        const row = document.createElement('tr');
        [record.platform, record.item, record.final_url || record.url, seller.name, seller.representative,
            seller.address, seller.phone].forEach((value, index) => {
            const cell = document.createElement('td');
            cell.style.cssText = 'vertical-align:middle; border:1px solid #000; padding:5px;';
            if (index === 2) {
                const link = document.createElement('a');
                link.href = value || '#';
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = value || '-';
                link.style.cssText = 'color:blue; text-decoration:underline;';
                cell.appendChild(link);
            } else {
                cell.textContent = value || '-';
            }
            row.appendChild(cell);
        });
        tbody.appendChild(row);
    });

    if (!filtered.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.textContent = '해당 월에 확정된 데이터가 없습니다.';
        cell.style.cssText = 'text-align:center; border:1px solid #000; padding:10px;';
        row.appendChild(cell);
        tbody.appendChild(row);
    }

    document.getElementById('hwpReportTitle').textContent = `${selectedMonth || '월별'} 불법 엽구류 온라인 확정 보고`;
    document.getElementById('hwpTotalCount').textContent = filtered.length;
    document.getElementById('hwpSnareCount').textContent = snareCount;
    document.getElementById('hwpTrapCount').textContent = trapCount;
    document.getElementById('hwpOtherCount').textContent = otherCount;
}

function setupReportActions() {
    document.getElementById('reportMonth').addEventListener('change', renderReportList);
    document.getElementById('copyTableBtn').addEventListener('click', () => {
        const range = document.createRange();
        range.selectNode(document.getElementById('hwpExportArea'));
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        try {
            document.execCommand('copy');
            alert('확정 보고서가 복사되었습니다. 한글 문서에 붙여넣으세요.');
        } finally {
            window.getSelection().removeAllRanges();
        }
    });

    document.getElementById('downloadExcelBtn').addEventListener('click', async () => {
        const button = document.getElementById('downloadExcelBtn');
        const month = document.getElementById('reportMonth').value;
        const data = confirmedRecords().filter(item => formatMonth(item.date) === month);
        if (!month || !data.length) {
            alert('다운로드할 확정 자료가 없습니다.');
            return;
        }
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 생성 중...';
        try {
            const response = await fetch('/generate-report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ month, data }),
            });
            if (!response.ok) throw new Error('엑셀 생성에 실패했습니다.');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `포획도구_판매처목록_${month}.xlsx`;
            anchor.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            alert(error.message);
        } finally {
            button.disabled = false;
            button.innerHTML = '<i class="fa-solid fa-file-excel"></i> 엑셀 양식 다운로드';
        }
    });
}

function setupScraperActions() {
    document.getElementById('runScraperBtn').addEventListener('click', async () => {
        const button = document.getElementById('runScraperBtn');
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 후보 탐색 중...';
        try {
            const result = await api('/run-scraper', { method: 'POST' });
            if (result.status !== 'success') throw new Error(result.error || '검색 실행 실패');
            await loadRecords();
            setActiveFilter('candidate');
            alert('자동 탐색이 완료되었습니다. 검토 대기 후보를 확인하세요.');
        } catch (error) {
            alert(`자동 탐색 실패: ${error.message}`);
        } finally {
            button.disabled = false;
            button.innerHTML = '<i class="fa-solid fa-magnifying-glass-arrow-right"></i> 자동 탐색 실행';
        }
    });

    document.getElementById('resetDataBtn').addEventListener('click', async () => {
        const confirmation = prompt('전체 데이터를 삭제하려면 "전체삭제"를 입력하세요. 이 작업은 되돌릴 수 없습니다.');
        if (confirmation !== '전체삭제') return;
        await api('/reset-data', { method: 'POST' });
        await loadRecords();
    });
}

async function loadSchedulerStatus() {
    try {
        const info = await api('/scheduler-status', { method: 'POST' });
        const element = document.getElementById('schedulerStatus');
        let text = `다음 자동 검색: ${info.next_run_date}`;
        if (info.last_run) text += ` · 최근 ${formatDate(info.last_run)} (+${info.added_count || 0}건)`;
        if (info.metrics?.free_mode) text += ` · 무료 검색 ${info.metrics.search_queries || 0}회`;
        if (info.metrics?.discovered_products) text += ` · 상세링크 ${info.metrics.discovered_products}건 발견`;
        element.textContent = text;
        const sourceElement = document.getElementById('sourceHealthStatus');
        const sources = info.sources || {};
        const sourceParts = Object.entries(sources).map(([key, value]) => {
            const label = SOURCE_LABELS[key] || key;
            if (key === 'link_discovery' && value.status === 'ok') {
                return `${label} ${value.discovered || 0}건`;
            }
            if (value.status === 'ok') return `${label} 정상 ${value.found || 0}건`;
            if (value.status === 'skipped') return `${label} 비활성`;
            return `${label} 오류`;
        });
        sourceElement.textContent = sourceParts.length ? sourceParts.join(' · ') : '검색원 실행 기록 없음';
        sourceElement.classList.toggle('has-error', Object.values(sources).some(value => value.status === 'error'));
    } catch (_) {
        // 서버 상태 표시는 부가 기능이므로 실패 시 화면을 막지 않습니다.
    }
}

function setupReviewModal() {
    document.getElementById('autoEnrichBtn').addEventListener('click', async () => {
        const button = document.getElementById('autoEnrichBtn');
        const recordId = document.getElementById('review_record_id').value;
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 공개정보 확인 중...';
        try {
            await api('/api/records/enrich', {
                method: 'POST',
                body: JSON.stringify({ id: recordId }),
            });
            await loadRecords();
            openReviewModal(recordId);
        } catch (error) {
            alert(`자동 확인 실패: ${error.message}`);
        } finally {
            button.disabled = false;
            button.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> 상품·판매자정보 자동 확인';
        }
    });
    document.getElementById('reviewForm').addEventListener('submit', async event => {
        event.preventDefault();
        try {
            await saveReview('confirmed');
            setActiveFilter('confirmed');
        } catch (error) {
            alert(`검토 저장 실패: ${error.message}`);
        }
    });
    document.getElementById('rejectReviewBtn').addEventListener('click', async () => {
        const note = document.getElementById('review_note').value.trim();
        if (!note) {
            alert('제외 사유를 입력해주세요.');
            return;
        }
        try {
            await saveReview('rejected');
            setActiveFilter('candidate');
        } catch (error) {
            alert(`제외 처리 실패: ${error.message}`);
        }
    });
    document.getElementById('closeReviewModal').addEventListener('click', closeReviewModal);
    document.getElementById('reviewModal').addEventListener('click', event => {
        if (event.target.id === 'reviewModal') closeReviewModal();
    });
}

async function boot() {
    setupTabs();
    setupManualForm();
    setupReportActions();
    setupScraperActions();
    setupReviewModal();
    document.querySelectorAll('.filter-btn').forEach(button => {
        button.addEventListener('click', () => setActiveFilter(button.dataset.filter));
    });
    document.getElementById('riskFilter').addEventListener('change', event => setRiskFilter(event.target.value));
    document.getElementById('currentDate').textContent = new Date().toLocaleDateString('ko-KR', {
        year: 'numeric', month: 'long', day: 'numeric', weekday: 'short',
    });
    try {
        await migrateLegacyBrowserData();
        await loadRecords();
        await loadSchedulerStatus();
    } catch (error) {
        console.error(error);
        document.getElementById('monitoringList').innerHTML = '<tr><td colspan="8" class="empty-state">서버에 연결할 수 없습니다. 실행.bat로 대시보드를 시작해주세요.</td></tr>';
    }
}

window.addEventListener('DOMContentLoaded', boot);
