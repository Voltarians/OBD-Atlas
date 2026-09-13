import 'package:flutter/material.dart';

import 'core/atlas_runtime.dart';
import 'core/capture_session.dart';
import 'core/signal_discovery.dart';
import 'core/voice_annotation_capture.dart';

/// Linux capture page with optional click markers, synchronized voice markers,
/// both marker sources, or no event markers.
class VoiceCapableCapturePage extends StatefulWidget {
  const VoiceCapableCapturePage({super.key});

  @override
  State<VoiceCapableCapturePage> createState() => _VoiceCapableCapturePageState();
}

class _VoiceCapableCapturePageState extends State<VoiceCapableCapturePage> {
  final _eventLabel = TextEditingController(text: 'Brake');
  final VoiceAnnotationCapture _voice = VoiceAnnotationCapture.shared;
  EventMarkerMode _markerMode = EventMarkerMode.click;
  bool _starting = false;
  bool _stopping = false;

  @override
  void initState() {
    super.initState();
    _voice.bindToCapture(AtlasRuntime.instance.capture);
    _voice.addListener(_voiceChanged);
  }

  void _voiceChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _voice.removeListener(_voiceChanged);
    _eventLabel.dispose();
    super.dispose();
  }

  Future<void> _startCapture() async {
    final runtime = AtlasRuntime.instance;
    setState(() => _starting = true);
    try {
      final canFile = await runtime.startCapture(eventLabel: _eventLabel.text);
      runtime.markCaptureEvent(
        'Marker mode: ${_markerMode.name}',
        source: 'atlas_marker_mode',
      );
      if (_markerMode.usesVoice) {
        try {
          final audio = await _voice.start(canFile);
          runtime.markCaptureEvent(
            'Voice annotation start: ${audio.uri.pathSegments.last}',
            source: 'voice',
          );
        } catch (error) {
          runtime.markCaptureEvent(
            'Voice annotation unavailable',
            source: 'voice_error',
          );
          _showMessage(
            'CAN capture is still running. Voice could not start: $error',
          );
        }
      }
    } catch (error) {
      _showMessage(error.toString());
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  Future<void> _stopCapture() async {
    final runtime = AtlasRuntime.instance;
    setState(() => _stopping = true);
    try {
      if (_voice.isRecording || _voice.isStopping) {
        if (runtime.capture.isRecording) {
          runtime.markCaptureEvent('Voice annotation stop', source: 'voice');
        }
        await _voice.stop();
      }
      await runtime.stopCapture();
    } catch (error) {
      _showMessage(error.toString());
    } finally {
      if (mounted) setState(() => _stopping = false);
    }
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        final phase = runtime.capture.phase;
        final isStarting = phase == CapturePhase.starting || _starting;
        final isRecording = phase == CapturePhase.recording;
        final isStopping = phase == CapturePhase.stopping || _stopping;
        final clickEnabled = _markerMode.usesClick;
        final voiceEnabled = _markerMode.usesVoice;
        final voiceFallbackToClick = voiceEnabled &&
            !_voice.isRecording &&
            _voice.lastError != null;
        final showClickControls = clickEnabled || voiceFallbackToClick;

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text('Passive Capture', style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 4),
            const Text(
              'All connected Linux CAN transports feed one candump-compatible evidence stream. Event markers can be click, voice, both, or off.',
            ),
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  children: [
                    Icon(
                      isRecording || isStopping
                          ? Icons.stop_circle
                          : Icons.fiber_manual_record,
                      size: 56,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      isStarting
                          ? 'Starting capture…'
                          : isRecording
                              ? 'Capture active'
                              : isStopping
                                  ? 'Stopping and saving…'
                                  : runtime.anyConnected
                                      ? '${runtime.connectedChannelCount} channels ready'
                                      : 'Connect at least one CAN interface',
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '${runtime.totalFrames} total frames • ${runtime.framesPerSecond} frames/s',
                    ),
                    const SizedBox(height: 16),
                    if (phase == CapturePhase.idle) ...[
                      SizedBox(
                        width: 360,
                        child: TextField(
                          controller: _eventLabel,
                          decoration: const InputDecoration(
                            labelText: 'Discovery event',
                            hintText: 'Brake, accelerator, switch…',
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: 360,
                        child: DropdownButtonFormField<EventMarkerMode>(
                          initialValue: _markerMode,
                          decoration: const InputDecoration(
                            labelText: 'Event markers',
                          ),
                          items: EventMarkerMode.values
                              .map(
                                (mode) => DropdownMenuItem(
                                  value: mode,
                                  child: Text(mode.displayName),
                                ),
                              )
                              .toList(),
                          onChanged: (mode) {
                            if (mode != null) setState(() => _markerMode = mode);
                          },
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _markerMode == EventMarkerMode.voice
                            ? 'Voice mode records a synchronized WAV track. Speak the event aloud; local transcription can correlate it with CAN changes later.'
                            : _markerMode == EventMarkerMode.clickAndVoice
                                ? 'Click markers retain deterministic timing while voice records hands-free operator observations.'
                                : _markerMode == EventMarkerMode.off
                                    ? 'Raw capture only. No event markers are required.'
                                    : 'Click start/end markers use the current deterministic discovery window.',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: runtime.anyConnected && !isStarting
                            ? _startCapture
                            : null,
                        icon: isStarting
                            ? const SizedBox.square(
                                dimension: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.play_arrow),
                        label: const Text('Start baseline capture'),
                      ),
                    ] else if (isRecording) ...[
                      if (voiceEnabled) _voiceStatusCard(),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        alignment: WrapAlignment.center,
                        children: [
                          if (showClickControls &&
                              runtime.discovery.phase == DiscoveryPhase.baseline)
                            FilledButton.icon(
                              onPressed: runtime.markDiscoveryEventStart,
                              icon: const Icon(Icons.flag),
                              label: Text(
                                voiceFallbackToClick
                                    ? 'Voice unavailable • mark ${runtime.discovery.eventLabel} start'
                                    : 'Mark ${runtime.discovery.eventLabel} start',
                              ),
                            ),
                          if (showClickControls &&
                              runtime.discovery.phase == DiscoveryPhase.event)
                            FilledButton.icon(
                              onPressed: runtime.markDiscoveryEventEnd,
                              icon: const Icon(Icons.flag_outlined),
                              label: Text('Mark ${runtime.discovery.eventLabel} end'),
                            ),
                          FilledButton.tonalIcon(
                            onPressed: isStopping ? null : _stopCapture,
                            icon: const Icon(Icons.stop),
                            label: const Text('Stop capture'),
                          ),
                        ],
                      ),
                    ] else
                      FilledButton.icon(
                        onPressed: null,
                        icon: const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        label: Text(
                          isStopping ? 'Saving capture…' : 'Opening capture…',
                        ),
                      ),
                    if (runtime.activeCaptureFile != null) ...[
                      const SizedBox(height: 10),
                      SelectableText(runtime.activeCaptureFile!.path),
                    ],
                    if (_voice.lastCompletedAudioFile != null &&
                        phase == CapturePhase.idle) ...[
                      const SizedBox(height: 10),
                      SelectableText(
                        'Voice evidence: ${_voice.lastCompletedAudioFile!.path}',
                      ),
                    ],
                    if (_voice.lastCompletedMetadataFile != null &&
                        phase == CapturePhase.idle) ...[
                      const SizedBox(height: 4),
                      SelectableText(
                        'Voice timing metadata: ${_voice.lastCompletedMetadataFile!.path}',
                      ),
                    ],
                    if (phase == CapturePhase.idle &&
                        runtime.capture.lastCompletedFile != null) ...[
                      const SizedBox(height: 10),
                      Text('Saved ${runtime.capture.lastCompletedFrames} frames'),
                    ],
                    if (phase == CapturePhase.idle &&
                        runtime.discovery.phase == DiscoveryPhase.complete &&
                        runtime.discovery.candidates.isNotEmpty) ...[
                      const SizedBox(height: 20),
                      const Divider(),
                      const SizedBox(height: 8),
                      Text(
                        '${runtime.discovery.eventLabel} signal candidates',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 8),
                      ...runtime.discovery.candidates.take(20).map(
                            (candidate) => ListTile(
                              dense: true,
                              leading: CircleAvatar(
                                child: Text('${candidate.channel}'),
                              ),
                              title: Text(
                                'CH${candidate.channel} • ID ${candidate.idHex} • byte ${candidate.byteIndex} bit ${candidate.bitIndex}',
                              ),
                              subtitle: Text('Bit set: ${candidate.transition}'),
                              trailing: Text(candidate.score.toStringAsFixed(2)),
                            ),
                          ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _voiceStatusCard() {
    final recording = _voice.isRecording;
    final error = _voice.lastError;
    return Card(
      child: ListTile(
        leading: Icon(recording ? Icons.mic : Icons.mic_off),
        title: Text(
          recording
              ? 'Synchronized voice annotation recording'
              : error == null
                  ? 'Starting voice annotation…'
                  : 'Voice annotation unavailable',
        ),
        subtitle: Text(
          recording
              ? 'Speak observations naturally. Audio is supporting evidence; microphone latency is not treated as exact CAN timing.'
              : error?.toString() ?? 'Opening ALSA microphone input.',
        ),
      ),
    );
  }
}
