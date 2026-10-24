// rf_sonifier.scd - RF spectrum sonifier (stereo version)
//
// Each FM station becomes a voice:
//   frequency on the dial -> left/right position and pitch (minor pentatonic)
//   signal strength       -> loudness and brightness
//   change in strength    -> tremolo (fading stations shimmer)
// A background hiss follows overall band activity.
//
// HOW TO RUN
// 1. Click anywhere inside block 1 and press Cmd+Enter. Wait for "RF sonifier ready".
// 2. In Terminal: python3 rf_bridge.py --fake
// 3. Listen on headphones. To stop: Ctrl+C in Terminal, then Cmd+. here.

// ---------- 1. SETUP ----------
(
s.waitForBoot {
    SynthDef(\rfVoice, { |out = 0, freq = 220, amp = 0, bright = 0.5, pan = 0, wobble = 0, gate = 1|
        var env, a, b, tone, hiss, trem, sig;
        env  = EnvGen.kr(Env.asr(2, 1, 3), gate, doneAction: 2);
        a    = amp.lag(1.5);
        b    = bright.lag(1.5);
        tone = SinOsc.ar(freq * [1, 1.003, 0.997], 0, [0.5, 0.25, 0.25]).sum;
        tone = tone + (LFTri.ar(freq * 2, 0, 0.3) * b);
        hiss = BPF.ar(PinkNoise.ar, freq * 4, 0.05) * (1 - b) * 2;   // weak stations sound noisier
        trem = 1 - (wobble.lag(0.5).clip(0, 1) * 0.6 * (SinOsc.kr(6) * 0.5 + 0.5));
        sig  = LPF.ar(tone + hiss, b.linexp(0, 1, 800, 8000)) * a * trem * env * 0.2;
        Out.ar(out, Pan2.ar(sig, pan.lag(1)));
    }).add;

    SynthDef(\rfDrone, { |out = 0, activity = 0|
        var act = activity.lag(3);
        var n1 = BPF.ar(PinkNoise.ar, LFNoise1.kr(0.07).exprange(200, 1200), 0.2);
        var n2 = BPF.ar(PinkNoise.ar, LFNoise1.kr(0.05).exprange(200, 1200), 0.2);
        Out.ar(out, [n1, n2] * act.linlin(0, 0.3, 0.02, 0.15));
    }).add;

    s.sync;

    ~drone = Synth(\rfDrone);
    ~voices = Dictionary.new;

    // Mappings - tweak these to change the piece.
    ~pitchFor = { |mhz| Scale.minorPentatonic.degreeToFreq(mhz.linlin(88.1, 107.9, 0, 14).round, 110, 0) };
    ~panFor   = { |mhz| mhz.linlin(88.1, 107.9, -0.9, 0.9) };   // low stations left, high stations right

    OSCdef(\rfStations, { |msg|
        var n = msg[1].asInteger;
        var seen = Set.new;
        n.do { |i|
            var mhz   = msg[2 + (i * 3)];
            var level = msg[3 + (i * 3)];
            var delta = msg[4 + (i * 3)];
            var key   = (mhz * 10).round.asInteger;
            var params = [
                \freq, ~pitchFor.(mhz), \amp, level, \bright, level,
                \pan, ~panFor.(mhz), \wobble, delta.abs * 5
            ];
            seen.add(key);
            if (~voices[key].isNil) {
                ~voices[key] = Synth(\rfVoice, params);
            } {
                ~voices[key].set(*params);
            };
        };
        ~voices.keys.copy.do { |key|
            if (seen.includes(key).not) {
                ~voices[key].set(\gate, 0);   // station disappeared: fade it out
                ~voices.removeAt(key);
            };
        };
    }, '/rf/stations');

    OSCdef(\rfActivity, { |msg| ~drone.set(\activity, msg[1]) }, '/rf/activity');

    "RF sonifier ready - listening on port %. Start rf_bridge.py.".format(NetAddr.langPort).postln;
};
)

// ---------- 2. RECORD (for the demo video) ----------
s.record;          // starts recording to ~/Music/SuperCollider Recordings
s.stopRecording;

// ---------- 3. STOP EVERYTHING ----------
(
OSCdef(\rfStations).free;
OSCdef(\rfActivity).free;
~voices.do(_.free); ~voices.clear;
~drone.free;
)
