# Textbook Ch. 4 — Recursion (excerpt)

A recursive procedure is one defined in terms of itself. To be well-defined, three
conditions must hold:

1. There must exist at least one **base case** — an input for which the procedure
   produces an answer without recursing.
2. The recursive case must **strictly reduce** the input toward a base case.
3. The base case must be **reachable** from every legal input via the reduction in (2).

Most bugs in recursive code violate (2) or (3): the function has a base case, but the
recursive call passes an input that doesn't move toward it. The function then runs out
of stack space.

## Worked example: `length(xs)`

```python
def length(xs):
    if xs == []:
        return 0
    return 1 + length(xs[1:])
```

Base case: the empty list. The recursive case slices off the first element, so each
call moves toward the base case. The recursion is well-founded.
