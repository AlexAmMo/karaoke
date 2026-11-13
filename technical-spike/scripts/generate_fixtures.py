#!/usr/bin/env python3
"""Original synthetic audio/maps, not commercial music. Safe to regenerate."""
from pathlib import Path
import math, struct, wave
root = Path(__file__).resolve().parents[1]
for name,language in [('A','English'),('B','Spanish'),('C','English')]:
    dest = root/'fixtures'/('initial' if name=='A' else 'staging')/name
    dest.mkdir(parents=True,exist_ok=True)
    with wave.open(str(dest/'tone.wav'),'wb') as f:
        f.setparams((1,2,48000,0,'NONE','not compressed'))
        f.writeframes(b''.join(struct.pack('<h',int(900*math.sin(2*math.pi*220*t/48000))) for t in range(48000*16)))
    notes=[]
    for line in range(6):
        for j in range(4):
            notes.append(f': {line*16+j*4} 3 21 '+('la ' if language=='English' else 'sí '))
        if line<5: notes.append(f'- {line*16+15}')
    (dest/'song.txt').write_text(f'#TITLE:Probe {name}\n#ARTIST:Karaoke technical spike\n#LANGUAGE:{language}\n#MP3:tone.wav\n#BPM:120\n#GAP:1000\n'+ '\n'.join(notes)+'\nE\n')
invalid=root/'fixtures'/'staging'/'invalid'
invalid.mkdir(parents=True,exist_ok=True)
(invalid/'song.txt').write_text('#TITLE:Broken\n#ARTIST:Probe\n#BPM:120\n#MP3:missing.wav\nE\n')
print(root/'fixtures')
