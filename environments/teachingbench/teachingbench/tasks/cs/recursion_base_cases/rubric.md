Score the tutoring on these criteria, each in [0, 1]:

- **clarity**: Was the explanation clear, well-paced, and free of unnecessary jargon? Did it avoid firehosing?
- **diagnosis**: Did the tutor identify *why* the student's list-sum was crashing — i.e., that the recursive call must move strictly toward the base case (textbook condition 2/3) — rather than just restating that base cases exist?
- **bridging**: Did the tutor reference the student's own materials (the factorial slide, the textbook conditions, the `length(xs)` worked example) and build on them, instead of presenting a generic explainer that ignored what the student already had?
- **transfer**: By the end, would the student be able to debug a *different* recursive function (not factorial, not sum_list) on their own? Look for principles being articulated, not just the one example being walked through.

The composite is the mean of the four sub-scores.
