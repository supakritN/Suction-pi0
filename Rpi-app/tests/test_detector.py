"""Detector + serial parsing tests (no Tk, no hardware).

    python -m unittest discover -s tests -v
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from app.detector import ThroatDetector, Injection          # noqa: E402
from app.serial_node import SensorNode                      # noqa: E402
import fake_esp                                             # noqa: E402

THR = {4: 214, 5: 40, 6: 40, 7: 40, 15: 40}
PERIOD = sum(d for d, _ in fake_esp.SCENARIO)


def _smooth_stream(seconds, noise, spikes, seed=1, ui_ms=50, hz=100):
    """Run fake_esp frames at 100 Hz through the real SensorNode parser +
    smoother; yield (t, smoothed_pin_values) at the UI poll rate."""
    rng = random.Random(seed)
    thr = {p: THR.get(p, 120) for p in fake_esp.PIN_ORDER}
    node = SensorNode(sim=False)
    node._connected = True
    t, step, next_ui = 0.0, 1.0 / hz, 0.0
    while t < seconds:
        node._handle_line(fake_esp.frame(t, thr, noise, spikes, rng))
        node._last_rx = float("inf")          # keep "fresh" without wall clock
        if t >= next_ui:
            next_ui += ui_ms / 1000.0
            with node._lock:
                yield t, {p: int(round(v)) for p, v in node._pin_smooth.items()}
        t += step


def _legacy_level(pv, base):
    """The old process.py logic: one sample vs threshold, no hysteresis."""
    trig = {p: abs(pv[p] - base[p]) > THR[p] for p in THR}
    return 3 if trig[7] or trig[15] else 2 if trig[5] or trig[6] else 1 if trig[4] else 0


class DetectorTest(unittest.TestCase):
    def run_detector(self, seconds, noise, spikes, seed=1, hz=100):
        det = ThroatDetector(lambda p: THR.get(p, 120))
        levels, injections = [], []
        for t, pv in _smooth_stream(seconds, noise, spikes, seed, hz=hz):
            s = det.feed(pv, t)
            if s.ready:
                levels.append(s.level)
            injections += [e for e in s.events if isinstance(e, Injection)]
        return det, levels, injections

    def test_counts_injections_under_noise(self):
        # 3 full scenario loops → 2 insertions per loop
        det, _, inj = self.run_detector(PERIOD * 3, noise=0.35, spikes=0.01)
        self.assertEqual(det.injections, 6, [round(i.duration_s, 2) for i in inj])
        self.assertEqual(det.max_level, 3)
        # first insertion is cap→9→11→9→cap = 1.0+1.5+1.2+0.8+0.6 = 5.1 s
        self.assertAlmostEqual(inj[0].duration_s, 5.1, delta=0.3)
        self.assertEqual(inj[0].max_level, 3)
        self.assertEqual(inj[1].max_level, 2)

    def test_counts_injections_at_50hz_heavy_spikes(self):
        """Real firmware rate (~50 lines/s) with 3% spikes, several seeds."""
        for seed in range(5):
            det, levels, _ = self.run_detector(PERIOD * 3, noise=0.35, spikes=0.03,
                                               seed=seed, hz=50)
            changes = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
            self.assertEqual(det.injections, 6, f"seed {seed}")
            self.assertLessEqual(changes, 9 * 3 + 2, f"seed {seed}: {changes} changes")

    def test_no_flicker(self):
        _, levels, _ = self.run_detector(PERIOD * 3, noise=0.35, spikes=0.01)
        changes = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
        # ideal per loop: 0→1→2→3→2→1→0 (6) + shallow 0→2→1→0 (3; "Entry" holds
        # for the 0.4 s tube-out delay) = 9
        self.assertLessEqual(changes, 9 * 3 + 2, f"{changes} level changes")

    def test_legacy_logic_flickers(self):
        """Documents the bug: the old raw-sample logic toggles far more."""
        rng = random.Random(1)
        thr = {p: THR.get(p, 120) for p in fake_esp.PIN_ORDER}
        node = SensorNode(sim=False)
        base = None
        levels = []
        t = 0.0
        while t < PERIOD * 3:
            node._handle_line(fake_esp.frame(t, thr, 0.35, 0.01, rng))
            if round(t * 100) % 8 == 0:                # old 80 ms poll, raw values
                pv = dict(node._pin_value)
                base = base or pv
                levels.append(_legacy_level(pv, base))
            t += 0.01
        legacy_changes = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
        _, new_levels, _ = self.run_detector(PERIOD * 3, noise=0.35, spikes=0.01)
        new_changes = sum(1 for a, b in zip(new_levels, new_levels[1:]) if a != b)
        print(f"\n  level changes over {PERIOD*3:.0f}s — legacy: {legacy_changes}, new: {new_changes}")
        self.assertGreater(legacy_changes, new_changes * 2)

    def test_idle_noise_no_false_injection(self):
        det = ThroatDetector(lambda p: THR.get(p, 120))
        rng = random.Random(3)
        for i in range(2000):                      # 100 s idle, heavy noise + spikes
            pv = {p: 2000 + int(rng.gauss(0, THR[p] * 0.4)) for p in THR}
            if rng.random() < 0.02:
                pv[rng.choice(list(THR))] += 500   # single-sample spike
            det.feed(pv, i * 0.05)
        self.assertEqual(det.injections, 0)

    def test_tube_in_at_start_recovers_from_calibration(self):
        cal = {p: (2000, 2000 - int(THR[p] * 2.2)) for p in THR}
        det = ThroatDetector(lambda p: THR[p], cal)
        t = 0.0
        tube_in = {p: v[1] for p, v in cal.items()}
        tube_out = {p: v[0] for p, v in cal.items()}
        for pv, secs in ((tube_in, 2.0), (tube_out, 2.0), (tube_in, 1.5), (tube_out, 1.5)):
            end = t + secs
            while t < end:
                det.feed(pv, t)
                t += 0.05
        self.assertEqual(det.recovered, set(THR))
        self.assertEqual(det.injections, 2)
        self.assertEqual(det.max_level, 3)

    def test_without_calibration_tube_in_start_is_stuck(self):
        """Documents why calibration levels are stored: no reference → no recovery."""
        det = ThroatDetector(lambda p: THR[p])
        for i in range(40):
            det.feed({p: 1500 for p in THR}, i * 0.05)
        self.assertEqual(det.recovered, set())

    def _run(self, det, seq):
        t = getattr(det, "_test_t", 0.0)      # clock continues across calls
        for pv, secs in seq:
            end = t + secs
            while t < end:
                st = det.feed(pv, t)
                t += 0.05
        det._test_t = t
        return st

    def test_entry_releases_after_overshoot(self):
        """Tube out, but the IR reading overshoots past baseline the other way."""
        det = ThroatDetector(lambda p: THR[p])
        idle = {p: 2000 for p in THR}
        cap_in = {**idle, 4: 2000 - 480}
        overshoot = {**idle, 4: 2000 + 300}       # |Δ| > thr, opposite direction
        st = self._run(det, [(idle, 1), (cap_in, 2), (overshoot, 1.5)])
        self.assertFalse(st.cap, "Entry stuck after overshoot")
        self.assertEqual(det.injections, 1)

    def test_entry_releases_when_settling_off_baseline(self):
        """Tube out, reading settles 70% of thr away from the old baseline."""
        det = ThroatDetector(lambda p: THR[p])
        idle = {p: 2000 for p in THR}
        cap_in = {**idle, 4: 2000 - 480}
        settle = {**idle, 4: 2000 - int(THR[4] * 0.7)}
        st = self._run(det, [(idle, 1), (cap_in, 2), (settle, 1.5)])
        self.assertFalse(st.cap, "Entry stuck when reading settles near threshold")

    def test_calibrated_direction_ignores_wrong_way(self):
        cal = {p: (2000, 2000 - int(THR[p] * 2.2)) for p in THR}
        det = ThroatDetector(lambda p: THR[p], cal)
        idle = {p: 2000 for p in THR}
        wrong = {**idle, 4: 2000 + 500}            # brighter, not a tube
        st = self._run(det, [(idle, 1), (wrong, 2)])
        self.assertFalse(st.cap)
        self.assertEqual(det.injections, 0)

    def test_weak_cap_with_pi_calibration(self):
        """Real Pi calibration 03:52: Cap 2621→2664 (Δ43) with thr floor 40."""
        thr = {4: 40, 5: 40, 6: 40, 7: 84, 15: 92}
        cal = {4: (2621, 2664), 5: (148, 146), 6: (144, 141), 7: (983, 815), 15: (955, 770)}
        det = ThroatDetector(lambda p: thr[p], cal)
        on, off = det.thr_pair(4)
        self.assertAlmostEqual(on, 43 * 0.6)                   # not 40 of 43
        self.assertEqual(det.thr_pair(5), (40, 32))            # Δ2: calibration unusable
        out = {4: 2621, 5: 148, 6: 144, 7: 983, 15: 955}
        cap_in = {**out, 4: 2664}
        st = self._run(det, [(out, 1), (cap_in, 2), (out, 1.5)])
        self.assertFalse(st.cap)
        self.assertEqual(det.injections, 1)

    def test_stuck_entry_heals(self):
        """Tube out but Cap settles above its release point → auto-heal."""
        det = ThroatDetector(lambda p: THR[p])
        idle = {p: 2000 for p in THR}
        cap_in = {**idle, 4: 2000 - 480}
        stuck = {**idle, 4: 2000 - 300}          # > release (171) from zero, flat
        st = self._run(det, [(idle, 1), (cap_in, 2), (stuck, 2)])
        self.assertTrue(st.cap)                  # still on before STUCK_S
        st = self._run(det, [(stuck, 6)])
        self.assertFalse(st.cap, "Entry never healed")
        self.assertEqual(det.injections, 1)
        self.assertAlmostEqual(det.last_time_s, 2.0, delta=0.3)   # ends at removal
        st = self._run(det, [(cap_in, 2)])                       # next insertion works
        self.assertTrue(st.cap, "muted pin didn't re-trigger on re-insertion")
        st = self._run(det, [(stuck, 7)])
        self.assertFalse(st.cap)
        self.assertEqual(det.injections, 2)
        self.assertAlmostEqual(det.last_time_s, 2.0, delta=0.3)
        st = self._run(det, [(idle, 1)])                          # sensor recovers
        self.assertFalse(st.cap)
        self.assertEqual(det.injections, 2)

    def test_long_hold_at_depth_is_not_healed(self):
        det = ThroatDetector(lambda p: THR[p])
        idle = {p: 2000 for p in THR}
        deep = {p: 2000 - int(THR[p] * 2.2) for p in THR}
        st = self._run(det, [(idle, 1), (deep, 12)])
        self.assertTrue(st.cap)
        self.assertEqual(st.level, 3)

    def test_drifted_sensor_does_not_fake_tube_in(self):
        """Pi 04:10: Cap calibrated 2621/2664 but idle drifted to ~3000."""
        thr = {4: 40, 5: 40, 6: 40, 7: 84, 15: 92}
        cal = {4: (2621, 2664), 5: (148, 146), 6: (144, 141), 7: (983, 815), 15: (955, 770)}
        det = ThroatDetector(lambda p: thr[p], cal)
        idle = {4: 3000, 5: 220, 6: 210, 7: 957, 15: 968}
        st = self._run(det, [(idle, 2)])
        self.assertEqual(det.recovered, set())
        self.assertFalse(st.cap)
        self.assertEqual(st.level, 0)

    def test_rezero(self):
        det = ThroatDetector(lambda p: THR.get(p, 120))
        for i in range(10):
            det.feed({p: 2000 for p in THR}, i * 0.05)
        det.reset_baseline()
        s = det.feed({p: 1500 for p in THR}, 1.0)
        self.assertFalse(s.ready)


class SelfCheckTest(unittest.TestCase):
    def _node(self, seq):
        from unittest import mock
        n = SensorNode(sim=False)
        for v in seq:
            n._handle_line(",".join(f"pin{p}:{v}" for p in (4, 5, 6, 7, 15)))
        n._last_rx = float("inf")
        # independent of whatever pins_config.json enables on this machine
        with mock.patch("app.serial_node.load_enabled_pins", return_value={4, 5, 6, 7, 15}):
            return {s.id: s for s in n.self_check()}

    def test_single_spike_is_not_floating(self):
        seq = [2000] * 15
        seq[7] = 2600
        self.assertTrue(self._node(seq)["throat_cap"].ok)

    def test_floating_pin_detected(self):
        rng = random.Random(0)
        st = self._node([rng.randint(0, 4095) for _ in range(15)])["throat_cap"]
        self.assertFalse(st.ok)
        self.assertIn("floating", st.detail)


class SerialParseTest(unittest.TestCase):
    def test_pin_format_and_partial_frame(self):
        n = SensorNode(sim=False)
        n._handle_line("n7:123,pin15:2100")            # partial first line: only pin15 usable
        n._handle_line("pin4:2000,pin5:1800,pin6:2200,pin7:1900,pin15:2100")
        n._handle_line("garbage,,")
        n._handle_line("")
        self.assertEqual(n._pin_value[4], 2000)
        self.assertEqual(n._pin_value[15], 2100)
        self.assertNotIn(7, {k for k in n._pin_value if n._pin_value[k] == 123})

    def test_smoothing_rejects_spike(self):
        n = SensorNode(sim=False)
        for _ in range(20):
            n._handle_line("pin4:2000")
        n._handle_line("pin4:2600")                    # one-sample spike
        self.assertEqual(round(n._pin_smooth[4]), 2000)
        for _ in range(3):
            n._handle_line("pin4:1500")                # real step still comes through
        self.assertLess(n._pin_smooth[4], 1900)


if __name__ == "__main__":
    unittest.main()


class _ReplayBase(unittest.TestCase):
    """Loads the factory calibration + position recordings for replay tests."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    PIN_ORDER = [4, 5, 6, 7, 15, 17, 1, 2, 18, 8, 3, 9]

    def setUp(self):
        import csv, json
        from app.detector import Roles
        with open(os.path.join(self.ROOT, "calibration_default.json")) as fh:
            cfg = json.load(fh)
        r = cfg["roles"]
        self.roles = Roles(tuple(r["entry"]), tuple(r["d9"]), tuple(r["d11"]))
        self.thr = {int(k): v for k, v in cfg["trigger_delta_overrides"].items()}
        self.cal = {int(k): tuple(v) for k, v in cfg["calibrated_levels"].items()}
        self.pos = {}
        for name in ("pos1_out", "pos2_entry", "pos3_9cm", "pos4_11cm"):
            with open(os.path.join(self.ROOT, "calib_samples", f"{name}.csv")) as fh:
                self.pos[name] = list(csv.DictReader(fh))

    def replay(self, sequence, det, prime_with=None):
        node = SensorNode(sim=False)
        t, levels, injections, ui_next = 0.0, [], [], 0.0
        if prime_with:
            samples = []
            for row in self.pos[prime_with]:
                node._handle_line(",".join(f"pin{p}:{row[f'pin{p}']}" for p in self.PIN_ORDER))
                with node._lock:
                    samples.append({p: int(round(v)) for p, v in node._pin_smooth.items()})
            det.prime(samples)
        for name in sequence:
            for row in self.pos[name]:
                node._handle_line(",".join(f"pin{p}:{row[f'pin{p}']}" for p in self.PIN_ORDER))
                t += 0.02
                if t >= ui_next:                       # UI polls at 50 ms
                    ui_next += 0.05
                    with node._lock:
                        pv = {p: int(round(v)) for p, v in node._pin_smooth.items()}
                    st = det.feed(pv, t)
                    if st.ready:
                        levels.append((name, st.level))
                    injections += [e for e in st.events if isinstance(e, Injection)]
        return levels, injections

    @staticmethod
    def _segment_ends(levels):
        """Level held at the end of each consecutive position segment."""
        ends, last = [], None
        for name, lvl in levels:
            if name != last:
                ends.append([name, lvl])
            else:
                ends[-1][1] = lvl
            last = name
        return ends



