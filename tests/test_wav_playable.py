# -*- coding: utf-8 -*-
# Tests for the undecodable-WAV converter (cue_lib.audio.wav_playable).
# Fixtures are built by hand (no ffmpeg) so the conversion math is asserted
# directly: 24/32-bit int keeps the top 16 bits of each sample, float32 is
# clamped then scaled, and unplayable files are reported with a reason.

import os
import io
import struct
import wave

from cue_lib.audio.wav_playable import CueWavPlayable


def _wav_raw(tag, sampwidth, data_bytes, channels=1, rate=48000):
    """Build a minimal WAV from raw fmt tag + sample bytes."""
    data_size = len(data_bytes)
    block_align = channels * sampwidth
    byte_rate = rate * block_align
    fmt = struct.pack(
        "<HHIIHH", tag, channels, rate, byte_rate, block_align, sampwidth * 8
    )
    riff_size = 4 + (8 + len(fmt)) + (8 + data_size)
    return (
        b"RIFF" + struct.pack("<I", riff_size) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", data_size) + data_bytes
    )


def _wav24(data_bytes, channels=1, rate=48000):
    return _wav_raw(1, 3, data_bytes, channels, rate)


def _wav_int(data_bytes, sampwidth=4, channels=1, rate=48000):
    return _wav_raw(1, sampwidth, data_bytes, channels, rate)


def _wav_float(data_bytes, channels=1, rate=48000):
    return _wav_raw(3, 4, data_bytes, channels, rate)


def _wav_extensible_float(data_bytes, channels=1, rate=48000):
    """WAVE_FORMAT_EXTENSIBLE carrying a 32-bit float sub-format (DAW export)."""
    sampwidth = 4
    data_size = len(data_bytes)
    block_align = channels * sampwidth
    byte_rate = rate * block_align
    guid = struct.pack("<IHH", 3, 0, 0x10) + bytes(
        [0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71]
    )
    fmt = struct.pack(
        "<HHIIHH", 0xFFFE, channels, rate, byte_rate, block_align, sampwidth * 8
    )
    fmt += struct.pack("<HHI", 22, sampwidth * 8, 0) + guid
    riff_size = 4 + (8 + len(fmt)) + (8 + data_size)
    return (
        b"RIFF" + struct.pack("<I", riff_size) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", data_size) + data_bytes
    )


def _wav_sw(sampwidth, data_bytes, channels=1, rate=48000):
    """Build a PCM WAV via the wave module (for widths it accepts)."""
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    try:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(bytes(data_bytes))
    finally:
        w.close()
    return buf.getvalue()


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def _read_frames(path):
    out = wave.open(path, "rb")
    try:
        return out.getnchannels(), out.getsampwidth(), out.getframerate(), out.readframes(out.getnframes())
    finally:
        out.close()


