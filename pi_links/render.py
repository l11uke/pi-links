"""Builds the page. Styled as a circuit board: each group is a silkscreened
outline and each link is a solder pad on a shared trace."""

from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from .config import Link, Task

STYLE = """
:root {
  --board: #0d3b2e;
  --board-light: #14503e;
  --silkscreen: #f1f5ea;
  --muted: #b4d0c1;
  --solder: #e8c267;
  --warning: #ffd9c7;
  --font: Bahnschrift, "DIN Alternate", "Roboto Condensed", "Arial Narrow",
    sans-serif-condensed, sans-serif;
}
* { box-sizing: border-box; }
html { background: var(--board); color: var(--silkscreen); font-family: var(--font); }
body { margin: 0 auto; max-width: 76rem; padding: clamp(1.5rem, 5vw, 4rem) clamp(1rem, 4vw, 3rem); }
header { margin-bottom: clamp(2.5rem, 6vw, 4.5rem); }
h1 { font-size: clamp(2.75rem, 9vw, 5.5rem); font-weight: 700; line-height: 1; margin: 0; }
header p { color: var(--muted); font-size: 1.125rem; margin: .5rem 0 0; }
main {
  align-items: start;
  display: grid;
  gap: 2.75rem clamp(1.5rem, 3vw, 2.5rem);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr));
}
section { border: 2px solid var(--silkscreen); border-radius: 4px; padding: 0 .5rem .5rem; }
h2 {
  background: var(--board);
  display: table;
  font-size: 1.25rem;
  font-weight: 600;
  margin: -.75rem 0 .5rem .5rem;
  padding: 0 .5rem;
}
ul { list-style: none; margin: 0; padding: 0; }
li { position: relative; }
li::before {
  background: var(--solder);
  bottom: 0;
  content: "";
  left: 1.5rem;
  position: absolute;
  top: 0;
  width: 3px;
}
li:first-child::before { top: 50%; }
li:last-child::before { bottom: 50%; }
li:only-child::before { display: none; }
a {
  align-items: center;
  border-radius: 3px;
  color: inherit;
  display: grid;
  gap: 1rem;
  grid-template-columns: 1.375rem minmax(0, 1fr) auto;
  min-height: 3.75rem;
  padding: .625rem .75rem 0.625rem .9rem;
  position: relative;
  text-decoration: none;
}
.pad {
  background: var(--board);
  border: 6px solid var(--solder);
  border-radius: 50%;
  height: 1.375rem;
  width: 1.375rem;
}
.name { display: block; font-size: 1.375rem; font-weight: 600; line-height: 1.15; overflow-wrap: anywhere; }
.description { color: var(--muted); display: block; font-size: 1rem; line-height: 1.3; margin-top: .125rem; }
.target { color: var(--solder); font-size: 1.25rem; font-variant-numeric: tabular-nums; text-align: right; }
a:hover { background: var(--board-light); }
a:hover .pad, a:focus-visible .pad { background: var(--solder); }
a:focus-visible { outline: 3px solid var(--silkscreen); outline-offset: -3px; }
.tasks { grid-column: 1 / -1; }
.task-groups {
  align-items: start;
  display: grid;
  gap: 1.25rem clamp(1.5rem, 3vw, 2.5rem);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr));
  padding: .5rem .25rem .25rem;
}
.task-group { border-left: 3px solid var(--solder); padding-left: .25rem; }
h3 { color: var(--solder); font-size: 1rem; font-weight: 600; margin: 0; padding: .25rem 0 0 .65rem; }
.tasks li::before { display: none; }
.task {
  align-items: center;
  display: grid;
  gap: 1rem;
  grid-template-columns: 1.375rem minmax(0, 1fr) minmax(0, auto);
  min-height: 2.75rem;
  padding: .375rem .75rem .375rem .9rem;
}
.tasks .name { font-size: 1.0625rem; }
.tasks .description { font-size: .875rem; }
.marker { border: 2px solid var(--silkscreen); height: .75rem; justify-self: center; width: .75rem; }
.schedule { font-size: .9375rem; line-height: 1.2; max-width: 11rem; text-align: right; }
@media (max-width: 30rem) { .schedule { max-width: 6.5rem; } }
.notice {
  border: 2px solid var(--warning);
  border-radius: 4px;
  color: var(--warning);
  font-size: 1.125rem;
  line-height: 1.4;
  margin: 0 0 2.5rem;
  max-width: 70ch;
  padding: 1rem 1.25rem;
}
.notice ul { list-style: disc; margin-top: .5rem; overflow-wrap: anywhere; padding-left: 1.25rem; }
.empty { color: var(--muted); font-size: 1.25rem; line-height: 1.4; max-width: 60ch; }
code { color: var(--silkscreen); font-family: inherit; font-weight: 600; overflow-wrap: anywhere; }
"""


