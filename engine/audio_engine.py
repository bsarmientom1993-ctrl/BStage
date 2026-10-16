import threading
import time
import io
import re
import zipfile
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import sounddevice as sd
import soundfile as sf
import numpy as np

from models.project import SongProject, Track

class AudioEngine:
    def __init__(self, sample_rate: int = 48000, blocksize: int = 512):
        self.sample_rate = sample_rate
        self.blocksize = blocksize

        # Device configuration
        self.device_index: Optional[int] = None
        self.num_output_channels: int = 2   # Defaults to stereo, can be 4 (UMC404HD), 8, 16

        # Audio Stream
        self.stream: Optional[sd.OutputStream] = None
        self.lock = threading.RLock()

        # Loaded project & track data
        self.current_project: Optional[SongProject] = None
        self.track_buffers: Dict[str, np.ndarray] = {}  # track_id -> 1D float32 numpy array
        self.total_samples: int = 0

        # Playback state
        self.is_playing: bool = False
        self.position_sample: int = 0
        self.loop_enabled: bool = False
        self.loop_start_sample: int = 0
        self.loop_end_sample: int = 0

        # Master settings
        self.master_volume: float = 1.0

        # Real-time VU meters (peak per output channel, 0.0 to 1.0)
        self.peak_levels: List[float] = [0.0] * self.num_output_channels

        # Detect and set initial default output
        self._auto_select_device()

    def _auto_select_device(self):
        """Auto-detect Behringer UMC or default system audio device."""
        devices = sd.query_devices()
        # Prefer Behringer UMC 404HD WASAPI if found
        for idx, dev in enumerate(devices):
            name = dev.get("name", "")
            hostapi = sd.query_hostapis(dev.get("hostapi", 0)).get("name", "")
            max_out = dev.get("max_output_channels", 0)
            if "UMC 404HD" in name and max_out >= 4 and "WASAPI" in hostapi:
                self.device_index = idx
                self.num_output_channels = 4
                print(f"[AudioEngine] Auto-selected UMC404HD WASAPI: device {idx} ({max_out} channels)")
                return

        # Fallback to default output
        default_dev = sd.default.device[1]
        if default_dev is not None and default_dev >= 0:
            dev_info = sd.query_devices(default_dev)
            self.device_index = default_dev
            self.num_output_channels = min(dev_info.get("max_output_channels", 2), 2)
            print(f"[AudioEngine] Selected default output device: {dev_info.get('name')} ({self.num_output_channels} ch)")

    def get_available_devices(self) -> List[Dict[str, Any]]:
        """Returns list of output audio devices."""
        devices = []
        hostapis = sd.query_hostapis()
        for idx, dev in enumerate(sd.query_devices()):
            max_out = dev.get("max_output_channels", 0)
            if max_out > 0:
                api_name = hostapis[dev.get("hostapi", 0)].get("name", "")
                devices.append({
                    "id": idx,
                    "name": dev.get("name"),
                    "hostapi": api_name,
                    "max_channels": max_out,
                    "default_samplerate": dev.get("default_samplerate"),
                    "is_active": (idx == self.device_index)
                })
        return devices

    def set_device(self, device_index: int, channels: Optional[int] = None):
        """Switches the hardware audio device."""
        with self.lock:
            was_playing = self.is_playing
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None

            dev_info = sd.query_devices(device_index)
            max_out = dev_info.get("max_output_channels", 2)
            self.device_index = device_index
            self.num_output_channels = channels if channels and channels <= max_out else max_out
            self.peak_levels = [0.0] * self.num_output_channels

            self._restart_stream()
            if was_playing:
                self.play()

    def _restart_stream(self):
        """Starts or restarts the sounddevice OutputStream."""
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()

            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.blocksize,
                device=self.device_index,
                channels=self.num_output_channels,
                dtype='float32',
                callback=self._audio_callback
            )
            self.stream.start()
            print(f"[AudioEngine] Stream active on device {self.device_index} with {self.num_output_channels} ch at {self.sample_rate}Hz")
        except Exception as e:
            print(f"[AudioEngine] Error opening audio stream: {e}")
            self.stream = None

    def load_project(self, project: SongProject, base_path: Path):
        """
        Loads all project audio files into memory.
        Supports both:
        - A directory containing WAV files
        - A single .bsp (BSplayer Package) file containing all stems and assets!
        """
        with self.lock:
            self.stop()
            self.current_project = project
            self.track_buffers.clear()
            max_samples = 0

            def normalize_name(s: str) -> str:
                return re.sub(r'[^a-zA-Z0-9]', '', Path(s).stem.lower())

            is_bsp_file = base_path.is_file() and base_path.suffix.lower() == ".bsp"

            if is_bsp_file:
                print(f"[AudioEngine] Abriendo paquete único .bsp: {base_path.name}")
                try:
                    with zipfile.ZipFile(base_path, 'r') as z:
                        zip_names = z.namelist()
                        available_wavs = [n for n in zip_names if n.lower().endswith(('.wav', '.flac', '.aif', '.aiff', '.mp3', '.ogg')) and not n.startswith('__')]
                        used_wavs = set()

                        for idx, track in enumerate(project.tracks):
                            matched_entry = None

                            # 1. Exact match
                            if track.filename in zip_names:
                                matched_entry = track.filename
                            elif Path(track.filename).name in zip_names:
                                matched_entry = Path(track.filename).name

                            # 2. Normalized filename match (ignore spaces, _, -)
                            if not matched_entry:
                                norm_fn = normalize_name(track.filename)
                                for wav in available_wavs:
                                    if wav not in used_wavs and normalize_name(wav) == norm_fn:
                                        matched_entry = wav
                                        break

                            # 3. Track name match (e.g. track name is contained in wav name)
                            if not matched_entry:
                                norm_tr = normalize_name(track.name)
                                for wav in available_wavs:
                                    if wav not in used_wavs:
                                        norm_w = normalize_name(wav)
                                        if norm_tr and (norm_tr in norm_w or norm_w in norm_tr):
                                            matched_entry = wav
                                            break

                            # 4. Numbered stem matching (e.g. -001, -002, 01, etc.)
                            if not matched_entry:
                                for wav in available_wavs:
                                    if wav not in used_wavs:
                                        nums = re.findall(r'\d+', Path(wav).stem)
                                        if nums and (int(nums[-1]) == idx + 1 or int(nums[-1]) == idx):
                                            matched_entry = wav
                                            break

                            # 5. Fallback sequential matching
                            if not matched_entry:
                                remaining = [w for w in available_wavs if w not in used_wavs]
                                if remaining:
                                    matched_entry = remaining[0]

                            if matched_entry:
                                used_wavs.add(matched_entry)
                                try:
                                    with z.open(matched_entry) as f:
                                        raw_bytes = io.BytesIO(f.read())
                                        data, sr = sf.read(raw_bytes, dtype='float32')
                                        if data.ndim > 1:
                                            data = data[:, 0]
                                        self.track_buffers[track.id] = data
                                        if len(data) > max_samples:
                                            max_samples = len(data)
                                        print(f"[AudioEngine] Stem '{track.name}' cargado como '{matched_entry}' ({len(data)} muestras, {len(data)/self.sample_rate:.1f}s)")
                                except Exception as e:
                                    print(f"[AudioEngine] Error leyendo stem {track.name} ({matched_entry}): {e}")
                            else:
                                print(f"[AudioEngine] No se encontró archivo de audio para pista: {track.name}")
                except Exception as e:
                    print(f"[AudioEngine] Error abriendo archivo .bsp: {e}")
            else:
                available_files = list(base_path.glob("*.wav")) + list(base_path.glob("*.mp3"))
                audio_dir = base_path / "audio"
                if audio_dir.exists():
                    available_files += list(audio_dir.glob("*.wav")) + list(audio_dir.glob("*.mp3"))
                used_files = set()

                for idx, track in enumerate(project.tracks):
                    matched_file = None
                    file_path = base_path / track.filename
                    if not file_path.exists():
                        file_path = base_path / "audio" / Path(track.filename).name

                    if file_path.exists():
                        matched_file = file_path
                    else:
                        norm_fn = normalize_name(track.filename)
                        for f in available_files:
                            if f not in used_files and normalize_name(f.name) == norm_fn:
                                matched_file = f
                                break
                        if not matched_file:
                            norm_tr = normalize_name(track.name)
                            for f in available_files:
                                if f not in used_files:
                                    nw = normalize_name(f.name)
                                    if norm_tr and (norm_tr in nw or nw in norm_tr):
                                        matched_file = f
                                        break
                        if not matched_file:
                            remaining = [f for f in available_files if f not in used_files]
                            if remaining:
                                matched_file = remaining[0]

                    if matched_file and matched_file.exists():
                        used_files.add(matched_file)
                        try:
                            data, sr = sf.read(str(matched_file), dtype='float32')
                            if data.ndim > 1:
                                data = data[:, 0]
                            self.track_buffers[track.id] = data
                            if len(data) > max_samples:
                                max_samples = len(data)
                            print(f"[AudioEngine] Loaded track '{track.name}' ({matched_file.name}) ({len(data)} samples, {len(data)/self.sample_rate:.1f}s)")
                        except Exception as e:
                            print(f"[AudioEngine] Error loading track {track.name}: {e}")
                    else:
                        print(f"[AudioEngine] Track file not found: {track.filename}")

            self.total_samples = max_samples
            project.duration_seconds = max_samples / self.sample_rate if self.sample_rate > 0 else 0.0
            self.position_sample = 0

            # Ensure audio stream is running
            if self.stream is None or not self.stream.active:
                self._restart_stream()

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        """
        Real-time audio mixing callback.
        Executed in high-priority audio thread.
        Renders all tracks to assigned hardware output channels with zero phase drift.
        """
        if status:
            pass # buffer underflow/overflow warning

        outdata.fill(0.0)

        if not self.is_playing or self.current_project is None or self.total_samples == 0:
            self.peak_levels = [0.0] * self.num_output_channels
            return

        pos = self.position_sample
        if pos >= self.total_samples:
            if self.loop_enabled and self.loop_end_sample > self.loop_start_sample:
                self.position_sample = self.loop_start_sample
                pos = self.loop_start_sample
            else:
                self.is_playing = False
                self.position_sample = 0
                return

        end_pos = min(pos + frames, self.total_samples)
        actual_frames = end_pos - pos

        # Check if any track has Solo active
        any_solo = any(t.solo for t in self.current_project.tracks)

        # Mix all tracks into outdata
        for track in self.current_project.tracks:
            if track.mute:
                continue
            if any_solo and not track.solo:
                continue

            buf = self.track_buffers.get(track.id)
            if buf is None:
                continue

            track_len = len(buf)
            if pos >= track_len:
                continue

            take_frames = min(actual_frames, track_len - pos)
            slice_data = buf[pos : pos + take_frames]
            vol = track.volume * self.master_volume

            # Route to primary hardware output channel
            ch = track.output_channel
            if 0 <= ch < self.num_output_channels:
                outdata[:take_frames, ch] += slice_data * vol

            # Route to extra outputs if configured
            for extra_ch in track.extra_outputs:
                if 0 <= extra_ch < self.num_output_channels:
                    outdata[:take_frames, extra_ch] += slice_data * vol

            # Route to Aux / Headphone output if configured
            if track.aux_channel is not None and 0 <= track.aux_channel < self.num_output_channels:
                aux_vol = track.aux_volume * self.master_volume
                outdata[:take_frames, track.aux_channel] += slice_data * aux_vol

        # Update position
        self.position_sample += actual_frames

        # Compute peak levels per output channel for VU meters (decaying envelope)
        for c in range(self.num_output_channels):
            peak = float(np.max(np.abs(outdata[:, c]))) if actual_frames > 0 else 0.0
            # Smooth peak meter
            self.peak_levels[c] = max(peak, self.peak_levels[c] * 0.85)

    def play(self):
        """Starts playback."""
        with self.lock:
            if self.current_project is None or self.total_samples == 0:
                return
            if self.stream is None or not self.stream.active:
                self._restart_stream()
            self.is_playing = True

    def pause(self):
        """Pauses playback."""
        with self.lock:
            self.is_playing = False

    def stop(self):
        """Stops playback and rewinds to 0."""
        with self.lock:
            self.is_playing = False
            self.position_sample = 0
            self.peak_levels = [0.0] * self.num_output_channels

    def seek(self, seconds: float):
        """Seeks to a specific timestamp in seconds."""
        with self.lock:
            sample = int(seconds * self.sample_rate)
            self.position_sample = max(0, min(sample, self.total_samples))

    def set_track_volume(self, track_id: str, volume: float):
        if self.current_project:
            for t in self.current_project.tracks:
                if t.id == track_id:
                    t.volume = max(0.0, min(float(volume), 2.0))
                    break

    def set_track_mute(self, track_id: str, mute: bool):
        if self.current_project:
            for t in self.current_project.tracks:
                if t.id == track_id:
                    t.mute = mute
                    break

    def set_track_solo(self, track_id: str, solo: bool):
        if self.current_project:
            for t in self.current_project.tracks:
                if t.id == track_id:
                    t.solo = solo
                    break

    def set_track_output(self, track_id: str, output_channel: int):
        if self.current_project:
            for t in self.current_project.tracks:
                if t.id == track_id:
                    t.output_channel = max(0, min(output_channel, self.num_output_channels - 1))
                    break

    def set_master_volume(self, volume: float):
        self.master_volume = max(0.0, min(float(volume), 2.0))

    def close(self):
        """Stops and releases hardware audio stream."""
        with self.lock:
            self.is_playing = False
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

    def get_status(self) -> Dict[str, Any]:
        """Returns the current state of the player."""
        current_sec = self.position_sample / self.sample_rate if self.sample_rate > 0 else 0.0
        total_sec = self.total_samples / self.sample_rate if self.sample_rate > 0 else 0.0

        current_marker = None
        current_lyric = None

        if self.current_project:
            # Find current marker
            for m in reversed(self.current_project.markers):
                if current_sec >= m.time_seconds:
                    current_marker = m.name
                    break

            # Find current lyric line
            for l in reversed(self.current_project.lyrics):
                if current_sec >= l.time_seconds:
                    current_lyric = {"text": l.text, "chords": l.chords}
                    break

        return {
            "is_playing": self.is_playing,
            "current_time": current_sec,
            "duration": total_sec,
            "position_sample": self.position_sample,
            "total_samples": self.total_samples,
            "device_index": self.device_index,
            "num_channels": self.num_output_channels,
            "master_volume": self.master_volume,
            "peak_levels": [round(p, 3) for p in self.peak_levels],
            "current_marker": current_marker,
            "current_lyric": current_lyric,
            "project_id": self.current_project.id if self.current_project else None,
            "project_title": self.current_project.title if self.current_project else None,
            "bpm": self.current_project.bpm if self.current_project else 120.0
        }
