# Discord intake – what the register bot posts

The stats program reads one private channel (the **stats inbox**) where the register bot posts every
deployment. The bot doesn't join that server: it posts through a **webhook URL** that the Stat Department gives
you (keep it secret – anyone with it can post there).

## When to post

Post a register **only once it has been reviewed** – when its status becomes `confirmed`, `flagged` or `denied` –
and again each time it changes after that (new status, edit by the host, stat modal filled later). Always with the
same `register_id`: the newest message of a register wins. **Pending registers are not posted.**

| Status | Meaning | Posted? | Counted in the stats? |
|---|---|---|---|
| `pending` | not reviewed yet | no | – |
| `flagged` | something is wrong, the host has time to fix it | yes | not yet (kept aside) |
| `confirmed` | reviewed, all good | yes | **yes** |
| `denied` | the host made a mistake (no point for them) – the deployment still happened | yes | **yes** |

If the stat modal is filled while the register is still pending, **keep the screenshots** (download them right
away – the modal links expire) and attach them to the first post, when the register is reviewed.

A status-only update is enough (`{"register_id": "4821", "status": "confirmed"}`): the details and screenshots
already received are kept.

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
  "status": "confirmed",
  "host": "Pengus",
  "members": ["Vicktor", "Panini", "Tiger"],
  "operation": "HOTDROP 8132-7735",
  "start": 1792876200,
  "planet": "Luxuriant",
  "enemy": "Terminids",
  "difficulty": 10,
  "success": true,
  "raid": false
}
```

* `host`: the host's callsign. `members`: the other players only (0 to 3).
* `order` (from the stat modal, optional): **all** the players, host included, in the order they appear on the stat
  screen **left to right**. Sent with the screenshots; without it the program assumes host first, then `members`.
* `start`: the operation start as a Unix timestamp (seconds) – the same number as in `<t:1792876200:F>`.
* `enemy`: `Terminids`, `Automatons` or `Illuminates`.
* Anything else you add is ignored. Unknown fields can be left out.

## Important: re-upload the screenshots

The links Discord gives your bot for files uploaded in a modal **expire**. Download each file from the modal
interaction (`resolved.attachments[...].url`) and attach the actual bytes to the webhook message – don't just
paste the links.

## TypeScript (discord.js v14)

Needs a recent discord.js 14 (modal `LabelBuilder` / `FileUploadBuilder` / select menus in modals). Check the
names against your version – the logic is what matters.

### 1. The stat modal (optional for the host)

One file-upload field for the 3 screenshots, and one dropdown per position for the order of the players on the
stat screen (the host looks at the screenshot and picks – no typing). `register` is your register object.

```ts
import {
  ModalBuilder, LabelBuilder, FileUploadBuilder, StringSelectMenuBuilder, StringSelectMenuOptionBuilder,
  type ButtonInteraction,
} from 'discord.js';

export async function showStatModal(i: ButtonInteraction,
                                    register: { id: string; host: string; members: string[] }) {
  const modal = new ModalBuilder().setCustomId(`stats:${register.id}`).setTitle('Mission stats (optional)');

  const shots = new FileUploadBuilder().setCustomId('shots').setMinValues(1).setMaxValues(3).setRequired(true);
  modal.addLabelComponents(new LabelBuilder()
    .setLabel('End-of-mission stat screens')
    .setDescription('One screenshot per mission (up to 3)')
    .setFileUploadComponent(shots));

  // Order on the stat screen, left to right (a modal holds 5 fields: 1 upload + up to 4 positions)
  const everyone = [register.host, ...register.members];
  const positions = ['Leftmost player', '2nd from the left', '3rd from the left', '4th from the left'];
  positions.slice(0, everyone.length).forEach((label, n) => {
    const menu = new StringSelectMenuBuilder().setCustomId(`pos${n + 1}`).setRequired(true)
      .addOptions(everyone.map((m) => new StringSelectMenuOptionBuilder().setLabel(m).setValue(m)));
    modal.addLabelComponents(new LabelBuilder().setLabel(label).setStringSelectMenuComponent(menu));
  });

  await i.showModal(modal);
}
```

### 2. Posting to the stats inbox – only for reviewed registers

```ts
import { WebhookClient, AttachmentBuilder, type ModalSubmitInteraction, type Attachment } from 'discord.js';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const inbox = new WebhookClient({ url: process.env.STATS_INBOX_WEBHOOK! });   // keep the URL secret
const SHOTS_DIR = 'stat-shots';                 // screenshots kept until the register is reviewed

