# Voice event markers

Atlas supports voice as an optional event-marker technique alongside the existing click-marker workflow.

## Modes

The Linux/PCG-1 capture UI exposes four marker modes:

- **Click markers** — existing deterministic event-start/event-end buttons.
- **Voice markers** — record a synchronized operator WAV track while CAN capture continues.
- **Click + voice** — keep precise click windows and record spoken observations at the same time.
- **Off** — raw CAN capture only.

Click remains the default. Voice recording is opt-in.

## Evidence boundary

Voice is supporting operator evidence, not a decoded vehicle signal and not proof that the operator's statement is correct. The raw CAN capture remains authoritative for network observations.

The Linux recorder uses ALSA `arecord` and writes two sidecar files next to the CAN log:

- `atlas_capture_YYYYMMDD_HHMMSS.voice.wav`
- `atlas_capture_YYYYMMDD_HHMMSS.voice.json`

The JSON sidecar records the application audio-start and audio-stop UTC anchors, audio format, sample rate, channel count, file size, and the timing boundary. ALSA microphone onset latency is deliberately marked **uncalibrated**. Correlations therefore use the evidence class `voiceSupportingEvidenceOnly` unless independent timing calibration and CAN evidence justify a stronger claim.

The raw WAV file is retained locally as source evidence. Transcription is derived evidence.

## Linux requirement

Voice capture currently requires ALSA `arecord`, normally supplied by `alsa-utils`.

If voice startup fails, CAN capture continues. In Voice-only mode the UI exposes click markers as a fallback rather than losing the experiment.

## Local transcription

`tools/transcribe_audio.py` restores the original Atlas local Faster-Whisper workflow. It creates a TSV containing:

```text
audio_start_seconds    audio_end_seconds    text
```

Example:

```bash
python3 tools/transcribe_audio.py \
  ~/Documents/'OBD Atlas'/logs/atlas_capture_20260913_170000.voice.wav
```

The transcription tool is optional and requires `faster-whisper` in the local analysis environment. Audio is not uploaded by the tool.

## Direct CAN correlation

Current PCG-1 captures can be analyzed without first building an Atlas SQLite manifest:

```bash
python3 tools/voice_event_correlator.py \
  atlas_capture_20260913_170000.log \
  atlas_capture_20260913_170000.voice.json \
  atlas_capture_20260913_170000.voice.transcript.tsv
```

For every spoken segment, the correlator compares a baseline window against the spoken/action window and ranks changing CAN ID/byte positions. It ignores `# ATLAS_EVENT` comment lines in the candump stream and writes a machine-readable JSON report.

Default analysis windows are:

- 5 seconds before speech start for baseline
- the spoken segment plus 0.75 seconds after it for action
- at least 3 observations in both windows

These defaults are research settings, not universal timing constants.

## Intended field use

During a multi-network capture an operator can say observations such as:

- `brake now`
- `start button now`
- `contactor clicked`
- `left signal on`
- `charger connected`
- `READY appeared`

The spoken observation is preserved as operator evidence and can be correlated against every captured CAN network. Click + voice is preferred when a hand is free because the click gives the strongest event boundary while the spoken note adds context.
