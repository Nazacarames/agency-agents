#!/bin/bash
# Poll /last/leadhunter until we get a report, then save locally
OUT_FILE=/tmp/last_resp.json
DEST="/c/Users/Administrator/Projects/agency-agents-render/data"
mkdir -p "$DEST"
for i in $(seq 1 60); do
  echo "poll #$i" >&2
  SECRET=$(cat /tmp/webhook.secret)
  curl -s -H "X-Webhook-Secret: $SECRET" "https://automiq-agents.onrender.com/last/leadhunter" -o "$OUT_FILE" -m 10
  if [ -s "$OUT_FILE" ]; then
    STATUS=$(python3 -c "import json,sys; j=json.load(open('$OUT_FILE')); print(j.get('status',''))" 2>/dev/null)
    echo "status=$STATUS" >&2
    if [ "$STATUS" = "ok" ]; then
      # Write files
      python3 -c "
import json,pathlib
j=json.load(open('$OUT_FILE'))
files=j.get('files',{})
dest=pathlib.Path('$DEST')
today=j.get('date','')
for key,fname in [('report_md','leadhunter-report-'+today+'.md'),('leads_json','leadhunter-leads-'+today+'.json'),('leads_md','leadhunter-leads-'+today+'.md')]:
    content=files.get(key)
    if content:
        (dest/fname).write_text(content,encoding='utf-8')
        print(f'Wrote {fname}')
"
      echo "DONE" >&2
      exit 0
    fi
  fi
  sleep 10
done
echo "TIMEOUT" >&2
exit 2