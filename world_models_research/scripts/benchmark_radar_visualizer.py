"""
World Models Benchmark Radar & Multi-Metric Visualizer
======================================================
Generates radar charts and multi-dimensional quantitative comparisons
for the 8 representative world models across 6 evaluation dimensions:
1. Physical & Spatial Consistency (物理时空因果一致性)
2. Long-Horizon Compounding Error Resistance (长程抗复合误差衰减)
3. Sample Efficiency (样本利用效率)
4. Inference Latency & Throughput (低推理时延与闭环吞吐)
5. Out-of-Distribution Generalization (域外泛化能力)
6. Action Controllability & Precision (闭环动作精确可控性)
"""

import os
import json
import numpy as np
import matplotlib.pyplot as plt

# Define the models and ratings from BENCHMARK_MATRIX.md (Scale: 1.0 to 5.0)
BENCHMARK_DATA = {
    "dimensions": [
        "Physical\nConsistency",
        "Compounding\nResistance",
        "Sample\nEfficiency",
        "Inference\nThroughput",
        "OOD\nGeneralization",
        "Action\nControllability"
    ],
    "models": {
        "World Models (2018)": [3.0, 2.0, 3.0, 4.5, 2.0, 4.0],
        "PlaNet (2019)":        [3.5, 3.0, 4.0, 2.0, 3.0, 4.0],
        "DreamerV3 (2023)":     [4.5, 4.0, 5.0, 5.0, 4.0, 5.0],
        "MuZero (2020)":        [2.0, 5.0, 5.0, 3.0, 2.5, 5.0],
        "V-JEPA (2024)":        [4.5, 4.0, 4.0, 4.5, 5.0, 2.5],
        "Sora (2024)":          [4.0, 3.5, 2.0, 1.0, 4.5, 2.0],
        "UniSim (2024)":        [4.5, 3.5, 3.5, 2.0, 4.0, 4.5],
        "GAIA-1 (2023)":        [4.5, 4.0, 3.0, 2.0, 4.0, 4.5]
    }
}

def plot_radar_comparison(data, output_path):
    categories = data["dimensions"]
    N = len(categories)
    
    # What will be the angle of each axis in the plot? (divide the plot / number of variable)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1] # Close the loop
    
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    
    # First axis on top:
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    
    # Draw one axe per variable + add labels
    plt.xticks(angles[:-1], categories, size=11, fontweight='bold')
    
    # Draw ylabels
    ax.set_rlabel_position(0)
    plt.yticks([1, 2, 3, 4, 5], ["1.0", "2.0", "3.0", "4.0", "5.0"], color="grey", size=9)
    plt.ylim(0, 5.5)
    
    # Select 4 representative archetypes to highlight for clean comparison
    highlight_models = {
        "DreamerV3": ("#1f77b4", "-"),        # RL Latent Imagination Champion
        "MuZero": ("#ff7f0e", "--"),          # Value-Equivalent Champion
        "V-JEPA": ("#2ca02c", "-."),          # Feature Space Predictive Champion
        "Sora (Video DiT)": ("#d62728", ":")  # Generative Physics Champion
    }
    
    for model_name, (color, linestyle) in highlight_models.items():
        # Find matching key
        key = [k for k in data["models"].keys() if model_name.split()[0] in k][0]
        values = data["models"][key]
        values_loop = values + values[:1]
        
        ax.plot(angles, values_loop, linewidth=2.5, linestyle=linestyle, label=key, color=color)
        ax.fill(angles, values_loop, color=color, alpha=0.1)
        
    plt.title("World Models Paradigm Archetype Radar Comparison", size=15, y=1.08, fontweight='bold')
    plt.legend(loc='upper right', bbox_to_anchor=(1.25, 1.1), fontsize=11)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"[+] Saved Radar Benchmark Chart to: {output_path}")

def print_summary_rankings(data):
    print("=" * 70)
    print(">>> World Models Quantitative Summary Ranking (Max Score: 30.0)")
    print("=" * 70)
    
    scores = []
    for model_name, ratings in data["models"].items():
        total_score = sum(ratings)
        avg_score = total_score / len(ratings)
        scores.append((model_name, total_score, avg_score))
        
    # Sort descending by total score
    scores.sort(key=lambda x: x[1], reverse=True)
    
    print(f"{'Rank':<5} | {'Model Name':<25} | {'Total Score':<12} | {'Average Rating':<14}")
    print("-" * 65)
    for rank, (name, total, avg) in enumerate(scores, 1):
        print(f"{rank:<5} | {name:<25} | {total:<12.1f} | {avg:<14.2f} / 5.0")
    print("=" * 70)

def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))
    chart_path = os.path.join(output_dir, "world_models_radar_benchmark.png")
    
    print_summary_rankings(BENCHMARK_DATA)
    plot_radar_comparison(BENCHMARK_DATA, chart_path)
    print("\n>>> Radar Visualization Completed Successfully! <<<")

if __name__ == "__main__":
    main()
