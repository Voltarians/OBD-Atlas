from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool"
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

import analyze_fleetcarma_volt_ids as analyze
import import_fleetcarma_c5 as fleetcarma


def _frame(ts: int, value: int) -> fleetcarma.CanRecord:
    return fleetcarma.CanRecord(
        source="fixture.BIN",
        offset=ts,
        timestamp_ms=ts,
        bus=1,
        can_id=0x210,
        data=bytes([value, 0x00, value, 0x00]),
    )


def _gps(ts: int, kph: float) -> fleetcarma.GpsRecord:
    return fleetcarma.GpsRecord(
        source="fixture.BIN",
        offset=ts,
        timestamp_ms=ts,
        sentence=f"GPVTG,0.00,T,,,0.00,N,{kph:.2f},K,A*00",
    )


class FleetCarmaSignalCorrelationTests(unittest.TestCase):
    def test_vtg_speed_parser(self) -> None:
        self.assertEqual(
            analyze.parse_vtg_speed_kph(
                "GPVTG,268.42,T,,,26.38,N,48.86,K,A*77"
            ),
            48.86,
        )
        self.assertIsNone(analyze.parse_vtg_speed_kph("GPGGA,123456.000,..."))

    def test_recovers_speed_correlated_byte_candidate(self) -> None:
        can = []
        gps = []
        for i in range(40):
            ts = i * 1000
            value = i * 3
            can.append(_frame(ts, value))
            gps.append(_gps(ts, float(value)))

        decoded = fleetcarma.DecodeResult(
            can=can,
            gps=gps,
            configured_ids=[],
            malformed_tail=False,
            bytes_consumed=100,
        )
        result = analyze.analyze_records(
            [("fixture.BIN", decoded)],
            max_speed_delta_ms=100,
            min_overlap=20,
        )

        self.assertEqual(result["mappingStatus"], "candidateOnly")
        top = result["topSpeedCandidates"][0]
        self.assertEqual(top["canIdHex"], "210")
        self.assertEqual(top["offset"], 0)
        self.assertGreaterEqual(top["absSpeedCorrelation"], 0.99)
        self.assertEqual(top["confidence"], "strongCandidate")

    def test_nearest_speed_respects_maximum_delta(self) -> None:
        samples = [analyze.Sample(1000, 10.0), analyze.Sample(5000, 20.0)]
        self.assertEqual(
            analyze.nearest_speed(1200, samples, max_delta_ms=500),
            10.0,
        )
        self.assertIsNone(
            analyze.nearest_speed(3000, samples, max_delta_ms=500)
        )

    def test_constant_byte_is_not_promoted(self) -> None:
        can = []
        gps = []
        for i in range(30):
            ts = i * 1000
            can.append(
                fleetcarma.CanRecord(
                    source="fixture.BIN",
                    offset=ts,
                    timestamp_ms=ts,
                    bus=1,
                    can_id=0x120,
                    data=bytes([0x55]),
                )
            )
            gps.append(_gps(ts, float(i)))

        decoded = fleetcarma.DecodeResult(
            can=can,
            gps=gps,
            configured_ids=[],
            malformed_tail=False,
            bytes_consumed=100,
        )
        result = analyze.analyze_records(
            [("fixture.BIN", decoded)],
            max_speed_delta_ms=100,
            min_overlap=20,
        )
        candidate = next(
            item for item in result["topSpeedCandidates"]
            if item["canIdHex"] == "120" and item["kind"] == "u8"
        )
        self.assertEqual(candidate["speedCorrelation"], 0.0)
        self.assertEqual(candidate["confidence"], "background")


if __name__ == "__main__":
    unittest.main()
