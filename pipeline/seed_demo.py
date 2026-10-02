"""Write synthetic tracks for every camera so the UI and verifier can be exercised
before real footage is assembled.

The tracks follow each camera's scripted scenario (see selftest.py scenes), shifted
to its ground-truth window. They are NOT detections. Once real footage exists, run
`python pipeline/run_all.py --redetect` to replace them with YOLO tracks.

    python pipeline/seed_demo.py && python pipeline/run_all.py
"""

from __future__ import annotations

import json

import selftest as S
from schema import load_config, tracks_path

SCENES = {
    "crowd_flow_anomaly": S.scene_surge,
    "restricted_zone_entry": S.scene_zone,
    "person_down_or_inactivity": S.scene_down,
    "possible_altercation": S.scene_argue,
}


def main() -> None:
    for cam in load_config()["cameras"]:
        gt = cam["groundTruth"]
        window = (gt["startSec"], gt["endSec"])
        scene = SCENES[gt["eventType"]]
        if gt["eventType"] == "restricted_zone_entry" and cam.get("restrictedPolygons"):
            poly = cam["restrictedPolygons"][0]
            inside_y = sum(p[1] for p in poly) / len(poly)
            inside_x = sum(p[0] for p in poly) / len(poly)

            def scene(t, window=window, ix=inside_x, iy=inside_y):
                yield from S.scene_calm(t)
                y = 0.8 if t < window[0] + 2 else iy
                yield 99, (ix, y - 0.08, 0.04, 0.16)

            data = S.frames_from(scene)
        else:
            data = S.frames_from(lambda t, f=scene, w=window: f(t, w))
        data["cameraId"] = cam["id"]
        data["synthetic"] = True
        tracks_path(cam["id"]).write_text(json.dumps(data))
        print(f"[seed_demo] {cam['id']}: synthetic {gt['eventType']} tracks at {window}")


if __name__ == "__main__":
    main()
