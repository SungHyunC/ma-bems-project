"""Narration audio, timing and subtitles for the demo video.

    python demo/timeline.py <work dir>

Reads demo/script.json, has demo/tts.ps1 speak every line with the Windows Korean voice, then writes into <work dir>:
  timeline.json   scene durations and line start times (demo/record.mjs plays the page actions on this clock)
  narration.wav   the whole soundtrack, title card silence included
  subtitles.ass   Korean subtitles for the band under the picture
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
TITLE, END = 3.0, 3.5                                     # title / end card seconds (silent)


def wav_info(p):
    with wave.open(str(p), 'rb') as w:
        return w.getnframes() / w.getframerate(), w.getframerate(), w.readframes(w.getnframes())


def ass_time(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return '%d:%02d:%05.2f' % (h, m, s)


def main():
    work = Path(sys.argv[1]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    plan = json.loads((HERE / 'script.json').read_text(encoding='utf-8'))
    lines = [{'id': '%s_%d' % (sc['id'], i + 1), 'say': ln['say']} for sc in plan['scenes'] for i, ln in enumerate(sc['lines'])]
    (work / 'lines.json').write_text(json.dumps(lines, ensure_ascii=False), encoding='utf-8')
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(HERE / 'tts.ps1'),
                    '-Json', str(work / 'lines.json'), '-OutDir', str(work / 'wav'), '-Rate', str(plan['rate'])], check=True)

    rate, pcm = None, bytearray()
    silence = lambda sec: b'\x00\x00' * int(round(sec * rate))   # noqa: E731  (16-bit mono)
    timeline, subs, clock = {'title': TITLE, 'end': END, 'scenes': []}, [], TITLE
    for sc in plan['scenes']:
        t, entries, audio = plan['lead'], [], bytearray()
        for i, ln in enumerate(sc['lines']):
            dur, sr, frames = wav_info(work / 'wav' / ('%s_%d.wav' % (sc['id'], i + 1)))
            if rate is None:
                rate = sr
                pcm += silence(TITLE)
            if not audio:
                audio += silence(plan['lead'])
            entries.append({'start': round(t, 3), 'dur': round(dur, 3), 'do': ln.get('do', []), 'after': ln.get('after', [])})
            subs.append((clock + t, clock + t + dur + 0.2, ln['text']))
            audio += frames
            t += dur
            if i + 1 < len(sc['lines']):
                audio += silence(plan['gap'])
                t += plan['gap']
        scene_dur = t + plan['tail'] + sc.get('extra', 0)
        audio += silence(scene_dur - t)
        pcm += audio
        timeline['scenes'].append({'id': sc['id'], 'url': sc.get('url'), 'setup': sc.get('setup', []), 'duration': round(scene_dur, 3), 'lines': entries})
        clock += scene_dur
    pcm += silence(END)
    timeline['total'] = round(clock + END, 3)
    with wave.open(str(work / 'narration.wav'), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(pcm))
    (work / 'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding='utf-8')

    head = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1920', 'PlayResY: 1080', 'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
            'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
            'Style: Band,Malgun Gothic,38,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,140,140,30,1',
            '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    ev = ['Dialogue: 0,%s,%s,Band,,0,0,0,,%s' % (ass_time(a), ass_time(b), txt.replace('\n', '\\N')) for a, b, txt in subs]
    (work / 'subtitles.ass').write_text('\n'.join(head + ev) + '\n', encoding='utf-8-sig')
    print('scenes', len(timeline['scenes']), 'total %.1f s' % timeline['total'])
    for s in timeline['scenes']:
        print('  %-4s %5.1f s  lines at %s' % (s['id'], s['duration'], [l['start'] for l in s['lines']]))


if __name__ == '__main__':
    main()
