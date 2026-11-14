#!/usr/bin/env python3
"""Generate Karaoke's original HUD geometry; standard library only, no external artwork."""
import math
import hashlib
import json
from pathlib import Path
import struct
import zlib

OUT = Path(__file__).resolve().parents[1] / 'assets/theme/Karaoke'

def png(name, width, height, pixel):
    data = bytearray()
    for y in range(height):
        data.append(0)
        for x in range(width):
            data.extend(pixel(x + .5, y + .5))
    def chunk(kind, value):
        return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value) & 0xffffffff)
    (OUT / name).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(data, 9)) + chunk(b'IEND', b''))

def capsule(part, filled):
    def color(x, y):
        if part == 'left': distance = math.hypot(x - 64, y - 64)
        elif part == 'right': distance = math.hypot(x, y - 64)
        else: distance = abs(y - 64)
        edge = max(0, min(1, 64 - distance))
        if filled:
            rgb = (38, 181, 244)
            alpha = 255 * edge
        else:
            rgb = (35, 150, 224)
            alpha = (230 if distance > 51 else 58) * edge
        return (*rgb, round(alpha))
    return color

OUT.mkdir(parents=True, exist_ok=True)
for part in ('left', 'mid', 'right'):
    for filled in (False, True):
        png(('sung-' if filled else 'guide-') + part + '.png', 64 if part != 'mid' else 4, 128, capsule(part, filled))
png('clear.png', 2, 2, lambda x, y: (255, 255, 255, 0))
png('lyrics.png', 4, 128, lambda x, y: (248, 249, 251, 248) if y < 65 else (228, 233, 238, 248))
png('score.png', 8, 8, lambda x, y: (10, 18, 30, 172))
png('white.png', 2, 2, lambda x, y: (255, 255, 255, 255))
# A restrained original pause veil with two bars; no text or console icon assets.
def pause(x, y):
    if (376 <= x <= 392 or 408 <= x <= 424) and 272 <= y <= 328:
        return (255, 255, 255, 245)
    return (8, 14, 24, 135)
png('pause.png', 800, 600, pause)
manifest = {
    'generator': 'scripts/create_theme_assets.py',
    'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'license': 'GPL-3.0-only',
    'provenance': 'Original geometry authored for Karaoke: circle/rectangle capsule segments, two-tone lyric band, flat translucent score backing and pause bars. No third-party image input.',
    'assets': [{'filename': 'Karaoke/' + file.name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'bytes': file.stat().st_size}
               for file in sorted(OUT.glob('*.png'))],
}
(OUT.parent / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(OUT)
