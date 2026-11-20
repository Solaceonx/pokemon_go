"""Measure physical HP rectangles without fixing their left edge to a guessed width.

This module only measures pixels. Identity, temporal smoothing, faint inference,
energy and battle outcomes belong to later stages. It never reads game labels.
"""
import hashlib
import inspect
import json


def acquisition_digest():
    from creator_observations import glyph_row, classify_headers
    code = '\n'.join(inspect.getsource(f) for f in
                     (palette, rectangle, dim_rectangle, candidates, independent_rail_rectangle,
                      positive_fallback_candidates, glyph_features, header_row_panels,
                      header_panels, glyph_row, classify_headers, scene_features, measure_frame,
                      measure_with_recent_geometry))
    return hashlib.sha256(code.replace('\r\n', '\n').encode('utf-8')).hexdigest()


def palette(rgb, bounds):
    import cv2
    import numpy as np
    x, y, right, bottom = bounds
    area = rgb[y+3:bottom-3, x+3:right-3]
    if not area.size:
        return None
    hsv = cv2.cvtColor(area, cv2.COLOR_RGB2HSV)
    vivid = (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 140)
    hue = hsv[:, :, 0]
    cyan = vivid & (hue >= 65) & (hue <= 105)
    yellow = vivid & (hue >= 26) & (hue <= 40)
    red = vivid & ((hue <= 9) | (hue >= 170))
    orange = vivid & (hue >= 14) & (hue <= 24)
    # A green HP strip has one live color. Warm pixels at its trailing edge
    # are transition/damage pixels, not another helping of live HP. Yellow
    # and red bars still use their actual warm live colors.
    live_color = cyan if cyan.sum() > (yellow | red).sum() else (yellow | red)
    live = live_color.mean(axis=0) >= .5
    damage = orange.mean(axis=0) >= .5
    colored = (live | damage)
    dark = hsv[:, :, 2] < 125
    support = float(((cyan | yellow | red | orange) | dark).mean())
    if support < .85:
        return None
    indices = np.flatnonzero(live)
    leading = int(indices[0]) if len(indices) else None
    if leading is not None and leading > 3:
        return None
    stop = 0
    if leading is not None:
        stop = len(live)
        for i in range(leading, len(live)-1):
            if not live[i] and not live[i+1]:
                stop = i
                break
        if live[min(stop+2, len(live)):].sum() > 2:
            return None
    # An offset orange damage strip is valid after the live prefix, but a
    # disconnected bright tail is not silently counted as current health.
    width = len(live)
    if width < 1:
        return None
    red_columns = int((red.mean(axis=0) >= .5).sum())
    yellow_columns = int((yellow.mean(axis=0) >= .5).sum())
    if stop and ((red_columns > stop*.5 and stop/width > .65) or
                 (yellow_columns > stop*.5 and stop/width > .85)):
        return None  # a near-full solid warm glyph is not a real full HP bar
    uncertainty = 2
    return {'interior_width_pixels': width, 'live_pixels': stop,
            'damage_pixels': int(damage.sum()), 'fraction': round(stop/width, 6),
            'fraction_interval': [round(max(0, stop-uncertainty)/width, 6),
                                  round(min(width, stop+uncertainty)/width, 6)],
            'pixel_uncertainty': uncertainty, 'interior_support': round(support, 4),
            'live_color_pixels': {'cyan': int((cyan.mean(axis=0) >= .5).sum()),
                                  'yellow': int((yellow.mean(axis=0) >= .5).sum()),
                                  'red': int((red.mean(axis=0) >= .5).sum())}}


