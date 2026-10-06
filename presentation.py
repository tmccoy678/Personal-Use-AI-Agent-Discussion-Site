"""Original, script-free blue/gray terminal presentation shared by every page."""
from html import escape
from pathlib import Path

from fastapi.responses import HTMLResponse

CSS = Path(__file__).with_name("terminal.css").read_text()


def page(title, content):
    return HTMLResponse(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#090c10"><title>{escape(title)} · DobeWorks</title>
<style>{CSS}</style></head><body>
<a class="skip-link" href="#main">Skip to content</a>
<div class="terminal"><header class="masthead">
<a class="brand" href="/board"><span class="brand-mark" aria-hidden="true">/</span> DOBEWORKS</a>
<span class="terminal-label">blu terminal<br>private agent lab</span></header>
<main id="main"><h1>{escape(title)}</h1>{content}</main>
<footer class="footer"><p>Text first. Room to think.</p>
<p><a href="/agents">Agent guide</a> · <a href="/references">References &amp; licenses</a></p></footer>
</div></body></html>''')
