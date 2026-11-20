"""Score grouped gesture detection separately from first-onset timing."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from fast_vfx_v6 import gestures


def distance(t, window):
    return max(window[0] - t, t - window[1], 0.)


def match_events(predictions, truth, tolerance=.15):
    candidates = sorted((distance(p['t'], q.get('gesture_window', q['onset_window'])), i, j)
        for i, p in enumerate(predictions) for j, q in enumerate(truth)
        if p['side'] == q['side'] and distance(p['t'], q.get('gesture_window', q['onset_window'])) <= tolerance)
    used_p, used_q, matches = set(), set(), []
    for error, i, j in candidates:
        if i in used_p or j in used_q:
            continue
        used_p.add(i); used_q.add(j)
        onset_error = distance(predictions[i]['t'], truth[j]['onset_window'])
        matches.append(dict(prediction=i, reference=j, gesture_window_error_seconds=error,
            onset_window_error_seconds=onset_error, onset_within_150ms=onset_error <= .15))
    tp = len(matches)
    return dict(tp=tp, fp=len(predictions)-tp, fn=len(truth)-tp,
        precision=tp/len(predictions) if predictions else None,
        recall=tp/len(truth) if truth else None,
        matched_onset_within_150ms=sum(m['onset_within_150ms'] for m in matches),
        matches=matches, unmatched_predictions=sorted(set(range(len(predictions)))-used_p),
        unmatched_references=sorted(set(range(len(truth)))-used_q))


def evaluate(root, model_path, labels_path, manifest):
    model = json.loads(model_path.read_text(encoding='utf8'))
    labels = json.loads(labels_path.read_text(encoding='utf8'))
    clips = []
    for clip in labels['clips']:
        if clip.get('scorable') is False:
            clips.append(dict(id=clip.get('id'), record=clip['record'], predictions=[], signals=[],
                reference_events=[], score=match_events([], []), unobservable=clip.get('unobservable', []),
                source_window_scorable=False, detector_run=False))
            continue
        path = root / manifest['features'][clip['record']]
        with gzip.open(path, 'rt', encoding='utf8') as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        predictions, signals = [], []
        for m in model['models']:
            if m['record'] != clip['record']:
                continue
            result = gestures(rows, m, start=clip['review_interval'][0], end=clip['review_interval'][1])
            predictions += result['events']
            signals.append(dict(model=m['id'], occluded_frames=len(result['occluded_frame_seconds'])))
        predictions.sort(key=lambda p: (p['t'], p['side']))
        clips.append(dict(id=clip.get('id'), record=clip['record'], predictions=predictions, signals=signals,
            reference_events=clip['events'], score=match_events(predictions, clip['events']),
            unobservable=clip.get('unobservable', []), features_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source_window_scorable=True, detector_run=True))
    counts = {k: sum(c['score'][k] for c in clips) for k in ['tp', 'fp', 'fn', 'matched_onset_within_150ms']}
    counts['precision'] = counts['tp']/(counts['tp']+counts['fp']) if counts['tp']+counts['fp'] else None
    counts['recall'] = counts['tp']/(counts['tp']+counts['fn']) if counts['tp']+counts['fn'] else None
    return dict(schema='fast-vfx-v6-timing-score-v1', scope=manifest['scope'], score=counts, clips=clips,
        attempted_source_windows=len(clips), scorable_source_windows=sum(c['source_window_scorable'] for c in clips),
        interpretation=['Gesture recognition uses source-annotated whole-gesture windows with0.15s tolerance',
            'First characteristic colour onset within0.15s is a separate metric; late strong peaks are not precise onsets',
            'Animation gestures are not independently verified energy-completion timestamps',
            'Unobservable actor/camera intervals stay explicit, never converted to zero attacks'],
        energy_credit_calibrated=False, certified_energy_integration=False, promoted=False,
        reproduction=dict(model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
            labels_sha256=hashlib.sha256(labels_path.read_bytes()).hexdigest(), manifest=manifest,
            scorer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root, args.model, args.labels, json.loads(args.manifest.read_text(encoding='utf8')))
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(result['score']))


if __name__ == '__main__': main()
