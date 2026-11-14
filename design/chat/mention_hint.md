# Mention hint

**Mention hint.** While `@` is typed in a description editor or a reply line, a hint
(`#mention-hint`) opens under the field's left edge, never taking the focus from it: the items
whose UID contains the text typed after `@` and the project files whose name contains it. Up and
Down move the choice, Enter and Tab pick it, replacing the typed word with `@UID` or with the
file's project-relative path; Esc closes the hint with the text as typed, and the hint is absent
while no entry matches.
