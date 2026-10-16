// ==============================================================================
// BSplayer Screen Controller for 4" LCD Display (Woodland Edition)
// ==============================================================================

let ws = null;
let currentProject = null;
let isPlaying = false;
let currentBpm = 120;
let lastBeat = -1;
let currentVolume = 1.0;
let hudTimeout = null;
let allProjects = [];
let allShows = [];
let activeShow = null;

const canvas = document.getElementById("waveform-canvas");
const ctx = canvas.getContext("2d");
let visualizerData = new Array(32).fill(0);

document.addEventListener("DOMContentLoaded", () => {
    initClock();
    initWebSocket();
    loadCurrentProject();
    loadLibraryAndShows();
    startVisualizerLoop();
});

function initClock() {
    function update() {
        const d = new Date();
        const str = d.toTimeString().split(' ')[0];
        document.getElementById("clock-display").innerText = str;
    }
    update();
    setInterval(update, 1000);
}

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
        try {
            const status = JSON.parse(event.data);
            handleScreenUpdate(status);
        } catch (e) {
            console.error(e);
        }
    };

    ws.onclose = () => {
        setTimeout(initWebSocket, 2000);
    };
}

function handleScreenUpdate(status) {
    isPlaying = status.is_playing;
    currentBpm = status.bpm || 120;

    // Transport button & state pill
    const btnPlay = document.getElementById("screen-btn-play");
    const statePill = document.getElementById("screen-state-pill");
    if (isPlaying) {
        btnPlay.innerText = "⏸";
        statePill.innerText = "PLAYING";
        statePill.classList.add("playing");
    } else {
        btnPlay.innerText = "▶";
        statePill.innerText = "STOPPED";
        statePill.classList.remove("playing");
    }

    // Time text
    document.getElementById("screen-time-current").innerText = formatTimeMinSec(status.current_time);
    document.getElementById("screen-time-total").innerText = `/ ${formatTimeMinSec(status.duration)}`;

    // Circular Progress Ring (Circumference ~ 440)
    if (status.duration > 0) {
        const pct = status.current_time / status.duration;
        const offset = 440 - (pct * 440);
        document.getElementById("ring-fill").style.strokeDashoffset = offset;
    }

    // BPM Beat LED Flasher (Warm Amber Pulse)
    const beatIndex = Math.floor((status.current_time * (currentBpm / 60.0)));
    if (beatIndex !== lastBeat && isPlaying) {
        lastBeat = beatIndex;
        const led = document.getElementById("bpm-led");
        led.classList.add("beat");
        setTimeout(() => led.classList.remove("beat"), 120);
    }
    document.getElementById("bpm-val").innerText = Math.round(currentBpm);

    // Section Badge
    if (status.current_marker) {
        document.getElementById("section-badge").innerText = status.current_marker;
    }

    // Cue Card (Lyrics & Chords)
    if (status.current_lyric) {
        document.getElementById("cue-lyric").innerText = status.current_lyric.text || "";
        document.getElementById("cue-chord").innerText = status.current_lyric.chords || "[ - ]";

        // Also update full prompter view
        document.querySelectorAll(".full-lyric-row").forEach(row => {
            const match = row.dataset.text === status.current_lyric.text;
            row.classList.toggle("active", match);
            if (match) {
                row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        });
    }

    // Hardware Output status
    if (status.num_channels) {
        document.getElementById("hw-status").innerText = `OUT 1-${status.num_channels} ACTIVO`;
    }

    // Update Visualizer bars from output peak levels
    if (status.peak_levels) {
        const peaks = status.peak_levels;
        for (let i = 0; i < visualizerData.length; i++) {
            const ch = i % peaks.length;
            const target = isPlaying ? (peaks[ch] * (0.6 + Math.random() * 0.4)) : 0.05;
            visualizerData[i] = visualizerData[i] * 0.7 + target * 0.3;
        }

        // Mixer strip VU meters
        peaks.forEach((lvl, ch) => {
            const meter = document.getElementById(`screen-vu-${ch}`);
            if (meter) {
                meter.style.height = `${Math.min(100, lvl * 100)}%`;
            }
        });
    }

    // Detect Master Volume Change (from physical knob)
    if (status.master_volume !== undefined && Math.abs(status.master_volume - currentVolume) > 0.02) {
        currentVolume = status.master_volume;
        showVolumeHUD(currentVolume);
    }
}

function formatTimeMinSec(sec) {
    if (!sec || isNaN(sec)) return "00:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

async function loadCurrentProject() {
    try {
        const res = await fetch("/api/projects/current");
        const data = await res.json();
        if (data) {
            currentProject = data;
            document.getElementById("screen-song-title").innerText = data.title;
            document.getElementById("screen-song-artist").innerText = `${data.artist || 'Artista'} • ${data.tracks.length} Stems`;
            renderScreenMixer();
            renderScreenPrompter();
            highlightCurrentSongInList();
        }
    } catch (e) {
        console.error(e);
    }
}

async function loadLibraryAndShows() {
    try {
        // 1. Load songs
        const pRes = await fetch("/api/projects");
        allProjects = await pRes.json();
        document.getElementById("songs-count").innerText = `${allProjects.length} temas`;
        renderSongsLibrary();

        // 2. Load shows
        const sRes = await fetch("/api/shows");
        allShows = await sRes.json();
        if (allShows.length > 0) {
            activeShow = allShows[0];
            renderActiveShow();
        }
    } catch (e) {
        console.error("Error loading library/shows", e);
    }
}

function renderSongsLibrary() {
    const list = document.getElementById("explorer-songs-list");
    if (!list) return;

    list.innerHTML = allProjects.map(p => `
        <div class="song-item-card ${currentProject && currentProject.id === p.id ? 'current' : ''}" onclick="loadSong('${p.id}')">
            <div style="flex:1;">
                <div class="song-item-title" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                    <span>${p.title}</span>
                    ${p.package_type === 'bsp' ? `<span style="background:var(--moss-green); color:#f6efe6; font-size:0.6rem; font-weight:800; padding:1px 5px; border-radius:3px;">BSP</span>` : ''}
                    ${p.has_video ? `<span style="background:var(--amber-tube); color:#100c09; font-size:0.6rem; font-weight:800; padding:1px 5px; border-radius:3px;">VID</span>` : ''}
                    ${p.has_midi ? `<span style="background:#5c7080; color:#fff; font-size:0.6rem; font-weight:800; padding:1px 5px; border-radius:3px;">MIDI</span>` : ''}
                </div>
                <div class="song-item-meta">${p.artist || 'Artista'} • ${p.bpm} BPM • ${p.file_size_mb ? p.file_size_mb + 'MB • ' : ''}${formatTimeMinSec(p.duration_seconds)}</div>
            </div>
            <button onclick="event.stopPropagation(); addToCurrentShow('${p.id}')" style="background:none; border:1px solid var(--border-wood); color:var(--amber-tube); border-radius:4px; padding:4px 8px; font-size:0.75rem; cursor:pointer;" title="Agregar al Show">+ Show</button>
        </div>
    `).join('');
}

function renderActiveShow() {
    if (!activeShow) return;
    document.getElementById("current-show-name").innerText = activeShow.name.toUpperCase();
    const list = document.getElementById("explorer-show-list");
    if (!list) return;

    if (!activeShow.song_ids || activeShow.song_ids.length === 0) {
        list.innerHTML = `<div style="color:var(--text-bark); font-size:0.8rem; padding:12px; text-align:center;">El show está vacío.<br>Toca "+ Show" en las canciones de la izquierda para armar tu setlist.</div>`;
        return;
    }

    list.innerHTML = activeShow.song_ids.map((sid, idx) => {
        const proj = allProjects.find(p => p.id === sid);
        const title = proj ? proj.title : sid;
        const bpm = proj ? `${proj.bpm} BPM` : '';
        const isCurrent = currentProject && currentProject.id === sid;

        return `
            <div class="song-item-card ${isCurrent ? 'current' : ''}" onclick="loadSong('${sid}')">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:0.75rem; color:var(--amber-tube); font-weight:800;">#${idx + 1}</span>
                    <div>
                        <div class="song-item-title">${title}</div>
                        <div class="song-item-meta">${bpm}</div>
                    </div>
                </div>
                <button onclick="event.stopPropagation(); removeFromShow(${idx})" style="background:none; border:none; color:var(--text-bark); font-size:0.9rem; cursor:pointer;" title="Quitar">✕</button>
            </div>
        `;
    }).join('');
}

async function loadSong(songId) {
    try {
        const res = await fetch("/api/projects/load", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: songId })
        });
        const data = await res.json();
        if (data.status === "ok") {
            currentProject = data.project;
            loadCurrentProject();
            renderActiveShow();
            switchView('perform'); // Return to live view ready to play!
        }
    } catch (e) {
        console.error("Error loading song", e);
    }
}

