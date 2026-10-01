# RV Control Web steering

- Build the application described in `docs/architecture.md`; use Python for the backend and Svelte for the frontend. RV-Control is an MQTT publisher only; never import its code or configuration.
- Be pragmatic and concise. Change the smallest relevant surface; avoid speculative work, repeated analysis, and wasteful tool use.
- Run focused checks for changed behavior. Do not repeat checks or run unrelated suites without a reason.
- Leave Git work (staging, commits, branches, Git tags, and pushes) to the user.
- Use `deploy/docker-image.sh` for every Docker image build, tag, or push, whether invoked by a person or automation. Keep credentials out of tracked files.
- The first release is read-only: no MQTT publish or control path from the UI.