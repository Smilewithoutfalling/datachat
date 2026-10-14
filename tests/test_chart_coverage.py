"""scripts/chart_coverage.py 的判定规则（[23]）。"""
import importlib.util
import os

_p = os.path.join(os.path.dirname(__file__), "..", "scripts", "chart_coverage.py")
_spec = importlib.util.spec_from_file_location("chart_coverage", _p)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def _v(code):
    k, s = cc.classify(code)
    return cc.verdict({"kinds": sorted(k), "struct": sorted(s)})


def test_three_spellings_recognized():
    assert _v("plt.bar(x, y)\nplt.savefig(chart_path)") == "covered"
    assert _v("ax.bar(x, y)\nplt.savefig(chart_path)") == "covered"
    assert _v("s.plot(kind='bar')\nplt.savefig(chart_path)") == "covered"
    assert _v("s.plot.bar()\nplt.savefig(chart_path)") == "covered"
    assert _v("s.plot()\nplt.savefig(chart_path)") == "covered"          # pandas 默认折线


def test_mixed_split_into_three():
    two_figs = "plt.figure()\ns.plot(kind='pie')\nplt.close()\nplt.figure()\nplt.bar(a, b)\nplt.savefig(chart_path)"
    assert _v(two_figs) == "multi_figure"
    markers = "ax.plot(m.index, m.values)\nax.scatter([m.idxmax()], [m.max()], color='red')\nplt.savefig(chart_path)"
    assert _v(markers) == "degraded"
    trend = "ax.scatter(df['p'], df['u'])\nax.plot(xs, ys, '--')\nplt.savefig(chart_path)"
    assert _v(trend) == "overlay"


def test_uncovered():
    assert _v("plt.hist(df['a'])\nplt.savefig(chart_path)") == "uncovered_kind"
    assert _v("ax.bar(a, b)\nax2 = ax.twinx()\nax2.plot(a, c)\nplt.savefig(chart_path)") == "uncovered_layout"
