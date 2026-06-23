"""Render a data chart (bar/line/pie) as a PNG, styled from brand/theme.json.

Usage:
    python tools/generate_chart.py --data '{"type":"bar","title":"...","labels":["A","B"],"values":[1,2],"xlabel":"...","ylabel":"..."}' --out .tmp/chart1.png

Prints JSON: {"path": "<out path>"}
"""
import argparse
import json
import os

from _common import load_theme, emit, fail


def build_chart(spec, theme, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = theme["colors"]
    accent_cycle = [colors["gold"], colors["nile_teal"], colors["scarab_red"], colors["sterling_silver"]]

    plt.rcParams["font.family"] = "sans-serif"  # brand body font may not be installed locally; safe fallback

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    fig.patch.set_facecolor(colors["navy"])
    ax.set_facecolor(colors["navy"])

    chart_type = spec.get("type", "bar")
    labels = spec["labels"]
    values = spec["values"]

    if chart_type == "bar":
        bars = ax.bar(labels, values, color=[accent_cycle[i % len(accent_cycle)] for i in range(len(values))])
    elif chart_type == "line":
        ax.plot(labels, values, color=colors["gold"], marker="o", linewidth=2)
    elif chart_type == "pie":
        ax.pie(
            values,
            labels=labels,
            colors=[accent_cycle[i % len(accent_cycle)] for i in range(len(values))],
            textprops={"color": colors["text_on_dark"]},
            autopct="%1.0f%%",
        )
    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")

    if chart_type != "pie":
        ax.set_title(spec.get("title", ""), color=colors["text_on_dark"], fontsize=14, fontweight="bold")
        ax.set_xlabel(spec.get("xlabel", ""), color=colors["text_on_dark"])
        ax.set_ylabel(spec.get("ylabel", ""), color=colors["text_on_dark"])
        ax.tick_params(colors=colors["text_on_dark"])
        for spine in ax.spines.values():
            spine.set_color(colors["gold_dark"])
    else:
        ax.set_title(spec.get("title", ""), color=colors["text_on_dark"], fontsize=14, fontweight="bold")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, facecolor=colors["navy"], bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="JSON spec: type/title/labels/values/xlabel/ylabel")
    parser.add_argument("--out", required=True, help="Output PNG path, e.g. .tmp/chart1.png")
    args = parser.parse_args()

    try:
        spec = json.loads(args.data)
    except json.JSONDecodeError as e:
        fail(f"Invalid --data JSON: {e}")
        return

    theme = load_theme()

    try:
        build_chart(spec, theme, args.out)
    except Exception as e:
        fail(f"Chart generation failed: {e}")
        return

    emit({"path": args.out})


if __name__ == "__main__":
    main()
