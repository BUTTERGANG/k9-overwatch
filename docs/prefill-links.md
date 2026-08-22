# One-tap "report via link" prefill links

Group admins can share a link from a Facebook post that opens the report
form with type / animal / color / location already filled in. People tap
the link, confirm the details, add a photo, and submit — no transcription
errors, no lost context.

## Generating a prefill link

Run this on the server (same environment as the app, so it signs with the
real session secret):

```bash
.venv/bin/python -c "
from k9overwatch.web.report_prefill import make_prefill_token
import os
token = make_prefill_token({
    'record_type': 'found',        # lost | found | sighting
    'animal_type': 'cat',          # dog | cat | other
    'color_primary': 'Orange tabby',
    'location_hint': 'Mass Ave & College, Indianapolis',
})
print(f\"{os.getenv('APP_BASE_URL', 'http://localhost:8000')}/report?prefill={token}\")
"
```

Paste the printed URL into your Facebook group post.

## Behavior

* Tokens are HMAC-signed with the app's session secret and expire after
  7 days (`PREFILL_TOKEN_TTL_DAYS` to change).
* Prefilled fields remain fully editable by the person filling in the form.
* Tampered or expired tokens are silently ignored — the form just renders
  empty.
* Viewing the form requires login today; anonymous visitors are sent to
  `/login` and returned to the same prefilled form afterwards.
