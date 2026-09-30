"""Read the shipped guide without executable HTML or remote image requests."""
import base64
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from util.paths import HELP_DIR


def catalog():
    return json.loads((HELP_DIR / "index.json").read_text(encoding="utf-8"))


class GuideHTML(HTMLParser):
    allowed = {"p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "b", "em", "i", "s", "del", "blockquote", "pre", "code", "hr", "br", "table", "thead", "tbody", "tr", "th", "td", "a", "img"}
    blocked = {"script", "style", "iframe", "object", "embed", "svg", "math", "form"}

    def __init__(self, pages):
        super().__init__(convert_charrefs=True)
        self.pages = pages
        self.output = []
        self.external = set()
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.skip += 1
            return
        if self.skip or tag not in self.allowed:
            return
        attrs = dict(attrs)
        kept = {}
        if attrs.get("id"):
            kept["id"] = attrs["id"]
        if tag == "a":
            href = attrs.get("href") or ""
            url = urlsplit(href)
            if url.scheme in {"https", "http"} and url.hostname and not url.username and not url.password:
                kept["href"] = href
                self.external.add(href)
            elif not url.scheme and not url.netloc:
                if not url.path:
                    kept["href"] = "#" + url.fragment
                elif unquote(url.path) in self.pages:
                    kept["href"] = "guide:" + self.pages[unquote(url.path)] + ("#" + url.fragment if url.fragment else "")
        elif tag == "img":
            url = urlsplit(attrs.get("src") or "")
            path = HELP_DIR / unquote(url.path)
            if not url.scheme and not url.netloc and path.resolve().is_relative_to(HELP_DIR.resolve()) and path.is_file() and not path.is_symlink() and path.stat().st_size < 3_000_000:
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(path.suffix.lower())
                if mime:
                    kept["src"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
            if "src" not in kept:
                return
            kept["alt"] = attrs.get("alt") or "Guide illustration"
        self.output.append("<" + tag + "".join(f' {key}="{escape(value, quote=True)}"' for key, value in kept.items()) + ">")

    def handle_endtag(self, tag):
        if tag in self.blocked:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in self.allowed and tag not in {"img", "br", "hr"}:
            self.output.append(f"</{tag}>")

    def handle_data(self, text):
        if not self.skip:
            self.output.append(escape(text))


def page(identity):
    import markdown
    entries = catalog()
    selected = next((item for item in entries if item.get("id") == identity), None)
    if not selected:
        raise ValueError("Choose an article from the guide.")
    parser = GuideHTML({item["file"]: item["id"] for item in entries if "file" in item})
    parser.feed(markdown.markdown((HELP_DIR / selected["file"]).read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "toc"]))
    return {"id": identity, "title": selected["title"], "html": "".join(parser.output), "external_links": sorted(parser.external)}
