"""This model takes the extracted questions in questions.md and parses them to google gemini using the api token. Gemini answers the questions and returns answers.md """

import os, json, time, sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
API_KEY = os.environ.get("GEMINI_API_TOKEN")
if not API_KEY:
    sys.exit("GEMINI_API_TOKEN not found in .env")

MODEL = "gemini-2.5-flash"   # swap for any model your key lists in AI Studio
DELAY = 6                    # seconds between calls, keeps you under free-tier per-minute limits
INPUT = "questions.json"

client = genai.Client(api_key=API_KEY)

SYSTEM = (
    "You are a student sitting for an examination. "
    "Pick the best answer for each question without explaining "
    "Reason through every question but do not give the reasoning , just the answer "
    "unsure, say so and lower the confidence. Reply ONLY with JSON: "
    '{"answer": "<letter and text of the option, or the answer for non-multiple-choice>", '
    '"explanation": "<2-4 sentences>", "confidence": "high|medium|low"}'
)


def build_prompt(q):
    lines = [f"Question {q['number']} (type: {q.get('type') or 'unknown'}):", q["question"], ""]
    for i, o in enumerate(q["options"]):
        letter = chr(ord("a") + i) if i < 26 else str(i + 1)
        lines.append(f"{letter}. {o['text']}")
    return "\n".join(lines)


def ask(q):
    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=build_prompt(q),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return json.loads(resp.text)
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  Q{q['number']}: {type(e).__name__}: {e} -> retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return {"answer": None, "explanation": "Failed after retries", "confidence": "none"}


with open(INPUT, encoding="utf-8") as f:
    questions = json.load(f)

results = []
for q in questions:
    if q.get("text_missing") or not q["question"]:
        print(f"Q{q['number']}: text missing (image only), skipped", file=sys.stderr)
        results.append({**q, "gemini": None, "skipped": "image-only question"})
        continue

    print(f"Q{q['number']}: asking Gemini...", file=sys.stderr)
    r = ask(q)
    results.append({**q, "gemini": r, "skipped": None})

    print(f"\nQ{q['number']}. {q['question']}")
    print(f"   Answer: {r.get('answer')}  [{r.get('confidence')}]")
    print(f"   Why: {r.get('explanation')}")
    time.sleep(DELAY)

with open("answers.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

with open("answers.md", "w", encoding="utf-8") as f:
    f.write("# Quiz review\n\n")
    for r in results:
        f.write(f"## Question {r['number']}\n\n{r['question'] or '*(text missing)*'}\n\n")
        for i, o in enumerate(r["options"]):
            f.write(f"- {chr(ord('a') + i)}. {o['text']}\n")
        g = r["gemini"]
        if g:
            f.write(f"\n**Gemini's answer:** {g.get('answer')}  (confidence: {g.get('confidence')})\n\n")
            f.write(f"{g.get('explanation')}\n")
        else:
            f.write(f"\n*Skipped: {r['skipped']}*\n")
        f.write("\n---\n\n")

print("\nSaved answers.json and answers.md", file=sys.stderr)
