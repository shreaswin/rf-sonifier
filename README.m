RF Sonifier
Makes the FM broadcast band audible. An RTL-SDR sweeps 88–108 MHz, a Python bridge finds the stations, and SuperCollider turns each one into a voice.
Radio property	Sound
Position on the dial	Left/right position and pitch (minor pentatonic)
Signal strength	Loudness and brightness
Change in strength	Tremolo
Overall band activity	Background drone
Status: working with simulated band data (--fake). Live RTL-SDR input and 3D binaural (Ambisonics) spatialization are next.
Setup (macOS)
cd rf-sonifier
python3 -m venv venv
source venv/bin/activate
pip install numpy scipy python-osc
pip install pyrtlsdr        # only needed for live mode
Also install SuperCollider.
Run
Open rf_sonifier.scd in SuperCollider, click inside block 1, press Cmd+Enter. Wait for "RF sonifier ready".
In Terminal:
Simulated band: python3 rf_bridge.py --fake
With an RTL-SDR: python3 rf_bridge.py
Listen on headphones. Stop with Ctrl+C in Terminal and Cmd+. in SuperCollider.
Tuning tips
Too many stations? Raise --threshold (e.g. 15).
Near a transmitter site: lower --gain (e.g. 5–10) or add an inline attenuator to avoid overload ghosts.
Change the music by editing ~pitchFor and ~panFor in the .scd file.
