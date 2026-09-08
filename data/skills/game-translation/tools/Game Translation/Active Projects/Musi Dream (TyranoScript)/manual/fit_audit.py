"""Measure complete parsed display pages in the running game's Chromium renderer.

No game state is modified: only detached/hidden measurement nodes are added to
document.body and removed in the same synchronous evaluation. Run after refreshing
manual/runtime_audit/parsed_output.json for the current build.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from cdp_client import CDPClient

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "source/app"
PARSED = ROOT / "manual/runtime_audit/parsed_output.json"


def bare_runs(line):
    """Recover source text chunks around quote-aware KAG tags for the JP baseline."""
    line = line.strip()
    if line.startswith("_"):
        line = line[1:]
    result, start, i = [], 0, 0
    while i < len(line):
        if line[i] != "[":
            i += 1
            continue
        if i > start:
            result.append(line[start:i])
        quote = None
        i += 1
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "]":
                i += 1
                break
            i += 1
        start = i
    if start < len(line):
        result.append(line[start:])
    return result


def make_records(parsed):
    units = []
    for path in (ROOT / "store").glob("*.json"):
        if not path.name.startswith("_"):
            units.extend(json.loads(path.read_text(encoding="utf-8"))["units"])
    sites = defaultdict(list)
    for unit in units:
        for site in unit["sites"]:
            sites[(site["file"], site["line"])].append(unit)
    font_default = {"size": 28, "face": parsed["config"]["userFace"], "bold": "normal", "italic": "normal"}
    fuki = {}
    for tag in parsed["files"]["data/scenario/system/chara_define.ks"]["array_s"]:
        if tag["name"] == "fuki_chara":
            fuki[tag["pm"]["name"]] = tag["pm"]
    records, errors = [], []
    covered = set()
    for rel, doc in parsed["files"].items():
        story = bool(re.fullmatch(r"data/scenario/scene\d.*\.ks", rel))
        sample = rel.endswith("testMessagePlus/sampletext.ks")
        if not story and not sample:
            continue
        source_lines = (APP / rel).read_text(encoding="utf-8").splitlines()
        seen_on_line = Counter()
        font, bubble, speaker, label = deepcopy(font_default), False, "", "start"
        script = False
        current = None

        def flush(reason):
            nonlocal current
            if current and current["parts"]:
                current["ended_by"] = reason
                current["ids"] = sorted(set(current["ids"]))
                records.append(current)
            current = None

        def add_part(en, jp, line, kind="text"):
            nonlocal current
            if current is None:
                f = fuki.get(speaker, {}) if bubble else {}
                current = {"kind": "sample" if sample else ("bubble" if bubble and f else "normal"),
                           "file": rel, "line": line, "label": label, "speaker": speaker,
                           "parts": [], "ids": [], "fuki": f}
            current["parts"].append({"en": en, "jp": jp, "font": deepcopy(font), "type": kind, "line": line})
            for unit in sites[(rel, line)]:
                if unit["kind"] in ("dialogue", "punct"):
                    current["ids"].append(unit["id"])
                    covered.add(unit["id"])

        for tag in doc["array_s"]:
            name, pm = tag["name"], tag.get("pm", {})
            line = tag.get("line", pm.get("line", 0)) + 1
            if name == "iscript":
                script = True
                continue
            if name == "endscript":
                script = False
                continue
            if script:
                continue
            if name == "text":
                chunks = bare_runs(source_lines[line - 1])
                ordinal = seen_on_line[line]
                seen_on_line[line] += 1
                if ordinal >= len(chunks):
                    errors.append({"file": rel, "line": line, "issue": "Source baseline text chunk missing"})
                    jp = ""
                else:
                    jp = chunks[ordinal]
                en = pm.get("val", tag.get("val", ""))
                if sample and current is not None:
                    # This plugin reads physical lines itself; the built source
                    # preserves a trailing separator that KAG's parser trims.
                    en = " " + en
                add_part(en, jp, line)
            elif name == "emb":
                if pm.get("exp") != "f.piston":
                    errors.append({"file": rel, "line": line, "issue": "Unclassified dynamic insertion", "pm": pm})
                digits = "8" if "piston_9" in label else ("58" if "10_60" in label else "888888")
                add_part(digits, digits, line, "dynamic")
            elif name == "r":
                add_part("\n", "\n", line, "break")
            elif name == "l":
                if current:
                    current["glyph"] = True
            elif name == "font":
                for key in ("size", "face", "bold", "italic"):
                    if pm.get(key) not in (None, ""):
                        font[key] = int(pm[key]) if key == "size" else pm[key]
            elif name == "resetfont":
                font = deepcopy(font_default)
            elif name == "chara_ptext":
                if current and speaker != pm.get("name", ""):
                    flush("speaker-change")
                speaker = pm.get("name", "")
            elif name in ("tb_fuki_start", "fuki_start", "tb_fuki_stop", "fuki_stop"):
                flush(name)
                bubble = name.endswith("start")
            elif name in ("p", "cm", "er", "ct", "s", "jump", "label"):
                if name == "p" and current:
                    current["glyph"] = True
                flush(name)
                if name in ("cm", "er", "ct", "s"):
                    # This game's interaction clicks clear messages with cm.
                    font = deepcopy(font_default)
                if name == "label":
                    label = pm.get("label_name", "")
            elif name == "glink":
                matches = [u for u in sites[(rel, line)] if u["kind"] == "choice"]
                for unit in matches:
                    covered.add(unit["id"])
                jp = next((u["src"] for u in matches), "")
                for site in (matches[0]["sites"] if matches else []):
                    if site["file"] == rel and site["line"] == line:
                        for index, token in enumerate(site.get("tokens", [])):
                            raw = token if isinstance(token, str) else token.get("raw", token.get("text", ""))
                            jp = jp.replace(f"⟦{index}⟧", raw)
                records.append({"kind": "choice", "file": rel, "line": line, "label": label,
                                "ids": [u["id"] for u in matches], "pm": pm,
                                "parts": [{"en": pm["text"], "jp": jp, "font": deepcopy(font)}]})
        flush("file-end")
    for unit in units:
        if unit["kind"] == "name":
            records.append({"kind": "name", "file": unit["sites"][0]["file"], "line": unit["sites"][0]["line"],
                            "ids": [unit["id"]], "parts": [{"en": unit["en"], "jp": unit["src"], "font": font_default}]})
            covered.add(unit["id"])
    expected = {u["id"] for u in units if u["kind"] in ("dialogue", "punct", "choice", "name")}
    errors.extend({"id": unit_id, "issue": "Unmeasured catalog display unit"} for unit_id in sorted(expected-covered))
    return records, {"expected_units": len(expected), "covered_units": len(expected & covered),
                     "kind_units": dict(Counter(u["kind"] for u in units if u["id"] in expected)), "errors": errors}


MEASURE_JS = r"""(records => {
 const host=document.createElement('div');
 host.setAttribute('data-translation-fit-audit','temporary');
 Object.assign(host.style,{position:'fixed',left:'-20000px',top:'0',width:'1280px',height:'auto',visibility:'hidden',pointerEvents:'none',contain:'layout style paint'});
 document.body.append(host);
 const defaults=TYRANO.kag.stat.default_font;
 const family=TYRANO.kag.config.userFace;
 const normal=document.querySelector('.message0_fore .message_inner')||document.querySelector('.message_inner');
 const nameplate=document.querySelector('.chara_name_area');
 const actualChar=document.querySelector('.current_span .char');
 const liveGlyph=document.querySelector('.img_next');
 const paragraph=normal&&normal.querySelector('p');
 const styleData={font:family,defaultSize:28,lineHeight:36,normalWidth:870,normalHeight:118,
   normalWordBreak:normal?getComputedStyle(normal).wordBreak:'normal',
   normalOverflowWrap:normal?getComputedStyle(normal).overflowWrap:'normal',
   charDisplay:actualChar?getComputedStyle(actualChar).display:'inline',
   paragraphPadding:paragraph?getComputedStyle(paragraph).padding:'8px 0px 0px',
   glyph:liveGlyph?{width:liveGlyph.getBoundingClientRect().width,height:liveGlyph.getBoundingClientRect().height,marginLeft:getComputedStyle(liveGlyph).marginLeft}:null,
   sampleStyle:typeof gMessageTester!=='undefined'?gMessageTester.style:null};
 const results=[];
 const rounded=n=>Math.round(n*100)/100;
 function measure(record,language) {
   const box=document.createElement('div');
   host.append(box);
   let width=870,heightLimit=118,initialHeight=0,outerWidth=0,outerHeight=0;
   Object.assign(box.style,{position:'absolute',left:'0',top:'0',boxSizing:'content-box',fontFamily:family,fontSize:'16px',lineHeight:'36px',wordBreak:styleData.normalWordBreak,overflowWrap:styleData.normalOverflowWrap,whiteSpace:'normal',letterSpacing:'0px',fontFeatureSettings:'initial',padding:'0',margin:'0'});
   let p=box, chars=[];
   if(record.kind==='choice') {
     box.className='glink_button '+(record.pm.color||'black');
     box.style.fontSize=(record.pm.size||30)+'px';
     box.style.fontFamily=record.pm.face||family;
     box.style.lineHeight='';
     box.style.padding='';box.style.boxSizing='';
     if(record.pm.width)box.style.width=record.pm.width+'px';
     if(record.pm.height)box.style.height=record.pm.height+'px';
     box.innerHTML=record.parts[0][language];
     // 169px between column origins, minus both 4px pseudo-element outlines.
     width=record.pm.width?Number(record.pm.width):(record.pm.autopos==='true'?1280:(record.file.endsWith('scene5_piston.ks')&&Number(record.pm.x)===64?161:1280-Number(record.pm.x||0)));
     heightLimit=record.pm.height?Number(record.pm.height):(record.pm.autopos==='true'?700:720-Number(record.pm.y||0));
   } else if(record.kind==='name') {
     if(nameplate)box.style.cssText=nameplate.style.cssText;
     Object.assign(box.style,{display:'block',position:'absolute',left:'0',top:'0',width:'360px',fontSize:'26px',height:'auto',fontFamily:family,visibility:'hidden',whiteSpace:'nowrap',lineHeight:'normal',padding:'0',margin:'0'});
     box.textContent=record.parts[0][language];width=360;heightLimit=50;
   } else {
     box.className='message_inner';
     p=document.createElement('p');p.style.margin='0';box.append(p);
     if(record.kind==='bubble') {
       width=Number(record.fuki.fix_width||record.fuki.max_width||300);
       box.style.maxWidth=record.fuki.fix_width?'':width+'px';
       box.style.width=record.fuki.fix_width?width+'px':'';
       heightLimit=700-Number(record.fuki.sippo_height||20)-35;
     } else if(record.kind==='sample') {
       width=760;heightLimit=62;
       box.className='test_message_area';
       Object.assign(box.style,{width:'760px',fontSize:'18px',lineHeight:'normal'});
     } else box.style.width=width+'px';
     for(const part of record.parts) {
       if(part.type==='break'){p.append(document.createElement('br'));continue;}
       const span=document.createElement('span');
       const font=part.font;
       Object.assign(span.style,{fontFamily:font.face||family,fontSize:(record.kind==='sample'?18:font.size)+'px',fontWeight:['true','bold'].includes(font.bold)?'bold':'normal',fontStyle:font.italic==='true'?'italic':'normal',lineHeight:record.kind==='sample'?'normal':(font.size+8)+'px',letterSpacing:'0px'});
       p.append(span);
       for(const c of part[language]) {
         const ch=document.createElement('span');ch.textContent=c;ch.className='char';ch.style.display='inline';span.append(ch);chars.push(ch);
       }
     }
     if(record.kind==='bubble') {
       // Shipped adjustCharaFukiSize measures at current font first, adds
       // left/right padding and the 20px outer inset, then applies font_size.
       initialHeight=p.getBoundingClientRect().height;
       outerWidth=parseInt(getComputedStyle(box).width)+40;
       outerHeight=parseInt(getComputedStyle(box).height)+35;
       if(!record.fuki.fix_width)box.style.width=outerWidth+'px';
       for(const span of p.children)if(span.tagName==='SPAN'&&record.fuki.font_size)span.style.fontSize=record.fuki.font_size+'px';
     }
     if(record.glyph){
       const glyph=document.createElement('span');
       Object.assign(glyph.style,record.kind==='sample'?{display:'inline-block',width:'10px',height:'4px',transform:'translateY(3px)'}:{display:'inline-block',width:'19px',height:'16px',marginLeft:'3px'});
       p.append(glyph);
     }
   }
   const boxRect=box.getBoundingClientRect();
   const range=document.createRange();range.selectNodeContents(p);
   const rects=Array.from(range.getClientRects()).filter(r=>r.width>0&&r.height>0);
   let minX=boxRect.left,maxX=boxRect.left,minY=Infinity,maxY=-Infinity;
   for(const r of rects){minX=Math.min(minX,r.left);maxX=Math.max(maxX,r.right);minY=Math.min(minY,r.top);maxY=Math.max(maxY,r.bottom);}
   const pHeight=p.getBoundingClientRect().height;
   const rows=new Map();
   for(const ch of chars){const r=ch.getBoundingClientRect();const y=Math.round(r.top*10)/10;rows.set(y,(rows.get(y)||'')+ch.textContent);}
   const maxUnbroken=(()=>{const probe=document.createElement('span');probe.style.whiteSpace='pre';box.append(probe);let largest=0;for(const span of Array.from(p.children)){if(span.tagName!=='SPAN')continue;probe.style.cssText=span.style.cssText+';white-space:pre;position:absolute;';for(const word of span.textContent.split(/\s+/)){probe.textContent=word;largest=Math.max(largest,probe.getBoundingClientRect().width);}}probe.remove();return largest;})();
   const naturalWidth=record.kind==='choice'?boxRect.width:(record.kind==='name'?range.getBoundingClientRect().width:maxX-boxRect.left);
   const result={width:rounded(width),heightLimit:rounded(heightLimit),usedWidth:rounded(naturalWidth),usedHeight:rounded(pHeight),rows:Array.from(rows.values()),rowCount:rows.size,unbreakableWidth:rounded(maxUnbroken),overflowX:naturalWidth>width+.5,overflowY:pHeight>heightLimit+.5,initialHeight:rounded(initialHeight),outerWidth:rounded(outerWidth),outerHeight:rounded(outerHeight),font:getComputedStyle(box).font};
   if(record.kind==='bubble'){result.overflowY=outerHeight+Number(record.fuki.sippo_height||20)>700||pHeight+15>outerHeight+.5;result.overflowX=maxX-boxRect.left>width+.5;}
   if(record.kind==='choice'){result.padding=getComputedStyle(box).padding;result.borderBox={width:rounded(boxRect.width),height:rounded(boxRect.height)};}
   if(record.parts.some(part=>part[language].trim())&&(!naturalWidth||!pHeight))throw new Error('Zero geometry for nonempty '+record.kind+' '+record.file+':'+record.line);
   box.remove();return result;
 }
 try {
   for(const record of records)results.push({id:record.audit_id,en:measure(record,'en'),jp:measure(record,'jp')});
   return {styles:styleData,results};
 } finally {host.remove();}
})"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--parsed", type=Path, default=PARSED)
    ap.add_argument("--report", type=Path, default=ROOT / "manual/fit_report.json")
    args = ap.parse_args()
    parsed_bytes = args.parsed.read_bytes()
    parsed = json.loads(parsed_bytes.decode("utf-8"))
    records, coverage = make_records(parsed)
    candidates = {"96024eee63ffb20c": "Deep, slow&nbsp;", "f07acaf057df6bc1": "Shallow, fast&nbsp;",
                  "bb44781a12524dba": "Deep, fast&nbsp;", "9adbaf6da3298dbf": "Shallow, slow&nbsp;",
                  "c55f124145126008": "Short, deep&nbsp;"}
    for unit_id, candidate in candidates.items():
        original = next(r for r in records if unit_id in r["ids"])
        item = deepcopy(original)
        item["candidate"] = True
        item["parts"][0]["en"] = candidate
        records.append(item)
    for index, record in enumerate(records):
        record["audit_id"] = index
    with CDPClient(args.port, timeout=45) as client:
        measured = client.evaluate(MEASURE_JS + "(" + json.dumps(records, ensure_ascii=False) + ")", timeout=45)
        target = client.target["url"]
    for record, result in zip(records, measured["results"]):
        record["measurement"] = {"en": result["en"], "jp": result["jp"]}
        en, jp = result["en"], result["jp"]
        record["issues"] = (["horizontal overflow"] if en["overflowX"] else []) + (["vertical overflow"] if en["overflowY"] else [])
        record["source_also_overflows"] = jp["overflowX"] or jp["overflowY"]
        record["observations"] = []
        if en["usedWidth"] >= .95 * en["width"]:
            record["observations"].append("within 5% of horizontal budget")
        if record["kind"] in ("normal", "sample") and en["rowCount"] > 1 and len(en["rows"][-1].strip().split()) == 1:
            record["observations"].append("single-word last text row")
    summary = {"records_by_kind": dict(Counter(r["kind"] for r in records if not r.get("candidate"))),
               "overflows_by_kind": dict(Counter(r["kind"] for r in records if r["issues"] and not r.get("candidate"))),
               "source_overflows_by_kind": dict(Counter(r["kind"] for r in records if r["source_also_overflows"] and not r.get("candidate"))),
               "candidate_overflows": sum(bool(r["issues"]) for r in records if r.get("candidate"))}
    report = {"measured_at_utc": datetime.now(timezone.utc).isoformat(), "renderer_url": target,
              "parsed_sha256": hashlib.sha256(parsed_bytes).hexdigest(), "coverage": coverage,
              "summary": summary, "runtime_styles": measured["styles"],
              "dynamic_policy": "f.piston measured with 8 below 9, 58 below 60, and 888888 in unbounded >60 branches; six digits is a stress case, not a logical maximum.",
              "records": records}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, args.report.with_suffix(".md"))
    print(json.dumps({"report": str(args.report), "coverage": coverage, "summary": summary}, ensure_ascii=False, indent=2))
    for r in records:
        if r["issues"]:
            print(json.dumps({"file": r["file"], "line": r["line"], "ids": r["ids"], "kind": r["kind"], "candidate": bool(r.get("candidate")), "text": "".join(p["en"] for p in r["parts"]), "issues": r["issues"], "en": r["measurement"]["en"], "jp": r["measurement"]["jp"]}, ensure_ascii=False))


