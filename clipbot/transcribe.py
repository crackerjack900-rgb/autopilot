"""Word-level transcript with faster-whisper (free, runs on CPU)."""
import json
from pathlib import Path

from . import log


def transcribe(video_path, model_name="small", language=None):
    out = Path(video_path).with_name("transcript.json")
    if out.exists():
        return json.loads(out.read_text())
    from faster_whisper import WhisperModel

    log(f"transcribing with whisper '{model_name}' (CPU)...")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    # Decode with ffmpeg ourselves: faster-whisper's own decoder (PyAV) breaks with some PyAV versions.
    import subprocess

    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    segments, info = model.transcribe(
        audio, language=language, word_timestamps=True, vad_filter=True, beam_size=5
    )
    words, segs = [], []
    for s in segments:
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"w": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)})
    data = {"language": info.language, "words": words, "segments": segs}
    out.write_text(json.dumps(data))
    log(f"transcript: {len(words)} words, language={info.language}")
    return data
