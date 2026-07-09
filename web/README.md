# Attending — demo web UI
Serve (fetch() is blocked over file://): `python3 -m http.server 8000 -d web` then open http://localhost:8000/
Drive it with Next / Back or the arrow keys; the summary overlay is the last step.
Regenerate the transcript after any fixture/gate change: `cd attending && PYTHONPATH=src python3 -m attending.demo --json > web/demo_transcript.json`
"⟳ reload from gateway" tries `fetch('/demo')` and falls back silently to the local JSON.
