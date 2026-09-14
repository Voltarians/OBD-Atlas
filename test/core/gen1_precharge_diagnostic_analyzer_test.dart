import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/gen1_precharge_diagnostic_analyzer.dart';

Gen1TimedHpcm2State sample(int milliseconds, int raw) =>
    Gen1TimedHpcm2State(
      timestamp: Duration(milliseconds: milliseconds),
      rawState: raw,
    );

Gen1TimedPrechargeVoltage voltage(
  int milliseconds,
  double pack,
  double dcLink,
) =>
    Gen1TimedPrechargeVoltage(
      timestamp: Duration(milliseconds: milliseconds),
      packVoltage: pack,
      dcLinkVoltage: dcLink,
    );

void main() {
  group('Gen1PrechargeDiagnosticAnalyzer', () {
    test('classifies the vehicle-confirmed successful startup sequence', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze([
        sample(0, 0x68),
        sample(200, 0x6A),
        sample(400, 0x6F),
        sample(600, 0x6B),
      ]);

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.successfulStartup,
      );
      expect(report.sequence, [0x68, 0x6A, 0x6F, 0x6B]);
      expect(report.reachedFirstMainContactor, isTrue);
      expect(report.reachedPrecharge, isTrue);
      expect(report.reachedHvBusEstablished, isTrue);
      expect(report.firstMainToPrecharge, const Duration(milliseconds: 200));
      expect(
        report.prechargeToHvBusEstablished,
        const Duration(milliseconds: 200),
      );
      expect(
        report.voltageAssessment.result,
        Gen1PrechargeVoltageResult.insufficientData,
      );
    });

    test('confirms voltage convergence during successful precharge', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze(
        [
          sample(0, 0x68),
          sample(200, 0x6A),
          sample(400, 0x6F),
          sample(800, 0x6B),
        ],
        voltageSamples: [
          voltage(400, 360.0, 10.0),
          voltage(500, 360.0, 150.0),
          voltage(650, 360.0, 300.0),
          voltage(800, 360.0, 340.0),
        ],
      );

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.successfulStartup,
      );
      expect(
        report.voltageAssessment.result,
        Gen1PrechargeVoltageResult.converged,
      );
      expect(report.voltageAssessment.bestConvergenceRatio, closeTo(340 / 360, 0.001));
    });

    test('detects commanded precharge with no meaningful DC-link rise', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze(
        [
          sample(0, 0x68),
          sample(200, 0x6A),
          sample(400, 0x6F),
          sample(1000, 0x6F),
        ],
        voltageSamples: [
          voltage(400, 360.0, 8.0),
          voltage(600, 360.0, 12.0),
          voltage(900, 360.0, 15.0),
        ],
      );

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.prechargeVoltageFailedToRise,
      );
      expect(
        report.voltageAssessment.result,
        Gen1PrechargeVoltageResult.failedToRise,
      );
    });

    test('detects DC-link rise that never converges with pack voltage', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze(
        [
          sample(0, 0x68),
          sample(200, 0x6A),
          sample(400, 0x6F),
          sample(1000, 0x6F),
        ],
        voltageSamples: [
          voltage(400, 360.0, 10.0),
          voltage(600, 360.0, 80.0),
          voltage(900, 360.0, 180.0),
        ],
      );

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.prechargeVoltageDidNotConverge,
      );
      expect(
        report.voltageAssessment.result,
        Gen1PrechargeVoltageResult.roseButDidNotConverge,
      );
    });

    test('does not guess voltage failure from one sample', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze(
        [
          sample(0, 0x68),
          sample(200, 0x6A),
          sample(400, 0x6F),
          sample(1000, 0x6F),
        ],
        voltageSamples: [voltage(500, 360.0, 10.0)],
      );

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.stalledInPrecharge,
      );
      expect(
        report.voltageAssessment.result,
        Gen1PrechargeVoltageResult.insufficientData,
      );
    });

    test('collapses repeated samples before classifying', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze([
        sample(0, 0x68),
        sample(100, 0x68),
        sample(200, 0x6A),
        sample(300, 0x6A),
        sample(400, 0x6F),
        sample(500, 0x6F),
        sample(600, 0x6B),
      ]);

      expect(report.sequence, [0x68, 0x6A, 0x6F, 0x6B]);
      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.successfulStartup,
      );
    });

    test('detects no first-main-contactor engagement', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze([
        sample(0, 0x68),
        sample(500, 0x68),
      ]);

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.noMainContactorEngagement,
      );
    });

    test('detects a stall after first main contactor', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze([
        sample(0, 0x68),
        sample(200, 0x6A),
        sample(500, 0x6A),
      ]);

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.stalledAfterFirstMainContactor,
      );
      expect(report.reachedPrecharge, isFalse);
    });

    test('detects a stall in precharge before HV bus established', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze([
        sample(0, 0x68),
        sample(200, 0x6A),
        sample(400, 0x6F),
        sample(900, 0x6F),
      ]);

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.stalledInPrecharge,
      );
      expect(report.reachedHvBusEstablished, isFalse);
    });

    test('does not over-interpret an unexpected sequence', () {
      final report = Gen1PrechargeDiagnosticAnalyzer.analyze([
        sample(0, 0x6A),
        sample(200, 0x6B),
      ]);

      expect(
        report.result,
        Gen1PrechargeDiagnosticResult.unexpectedOrIncompleteSequence,
      );
    });
  });
}
