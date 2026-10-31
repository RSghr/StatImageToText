# Discord intake – what the register bot posts

The stats program reads one private channel (the **stats inbox**) where the register bot posts every
deployment. The bot doesn't join that server: it posts through a **webhook URL** that the Stat Department gives
you (keep it secret – anyone with it can post there).

## When to post

* When a register is **approved**: one message with the deployment details (+ the screenshots if the optional
  **stat modal** was filled).
* When the stat modal is filled **later**: post again with the same `register_id` and the screenshots.
* When a register is **edited**: post again with the same `register_id` (the newest message wins).
* When a register is **denied / cancelled**: post `{"register_id": "...", "status": "denied"}` – it is removed.

## The message

A normal webhook message with these attachments:

| File | Content |
|---|---|
| `deployment.json` | the details below |
| `1.png`, `2.png`, `3.png` | the stat screenshots from the stat modal (optional; any image type) |

The text of the message can be anything readable for humans (an embed is fine).

```json
{
  "register_id": "4821",
  "status": "approved",
  "host": "Pengus",
  "members": ["Pengus", "Vicktor", "Panini", "Tiger"],
  "operation": "HOTDROP 8132-7735",
  "start": 1792876200,
  "planet": "Luxuriant",
  "enemy": "Terminids",
  "difficulty": 10,
  "success": true,
  "crashed": "No",
  "raid": false
}
```

* `members`: callsigns, **host first, then in the order the players appear on the stat screen, left to right**
  (the program uses that order to match the screenshots). 1 to 4 names.
* `start`: the operation start as a Unix timestamp (seconds) – the same number as in `<t:1792876200:F>`.
* `enemy`: `Terminids`, `Automatons` or `Illuminates`.
* `crashed`: the stat-modal answer about crashed missions / players leaving (free text is fine, e.g. `"No"` or
  `"Mission 2 crashed"`).
* Anything else you add is ignored. Unknown fields can be left out.

## Important: re-upload the screenshots

The links Discord gives your bot for files uploaded in a modal **expire**. Download each file from the modal
interaction (`resolved.attachments[...].url`) and attach the actual bytes to the webhook message – don't just
paste the links.

## Examples

discord.py

```python
import io, json, aiohttp, discord

async def post_to_inbox(webhook_url: str, data: dict, shots: list[discord.Attachment]):
    files = [discord.File(io.BytesIO(json.dumps(data).encode()), filename="deployment.json")]
    for i, a in enumerate(shots, 1):
        files.append(discord.File(io.BytesIO(await a.read()), filename=f"{i}{a.filename[a.filename.rfind('.'):]}"))
    async with aiohttp.ClientSession() as s:
        wh = discord.Webhook.from_url(webhook_url, session=s)
        await wh.send(content=f"Deployment {data['register_id']} - {data['operation']}", files=files,
                      username="505th register")
```

discord.js

```js
const { WebhookClient, AttachmentBuilder } = require('discord.js');

async function postToInbox(webhookUrl, data, shots /* attachments from the modal */) {
  const files = [new AttachmentBuilder(Buffer.from(JSON.stringify(data)), { name: 'deployment.json' })];
  for (const [i, a] of shots.entries()) {
    const buf = Buffer.from(await (await fetch(a.url)).arrayBuffer());
    files.push(new AttachmentBuilder(buf, { name: `${i + 1}${a.name.slice(a.name.lastIndexOf('.'))}` }));
  }
  await new WebhookClient({ url: webhookUrl }).send({
    content: `Deployment ${data.register_id} - ${data.operation}`, files, username: '505th register' });
}
```

## The stat modal (suggestion)

A modal can hold a **file upload** field (Discord "File Upload" component inside a Label, `max_values: 3`,
`file_types: ["image"]`) next to text fields:

* Crashed missions / players leaving (short text, optional)
* Stat screenshots – 3 images, one per mission
* (optional) Player order on the screenshots, left to right, if it differs from the register's member list
