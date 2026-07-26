"""Scout tests: fetch (local), extract (heuristic + LLM hook), build, end-to-end."""
import os
import tempfile

from atlas.scout.fetch import html_to_text, fetch
from atlas.scout.extract import extract_rules, heuristic_extract
from atlas.scout.build import build_hypothesis
from atlas.scout import Scout
from atlas.research.fx.strategies.base import Strategy
import atlas.research.fx.strategies  # noqa: registers templates


def test_html_to_text_strips_markup():
    html = "<html><body><h1>ORB</h1><script>x=1</script><p>Trade the open.</p></body></html>"
    t = html_to_text(html)
    assert "ORB" in t and "Trade the open." in t and "x=1" not in t


def test_heuristic_extracts_orb_rules():
    text = ("This opening range breakout strategy uses the first 15-minute range. "
            "Go long above the range with a 20 EMA filter, target 1:2 risk reward, "
            "stop 1.5 ATR.")
    ex = heuristic_extract(text)
    assert ex["template"] == "orb"
    p = ex["params"]
    assert p.get("orb.range_minutes") == 15
    assert p.get("orb.ema") == 20
    assert p.get("risk.target_r") == 2
    assert p.get("risk.stop.atr_mult") == 1.5


def test_heuristic_detects_mean_reversion():
    text = "A mean reversion system: fade oversold RSI, revert to the 20 MA."
    ex = heuristic_extract(text)
    assert ex["template"] == "mean_reversion"
    assert ex["params"].get("meanrev.ma_period") == 20


def test_llm_extractor_hook_overrides():
    out = extract_rules("anything", extractor=lambda t: {"template": "breakout",
                        "params": {"breakout.channel": 55}})
    assert out["template"] == "breakout" and out["params"]["breakout.channel"] == 55


def test_build_hypothesis_is_valid_and_buildable():
    ex = {"template": "orb", "params": {"orb.range_minutes": 15, "orb.ema": 10}}
    cfg = build_hypothesis(ex, "scout_test", ["GBPUSD"])
    for key in ("name", "markets", "timeframes", "risk", "criteria", "data"):
        assert key in cfg
    assert cfg["orb"]["range_minutes"] == 15 and cfg["orb"]["ema"] == 10
    assert Strategy.create(cfg) is not None       # the engine can build it


def test_llm_sanitise_allowlists_and_coerces():
    from atlas.scout.llm import sanitise
    raw = {"template": "orb",
           "params": {"orb.range_minutes": "15 minutes",   # coerced -> 15
                      "orb.ema": 20,
                      "risk.target_r": 2.0,
                      "evil.injected": 999,                  # off-allowlist -> dropped
                      "orb.bogus": 5},                       # off-allowlist -> dropped
           "evidence": "first 15-min range, 20 ema, 1:2"}
    out = sanitise(raw)
    assert out["template"] == "orb"
    assert out["params"] == {"orb.range_minutes": 15, "orb.ema": 20,
                             "risk.target_r": 2.0}
    assert "evil.injected" not in out["params"]


def test_llm_sanitise_rejects_unknown_template():
    import pytest
    from atlas.scout.llm import sanitise
    with pytest.raises(ValueError):
        sanitise({"template": "martingale", "params": {}})


def test_llm_extractor_result_flows_through_build():
    # simulate what an LLM returns; verify the whole pipe builds a valid config
    from atlas.scout.llm import sanitise
    stub = lambda t: sanitise({"template": "mean_reversion",
                               "params": {"meanrev.ma_period": 30,
                                          "meanrev.entry_z": "2.5 sigma"},
                               "evidence": "fade 2.5 std from 30 MA"})
    out = extract_rules("some article prose", extractor=stub)
    assert out["template"] == "mean_reversion"
    cfg = build_hypothesis(out, "scout_llm_test", ["GBPUSD"])
    assert cfg["meanrev"]["ma_period"] == 30 and cfg["meanrev"]["entry_z"] == 2.5
    assert Strategy.create(cfg) is not None


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_discover_urls_from_message_merges_json_and_results():
    from atlas.scout.discover import urls_from_message
    msg = _Block(content=[
        _Block(type="text",
               text='Here you go: [{"url":"https://a.com/orb","title":"ORB"}]'),
        _Block(type="web_search_tool_result",
               content=[_Block(url="https://b.com/breakout", title="B"),
                        _Block(url="https://a.com/orb", title="dup")]),
    ])
    urls = urls_from_message(msg)
    assert urls[0] == "https://a.com/orb"          # model's JSON pick first
    assert "https://b.com/breakout" in urls
    assert urls.count("https://a.com/orb") == 1     # deduped


def test_discover_falls_back_to_bare_urls_in_prose():
    from atlas.scout.discover import urls_from_message
    msg = _Block(content=[_Block(type="text",
                 text="See https://x.com/strategy and http://y.com/rules.")])
    urls = urls_from_message(msg)
    assert "https://x.com/strategy" in urls and "http://y.com/rules" in urls


