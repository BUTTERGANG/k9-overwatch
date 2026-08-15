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
    lost:      { bg: '#fef2f2', color: '#991b1b', border: '#fecaca', dot: '#dc2626', label: 'Lost' },
    found:     { bg: '#f0fdf4', color: '#14532d', border: '#bbf7d0', dot: '#16a34a', label: 'Found' },
    sighting:  { bg: '#eff6ff', color: '#1e3a8a', border: '#bfdbfe', dot: '#2563eb', label: 'Sighting' },
    adoptable: { bg: '#fffbeb', color: '#92400e', border: '#fde68a', dot: '#d97706', label: 'Adoptable' },
};

function buildBadgeHtml(record_type) {
    const s = BADGE_STYLES[record_type] || BADGE_STYLES.lost;
    return `<span style="display:inline-flex;align-items:center;gap:4px;
                          background:${s.bg};color:${s.color};border:1px solid ${s.border};
                          padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;
                          text-transform:uppercase;letter-spacing:0.06em;">
                <span style="width:6px;height:6px;border-radius:50%;background:${s.dot};flex-shrink:0;display:inline-block;"></span>
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
            return;
        }
        const label = total === 1 ? '1 pet' : `${total.toLocaleString()} pets`;
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
                    ${p.match_count > 0 ? `
                    <div style="margin-bottom:8px;">
                        <a href="/matches" style="display:inline-flex;align-items:center;gap:4px;
                                  background:#fffbeb;color:#92400e;border:1px solid #fde68a;
                                  padding:3px 8px;border-radius:999px;font-size:10px;font-weight:700;
                                  text-decoration:none;">
                            <span style="width:6px;height:6px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
                            ${p.match_count} potential match${p.match_count > 1 ? 'es' : ''}
                        </a>
                    </div>` : ''}
                    ${lensHtml}
                    <a href="/pets/${safeId}"
                       style="display:block;text-align:center;background:#2540eb;color:white;
                              text-decoration:none;font-weight:600;font-size:12px;
                              padding:7px 12px;border-radius:10px;transition:background 0.15s;"
                       onmouseover="this.style.background='#1d32d0'"
                       onmouseout="this.style.background='#2540eb'">
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
                    markers.push(marker);
                });
            }

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

    // Filter apply: reload immediately and keep search button hidden
    document.getElementById('apply-filters-btn').addEventListener('click', () => {
        clearTimeout(moveDebounceTimer);
        loadPins();
    });

    // Initial load — wait until the map has a real viewport
    map.whenReady(() => loadPins());
});
