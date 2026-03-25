document.addEventListener("DOMContentLoaded", () => {
    // Initialize map centered on Indianapolis
    const map = L.map('map').setView([39.7684, -86.1581], 11);
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        className: 'map-tiles'
    }).addTo(map);

    let layerGroup = L.layerGroup().addTo(map);
    const searchAreaBtn = document.getElementById('search-this-area-btn');

    const icons = {
        lost: L.divIcon({ className: 'pin-lost', iconSize: [16, 16] }),
        found: L.divIcon({ className: 'pin-found', iconSize: [16, 16] }),
        sighting: L.divIcon({ className: 'pin-sighting', iconSize: [16, 16] }),
        adoptable: L.divIcon({ className: 'pin-adoptable', iconSize: [16, 16] }),
    };

    async function loadPins() {
        const bounds = map.getBounds();
        const form = document.getElementById('map-filters');
        const formData = new FormData(form);
        
        const params = new URLSearchParams();
        params.append('sw_lat', bounds.getSouth());
        params.append('sw_lng', bounds.getWest());
        params.append('ne_lat', bounds.getNorth());
        params.append('ne_lng', bounds.getEast());
        
        formData.getAll('record_type').forEach(v => params.append('record_type', v));
        formData.getAll('animal_type').forEach(v => params.append('animal_type', v));
        params.append('days', formData.get('days'));

        try {
            const resp = await fetch(`/api/map/geojson?${params.toString()}`);
            if (!resp.ok) throw new Error('Network response was not ok');
            const data = await resp.json();

            layerGroup.clearLayers();
            L.geoJSON(data, {
                pointToLayer: (feature, latlng) => {
                    const type = feature.properties.record_type;
                    return L.marker(latlng, { icon: icons[type] || icons.lost });
                },
                onEachFeature: (feature, layer) => {
                    const p = feature.properties;
                    // Provide a nice fallback for image and formatting
                    const imgHtml = p.thumbnail_url 
                        ? `<img src="${p.thumbnail_url}" class="popup-thumb object-cover w-full h-32 rounded bg-gray-100">` 
                        : `<div class="w-full h-32 bg-gray-100 flex items-center justify-center rounded mb-2 text-gray-400 border border-gray-200"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-8 h-8"><path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" /><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" /></svg></div>`;
                    
                    const badgeColors = {
                        lost: "bg-red-100 text-red-700",
                        found: "bg-green-100 text-green-700",
                        sighting: "bg-blue-100 text-blue-700",
                        adoptable: "bg-orange-100 text-orange-700"
                    };
                    const badgeClass = badgeColors[p.record_type] || badgeColors.lost;

                    layer.bindPopup(`
                        <div class="w-48 text-sm font-sans">
                            ${imgHtml}
                            <h3 class="font-bold text-gray-900 truncate" title="${p.name || 'Unknown name'}">${p.name || 'Unknown name'}</h3>
                            <p class="text-gray-600 mb-1 capitalize">${p.breed || 'Unknown breed'} ${p.animal_type ? '- ' + p.animal_type : ''}</p>
                            <span class="inline-block px-2 py-0.5 ${badgeClass} text-xs font-semibold rounded-full uppercase tracking-wider mb-2">${p.record_type}</span>
                            <p class="text-xs text-gray-500 mb-2 font-mono">${p.date_event || 'Unknown date'}</p>
                            <a href="/pets/${p.id}" class="text-indigo-600 hover:text-indigo-800 hover:underline font-medium block text-center border-t border-gray-100 pt-2 transition">View details &rarr;</a>
                        </div>
                    `);
                }
            }).addTo(layerGroup);
            
            searchAreaBtn.classList.add('hidden');
        } catch (err) {
            console.error("Failed to load map pins:", err);
        }
    }

    // Debounce function to prevent API spam while panning
    let timeout;
    function debounce(func, wait) {
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Event listeners
    map.on('moveend', () => {
        searchAreaBtn.classList.remove('hidden');
    });

    searchAreaBtn.addEventListener('click', () => {
        loadPins();
    });

    document.getElementById('apply-filters-btn').addEventListener('click', () => {
        loadPins();
    });

    // Initial load
    loadPins();
});
