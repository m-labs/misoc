from migen import *

char_width = 8
char_layout = [("data", char_width), ("k", char_width // 8)]

word_width = 32
word_layout = [("data", word_width), ("k", word_width // 8)]

word_layout_dchar = [
    ("data", word_width),
    ("k", word_width // 8),
    ("dchar", char_width),
    ("dchar_k", char_width // 8),
]


def _K(x, y):
    return (y << 5) | x


KCode = {
    "pak_start": C(_K(27, 7), char_width),
    "io_ack": C(_K(28, 6), char_width),
    "trig_indic_28_2": C(_K(28, 2), char_width),
    "stream_marker": C(_K(28, 3), char_width),
    "trig_indic_28_4": C(_K(28, 4), char_width),
    "pak_end": C(_K(29, 7), char_width),
    "idle_comma": C(_K(28, 5), char_width),
    "idle_alignment": C(_K(28, 1), char_width),
}


def switch_endianness(s):
    assert len(s) % 8 == 0
    char = [s[i * 8 : (i + 1) * 8] for i in range(len(s) // 8)]
    return Cat(char[::-1])
