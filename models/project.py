from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import json

@dataclass
class Track:
    id: str
    name: str
    filename: str                      # Relative to project directory (e.g. "drums_L.wav")
    volume: float = 1.0                # 0.0 to 1.5
    pan: float = 0.0                   # -1.0 (Left) to +1.0 (Right)
    output_channel: int = 0            # Hardware output (0=Out 1, 1=Out 2, 2=Out 3, etc.)
    extra_outputs: List[int] = field(default_factory=list)
    aux_volume: float = 1.0            # Send volume for headphones/monitors
    aux_channel: Optional[int] = None  # Dedicated monitor output if any
    mute: bool = False
    solo: bool = False
    is_click: bool = False             # Is this the click/metronome track?
    group: str = "Main"                # Drums, Bass, Guitars, Keys, Vocals, Click, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "volume": self.volume,
            "pan": self.pan,
            "output_channel": self.output_channel,
            "extra_outputs": self.extra_outputs,
            "aux_volume": self.aux_volume,
            "aux_channel": self.aux_channel,
            "mute": self.mute,
            "solo": self.solo,
            "is_click": self.is_click,
            "group": self.group
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        return cls(
            id=data["id"],
            name=data["name"],
            filename=data["filename"],
            volume=float(data.get("volume", 1.0)),
            pan=float(data.get("pan", 0.0)),
            output_channel=int(data.get("output_channel", 0)),
            extra_outputs=data.get("extra_outputs", []),
            aux_volume=float(data.get("aux_volume", 1.0)),
            aux_channel=data.get("aux_channel"),
            mute=bool(data.get("mute", False)),
            solo=bool(data.get("solo", False)),
            is_click=bool(data.get("is_click", False)),
            group=data.get("group", "Main")
        )

@dataclass
class Marker:
    name: str
    time_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "time_seconds": self.time_seconds}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Marker":
        return cls(name=data["name"], time_seconds=float(data["time_seconds"]))

@dataclass
class LyricLine:
    time_seconds: float
    text: str
    chords: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"time_seconds": self.time_seconds, "text": self.text, "chords": self.chords}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LyricLine":
        return cls(
            time_seconds=float(data["time_seconds"]),
            text=data["text"],
            chords=data.get("chords")
        )

@dataclass
class SongProject:
    id: str
    title: str
    artist: str = ""
    bpm: float = 120.0
    time_signature: str = "4/4"
    duration_seconds: float = 0.0
    tracks: List[Track] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)
    lyrics: List[LyricLine] = field(default_factory=list)
    video_file: Optional[str] = None
    midi_file: Optional[str] = None
    midi_cues: List[Dict[str, Any]] = field(default_factory=list)
    is_package: bool = False
    package_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "bpm": self.bpm,
            "time_signature": self.time_signature,
            "duration_seconds": self.duration_seconds,
            "tracks": [t.to_dict() for t in self.tracks],
            "markers": [m.to_dict() for m in self.markers],
            "lyrics": [l.to_dict() for l in self.lyrics],
            "video_file": self.video_file,
            "midi_file": self.midi_file,
            "midi_cues": self.midi_cues,
            "is_package": self.is_package,
            "package_path": self.package_path
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SongProject":
        return cls(
            id=data["id"],
            title=data["title"],
            artist=data.get("artist", ""),
            bpm=float(data.get("bpm", 120.0)),
            time_signature=data.get("time_signature", "4/4"),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            tracks=[Track.from_dict(t) for t in data.get("tracks", [])],
            markers=[Marker.from_dict(m) for m in data.get("markers", [])],
            lyrics=[LyricLine.from_dict(l) for l in data.get("lyrics", [])],
            video_file=data.get("video_file"),
            midi_file=data.get("midi_file"),
            midi_cues=data.get("midi_cues", []),
            is_package=bool(data.get("is_package", False)),
            package_path=data.get("package_path")
        )

@dataclass
class ShowPlaylist:
    id: str
    name: str
    song_ids: List[str] = field(default_factory=list)
    auto_next: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "song_ids": self.song_ids,
            "auto_next": self.auto_next
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShowPlaylist":
        return cls(
            id=data["id"],
            name=data.get("name", "Nuevo Show"),
            song_ids=data.get("song_ids", []),
            auto_next=bool(data.get("auto_next", False))
        )