class FactoryCalibrationReplayTest(_ReplayBase):
    """Replays the real position recordings (calib_samples/pos*.csv, 2026-10-03)
    through SensorNode parsing + smoothing and the detector with the factory
    calibration (calibration_default.json)."""

    def test_out_entry_9_11_out(self):
        det = ThroatDetector(lambda p: self.thr.get(p, 120), self.cal, self.roles)
        seq = ["pos1_out", "pos2_entry", "pos3_9cm", "pos4_11cm", "pos1_out"]
        levels, inj = self.replay(seq, det)
        ends = self._segment_ends(levels)
        self.assertEqual([lvl for _, lvl in ends], [0, 1, 2, 3, 0], ends)
        self.assertEqual(det.injections, 1)
        self.assertEqual(det.max_level, 3)
        self.assertAlmostEqual(inj[0].duration_s, 24.0, delta=0.5)   # 3 × 8 s inside

    def test_no_false_trigger_while_out(self):
        det = ThroatDetector(lambda p: self.thr.get(p, 120), self.cal, self.roles)
        levels, _ = self.replay(["pos1_out"], det)
        self.assertTrue(levels)
        self.assertTrue(all(lvl == 0 for _, lvl in levels))

    def test_tube_at_entry_during_countdown_recovers(self):
        det = ThroatDetector(lambda p: self.thr.get(p, 120), self.cal, self.roles)
        levels, _ = self.replay(["pos2_entry", "pos3_9cm", "pos1_out"], det, prime_with="pos2_entry")
        self.assertIn(17, det.recovered)
        ends = self._segment_ends(levels)
        self.assertEqual([lvl for _, lvl in ends], [1, 2, 0], ends)