/** Statuses that are sent to the stats inbox. Pending registers are never sent. */
const POSTED = new Set(['confirmed', 'flagged', 'denied']);

export interface RegisterData {
  register_id: string;
  status: 'pending' | 'flagged' | 'confirmed' | 'denied';
  host: string;
  members: string[];        // other players only
  order?: string[];         // everyone, host included, left to right on the stat screen (from the stat modal)
  operation: string;
  start: number;            // unix seconds, same number as in <t:...:F>
  planet: string;
  enemy: string;            // Terminids | Automatons | Illuminates
  difficulty: number;
}

/** Download the modal's screenshots now (their links expire) and keep them with the register. */
async function keepShots(registerId: string, shots: Attachment[]) {
  const dir = path.join(SHOTS_DIR, registerId);
  await mkdir(dir, { recursive: true });
  for (const [n, a] of shots.entries()) {
    const buf = Buffer.from(await (await fetch(a.url)).arrayBuffer());
    const ext = a.name.includes('.') ? a.name.slice(a.name.lastIndexOf('.')) : '.png';
    await writeFile(path.join(dir, `${n + 1}${ext}`), buf);
  }
}

async function keptShots(registerId: string): Promise<AttachmentBuilder[]> {
  const dir = path.join(SHOTS_DIR, registerId);
  const names = await readdir(dir).catch(() => [] as string[]);
  return Promise.all(names.sort().map(async (n) => new AttachmentBuilder(await readFile(path.join(dir, n)), { name: n })));
}

/**
 * Call this whenever a register is created, reviewed, edited or its stat modal is filled.
 * It only posts when the register has been reviewed (confirmed / flagged / denied) - pending ones wait.
 * `withShots`: attach the kept screenshots (first post, or the stat modal was just filled).
 */
export async function syncToInbox(data: RegisterData, withShots = true) {
  if (!POSTED.has(data.status)) return;
  const files = [new AttachmentBuilder(Buffer.from(JSON.stringify(data)), { name: 'deployment.json' })];
  if (withShots) files.push(...await keptShots(data.register_id));
  await inbox.send({ content: `Register ${data.register_id} - ${data.operation} (${data.status})`,
                     files, username: '505th register' });
}

/** Stat modal submitted: keep the screenshots and the order; post now only if already reviewed. */
export async function onStatModal(i: ModalSubmitInteraction, register: RegisterData) {
  const shots = [...(i.fields.getUploadedFiles('shots')?.values() ?? [])];
  const order = ['pos1', 'pos2', 'pos3', 'pos4']
    .filter((id) => i.fields.fields.has(id))
    .map((id) => i.fields.getStringSelectValues(id)[0]);
  if (new Set(order).size !== order.length) {               // same player picked twice
    await i.reply({ content: 'Each player can only be picked once - please try again.', ephemeral: true });
    return;
  }
  await keepShots(register.register_id, shots);
  register.order = order;                                    // save it with the register in your storage
  await syncToInbox(register);                               // (does nothing while the register is pending)
  await i.reply({ content: 'Stats received, thanks!', ephemeral: true });
}

// When an officer confirms / flags / denies a register, or the host edits it:
//   await syncToInbox(updatedRegister);
// (The kept screenshots go along every time, so the first post after the review always has them.)
```

## The stat modal (summary)

* **File upload**: the 3 stat screenshots (up to 3 images). Hosts can skip the whole modal.
* **Up to 4 dropdowns**: who is leftmost, 2nd, 3rd, 4th on the stat screen, picked from the register's players.
  This tells the stats program which callsign belongs to which in-game name the first time a player shows up;
  after that it recognises the in-game name by itself. Officers don't need to check anything.
