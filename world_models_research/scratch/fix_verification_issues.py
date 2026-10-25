# -*- coding: utf-8 -*-
import os

BASE_DIR = r"e:\code\Crafter\world_models_research"

for filename in ["UNIFIED_BENCHMARK_LEADERBOARD.md", "BENCHMARK_MATRIX.md"]:
    path = os.path.join(BASE_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = content.replace("cgc_metrics.json", "cgc_saturation_metrics.json")
    new_content = new_content.replace("cgc_gluon_saturation_eval.png", "cgc_eval.png")
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"[Fixed] {filename} cgc links fixed.")

bfa_md = os.path.join(BASE_DIR, "experiments", "embodied_driving_sim", "BIONIC_FLAPPING_WING_WORLD_MODELS.md")
if os.path.exists(bfa_md):
    with open(bfa_md, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = content.replace(r"[\xi](t)", r"[\xi]\!(t)")
    if new_content != content:
        with open(bfa_md, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("[Fixed] BIONIC_FLAPPING_WING_WORLD_MODELS.md fake link fixed.")

for subdir in ["generative_physics_eval", "generative_physics_sim"]:
    py_path = os.path.join(BASE_DIR, "experiments", subdir, "cgc_gluon_saturation_wm.py")
    if os.path.exists(py_path):
        with open(py_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if r"\m" in line or r"\l" in line or r"\p" in line:
                line = line.replace(r"\mathbf", r"\\mathbf").replace(r"\frac", r"\\frac").replace(r"\ln", r"\\ln").replace(r"\pi", r"\\pi")
            new_lines.append(line)
        with open(py_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"[Fixed] {py_path} escapes fixed.")

print("[All Fixes Applied]")
