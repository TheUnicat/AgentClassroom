# Lecture 7 — Recursion (excerpt)

## Slide 12: What is recursion?

A recursive function calls itself on a smaller version of the same problem.

## Slide 13: The classic example

```python
def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)
```

The `if n == 0` line is the **base case**. Without it, `factorial` would call itself forever.

## Slide 14: Anatomy of a recursive function

Every recursive function has two parts:

1. **Base case** — the smallest version of the problem, which we know the answer to directly.
2. **Recursive case** — the problem solved in terms of a smaller version of itself.

> **Rule of thumb:** if the recursive call doesn't move toward the base case, you have a bug.

## Slide 15: Practice problem

Write `sum_list(xs)` that returns the sum of a list of numbers, using recursion.
