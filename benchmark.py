"""
Benchmark an LLM's quiz answers against your Moodle quiz review.

Pipeline:
  1. Scrape the review page -> build an answer key.
  2. Load results.json (the LLM's answers).
  3. Match by question number or question text.
  4. Score, print results, and plot accuracy.

results.json expected format:
[
    {
        "question_number": 1,
        "choice": "B",
        "confidence": "high"
    },
    ...
]

Option letters (A/B/C/D) are matched against the order options
appear in the scraped Moodle HTML.
"""

import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


# ---- fill these in ----
MOODLE_SESSION_COOKIE = "gn1ku8a15mibq9kq4a85lscklo"

REVIEW_URL = (
    "https://emasomo.cuk.ac.ke/mod/quiz/review.php"
    "?attempt=1428740&cmid=396554"
)

RESULTS_JSON_PATH = "results.json"

# Save graph in the same directory as this script.
OUTPUT_CHART_PATH = (
    Path(__file__).resolve().parent / "llm_quiz_accuracy.png"
)
# ------------------------


def fetch_review_html(url: str, session_cookie: str) -> str:
    """Fetch the Moodle quiz review page."""
    cookies = {"MoodleSession": session_cookie}

    resp = requests.get(url, cookies=cookies, timeout=30)
    resp.raise_for_status()

    return resp.text


def build_answer_key(html: str):
    """
    Returns a list of dicts:
      {
        "question_number": int,
        "question_text": str,
        "options": [...],
        "correct_option_letter": "A" | None,
        "your_outcome": "correct" | "incorrect" | "partial" | "unknown",
      }
    """

    soup = BeautifulSoup(html, "html.parser")
    key = []

    for question_number, q in enumerate(
        soup.select("div.que"), start=1
    ):
        qtext_el = q.select_one(".qtext")
        qtext = qtext_el.get_text(" ", strip=True) if qtext_el else None

        classes = q.get("class", [])

        if "gradedright" in classes:
            outcome = "correct"
        elif "gradedwrong" in classes:
            outcome = "incorrect"
        elif "gradedpartial" in classes:
            outcome = "partial"
        else:
            outcome = "unknown"

        options = []
        correct_letter = None
        letters = "ABCDEFGH"

        for i, opt in enumerate(q.select(".answer > div")):
            label = opt.select_one("label")
            label_text = (
                label.get_text(" ", strip=True)
                if label
                else f"option_{i}"
            )

            options.append(label_text)

            opt_classes = opt.get("class", [])

            if "correct" in opt_classes and i < len(letters):
                correct_letter = letters[i]

        # Check Moodle's explicit right-answer text as a fallback.
        rightanswer_el = q.select_one(".rightanswer")

        rightanswer_text = (
            rightanswer_el.get_text(" ", strip=True)
            if rightanswer_el
            else None
        )

        if correct_letter is None and rightanswer_text and options:
            for i, opt_text in enumerate(options):
                if opt_text and opt_text in rightanswer_text:
                    correct_letter = letters[i]
                    break

        key.append({
            "question_number": question_number,
            "question_text": qtext,
            "options": options,
            "correct_option_letter": correct_letter,
            "your_outcome": outcome,
        })

    return key


def load_llm_answers(path: str):
    """Load Gemini's answers from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def score(answer_key, llm_answers):
    """
    Matches LLM answers to the key.

    Matching priority:
      1. Question number
      2. Question text (fallback)

    Returns per-question results and summary counts.
    """

    key_by_number = {
        q["question_number"]: q
        for q in answer_key
    }

    key_by_text = {
        q["question_text"]: q
        for q in answer_key
        if q["question_text"]
    }

    rows = []

    for ans in llm_answers:
        question_number = ans.get("question_number")
        qtext = ans.get("question_text")

        choice = (ans.get("choice") or "").strip().upper()
        confidence = ans.get("confidence", "not provided")

        # First try matching by question number.
        k = key_by_number.get(question_number)

        # If no number match, fall back to question text.
        if k is None and qtext:
            k = key_by_text.get(qtext)

        if k is None:
            rows.append({
                "question_number": question_number,
                "question_text": qtext,
                "llm_choice": choice or None,
                "confidence": confidence,
                "correct_letter": None,
                "result": "no_match_found",
            })
            continue

        correct_letter = k["correct_option_letter"]

        if not choice:
            result = "unanswered"
        elif correct_letter is None:
            result = "unknown"
        elif choice == correct_letter:
            result = "correct"
        else:
            result = "incorrect"

        rows.append({
            "question_number": (
                question_number or k["question_number"]
            ),
            "question_text": qtext or k["question_text"],
            "llm_choice": choice or None,
            "confidence": confidence,
            "correct_letter": correct_letter,
            "result": result,
        })

    summary = {
        "correct": sum(
            1 for r in rows if r["result"] == "correct"
        ),
        "incorrect": sum(
            1 for r in rows if r["result"] == "incorrect"
        ),
        "unanswered": sum(
            1 for r in rows if r["result"] == "unanswered"
        ),
        "unknown": sum(
            1 for r in rows if r["result"] == "unknown"
        ),
        "no_match_found": sum(
            1 for r in rows if r["result"] == "no_match_found"
        ),
        "total": len(rows),
    }

    return rows, summary


def plot_summary(summary: dict, title: str, out_path: str):
    """Plot and save benchmark results."""

    if plt is None:
        print(
            "matplotlib not installed - skipping chart. "
            "Run: pip install matplotlib"
        )
        return

    labels = [
        "Correct",
        "Incorrect",
        "Unanswered",
        "Unknown",
    ]

    values = [
        summary["correct"],
        summary["incorrect"],
        summary["unanswered"],
        summary["unknown"],
    ]

    colors = [
        "#4caf50",
        "#f44336",
        "#ff9800",
        "#9e9e9e",
    ]

    fig, ax = plt.subplots(figsize=(7, 4))

    bars = ax.bar(labels, values, color=colors)

    ax.set_ylabel("Number of questions")
    ax.set_title(title)

    # Display values above the bars.
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            str(val),
            ha="center",
        )

    fig.tight_layout()

    # Create the output directory if it doesn't exist.
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save the graph.
    fig.savefig(output_path, dpi=150)

    # Free matplotlib resources.
    plt.close(fig)

    print(f"Chart saved to {output_path}")


def main():
    html = fetch_review_html(
        REVIEW_URL,
        MOODLE_SESSION_COOKIE,
    )

    answer_key = build_answer_key(html)

    llm_answers = load_llm_answers(
        RESULTS_JSON_PATH
    )

    rows, summary = score(
        answer_key,
        llm_answers,
    )

    print("Per-question results:")

    for r in rows:
        print(
            f" - Q{r['question_number']}: "
            f"LLM said {r['llm_choice'] or 'N/A'}, "
            f"correct is {r['correct_letter']}, "
            f"confidence={r['confidence']} -> {r['result']}"
        )

    print("\nSummary:")

    for k, v in summary.items():
        print(f"  {k}: {v}")

    known_total = (
        summary["correct"] + summary["incorrect"]
    )

    if known_total:
        accuracy = (
            summary["correct"] / known_total
        ) * 100

        print(
            f"\nAccuracy (on the {known_total} questions "
            f"with a known answer): {accuracy:.1f}%"
        )
    else:
        print(
            "\nNo questions with a known correct answer to score against."
        )

    plot_summary(
        summary,
        "LLM quiz performance (prompting baseline)",
        OUTPUT_CHART_PATH,
    )


if __name__ == "__main__":
    main()
