"""Builds the demo video from the recorded frames, the narration and the subtitles.

    python demo/assemble.py <work dir> <out.mp4>

<work dir> holds timeline.json, narration.wav, subtitles.ass (demo/timeline.py) and frames/<scene>/ (demo/record.mjs).
Each scene becomes a constant 30 fps clip of exactly its narration length (frames are placed at the time they arrived),
title and end cards are added, then the picture gets a 120 px subtitle band below it (1920x960 -> 1920x1080) and the
narration, loudness-normalised, as AAC.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 960, 30
FONT, BOLD = r'C:\Windows\Fonts\malgun.ttf', r'C:\Windows\Fonts\malgunbd.ttf'


def run(args, cwd):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y'] + args, cwd=cwd)
    if r.returncode:
        raise SystemExit('ffmpeg failed: %s' % ' '.join(args[:12]))


def card(path, lines):
    """A dark violet card: lines = [(text, size, bold, colour)] centred vertically."""
    img = Image.new('RGB', (W, H))
    top, bottom = (36, 28, 84), (14, 12, 31)
    px = img.load()
    for y in range(H):
        k = y / (H - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3))
        for x in range(W):
            px[x, y] = c
    d = ImageDraw.Draw(img)
    fonts = [ImageFont.truetype(BOLD if b else FONT, s) for _, s, b, _ in lines]
    heights = [f.getbbox(t)[3] - f.getbbox(t)[1] for (t, _, _, _), f in zip(lines, fonts)]
    gap = 28
    y = (H - (sum(heights) + gap * (len(lines) - 1))) / 2
    for (t, _, _, col), f, h in zip(lines, fonts, heights):
        w = d.textlength(t, font=f)
        d.text(((W - w) / 2, y - f.getbbox(t)[1]), t, font=f, fill=col)
        y += h + gap
    img.save(path)


def main():
    work, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    tl = json.loads((work / 'timeline.json').read_text(encoding='utf-8'))
    clips = work / 'clips'
    clips.mkdir(exist_ok=True)

    card(work / 'title.png', [('MA-BEMS', 120, True, (255, 255, 255)),
                              ('멀티에이전트 건물 에너지 관리 시스템 · 시연', 46, True, (214, 209, 255)),
                              ('고려대 세종 2026-2 기업연계형 캡스톤디자인', 30, False, (170, 164, 214))])
    card(work / 'end.png', [('감사합니다', 92, True, (255, 255, 255)),
                            ('공개 대시보드  sunghyunc.github.io/ma-bems', 38, False, (214, 209, 255)),
                            ('프로젝트 원본  github.com/SungHyunC/ma-bems-project', 32, False, (170, 164, 214))])
    still = lambda png, sec, name: run(['-loop', '1', '-i', png, '-t', str(sec), '-vf',   # noqa: E731
                                        'fps=%d,format=yuv420p,fade=in:st=0:d=0.5,fade=out:st=%.2f:d=0.5' % (FPS, sec - 0.5),
                                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', str(clips / name)], work)
    still('title.png', tl['title'], '00_title.mp4')
    order = ['00_title.mp4']
    scenes = tl['scenes']
    for i, sc in enumerate(scenes):
        meta = json.loads((work / 'frames' / sc['id'] / 'frames.json').read_text(encoding='utf-8'))
        frames = [f for f in meta['frames'] if f['t'] < sc['duration']]
        lst = []
        for j, f in enumerate(frames):
            nxt = frames[j + 1]['t'] if j + 1 < len(frames) else sc['duration']
            lst.append("file 'frames/%s/%s'\nduration %.4f" % (sc['id'], f['file'], max(0.001, nxt - f['t'])))
        lst.append("file 'frames/%s/%s'" % (sc['id'], frames[-1]['file']))        # the concat demuxer needs the last file twice
        (work / ('list_%s.txt' % sc['id'])).write_text('\n'.join(lst) + '\n', encoding='utf-8')
        vf = ['fps=%d' % FPS, 'scale=%d:%d:flags=lanczos' % (W, H), 'format=yuv420p']
        if sc.get('url') and i > 0:                         # a new page load: soften the cut
            vf.append('fade=in:st=0:d=0.35')
        if i + 1 < len(scenes) and scenes[i + 1].get('url'):
            vf.append('fade=out:st=%.2f:d=0.35' % (sc['duration'] - 0.35))
        name = '%02d_%s.mp4' % (i + 1, sc['id'])
        run(['-f', 'concat', '-safe', '0', '-i', 'list_%s.txt' % sc['id'], '-vf', ','.join(vf), '-t', '%.3f' % sc['duration'],
             '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-r', str(FPS), str(clips / name)], work)
        order.append(name)
        print('clip', name, sc['duration'], 's', len(frames), 'frames')
    still('end.png', tl['end'], '99_end.mp4')
    order.append('99_end.mp4')
    (clips / 'all.txt').write_text(''.join("file '%s'\n" % n for n in order), encoding='utf-8')
    run(['-f', 'concat', '-safe', '0', '-i', 'all.txt', '-c', 'copy', 'video.mp4'], clips)
    run(['-i', 'clips/video.mp4', '-i', 'narration.wav',
         '-filter_complex', "[0:v]pad=1920:1080:0:0:color=0x14121F,ass=subtitles.ass:fontsdir='C\\:/Windows/Fonts'[v];"
                            "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]",
         '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'slow', '-crf', '26', '-pix_fmt', 'yuv420p',   # about 90 MB for 3 min: under GitHub's 100 MB file limit
         '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-shortest', str(out)], work)
    print('wrote', out)


if __name__ == '__main__':
    main()