def test_convert_24bit_to_16bit(tmp_path):
    src = str(tmp_path / "in.wav")
    _write(src, _wav24(bytes([0x01, 0x02, 0x03, 0xFF, 0xFE, 0x7F, 0x00, 0x00, 0x80])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    playable = w.ensure_playable(src)

    assert playable != src  # redirected to a cached 16-bit copy
    ch, sw, rate, frames = _read_frames(playable)
    assert (ch, sw, rate) == (1, 2, 48000)
    # top 16 bits of each 24-bit sample, low byte dropped
    assert frames == bytes([0x02, 0x03, 0xFE, 0x7F, 0x00, 0x80])


def test_convert_32bit_int_to_16bit(tmp_path):
    src = str(tmp_path / "in32.wav")
    _write(src, _wav_int(bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    playable = w.ensure_playable(src)

    assert playable != src  # no longer passed through silently
    ch, sw, rate, frames = _read_frames(playable)
    assert (ch, sw, rate) == (1, 2, 48000)
    # top 16 bits of each 32-bit sample
    assert frames == bytes([0x03, 0x04, 0x07, 0x08])


def test_convert_32bit_float_to_16bit(tmp_path):
    src = str(tmp_path / "in32f.wav")
    _write(src, _wav_float(struct.pack("<4f", 0.0, -1.0, 1.0, 1.5)))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    playable = w.ensure_playable(src)

    assert playable != src
    ch, sw, rate, frames = _read_frames(playable)
    assert (ch, sw, rate) == (1, 2, 48000)
    # 0.0 -> 0; -1.0 -> -32767 (0x8001 LE); 1.0 -> 32767 (0x7fff LE);
    # 1.5 clamps to 1.0 -> 32767 (0x7fff LE)
    assert frames == bytes([0x00, 0x00, 0x01, 0x80, 0xFF, 0x7F, 0xFF, 0x7F])


def test_convert_extensible_float_to_16bit(tmp_path):
    src = str(tmp_path / "in_ext.wav")
    _write(src, _wav_extensible_float(struct.pack("<2f", -1.0, 1.0)))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    playable = w.ensure_playable(src)

    assert playable != src
    ch, sw, rate, frames = _read_frames(playable)
    assert (ch, sw, rate) == (1, 2, 48000)
    # sub-format GUID (IEEE float) resolves: -1.0 -> -32767, 1.0 -> 32767
    assert frames == bytes([0x01, 0x80, 0xFF, 0x7F])


def test_header_probed_once_then_memoized(tmp_path):
    src = str(tmp_path / "in16.wav")
    _write(src, _wav_sw(2, bytes([0x00, 0x40])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    probes = []
    orig_probe = w._classify

    def _counting_probe(p):
        probes.append(p)
        return orig_probe(p)

    w._classify = _counting_probe

    stats = []
    orig_stat = w._stat

    def _counting_stat(p):
        stats.append(p)
        return orig_stat(p)

    w._stat = _counting_stat

    w.ensure_playable(src)
    w.ensure_playable(src)
    assert len(probes) == 1  # memoized -- header not re-read on later plays
    assert len(stats) == 1   # zero per-play os.stat after the first sighting


def test_passthrough_16bit(tmp_path):
    src = str(tmp_path / "in16.wav")
    _write(src, _wav_sw(2, bytes([0x00, 0x40])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    assert w.ensure_playable(src) == src  # already playable, no cache


def test_passthrough_8bit(tmp_path):
    src = str(tmp_path / "in8.wav")
    _write(src, _wav_sw(1, bytes([0x00, 0x40, 0x80, 0xC0])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    assert w.ensure_playable(src) == src  # SDL_mixer handles 8-bit natively


def test_cache_reused_and_same_node(tmp_path):
    src = str(tmp_path / "in.wav")
    _write(src, _wav24(bytes([0x01, 0x02, 0x03])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    p1 = w.ensure_playable(src)
    p2 = w.ensure_playable(src)
    assert p1 == p2
    assert os.path.exists(p1)


def test_convert_only_once(tmp_path):
    src = str(tmp_path / "in.wav")
    _write(src, _wav24(bytes([0x01, 0x02, 0x03])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    calls = []
    orig = w._convert

    def _counting_convert(s, d):
        calls.append(s)
        return orig(s, d)

    w._convert = _counting_convert

    w.ensure_playable(src)
    w.ensure_playable(src)
    assert len(calls) == 1  # second play did not re-convert


def test_refresh_rebuilds_on_source_size_change(tmp_path):
    src = str(tmp_path / "in.wav")
    _write(src, _wav24(bytes([0x01, 0x02, 0x03])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    p1 = w.refresh(src)

    # Replace with a longer source -> size changes -> refresh rebuilds the node
    _write(src, _wav24(bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])))
    p2 = w.refresh(src)

    assert p1 == p2  # node name is path-derived, stable across rebuilds
    ch, sw, rate, frames = _read_frames(p2)
    # content reflects the new source, not the stale first conversion
    assert frames == bytes([0x02, 0x03, 0x05, 0x06])


def test_unplayable_adpcm_reports_reason(tmp_path):
    src = str(tmp_path / "in_adpcm.wav")
    _write(src, _wav_raw(2, 3, bytes([0x00, 0x11, 0x22])))

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    assert w.ensure_playable(src) == src  # no fake conversion
    assert w.unplayable() == {src: "ADPCM"}


def test_nonwav_passthrough_silent(tmp_path, monkeypatch):
    """Non-WAV containers (ogg/mp3/opus) are left alone -- no warning, no log."""
    src = str(tmp_path / "in.ogg")
    _write(src, b"OggS" + b"\x00" * 20)

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    logged = []
    monkeypatch.setattr("cue_lib.audio.wav_playable._cue_log", lambda msg: logged.append(msg))

    assert w.ensure_playable(src) == src  # passthrough, not our problem
    assert w.unplayable() == {}           # nothing flagged
    assert not any("unplayable" in m for m in logged)


def test_corrupt_wav_reports_not_valid(tmp_path, monkeypatch):
    """A file with a WAV container but a broken header is flagged, not silent."""
    src = str(tmp_path / "broken.wav")
    _write(src, b"RIFF" + struct.pack("<I", 4) + b"WAVE")  # RIFF/WAVE magic, no fmt/data

    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))
    logged = []
    monkeypatch.setattr("cue_lib.audio.wav_playable._cue_log", lambda msg: logged.append(msg))

    assert w.ensure_playable(src) == src
    assert w.unplayable() == {src: "not a valid WAV"}
    assert any("unplayable" in m for m in logged)


def test_unreadable_and_nonwav_return_original(tmp_path):
    w = CueWavPlayable(temp_root=str(tmp_path / "cache"))

    missing = str(tmp_path / "nope.wav")
    assert w.ensure_playable(missing) == missing

    txt = str(tmp_path / "x.txt")
    _write(txt, b"hello")
    assert w.ensure_playable(txt) == txt
