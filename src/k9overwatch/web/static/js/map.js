// ── Dark mode helper ─────────────────────────────────────────────────────
function isDark() {
    return document.documentElement.classList.contains('dark');
}

// ── Camera placeholder for popups (no photo) ────────────────────────────
function getCameraPlaceholder() {
    var bg = isDark() ? '#1e293b' : '#f1f5f9';
    var stroke = isDark() ? '#475569' : '#cbd5e1';
    return `
<div class="w-full flex items-center justify-center rounded-none mb-0 border-b" style="height:120px;background:${bg};border-color:${stroke};">
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="${stroke}" class="w-8 h-8">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" />
    </svg>
</div>`;
}

// ── Listing age helpers ───────────────────────────────────────────────────
function daysOld(dateStr) {
    if (!dateStr) return null;
    const diff = Date.now() - new Date(dateStr).getTime();
    return Math.floor(diff / 86400000);
}

function relativeAge(dateStr) {
    const d = daysOld(dateStr);
    if (d === null) return null;
    if (d === 0) return 'today';
    if (d === 1) return 'yesterday';
    if (d < 30) return `${d} days ago`;
    if (d < 60) return '1 month ago';
    const months = Math.floor(d / 30);
    if (d < 365) return `${months} months ago`;
    const years = Math.floor(d / 365);
    return years === 1 ? '1 year ago' : `${years} years ago`;
}

// Returns CSS opacity [0.2 – 1.0] based on listing age
function ageOpacity(dateStr) {
    const d = daysOld(dateStr);
    if (d === null) return 1;
    if (d <= 30)  return 1;
    if (d <= 60)  return 0.85;
    if (d <= 90)  return 0.70;
    if (d <= 180) return 0.50;
    if (d <= 365) return 0.35;
    return 0.20;
}

// ── XSS-safe HTML escaping ───────────────────────────────────────────────
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── Badge styles per record_type ─────────────────────────────────────────
const BADGE_STYLES = {
    lost:      { cssBg: '--status-lost-bg', cssColor: '--status-lost-text', cssBorder: '--status-lost-border', cssDot: '--status-lost', label: 'Lost' },
    found:     { cssBg: '--status-found-bg', cssColor: '--status-found-text', cssBorder: '--status-found-border', cssDot: '--status-found', label: 'Found' },
    sighting:  { cssBg: '--status-sighting-bg', cssColor: '--status-sighting-text', cssBorder: '--status-sighting-border', cssDot: '--status-sighting', label: 'Sighting' },
    adoptable: { cssBg: '--status-adoptable-bg', cssColor: '--status-adoptable-text', cssBorder: '--status-adoptable-border', cssDot: '--status-adoptable', label: 'Adoptable' },
};

function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function buildBadgeHtml(record_type) {
    const s = BADGE_STYLES[record_type] || BADGE_STYLES.lost;
    const bg = cssVar(s.cssBg) || '#fef2f2';
    const color = cssVar(s.cssColor) || '#991b1b';
    const border = cssVar(s.cssBorder) || '#fecaca';
    const dot = cssVar(s.cssDot) || '#dc2626';
    return `<span style="display:inline-flex;align-items:center;gap:4px;
                          background:${bg};color:${color};border:1px solid ${border};
                          padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;
                          text-transform:uppercase;letter-spacing:0.06em;">
                <span style="width:6px;height:6px;border-radius:50%;background:${dot};flex-shrink:0;display:inline-block;"></span>
                ${s.label}
            </span>`;
}

