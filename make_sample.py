import sys
import zipfile
from xml.sax.saxutils import escape

PARAGRAPHS = [
    "Interviewer: How do you feel about working remotely?",
    "Respondent: Remote work gives me flexibility. I can pick up my kids from school and still finish my tasks.",
    "Respondent: The hardest part is communication. Meetings on video feel tiring and I miss quick chats with my team.",
    "Interviewer: What about your manager?",
    "Respondent: My manager trusts me, which matters a lot. Trust makes remote work possible.",
    "Respondent: Sometimes communication breaks down because messages get lost across too many tools.",
    "Respondent: Flexibility is the main reason I would never go back to the office full time.",
    "Respondent: Burnout is real though. Without a commute the workday never really ends, and burnout creeps in.",
]

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in PARAGRAPHS)
DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    f"<w:body>{body}</w:body></w:document>"
)

out = sys.argv[1] if len(sys.argv) > 1 else "sample_interview.docx"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as docx:
    docx.writestr("[Content_Types].xml", CONTENT_TYPES)
    docx.writestr("_rels/.rels", RELS)
    docx.writestr("word/document.xml", DOCUMENT)
print(f"wrote {out}")