async function addToCurrentShow(songId) {
    if (!activeShow) return;
    if (!activeShow.song_ids) activeShow.song_ids = [];
    activeShow.song_ids.push(songId);
    await saveShowToServer();
    renderActiveShow();
}

async function removeFromShow(index) {
    if (!activeShow || !activeShow.song_ids) return;
    activeShow.song_ids.splice(index, 1);
    await saveShowToServer();
    renderActiveShow();
}

async function createNewShowPrompt() {
    const name = prompt("Nombre del nuevo Show (Setlist):", "Show Viernes");
    if (!name) return;
    activeShow = {
        id: "show-" + Date.now().toString(36),
        name: name,
        song_ids: []
    };
    await saveShowToServer();
    renderActiveShow();
}

async function saveShowToServer() {
    if (!activeShow) return;
    await fetch("/api/shows/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(activeShow)
    });
}

function highlightCurrentSongInList() {
    renderSongsLibrary();
    renderActiveShow();
}

function renderScreenMixer() {
    const container = document.getElementById("screen-mixer-strips");
    if (!container || !currentProject) return;

    // Display first 4 tracks on 4-inch LCD
    const displayTracks = currentProject.tracks.slice(0, 4);

    container.innerHTML = displayTracks.map((t, idx) => `
        <div class="screen-strip">
            <span class="strip-badge-out">OUT ${t.output_channel + 1}</span>
            <span class="strip-name">${t.name}</span>

            <div class="strip-fader-area">
                <div class="screen-vu-meter">
                    <div class="screen-vu-fill" id="screen-vu-${idx}"></div>
                </div>
                <input type="range" class="screen-fader" min="0" max="1.5" step="0.02" value="${t.volume}"
                    orient="vertical" oninput="changeTrackVolume('${t.id}', this.value, ${idx})">
            </div>

            <span class="strip-vol-text" id="scr-vol-${idx}">${Math.round(t.volume * 100)}%</span>
            <button class="strip-mute-btn ${t.mute ? 'active' : ''}" onclick="toggleMute('${t.id}', this)">MUTE</button>
        </div>
    `).join('');
}

