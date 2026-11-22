"""
split_portfolio.py

Run this next to your current index.html:

    python split_portfolio.py

It creates (in a new folder called "output"):
    output/index.html            -> same design, but loads its content from portfolio.json
    output/portfolio.json        -> all your text content (skills, projects, ...)
    output/assets/profile.jpg    -> your photo, taken out of the HTML

Your original index.html is NOT changed.
"""
import base64
import json
import os
import re
import sys

SRC = "index.html"
OUT = "output"

if not os.path.exists(SRC):
    sys.exit("Could not find index.html in this folder. Put this script next to it and try again.")

html = open(SRC, encoding="utf-8").read()

# 1. Locate the portfolioData object ------------------------------------------
marker = "const portfolioData = "
start = html.find(marker)
if start == -1:
    sys.exit("Could not find 'const portfolioData = ' in index.html.")
obj_start = html.index("{", start)

depth, i, in_str, quote = 0, obj_start, False, ""
while i < len(html):
    ch = html[i]
    if in_str:
        if ch == "\\":
            i += 1
        elif ch == quote:
            in_str = False
    else:
        if ch in "\"'":
            in_str, quote = True, ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
    i += 1
obj_end = i + 1                      # just after the closing }
after = obj_end
if html[after] == ";":
    after += 1
obj_text = html[obj_start:obj_end]

# 2. Move the base64 photo into a real file -----------------------------------
os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)
m = re.search(r'profileImage:\s*"data:image/(\w+);base64,([^"]+)"', obj_text)
if m:
    ext = "jpg" if m.group(1) in ("jpeg", "jpg") else m.group(1)
    img_name = f"profile.{ext}"
    with open(os.path.join(OUT, "assets", img_name), "wb") as f:
        f.write(base64.b64decode(m.group(2)))
    obj_text = obj_text[:m.start()] + f'profileImage: "assets/{img_name}"' + obj_text[m.end():]
    print(f"Saved photo to {OUT}/assets/{img_name}")
else:
    print("No embedded photo found (that's fine).")

# 3. Convert the JavaScript object into JSON ----------------------------------
def js_to_json(src):
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'":
            q, j = ch, i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            s = src[i + 1:j]
            if q == "'":
                s = s.replace('"', '\\"')
            out.append('"' + s + '"')
            i = j + 1
        elif ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word, k = src[i:j], j
            while k < n and src[k] in " \t\r\n":
                k += 1
            out.append('"' + word + '"' if k < n and src[k] == ":" else word)
            i = j
        elif src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            i = src.index("*/", i) + 2
        else:
            out.append(ch)
            i += 1
    text = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", text)      # remove trailing commas

try:
    data = json.loads(js_to_json(obj_text))
except json.JSONDecodeError as e:
    sys.exit(f"Could not convert the data to JSON: {e}")

with open(os.path.join(OUT, "portfolio.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print(f"Wrote {OUT}/portfolio.json")

# 4. Build the new index.html ---------------------------------------------------
script_end = html.rfind("</script>")
loader = """/* Content now lives in portfolio.json. Edit that file, not this one. */
fetch('portfolio.json')
  .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
  .then(boot)
  .catch(err => {
    console.error(err);
    document.body.insertAdjacentHTML('afterbegin',
      '<p style="padding:24px;font-family:sans-serif;color:#c00">Could not load portfolio.json. If you opened this file directly, run it through a local server instead.</p>');
  });

function boot(portfolioData) {
"""
new_html = html[:start] + loader + html[after:script_end] + "}\n" + html[script_end:]

# drop the now-misleading "EDIT EVERYTHING HERE" comment
new_html = re.sub(r"/\* EDIT EVERYTHING ABOUT YOU HERE\.[^*]*\*/\s*", "", new_html)

with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write(new_html)
print(f"Wrote {OUT}/index.html  ({len(html) // 1024} KB -> {len(new_html) // 1024} KB)")
print("Done.")
