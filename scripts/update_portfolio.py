"""
update_portfolio.py

Reads portfolio.json + real job descriptions (data/jobs/*.txt), asks Google's
Gemini AI to (1) reorder your skills so the most in-demand ones come first,
(2) reword your intro and project descriptions, and (3) suggest skills you
could learn. Then it SAFELY merges the result back into portfolio.json.

Safety rules enforced by this script (not just requested from the AI):
  * The AI never sees your email or phone number.
  * Skills can only be re-ordered. None can be added, removed or renamed.
  * Only 'intro' and project descriptions can change. Experience, education,
    certifications, links, contact details and projects' tech lists are
    copied from your original file, untouched.
  * Skills you do NOT have go to suggestions.json as advice, never into the
    portfolio itself.
  * If anything looks wrong, the script stops and changes nothing.
"""
import copy
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# If Google renames or retires this model, change it here (or set the
# GEMINI_MODEL setting). Check the model list in Google AI Studio.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PORTFOLIO_FILE = "portfolio.json"
SUGGESTIONS_FILE = "suggestions.json"
JOBS_GLOB = "data/jobs/*.txt"
MAX_JOB_CHARS = 6000          # per job file, keeps requests small
MAX_INTRO = 400
MAX_DESC = 300
MAX_SUGGESTIONS = 6

PROMPT = """You are helping a student keep their portfolio aligned with the job market.

You get (1) the student's current portfolio content as JSON and (2) several real job descriptions.

STRICT RULES
- Use ONLY skills, tools, projects and facts that already appear in the portfolio JSON. Never invent skills, projects, employers, numbers, certificates or achievements.
- "skills": return the SAME categories and the SAME skill names. You may only change the ORDER (put the skills most relevant to the job descriptions first). Do not add, remove or rename anything.
- "intro": rewrite in at most 350 characters. Plain, honest, professional English. Highlight strengths that match the jobs, but only real ones.
- "projects": for each project return its exact "name" and a rewritten "description" of at most 250 characters. Highlight relevant technologies that the project really uses.
- "suggestions": up to 6 skills or tools that appear often in the job descriptions but are NOT in the student's skills. For each give "skill" and a short "reason" (at most 120 characters). These are advice for the student, not claims about them.
- Reply with ONLY valid JSON in exactly this shape and nothing else:
{
  "intro": "...",
  "skills": {"Category name": ["skill", "skill"]},
  "projects": [{"name": "...", "description": "..."}],
  "suggestions": [{"skill": "...", "reason": "..."}]
}

PORTFOLIO JSON:
%s

JOB DESCRIPTIONS:
%s
"""


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def safe_view(portfolio):
    """Only the parts the AI is allowed to see. No email, phone or links."""
    return {
        "intro": portfolio.get("intro", ""),
        "skills": portfolio.get("skills", {}),
        "projects": [
            {
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "tech": p.get("tech", []),
                "features": p.get("features", []),
            }
            for p in portfolio.get("projects", [])
        ],
    }


def read_jobs():
    files = sorted(glob.glob(JOBS_GLOB))
    texts = []
    for i, path in enumerate(files, 1):
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()[:MAX_JOB_CHARS]
        if text:
            texts.append(f"--- JOB {i} ---\n{text}")
    return texts


def call_gemini(prompt, api_key):
    url = API_URL.format(model=MODEL)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

    for attempt in range(1, 4):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:500]
            if e.code in (429, 500, 503) and attempt < 3:
                wait = 30 * attempt
                print(f"Google returned {e.code}. Waiting {wait}s and trying again...")
                time.sleep(wait)
                continue
            sys.exit(f"Google API error {e.code}: {detail}")
        except (KeyError, IndexError, json.JSONDecodeError):
            sys.exit("Google replied in an unexpected format. Nothing was changed.")
        except urllib.error.URLError as e:
            sys.exit(f"Network problem: {e}. Nothing was changed.")
    sys.exit("Gave up after 3 tries. Nothing was changed.")


def parse_ai_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI did not return valid JSON ({e})")


def validate_and_merge(original, result):
    """Returns (new_portfolio, suggestions). Raises ValueError if anything is off."""
    if not isinstance(result, dict):
        raise ValueError("AI result is not a JSON object")

    # intro
    intro = result.get("intro")
    if not isinstance(intro, str) or not intro.strip() or len(intro) > MAX_INTRO:
        raise ValueError("intro is missing, empty or too long")

    # skills: same categories, same skills, order may change
    orig_skills = original.get("skills", {})
    new_skills = result.get("skills")
    if not isinstance(new_skills, dict) or set(new_skills) != set(orig_skills):
        raise ValueError("skills categories were added, removed or renamed")
    for cat, items in orig_skills.items():
        got = new_skills[cat]
        if not isinstance(got, list) or sorted(map(str, got)) != sorted(map(str, items)):
            raise ValueError(f"skills in '{cat}' were added, removed or renamed")

    # projects: same names, new descriptions
    orig_projects = original.get("projects", [])
    new_projects = result.get("projects")
    if not isinstance(new_projects, list):
        raise ValueError("projects is not a list")
    desc_by_name = {}
    for p in new_projects:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not isinstance(p.get("description"), str):
            raise ValueError("a project entry is malformed")
        if not p["description"].strip() or len(p["description"]) > MAX_DESC:
            raise ValueError(f"description for '{p['name']}' is empty or too long")
        desc_by_name[p["name"]] = p["description"].strip()
    if set(desc_by_name) != {p["name"] for p in orig_projects}:
        raise ValueError("project names do not match your original projects")

    # suggestions
    have = {str(s).lower() for items in orig_skills.values() for s in items}
    suggestions = []
    for s in (result.get("suggestions") or [])[:MAX_SUGGESTIONS]:
        if isinstance(s, dict) and isinstance(s.get("skill"), str) and isinstance(s.get("reason"), str):
            if s["skill"].strip() and s["skill"].lower() not in have:
                suggestions.append({"skill": s["skill"].strip(), "reason": s["reason"].strip()[:160]})

    merged = copy.deepcopy(original)
    merged["intro"] = intro.strip()
    merged["skills"] = {cat: new_skills[cat] for cat in new_skills}
    for p in merged.get("projects", []):
        p["description"] = desc_by_name[p["name"]]
    return merged, suggestions


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set. Add it in GitHub: Settings > Secrets and variables > Actions.")

    original = load_json(PORTFOLIO_FILE)
    jobs = read_jobs()
    if not jobs:
        sys.exit("No job descriptions found. Add .txt files to data/jobs/ first.")
    print(f"Read {len(jobs)} job description(s). Using model: {MODEL}")

    prompt = PROMPT % (json.dumps(safe_view(original), indent=2, ensure_ascii=False), "\n\n".join(jobs))
    reply = call_gemini(prompt, api_key)

    try:
        merged, suggestions = validate_and_merge(original, parse_ai_json(reply))
    except ValueError as e:
        sys.exit(f"Safety check FAILED: {e}. Nothing was changed.")

    save_json(PORTFOLIO_FILE, merged)
    save_json(SUGGESTIONS_FILE, {
        "note": "Skills seen often in the job descriptions that are not on your portfolio. Advice only.",
        "suggestions": suggestions,
    })
    print("Safety checks passed. portfolio.json and suggestions.json updated.")


if __name__ == "__main__":
    main()
