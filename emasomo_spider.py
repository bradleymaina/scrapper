import requests, json, time, os
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
import tempfile
from pathlib import Path


url = input("Enter url(copy from browser tab): ")
parsed_url = urlparse(url)
query_params = parse_qs(parsed_url.query)


BASE = "https://emasomo.cuk.ac.ke/mod/quiz/attempt.php"
PARAMS = {
        "attempt": int(query_params["attempt"][0]),
        "cmid": int(query_params["cmid"][0]),
        }

def show_cookie_instructions():
    print("=" * 50)
    print("COOKIE SETUP")
    print("=" * 50)
    print(
            """
            You need to retrieve cookie value from your browser

            1. Open Browser
            2. Log in to emasomo and open the quiz or assignment you are trying to do 
            3. Press F12 for developer tools or right click and click inspect
            4. Navigate to the Application Tab
            5. Go to the cookie section and copy the value of Moodle session
            6. Paste this string when prompted to enter cookie value

            YOUR COOKIE IS SENSITIVE DO NOT SHARE IT WITH ANYONE ELSE
            """
            )
    print("=" * 50)

show_cookie_instructions()
COOKIE = input("Enter cookie value: ")

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

def download_image(url, destination):
    response = s.get(url, timeout=30 )
    response.raise_for_status()

    destination.write_bytes(response.content)
    return destination

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

# ---- save files to temporary directory  ----
with tempfile.TemporaryDirectory(prefix="quiz__") as temp_dir:
    image_dir = Path(temp_dir)

    for q in questions:
        q["question_image_files"] = []

        for i, url in enumerate(q["question_images"]):
            path = image_dir / f"q{q['number']}_question_{i}.jpg"
            download_image(url, path)
            q["question_image_files"].append(path)

        for i, option in enumerate(q["options"]):
            option["image_files"] = []

            for j, url in enumerate(option["images"]):
                path = image_dir / f"q{q['number']}_option_{i}_{j}.jpg"
                download_image(url, path)
                option["image_files"].append(path)

    console.print("[green]Image downloads complete.[/green]")

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

