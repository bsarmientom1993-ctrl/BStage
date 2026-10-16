import os
import json
import uuid
import zipfile
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
import soundfile as sf
import numpy as np

from models.project import SongProject, Track, Marker, LyricLine
from engine.click_generator import save_click_wav

class ProjectService:
    def __init__(self, projects_root: Path):
        self.root = projects_root
        self.root.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> List[Dict[str, Any]]:
        """Scans the projects directory for folders and .bsp packages and returns summary metadata."""
        projects = []
        found_ids = set()

        # 1. Scan .bsp single-file packages first
        for p in self.root.glob("*.bsp"):
            try:
                with zipfile.ZipFile(p, "r") as z:
                    names = z.namelist()
                    if "project.json" in names:
                        with z.open("project.json") as f:
                            data = json.load(f)
                            proj_id = data.get("id", p.stem)
                            found_ids.add(proj_id)
                            found_ids.add(p.stem)
                            projects.append({
                                "id": proj_id,
                                "title": data.get("title", p.stem),
                                "artist": data.get("artist", ""),
                                "bpm": data.get("bpm", 120.0),
                                "duration_seconds": data.get("duration_seconds", 0.0),
                                "track_count": len(data.get("tracks", [])),
                                "package_type": "bsp",
                                "package_file": p.name,
                                "file_size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                                "has_video": bool(data.get("video_file")),
                                "has_midi": bool(data.get("midi_file") or data.get("midi_cues")),
                                "has_lyrics": bool(data.get("lyrics"))
                            })
            except Exception as e:
                print(f"[ProjectService] Error reading package {p.name}: {e}")

        # 2. Scan standard directories (skip system directories like _shows)
        for p in self.root.iterdir():
            if p.is_dir() and not p.name.startswith("_"):
                if p.name in found_ids:
                    continue
                json_file = p / "project.json"
                if json_file.exists():
                    has_audio = any(p.glob("*.wav")) or any(p.glob("*.mp3")) or any((p / "audio").glob("*.wav"))
                    if not has_audio:
                        continue
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            proj_id = data.get("id", p.name)
                            if proj_id in found_ids:
                                continue
                            found_ids.add(proj_id)
                            projects.append({
                                "id": proj_id,
                                "title": data.get("title", p.name),
                                "artist": data.get("artist", ""),
                                "bpm": data.get("bpm", 120.0),
                                "duration_seconds": data.get("duration_seconds", 0.0),
                                "track_count": len(data.get("tracks", [])),
                                "package_type": "folder",
                                "package_file": None,
                                "file_size_mb": 0.0,
                                "has_video": bool(data.get("video_file")),
                                "has_midi": bool(data.get("midi_file") or data.get("midi_cues")),
                                "has_lyrics": bool(data.get("lyrics"))
                            })
                    except Exception as e:
                        print(f"[ProjectService] Error reading {json_file}: {e}")
        return projects

    def get_project_path(self, project_id: str) -> Optional[Path]:
        """Returns the Path to a project (either .bsp file or directory)."""
        clean_id = project_id.removesuffix(".bsp")
        
        # 1. Try clean_id.bsp
        bsp_path = self.root / f"{clean_id}.bsp"
        if bsp_path.exists():
            return bsp_path

        # 2. Try raw project_id (in case it already had .bsp or is folder)
        direct_path = self.root / project_id
        if direct_path.exists():
            return direct_path

        # 3. Try directory with clean_id
        dir_path = self.root / clean_id
        if dir_path.is_dir():
            return dir_path

        # 4. Search inside all .bsp files for matching id in project.json
        for p in self.root.glob("*.bsp"):
            try:
                with zipfile.ZipFile(p, "r") as z:
                    if "project.json" in z.namelist():
                        with z.open("project.json") as f:
                            data = json.load(f)
                            if data.get("id") == project_id or data.get("id") == clean_id:
                                return p
            except Exception:
                pass

        return None

    def get_project_dir(self, project_id: str) -> Path:
        """Backwards compatible path resolver."""
        p = self.get_project_path(project_id)
        return p if p is not None else (self.root / project_id)

    def get_project(self, project_id: str) -> Optional[SongProject]:
        """Loads and parses a project by ID from .bsp package or folder."""
        path = self.get_project_path(project_id)
        if not path or not path.exists():
            return None

        if path.is_file() and path.suffix.lower() == ".bsp":
            try:
                with zipfile.ZipFile(path, "r") as z:
                    if "project.json" in z.namelist():
                        with z.open("project.json") as f:
                            data = json.load(f)
                            proj = SongProject.from_dict(data)
                            proj.is_package = True
                            proj.package_path = str(path)
                            return proj
            except Exception as e:
                print(f"[ProjectService] Error loading .bsp project {path.name}: {e}")
                return None
        elif path.is_dir():
            json_file = path / "project.json"
            if json_file.exists():
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    proj = SongProject.from_dict(data)
                    proj.is_package = False
                    return proj

        return None

    def save_project(self, project: SongProject) -> None:
        """Saves project metadata to JSON or updates inside .bsp."""
        if project.is_package and project.package_path and Path(project.package_path).exists():
            bsp_file = Path(project.package_path)
            # Update project.json inside zip safely
            temp_bsp = bsp_file.with_suffix(".tmp.bsp")
            try:
                with zipfile.ZipFile(bsp_file, "r") as zin:
                    with zipfile.ZipFile(temp_bsp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                        for item in zin.infolist():
                            if item.filename != "project.json":
                                zout.writestr(item, zin.read(item.filename))
                        # Write updated project.json
                        zout.writestr("project.json", json.dumps(project.to_dict(), indent=2))
                shutil.move(str(temp_bsp), str(bsp_file))
                print(f"[ProjectService] Updated project.json inside {bsp_file.name}")
                return
            except Exception as e:
                print(f"[ProjectService] Error updating .bsp package: {e}")
                if temp_bsp.exists():
                    temp_bsp.unlink()

        proj_dir = self.root / project.id
        proj_dir.mkdir(parents=True, exist_ok=True)
        json_file = proj_dir / "project.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, indent=2)

    def create_demo_project(self) -> SongProject:
        """
        Creates a ready-to-test multitrack project with 4 stems:
        1. Click track (accented 120 BPM) -> Routed to Output 4 (In-Ear/Cue)
        2. Drums & Bass (Synthesized rhythm groove) -> Routed to Output 1
        3. Harmony & Synth (Chords) -> Routed to Output 2
        4. Lead / Guitars -> Routed to Output 3
        Perfect for testing the Behringer UMC404HD 4 hardware outputs!
        """
        proj_id = "demo-song"
        proj_dir = self.root / proj_id
        proj_dir.mkdir(parents=True, exist_ok=True)

        sr = 48000
        bpm = 120.0
        duration = 32.0  # 32 seconds (16 bars of 4/4)
        t = np.linspace(0, duration, int(sr * duration), False)

        # 1. Click Track
        click_path = proj_dir / "click.wav"
        save_click_wav(str(click_path), bpm=bpm, duration_seconds=duration, sample_rate=sr)

        # 2. Drums & Bass Stem (Kick on 1 & 3, Bass synth)
        drums_bass = np.zeros(len(t), dtype=np.float32)
        beat_interval = int(sr * 0.5) # 120 bpm = 0.5s per beat
        kick_samples = int(sr * 0.1)
        t_kick = np.linspace(0, 0.1, kick_samples, False)
        kick_wave = (np.sin(2 * np.pi * 65 * np.exp(-t_kick * 30) * t_kick) * np.exp(-t_kick * 20)).astype(np.float32)

        # Bass line (C, G, Am, F)
        bass_notes = [65.41, 48.99, 55.00, 43.65] # C2, G1, A1, F1
        for bar in range(16):
            note_freq = bass_notes[bar % 4]
            bar_start = bar * 4 * beat_interval
            for beat in range(4):
                idx = bar_start + beat * beat_interval
                if idx + kick_samples < len(drums_bass) and (beat == 0 or beat == 2):
                    drums_bass[idx : idx + kick_samples] += kick_wave * 0.8
                # bass tone
                note_len = int(beat_interval * 0.8)
                if idx + note_len < len(drums_bass):
                    t_note = np.linspace(0, 0.4, note_len, False)
                    drums_bass[idx : idx + note_len] += (np.sin(2 * np.pi * note_freq * t_note) * 0.4).astype(np.float32)

        drums_path = proj_dir / "drums_bass.wav"
        sf.write(str(drums_path), drums_bass, sr, subtype='PCM_24')

        # 3. Harmony Chords (Synth pad)
        chords = np.zeros(len(t), dtype=np.float32)
        chord_freqs = [
            [261.63, 329.63, 392.00], # C Major
            [196.00, 246.94, 293.66], # G Major
            [220.00, 261.63, 329.63], # A minor
            [174.61, 220.00, 261.63]  # F Major
        ]
        for bar in range(16):
            c_freq = chord_freqs[bar % 4]
            bar_start = bar * 4 * beat_interval
            bar_len = 4 * beat_interval
            if bar_start + bar_len <= len(chords):
                t_bar = np.linspace(0, 2.0, bar_len, False)
                pad = np.zeros(bar_len, dtype=np.float32)
                for f_note in c_freq:
                    pad += np.sin(2 * np.pi * f_note * t_bar) * 0.1
                # Smooth envelope
                env = np.sin(np.pi * np.linspace(0, 1, bar_len)) ** 0.5
                chords[bar_start : bar_start + bar_len] += (pad * env).astype(np.float32)

        chords_path = proj_dir / "chords.wav"
        sf.write(str(chords_path), chords, sr, subtype='PCM_24')

        # 4. Lead Arpeggio
        lead = np.zeros(len(t), dtype=np.float32)
        lead_notes = [523.25, 659.25, 783.99, 1046.50]
        arp_interval = int(sr * 0.125) # 16th notes
        for i in range(len(t) // arp_interval):
            freq = lead_notes[i % 4]
            idx = i * arp_interval
            arp_len = int(arp_interval * 0.7)
            if idx + arp_len < len(lead):
                t_arp = np.linspace(0, 0.08, arp_len, False)
                lead[idx : idx + arp_len] += (np.sin(2 * np.pi * freq * t_arp) * np.exp(-t_arp * 40) * 0.25).astype(np.float32)

        lead_path = proj_dir / "lead.wav"
        sf.write(str(lead_path), lead, sr, subtype='PCM_24')

        # Create Project Model
        project = SongProject(
            id=proj_id,
            title="BSplayer Demo - 4 Output Multitrack",
            artist="BSplayer Team",
            bpm=bpm,
            time_signature="4/4",
            duration_seconds=duration,
            tracks=[
                Track(
                    id="trk-1",
                    name="Drums & Bass",
                    filename="drums_bass.wav",
                    volume=1.0,
                    output_channel=0, # Hardware Output 1
                    group="Rhythm"
                ),
                Track(
                    id="trk-2",
                    name="Harmony & Synth",
                    filename="chords.wav",
                    volume=0.9,
                    output_channel=1, # Hardware Output 2
                    group="Keyboards"
                ),
                Track(
                    id="trk-3",
                    name="Lead Arpeggio",
                    filename="lead.wav",
                    volume=0.85,
                    output_channel=2, # Hardware Output 3
                    group="Guitars"
                ),
                Track(
                    id="trk-4",
                    name="Click & Count-in",
                    filename="click.wav",
                    volume=1.0,
                    output_channel=3, # Hardware Output 4 (In-Ear Cue)
                    is_click=True,
                    group="Click"
                )
            ],
            markers=[
                Marker("Intro", 0.0),
                Marker("Verse 1", 8.0),
                Marker("Chorus", 16.0),
                Marker("Outro", 24.0)
            ],
            lyrics=[
                LyricLine(0.0, "Bienvenidos a BSplayer", "[ C ]"),
                LyricLine(8.0, "Reproduciendo 4 stems independientes a 48kHz 24-bit", "[ G ]"),
                LyricLine(16.0, "Canal 4 dedicado a Claqueta en Auriculares", "[ Am ]"),
                LyricLine(24.0, "Sincronización exacta sin latencia ni jitter", "[ F ]")
            ]
        )

        self.save_project(project)
        return project

    def get_shows_dir(self) -> Path:
        p = self.root / "_shows"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def list_shows(self) -> List[Dict[str, Any]]:
        """Lists all setlists/shows."""
        shows_dir = self.get_shows_dir()
        shows = []
        for f in shows_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    shows.append(data)
            except Exception as e:
                print(f"[ProjectService] Error reading show {f}: {e}")

        # If no shows exist, create default show with all songs
        if not shows:
            default_show = self.create_show("Show Principal - Directo", [p["id"] for p in self.list_projects()])
            shows.append(default_show.to_dict())

        return shows

    def get_show(self, show_id: str) -> Optional[Dict[str, Any]]:
        show_file = self.get_shows_dir() / f"{show_id}.json"
        if show_file.exists():
            with open(show_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def save_show(self, show_data: Dict[str, Any]) -> Dict[str, Any]:
        show_id = show_data.get("id") or str(uuid.uuid4())[:8]
        show_data["id"] = show_id
        show_file = self.get_shows_dir() / f"{show_id}.json"
        with open(show_file, "w", encoding="utf-8") as f:
            json.dump(show_data, f, indent=2)
        return show_data

    def create_show(self, name: str, song_ids: List[str]) -> Any:
        from models.project import ShowPlaylist
        show = ShowPlaylist(
            id=str(uuid.uuid4())[:8],
            name=name,
            song_ids=song_ids,
            auto_next=False
        )
        self.save_show(show.to_dict())
        return show