def _url_host(host: str, port: int, scheme: str) -> str:
    default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    return host if default else f"{host}:{port}"


def link_href(link: Link, host: str) -> str:
    if link.url:
        return link.url
    return f"{link.scheme}://{_url_host(host, link.port, link.scheme)}{link.path}"


def link_target(link: Link) -> str:
    if link.url:
        hostname = urlsplit(link.url).hostname or ""
        return hostname.removeprefix("www.")
    return f":{link.port}"


def _render_link(link: Link, host: str) -> str:
    description = (
        f'<span class="description">{escape(link.description)}</span>'
        if link.description
        else ""
    )
    return (
        f'<li><a href="{escape(link_href(link, host), quote=True)}">'
        '<span class="pad" aria-hidden="true"></span>'
        f'<span><span class="name">{escape(link.name)}</span>{description}</span>'
        f'<span class="target">{escape(link_target(link))}</span>'
        "</a></li>"
    )


def _render_task(task: Task) -> str:
    description = (
        f'<span class="description">{escape(task.description)}</span>'
        if task.description
        else ""
    )
    return (
        '<li><div class="task"><span class="marker" aria-hidden="true"></span>'
        f'<span><span class="name">{escape(task.name)}</span>{description}</span>'
        f'<span class="schedule">{escape(task.schedule)}</span></div></li>'
    )


def render_page(
    title: str,
    host: str,
    links: list[Link],
    links_file: str,
    problems: list[str] | None = None,
    tasks: list[Task] | tuple[Task, ...] = (),
) -> str:
    groups: dict[str, list[Link]] = {}
    for link in links:
        groups.setdefault(link.group, []).append(link)

    sections = "".join(
        f"<section><h2>{escape(group)}</h2><ul>"
        + "".join(_render_link(link, host) for link in members)
        + "</ul></section>"
        for group, members in groups.items()
    )

    if tasks:
        task_groups: dict[str, list[Task]] = {}
        for task in tasks:
            task_groups.setdefault(task.group, []).append(task)
        sections += (
            '<section class="tasks"><h2>Scheduled tasks</h2><div class="task-groups">'
            + "".join(
                f'<div class="task-group"><h3>{escape(group)}</h3><ul>'
                + "".join(_render_task(task) for task in members)
                + "</ul></div>"
                for group, members in task_groups.items()
            )
            + "</div></section>"
        )

    notice = ""
    if problems:
        items = "".join(f"<li>{escape(problem)}</li>" for problem in problems)
        notice = (
            '<div class="notice" role="alert">The links file has errors, so this '
            f"page shows the last working version. Fix these and reload:<ul>{items}</ul></div>"
        )

    if sections:
        body = f"<main>{sections}</main>"
    else:
        body = (
            '<p class="empty">No links yet. Add a service to '
            f"<code>{escape(links_file)}</code> and reload this page.</p>"
        )

    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        '<link rel="icon" href="data:,">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>"
        f"<header><h1>{escape(title)}</h1><p>{escape(host)}</p></header>"
        f"{notice}{body}</body></html>"
    )