document.addEventListener("DOMContentLoaded", () => {
    // ── Init map ─────────────────────────────────────────────────────────
    const map = L.map('map', { zoomControl: true }).setView([39.7684, -86.1581], 11);
    map.zoomControl.setPosition('bottomright');

    // ── Theme-aware tile layers ──────────────────────────────────────────
    var _TILES = {
        light: {
            url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
        },
        dark: {
            url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>',
        },
    };

    // "See similar photos" — opens Google Lens reverse image search for the
    // pet's photo. Lets a user visually confirm a match without any ML on our
    // side, and is a familiar interaction ("search by image").
    function lensUrl(imageUrl) {
        return `https://lens.google.com/uploadbyurl?url=${encodeURIComponent(imageUrl)}`;
    }

    function updateFilterSummary() {
        const form = document.getElementById('map-filters');
        const statusCount = form.querySelectorAll('input[name="record_type"]:checked').length;
        const speciesCount = form.querySelectorAll('input[name="animal_type"]:checked').length;
        const days = form.querySelector('select[name="days"]').value;
        const parts = [];
        if (statusCount < form.querySelectorAll('input[name="record_type"]').length) parts.push(`${statusCount} statuses`);
        if (speciesCount < form.querySelectorAll('input[name="animal_type"]').length) parts.push(`${speciesCount} species`);
        if (days !== '365') parts.push(`${days}-day window`);
        filterSummary.textContent = parts.length ? parts.join(' · ') : 'All filters active';
    }

    function updateRecencyBar() {
        const form = document.getElementById('map-filters');
        const types = new FormData(form).getAll('record_type');
        const params = new URLSearchParams();
        // If exactly one record type is selected, scope the counts to it.
        if (types.length === 1) params.append('record_type', types[0]);
        fetch(`/api/map/buckets?${params.toString()}`)
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (!data) return;
                const byKey = Object.fromEntries(data.buckets.map(b => [b.key, b.count]));
                document.querySelectorAll('#recency-bar [data-bucket]').forEach(el => {
                    const key = el.getAttribute('data-bucket');
                    const label = { week: 'this week', fortnight: '1–2 wks', month: 'this month', older: 'older' }[key];
                    el.textContent = `${byKey[key] ?? 0} ${label}`;
                });
            })
            .catch(() => { /* non-critical: leave placeholder text */ });
    }

    function makeTileLayer(dark) {
        var cfg = dark ? _TILES.dark : _TILES.light;
        return L.tileLayer(cfg.url, { attribution: cfg.attribution, maxZoom: 19 });
    }

    var tileLayer = makeTileLayer(isDark());
    tileLayer.addTo(map);

    // Swap tile layer when the global dark-mode toggle fires
    document.addEventListener('k9:darkModeChange', function(e) {
        tileLayer.remove();
        tileLayer = makeTileLayer(e.detail.dark);
        tileLayer.addTo(map);
    });

    // ── Marker cluster group ─────────────────────────────────────────────
    //
    // iconCreateFunction inspects all markers in the cluster to determine the
    // dominant record_type, then sets a data-cluster-type attribute that the
    // CSS in map.html uses to choose the fill color (red/green/blue).
    //
    function clusterIconCreate(cluster) {
        const markers = cluster.getAllChildMarkers();
        let lost = 0, found = 0, other = 0;
        markers.forEach(m => {
            const t = m.options._recordType;
            if (t === 'lost')       lost++;
            else if (t === 'found') found++;
            else                    other++;
        });
        const total = markers.length;

        // Dominant type: >60% threshold wins; otherwise "mixed"
        let clusterType;
        if (lost / total > 0.6)        clusterType = 'lost';
        else if (found / total > 0.6)  clusterType = 'found';
        else                           clusterType = 'mixed';

        // Size tiers: sm (<10), md (10-99), lg (100+)
        const size = total >= 100 ? 42 : total >= 10 ? 36 : 30;

        return L.divIcon({
            html: `<div class="marker-cluster" data-cluster-type="${clusterType}"
                        style="width:${size}px;height:${size}px;"
                        aria-label="${total} pets in this area">
                       ${total}
                   </div>`,
            className: '',   // suppress Leaflet's own leaflet-div-icon wrapper styles
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
        });
    }

    let clusterGroup = L.markerClusterGroup({
        maxClusterRadius: 40,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        chunkedLoading: true,
        iconCreateFunction: clusterIconCreate,
    }).addTo(map);

    const searchAreaBtn = document.getElementById('search-this-area-btn');
    const resultCountEl = document.getElementById('map-result-count');
    const resultCountText = document.getElementById('map-result-count-text');
    const emptyState = document.getElementById('map-empty-state');
    const clearFiltersBtn = document.getElementById('clear-map-filters-btn');
    const clearAllFiltersBtn = document.getElementById('clear-all-map-filters-btn');
    const filterSummary = document.getElementById('map-filter-summary');
    const listPanel = document.getElementById('map-list-panel');
    const reportList = document.getElementById('map-report-list');
    const listCount = document.getElementById('map-list-count');
    const toggleListBtn = document.getElementById('toggle-map-list-btn');
    const closeListBtn = document.getElementById('close-map-list-btn');
    const markerById = new Map();

    function setListOpen(open) {
        listPanel.classList.toggle('open', open);
        listPanel.setAttribute('aria-hidden', String(!open));
        toggleListBtn.setAttribute('aria-expanded', String(open));
        if (open) closeListBtn.focus();
    }

    toggleListBtn.addEventListener('click', () => setListOpen(!listPanel.classList.contains('open')));
    closeListBtn.addEventListener('click', () => {
        setListOpen(false);
        toggleListBtn.focus();
    });

    function renderReportList(features) {
        markerById.clear();
        reportList.replaceChildren();
        listCount.textContent = `${features.length} report${features.length === 1 ? '' : 's'} in this view`;
        if (!features.length) {
            reportList.innerHTML = '<p class="p-4 text-sm text-slate-500 dark:text-slate-400">No reports match these filters.</p>';
            return;
        }
        features.forEach(feature => {
            const p = feature.properties || {};
            const card = document.createElement('div');
            card.className = 'map-report-card block w-full text-left mb-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 hover:border-brand-400 dark:hover:border-brand-500';
            card.setAttribute('role', 'listitem');
            card.dataset.petId = p.id || '';
            const matchCount = Number(p.match_count || 0);
            const matchBadge = matchCount > 0 ? `<a href="/matches" aria-label="View ${escapeHtml(matchCount)} potential match${matchCount === 1 ? '' : 'es'}" class="mt-2 inline-flex w-fit items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-800 ring-1 ring-inset ring-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-700"><span aria-hidden="true">◆</span>${escapeHtml(matchCount)} potential match${matchCount === 1 ? '' : 'es'}</a>` : '';
            card.innerHTML = `<button type="button" class="map-report-card-main block w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 rounded-lg"><span class="block text-xs font-bold uppercase tracking-wide text-brand-600 dark:text-brand-400">${escapeHtml(p.record_type || 'report')}</span><span class="mt-1 block font-semibold text-sm text-slate-800 dark:text-slate-100">${escapeHtml(p.name || 'Unknown name')}</span><span class="mt-1 block text-xs text-slate-500 dark:text-slate-400">${escapeHtml(p.breed || 'Unknown breed')} · ${escapeHtml(p.date_event || 'Date unavailable')}</span></button>${matchBadge}`;
            const cardMain = card.querySelector('.map-report-card-main');
            cardMain.addEventListener('click', () => {
                const marker = markerById.get(String(p.id));
                if (!marker) return;
                map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14));
                marker.openPopup();
                reportList.querySelectorAll('.is-selected').forEach(el => el.classList.remove('is-selected'));
                card.classList.add('is-selected');
            });
            reportList.appendChild(card);
        });
    }

    // ── Spinner overlay ──────────────────────────────────────────────────
    const mapContainer = document.getElementById('map').parentElement;
    const spinner = document.createElement('div');
    spinner.id = 'map-spinner';
    spinner.className = 'absolute inset-0 z-[999] flex items-center justify-center bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm hidden';
    spinner.innerHTML = `
        <div class="flex flex-col items-center gap-3 bg-white dark:bg-slate-800 rounded-2xl px-6 py-5 shadow-card-hover border border-slate-100 dark:border-slate-700">
            <svg class="animate-spin w-8 h-8 text-brand-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
            </svg>
            <span class="text-sm font-semibold text-slate-600 dark:text-slate-300">Loading pins&hellip;</span>
        </div>`;
    mapContainer.appendChild(spinner);

    // ── Error banner ─────────────────────────────────────────────────────
    const errorBanner = document.createElement('div');
    errorBanner.id = 'map-error';
    errorBanner.className = 'absolute top-4 left-1/2 -translate-x-1/2 z-[1001] hidden ' +
        'bg-red-600 text-white text-sm font-semibold px-5 py-2.5 rounded-full shadow-lg flex items-center gap-2';
    errorBanner.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 flex-shrink-0" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
        </svg>
        <span id="map-error-text">Failed to load map data. Please try again.</span>
        <button id="map-retry-btn" type="button" class="underline underline-offset-2 hover:no-underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-white">Retry</button>`;
    mapContainer.appendChild(errorBanner);
    document.getElementById('map-retry-btn').addEventListener('click', () => loadPins());

    const truncationBanner = document.createElement('div');
    truncationBanner.id = 'map-truncation';
    truncationBanner.className = 'absolute bottom-16 left-1/2 -translate-x-1/2 z-[1000] hidden bg-amber-100 dark:bg-amber-900/80 text-amber-900 dark:text-amber-100 text-xs font-semibold px-4 py-2 rounded-full shadow-lg border border-amber-200 dark:border-amber-700';
    truncationBanner.setAttribute('role', 'status');
    mapContainer.appendChild(truncationBanner);

    // ── Marker icons ─────────────────────────────────────────────────────
    const icons = {
        lost:      L.divIcon({ className: 'pin-base pin-lost',      iconSize: [14, 14], iconAnchor: [7, 7] }),
        found:     L.divIcon({ className: 'pin-base pin-found',     iconSize: [14, 14], iconAnchor: [7, 7] }),
        sighting:  L.divIcon({ className: 'pin-base pin-sighting',  iconSize: [14, 14], iconAnchor: [7, 7] }),
        adoptable: L.divIcon({ className: 'pin-base pin-adoptable', iconSize: [14, 14], iconAnchor: [7, 7] }),
    };

    function makeMatchIcon(type) {
        return L.divIcon({
            className: '',
            html: `<div class="pin-base pin-${type}" style="position:relative;">
                     <span style="position:absolute;top:-5px;right:-5px;width:8px;height:8px;
                                  background:#f59e0b;border-radius:50%;border:1.5px solid white;
                                  box-shadow:0 0 4px rgba(245,158,11,0.7);"></span>
                   </div>`,
            iconSize: [14, 14],
            iconAnchor: [7, 7],
        });
    }

    function showSpinner() {
        spinner.classList.remove('hidden');
        errorBanner.classList.add('hidden');
    }

    function hideSpinner() {
        spinner.classList.add('hidden');
    }

    function showError(message) {
        document.getElementById('map-error-text').textContent =
            message || 'Failed to load map data. Please try again.';
        errorBanner.classList.remove('hidden');
        // Keep the error visible until the user retries or a later request succeeds.
    }

    // ── Result count badge ───────────────────────────────────────────────
    function updateResultCount(total, returned, truncated) {
        if (total == null) {
            resultCountEl.style.display = 'none';
            truncationBanner.classList.add('hidden');
            emptyState.classList.add('hidden');
            return;
        }
        const label = total === 1 ? '1 pet' : `${total.toLocaleString()} pets`;
        emptyState.classList.toggle('hidden', total !== 0);
        resultCountText.textContent = truncated
            ? `${returned.toLocaleString()} of ${label}`
            : label;
        resultCountEl.style.display = 'flex';
        if (truncated) {
            truncationBanner.textContent = `Showing ${returned.toLocaleString()} of ${total.toLocaleString()} pets in this area. Zoom in to see more.`;
            truncationBanner.classList.remove('hidden');
        } else {
            truncationBanner.classList.add('hidden');
        }
    }

    // ── Build popup HTML ─────────────────────────────────────────────────
    function buildPopupHtml(p) {
        const safeName       = escapeHtml(p.name)        || 'Unknown name';
        const safeBreed      = escapeHtml(p.breed)       || 'Unknown breed';
        const safeAnimalType = p.animal_type ? ' &middot; ' + escapeHtml(p.animal_type) : '';
        const safeDateEvent  = escapeHtml(p.date_event)  || 'Unknown date';
        const safeId         = escapeHtml(p.id);
        const safeThumbnail  = escapeHtml(p.thumbnail_url);
        const safeGeoSource = p.geocode_source || null;
        const safeGeoConf   = p.geocode_confidence || null;

        // Geocode confidence badge
        let geoBadgeHtml = '';
        if (safeGeoConf) {
            const geoLabels = { high: 'Exact location', medium: 'Neighborhood', low: 'ZIP code area' };
            const geoColors = {
                high: { bg: dark ? 'rgba(22,163,74,0.2)' : '#f0fdf4', border: dark ? '#166534' : '#bbf7d0', text: dark ? '#4ade80' : '#166534' },
                medium: { bg: dark ? 'rgba(234,179,8,0.2)' : '#fefce8', border: dark ? '#854d0e' : '#fde68a', text: dark ? '#facc15' : '#854d0e' },
                low: { bg: dark ? 'rgba(239,68,68,0.2)' : '#fef2f2', border: dark ? '#991b1b' : '#fecaca', text: dark ? '#f87171' : '#991b1b' },
            };
            const c = geoColors[safeGeoConf] || geoColors.low;
            const label = geoLabels[safeGeoConf] || safeGeoConf;
            geoBadgeHtml = `<div style="margin-bottom:8px;padding:3px 7px;border-radius:6px;background:${c.bg};border:1px solid ${c.border};font-size:10px;color:${c.text};display:flex;align-items:center;gap:4px;">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" style="width:10px;height:10px;flex-shrink:0;"><path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z"/></svg>
                ${label}
            </div>`;
        }

        const age     = relativeAge(p.date_event);
        const ageDays = daysOld(p.date_event);

        const dark = isDark();
        const wrapperBg   = dark ? '#0f172a' : 'white';
        const nameColor   = dark ? '#f1f5f9' : '#0f172a';
        const breedColor  = dark ? '#94a3b8' : '#64748b';
        const dateColor   = dark ? '#64748b' : '#94a3b8';

        const cameraPlaceholder = getCameraPlaceholder();

        const imgHtml = safeThumbnail
            ? `<img src="/img?url=${encodeURIComponent(p.thumbnail_url)}"
                    class="w-full object-cover"
                    style="height:120px;"
                    alt="${safeName}"
                    loading="lazy"
                    onerror="this.onerror=null;this.src='/static/img/pet-placeholder.svg';">`
            : cameraPlaceholder;

        // Optional "see similar photos" button, only when a photo exists.
        const lensHtml = safeThumbnail
            ? `<a href="${lensUrl(p.thumbnail_url)}" target="_blank" rel="noopener"
                  style="display:block;text-align:center;margin-bottom:6px;font-size:11px;font-weight:600;
                         color:#4f46e5;text-decoration:none;">
                 &#128269; See similar photos
               </a>`
            : '';

        return `
            <div style="width:210px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;background:${wrapperBg};">
                <div style="overflow:hidden;border-radius:0;">
                    ${imgHtml}
                </div>
                <div style="padding:12px 14px 14px;">
                    <div style="margin-bottom:6px;">
                        ${buildBadgeHtml(p.record_type)}
                    </div>
                    <h3 style="font-weight:700;color:${nameColor};margin:0 0 2px;
                                overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;"
                        title="${safeName}">${safeName}</h3>
                    <p style="color:${breedColor};margin:0 0 8px;font-size:12px;text-transform:capitalize;">
                        ${safeBreed}${safeAnimalType}
                    </p>
                    <p style="color:${dateColor};font-size:11px;font-family:ui-monospace,monospace;margin:0 0 6px;">
                        ${safeDateEvent}${age ? ` &middot; <em style="font-style:normal;">${age}</em>` : ''}
                    </p>
                    ${ageDays !== null && ageDays > 90 ? `
                    <div style="margin-bottom:8px;padding:4px 8px;border-radius:6px;
                                background:${dark?'rgba(120,53,15,0.25)':'#fef9c3'};
                                border:1px solid ${dark?'#78350f':'#fde68a'};
                                font-size:10px;color:${dark?'#fcd34d':'#92400e'};
                                display:flex;align-items:center;gap:4px;">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" style="width:11px;height:11px;flex-shrink:0;">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
                        </svg>
                        Listing is ${ageDays > 365 ? 'over a year' : 'over 90 days'} old
                    </div>` : ''}
                    ${geoBadgeHtml}
                    ${p.match_count > 0 ? `
                    <div style="margin-bottom:8px;">
                        <a href="/matches" style="display:inline-flex;align-items:center;gap:4px;
                                  background:${cssVar('--status-adoptable-bg') || '#fffbeb'};
                                  color:${cssVar('--status-adoptable-text') || '#92400e'};
                                  border:1px solid ${cssVar('--status-adoptable-border') || '#fde68a'};
                                  padding:3px 8px;border-radius:999px;font-size:10px;font-weight:700;
                                  text-decoration:none;">
                            <span style="width:6px;height:6px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
                            ${p.match_count} potential match${p.match_count > 1 ? 'es' : ''}
                        </a>
                    </div>` : ''}
                    ${lensHtml}
                    <a href="/pets/${safeId}"
                       style="display:block;text-align:center;background:${cssVar('--brand-600') || '#2540eb'};color:white;
                              text-decoration:none;font-weight:600;font-size:12px;
                              padding:7px 12px;border-radius:10px;transition:background 0.15s;"
                       onmouseover="this.style.background='#1d32d0'"
                       onmouseout="this.style.background='${cssVar('--brand-600') || '#2540eb'}'">
                        View details &rarr;
                    </a>
                </div>
            </div>`;
    }

    // ── In-flight request cancellation ───────────────────────────────────
    let currentAbortController = null;

    // ── Load map pins ────────────────────────────────────────────────────
    async function loadPins() {
        // Cancel any in-flight request before firing a new one
        if (currentAbortController) {
            currentAbortController.abort();
        }
        currentAbortController = new AbortController();
        const signal = currentAbortController.signal;

        const bounds   = map.getBounds();
        const form     = document.getElementById('map-filters');
        const formData = new FormData(form);

        const params = new URLSearchParams();
        params.append('sw_lat', bounds.getSouth());
        params.append('sw_lng', bounds.getWest());
        params.append('ne_lat', bounds.getNorth());
        params.append('ne_lng', bounds.getEast());

        formData.getAll('record_type').forEach(v => params.append('record_type', v));
        formData.getAll('animal_type').forEach(v => params.append('animal_type', v));
        params.append('days', formData.get('days') || '30');

        showSpinner();

        try {
            const resp = await fetch(`/api/map/geojson?${params.toString()}`, { signal });
            if (!resp.ok) throw new Error(`Server error: ${resp.status} ${resp.statusText}`);
            const data = await resp.json();
            errorBanner.classList.add('hidden');

            clusterGroup.clearLayers();

            // Build markers manually so we can attach _recordType for the
            // cluster iconCreateFunction to read later.
            const markers = [];
            if (data.features) {
                data.features.forEach(feature => {
                    if (!feature.geometry || !feature.geometry.coordinates) return;
                    const [lng, lat] = feature.geometry.coordinates;
                    const p = feature.properties;
                    const type = p.record_type;
                    const hasMatch = p.match_count > 0;
                    const icon = hasMatch ? makeMatchIcon(type) : (icons[type] || icons.lost);
                    const marker = L.marker([lat, lng], {
                        icon,
                        // Store record_type on the options object so
                        // iconCreateFunction can read it without closures
                        _recordType: type,
                    });
                    const opacity = ageOpacity(p.date_event);
                    if (opacity < 1) marker.setOpacity(opacity);
                    marker.bindPopup(buildPopupHtml(p), {
                        maxWidth: 220,
                        minWidth: 210,
                        className: 'k9-popup',
                    });
                    markerById.set(String(p.id), marker);
                    markers.push(marker);
                });
            }

            renderReportList(data.features || []);
            clusterGroup.addLayers(markers);

            // Update the result count badge using the `total` field from the
            // API response, falling back to the feature count if absent.
            const returned = (data.returned != null) ? data.returned : (data.features ? data.features.length : 0);
            const total = (data.total != null) ? data.total : returned;
            updateResultCount(total, returned, data.truncated === true);

            // Auto-reload is now handling pan/zoom — keep the manual button
            // hidden until an explicit filter change triggers it to reappear.
            searchAreaBtn.classList.add('hidden');
            updateRecencyBar();
        } catch (err) {
            if (err.name === 'AbortError') {
                // A newer request superseded this one — swallow silently
                return;
            }
            showError('Failed to load map pins. Please try again.');
            console.error('[K9-Map] Failed to load pins:', err && (err.stack || err.message || err));
        } finally {
            hideSpinner();
        }
    }

    // ── Track open popups so we can suppress reloads ───────────────────
    let popupOpen = false;
    map.on('popupopen',  () => { popupOpen = true; });
    map.on('popupclose', () => { popupOpen = false; });

    // ── Debounced auto-reload on pan/zoom ────────────────────────────────
    //
    // 800ms debounce: if the user is still panning/zooming, we hold off.
    // Only fires automatically — the manual "Search this area" button remains
    // as a visible fallback but is hidden by default since auto-reload handles
    // most cases. It reappears only when a filter change is applied without
    // a subsequent move (filter changes call loadPins() directly).
    //
    // When a popup is open we skip the reload entirely — calling
    // clearLayers() while Leaflet is displaying a popup on a marker inside
    // the cluster group causes a crash.
    //
    let moveDebounceTimer = null;
    const MOVE_DEBOUNCE_MS = 800;

    map.on('moveend', () => {
        clearTimeout(moveDebounceTimer);
        if (popupOpen) return;   // don't reload while user is viewing a popup
        moveDebounceTimer = setTimeout(() => {
            loadPins();
        }, MOVE_DEBOUNCE_MS);
    });

    // Manual fallback — always available even though hidden by default
    searchAreaBtn.addEventListener('click', () => {
        clearTimeout(moveDebounceTimer);
        loadPins();
    });

    // Clear filters from the empty state and broaden the search.
    function clearMapFilters() {
        const form = document.getElementById('map-filters');
        form.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = true; });
        document.getElementById('map-days-select').value = '365';
        updateFilterSummary();
        clearTimeout(moveDebounceTimer);
        loadPins();
    }

    clearFiltersBtn.addEventListener('click', clearMapFilters);
    clearAllFiltersBtn.addEventListener('click', clearMapFilters);
    document.querySelectorAll('#map-filters input, #map-filters select').forEach(input => {
        input.addEventListener('change', updateFilterSummary);
    });

    // Filter apply: reload immediately and keep search button hidden
    document.getElementById('apply-filters-btn').addEventListener('click', () => {
        updateFilterSummary();
        clearTimeout(moveDebounceTimer);
        loadPins();
    });
    updateFilterSummary();

    // Initial load — wait until the map has a real viewport
    map.whenReady(() => loadPins());
});
