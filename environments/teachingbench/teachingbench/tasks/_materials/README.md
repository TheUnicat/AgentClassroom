# _materials/ — shared materials library

Files (PDFs, images, etc.) that one or more tasks reference as "the thing the
user uploaded." Tasks reference these by **path** in `meta.yaml` rather than
copying the binary into every task folder.

## How to reference from a task's `meta.yaml`

```yaml
materials:
  - path: _materials/handwritten_svd_solution.pdf
    description: |
      Two-page handwritten SVD solution for A = [[1,0,1],[0,1,1]].
  - _materials/some_other_doc.pdf   # short form: just the path, no description
```

Paths are resolved relative to `tasks/` root. The loader auto-detects type
from the file extension:

- `.md`, `.txt` — read as text and concatenated into the materials text blob
  (interpolated into `{materials}` in the student/tutor prompts)
- `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp` — recorded as **media** references
  passed through as `materials_media` in the loaded task dict. The text blob
  gets a stub line like `[Attached: foo.pdf — <description>]` so v0.1
  text-only LLMs at least know an attachment exists.

## Why a shared library

A single PDF (textbook, lecture notes, homework) often powers multiple
distinct tasks — different student personas, different questions about the
same artifact. Storing the binary once and referencing it by path keeps the
repo lean and avoids accidental divergence.

Per-task `description:` overrides exist for cases where the framing of "what
this is" differs across tasks sharing the file.
