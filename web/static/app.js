// BSplayer Client App

let ws = null;
let currentProject = null;
let isPlaying = false;
let currentDuration = 0.0;
let availableDevices = [];
let availableProjects = [];

document.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
    loadCurrentProject();
    loadProjectsList();
    loadDevicesList();
    setupEventListeners();
});

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log("[BSplayer] WebSocket connected");
        document.getElementById("connection-status").classList.add("connected");
    };

    ws.onmessage = (event) => {
        try {
            const status = JSON.parse(event.data);
            handleStatusUpdate(status);
        } catch (e) {
            console.error("WS Parse error", e);
        }
    };

    ws.onclose = () => {
        console.warn("[BSplayer] WebSocket closed. Reconnecting in 2s...");
        document.getElementById("connection-status").classList.remove("connected");
        setTimeout(initWebSocket, 2000);
    };
}

function handleStatusUpdate(status) {
    isPlaying = status.is_playing;
    currentDuration = status.duration;

    // Update Play / Pause Button text
    const btnPlay = document.getElementById("btn-play");
    if (isPlaying) {
        btnPlay.innerHTML = `<span>⏸</span> Pausar`;
        btnPlay.classList.add("playing");
    } else {
        btnPlay.innerHTML = `<span>▶</span> Reproducir`;
        btnPlay.classList.remove("playing");
    }

    // Time counter
    document.getElementById("time-current").innerText = formatTime(status.current_time);
    document.getElementById("time-total").innerText = formatTime(status.duration);

    // Progress bar
    if (status.duration > 0) {
        const pct = (status.current_time / status.duration) * 100;
        document.getElementById("progress-fill").style.width = `${pct}%`;
    }

    // Output Peak Meters
    if (status.peak_levels) {
        status.peak_levels.forEach((lvl, ch) => {
            const meter = document.getElementById(`master-vu-${ch}`);
            if (meter) {
                const heightPct = Math.min(100, Math.pow(lvl, 0.7) * 100);
                meter.style.height = `${heightPct}%`;
            }
        });
    }

    // Marker highlight
    if (status.current_marker) {
        document.querySelectorAll(".marker-pill").forEach(pill => {
            pill.classList.toggle("active", pill.dataset.name === status.current_marker);
        });
    }

    // Lyric line highlight
    if (status.current_lyric) {
        document.querySelectorAll(".lyric-item").forEach(item => {
            const textMatch = item.querySelector(".lyric-text")?.innerText === status.current_lyric.text;
            item.classList.toggle("active", textMatch);
            if (textMatch) {
                item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        });
    }
}

function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return "00:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${ms}`;
}

async function loadCurrentProject() {
    try {
        const res = await fetch("/api/projects/current");
        const data = await res.json();
        if (data) {
            currentProject = data;
            renderProjectInfo();
            renderMixerConsole();
            renderPrompter();
            renderMarkers();
        }
    } catch (e) {
        console.error("Error loading current project", e);
    }
}

async function loadProjectsList() {
    try {
        const res = await fetch("/api/projects");
        availableProjects = await res.json();
        const select = document.getElementById("select-project");
        if (select) {
            select.innerHTML = availableProjects.map(p => 
                `<option value="${p.id}" ${currentProject && currentProject.id === p.id ? 'selected' : ''}>${p.title}</option>`
            ).join('');
        }
    } catch (e) {
        console.error("Error loading projects list", e);
    }
}

async function loadSelectedProject(songId) {
    try {
        const res = await fetch("/api/projects/load", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: songId })
        });
        const data = await res.json();
        if (data.status === "ok") {
            currentProject = data.project;
            renderProjectInfo();
            renderMixerConsole();
            renderPrompter();
            renderMarkers();
        }
    } catch (e) {
        console.error("Error loading selected project", e);
    }
}

function renderProjectInfo() {
    if (!currentProject) return;
    document.getElementById("song-title").innerText = currentProject.title;
    document.getElementById("song-artist").innerText = `${currentProject.artist || 'Artista'} • ${currentProject.bpm} BPM`;
}

function renderMarkers() {
    const container = document.getElementById("markers-container");
    if (!container || !currentProject) return;

    container.innerHTML = currentProject.markers.map(m => `
        <div class="marker-pill" data-name="${m.name}" onclick="seekTo(${m.time_seconds})">
            ${m.name}
        </div>
    `).join('');
}

function renderPrompter() {
    const container = document.getElementById("lyrics-box");
    if (!container || !currentProject) return;

    container.innerHTML = currentProject.lyrics.map(l => `
        <div class="lyric-item" onclick="seekTo(${l.time_seconds})">
            ${l.chords ? `<div class="chord-line">${l.chords}</div>` : ''}
            <div class="lyric-text">${l.text}</div>
        </div>
    `).join('');
}

