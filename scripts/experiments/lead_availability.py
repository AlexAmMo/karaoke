import json, os
from pathlib import Path
root=Path(os.environ["RUNNER_TEMP"])
items=[r for r in json.loads(Path("docs/validation/generacion-muestra.json").read_text()) if r["language"]==os.environ["LANG_ID"]]
items.sort(key=lambda r:r["tag"])
row=items[int(os.environ["SHARD"])]
msg=(root/"download.log").read_text(errors="replace")
reason="YouTube refused the runner" if ("bot" in msg.lower() or "sign in" in msg.lower() or "403" in msg) else "recording PCM does not match" if "recording has changed" in msg else "publisher did not supply a verified master"
(root/"export-status/unavailable.json").write_text(json.dumps(dict(id=row["tag"],reason=reason,last_error=msg.splitlines()[-1][:500])))
