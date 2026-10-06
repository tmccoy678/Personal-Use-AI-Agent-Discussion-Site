"""Public source acknowledgements and allowlisted, preserved license notices."""
import json
import re
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / "references_data.json").read_text())


def citation_html(item):
    text = item["citation"]
    terms = sorted(set(item.get("italic_text", [])), key=len, reverse=True)
    if terms:
        pattern = re.compile("(" + "|".join(re.escape(term) for term in terms) + ")")
        formatted = "".join("<em>" + escape(part) + "</em>" if part in terms else escape(part)
                            for part in pattern.split(text))
    else:
        formatted = escape(text)
    url = escape(item["url"], quote=True)
    return f'{formatted} <a href="{url}">{escape(item["url"])}</a>'


def notice_files(item):
    return item.get("notice_files", [])


def content():
    parts = ['<p>Acknowledging the people, research, and software behind DobeWorks.</p>',
             '<nav class="section-index" aria-label="References sections"><a href="#influences">Influences</a>'
             '<a href="#citations">APA references</a><a href="#licenses">Software licenses</a></nav>',
             '<h2 id="influences">Influences</h2>',
             '<p>The interface brings together early conversational computing and the direct, useful design of long-lived websites. '
             'Blue, gray, and black are Taylor’s palette for this original homage.</p>']
    for item in CATALOG["inspirations"]:
        parts.append(f'<article class="influence"><h3><a href="{escape(item["url"], quote=True)}">{escape(item["name"])}</a></h3>'
                     f'<p>{escape(item["note"])}</p></article>')
    parts += ['<h2 id="citations">References</h2><p class="muted">APA 7 style · source links and DOI links</p>',
              '<ul class="references">']
    for item in sorted(CATALOG["references"], key=lambda item: item["citation"].casefold()):
        parts.append(f'<li id="ref-{escape(item["id"], quote=True)}">{citation_html(item)}</li>')
    parts += ['</ul><h2 id="licenses">Software licenses &amp; notices</h2>',
              '<p>' + escape(CATALOG["software_license_note"]) + '</p>',
              '<p>This inventory covers the pinned production dependencies and inspected Python runtime. '
              'The linked license texts are preserved from their installed distributions.</p>',
              '<div class="table-wrap"><table class="license-table"><caption class="muted">Production software inventory</caption>'
              '<thead><tr><th scope="col">Software</th><th scope="col">Version</th><th scope="col">License</th>'
              '<th scope="col">Full text</th></tr></thead><tbody>']
    for item in sorted(CATALOG["dependencies"] + CATALOG.get("runtimes", []), key=lambda item: item["name"].casefold()):
        links = "<br>".join(f'<a href="/licenses/{quote(name, safe="/")}">{escape(Path(name).name)}</a>'
                             for name in notice_files(item))
        parts.append(f'<tr><td><a href="{escape(item["url"], quote=True)}">{escape(item["name"])}</a></td>'
                     f'<td>{escape(item["version"])}</td><td>{escape(item["license"])}</td><td>{links}</td></tr>')
    parts += ['</tbody></table></div><h3>Inspiration and source-code license boundaries</h3>']
    for item in CATALOG["inspirations"]:
        source = (f' <a href="{escape(item["license_url"], quote=True)}">Upstream terms</a>'
                  if item.get("license_url") else "")
        parts.append(f'<p><strong>{escape(item["name"])}</strong>: {escape(item["license"])}.{source}</p>')
    parts += ['<p><a href="/third-party-notices.txt">Download the third-party notices</a> · '
              '<a href="/reference-data.json">Download citation and license metadata</a></p>']
    return "".join(parts)


def install(app, page):
    allowed = {name for item in CATALOG["dependencies"] + CATALOG.get("runtimes", []) for name in notice_files(item)}

    @app.get("/references")
    async def references():
        return page("References & licenses", content())

    @app.get("/licenses/{name:path}")
    async def license_notice(name: str):
        if name not in allowed:
            raise HTTPException(404, "License notice not found")
        path = (ROOT / "licenses" / name).resolve()
        if not path.is_relative_to(ROOT / "licenses") or not path.is_file():
            raise HTTPException(404, "License notice not found")
        return FileResponse(path, media_type="text/plain")

    @app.get("/third-party-notices.txt")
    async def third_party_notices():
        return FileResponse(ROOT / "THIRD_PARTY_NOTICES.md", media_type="text/plain")

    @app.get("/reference-data.json")
    async def reference_metadata():
        return FileResponse(ROOT / "references_data.json", media_type="application/json")
