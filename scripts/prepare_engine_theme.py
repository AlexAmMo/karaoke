"""Apply the original Karaoke HUD to the pinned Deluxe resources, reproducibly."""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def prepare_theme(engine: Path):
    fonts = engine / 'game/fonts'
    shutil.copytree(ROOT / 'assets/fonts', fonts / 'InstrumentSans', dirs_exist_ok=True)
    layout = fonts / 'fonts.ini'
    text = layout.read_text(encoding='utf-8-sig')
    if '[Font_InstrumentSans]' not in text:
        family = ['[Font_InstrumentSans]', 'Name=Instrument Sans']
        for style, weight in [('Regular', 'Regular'), ('Bold', 'Bold'), ('Outline', 'Bold'), ('BoldHighRes', 'Bold')]:
            family.extend([f'{style}File=InstrumentSans/InstrumentSans-{weight}.ttf',
                           f'{style}MaxResolution=128',
                           f'{style}FallbackFile1=NotoSans/GoNotoKurrent-{weight}.ttf',
                           f'{style}FallbackFile2=NotoSans/GoNotoCurrent-{weight}.ttf'])
        family.extend(['OutlineOutline=0.035', ''])
        text = text.replace('[Font_NotoSans]', '\n'.join(family) + '\n[Font_NotoSans]', 1)
        layout.write_text(text, encoding='utf-8')
    themes = engine / 'game/themes'
    source = (themes / 'Modern.ini').read_text(encoding='utf-8-sig')
    replacements = {
        'Theme': {'Name': 'Karaoke', 'Creator': 'Karaoke contributors', 'DefaultSkin': 'Classic'},
        'SingLyricsBar': {'X': 0, 'Y': 484, 'W': 800, 'H': 94, 'Alpha': 1},
        'SingLyricsUpperBar': {'X': 38, 'Y': 492, 'W': 724, 'H': 34, 'IndicatorYOffset': 0},
        'SingLyricsLowerBar': {'X': 38, 'Y': 539, 'W': 724, 'H': 28},
        'SingTimeBar': {'X': 0, 'Y': 578, 'W': 800, 'H': 22},
        'SingTimeProgress': {'X': 90, 'Y': 589, 'W': 620, 'H': 2, 'Color': 'LightBlue'},
        'SingTimeLabelText': {'Text': 'Tiempo', 'Size': 14, 'Style': 0, 'Color': 'GrayDark', 'Y': 580},
        'SingTimeText': {'Size': 14, 'Style': 0, 'Color': 'GrayDark', 'Y': 580},
        'SingDefaultAvatarFrame': {'Alpha': 0},
        'SingDefaultAvatar': {'Alpha': 0},
        'SingDefaultPlayerText': {'X': 38, 'Y': 290, 'Style': 0, 'Size': 18},
        'SingDefaultScoreBG': {'X': 648, 'Y': 278, 'W': 130, 'H': 44, 'Type': 'Transparent', 'Color': 'White'},
        'SingDefaultPlayerTextScore': {'X': 658, 'Y': 282, 'Style': 0, 'Size': 32, 'Color': 'White'},
        'SingDefaultSingBar': {'X': 648, 'Y': 322, 'W': 130, 'H': 3},
        'SingP1Static2': {'Color': 'White'},
        'SingP1TwoPText': {'Y': 110},
        'SingP1TwoPStatic2': {'Y': 98, 'Color': 'White'},
        'SingP1TwoPTextScore': {'Y': 102},
        'SingP1TwoPSingBar': {'Y': 142},
        'SingP2RText': {'Y': 290},
        'SingP2RStatic2': {'Y': 278, 'Color': 'White'},
        'SingP2RTextScore': {'Y': 282},
        'SingP2RSingBar': {'Y': 322},
        'PausePopUpStatic': {'Type': 'Transparent', 'Color': 'White'},
    }
    for section, values in replacements.items():
        pattern = re.compile(r'(?m)^\[' + re.escape(section) + r'\]\s*\n(?:(?!^\[).)*', re.S)
        match = pattern.search(source)
        if not match:
            raise RuntimeError('Missing pinned theme section: ' + section)
        block = match[0].rstrip() + '\n'
        for key, value in values.items():
            key_pattern = re.compile(r'(?m)^' + re.escape(key) + r'\s*=.*$')
            line = f'{key} = {value}'
            if key_pattern.search(block):
                block = key_pattern.sub(line, block)
            else:
                block += line + '\n'
        source = source[:match.start()] + block + '\n' + source[match.end():]
    (themes / 'Karaoke.ini').write_text(source, encoding='utf-8')
    target = themes / 'Karaoke'
    shutil.copytree(ROOT / 'assets/theme/Karaoke', target, dirs_exist_ok=True)
    shutil.copy2(ROOT / 'assets/theme/manifest.json', target / 'manifest.json')
    shutil.copy2(ROOT / 'assets/theme/README.md', target / 'README.md')
    overrides = {
        'LyricBar': 'lyrics.png', 'LyricBarDuet': 'lyrics.png',
        'TimeBar1': 'white.png', 'TimeBar': 'white.png',
        'ScoreBG': 'score.png', 'Pause': 'pause.png',
        'LineBonusBack': 'clear.png', 'SingBarBack': 'clear.png',
        'SingBarBar': 'white.png', 'SingBarFront': 'clear.png',
        'LyricHelpBar': 'clear.png', 'Ball': 'clear.png',
        # Unused upstream mappings point to absent files in the pinned Modern skin.
        'MainSearch': 'clear.png', 'IconSongMenu': 'clear.png',
        'PopUpBG': 'score.png', 'JukeboxSong': 'clear.png', 'Hue': 'white.png',
    }
    for part, title in [('left', 'Left'), ('mid', 'Mid'), ('right', 'Right')]:
        for suffix in ('', 'Rap'):
            overrides['Gray' + title + suffix] = 'sung-' + part + '.png'
            overrides['NotePlain' + title + suffix] = 'guide-' + part + '.png'
            overrides['NoteBG' + title + suffix] = 'clear.png'
    skin = (themes / 'Modern/Blue.ini').read_text(encoding='utf-8-sig')
    output = []
    textures = False
    for line in skin.splitlines():
        if line.strip().startswith('['):
            textures = line.strip() == '[Textures]'
        if textures and re.match(r'^\w[^=]*=', line):
            key, filename = line.split('=', 1)
            name = key.strip()
            line = key + '= ' + overrides.get(name, '../Modern/' + filename.strip())
        elif line.startswith('Theme='):
            line = 'Theme=Karaoke'
        elif line.startswith('Name='):
            line = 'Name=Classic'
        output.append(line)
    (target / 'Classic.ini').write_text('\n'.join(output) + '\n', encoding='utf-8')


if __name__ == '__main__':
    prepare_theme(ROOT / 'build/engine')
