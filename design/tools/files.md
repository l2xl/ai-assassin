# Files tool

The **files tool** lists a folder (`{"tool": "list", "path": "src", "depth": 2}`) and reads a text
file by line range (`{"tool": "read", "path": "src/queue.py", "from": 120, "lines": 80}`), each
line under its number, a long read cut with the line to go on from. Its guard keeps it inside the
project and off `.git`, the tree — read through the tree calls — and the server settings file,
which holds keys.

It is offered on every connection and in every mode, and it is what makes a file held by
reference reachable.
