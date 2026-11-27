"""Run V1/V2/V3 experiments, export summary tables and 4-panel dashboard."""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from .models import MicroLendingV1, MicroLendingV2, MicroLendingV3


def run_all(seed=42, months=60):
    models = {
        "V1": MicroLendingV1(seed=seed),
        "V2": MicroLendingV2(seed=seed),
        "V3": MicroLendingV3(seed=seed),
    }
    results = {}
    for name, model in models.items():
        df = model.run(months).reset_index(drop=True)
        df["version"] = name
        results[name] = df
    return results


def make_dashboard(results, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    colors = {"V1": "#b23a48", "V2": "#2878b5", "V3": "#27856a"}

    # 1. TVL
    ax = axes[0, 0]
    for name, df in results.items():
        ax.plot(df["month"], df["TVL"], label=name, linewidth=2, color=colors[name])
    ax.axvspan(30, 35, color="grey", alpha=0.15, label="Macro shock")
    ax.set(title="1. Total Value Locked (TVL)", xlabel="Month", ylabel="Million VND")
    ax.legend()
    ax.grid(alpha=.25)

    # 2. Cumulative NPL
    ax = axes[0, 1]
    for name, df in results.items():
        ax.plot(df["month"], df["NPL"] * 100, label=name, linewidth=2, color=colors[name])
    ax.axvspan(30, 35, color="grey", alpha=0.15)
    ax.set(title="2. Cumulative NPL rate", xlabel="Month", ylabel="NPL (%)")
    ax.legend()
    ax.grid(alpha=.25)

    # 3. Empirical kink curve at a representative score
    ax = axes[1, 0]
    util = np.linspace(0, 1, 201)
    score = 50
    opt = 0.80
    borrow = np.where(util <= opt, .10 + (util / opt) * .12 - .0005 * score,
                      .10 + .12 + ((util - opt) / (1-opt)) * .80 - .0005 * score)
    borrow = np.maximum(.01, borrow)
    supply = borrow * util * .90
    ax.plot(util * 100, borrow * 100, label="Borrow APR", linewidth=2)
    ax.plot(util * 100, supply * 100, label="Supply APR", linewidth=2)
    ax.axvline(80, linestyle="--", color="black", alpha=.7, label="Uopt = 80%")
    ax.set(title="3. Kinked interest-rate curve (score = 50)", xlabel="Utilization (%)", ylabel="Annual rate (%)")
    ax.legend()
    ax.grid(alpha=.25)

    # 4. V3 borrower cost vs requested informal-credit comparison band
    ax = axes[1, 1]
    v3 = results["V3"]
    ax.plot(v3["month"], v3["borrow_apr"] * 100, label="V3 protocol APR", color=colors["V3"], linewidth=2)
    ax.axhspan(180, 360, color="#b23a48", alpha=.16, label="Informal-loan comparison band (assumption)")
    ax.set(title="4. Borrowing cost comparison", xlabel="Month", ylabel="Annual rate (%)")
    ax.legend()
    ax.grid(alpha=.25)

    fig.suptitle("Vietnam P2P Micro-Lending: V1 vs V2 vs V3", fontsize=16, fontweight="bold")
    fig.tight_layout()
    fig.savefig(output_dir / "comparison_dashboard.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = run_all(seed=42, months=60)
    combined = pd.concat(results.values(), ignore_index=True)
    combined.to_csv(output_dir / "monthly_results.csv", index=False)

    summary = []
    for name, df in results.items():
        summary.append({
            "Version": name,
            "Final_TVL_million_VND": df["TVL"].iloc[-1],
            "Final_NPL_percent": df["NPL"].iloc[-1] * 100,
            "Total_disbursed_million_VND": df["cumulative_disbursed"].iloc[-1],
            "Defaulted_principal_million_VND": df["defaulted_principal"].iloc[-1],
            "Cumulative_losses_million_VND": df["losses"].iloc[-1],
            "Final_utilization_percent": df["utilization"].iloc[-1] * 100,
        })
        summary_df = pd.DataFrame(summary)
        summary_df.to_csv(output_dir / "summary.csv", index=False)
    print("\n=== SUMMARY: all monetary values in million VND ===")
    print(summary_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    make_dashboard(results, output_dir)
    print(f"\nSaved outputs to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