function renderScreenPrompter() {
    const container = document.getElementById("screen-lyrics-scroll");
    if (!container || !currentProject) return;

    container.innerHTML = currentProject.lyrics.map(l => `
        <div class="full-lyric-row" data-text="${l.text}">
            ${l.chords ? `<div class="full-chord">${l.chords}</div>` : ''}
            <div class="full-text">${l.text}</div>
        </div>
    `).join('');
}

function switchView(viewName, btn) {
    document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));

    document.getElementById(`view-${viewName}`).classList.add("active");
    if (btn) {
        btn.classList.add("active");
    } else {
        // find matching nav btn
        const matchingBtn = document.querySelector(`.nav-btn[onclick*="${viewName}"]`);
        if (matchingBtn) matchingBtn.classList.add("active");
    }
}

function togglePlay() {
    if (isPlaying) {
        fetch("/api/playback/pause", { method: "POST" });
    } else {
        fetch("/api/playback/play", { method: "POST" });
    }
}

function seekTo(seconds) {
    fetch("/api/playback/seek", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seconds: parseFloat(seconds) })
    });
}

function changeTrackVolume(trackId, val, idx) {
    fetch("/api/track/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: trackId, volume: parseFloat(val) })
    });
    document.getElementById(`scr-vol-${idx}`).innerText = `${Math.round(val * 100)}%`;
}

function toggleMute(trackId, btn) {
    const isMuted = btn.classList.toggle("active");
    fetch("/api/track/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: trackId, mute: isMuted })
    });
}

function showVolumeHUD(vol) {
    const hud = document.getElementById("volume-hud");
    document.getElementById("hud-val").innerText = `${Math.round(vol * 100)}%`;
    document.getElementById("hud-fill").style.width = `${Math.min(100, (vol / 1.5) * 100)}%`;

    hud.classList.add("visible");
    clearTimeout(hudTimeout);
    hudTimeout = setTimeout(() => {
        hud.classList.remove("visible");
    }, 1500);
}

// Warm Woodland Audio Visualizer (Amber & Forest Moss)
function startVisualizerLoop() {
    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const barWidth = canvas.width / visualizerData.length;

        for (let i = 0; i < visualizerData.length; i++) {
            const val = visualizerData[i];
            const barHeight = Math.max(4, val * canvas.height * 0.95);
            const x = i * barWidth;
            const y = canvas.height - barHeight;

            // Woodland Forest gradient: Amber -> Moss Green -> Gold
            const grad = ctx.createLinearGradient(0, canvas.height, 0, 0);
            grad.addColorStop(0, '#e29b38');
            grad.addColorStop(0.65, '#487e53');
            grad.addColorStop(1, '#ffd166');

            ctx.fillStyle = grad;
            ctx.shadowBlur = 6;
            ctx.shadowColor = '#e29b38';
            ctx.fillRect(x + 2, y, barWidth - 4, barHeight);
        }

        requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
}
