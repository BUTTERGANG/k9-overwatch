// ── Camera placeholder for popups (no photo) ────────────────────────────
const CAMERA_SVG_PLACEHOLDER = `
<div class="w-full bg-slate-100 flex items-center justify-center rounded-none mb-0 text-slate-300 border-b border-slate-200" style="height:120px;">
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-8 h-8">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" />
    </svg>
</div>`;

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

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
        maxZoom: 19,
    }).addTo(map);

    let layerGroup = L.layerGroup().addTo(map);
    const searchAreaBtn = document.getElementById('search-this-area-btn');

    // ── Spinner overlay ──────────────────────────────────────────────────
    const mapContainer = document.querySelector('.flex-1.relative');
    const spinner = document.createElement('div');
    spinner.id = 'map-spinner';
    spinner.className = 'absolute inset-0 z-[999] flex items-center justify-center bg-white/60 backdrop-blur-sm hidden';
    spinner.innerHTML = `
        <div class="flex flex-col items-center gap-3 bg-white rounded-2xl px-6 py-5 shadow-card-hover border border-slate-100">
            <svg class="animate-spin w-8 h-8 text-brand-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
            </svg>
            <span class="text-sm font-semibold text-slate-600">Loading pins&hellip;</span>
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
        <span id="map-error-text">Failed to load map data. Please try again.</span>`;
    mapContainer.appendChild(errorBanner);

    // ── Marker icons ─────────────────────────────────────────────────────
    const icons = {
        lost:      L.divIcon({ className: 'pin-base pin-lost',      iconSize: [14, 14], iconAnchor: [7, 7] }),
        found:     L.divIcon({ className: 'pin-base pin-found',     iconSize: [14, 14], iconAnchor: [7, 7] }),
        sighting:  L.divIcon({ className: 'pin-base pin-sighting',  iconSize: [14, 14], iconAnchor: [7, 7] }),
        adoptable: L.divIcon({ className: 'pin-base pin-adoptable', iconSize: [14, 14], iconAnchor: [7, 7] }),
    };

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
        // Auto-hide after 6s
        setTimeout(() => errorBanner.classList.add('hidden'), 6000);
    }

    // ── Build popup HTML ─────────────────────────────────────────────────
    function buildPopupHtml(p) {
        const safeName       = escapeHtml(p.name)        || 'Unknown name';
        const safeBreed      = escapeHtml(p.breed)       || 'Unknown breed';
        const safeAnimalType = p.animal_type ? ' &middot; ' + escapeHtml(p.animal_type) : '';
        const safeDateEvent  = escapeHtml(p.date_event)  || 'Unknown date';
        const safeId         = escapeHtml(p.id);
        const safeThumbnail  = escapeHtml(p.thumbnail_url);

        const imgHtml = safeThumbnail
            ? `<img src="${safeThumbnail}"
                    class="w-full object-cover"
                    style="height:120px;"
                    alt="${safeName}"
                    loading="lazy"
                    onerror="this.parentNode.innerHTML='${CAMERA_SVG_PLACEHOLDER.replace(/\n\s*/g,' ').replace(/'/g,"\\'")}'">`
            : CAMERA_SVG_PLACEHOLDER;

        return `
            <div style="width:210px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;">
                <div style="overflow:hidden;border-radius:0;">
                    ${imgHtml}
                </div>
                <div style="padding:12px 14px 14px;">
                    <div style="margin-bottom:6px;">
                        ${buildBadgeHtml(p.record_type)}
                    </div>
                    <h3 style="font-weight:700;color:#0f172a;margin:0 0 2px;
                                overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;"
                        title="${safeName}">${safeName}</h3>
                    <p style="color:#64748b;margin:0 0 8px;font-size:12px;text-transform:capitalize;">
                        ${safeBreed}${safeAnimalType}
                    </p>
                    <p style="color:#94a3b8;font-size:11px;font-family:ui-monospace,monospace;margin:0 0 10px;">
                        ${safeDateEvent}
                    </p>
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

    // ── Load map pins ────────────────────────────────────────────────────
    async function loadPins() {
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
            const resp = await fetch(`/api/map/geojson?${params.toString()}`);
            if (!resp.ok) throw new Error(`Server error: ${resp.status} ${resp.statusText}`);
            const data = await resp.json();

            layerGroup.clearLayers();

            L.geoJSON(data, {
                pointToLayer: (feature, latlng) => {
                    const type = feature.properties.record_type;
                    return L.marker(latlng, { icon: icons[type] || icons.lost });
                },
                onEachFeature: (feature, layer) => {
                    layer.bindPopup(buildPopupHtml(feature.properties), {
                        maxWidth: 220,
                        minWidth: 210,
                        className: 'k9-popup',
                    });
                }
            }).addTo(layerGroup);

            searchAreaBtn.classList.add('hidden');
        } catch (err) {
            showError('Failed to load map pins. Please try again.');
            console.error('[K9-Map] Failed to load pins:', err);
        } finally {
            hideSpinner();
        }
    }

    // ── Event bindings ───────────────────────────────────────────────────
    map.on('moveend', () => searchAreaBtn.classList.remove('hidden'));
    searchAreaBtn.addEventListener('click', loadPins);
    document.getElementById('apply-filters-btn').addEventListener('click', loadPins);

    // Initial load
    loadPins();
});