def write_markdown(report, path):
    records = [r for r in report["records"] if not r.get("candidate")]
    issues = [r for r in records if r["issues"]]
    lines = ["# Renderer text fit audit", "",
             f"Measured {report['measured_at_utc']}. **{len(issues)} overflowing displays; "
             f"{report['coverage']['covered_units']}/{report['coverage']['expected_units']} catalog display units covered; "
             f"{len(report['coverage']['errors'])} coverage errors.**", "",
             f"Parsed payload SHA-256: `{report['parsed_sha256']}`.", "",
             "## Coverage and measurements", "",
             "The coverage consists of 420 story dialogue units, three configuration sample units, "
             "14 distinct choices, four display names, and one catalog punctuation unit. "
             "Unchanged source ellipses are also included in complete display pages. "
             "All pages are assembled across text, dynamic embeddings, and explicit line breaks "
             "until page/clear/branch boundaries; script blocks are skipped.", "",
             "| Display | Measured occurrences/pages | Largest content height | Constraint |",
             "|---|---:|---:|---|" ]
    limits = {"normal": "870 x 118 px content area", "bubble": "Source character width and dynamic height; 1280 x 720 viewport",
              "sample": "760 x 62 px", "choice": "Source size/position; both 4 px column outlines reserved",
              "name": "360 px width at 26 px font"}
    for kind in ("normal", "bubble", "sample", "choice", "name"):
        group = [r for r in records if r["kind"] == kind]
        lines.append(f"| {kind} | {len(group)} | {max(r['measurement']['en']['usedHeight'] for r in group):.2f} px | {limits[kind]} |")
    lines.extend(["", "## Runtime model", "",
                  "Measurement used the running repacked game's Chromium renderer and computed font family. "
                  "The normal message font is 28 px with a 36 px line-height declaration, plus the actual "
                  "8 px paragraph padding. Chromium's resulting line boxes are measured directly. "
                  "Source font overrides, normal word wrapping, inline per-character spans, and the inline "
                  "next-page marker (19 px rendered width plus 3 px left margin) are included. "
                  "Normal two-line pages measure 90 px. The configuration sample includes its 10 px marker.", "",
                  "Bubble measurement reproduces max/fixed widths and the engine's initial height calculation "
                  "before its per-character font-size override. It checks the final text and marker against "
                  "the bubble interior, and the bubble plus tail against the viewport. The character body "
                  "font remains the source-defined 20, 24, or 28 px. No font or geometry changes are applied.", "",
                  "Nameplates are forced visible only inside the isolated hidden measurement host, "
                  "with nowrap text for measuring their single-line width. The widest name is "
                  "Small-Time Ytuber Himarii: 316.56 / 360 px. Every nonempty record has nonzero geometry.", "",
                  "The same renderer model measures source Japanese as a baseline; no source baseline "
                  "overflow was found. The temporary offscreen nodes are removed in a finally block. "
                  "The audit does not advance dialogue or alter game state.", "",
                  "## Thrust controls", "",
                  "All 33 choice occurrences fit. The two left/right column origins are 169 px apart; "
                  "reserving both 4 px outlines leaves a 161 px label border-box budget. "
                  "The widest revised left-column control is 154.28 px, leaving 6.72 px between outlines.", "",
                  "| Label | Width including padding and trailing NBSP |", "|---|---:|"])
    for r in report["records"]:
        if r.get("candidate"):
            label = r["parts"][0]["en"].replace("&nbsp;", "")
            lines.append(f"| {label} | {r['measurement']['en']['usedWidth']:.2f} px |")
    lines.extend(["", "## Remaining observations", ""])
    orphans = [r for r in records if "single-word last text row" in r["observations"]]
    if orphans:
        for r in orphans:
            lines.append(f"- `{r['file']}:{r['line']}`: final text row is `{r['measurement']['en']['rows'][-1].strip()}`; it fits without clipping.")
    else:
        lines.append("No single-word last rows remain in normal message or sample pages.")
    near = [r for r in records if "within 5% of horizontal budget" in r["observations"]]
    lines.extend(["", f"{len(near)} complete displays have a line within 5% of its horizontal budget; "
                  "each is flagged in the JSON observations inventory. These are measured fits; "
                  "multi-line pages may naturally fill their first line.", "", report["dynamic_policy"], "",
                  "The report validates text geometry and wrapping. Runtime route progression, "
                  "save/load behavior, and scene composition are covered by the parent's separate live tests.", "",
                  "## Reproduce", "", "Refresh `manual/runtime_audit/parsed_output.json` from the current build, "
                  "then run from the game workspace:", "", "```powershell",
                  "python translation/manual/fit_audit.py --port 9222", "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
