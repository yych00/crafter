import json
import os

path = os.path.join(os.path.dirname(__file__), "embodied_safety_metrics.json")
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"{'Scenario ID':36s} | {'Branch':18s} | {'P_fail':6s} | {'TTC(s)':6s} | {'Clear(m)':8s} | {'DriftVar':8s} | {'Sim2Real':8s}")
print("-" * 105)
for sc_id, sc in data["scenarios"].items():
    for b_name, b_data in sc["branches"].items():
        pf = b_data.get("collision_probability", 0.0)
        ttc = b_data.get("min_ttc_sec", 0.0)
        clear = b_data.get("min_clearance_m", 0.0)
        drift = b_data.get("kinematic_drift_variance", 0.0)
        s2r = b_data.get("sim2real_confidence", 0.0)
        print(f"{sc_id:36s} | {b_name:18s} | {pf:6.3f} | {ttc:6.2f} | {clear:8.2f} | {drift:8.3f} | {s2r:8.3f}")
