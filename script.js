// Local Storage Key
const DB_KEY = 'trap_monitor_data';
const DELETED_KEY = 'trap_monitor_deleted';

// Initialize sample data if none exists
function initializeData() {
    if (!localStorage.getItem(DB_KEY)) {
        const sampleData = [
            {
                id: Date.now().toString(),
                platform: '당근마켓',
                item: '포획틀',
                seller: '[업체명] 산짐승잡이\n[대표자] 익명\n[주소] 미상\n[연락처] 채팅연락',
                url: 'https://daangn.com/articles/12345',
                date: new Date().toISOString()
            }
        ];
        localStorage.setItem(DB_KEY, JSON.stringify(sampleData));
    }
}

// Fetch Backend Scraped Data
async function syncBackendData() {
    try {
        // Append timestamp to prevent caching
        const response = await fetch(`data/scraped_data.json?t=${new Date().getTime()}`);
        if (response.ok) {
            const scrapedData = await response.json();
            let localData = JSON.parse(localStorage.getItem(DB_KEY) || '[]');

            // Merge using ID to avoid duplicates
            const localIds = new Set(localData.map(item => item.id));
            const deletedIds = new Set(JSON.parse(localStorage.getItem(DELETED_KEY) || '[]'));
            let addedCount = 0;

            scrapedData.forEach(item => {
                if (!localIds.has(item.id) && !deletedIds.has(item.id)) {
                    localData.push(item);
                    addedCount++;
                }
            });

            if (addedCount > 0) {
                localStorage.setItem(DB_KEY, JSON.stringify(localData));
                console.log(`${addedCount} new scraped items synced.`);
                // Rerender if we are on dashboard or report tab
                if (document.getElementById('tab-dashboard').classList.contains('active')) renderDashboard();
                if (document.getElementById('tab-report-export').classList.contains('active')) initReportTab();
            }
        }
    } catch (err) {
        console.log("Scraped data not found or fetch error:", err);
    }
}

