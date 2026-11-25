"""Figure export: PNG (>= 300 dpi), SVG, PDF and interactive HTML.

Primary path: Plotly + Kaleido (needs a Chrome/Chromium installation on the PC; Kaleido
>= 1.0 can download one with ``plotly_get_chrome``). If Kaleido is not usable, a built-in
Matplotlib fallback re-draws the figure (scatter, bar, histogram, heatmap traces; titles
and axis labels are kept) so that static export always works offline.
"""
from __future__ import annotations

import io

import numpy as np
import plotly.graph_objects as go

DPI = 300
WIDTH_IN = 7.0  # typical text width of a thesis page


def _set_png_dpi(png: bytes, dpi: int = DPI) -> bytes:
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(png))
        out = io.BytesIO()
        im.save(out, format="PNG", dpi=(dpi, dpi))
        return out.getvalue()
    except Exception:  # pragma: no cover
        return png


def to_html(fig: go.Figure) -> bytes:
    return fig.to_html(include_plotlyjs=True, full_html=True).encode("utf-8")


def export_figure(fig: go.Figure, fmt: str, width_in: float = WIDTH_IN, dpi: int = DPI) -> tuple[bytes, str]:
    """Return (bytes, engine) for fmt in png|svg|pdf|html."""
    fmt = fmt.lower()
    if fmt == "html":
        return to_html(fig), "plotly"
    height_px = fig.layout.height or 450
    width_px = int(width_in * 100)
    try:
        data = fig.to_image(format=fmt, width=width_px, height=height_px, scale=dpi / 100 if fmt == "png" else 1)
        if fmt == "png":
            data = _set_png_dpi(data, dpi)
        return data, "kaleido"
    except Exception:
        return mpl_export(fig, fmt, width_in, height_px / 100, dpi), "matplotlib-fallback"


def mpl_export(fig: go.Figure, fmt: str, width_in: float, height_in: float, dpi: int = DPI) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f, ax = plt.subplots(figsize=(width_in, height_in))
    for tr in fig.data:
        name = tr.name if getattr(tr, "showlegend", True) is not False else None
        color = None
        if tr.type == "scatter":
            if tr.x is None or (len(tr.x) and tr.x[0] is None):
                continue
            mode = tr.mode or "lines"
            line_color = tr.line.color if tr.line and isinstance(tr.line.color, str) else None
            m_color = tr.marker.color if tr.marker and isinstance(tr.marker.color, str) else None
            color = line_color or m_color
            if isinstance(color, str) and color.startswith("rgb("):
                color = tuple(int(c) / 255 for c in color[4:-1].split(","))
            ls = "--" if tr.line and tr.line.dash in ("dash", "dot") else "-"
            if "lines" in mode:
                ax.plot(tr.x, tr.y, ls, color=color, lw=1.5, label=name,
                        marker="o" if "markers" in mode else None, ms=4)
            elif "markers" in mode:
                ax.scatter(tr.x, tr.y, color=color or "C0", s=25, label=name, zorder=3)
        elif tr.type == "bar":
            cols = tr.marker.color if tr.marker is not None else None
            if tr.orientation == "h":
                ax.barh([str(v) for v in tr.y], tr.x, color=cols, label=name)
                ax.invert_yaxis()
            else:
                ax.bar([str(v) for v in tr.x], tr.y, color=cols, label=name)
        elif tr.type == "histogram":
            ax.hist(tr.x, bins=30, color="#257de0", edgecolor="white")
        elif tr.type == "heatmap":
            z = np.asarray(tr.z, float)
            m = ax.pcolormesh(np.asarray(tr.x, float), np.asarray(tr.y, float), z, shading="auto", cmap="Blues")
            f.colorbar(m, ax=ax)
    title = fig.layout.title.text if fig.layout.title and fig.layout.title.text else ""
    ax.set_title(title, fontsize=10, loc="left")
    xa, ya = fig.layout.xaxis, fig.layout.yaxis
    ax.set_xlabel(xa.title.text if xa and xa.title and xa.title.text else "")
    ax.set_ylabel(ya.title.text if ya and ya.title and ya.title.text else "")
    if xa and xa.type == "log":
        ax.set_xscale("log")
    if ya and ya.type == "log":
        ax.set_yscale("log")
    ax.grid(axis="y", color="#e6e6e6")
    ax.spines[["top", "right"]].set_visible(False)
    if any(t.name for t in fig.data if getattr(t, "showlegend", None) is not False and t.type in ("scatter",)):
        handles, labels = ax.get_legend_handles_labels()
        if labels:
            ax.legend(frameon=False, fontsize=8)
    f.tight_layout()
    buf = io.BytesIO()
    f.savefig(buf, format=fmt, dpi=dpi)
    plt.close(f)
    return buf.getvalue()
