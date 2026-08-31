#!/usr/bin/env python3
"""Create timestamped voice annotations from an Atlas capture audio file."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="base.en")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    audio = args.audio.expanduser().resolve()
    if not audio.is_file():
        parser.error(f"audio file does not exist: {audio}")
    output = args.output or audio.with_suffix(".transcript.tsv")
    output = output.expanduser().resolve()

    print(f"Loading Whisper model: {args.model}")
    model = WhisperModel(
        args.model, device=args.device, compute_type=args.compute_type
    )
    print(f"Transcribing: {audio}")
    segments, info = model.transcribe(
        str(audio),
        language="en",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    count = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("audio_start_seconds", "audio_end_seconds", "text"))
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            writer.writerow((f"{segment.start:.3f}", f"{segment.end:.3f}", text))
            print(f"[{segment.start:8.3f} - {segment.end:8.3f}] {text}")
            count += 1

    print(f"Language: {info.language} ({info.language_probability:.3f})")
    print(f"Segments: {count}")
    print(f"Transcript: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