// Format Date
function formatDate(dateString) {
    const d = new Date(dateString);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Format Month for Report
function formatMonth(dateString) {
    const d = new Date(dateString);
    return `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
}

// Load and Render Dashboard
let showAllRecords = false;

function renderDashboard() {
    const data = JSON.parse(localStorage.getItem(DB_KEY) || '[]');

    // Calculate Stats
    const currentMonth = new Date().getMonth();
    const currentYear = new Date().getFullYear();

    let totalCount = 0;
    let snareCount = 0;
    let trapCount = 0;
    let otherCount = 0;

    const allItemsHtml = [];

    data.reverse().forEach((record, index) => {
        const recordDate = new Date(record.date);

        // Stats for current month
        if (recordDate.getMonth() === currentMonth && recordDate.getFullYear() === currentYear) {
            totalCount++;
            if (record.item.includes('올무') || record.item.includes('창애')) snareCount++;
            else if (record.item.includes('포획틀')) trapCount++;
            else otherCount++;
        }

        // Build all rows (toggle controlled)
        const showRow = showAllRecords || index < 10;
        if (showRow) {
            allItemsHtml.push(`
                <tr>
                    <td><strong>${record.platform}</strong></td>
                    <td><span class="badge">${record.item}</span></td>
                    <td style="white-space: pre-line; font-size: 0.85rem; line-height: 1.4;">${record.seller}</td>
                    <td><a href="${record.url}" target="_blank" class="external-link">링크 열기 <i class="fa-solid fa-arrow-up-right-from-square" style="font-size:0.75rem"></i></a></td>
                    <td>${formatDate(record.date)}</td>
                    <td>
                        <button class="btn-delete" onclick="deleteRecord('${record.id}')" title="삭제">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `);
        }
    });

    // Update DOM
    document.getElementById('totalCount').textContent = totalCount;
    document.getElementById('snareCount').textContent = snareCount;
    document.getElementById('trapCount').textContent = trapCount;
    document.getElementById('otherCount').textContent = otherCount;
    document.getElementById('monitoringList').innerHTML = allItemsHtml.join('') || '<tr><td colspan="6" style="text-align:center; padding: 2rem;">최근 등록된 내역이 없습니다.</td></tr>';

    // Update toggle button label
    const toggleBtn = document.getElementById('toggleAllBtn');
    if (toggleBtn) {
        const totalRecords = data.length;
        toggleBtn.innerHTML = showAllRecords
            ? '<i class="fa-solid fa-list"></i> 최근 10건만 보기'
            : `<i class="fa-solid fa-list"></i> 전체 목록 보기 (${totalRecords}건)`;
    }
}

// Form Submit Handler
document.getElementById('recordForm').addEventListener('submit', function (e) {
    e.preventDefault();

    // Format the seller data
    const sName = document.getElementById('seller_name').value;
    const sRep = document.getElementById('seller_rep').value;
    const sAddr = document.getElementById('seller_address').value;
    const sPhone = document.getElementById('seller_phone').value;
    const formattedSeller = `[업체명] ${sName}\n[대표자] ${sRep}\n[주소] ${sAddr}\n[연락처] ${sPhone}`;

    const newRecord = {
        id: Date.now().toString(),
        platform: document.getElementById('platform').value,
        item: document.getElementById('item').value,
        seller: formattedSeller,
        url: document.getElementById('url').value,
        date: new Date().toISOString()
    };

    const data = JSON.parse(localStorage.getItem(DB_KEY) || '[]');
    data.push(newRecord);
    localStorage.setItem(DB_KEY, JSON.stringify(data));

    alert('적발 내역이 성공적으로 등록되었습니다.');
    this.reset();

    // Switch to dashboard tab
    document.querySelector('.nav-item[data-tab="dashboard"]').click();
});

// Delete Record
window.deleteRecord = function (id) {
    if (confirm('정말 이 적발 내역을 삭제하시겠습니까?')) {
        let data = JSON.parse(localStorage.getItem(DB_KEY) || '[]');
        data = data.filter(record => record.id !== id);
        localStorage.setItem(DB_KEY, JSON.stringify(data));

        let deletedIds = JSON.parse(localStorage.getItem(DELETED_KEY) || '[]');
        if (!deletedIds.includes(id)) {
            deletedIds.push(id);
            localStorage.setItem(DELETED_KEY, JSON.stringify(deletedIds));
        }

        renderDashboard();
        // 보고서 탭에 선택된 월이 있을 때만 갱신 (빈 값 예외처리)
        const reportMonthEl = document.getElementById('reportMonth');
        if (reportMonthEl && reportMonthEl.value) renderReportList();
    }
}

// Clear form mapping
document.getElementById('clearFormBtn').addEventListener('click', () => {
    document.getElementById('recordForm').reset();
});

// Tab Navigation Logic
document.querySelectorAll('.nav-item').forEach(tab => {
    tab.addEventListener('click', (e) => {
        e.preventDefault();

        // Remove active class from all
        document.querySelectorAll('.nav-item').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

        // Add active class to clicked
        tab.classList.add('active');
        const targetId = `tab-${tab.getAttribute('data-tab')}`;
        document.getElementById(targetId).classList.add('active');

        // Re-render specifics based on tab
        if (targetId === 'tab-dashboard') renderDashboard();
        if (targetId === 'tab-report-export') initReportTab();
    });
});

// Setup Date Header
function setupDate() {
    const options = { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' };
    document.getElementById('currentDate').textContent = new Date().toLocaleDateString('ko-KR', options);
}

// Initialize Report Tab
function initReportTab() {
    const data = JSON.parse(localStorage.getItem(DB_KEY) || '[]');
    const select = document.getElementById('reportMonth');

    // Extract unique months
    const months = [...new Set(data.map(item => formatMonth(item.date)))];

    select.innerHTML = '';
    if (months.length === 0) {
        select.innerHTML = '<option value="">데이터 없음</option>';
    } else {
        months.sort().reverse().forEach(m => {
            const option = document.createElement('option');
            option.value = m;
            option.textContent = m;
            select.appendChild(option);
        });

        // Render table for the first month
        renderReportList();
    }
}

// Render Report Table based on selected month
function renderReportList() {
    const reportMonthEl = document.getElementById('reportMonth');
    if (!reportMonthEl) return;
    const selectedMonth = reportMonthEl.value;
    if (!selectedMonth) return; // 빈 값 예외처리

    const data = JSON.parse(localStorage.getItem(DB_KEY) || '[]');

    const filteredData = data.filter(item => formatMonth(item.date) === selectedMonth);
    const tbody = document.getElementById('hwpTableBody');

    let totalCount = 0;
    let snareCount = 0;
    let trapCount = 0;
    let otherCount = 0;

    const html = filteredData.map(record => {
        totalCount++;
        if (record.item.includes('올무') || record.item.includes('창애')) snareCount++;
        else if (record.item.includes('포획틀')) trapCount++;
        else otherCount++;

        // Parse the formatted seller string
        let sName = '-', sRep = '-', sAddr = '-', sPhone = '-';

        if (record.seller.includes('[업체명]')) {
            const parts = record.seller.split('\n');
            parts.forEach(p => {
                if (p.startsWith('[업체명]')) sName = p.replace('[업체명]', '').trim();
                else if (p.startsWith('[대표자]')) sRep = p.replace('[대표자]', '').trim();
                else if (p.startsWith('[주소]')) sAddr = p.replace('[주소]', '').trim();
                else if (p.startsWith('[연락처]')) sPhone = p.replace('[연락처]', '').trim();
            });
        } else {
            // Fallback for older data format
            sName = record.seller;
        }

        return `
        <tr>
            <td style="text-align:center; border: 1px solid #000; padding: 5px; vertical-align:middle;">${record.platform}</td>
            <td style="text-align:center; border: 1px solid #000; padding: 5px; vertical-align:middle;">${record.item}</td>
            <td style="vertical-align:middle; border: 1px solid #000; padding: 5px;"><a href="${record.url}" target="_blank" style="color: blue; text-decoration: underline;">${record.url}</a></td>
            <td style="text-align:center; border: 1px solid #000; padding: 5px; vertical-align:middle;">${sName}</td>
            <td style="text-align:center; border: 1px solid #000; padding: 5px; vertical-align:middle;">${sRep}</td>
            <td style="text-align:center; border: 1px solid #000; padding: 5px; vertical-align:middle;">${sAddr}</td>
            <td style="text-align:center; border: 1px solid #000; padding: 5px; vertical-align:middle;">${sPhone}</td>
        </tr>
        `;
    }).join('');

    tbody.innerHTML = html || '<tr><td colspan="7" style="text-align:center; border: 1px solid #000; padding: 10px;">해당 월에 데이터가 없습니다.</td></tr>';

    // Update Summary Texts
    document.getElementById('hwpReportTitle').textContent = `${selectedMonth} 불법 엽구류 온라인 적발 보고`;
    document.getElementById('hwpTotalCount').textContent = totalCount;
    document.getElementById('hwpSnareCount').textContent = snareCount;
    document.getElementById('hwpTrapCount').textContent = trapCount;
    const hwpOtherCountEl = document.getElementById('hwpOtherCount');
    if (hwpOtherCountEl) hwpOtherCountEl.textContent = otherCount;
}

document.getElementById('reportMonth').addEventListener('change', renderReportList);

// Copy Table functionality
document.getElementById('copyTableBtn').addEventListener('click', () => {
    const reportArea = document.getElementById('hwpExportArea');
    const range = document.createRange();
    range.selectNode(reportArea);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);

    try {
        document.execCommand('copy');
        alert('보고서 전체가 클립보드에 복사되었습니다. 한글(HWP) 문서에 그대로 붙여넣기(Ctrl+V) 하세요.');
    } catch (err) {
        alert('복사 중 오류가 발생했습니다.');
    }

    window.getSelection().removeAllRanges();
});

// Run Scraper Button via Local Server API
document.getElementById('runScraperBtn').addEventListener('click', async () => {
    const btn = document.getElementById('runScraperBtn');
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 탐색 중...';
    btn.disabled = true;

    try {
        const response = await fetch('/run-scraper', {
            method: 'POST'
        });

        if (response.ok) {
            const result = await response.json();
            if (result.status === "success") {
                console.log(result.output);
                alert('자동 검색이 완료되었습니다. 결과를 최신화합니다.');
                // backend 데이터 다시 불러오기
                await syncBackendData();
            } else {
                alert('검색 중 오류: ' + result.message);
            }
        } else {
            console.warn('API 서버 응답 실패, 로컬 테스트용 모의 실행');
            setTimeout(() => {
                alert('서버가 실행 중이지 않아 모의 실행되었습니다.');
            }, 1000);
        }
    } catch (e) {
        console.warn('요청 실패 (로컬 파일 실행 시 작동 불가):', e);
        alert('자동 탐색은 app.py 서버를 통해 실행해야 합니다.');
    } finally {
        btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-arrow-right"></i> 자동 탐색 실행';
        btn.disabled = false;
    }
});

// Reset Data Button via Local Server API
document.getElementById('resetDataBtn').addEventListener('click', async () => {
    if (confirm('모든 누적 적발 건수와 데이터를 완전히 초기화하시겠습니까?\n스크래핑 된 데이터 및 수동 데이터가 모두 지워집니다.\n이 작업은 되돌릴 수 없습니다.')) {
        try {
            const response = await fetch('/reset-data', { method: 'POST' });
            if (response.ok) {
                const result = await response.json();
                if (result.status === "success" || result.status === "ignored") {
                    localStorage.setItem(DB_KEY, JSON.stringify([]));
                    localStorage.setItem(DELETED_KEY, JSON.stringify([]));
                    renderDashboard();
                    renderReportList();
                    alert('데이터가 성공적으로 초기화되었습니다.');
                } else {
                    alert('초기화 중 서버 오류: ' + result.message);
                }
            } else {
                alert('서버 응답 실패 (로컬 모드에서는 브라우저 데이터만 초기화됩니다.)');
                localStorage.setItem(DB_KEY, JSON.stringify([]));
                localStorage.setItem(DELETED_KEY, JSON.stringify([]));
                renderDashboard();
                renderReportList();
            }
        } catch (e) {
            console.warn('요청 실패:', e);
            alert('초기화 요청 실패: ' + e);
        }
    }
});

// Toggle All Records Button
document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn = document.getElementById('toggleAllBtn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            showAllRecords = !showAllRecords;
            renderDashboard();
        });
    }
});

// Boot
window.onload = () => {
    initializeData();
    setupDate();
    syncBackendData();
    renderDashboard();
};
