"""Measure visible HP-bar pixels; never translate them into unverified integer HP."""
from button_reader import cv2, np


def outlined_rectangles(crop, expected_width):
    """Find the two pale horizontal rails, rather than the colored fill contour."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    pale = (((hsv[:, :, 1] < 90) & (hsv[:, :, 2] > 185)) |
            ((hsv[:, :, 0] <= 38) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 160))).astype(np.uint8)*255
    pale = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8))
    rail_kernel = expected_width-8
    rail_kernel += 1-rail_kernel % 2
    rails = cv2.morphologyEx(pale, cv2.MORPH_OPEN, np.ones((1, rail_kernel), np.uint8))
    contours, _ = cv2.findContours(rails, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    lines = [cv2.boundingRect(c) for c in contours]
    lines = [r for r in lines if r[2] >= expected_width-8 and r[3] <= 4]
    rectangles = []
    for x, y, w, h in lines:
        for bx, by, bw, bh in lines:
            if 7 <= by-y <= 17 and abs((x+w)-(bx+bw)) <= 3:
                # A battlefield line often joins the left rail. Anchor its right
                # end and use calibrated full width instead of truncating HP.
                right=round(((x+w)+(bx+bw))/2)
                left=right-expected_width
                rectangles.append((left, y, right-left, by+bh-y, "paired_outline"))
    return rectangles


def read_health_bar(rgb, region, expected_width=144):
    x0, y0, x1, y1 = region
    crop = rgb[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    outline = cv2.Canny(gray, 35, 90)
    contours, _ = cv2.findContours(outline, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    rectangles = outlined_rectangles(crop, expected_width)
    rectangles.extend((*cv2.boundingRect(contour), "edge_contour") for contour in contours)
    for x, y, w, h, method in rectangles:
        if abs(w-expected_width) > 10 or not 7 <= h <= 19:
            continue
        if x < 0 or y < 0 or x+w > crop.shape[1] or y+h > crop.shape[0]:
            continue
        if method == "edge_contour" and abs(w-6-(expected_width-6)) > 5:
            continue
        area = crop[y+3:y+h-3, x+3:x+w-3]
        if not area.size:
            continue
        hsv = cv2.cvtColor(area, cv2.COLOR_RGB2HSV)
        # Filled areas are cyan, yellow/orange or red. Tail areas are dark.
        cyan = (hsv[:, :, 0] >= 65) & (hsv[:, :, 0] <= 105)
        warm = (hsv[:, :, 0] <= 40) | (hsv[:, :, 0] >= 170)
        saturated = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 90)
        # Empty bars are translucent: a red Pokemon behind the tail can leave
        # dark, saturated red pixels. Warm HP fill itself is bright.
        colored = saturated & (cyan | (warm & (hsv[:, :, 2] > 140)))
        dark = hsv[:, :, 2] < 120
        # Require a bar-like interior, not a white battlefield line or sky edge.
        interior_support = float((colored | dark).mean())
        if interior_support < 0.85 or float(dark.mean()) < 0.02:
            if float(colored.mean()) < 0.90:
                continue
        column_fill = colored.mean(axis=0) >= 0.5
        colored_indexes = np.flatnonzero(column_fill)
        leading = int(colored_indexes[0]) if len(colored_indexes) else 0
        if leading > 3:
            continue
        # A bar fills from the left; isolated particles in the tail are not HP.
        stop = len(column_fill)
        for index in range(leading, len(column_fill)-1):
            if not column_fill[index] and not column_fill[index+1]:
                stop = index
                break
        if stop > 0 and not column_fill[:min(stop, 3)].any():
            continue
        if column_fill[min(stop+2, len(column_fill)):].sum() > 3:
            # An occluding flash/hole is not a loss of all HP to its right.
            continue
        border_pixels = np.concatenate([crop[y, x:x+w], crop[y+h-1, x:x+w]])
        border_light = float((border_pixels.max(axis=1) > 135).mean())
        if border_light < 0.35:
            continue
        width = len(column_fill)
        # A complete contour locates the edge more precisely. Paired rails are
        # a fallback when fill/background fragments prevent a closed contour.
        score = interior_support + border_light - abs(w-expected_width)/40 - (0.15 if method == "paired_outline" else 0)
        # Report differently colored segments instead of deciding whether orange/red
        # animation segments represent already applied or pending damage.
        labels = []
        for index in range(stop):
            values = hsv[:, index]
            hue = float(np.median(values[:, 0]))
            labels.append("cyan" if 65 <= hue <= 105 else ("red" if hue < 12 or hue >= 170 else "yellow_or_orange"))
        segments = []
        for label in labels:
            if not segments or segments[-1]["color"] != label:
                segments.append({"color": label, "pixels": 1})
            else:
                segments[-1]["pixels"] += 1
        candidates.append((score, {"fraction": round(stop/width, 5), "filled_pixels": stop,
                                   "interior_width_pixels": width,
                                   "pixel_resolution_fraction": round(1/width, 5),
                                   "bounds": [x+x0, y+y0, x+x0+w, y+y0+h],
                                   "segments": segments,
                                   "pending_damage_interpretation": "unknown",
                                   "outline_method": method,
                                   "measurement": "visible_colored_extent"}))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def read_card_health(rgb, bounds):
    x0, y0, x1, y1 = map(int, bounds)
    area = rgb[max(y0, y1-18):y1-3, x0+8:x1-8]
    if area.size == 0:
        return None
    hsv = cv2.cvtColor(area, cv2.COLOR_RGB2HSV)
    colored = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 95)
    rows = colored.sum(axis=1)
    row = int(rows.argmax())
    indexes = np.flatnonzero(colored[row])
    if len(indexes) < 2:
        return None
    # Require the fill to begin at the left end of the known card bar region.
    if indexes[0] > 6:
        return None
    return {"fraction": round((indexes[-1]+1)/area.shape[1], 4),
            "pixel_resolution_fraction": round(1/area.shape[1], 4),
            "status": "provisional", "method": "card_bottom_color_extent"}