function renderMixerConsole() {
    const container = document.getElementById("mixer-strips");
    if (!container || !currentProject) return;

    // Output channels options (based on 4 channels for Behringer UMC404HD or 8 for 1820)
    const outOptions = [0, 1, 2, 3].map(ch => 
        `<option value="${ch}">Out ${ch + 1}</option>`
    ).join('');

    container.innerHTML = currentProject.tracks.map(t => `
        <div class="channel-strip" id="strip-${t.id}">
            <div class="track-group-tag ${t.is_click ? 'click' : ''}">${t.group}</div>
            <div class="channel-title" title="${t.name}">${t.name}</div>
            
            <select class="output-routing-select" onchange="changeTrackOutput('${t.id}', this.value)">
                ${[0, 1, 2, 3].map(ch => `<option value="${ch}" ${t.output_channel === ch ? 'selected' : ''}>Out ${ch + 1}</option>`).join('')}
            </select>

            <div class="fader-vu-container">
                <div class="vu-meter-bar">
                    <div class="vu-meter-fill" id="vu-${t.id}"></div>
                </div>
                <input type="range" class="vertical-slider" min="0" max="1.5" step="0.01" value="${t.volume}"
                    orient="vertical" oninput="changeTrackVolume('${t.id}', this.value)">
            </div>

            <div class="volume-value-label" id="vol-lbl-${t.id}">
                ${Math.round(t.volume * 100)}%
            </div>

            <div class="strip-buttons">
                <button class="btn-mute ${t.mute ? 'active' : ''}" onclick="toggleMute('${t.id}', this)">M</button>
                <button class="btn-solo ${t.solo ? 'active' : ''}" onclick="toggleSolo('${t.id}', this)">S</button>
            </div>
        </div>
    `).join('');
}

// Controls
function setupEventListeners() {
    document.getElementById("btn-play").addEventListener("click", () => {
        if (isPlaying) {
            fetch("/api/playback/pause", { method: "POST" });
        } else {
            fetch("/api/playback/play", { method: "POST" });
        }
    });

    document.getElementById("btn-stop").addEventListener("click", () => {
        fetch("/api/playback/stop", { method: "POST" });
    });

    document.getElementById("progress-bar-bg").addEventListener("click", (e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const clickRatio = (e.clientX - rect.left) / rect.width;
        const targetSeconds = clickRatio * currentDuration;
        seekTo(targetSeconds);
    });

    document.getElementById("master-fader").addEventListener("input", (e) => {
        const vol = parseFloat(e.target.value);
        fetch("/api/master/volume", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ volume: vol })
        });
        document.getElementById("master-vol-lbl").innerText = `${Math.round(vol * 100)}%`;
    });
}

function seekTo(seconds) {
    fetch("/api/playback/seek", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seconds: parseFloat(seconds) })
    });
}

function changeTrackVolume(trackId, volume) {
    fetch("/api/track/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: trackId, volume: parseFloat(volume) })
    });
    document.getElementById(`vol-lbl-${trackId}`).innerText = `${Math.round(volume * 100)}%`;
}

function changeTrackOutput(trackId, channel) {
    fetch("/api/track/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: trackId, output_channel: parseInt(channel) })
    });
}

function toggleMute(trackId, btn) {
    const isActive = btn.classList.toggle("active");
    fetch("/api/track/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: trackId, mute: isActive })
    });
}

function toggleSolo(trackId, btn) {
    const isActive = btn.classList.toggle("active");
    fetch("/api/track/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track_id: trackId, solo: isActive })
    });
}

// Device Selection Modal
async function loadDevicesList() {
    try {
        const res = await fetch("/api/devices");
        availableDevices = await res.json();
        const activeDev = availableDevices.find(d => d.is_active);
        if (activeDev) {
            document.getElementById("active-device-name").innerText = `${activeDev.name} (${activeDev.max_channels} Out)`;
        }
    } catch (e) {
        console.error("Error loading devices", e);
    }
}

function openDeviceModal() {
    const list = document.getElementById("device-list-container");
    list.innerHTML = availableDevices.map(d => `
        <div class="device-card ${d.is_active ? 'active' : ''}" onclick="selectAudioDevice(${d.id}, ${d.max_channels})">
            <div>
                <strong>${d.name}</strong>
                <div style="font-size:0.75rem; color:var(--text-muted);">${d.hostapi} • ${d.max_channels} Salidas de Hardware</div>
            </div>
            ${d.is_active ? '<span style="color:var(--accent-green);font-weight:700;">Activo</span>' : ''}
        </div>
    `).join('');
    document.getElementById("device-modal").style.display = "flex";
}

function closeDeviceModal() {
    document.getElementById("device-modal").style.display = "none";
}

async function selectAudioDevice(devId, maxChannels) {
    await fetch("/api/device/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: devId, channels: maxChannels })
    });
    closeDeviceModal();
    loadDevicesList();
}
