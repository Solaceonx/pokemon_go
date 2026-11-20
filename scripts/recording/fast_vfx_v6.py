"""Source-conditional attack-VFX gestures, distinct from energy completions.

Pixels are used only during acquisition; saved features contain numeric values
and game enums. Training counts are never detector input. Known camera/target
depth is an explicit source-assisted prerequisite, not a whole-VOD classifier.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


def signal(rgb, model, colour):
    import cv2
    import numpy as np
    x0, y0, x1, y1 = model['box']
    a = rgb[y0:y1, x0:x1].astype(np.float32)
    if model['kind'] == 'orange_glow_component':
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        mask = ((r > colour['orange_r_min']) & (g >= colour['orange_g_range'][0])
            & (g <= colour['orange_g_range'][1]) & (b < colour['orange_b_max'])
            & (r > colour['r_over_g'] * g) & (g > colour['g_over_b'] * b))
        fraction = float(mask.mean())
        if fraction > model['occluded_orange_fraction']:
            return dict(positive=False, visible=False, score=0., orange_fraction=fraction,
                        reason='large_foreground_orange_occlusion')
        n, components, stats, centres = cv2.connectedComponentsWithStats(mask.astype('uint8'), 8)
        white = (a.min(2) > colour['halo_white_min']) & (a.max(2) - a.min(2) < colour['halo_white_chroma_max'])
        blue = ((b > model.get('halo_blue_b_min', colour['halo_blue_b_min']))
                & (g > model.get('halo_blue_g_min', colour['halo_blue_g_min']))
                & (r <= model.get('halo_blue_r_max', 255))
                & (b > colour['halo_blue_r_ratio'] * r))
        score = 0
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if not model['area_range'][0] <= area <= model['area_range'][1]:
                continue
            if not model['aspect_range'][0] <= w / max(1, h) <= model['aspect_range'][1]:
                continue
            if centres[i][1] + y0 < model['minimum_center_y']:
                continue
            component = (components == i).astype('uint8')
            halo = (cv2.dilate(component, np.ones((17, 17), np.uint8)) > 0) & ~component.astype(bool)
            white_ok = int((halo & white).sum()) >= model.get('halo_white_min_pixels', 8)
            blue_ok = int((halo & blue).sum()) >= model.get('halo_blue_min_pixels', 20)
            accepted = white_ok and blue_ok if model.get('halo_mode') == 'both' else white_ok or blue_ok
            if accepted:
                score = max(score, int(area))
        return dict(positive=score > 0, visible=True, score=float(score), orange_fraction=fraction,
                    reason='orange_component_with_local_impact_halo' if score else 'no_accepted_component')
    if model['kind'] != 'white_parallel_slashes':
        raise ValueError('Unknown VFX feature')
    white = ((a.min(2) > 175) & (a.max(2) - a.min(2) < 100)).astype('uint8') * 255
    if float((white > 0).mean()) > .35:
        return dict(positive=False, visible=False, score=0., reason='white_foreground_occlusion')
    edges = cv2.Canny(white, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, math.pi / 180, 12, minLineLength=20, maxLineGap=3)
    offsets = []
    for x, y, xx, yy in [] if lines is None else np.asarray(lines).reshape(-1, 4):
        angle = math.degrees(math.atan2(float(yy-y), float(xx-x)))
        angle = (angle + 90) % 180 - 90
        if -65 <= angle <= -25:
            offsets.append((x + xx + y + yy) / (2 * math.sqrt(2)))
    unique = []
    for value in sorted(offsets):
        if not unique or value - unique[-1] >= 6:
            unique.append(value)
    count = int(max((sum(abs(v-u) <= 45 for v in unique) for u in unique), default=0))
    return dict(positive=count >= 3, visible=True, score=float(count),
                reason='parallel_bright_slashes' if count >= 3 else 'no_three_distinct_slashes')


def gestures(rows, model, *, start=None, end=None):
    events, gaps, current = [], [], None
    for row in rows:
        t = row['t']
        if start is not None and t < start or end is not None and t > end:
            continue
        item = row['signals'][model['id']]
        if not item['visible']:
            gaps.append(t)
        if current and t - current['last'] > model['merge_gap_seconds']:
            if current['samples'] >= model['min_positive_samples']:
                events.append(current)
            current = None
        if item['positive']:
            if current is None:
                current = dict(t=t, last=t, samples=0, side=model['side'], move=model['move_id'],
                    model=model['id'], kind='measured_animation_gesture', energy_completion_verified=False)
            current['last'] = t
            current['samples'] += 1
    if current and current['samples'] >= model['min_positive_samples']:
        events.append(current)
    merged = []
    for event in events:
        if (merged and event['t'] - merged[-1]['t'] <
                model.get('minimum_distinct_gesture_spacing_seconds', 0)):
            merged[-1]['last'] = event['last']
            merged[-1]['samples'] += event['samples']
        else:
            merged.append(event)
    return dict(events=merged, occluded_frame_seconds=gaps, measured_energy_credit=False)


def acquire(video, models, colour, start, end, fps, target):
    if (not models or not all(math.isfinite(v) for v in [start, end, fps])
            or not 0 <= start < end or end-start > 20 or not 0 < fps <= 60):
        raise ValueError('Prototype requires a known model and a finite reference window of at most20seconds')
    import av
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    frames = []
    next_at = start
    with av.open(str(video)) as media:
        stream = media.streams.video[0]
        stream.codec_context.thread_count = 1
        if start > 30:
            media.seek(int(max(0, start-2)/float(stream.time_base)), stream=stream,
                       backward=True, any_frame=False)
        for frame in media.decode(stream):
            if frame.time is None or frame.time + 1e-7 < next_at:
                continue
            if frame.time > end + 1e-7:
                break
            raw = frame.to_ndarray(format='rgb24')
            rgb = cv2.resize(raw, (508, 1080))
            frames.append(dict(t=frame.time, pts=frame.pts, time_base=str(frame.time_base),
                decoded_rgb_sha256=hashlib.sha256(raw.tobytes()).hexdigest(),
                signals={m['id']: signal(rgb, m, colour) for m in models}))
            next_at += 1 / fps
    pending = target.with_name(target.name + '.pending')
    with pending.open('wb') as raw:
        with gzip.GzipFile(filename=target.name, fileobj=raw, mode='wb', mtime=0) as handle:
            for row in frames:
                handle.write((json.dumps(row, separators=(',', ':')) + '\n').encode())
    pending.replace(target)
    return dict(video_sha256=source_sha, sampled_frames=len(frames), interval=[start, end], fps=fps,
                features_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                acquisition_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                persistent_decoder=True, raw_images_exported=False,
                runtime=dict(av=av.__version__, cv2=cv2.__version__, numpy=np.__version__))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--record', required=True)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    parser.add_argument('--fps', type=float, default=15)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.model.read_text(encoding='utf8'))
    models = [m for m in data['models'] if m['record'] == args.record]
    result = acquire(args.video, models, data['colour_parameters'], args.start, args.end, args.fps, args.out)
    result['model_sha256'] = hashlib.sha256(args.model.read_bytes()).hexdigest()
    args.receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__': main()
