"""Melee sound bank (.ssm) -> WAV files: the samples are GameCube DSP-ADPCM.

    uv run python tools/melee_ssm.py melee/audio/us/captain.ssm out/melee/voice

SSM (big endian): u32 header size (after these 16 bytes), u32 data size, u32 sound count, u32 first sound id; per
sound: u32 channels, u32 rate, then per channel 0x40 bytes: u16 loop flag, u16 format, u32 loop start, u32 end,
u32 current address (all in nibbles from the data's start), 16 s16 coefficients, u16 gain, u16 predictor/scale, s16
history 1 and 2, the loop's three, u16 pad. The data follows the header; a frame is a header byte (coefficient pair,
scale) and 14 four-bit samples.
"""
import struct
import sys
import wave
from pathlib import Path


def decode(data, start, end, coef, h1=0, h2=0):
    """Samples from nibble address `start` to `end` (inclusive)"""
    out = []
    n = start
    while n <= end:
        if n % 16 < 2:   # (the frame's header byte)
            n += 2 - n % 16
            continue
        hb = data[n // 16 * 8] if n // 16 * 8 < len(data) else 0
        scale, ci = 1 << (hb & 15), hb >> 4
        b = data[n // 2] if n // 2 < len(data) else 0
        nib = (b >> 4) if n % 2 == 0 else (b & 15)
        if nib >= 8:
            nib -= 16
        c1, c2 = coef[ci * 2], coef[ci * 2 + 1]
        s = ((nib * scale) << 11) + c1 * h1 + c2 * h2 + 1024 >> 11
        s = max(-32768, min(32767, s))
        out.append(s)
        h2, h1 = h1, s
        n += 1
    return out


def sounds(ssm):
    hsize, _, count, first = struct.unpack_from(">IIII", ssm, 0)
    data = ssm[0x10 + hsize:]
    o = 0x10
    for k in range(count):
        ch, rate = struct.unpack_from(">II", ssm, o)
        o += 8
        chans = []
        for _ in range(ch):
            _, _, _, ea, ca = struct.unpack_from(">HHIII", ssm, o)
            coef = struct.unpack_from(">16h", ssm, o + 16)
            _, _, h1, h2 = struct.unpack_from(">HHhh", ssm, o + 48)
            chans.append(decode(data, ca, ea, coef, h1, h2))
            o += 0x40
        yield first + k, rate, chans


def write_wav(path, rate, chans):
    n = min(len(c) for c in chans)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(chans))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<%dh" % len(chans), *[c[i] for c in chans]) for i in range(n)))


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for sid, rate, chans in sounds(src.read_bytes()):
        write_wav(out / f"{src.stem}_{sid:04d}.wav", rate, chans)
        print(f"{sid:5d}  {rate} Hz  {len(chans)} ch  {len(chans[0]) / rate:.2f} s")


if __name__ == "__main__":
    main()
