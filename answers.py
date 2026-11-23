import os, re, json, time, sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
API_KEY = os.environ.get("GEMINI_API_TOKEN")
if not API_KEY:
    sys.exit("GEMINI_API_TOKEN not found in .env")

MODEL = "gemini-3.5-flash-lite"   # swap for a model your key lists in AI Studio
DELAY = 6                    # seconds between calls (free-tier rate limits)
INPUT = sys.argv[1] if len(sys.argv) > 1 else "questions.md"

client = genai.Client(api_key=API_KEY)

SYSTEM = (
    "You are an expert question solver. "
    "Solve each question carefully, including any images provided. "
    "For multiple-choice questions, select the single best option. "
    "Return only the option letter, such as a, b, c, or d. "
    "For open-ended questions with a definitive answer, solve the problem "
    "and return only the final answer. For mathematical questions, "
    "calculate the answer rather than merely describing the method. "
    "If a question is missing options, do not invent options. "
    "If the question cannot be answered confidently, indicate uncertainty. "
    "Do not include explanations, working steps, reasoning, or extra text. "
    "Return ONLY valid JSON in this format: "
    '{"answer": "<final answer>", "confidence": "high|medium|low"}'
)


def load_markdown(path):
    text = open(path, encoding="utf-8").read()
    parts = re.split(r"^## Question (\d+)\s*$", text, flags=re.M)
    questions = []
    for num, body in zip(parts[1::2], parts[2::2]):
        body = body.split("\n---")[0]
        q_lines, options = [], []
        for line in body.splitlines():
            s = line.strip()
            m = re.match(r"^- \*\*([a-z0-9]+)\.\*\*\s*(.*)", s)
            if m:
                letter, opt = m.group(1), m.group(2).strip()
                opt = re.sub(rf"^{re.escape(letter)}\.\s*", "", opt)
                options.append({"text": opt, "images": []})
            elif s.startswith(("- ![", "![", "- **")) or not s:
                continue
            elif not options:
                q_lines.append(s)
        qtext = " ".join(q_lines)
        missing = (not qtext) or "text missing" in qtext
        questions.append({
            "number": int(num),
            "type": None,
            "question": "" if missing else qtext,
            "options": options,
            "text_missing": missing,
        })
    return questions


def build_prompt(q):
    lines = [f"Question {q['number']}:", q["question"], ""]
    for i, o in enumerate(q["options"]):
        lines.append(f"{chr(ord('a') + i)}. {o['text']}")
    return "\n".join(lines)


def ask(q, image_files=None):
    for attempt in range(5):
        try:
            contents = [build_prompt(q)]

            if image_files:
                for path in image_files:
                    contents.append(
                            types.Part.from_bytes(
                                data=path.read_bytes(),
                                mime_type="image/jpeg",
                                )
                            )
            resp = client.models.generate_content(
                model=MODEL,
                contents=contents,
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

def main():
    if INPUT.endswith(".md"):
        questions = load_markdown(INPUT)
    else:
        with open(INPUT, encoding="utf-8") as f:
            questions = json.load(f)

    # questions = questions[:3]   # uncomment for a cheap 3-question test

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

    print("\nSaved answers.json", file=sys.stderr)


if __name__ == "__main__":
    main()


