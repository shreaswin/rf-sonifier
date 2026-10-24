#!/usr/bin/env python3
"""
rf_bridge.py - sweep the FM broadcast band with an RTL-SDR and stream
station levels to SuperCollider over OSC.

Usage:
  python rf_bridge.py --fake                 # synthetic band, no hardware needed
  python rf_bridge.py                        # live sweep with the RTL-SDR
  python rf_bridge.py --gain 20 --threshold 8

OSC messages sent to SuperCollider (127.0.0.1:57120 by default):
  /rf/stations  n, f1, level1, delta1, f2, level2, delta2, ...
                f = channel in MHz, level = 0..1 (SNR over the noise floor),
                delta = change in level since the previous sweep
  /rf/activity  a   overall band activity 0..1 (drives the background drone)
"""
import argparse
import sys
import time

import numpy as np
from pythonosc.udp_client import SimpleUDPClient

FM_LOW, FM_HIGH = 88.1, 107.9                                   # US FM channel centers (MHz)
CHANNELS = np.round(np.arange(FM_LOW, FM_HIGH + 0.001, 0.2), 1)  # 100 channels
CHANNEL_HALF_BW = 0.075                                          # measure +/-75 kHz around each center
MAX_VOICES = 16
SNR_FULL_SCALE = 60.0                                            # dB above floor that maps to level 1.0


class FakeBand:
    """Synthetic FM band: a handful of stations that drift and occasionally fade."""

    def __init__(self, seed=None, n_stations=14):
        self.rng = np.random.default_rng(seed)
        self.stations = np.sort(self.rng.choice(CHANNELS, n_stations, replace=False))
        self.base = self.rng.uniform(-60, -25, n_stations)  # dB
        self.state = self.base.copy()
        self.floor = -85.0

    def sweep(self):
        self.state += self.rng.normal(0, 1.5, len(self.state))  # random walk
        self.state += 0.1 * (self.base - self.state)            # pull back toward base level
        fades = self.rng.random(len(self.state)) < 0.03          # occasional deep fade
        self.state[fades] -= 25
        power = self.floor + self.rng.normal(0, 1.0, len(CHANNELS))
        for f, p in zip(self.stations, self.state):
            idx = int(round((f - FM_LOW) / 0.2))
            power[idx] = max(power[idx], p)
        time.sleep(0.5)  # roughly the pace of a real sweep
        return power

    def close(self):
        pass


class LiveBand:
    """Sweeps 88-108 MHz in 2 MHz hops and measures power in each FM channel."""

    def __init__(self, gain, ppm=0, sample_rate=2.4e6, nsamples=256 * 1024):
        try:
            from rtlsdr import RtlSdr
        except ImportError:
            sys.exit("pyrtlsdr missing: pip install pyrtlsdr  (and: brew install librtlsdr)")
        from scipy.signal import welch

        self.welch = welch
        self.sdr = RtlSdr()
        self.sdr.sample_rate = sample_rate
        self.sdr.gain = gain
        if ppm:
            self.sdr.freq_correction = ppm
        self.fs = sample_rate
        self.n = nsamples
        self.usable = 2.0e6                       # keep the flat middle of the 2.4 MHz passband
        self.centers = np.arange(89.0, 108.0, 2.0)  # 89, 91, ... 107 MHz -> covers 88-108

    def sweep(self):
        freqs_all, psd_all = [], []
        for c in self.centers:
            self.sdr.center_freq = c * 1e6
            self.sdr.read_samples(4096)            # flush samples captured while retuning
            x = self.sdr.read_samples(self.n)
            f, p = self.welch(x, fs=self.fs, nperseg=1024, return_onesided=False)
            f, p = np.fft.fftshift(f), np.fft.fftshift(p)
            keep = np.abs(f) <= self.usable / 2
            freqs_all.append(c + f[keep] / 1e6)
            psd_all.append(p[keep])
        freqs = np.concatenate(freqs_all)
        psd = np.concatenate(psd_all)

        power = np.empty(len(CHANNELS))
        for i, ch in enumerate(CHANNELS):
            m = np.abs(freqs - ch) <= CHANNEL_HALF_BW
            power[i] = 10 * np.log10(np.mean(psd[m]) + 1e-20)
        return power

    def close(self):
        self.sdr.close()


def analyze(power, threshold):
    """Return (snr per channel, indices of detected stations sorted by frequency)."""
    floor = float(np.median(power))
    snr = power - floor
    # A station must clear the threshold AND be a local peak, so HD Radio
    # sidebands and adjacent-channel splatter don't count as separate stations.
    padded = np.pad(snr, 1, constant_values=-np.inf)
    is_peak = (snr >= padded[:-2]) & (snr >= padded[2:])
    idx = np.where((snr > threshold) & is_peak)[0]
    idx = idx[np.argsort(snr[idx])[::-1][:MAX_VOICES]]  # strongest first, capped
    return snr, np.sort(idx)


def main():
    ap = argparse.ArgumentParser(description="FM band -> OSC bridge for the RF sonifier")
    ap.add_argument("--fake", action="store_true", help="use a synthetic band (no hardware)")
    ap.add_argument("--gain", default="20", help="tuner gain in dB, or 'auto' (default 20)")
    ap.add_argument("--ppm", type=int, default=0, help="frequency correction in ppm")
    ap.add_argument("--threshold", type=float, default=10.0, help="dB above floor to count as a station")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=57120, help="SuperCollider language port")
    ap.add_argument("--seed", type=int, default=None, help="random seed for --fake")
    args = ap.parse_args()

    gain = args.gain if args.gain == "auto" else float(args.gain)
    band = FakeBand(args.seed) if args.fake else LiveBand(gain, args.ppm)
    client = SimpleUDPClient(args.host, args.port)
    prev = {}

    print(f"Streaming to {args.host}:{args.port} ({'fake' if args.fake else 'live'} mode). Ctrl+C to stop.")
    try:
        while True:
            power = band.sweep()
            snr, idx = analyze(power, args.threshold)

            payload, current = [len(idx)], {}
            for i in idx:
                f = float(CHANNELS[i])
                level = float(np.clip(snr[i] / SNR_FULL_SCALE, 0, 1))
                delta = level - prev.get(f, level)
                payload += [f, level, delta]
                current[f] = level
            prev = current

            activity = float(np.mean(np.clip(snr / SNR_FULL_SCALE, 0, 1)))
            client.send_message("/rf/stations", payload)
            client.send_message("/rf/activity", activity)

            summary = "  ".join(f"{f:.1f}:{l:.2f}" for f, l in current.items())
            print(f"[{len(idx):2d} stations] {summary}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        band.close()


if __name__ == "__main__":
    main()