class RealInsertionCyclesTest(_ReplayBase):
    """calib_samples/cycles_9cm_2.csv: 3 real insertions (9 cm holds, one to
    11 cm). While the tube is held the entry pair often reads only 20–300 ADC
    below out — the old entry-only logic split these into 10 injections."""

    def test_three_insertions_not_split(self):
        import csv
        with open(os.path.join(self.ROOT, "calib_samples", "cycles_9cm_2.csv")) as fh:
            rows = list(csv.DictReader(fh))
        det = ThroatDetector(lambda p: self.thr.get(p, 120), self.cal, self.roles)
        line = lambda r: ",".join(f"pin{p}:{r[f'pin{p}']}" for p in self.PIN_ORDER)
        node, prime = SensorNode(sim=False), []
        for r in rows:                              # countdown zero: tube-out part
            if 32 <= float(r["t"]) < 34:
                node._handle_line(line(r))
                prime.append({p: int(round(v)) for p, v in node._pin_smooth.items()})
        det.prime(prime)
        node, nxt, first9 = SensorNode(sim=False), 0.0, []
        for r in rows:
            t = float(r["t"])
            node._handle_line(line(r))
            if t >= nxt:
                nxt += 0.05
                st = det.feed({p: int(round(v)) for p, v in node._pin_smooth.items()}, t)
                if st.level >= 2 and (not first9 or t - first9[-1] > 3):
                    first9.append(t)
        self.assertEqual(det.injections, 3)
        self.assertEqual(det.max_level, 3)
        # 9 cm shown promptly each time GPIO 6 changed (≈ 0.0 s, 11.2 s, 20.6 s)
        for expected, got in zip((0.03, 11.17, 20.57), first9):
            self.assertLess(got - expected, 0.3)
