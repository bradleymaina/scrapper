import requests, json, time, os
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

BASE = "https://emasomo.cuk.ac.ke/mod/quiz/attempt.php"
PARAMS = {"attempt": 1428740, "cmid": 396554}
COOKIE = "d0fc7ns949erua31e2kcchg3jm"
WRITE_MARKDOWN = True   # also create questions.md for easy reading

console = Console()

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
})
s.cookies.set("MoodleSession", COOKIE, domain="emasomo.cuk.ac.ke")


def get(page):
    for delay in (0, 5, 15, 30, 60):
        if delay:
            with console.status(f"[yellow]Waiting {delay}s before retrying page {page}..."):
                time.sleep(delay)
        r = s.get(BASE, params={**PARAMS, "page": page}, timeout=30)
        if r.status_code == 200:
            return r
        console.print(f"[red]page {page}: HTTP {r.status_code}[/red]")
    return None


def images_in(el, base_url):
    return [urljoin(base_url, i["src"]) for i in el.find_all("img")
            if i.get("src") and not i["src"].startswith("data:")]


def trim(text, n=60):
    return text if len(text) <= n else text[: n - 1] + "…"


console.print(Panel.fit("[bold cyan]E-masomo Quiz Extractor[/bold cyan]\n"
                        f"attempt {PARAMS['attempt']}  •  cmid {PARAMS['cmid']}",
                        border_style="cyan"))

questions, seen = [], set()
page = 0

while page < 40:
    with console.status(f"[cyan]Fetching page {page}..."):
        r = get(page)
    if r is None:
        console.print("[bold red]Server kept failing. Re-run later.[/bold red]")
        break
    if "login/index.php" in r.url:
        console.print("[bold red]Session expired. Copy a fresh cookie.[/bold red]")
        break

    soup = BeautifulSoup(r.text, "html.parser")
    new = [q for q in soup.select("div.que") if q.get("id") and q["id"] not in seen]
    if not new:
        console.print(f"[green]✓ page {page}: nothing new, finished[/green]")
        break

    for q in new:
        seen.add(q["id"])
        for junk in q.select(".info, .im-controls, .history"):
            junk.decompose()

        qtext = q.select_one(".qtext")
        options = [{"text": a.get_text(" ", strip=True), "images": images_in(a, r.url)}
                   for a in q.select(".answer > div, .answer tr")]
        q_imgs = images_in(qtext, r.url) if qtext else images_in(q.select_one(".content") or q, r.url)
        text = qtext.get_text(" ", strip=True) if qtext else ""

        qtype = next((c for c in q.get("class", []) if c in
                      ("multichoice", "truefalse", "shortanswer", "match",
                       "ddwtos", "gapselect", "numerical", "essay")), None)

        questions.append({
            "number": len(questions) + 1,
            "type": qtype,
            "question": text,
            "question_images": q_imgs,
            "options": options,
            "text_missing": not text,
        })

    console.print(f"[green]✓ page {page}:[/green] +{len(new)} question(s)  "
                  f"[dim](total {len(questions)})[/dim]")
    page += 1
    time.sleep(1.5)

# ---- save files ----
with open("questions.json", "w", encoding="utf-8") as f:
    json.dump(questions, f, ensure_ascii=False, indent=2)

if WRITE_MARKDOWN:
    with open("questions.md", "w", encoding="utf-8") as f:
        f.write("# Quiz Questions\n\n")
        for q in questions:
            f.write(f"## Question {q['number']}\n\n")
            f.write((q["question"] or "*(text missing, see images)*") + "\n\n")
            for u in q["question_images"]:
                f.write(f"![question image]({u})\n\n")
            for i, o in enumerate(q["options"]):
                letter = chr(ord("a") + i) if i < 26 else str(i + 1)
                f.write(f"- **{letter}.** {o['text']}\n")
                for u in o["images"]:
                    f.write(f"  - ![option image]({u})\n")
            f.write("\n---\n\n")

# ---- summary table ----
table = Table(title="Extraction summary", box=box.ROUNDED, header_style="bold magenta")
table.add_column("#", justify="right")
table.add_column("Type")
table.add_column("Question")
table.add_column("Opts", justify="right")
table.add_column("Imgs", justify="right")
table.add_column("Status")

for q in questions:
    imgs = len(q["question_images"]) + sum(len(o["images"]) for o in q["options"])
    status = "[yellow]images only[/yellow]" if q["text_missing"] else "[green]ok[/green]"
    table.add_row(str(q["number"]), q["type"] or "?", trim(q["question"]) or "[dim]—[/dim]",
                  str(len(q["options"])), str(imgs), status)

console.print(table)
console.print(Panel.fit(
    f"[bold green]Saved {len(questions)} questions[/bold green]\n"
    f"JSON: {os.path.abspath('questions.json')}"
    + (f"\nMarkdown: {os.path.abspath('questions.md')}" if WRITE_MARKDOWN else ""),
    border_style="green"))