def rectangle(rgb, bounds, method):
    import cv2
    import numpy as np
    x, y, right, bottom = bounds
    if x < 1 or y < 1 or right >= rgb.shape[1]-1 or bottom >= rgb.shape[0]-1:
        return None
    hsv = cv2.cvtColor(rgb[y-1:bottom+1, x-1:right+1], cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    pale = ((s < 100) & (v > 150)) | ((h <= 40) & (v > 160))
    # A saturated orange/yellow damage boundary can close a contour inside
    # the real bar. Require pale vertical rails so that boundary cannot turn
    # a partly depleted bar into an apparently full, shorter rectangle.
    side_pale = (s < 100) & (v > 150)
    left = float(side_pale[3:-3, :4].mean(axis=0).max())
    right_support = float(side_pale[3:-3, -4:].mean(axis=0).max())
    top = float(pale[:4, 3:-3].mean(axis=1).max())
    bottom_support = float(pale[-4:, 3:-3].mean(axis=1).max())
    if min(left, right_support) < .6 or min(top, bottom_support) < .65:
        return None
    measurement = palette(rgb, bounds)
    if measurement is None:
        return None
    return {'bounds': list(bounds), 'outline_method': method,
            'side_rail_support': [round(left, 4), round(right_support, 4)],
            'horizontal_rail_support': [round(top, 4), round(bottom_support, 4)],
            **measurement}


def dim_rectangle(rgb, bounds, expected_width):
    """Recover a positive bar with four mutually consistent, dim physical rails.

    The width guard belongs to the measured UI profile. This fallback cannot
    establish an empty bar or a faint; those still require the strict outline.
    """
    import numpy as np
    x, y, right, bottom = bounds
    if (abs((right-x)-expected_width) > 6 or x < 1 or y < 1
            or right >= rgb.shape[1]-1 or bottom >= rgb.shape[0]-1):
        return None
    measurement = palette(rgb, bounds)
    if measurement is None or measurement['live_pixels'] == 0:
        return None
    roi = rgb[y-1:bottom+1, x-1:right+1].astype(float)
    if min(roi.shape[:2]) <= 6:
        return None
    colors = np.concatenate([np.median(roi[3:-3, :4], axis=0),
                             np.median(roi[3:-3, -4:], axis=0),
                             np.median(roi[:4, 3:-3], axis=1),
                             np.median(roi[-4:, 3:-3], axis=1)])
    choices = []
    for color in colors:
        if color.max() < 80 or color.max()-color.min() > 160:
            continue
        same = np.linalg.norm(roi-color, axis=2) < 35
        support = [float(same[3:-3, :4].mean(axis=0).max()),
                   float(same[3:-3, -4:].mean(axis=0).max()),
                   float(same[:4, 3:-3].mean(axis=1).max()),
                   float(same[-4:, 3:-3].mean(axis=1).max())]
        if min(support) >= .65:
            choices.append(support)
    if not choices:
        return None
    support = max(choices, key=min)
    return {'bounds': list(bounds), 'outline_method': 'four_rail_color_consensus_positive_only',
            'side_rail_support': [round(v, 4) for v in support[:2]],
            'horizontal_rail_support': [round(v, 4) for v in support[2:]], **measurement}


def candidates(rgb, expected_width=144):
    import cv2
    import numpy as np
    region = rgb[200:900, 2:506]
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 35, 90)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    rectangles = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if expected_width-20 <= w <= expected_width+25 and 10 <= h <= 20:
            rectangles.append(([x+2, y+200, x+w+2, y+h+200], 'closed_physical_contour'))
    hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    pale = (((s < 100) & (v > 150)) | ((h <= 40) & (v > 160))).astype(np.uint8)*255
    pale = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8))
    rails = cv2.morphologyEx(pale, cv2.MORPH_OPEN, np.ones((1, expected_width-20), np.uint8))
    rail_contours, _ = cv2.findContours(rails, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    lines = [cv2.boundingRect(c) for c in rail_contours]
    lines = [r for r in lines if r[3] <= 4]
    for x, y, w, h in lines:
        for bx, by, bw, bh in lines:
            left, right = max(x, bx), min(x+w, bx+bw)
            if 8 <= by-y <= 17 and expected_width-20 <= right-left <= expected_width+25:
                rectangles.append(([left+2, y+200, right+2, by+bh+200], 'physical_rail_intersection'))
    found = []
    for bounds, method in rectangles:
        r = rectangle(rgb, bounds, method)
        if r is None:
            r = dim_rectangle(rgb, bounds, expected_width)
        if r:
            found.append(r)
    # Multiple contours describe the outer and inner edges of the same UI bar.
    # Prefer strong physical rails and a supported interior over an outer glow halo.
    def quality(r):
        height = r['bounds'][3]-r['bounds'][1]
        return r['interior_support']+min(r['side_rail_support'])+min(r['horizontal_rail_support'])-.03*abs(height-14)
    found.sort(key=lambda r: (-quality(r), -(r['bounds'][2]-r['bounds'][0])))
    unique = []
    for r in found:
        a = r['bounds']
        if any(abs((a[0]+a[2])-(b['bounds'][0]+b['bounds'][2])) <= 14 and
               abs((a[1]+a[3])-(b['bounds'][1]+b['bounds'][3])) <= 12 for b in unique):
            continue
        unique.append(r)
    return unique


def independent_rail_rectangle(rgb, bounds, expected_width):
    """Positive-only, width-bounded reading when the four rails shade differently.

    Each rail must be coherent and contrast with the adjacent interior. The
    profile width bounds geometry uncertainty; this path cannot establish zero.
    """
    import numpy as np
    x, y, right, bottom = bounds
    if (expected_width <= 12 or abs(right-x-expected_width) > 6 or x < 1 or y < 1
            or right >= rgb.shape[1]-1 or bottom >= rgb.shape[0]-1):
        return None
    measurement = palette(rgb, bounds)
    if measurement is None or measurement['live_pixels'] == 0:
        return None
    roi = rgb[y-1:bottom+1, x-1:right+1].astype(float)
    if min(roi.shape[:2]) < 10:
        return None
    rail_sets = [
        [(roi[3:-3, j], roi[3:-3, j+3]) for j in range(4)],
        [(roi[3:-3, j], roi[3:-3, j-3]) for j in range(roi.shape[1]-4, roi.shape[1])],
        [(roi[j, 3:-3], roi[j+3, 3:-3]) for j in range(4)],
        [(roi[j, 3:-3], roi[j-3, 3:-3]) for j in range(roi.shape[0]-4, roi.shape[0])]]
    selected = []
    for options in rail_sets:
        found = []
        for pixels, inside in options:
            color = np.median(pixels, axis=0)
            if color.max() < 80:
                continue
            support = float((np.linalg.norm(pixels-color, axis=1) < 35).mean())
            contrast = float((np.linalg.norm(pixels-inside, axis=1) > 25).mean())
            if support >= .65 and contrast >= .65:
                found.append((support, contrast))
        if not found:
            return None
        selected.append(max(found, key=min))
    live = measurement['live_pixels']
    lo, hi = measurement['fraction_interval']
    measurement['fraction_interval'] = [round(min(lo, max(0, (live-2)/expected_width)), 6),
        round(max(hi, min(1, (live+2)/(expected_width-12))), 6)]
    return dict(bounds=list(bounds), outline_method='independent_shaded_rails_positive_only',
        side_rail_support=[r[0] for r in selected[:2]], horizontal_rail_support=[r[0] for r in selected[2:]],
        rail_inner_contrast=[r[1] for r in selected], profile_width_guard=expected_width,
        geometry_width_uncertainty_pixels=6, **measurement)


def positive_fallback_candidates(rgb, expected_width):
    """Find color edges missed by grayscale; all supplemental bars stay positive."""
    import cv2
    region = rgb[200:900, 2:506]
    boxes = set()
    for channel in range(3):
        contours, _ = cv2.findContours(cv2.Canny(region[:, :, channel], 35, 90),
                                      cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if expected_width-6 <= w <= expected_width+6 and 10 <= h <= 20:
                boxes.add((x+2, y+200, x+w+2, y+h+200))
    # A grayscale contour can have the correct geometry despite shaded rails.
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    contours, _ = cv2.findContours(cv2.Canny(gray, 35, 90), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if expected_width-6 <= w <= expected_width+6 and 10 <= h <= 20:
            boxes.add((x+2, y+200, x+w+2, y+h+200))
    found = []
    for bounds in sorted(boxes):
        bar = (rectangle(rgb, bounds, 'color_channel_physical_contour')
               or dim_rectangle(rgb, bounds, expected_width)
               or independent_rail_rectangle(rgb, bounds, expected_width))
        if bar and bar['live_pixels'] > 0:
            found.append(bar)
    def quality(bar):
        return (bar['outline_method'] == 'independent_shaded_rails_positive_only',
                -(bar['interior_support']+min(bar['side_rail_support'])+min(bar['horizontal_rail_support'])),
                abs(bar['bounds'][3]-bar['bounds'][1]-14), tuple(bar['bounds']))
    found.sort(key=quality)
    unique = []
    for bar in found:
        a = bar['bounds']
        if any(abs(a[0]+a[2]-b['bounds'][0]-b['bounds'][2]) <= 14
               and abs(a[1]+a[3]-b['bounds'][1]-b['bounds'][3]) <= 12 for b in unique):
            continue
        unique.append(bar)
    return unique


def measure_frame(rgb, expected_width=144):
    regions = {'mine': [], 'theirs': [], 'center': []}
    for bar in candidates(rgb, expected_width):
        x, y, right, bottom = bar['bounds']
        center = (x+right)/2
        side = 'mine' if center < 195 and right <= 242 else 'theirs' if center > 315 and x >= 228 else 'center' if 222 <= center <= 286 else None
        if side:
            regions[side].append(bar)
    # Preserve existing readings and ambiguities. Supplemental positive pixels
    # apply only to missing sidebars outside a detected charged close-up.
    if not regions['center'] and any(not regions[s] for s in ('mine', 'theirs')):
        supplemental = {'mine': [], 'theirs': []}
        for bar in positive_fallback_candidates(rgb, expected_width):
            x, y, right, bottom = bar['bounds']
            center = (x+right)/2
            side = 'mine' if center < 195 and right <= 242 else 'theirs' if center > 315 and x >= 228 else None
            if side and not regions[side]:
                supplemental[side].append(bar)
        for side in supplemental:
            if not regions[side]:
                regions[side] = supplemental[side]
    return {side: {'status': 'observed' if len(bars) == 1 else 'ambiguous' if bars else 'not_visible',
                   'bar': bars[0] if len(bars) == 1 else None,
                   **({'candidate_count': len(bars)} if len(bars) > 1 else {})}
            for side, bars in regions.items()}


def measure_with_recent_geometry(rgb, expected_width=144, previous=(), at=None):
    """Reuse only a recent rectangle proposal; measure HP from current pixels.

    An animation can break a contour without hiding the physical rails. A
    proposal from at most a quarter second ago still needs the existing four
    rails, valid width and positive live prefix in this frame. It cannot add
    an empty bar, resolve an ambiguity, or replace a current measurement.
    """
    import math
    result = measure_frame(rgb, expected_width)
    if (not isinstance(at, (int, float)) or isinstance(at, bool) or not math.isfinite(at)
            or result['center']['status'] != 'not_visible'):
        return result
    for side in ('mine', 'theirs'):
        if result[side]['status'] != 'not_visible':
            continue
        proposals = {}
        for sample in previous:
            seen = sample.get('t')
            if (not isinstance(seen, (int, float)) or isinstance(seen, bool) or not math.isfinite(seen)
                    or not 0 < at-seen <= .25):
                continue
            value = sample.get('health', {}).get(side, {})
            if value.get('status') != 'observed' or not value.get('bar'):
                continue
            x, y, right, bottom = value['bar']['bounds']
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    bounds = (x+dx, y+dy, right+dx, bottom+dy)
                    center = (bounds[0]+bounds[2])/2
                    who = ('mine' if center < 195 and bounds[2] <= 242 else
                           'theirs' if center > 315 and bounds[0] >= 228 else None)
                    if who == side and abs(bounds[2]-bounds[0]-expected_width) <= 6:
                        proof = dict(observed_at_seconds=seen, source_bounds=list(value['bar']['bounds']),
                                     translation_pixels=[dx,dy], value_carried=False)
                        if bounds not in proposals or seen > proposals[bounds]['observed_at_seconds']:
                            proposals[bounds] = proof
        found = []
        for bounds, proof in proposals.items():
            value = (rectangle(rgb, bounds, 'recent_geometry_current_positive_pixels')
                     or dim_rectangle(rgb, bounds, expected_width)
                     or independent_rail_rectangle(rgb, bounds, expected_width))
            if value and value['live_pixels'] > 0:
                value['geometry_proposal'] = proof
                found.append(value)
        found.sort(key=lambda b: (b['outline_method'] == 'independent_shaded_rails_positive_only',
            -(b['interior_support']+min(b['side_rail_support'])+min(b['horizontal_rail_support'])),
            abs(b['bounds'][3]-b['bounds'][1]-14), tuple(b['bounds'])))
        unique = []
        for value in found:
            a = value['bounds']
            if any(abs(a[0]+a[2]-b['bounds'][0]-b['bounds'][2]) <= 14 and
                   abs(a[1]+a[3]-b['bounds'][1]-b['bounds'][3]) <= 12 for b in unique):
                continue
            unique.append(value)
        if unique:
            result[side] = dict(status='observed' if len(unique) == 1 else 'ambiguous',
                bar=unique[0] if len(unique) == 1 else None,
                **({'candidate_count':len(unique)} if len(unique) > 1 else {}))
    return result


def glyph_features(roi, offset_x, offset_y):
    import cv2
    import numpy as np
    hue, sat, val = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    # Pale active shields still satisfy the purple classifier below. Include
    # those same pixels in their contours, otherwise the five-icon locator
    # loses the entire header (including party count and identity).
    purple = (hue >= 125) & (hue <= 175) & (sat > 45) & (val > 160)
    ink = ((val < 155) | (sat > 65) | purple).astype(np.uint8)*255
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    glyphs = []
    for glyph in contours:
        x, y, w, h = cv2.boundingRect(glyph)
        if not 6 <= w <= 24 or not 5 <= h <= 24:
            continue
        pixels = roi[y:y+h, x:x+w]
        hue, sat, val = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        red = ((hue < 12) | (hue > 170)) & (sat > 100) & (val > 120)
        purple = (hue >= 125) & (hue <= 175) & (sat > 45) & (val > 160)
        glyphs.append({'bounds': [offset_x+x, offset_y+y, offset_x+x+w, offset_y+y+h],
                       'red_pixels': int(red.sum()), 'purple_pixels': int(purple.sum()),
                       'dark_pixels': int((val < 145).sum()), 'area': w*h})
    return sorted(glyphs, key=lambda g: g['bounds'][0])


def header_row_panels(rgb):
    """Locate a header from fresh five-icon geometry when clouds hide its edge.

    Color seeds only select a row. All five glyphs, their spacing, the pale
    background and actual name/CP pixels still need separate validation.
    """
    import cv2
    import numpy as np
    from creator_observations import glyph_row
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    output = []
    for x, right in [(0, 248), (260, 508)]:
        glyphs = glyph_features(hsv[45:240, x:right], x, 45)
        seeds = [g for g in glyphs if g['red_pixels'] >= 4 or g['purple_pixels'] >= 4]
        accepted = []
        for seed in seeds:
            cy = (seed['bounds'][1]+seed['bounds'][3])/2
            near = [g for g in glyphs if abs((g['bounds'][1]+g['bounds'][3])/2-cy) <= 7]
            row = glyph_row(dict(background_value_median=255, glyphs=near))
            if row is None:
                continue
            center = sum((g['bounds'][1]+g['bounds'][3])/2 for g in row)/5
            if any(abs(center-old) < 8 for old in accepted):
                continue
            top, bottom = max(45, round(center-45)), min(240, round(center+18))
            panel = hsv[top:bottom, x:right]
            pale = (panel[:, :, 1] < 105) & (panel[:, :, 2] > 150)
            if pale.mean() < .55:
                continue
            accepted.append(center)
            output.append(dict(bounds=[x, top, right, bottom], geometry_source='fresh_five_glyph_header_row',
                background_value_median=float(np.median(panel[:, :, 2][pale])),
                background_fraction=float(pale.mean()), glyphs=row))
    return output


def header_panels(rgb, anchors=()):
    """Describe header glyphs using physical panels or a fresh CP-text anchor.

    White cloud backgrounds can join the panel's pale component. A fresh,
    already-recorded CP bounding box then locates the row; icon positions are
    still measured rather than taken from a fixed screen-coordinate list.
    """
    import cv2
    import numpy as np
    hsv_full = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hsv = hsv_full[45:240]
    pale = ((hsv[:, :, 1] < 105) & (hsv[:, :, 2] > 150)).astype(np.uint8)*255
    pale = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    # Weather icons can touch a panel after closing and extend its component
    # above the actual rectangle. Preserve the broad panel while separating
    # narrow icon connections; fresh five-glyph geometry still has to pass.
    pale = cv2.morphologyEx(pale, cv2.MORPH_OPEN, np.ones((1, 31), np.uint8))
    contours, _ = cv2.findContours(pale, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 150 <= w <= 245 and 35 <= h <= 82:
            boxes.append((x, y+45, x+w, y+h+45, y+45+round(h*.5), 'pale_component'))
    for anchor in anchors:
        bounds = anchor['bounds']
        cy = (bounds[1]+bounds[3])/2
        x, right = (0, 248) if anchor['side'] == 'mine' else (260, 508)
        boxes.append((x, max(0, round(cy-14)), right, min(240, round(cy+44)),
                      max(0, round(cy+6)), 'fresh_cp_anchor'))
    result = []
    for x, y, right, bottom, glyph_y, method in boxes:
        panel = hsv_full[y:bottom, x:right]
        if not panel.size:
            continue
        background = (panel[:, :, 1] < 105) & (panel[:, :, 2] > 150)
        minimum = .35 if method == 'fresh_cp_anchor' else .55
        if float(background.mean()) < minimum:
            continue
        roi = hsv_full[glyph_y:bottom-2, x:right]
        glyphs = glyph_features(roi, x, glyph_y)
        result.append({'bounds': [x, y, right, bottom], 'geometry_source': method,
                       'background_fraction': round(float(background.mean()), 4),
                       'background_value_median': float(np.median(panel[:, :, 2][background])),
                       'glyphs': glyphs})
    # A cloud can merge one pale panel into a much larger component. Its mate
    # supplies a search band, while fresh background and glyph pixels still
    # determine whether the opposite header is actually present.
    for panel in list(result):
        if panel['geometry_source'] != 'pale_component':
            continue
        x,y,right,bottom = panel['bounds']
        x,right = rgb.shape[1]-right,rgb.shape[1]-x
        roi = hsv_full[y:bottom,x:right]
        if not roi.size:
            continue
        background = (roi[:,:,1] < 105) & (roi[:,:,2] > 150)
        if float(background.mean()) < .55:
            continue
        glyph_y = y+round((bottom-y)*.5)
        glyphs = glyph_features(hsv_full[glyph_y:bottom-2,x:right],x,glyph_y)
        if len(glyphs) < 5:
            continue
        result.append({'bounds':[x,y,right,bottom],
            'geometry_source':'opposite_panel_search_with_fresh_glyph_geometry',
            'background_fraction':round(float(background.mean()),4),
            'background_value_median':float(np.median(roi[:,:,2][background])), 'glyphs':glyphs})
    # Preserve already valid panel/CP geometry. Appending competing boxes to a
    # good header can make an otherwise readable text line ambiguous.
    from creator_observations import classify_headers
    baseline = classify_headers(result)
    if any(all(baseline[side][key]['value'] is None for key in ('party', 'shields'))
           for side in ('mine', 'theirs')):
        for panel in header_row_panels(rgb):
            side = 'mine' if panel['bounds'][0] == 0 else 'theirs'
            if all(baseline[side][key]['value'] is None for key in ('party', 'shields')):
                result.append(panel)
    return result


def scene_features(rgb):
    """Small color summaries for shield/occlusion evidence; no image storage."""
    import cv2
    import numpy as np
    area = cv2.cvtColor(rgb[250:950], cv2.COLOR_RGB2HSV)
    hue, sat, val = area[:, :, 0], area[:, :, 1], area[:, :, 2]
    purple = (hue >= 125) & (hue <= 175) & (sat > 65) & (val > 120)
    cells = []
    for row in np.array_split(purple, 5, axis=0):
        cells.append([round(float(cell.mean()), 4) for cell in np.array_split(row, 5, axis=1)])
    return {'purple_fraction': round(float(purple.mean()), 5), 'purple_grid': cells,
            'bright_fraction': round(float((val > 225).mean()), 5),
            'dark_fraction': round(float((val < 45).mean()), 5)}
