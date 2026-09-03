"""Build the standalone illustrated HTML report from the authoritative Markdown."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
DEFAULT_SOURCE = REPORTS / "DETAILED_EXPERIMENT_REPORT.md"
DEFAULT_OUTPUT = REPORTS / "DETAILED_EXPERIMENT_REPORT.html"


def inline(text: str) -> str:
    value = html.escape(text, quote=False)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\[([^]]+)]\(([^)]+)\)", r'<a href="\2">\1</a>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
    return value


def cells(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def markdown_to_html(source: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = source.splitlines()
    output: list[str] = []
    headings: list[tuple[int, str, str]] = []
    heading_count = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = re.match(r"^```([^`]*)$", line)
        if fence:
            language = fence.group(1).strip()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            output.append(f'<pre><code class="language-{html.escape(language)}">{html.escape(chr(10).join(code))}</code></pre>')
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            heading_count += 1
            anchor = "report-title" if level == 1 else f"section-{heading_count:02d}"
            headings.append((level, re.sub(r"[*`]", "", title), anchor))
            output.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
            index += 1
            continue

        if line.strip() == "---":
            output.append("<hr>")
            index += 1
            continue

        image = re.match(r"^!\[([^]]*)]\(([^)]+)\)$", line)
        if image:
            alt, path = image.groups()
            caption = alt
            consumed = 1
            if index + 2 < len(lines) and not lines[index + 1].strip() and lines[index + 2].startswith("> "):
                caption = lines[index + 2][2:]
                consumed = 3
            number = re.search(r"図(\d+)", caption)
            figure_id = f' id="figure-{number.group(1)}"' if number else ""
            output.append(
                f'<figure{figure_id}><a href="{html.escape(path, quote=True)}" target="_blank" rel="noopener">'
                f'<img src="{html.escape(path, quote=True)}" alt="{html.escape(alt, quote=True)}" loading="lazy"></a>'
                f'<figcaption>{inline(caption)}</figcaption></figure>'
            )
            index += consumed
            continue

        if line.startswith("> "):
            quotes: list[str] = []
            while index < len(lines) and lines[index].startswith("> "):
                quotes.append(lines[index][2:])
                index += 1
            output.append(f'<blockquote>{"<br>".join(inline(item) for item in quotes)}</blockquote>')
            continue

        if line.startswith("|") and index + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[index + 1]):
            header = cells(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(cells(lines[index]))
                index += 1
            head = "".join(f"<th scope=\"col\">{inline(item)}</th>" for item in header)
            body = "".join("<tr>" + "".join(f"<td>{inline(item)}</td>" for item in row) + "</tr>" for row in rows)
            output.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            continue

        unordered = re.match(r"^(\s*)-\s+(.+)$", line)
        if unordered:
            items: list[tuple[int, str]] = []
            while index < len(lines):
                match = re.match(r"^(\s*)-\s+(.+)$", lines[index])
                if not match:
                    break
                items.append((len(match.group(1)) // 2, match.group(2)))
                index += 1
            output.append('<ul class="report-list">' + "".join(f'<li class="depth-{depth}">{inline(item)}</li>' for depth, item in items) + "</ul>")
            continue

        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        if ordered:
            items: list[str] = []
            while index < len(lines):
                match = re.match(r"^\d+\.\s+(.+)$", lines[index])
                if not match:
                    break
                items.append(match.group(1))
                index += 1
            output.append("<ol>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ol>")
            continue

        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(
            r"^(#{1,3})\s+|^```|^---$|^!\[|^> |^\||^\s*-\s+|^\d+\.\s+", lines[index]
        ):
            paragraph.append(lines[index].strip())
            index += 1
        output.append(f'<p>{inline(" ".join(paragraph))}</p>')
    return "\n".join(output), headings


def navigation(headings: list[tuple[int, str, str]]) -> str:
    links = []
    for level, title, anchor in headings:
        if level == 1:
            continue
        links.append(f'<a class="toc-level-{level}" href="#{anchor}">{html.escape(title)}</a>')
    links.append('<a class="toc-level-2" href="#video-players">動画プレイヤー</a>')
    return "\n".join(links)


def video_gallery(report_dir: Path) -> str:
    manifest = json.loads((report_dir / "videos" / "manifest.json").read_text(encoding="utf-8"))
    descriptions = {
        "01_self_physics_speed.mp4": ("Self物理条件", "slow・medium・fastを同じ姿勢と接触部位で比較"),
        "02_other_observation_four_conditions.mp4": ("Other観察4条件", "matched条件と二つの主要不一致条件を同時表示"),
        "03_self_other_mismatch_pairs.mp4": ("Self/Other不一致ペア", "同じevent seedに対するSelf参照とOther actual"),
        "04_protection_decision_replay.mp4": ("Stage 8保護判断", "高Otherを過小評価して非介入となった負の結果"),
    }
    cards = []
    for item in manifest["videos"]:
        title, description = descriptions[item["file"]]
        source_count = len(item["sources"])
        cards.append(
            f'<article class="video-card"><div class="video-heading"><div><h3>{title}</h3><p>{description}</p></div>'
            f'<span>{item["duration_s"]:.1f} s / {item["size"][0]}×{item["size"][1]}</span></div>'
            f'<video controls preload="metadata"><source src="videos/{item["file"]}" type="video/mp4">'
            f'<a href="videos/{item["file"]}">{item["file"]}</a></video>'
            f'<p class="file-ref"><strong>動画ファイル名:</strong> <a href="videos/{item["file"]}">{item["file"]}</a>'
            f' <span>／同期元 {source_count}エピソード</span></p></article>'
        )
    return '<section class="video-section" id="video-players"><h2>シミュレーション動画プレイヤー</h2><p>保存済みのPyCub左眼RGBと物理ログを同期した実験replayである。元の2秒を0.5倍速の4秒で表示する。</p><div class="video-grid">' + "".join(cards) + "</div></section>"


STYLE = r"""
:root { color-scheme: light; --ink:#17212b; --muted:#5d6a75; --paper:#fff; --wash:#f3f6f7; --navy:#123047; --teal:#007f78; --orange:#d67818; --red:#b83b3b; --line:#d8e0e3; --shadow:0 12px 38px rgba(18,48,71,.09); }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; color:var(--ink); background:var(--wash); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif; line-height:1.76; }
a { color:#0069a6; text-underline-offset:3px; }
.hero { background:linear-gradient(125deg,#102b3f 0%,#17455b 56%,#08756f 100%); color:#fff; padding:64px max(24px,calc((100vw - 1320px)/2)); }
.hero .eyebrow { margin:0 0 10px; color:#8ee4d6; font-size:.82rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
.hero h1 { max-width:1000px; margin:0; font-size:clamp(2rem,4vw,4rem); line-height:1.08; letter-spacing:-.035em; }
.hero .lead { max-width:940px; margin:22px 0 0; color:#dcecf0; font-size:1.08rem; }
.metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; max-width:1100px; margin-top:30px; }
.metric { padding:16px 18px; border:1px solid rgba(255,255,255,.18); background:rgba(255,255,255,.08); }
.metric strong { display:block; color:#fff; font-size:1.55rem; line-height:1.2; }.metric span { color:#cbe0e5; font-size:.83rem; }
.layout { display:grid; grid-template-columns:280px minmax(0,1040px); gap:44px; max-width:1400px; margin:0 auto; padding:40px 24px 90px; align-items:start; }
.toc { position:sticky; top:20px; max-height:calc(100vh - 40px); overflow:auto; padding:20px 16px; background:var(--paper); border:1px solid var(--line); box-shadow:var(--shadow); }
.toc strong { display:block; margin:0 8px 12px; color:var(--navy); }.toc a { display:block; padding:6px 8px; color:#43515c; text-decoration:none; border-left:2px solid transparent; font-size:.86rem; line-height:1.35; }.toc a:hover { color:var(--teal); border-left-color:var(--teal); background:#f2f8f8; }.toc .toc-level-3 { padding-left:20px; color:#6a767e; font-size:.78rem; }
main { min-width:0; padding:24px clamp(20px,4vw,58px) 60px; background:var(--paper); border:1px solid var(--line); box-shadow:var(--shadow); }
main > h1 { margin:0; color:var(--navy); font-size:2.25rem; line-height:1.15; } main > h1 + h2 { margin-top:12px; border:0; padding-top:0; font-size:1.35rem; color:var(--teal); }
h2 { scroll-margin-top:22px; margin:56px 0 18px; padding-top:28px; border-top:1px solid var(--line); color:var(--navy); font-size:1.7rem; line-height:1.25; }
h3 { scroll-margin-top:22px; margin:34px 0 12px; color:#16566a; font-size:1.22rem; }
p { margin:0 0 18px; } strong { color:#102f46; } hr { margin:50px 0; border:0; border-top:1px solid var(--line); }
code { padding:.1em .34em; background:#eef2f4; border-radius:3px; font:85% ui-monospace,SFMono-Regular,Menlo,monospace; } pre { overflow:auto; margin:22px 0; padding:20px; color:#e9f3f4; background:#102a3d; border-left:4px solid var(--teal); line-height:1.55; } pre code { padding:0; color:inherit; background:transparent; }
.report-list,ol { margin:10px 0 22px; padding-left:1.45rem; }.report-list li,ol li { margin:5px 0; }.report-list .depth-1 { margin-left:1.4rem; list-style-type:circle; }
blockquote { margin:18px 0; padding:12px 16px; color:#31515e; background:#eef7f6; border-left:4px solid var(--teal); }
.table-wrap { overflow-x:auto; margin:18px 0 30px; border:1px solid var(--line); }
table { width:100%; border-collapse:collapse; font-size:.88rem; line-height:1.45; } th { position:sticky; top:0; padding:11px 12px; color:#fff; background:var(--navy); text-align:left; white-space:nowrap; } td { padding:10px 12px; border-top:1px solid var(--line); vertical-align:top; } tbody tr:nth-child(even) { background:#f7f9fa; } tbody tr:hover { background:#eef7f6; }
figure { scroll-margin-top:24px; margin:30px 0 38px; border:1px solid var(--line); background:#fbfcfc; box-shadow:0 6px 22px rgba(18,48,71,.06); } figure a { display:block; } figure img { display:block; width:100%; height:auto; } figcaption { padding:14px 18px; color:#3d4c56; border-top:1px solid var(--line); font-size:.9rem; } figcaption code { word-break:break-all; }
.video-section { margin-top:60px; padding-top:30px; border-top:2px solid var(--navy); }.video-grid { display:grid; grid-template-columns:1fr 1fr; gap:22px; }.video-card { overflow:hidden; border:1px solid var(--line); background:#f9fbfb; }.video-heading { display:flex; justify-content:space-between; gap:14px; padding:15px 16px 12px; }.video-heading h3 { margin:0 0 2px; }.video-heading p { margin:0; color:var(--muted); font-size:.84rem; }.video-heading span { flex:none; color:var(--muted); font-size:.76rem; }.video-card video { display:block; width:100%; aspect-ratio:16/9; background:#0c1820; }.file-ref { margin:0; padding:10px 14px 13px; color:var(--muted); font-size:.8rem; }.file-ref span { white-space:nowrap; }
.footer { max-width:1400px; margin:0 auto; padding:0 24px 44px; color:var(--muted); font-size:.84rem; }.top-link { display:inline-block; margin-top:18px; }
@media (max-width:980px) { .metrics { grid-template-columns:1fr 1fr; }.layout { display:block; }.toc { position:relative; top:0; max-height:none; margin-bottom:24px; columns:2; }.toc strong { column-span:all; }.video-grid { grid-template-columns:1fr; } }
@media (max-width:620px) { .hero { padding-top:42px; padding-bottom:42px; }.metrics { grid-template-columns:1fr; }.layout { padding:18px 10px 54px; }.toc { columns:1; }.toc .toc-level-3 { display:none; } main { padding:22px 15px 44px; }.video-heading { display:block; }.video-heading span { display:block; margin-top:6px; } table { font-size:.8rem; } }
@media print { body { background:#fff; }.hero { color:#000; background:#fff; padding:20px 0; }.hero .lead,.hero .eyebrow,.metric span { color:#333; }.metric { border:1px solid #bbb; }.metric strong { color:#000; }.layout { display:block; max-width:none; padding:0; }.toc,.video-section { display:none; } main { border:0; box-shadow:none; padding:0; } a { color:inherit; text-decoration:none; } figure,table,pre { break-inside:avoid; } }
"""


def page(body: str, headings: list[tuple[int, str, str]], gallery: str) -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="PyCubSim2とDMBNによるSelf/Other身体状態予測実験の詳細結果">
<title>PyCubSim2 × DMBN — Self/Other実験詳細報告</title>
<style>{STYLE}</style>
</head>
<body id="top">
<header class="hero">
  <p class="eyebrow">Executed research report · 2026-09-03</p>
  <h1>Self経験からOther実状態予測・解離・保護へ</h1>
  <p class="lead">PyCubSim2で実行したX/T/P/I物理実験、DMBN学習、Self反実仮想、Other較正、中心的な不一致条件、保護判断の成功と負の結果を、図・表・動画・再現手順とともに統合した報告書。</p>
  <div class="metrics" aria-label="主要結果">
    <div class="metric"><strong>523</strong><span>主要物理エピソード</span></div>
    <div class="metric"><strong>44.5 / 94.5 / 50.9%</strong><span>T / P / IのSelf投影比改善</span></div>
    <div class="metric"><strong>10図 + 4動画</strong><span>結果の視覚資料</span></div>
    <div class="metric"><strong>Stage 8: PARTIAL</strong><span>0.6850 &lt; 閾値0.7500</span></div>
  </div>
</header>
<div class="layout">
  <nav class="toc" aria-label="報告書目次"><strong>目次</strong>{navigation(headings)}</nav>
  <main>{body}{gallery}<a class="top-link" href="#top">ページ先頭へ戻る ↑</a></main>
</div>
<footer class="footer">本ページは <code>DETAILED_EXPERIMENT_REPORT.md</code> から生成したローカル研究成果物である。主観的痛み、生物学的共感、意識を主張しない。</footer>
</body>
</html>
"""


class Validator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, int] = {}
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags[tag] = self.tags.get(tag, 0) + 1
        self.ids.extend(value for name, value in attrs if name == "id" and value)


def validate(document: str, output: Path) -> None:
    validator = Validator()
    validator.feed(document)
    assert validator.tags.get("figure") == 10
    assert validator.tags.get("video") == 4
    assert validator.tags.get("table", 0) >= 10
    assert len(validator.ids) == len(set(validator.ids))
    internal_targets = {item[1:] for item in re.findall(r'href="(#[^"]+)"', document)}
    assert internal_targets <= set(validator.ids), f"Missing anchors: {internal_targets - set(validator.ids)}"
    resources = re.findall(r'(?:src|href)="([^"]+)"', document)
    missing = [item for item in resources if not item.startswith(("#", "http://", "https://")) and not (output.parent / item).resolve().exists()]
    assert not missing, f"Missing local resources: {missing}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    body, headings = markdown_to_html(args.source.read_text(encoding="utf-8"))
    document = page(body, headings, video_gallery(args.output.parent))
    validate(document, args.output)
    args.output.write_text(document, encoding="utf-8")
    print(f"generated {args.output} ({len(document):,} characters, 10 figures, 4 videos)")


if __name__ == "__main__":
    main()
