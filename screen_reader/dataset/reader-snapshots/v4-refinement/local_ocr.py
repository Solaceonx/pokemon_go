"""Optional local OCR with project-local runtime support on Windows."""
import os
from pathlib import Path
import sys
from button_reader import ROOT, cv2, np

_DLL_HANDLES = []
if os.name == "nt" and (ROOT / "tools/msvc-runtime").exists():
    for directory in [ROOT / "tools/msvc-runtime", ROOT / "tools/msvc-runtime/Scripts"]:
        _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
if (ROOT / "tools/ocr-runtime-120").exists():
    sys.path.insert(0, str(ROOT / "tools/ocr-runtime-120"))


def compact(text):
    return "".join(c for c in text.upper() if c.isalnum())


class LocalOCR:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1, use_cls=False)

    def read(self, rgb):
        result, _ = self.engine(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        records = []
        for polygon, text, confidence in result or []:
            if confidence < 0.75:
                continue
            points = np.asarray(polygon)
            records.append({"text": text, "confidence": round(float(confidence), 4),
                            "bounds": [round(float(points[:, 0].min())), round(float(points[:, 1].min())),
                                       round(float(points[:, 0].max())), round(float(points[:, 1].max()))]})
        return records