def test_is_fx_source_gate():
    from atlas.scout.discover import is_fx_source
    fx = ("This forex strategy trades GBP/USD and USD/JPY on the London session. "
          "Target 20 pips, stop 15 pips on the currency pair.")
    equity = ("A 0DTE SPY options strategy. Buy calls on the S&P 500 at the open; "
              "QQQ works too. Pure equity/ETF play, no forex here.")
    assert is_fx_source(fx) is True
    assert is_fx_source(equity) is False


def test_discover_fx_only_skips_offmarket(tmp_path):
    fxfile = tmp_path / "fx.html"
    fxfile.write_text("<html><body><p>Forex breakout on GBP/USD: buy the 40-day "
                      "channel high, 20 pip stop, currency pair intraday.</p></body></html>")
    spyfile = tmp_path / "spy.html"
    spyfile.write_text("<html><body><p>0DTE SPY options: buy S&P 500 calls on the "
                       "opening range breakout. QQQ equity play.</p></body></html>")
    stub = lambda q, n: [str(spyfile), str(fxfile)]
    out = Scout().discover("breakout", root=str(tmp_path), markets=["GBPUSD"],
                           max_results=5, test=False, fx_only=True, searcher=stub)
    assert len(out["results"]) == 1                       # only the forex one scouted
    assert out["results"][0]["template"] == "breakout"
    assert len(out["skipped"]) == 1 and out["skipped"][0]["url"] == str(spyfile)


def test_discover_all_markets_keeps_offmarket(tmp_path):
    spyfile = tmp_path / "spy.html"
    spyfile.write_text("<html><body><p>0DTE SPY options: opening range breakout on "
                       "the S&P 500, buy calls, QQQ equity.</p></body></html>")
    stub = lambda q, n: [str(spyfile)]
    out = Scout().discover("orb", root=str(tmp_path), markets=["GBPUSD"],
                           max_results=5, test=False, fx_only=False, searcher=stub)
    assert len(out["results"]) == 1 and out["skipped"] == []   # gate off -> kept


def test_scout_discover_pipeline_with_stub_searcher(tmp_path):
    # write two local "articles"; the stub searcher returns their paths as if URLs
    a = tmp_path / "orb.html"
    a.write_text("<html><body><p>Opening range breakout: first 15-min range, "
                 "20 EMA filter, 1:2 target.</p></body></html>")
    b = tmp_path / "chan.html"
    b.write_text("<html><body><p>Buy the 40-day channel breakout, 2 ATR stop.</p>"
                 "</body></html>")
    stub = lambda q, n: [str(a), str(b)][:n]
    out = Scout().discover("breakouts", root=str(tmp_path), markets=["GBPUSD"],
                           max_results=2, test=False, fx_only=False, searcher=stub)
    assert out["query"] == "breakouts"
    templates = sorted(r["template"] for r in out["results"])
    assert templates == ["breakout", "orb"]
    assert out["errors"] == []
    for r in out["results"]:
        cfg = __import__("atlas.research.fx.config", fromlist=["load"]).load(r["path"])
        assert Strategy.create(cfg) is not None


def test_scout_discover_captures_bad_sources(tmp_path):
    good = tmp_path / "ok.html"
    good.write_text("<html><body><p>Donchian 20-day breakout, 1:2 target.</p></body></html>")
    baddir = tmp_path / "a_directory"           # exists but can't be read as a file
    baddir.mkdir()
    stub = lambda q, n: [str(baddir), str(good)]
    out = Scout().discover("x", root=str(tmp_path), markets=["GBPUSD"],
                           max_results=5, test=False, fx_only=False, searcher=stub)
    # the bad source is captured as an error; the good one still scouts — the
    # sweep never crashes on one dead source
    assert len(out["results"]) == 1 and out["results"][0]["template"] == "breakout"
    assert len(out["errors"]) == 1 and out["errors"][0]["url"] == str(baddir)


def test_scout_end_to_end_from_file_no_network():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "article.html")
        with open(src, "w") as f:
            f.write("<html><body><h1>Donchian breakout</h1>"
                    "<p>Buy the 40-day high breakout, 2 ATR stop, 1:3 target.</p>"
                    "</body></html>")
        info = Scout().scout(src, root=d, markets=["GBPUSD"])
        assert info["template"] == "breakout"
        assert os.path.exists(info["path"])         # hypothesis YAML written
        # a knowledge note was stored
        from atlas.memory import MemoryStore
        store = MemoryStore(d)
        assert len(store.list_knowledge()) == 1
        store.close()
        # the written hypothesis loads + builds
        from atlas.research.fx.config import load
        cfg = load(info["path"])
        assert Strategy.create(cfg) is not None
