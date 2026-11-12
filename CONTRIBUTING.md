# How work moves through drx-2.0

Every change starts as an issue and ends as a merged pull request that closes it.

## 1. File an issue

One issue per bug or feature, in this repository. Use the Bug or Feature template.

- A bug seen in drx-demo is filed here too, with the `drx-demo` label.
- Add one area label: `ui`, `motion`, `pressure`, `firmware`, `video`, `cloud` or `tooling`.
- Add `safety` if a patient or the device could be harmed.
- Add `needs-info` if the issue can't be worked on until a question is answered.

## 2. Open a pull request

- One pull request per issue, on its own branch.
- The description contains `Fixes #<issue number>`, so merging closes the issue.
- Say what was tested and what was not, including whether it ran on a device.

## 3. Merge

`main` requires the CI checks to pass. It does not require a review, so the
owner's approval is the gate.

A pull request is ready when its checks pass and it has no conflicts with
`main`. The owner approves ready pull requests in batches: ask for a "merge
sweep" to get the open pull requests grouped as ready, blocked or draft.

## For coding agents

- Do not start a change without an issue number. If there is none, file one first.
- Link the pull request to its issue with `Fixes #<n>`.
- Do not merge without the owner's approval.
