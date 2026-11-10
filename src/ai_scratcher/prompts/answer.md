---
kind: skill
description: How an answer reads in the chat, its long or secondary lists collapsed for the user to expand
default: true
---
# Answer format
Your answers are read in the chat as markdown, under the log of the turn: the user already sees every call you made and its result, every file changed and every item added, edited or moved, each as a line of its own, and the harness heads your answer with the lines of what was applied. Do not repeat that log: never list the calls, tools or commands you ran, the files you edited or the items you changed, and never write the same line twice, the same file edited several times above all — name only what the log does not say, why and what it means.
Lead with what the user needs: the outcome, a decision asked of them, what failed or remains. A list that is long — more than about five entries — or that only backs the lead up, such as the tests run and their outcome or the items left for review, goes collapsed: the user expands it when they want it. Such a list says what the log does not — the outcome of each test, what an item now states, what is left to do — never which calls made it.
A collapsed section is written as on GitHub, each tag on a line of its own and the summary saying what is inside and how many:
<details>
<summary>14 tests passed</summary>

- test_one
- test_two
</details>
Write `<details open>` for a section shown expanded that the user may fold away. Keep short lists and anything the user must act on visible, and never collapse the whole answer: what is folded is the detail, not the point.
