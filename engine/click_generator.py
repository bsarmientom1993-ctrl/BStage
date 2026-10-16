import numpy as np
import soundfile as sf
from typing import Tuple

def generate_click_audio(
    bpm: float,
    duration_seconds: float,
    sample_rate: int = 48000,
    time_sig_beats: int = 4,
    accent_freq: float = 1600.0,
    beat_freq: float = 800.0,
    click_duration: float = 0.03
) -> np.ndarray:
    """
    Generates a sample-accurate click track with accented first beats.
    Returns 1D float32 numpy array.
    """
    total_samples = int(duration_seconds * sample_rate)
    output = np.zeros(total_samples, dtype=np.float32)

    beat_interval_samples = int(sample_rate * (60.0 / bpm))
    click_samples = int(sample_rate * click_duration)

    # Click waveforms with exponential decay envelope
    t_click = np.linspace(0, click_duration, click_samples, endpoint=False)
    envelope = np.exp(-t_click * 80.0).astype(np.float32)

    high_click = (np.sin(2 * np.pi * accent_freq * t_click) * envelope * 0.9).astype(np.float32)
    low_click = (np.sin(2 * np.pi * beat_freq * t_click) * envelope * 0.6).astype(np.float32)

    current_sample = 0
    beat_count = 0

    while current_sample < total_samples:
        is_accent = (beat_count % time_sig_beats == 0)
        click_sound = high_click if is_accent else low_click

        end_sample = min(current_sample + click_samples, total_samples)
        sound_len = end_sample - current_sample
        output[current_sample:end_sample] += click_sound[:sound_len]

        current_sample += beat_interval_samples
        beat_count += 1

    return output

def save_click_wav(filepath: str, bpm: float, duration_seconds: float, sample_rate: int = 48000) -> None:
    data = generate_click_audio(bpm, duration_seconds, sample_rate)
    sf.write(filepath, data, sample_rate, subtype='PCM_24')
