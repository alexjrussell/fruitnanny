#!/usr/bin/python

import sys
import alsaaudio
import subprocess

level = 0

# Get the card number for the microphone - bit of a hack for now
output = subprocess.check_output("arecord -l | grep -e \"^card [0-9]:\"", shell=True)
card = int(output[5:6])

mic_mixer = alsaaudio.Mixer(control='Mic', cardindex=card)

# Set the level
if len(sys.argv) == 2:
    new_level = int(sys.argv[1])
    mic_mixer.setvolume(new_level, 0)

level = mic_mixer.getvolume()[0]
print(str(level))
