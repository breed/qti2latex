#!/usr/bin/env python3
import argparse
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pypandoc


# --- Minimal HTML -> LaTeX converter (safe, simple) ---
def html_to_latex(s: str) -> str:
    # use pandoc to convert HTML to LaTeX
    return pypandoc.convert_text(s, 'latex', format='html')

def escape_tex(s: str) -> str:
    # Be careful not to double-escape protected sequences like \\ from <br>
    s = s.replace("\\", "\\\\")
    replacements = [
        ("{", "\\{"), ("}", "\\}"), ("#", "\\#"), ("$", "\\$"),
        ("%", "\\%"), ("&", "\\&"), ("_", "\\_"), ("^", "\\^{}"),
        ("~", "\\~{}"),
    ]
    for a, b in replacements:
        s = s.replace(a, b)
    # restore line breaks
    s = s.replace("\\\\\\\\\n", "\\\\\n")
    return s


# --- QTI parsing helpers ---
NS = {
    "ims": "http://www.imsglobal.org/xsd/imscp_v1p1",
    "qti": "http://www.imsglobal.org/xsd/ims_qtiasiv1p2",
    # Canvas often omits proper ns; we'll access tags by suffix if needed
}

def findall_anyns(elem, tagname):
    # find tags regardless of namespace by localname
    return [n for n in elem.iter() if n.tag.split('}')[-1] == tagname]

def childall_anyns(elem, tagname):
    # find tags regardless of namespace by localname
    return [n for n in elem if n.tag.split('}')[-1] == tagname]

def child_anyns(element, tagname):
    c = childall_anyns(element, tagname)
    return c[0] if c else None

def text_of(elem):
    return (elem.text or "").strip() if elem is not None else ""

def first(elem_list):
    return elem_list[0] if elem_list else None

def read_qti_dir(in_dir: Path):
    # Collect all XML files except imsmanifest.xml
    xmls = []
    for p in in_dir.rglob("*.xml"):
        if p.name.lower() != "imsmanifest.xml":
            xmls.append(p)
    # Also try files with .xhtml that hold items (rare)
    for p in in_dir.rglob("*.xhtml"):
        xmls.append(p)
    return xmls

def extract_zip_to_tmp(zip_path: Path) -> Path:
    td = Path(tempfile.mkdtemp(prefix="qti2tex_"))
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(td)
    return td

def get_qti_metadata(item):
    meta = {}
    for qtm in findall_anyns(item, "qtimetadatafield"):
        label = text_of(first(findall_anyns(qtm, "fieldlabel")))
        val = text_of(first(findall_anyns(qtm, "fieldentry")))
        if label:
            meta[label] = val
    return meta

def get_item_stem(item):
    # Canvas stores the prompt under presentation/material/mattext (often HTML)
    pres = first(findall_anyns(item, "presentation"))
    if pres is not None:
        mats = findall_anyns(pres, "mattext")
        if mats:
            return text_of(mats[0])
        # sometimes material/flow/ material
        mats2 = findall_anyns(pres, "material")
        for m in mats2:
            mt = first(findall_anyns(m, "mattext"))
            if mt is not None:
                return text_of(mt)
    # fallback: item/presentation/flow/p/material/mattext etc.
    mats = findall_anyns(item, "mattext")
    return text_of(first(mats))

def get_choices(item):
    # Return list of (ident, html_text)
    choices = []
    for rl in findall_anyns(item, "response_lid"):
        for rc in findall_anyns(rl, "render_choice"):
            for lbl in findall_anyns(rc, "response_label"):
                ident = lbl.attrib.get("ident", "")
                mat = first(findall_anyns(lbl, "mattext"))
                txt = text_of(mat)
                choices.append((ident, txt))
    return choices

def get_correct_idents(item):
    # Parse resprocessing/respcondition/conditionvar/varequal
    correct = set()
    for rp in findall_anyns(item, "resprocessing"):
        for rc in findall_anyns(rp, "respcondition"):
            condvar = first(findall_anyns(rc, "conditionvar"))
            if condvar is None:
                continue
            for ve in findall_anyns(condvar, "varequal"):
                ident = (ve.text or "").strip()
                if ident:
                    correct.add(ident)
    return correct

def guess_type(meta, item):
    # Prefer Canvas metadata when present
    qt = (meta.get("question_type") or meta.get("interaction_type") or "").lower()
    if qt:
        return qt
    # Guess from structure
    if findall_anyns(item, "response_lid"):
        # Could be multiple_choice_question or multiple_answers_question or true_false_question
        # Try to detect T/F by choice labels
        labels = [t.lower() for _, t in get_choices(item)]
        if set(labels) & {"true", "false"} and len(labels) <= 3:
            return "true_false_question"
        # multi-answer if more than one correct
        if len(get_correct_idents(item)) > 1:
            return "multiple_answers_question"
        return "multiple_choice_question"
    if findall_anyns(item, "response_str"):
        # short answer / numeric
        return "short_answer_question"
    # fallback
    return "unknown"

