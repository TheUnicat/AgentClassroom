I'm reviewing my professor's slides on recursion and I keep getting confused about base cases. The slides give the factorial example and just say "you need a base case or it'll recurse forever," but when I tried to write a function that sums a list, my version crashed with a stack overflow even though I had a base case. Can you walk me through what a base case actually has to *do*, and why my list-sum might still have failed?

Here are the materials I have from class:

---

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

---

# Textbook Ch. 4 — Recursion (excerpt)

A recursive procedure is one defined in terms of itself. To be well-defined, three conditions must hold:

1. There must exist at least one **base case** — an input for which the procedure produces an answer without recursing.
2. The recursive case must **strictly reduce** the input toward a base case.
3. The base case must be **reachable** from every legal input via the reduction in (2).

Most bugs in recursive code violate (2) or (3): the function has a base case, but the recursive call passes an input that doesn't move toward it. The function then runs out of stack space.

## Worked example: `length(xs)`

```python
def length(xs):
    if xs == []:
        return 0
    return 1 + length(xs[1:])
```

Base case: the empty list. The recursive case slices off the first element, so each call moves toward the base case. The recursion is well-founded.
