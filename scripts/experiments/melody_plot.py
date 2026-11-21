"""Plot the frozen note metrics on recordings evaluated by both models. Requires matplotlib."""

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
from matplotlib.patches import Rectangle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    paths = ["melodia-some.csv", "melodia-rosvot.csv", "melodia-cambios-letra.csv"]
    metrics = {}
    for name in paths:
        with (args.results / name).open(encoding="utf-8") as source:
            for row in csv.DictReader(source):
                metrics[row["id"], row["acoustic_model"], row["variant"]] = row
    ids = sorted({tag for tag, _, _ in metrics if (tag, "rosvot", "consensus") in metrics})
    panels = [
        ("some", "baseline", "GAME de partida"),
        ("some", "pitch", "SOME · altura"),
        ("some", "events", "SOME · eventos"),
        ("rosvot", "consensus", "Consenso de alturas"),
        ("rosvot", "pitch", "ROSVOT · altura"),
        ("rosvot", "events", "ROSVOT · eventos"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.5), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.08, right=0.97, bottom=0.18, top=0.81, hspace=0.37, wspace=0.15)
    fig.text(
        0.08,
        0.94,
        "Altura y ataques que coinciden con la edición humana",
        fontsize=17,
        weight="bold",
    )
    fig.text(
        0.08,
        0.89,
        f"{len(ids)} grabaciones compartidas por método · textos corregidos en los dos casos de desarrollo",
        fontsize=10,
    )
    for ax, (family, method, title) in zip(axes.flat, panels, strict=True):
        ax.set_title(title, fontsize=11, loc="left", weight="bold")
        ax.set_axisbelow(True)
        ax.grid(color="#e2e6e8", linewidth=0.7)
        ax.add_patch(Rectangle((0.85, 0.9), 0.15, 0.1, color="#d8efe2", zorder=0))
        for tag in ids:
            r = metrics[tag, family, method]
            good_text = float(r["wer"]) <= 0.05 and float(r["word_p90_s"]) <= 0.12
            passed = r["passes_all"] == "True"
            color = "#14744c" if passed else "#134f78" if good_text else "#909aa1"
            ax.scatter(
                float(r["onset_pitch_f1_100ms"]),
                float(r["correct_class_all"]),
                s=84 if passed else 21,
                marker="*" if passed else "o",
                edgecolor=color,
                facecolor=color if good_text else "none",
                linewidth=0.85,
                alpha=1 if passed else 0.84,
                zorder=4 if passed else 2,
            )
        ax.set(xlim=(0.05, 1), ylim=(0.15, 1))
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.tick_params(labelsize=8)
    fig.text(0.51, 0.11, "F1 de ataques con clase correcta (±100 ms)", ha="center", fontsize=10)
    fig.text(0.02, 0.48, "Fotogramas con clase correcta", rotation=90, va="center", fontsize=10)
    legend = [
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            markerfacecolor="none",
            markeredgecolor="#909aa1",
            label="Letra o sincronía fuera de umbral",
        ),
        Line2D(
            [], [], ls="", marker="o", color="#134f78", label="Letra y sincronía dentro de umbral"
        ),
        Line2D(
            [],
            [],
            ls="",
            marker="*",
            markersize=11,
            color="#14744c",
            label="Cumple los cuatro criterios",
        ),
    ]
    fig.legend(
        handles=legend,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.015),
        ncol=3,
        frameon=False,
        fontsize=9,
    )
    fig.savefig(args.output, dpi=160, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
