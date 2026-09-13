import ctypes as C
import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "tool" / "uc2_vcx_bench.py"
SPEC = importlib.util.spec_from_file_location("uc2_vcx_bench", MODULE_PATH)
bench = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bench)


class Uc2VcxBenchTests(unittest.TestCase):
    def test_native_layouts_match_controlcan(self):
        bench.check_layouts()
        self.assertEqual(C.sizeof(bench.VciInitConfig), 16)
        self.assertEqual(C.sizeof(bench.VciCanObj), 24)

    def test_500k_config_is_active_mode(self):
        config = bench.make_init_config(500000)
        self.assertEqual(config.Timing0, 0x00)
        self.assertEqual(config.Timing1, 0x1C)
        self.assertEqual(config.Mode, 0)

    def test_probe_match_is_exact(self):
        self.assertTrue(
            bench.matches_vcx_probe(0x7E4, bytes((0x02, 0x3E, 0x00)))
        )
        self.assertFalse(
            bench.matches_vcx_probe(0x7E4, bytes((0x02, 0x3E, 0x80)))
        )
        self.assertFalse(
            bench.matches_vcx_probe(0x7E5, bytes((0x02, 0x3E, 0x00)))
        )
        self.assertFalse(
            bench.matches_vcx_probe(
                0x7E4,
                bytes((0x02, 0x3E, 0x00)),
                extended=True,
            )
        )
        self.assertFalse(
            bench.matches_vcx_probe(
                0x7E4,
                bytes((0x02, 0x3E, 0x00)),
                remote=True,
            )
        )

    def test_response_is_single_exact_tester_present_reply(self):
        frame = bench.make_response_frame()
        self.assertEqual(frame.ID, 0x7EC)
        self.assertEqual(frame.DataLen, 3)
        self.assertEqual(bench.frame_bytes(frame), bytes((0x02, 0x7E, 0x00)))
        self.assertEqual(frame.ExternFlag, 0)
        self.assertEqual(frame.RemoteFlag, 0)

    def test_default_cli_targets_current_bench(self):
        args = bench.build_parser().parse_args([])
        self.assertEqual(args.device, 0)
        self.assertEqual(args.channel, 1)
        self.assertEqual(args.bitrate, 500000)
        self.assertEqual(args.timeout, 60.0)
        self.assertFalse(args.confirm_isolated_bench)

    def test_bench_result_requires_both_directions(self):
        self.assertFalse(
            bench.BenchResult(True, False, 0.1).passed
        )
        self.assertFalse(
            bench.BenchResult(False, True, 0.1).passed
        )
        self.assertTrue(
            bench.BenchResult(True, True, 0.1).passed
        )


if __name__ == "__main__":
    unittest.main()
