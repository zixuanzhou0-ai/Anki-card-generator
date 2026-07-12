import re
import zipfile
from pathlib import Path

patterns = [
    r"sk-[A-Za-z0-9_-]{20,}",
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"AIza[0-9A-Za-z_-]{20,}",
    r"gh[pousr]_[A-Za-z0-9_]{20,}",
    r"xox[baprs]-[A-Za-z0-9-]{20,}",
    r"(?i)(api[_ -]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{8,}",
]
files = [
    Path(r"E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\Anki_Card_Generator_Cross_Platform_Verification.docx"),
    Path(r"E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\Anki_Card_Generator_Cross_Platform_Verification.pptx"),
]
hits = []
for file_path in files:
    with zipfile.ZipFile(file_path) as archive:
        for name in archive.namelist():
            if not name.endswith((".xml", ".rels")):
                continue
            text = archive.read(name).decode("utf-8", "ignore")
            for pattern in patterns:
                if re.search(pattern, text):
                    hits.append((str(file_path), name, pattern))
if hits:
    for hit in hits:
        print(hit)
    raise SystemExit(1)
print("SECRET_SCAN_OFFICE_PASS")


