"""Code-validity: do the teacher's Python fences parse?

Measures: for code tasks where the teacher posts fenced Python code,
the fraction of those snippets that pass `compile(..., 'exec')`.

Good: every code snippet the teacher writes is at least syntactically
valid Python.
Bad: snippets that don't even parse — typos, dangling colons, mismatched
brackets — which signal the teacher is making things up.

Important scope: we only verify *syntactic* validity, not semantic
correctness. A snippet that parses but does the wrong thing (off-by-one,
wrong API, hallucinated stdlib) scores 1.0 here. The LLM judge
(`factual_correctness`) is responsible for catching semantic errors;
this function is a cheap floor underneath it.

Applicability:
- Only runs on CS tasks (`task_info['subject'] == 'cs'`) AND when at
  least one teacher message contains a fenced code block.
- Otherwise returns None.

Per code block:
- Language tag in {python, py, py3, python3}: try `compile(body)`.
- bash/sh/shell/console: skipped (no easy parser without subprocess).
- js/javascript/sql/other/unspecified: skipped (no stdlib parser).
- REPL transcripts (lines starting with `>>> ` or shell traces): skipped.

Score = parseable_python_blocks / attempted_python_blocks. If zero
Python blocks were attempted (e.g. all snippets were bash), returns
None — we have nothing to say.
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    code_blocks,
    teacher_turns,
)


_PYTHON_LANGS = {"python", "py", "py3", "python3"}
_REPL_PREFIXES = (">>>", "$ ", "# $", "PS>", "PS C:")


def _looks_like_repl(body: str) -> bool:
    stripped = body.strip()
    if not stripped:
        return True
    first = stripped.splitlines()[0].lstrip()
    return any(first.startswith(p) for p in _REPL_PREFIXES)


def _is_python(lang: str) -> bool:
    return lang.strip().lower() in _PYTHON_LANGS


def score(messages: list[dict], task_info: dict) -> float | None:
    if (task_info or {}).get("subject") != "cs":
        return None
    turns = teacher_turns(messages)
    if not turns:
        return None

    attempted = 0
    parsed = 0
    saw_any_fence = False
    for t in turns:
        for lang, body in code_blocks(t):
            saw_any_fence = True
            if not _is_python(lang):
                continue
            if _looks_like_repl(body):
                continue
            attempted += 1
            try:
                compile(body, "<judge>", "exec")
                parsed += 1
            except SyntaxError:
                pass
            except Exception:
                # compile() can raise ValueError on NUL bytes, etc.
                pass

    if not saw_any_fence:
        return None
    if attempted == 0:
        return None
    return parsed / attempted


if __name__ == "__main__":
    good = [
        {"role": "user", "content": "show me a loop"},
        {
            "role": "assistant",
            "content": "Here:\n```python\nfor i in range(3):\n    print(i)\n```",
        },
        {"role": "user", "content": "and a function?"},
        {
            "role": "assistant",
            "content": "```py\ndef add(a, b):\n    return a + b\n```",
        },
    ]
    bad = [
        {"role": "user", "content": "show me a loop"},
        {
            "role": "assistant",
            "content": "```python\nfor i in range(3)\n    print(i)\n```",  # missing colon
        },
    ]
    mixed = [
        {"role": "user", "content": "examples"},
        {
            "role": "assistant",
            "content": (
                "Valid:\n```python\nx = 1 + 2\n```\n"
                "Invalid:\n```python\nif x =\n  pass\n```\n"
                "Shell (skipped):\n```bash\nls -la\n```\n"
                "REPL (skipped):\n```python\n>>> 1 + 1\n2\n```"
            ),
        },
    ]
    not_cs = [
        {"role": "user", "content": "what's an eigenvalue"},
        {"role": "assistant", "content": "An eigenvalue is..."},
    ]
    cs_no_code = [
        {"role": "user", "content": "what's recursion"},
        {"role": "assistant", "content": "Recursion is when a function calls itself."},
    ]
    print("good (cs)       ->", score(good, {"subject": "cs"}))
    print("bad  (cs)       ->", score(bad, {"subject": "cs"}))
    print("mixed (cs)      ->", score(mixed, {"subject": "cs"}))
    print("not_cs (math)   ->", score(not_cs, {"subject": "math"}))
    print("cs no fences    ->", score(cs_no_code, {"subject": "cs"}))
