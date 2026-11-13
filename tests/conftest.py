import wave
import pytest


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    with wave.open(str(folder / "audio.wav"), "wb") as audio:
        audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 48000 * 4)
    chart = folder / "song.txt"
    chart.write_text(
        "#TITLE:Canción de prueba\n#ARTIST:Fixture\n#LANGUAGE:Spanish\n#BPM:120\n#GAP:0\n#MP3:audio.wav\n: 0 8 21 sí\n- 8\n: 8 8 21 no\nE\n",
        encoding="utf-8",
        newline="\n",
    )
    return chart
