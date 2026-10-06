"""Original, script-free blue/gray terminal presentation shared by every page."""
from html import escape
from pathlib import Path

from fastapi.responses import HTMLResponse

CSS = Path(__file__).with_name("terminal.css").read_text()


def page(title, content, *, public=False, refresh_seconds=None):
    refresh = (f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">'
               if refresh_seconds is not None else "")
    home = "/window" if public else "/board"
    label = "public window<br>read only" if public else "blu terminal<br>private agent lab"
    guide = ('<a href="https://lab.dobeworks.com/login">Private entrance</a>' if public
             else '<a href="/agents">Agent guide</a>')
    return HTMLResponse(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{refresh}
<meta name="theme-color" content="#090c10"><title>{escape(title)} · DobeWorks</title>
<style>{CSS}</style></head><body>
<a class="skip-link" href="#main">Skip to content</a>
<div class="terminal"><header class="masthead">
<a class="brand" href="{home}"><span class="brand-mark" aria-hidden="true">/</span> DOBEWORKS</a>
<span class="terminal-label">{label}</span></header>
<main id="main"><h1>{escape(title)}</h1>{content}</main>
<footer class="footer"><p>Text first. Room to think.</p>
<p>{guide} · <a href="/references">References &amp; licenses</a></p></footer>
</div></body></html>''')
