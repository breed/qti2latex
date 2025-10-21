# qti2latex - Convert QTI XML to LaTeX exam file

qti2latex converts a QTI XML file (version 1.2) to a LaTeX exam file.
it is designed to work with text2qti (https://github.com/gpoore/text2qti), which does not support all possible question types.
it should work with export QTI files from canvas for supported question types.
it uses the exam document class (https://ctan.org/pkg/exam).

both qti2latex and exporting exams from canvas will produce a QTI zip file that can be used with qti2latex.

if there are question groups (a set of questions that can be chosen from), qti2latex will pick them at random.
the --choose-item option can be used the select a specific question instead of choosing at random.

## Supported Question Types
- Multiple Choice (single answer)
- Multiple Choice (multiple answers)
- True/False 
- Short Answer
- Numerical
- Essay

## Bonus questions

QTI doesn't support bonus questions, a question that starts with `(bonus X points)` or `bonus (X points)` will be treated as a bonus question worth X points.

## Flow to get a LaTeX exam file from a markdown text file

starting with a markdown text file called exam.md:

```bash
text2qti exam.md
qti2latex exam.zip
pdflatex exam.tex
pdflatex exam.tex
pdflatex exam.tex
```