def write_exam_header(f, title, description):
    f.write(r"""\documentclass[10pt,addpoints]{exam}
\usepackage{graphicx}
\usepackage{amsmath,amssymb}
\usepackage{enumitem}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage[margin=1in]{geometry}

\providecommand{\tightlist}{%%
    \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\date{}
\begin{document}
\begin{center}
  Name:\ \rule{1.5in}{0.4pt}\hfill ID:\ \rule{1.5in}{0.4pt}
  
  {\Large %s}\\[4pt]
\end{center}
\vspace{0.5cm}
%s

\begin{questions}
""" % (escape_tex(title), description))
    f.write("\n")

def write_exam_footer(f):
    f.write(r"\end{questions}" "\n" r"\end{document}" "\n")

def render_question_latex(qtype, stem_html, item):
    stem = html_to_latex(stem_html)
    lines = [f"\\question {stem}\n"]

    if qtype in ("multiple_choice_question", "true_false_question"):
        lines.append("\\begin{choices}\n")
        choices = get_choices(item)
        correct = get_correct_idents(item)
        for ident, txt in choices:
            body = html_to_latex(txt)
            if ident in correct:
                lines.append(f"\\CorrectChoice {body}\n")
            else:
                lines.append(f"\\choice {body}\n")
        lines.append("\\end{choices}\n")

    elif qtype == "multiple_answers_question":
        lines.append("\\begin{checkboxes}\n")
        choices = get_choices(item)
        correct = get_correct_idents(item)
        for ident, txt in choices:
            body = html_to_latex(txt)
            if ident in correct:
                lines.append(f"\\CorrectChoice {body}\n")
            else:
                lines.append(f"\\choice {body}\n")
        lines.append("\\end{checkboxes}\n")

    elif qtype in ("short_answer_question", "numerical_question", "short_answer"):
        lines.append("\\fillin[\\hspace{1.5in}]\n")

    elif qtype in ("essay_question", "text_only_question"):
        lines.append("\\vspace{2.5\\baselineskip}\n")

    else:
        lines.append("\\\\[4pt]\\emph{[Unsupported/unknown question type—review manually.]}\n")

    lines.append("\n")
    return "".join(lines)

def extract_tag(element):
    return element.tag.split('}')[-1]

def main():
    ap = argparse.ArgumentParser(description="Convert QTI (Canvas) to LaTeX exam")
    ap.add_argument("input", help="Path to QTI .zip or extracted QTI folder")
    ap.add_argument("-o", "--output", default="exam.tex", help="Output LaTeX file")
    ap.add_argument("--title", default="Exam", help="Exam title")
    ap.add_argument("--author", default="", help="Instructor / Course / Date line")
    args = ap.parse_args()
    title = args.title
    tmp_dir = None
    if args.input.lower().endswith(".zip"):
        tmp_dir = extract_zip_to_tmp(Path(args.input))
        in_dir = tmp_dir
    else:
        in_dir = Path(args.input)

    # collect XML item containers
    xml_files = read_qti_dir(in_dir)
    if not xml_files:
        raise SystemExit("No QTI XML files found.")

    # Copy any non-XML assets (images) into a 'media' folder next to the .tex
    out_media = Path("media")
    if not out_media.exists():
        out_media.mkdir(parents=True, exist_ok=True)
    for p in in_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() not in (".xml", ".xsd"):
            # keep relative name
            dest = out_media / p.name
            if not dest.exists():
                try:
                    shutil.copy2(p, dest)
                except Exception:
                    pass  # best effort

    description = ''
    for xf in sorted(xml_files):
        try:
            tree = ET.parse(xf)
        except ET.ParseError:
            continue
        root = tree.getroot()
        title_element = child_anyns(root, "title")
        if title_element is not None:
            title = text_of(title_element)
        description_element = child_anyns(root, "description")
        if description_element is not None:
            description = html_to_latex(text_of(description_element))


    # parse and write latex
    with open(args.output, "w", encoding="utf-8") as f:
        write_exam_header(f, title, description)

        qcount = 0
        for xf in sorted(xml_files):
            try:
                tree = ET.parse(xf)
            except ET.ParseError:
                continue
            root = tree.getroot()
            assessement = child_anyns(root, "assessment")
            if assessement is None:
                continue
            questions = child_anyns(assessement, "section")
            if questions is None:
                continue
            for question in questions:
                if extract_tag(question) == "item":
                    meta = get_qti_metadata(question)
                    qtype = guess_type(meta, question)
                    stem = get_item_stem(question)
                    # rewrite any <img src="..."> to media/filename
                    stem = re.sub(r'src=["\']([^"\']+)["\']', lambda m: f'src="media/{Path(m.group(1)).name}"', stem)
                    qcount += 1
                    f.write(render_question_latex(qtype, stem, question))
                elif extract_tag(question) == "section":
                    print("found a section")
                else:
                    print(f"what is {question}")
        write_exam_footer(f)

    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Wrote {args.output}.")
    print("Note: image files copied (best-effort) to ./media/. Compile with:")
    print("  pdflatex -interaction=nonstopmode exam.tex")

if __name__ == "__main__":
    main()