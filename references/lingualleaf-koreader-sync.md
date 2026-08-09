# LinguaLeaf Books to Kindle KOReader

Date: 2026-06-11

The first part of this note is the historical five-book USB sync completed on
that date. The larger Nutstore-to-PW5SE migration completed and independently
confirmed on 2026-08-09 is documented separately at the end.

## Goal

Sync the color LinguaLeaf PDF books to a folder that is easy to open from
KOReader on the Kindle.

Status: completed on 2026-06-11.

## Source Files

Color edition:

```text
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Wuthering Heights（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/One Hundred Years of Solitude（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/The Count of Monte Cristo（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Les Misérables（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Notre-Dame de Paris（日文注）.pdf
```

Black-white edition:

```text
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/Wuthering Heights（日文注・黑白）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/One Hundred Years of Solitude（日文注・黑白）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/The Count of Monte Cristo（日文注・黑白）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/Les Misérables（日文注・黑白）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/Notre-Dame de Paris（日文注・黑白）.pdf
```

Observed color sizes before sync:

```text
Wuthering Heights（日文注）.pdf                 14M
One Hundred Years of Solitude（日文注）.pdf    16M
The Count of Monte Cristo（日文注）.pdf         27M
Les Misérables（日文注）.pdf                   28M
Notre-Dame de Paris（日文注）.pdf              17M
```

Total size is about 102 MB.

Observed black-white sizes before sync:

```text
Wuthering Heights（日文注・黑白）.pdf                 5.1M
One Hundred Years of Solitude（日文注・黑白）.pdf    5.4M
The Count of Monte Cristo（日文注・黑白）.pdf         17M
Les Misérables（日文注・黑白）.pdf                   21M
Notre-Dame de Paris（日文注・黑白）.pdf              7.1M
```

## Kindle Target Folder

USB mount path from Ubuntu:

```text
/media/lachlan/Kindle/documents/LinguaLeaf/en-main-color/
/media/lachlan/Kindle/documents/LinguaLeaf/en-main-blackwhite/
```

Verified copied color files:

```text
Les Misérables（日文注）.pdf                   28705466 bytes
Notre-Dame de Paris（日文注）.pdf              17201384 bytes
One Hundred Years of Solitude（日文注）.pdf    15837858 bytes
The Count of Monte Cristo（日文注）.pdf         27913066 bytes
Wuthering Heights（日文注）.pdf                14181176 bytes
```

Verified copied black-white files:

```text
Les Misérables（日文注・黑白）.pdf                   21208446 bytes
Notre-Dame de Paris（日文注・黑白）.pdf              7383528 bytes
One Hundred Years of Solitude（日文注・黑白）.pdf    5656217 bytes
The Count of Monte Cristo（日文注・黑白）.pdf         17173868 bytes
Wuthering Heights（日文注・黑白）.pdf                5316672 bytes
```

After syncing both editions, the Kindle had about 2.7 GB free.

The same folder as seen by KOReader on the Kindle:

```text
/mnt/us/documents/LinguaLeaf/en-main-color/
/mnt/us/documents/LinguaLeaf/en-main-blackwhite/
```

Reason for using `documents/LinguaLeaf/en-main-color`:

- `documents/` is the easiest folder to reach from KOReader's file browser.
- The books remain available to the stock Kindle document browser if needed.
- The `LinguaLeaf/en-main-color` subfolder keeps generated language-learning
  PDFs separated from normal Kindle books.

## Script

Sync script:

```bash
./scripts/sync-lingualleaf-books.sh
```

Usage with auto-detected Kindle mount:

```bash
./scripts/sync-lingualleaf-books.sh
```

Usage with explicit mount root:

```bash
./scripts/sync-lingualleaf-books.sh /media/lachlan/Kindle
```

Available edition options:

```bash
./scripts/sync-lingualleaf-books.sh --color
./scripts/sync-lingualleaf-books.sh --blackwhite
./scripts/sync-lingualleaf-books.sh --all
```

The script:

1. Detects the Kindle root if no path is supplied.
2. Verifies the selected source PDFs exist.
3. Creates the selected `documents/LinguaLeaf/...` folder on the Kindle.
4. Uses `rsync -a --info=progress2` to copy each PDF.
5. Runs `sync`.
6. Prints the copied PDF list.

## How to Read in KOReader

On the Kindle:

1. Open KUAL.
2. Launch KOReader.
3. In KOReader's file browser, open `documents`.
4. Open `LinguaLeaf`.
5. Open `en-main-color` or `en-main-blackwhite`.
6. Select one of the PDF files.

If KOReader opens somewhere else, use the file browser's parent-folder entry
until you reach `/mnt/us`, then open:

```text
/mnt/us/documents/LinguaLeaf/en-main-color/
```

## Current USB Note

At one check after post-jailbreak staging, Ubuntu saw the Kindle USB device as:

```text
Bus 001 Device 016: ID 1949:0004 Lab126, Inc. Amazon Kindle 3/4/Paperwhite
```

But `lsblk` reported the storage as `0B` with no partition mounted. In that
state Linux cannot copy books. The Kindle must be reconnected or switched into
USB Drive Mode until `/dev/sdc1` appears mounted at `/media/lachlan/Kindle`.

Confirmed cause when KOReader is open:

KOReader's Kindle device implementation says Kindle cannot support running in
USB mass-storage mode while KOReader is running because KOReader itself lives on
the partition that would be exported to the host computer. It inhibits the
normal Kindle USBMS behavior when USB is plugged in.

Local reference:

```text
packages/koreader-kindlepw2-v2026.03/koreader/frontend/device/kindle/device.lua
```

Relevant behavior:

```text
function Kindle:usbPlugIn()
    -- NOTE: We cannot support running in USBMS mode (we cannot, we live on the partition being exported!).
    --       To that end, we're currently SIGSTOPping volumd to inhibit the system's USBMS mode handling.
end
```

Practical rule:

- To copy files from Ubuntu, exit KOReader first.
- Return to the normal Kindle home/library screen.
- Reconnect USB and wait for normal USB Drive Mode.
- Then run `sync-lingualleaf-books.sh`.

The inverse rule applies to PW5SE autostart testing: disconnect USB **data**
before reboot. A computer data cable can put the Kindle into USB Drive Mode and
export/make unavailable `/mnt/us`, which contains both KOReader and its marker.
No cable, a wall charger, or a charge-only cable is safe for boot acceptance.

## Windows PW5SE copy recorded on 2026-08-08

One black-and-white trilingual PDF was copied with literal Unicode paths to
both of these folders, without a `blackwhite` subfolder:

```text
documents/PocketPolished/
documents/LinguaLeaf/
```

Source and both destinations were verified as 15,373,749 bytes with SHA-256:

```text
2d12225ef4c37b6045e6fb7dc74c6c94d5d1b11334a7d5c46b51f4c4fbf7a0e4
```

Use `scripts/sync-kindle-book.ps1` for repeat copies. It skips matching files,
backs up a differing destination to the ignored local `device-backups/` tree,
and verifies each destination after copying.

## Nutstore to PW5SE initial library snapshot completed on 2026-08-09

The initial-snapshot migration is complete. Its final idempotent apply
confirmation reported `bookCount=249`, `copied=0`, and `resumed=249`, meaning
all 249 plan entries had already completed and no book required retransmission
during confirmation. The post-transfer audit found all seven exact folder
counts shown below, zero owned `.migrate-*.tmp` files, and 22,910,896 KiB free
on `/mnt/us`.

This is a dated snapshot, not a permanent source count. Later on 2026-08-09,
Nutstore added one LinguaLeaf PDF, `Giving Up the Gun...｜黑白.pdf`, with source
timestamp 17:07. That new book was not in the audited 249-entry plan and is not
yet claimed transferred. The current desired corpus is 240 LinguaLeaf PDFs plus
10 PocketPolished PDFs, or 250 total; append-only resume/live sync is pending.

### Source-of-truth rule

All PDF files come from these two local Nutstore directories:

```text
C:\Users\Administrator\Nutstore\1\Share\LinguaLeaf\blackwhite
C:\Users\Administrator\Nutstore\1\Share\PocketPolished
```

The completed snapshot inventory was 239 LinguaLeaf PDFs plus 10
PocketPolished PDFs; the current source is 240 plus 10 after the addition noted
above. The old PW2 is never a source for book bytes and is not an inclusion
filter. It is consulted only for the relative folder of an exact-name
predecessor and, optionally, for a compatible KOReader `.sdr` sidecar.
Therefore every Nutstore book remains in scope even if the old PW2 never
contained it.

The audited 249-book snapshot's deterministic PW5SE destination plan under
`/mnt/us/documents` is:

| Relative folder | PDFs |
| --- | ---: |
| `LinguaLeaf/ar-en-jp-zh-blackwhite` | 1 |
| `LinguaLeaf/en-jp-zh-blackwhite` | 160 |
| `LinguaLeaf/jp-zh-blackwhite` | 9 |
| `LinguaLeaf/waka-kana-en-jp-zh-blackwhite` | 2 |
| `LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite` | 3 |
| `LinguaLeaf/wenyan-main-quadrilingual-blackwhite` | 64 |
| `PocketPolished` | 10 |
| **Total** | **249** |

This mapping has no destination collisions. It preserves an exact old-PW2
relative folder when one unambiguous filename match exists; audited filename
descriptors provide the folder for additional Nutstore books. PocketPolished
stays flat. `A Brief History of Time` is canonical only in
`LinguaLeaf/en-jp-zh-blackwhite`, not in PocketPolished or the LinguaLeaf root.

### Guarded and resumable transfer

`scripts/migrate-kindle-library.py` is plan-only unless `--apply` is supplied:

```powershell
python .\scripts\migrate-kindle-library.py
python .\scripts\migrate-kindle-library.py --apply
```

For each PDF, the tool hashes the Nutstore source with SHA-256, uploads one book
at a time to an owned temporary name in the destination directory, checks its
size, atomically publishes it with SFTP rename, then reads the published remote
file back through SFTP and verifies its SHA-256. The local resume manifest is
written atomically after each verified book, so an interrupted run can repeat
the same `--apply` command without restarting completed work.

The default resume manifest is:

```text
device-backups/kindle-library-migration/resume.json
```

Despite that ignored directory name, this JSON is transfer state only: it is
not a copy of any book or Kindle content. Per the chosen migration policy, the
tool creates no backup copy on the new PW5SE. An existing destination may be
replaced only through the guarded temporary-file flow. Cleanup of the two old,
misplaced `A Brief History of Time` paths is allowed only after the canonical
copy matches the Nutstore size and SHA-256; each misplaced file must also match
that exact source before removal.

### Optional reading state

KOReader sidecars are deliberately best effort and never block the book sync.
No `.sdr` sidecars were part of the initial 249-PDF transfer. A later read-only
audit found 20 adjacent sidecars on the PW2. Every stored metadata checksum is
stale, so metadata alone is not sufficient evidence. For 11 of the 20,
however, the adjacent PW2 PDF has the same size and current KOReader partial MD5
as the corresponding Nutstore PDF. Those 11 were eligible for a guarded
sidecar-only attempt without using the PW2 as a source of book bytes. The other
nine current PDFs differ and remain ineligible.

The guarded apply is complete for that 249-book snapshot. Its PDF result was
`bookCount=249`, `copied=0`, and `resumed=249`; its sidecar result was 10 copied
and 239 skipped. Across all 249 entries, the detailed sidecar statuses were:

- 10 `copied`;
- one `skipped-destination-exists`;
- 161 `not-inspected`;
- 68 absent or ambiguous; and
- nine checksum/current-PDF mismatches.

An independent post-copy audit compared every file in all 10 copied sidecar
trees with its PW2 source by file size and SHA-256. All 10 trees matched exactly,
and no owned temporary files remained. Both guarded executions captured an
original `com.lab126.powerd preventScreenSaver` value of `0` and restored it to
`0`.

*Zizhi Tongjian, Part 1* is the one
`skipped-destination-exists` result and was **not** overwritten. Its existing
PW5SE sidecar records `last_page=11` and `doc_pages=18079`; the PW2 sidecar
records `last_page=4651` and the same `doc_pages=18079`. The full PDF SHA-256 is
identical across Nutstore, PW2, and PW5SE, so this is a reading-state conflict,
not an edition mismatch. The safe default correctly preserved the PW5SE state.
An explicit transactional replacement path is implemented and tested but has not
run. Replacement awaits closing the book in KOReader/file browser and a
separate explicit guarded run.

*Shiji* has differently named/edition sidecars. No mapping is guessed, so its
reading state remains deliberately unmapped and was not copied.

The migration command supports an independent sidecar attempt with:

```powershell
python .\scripts\migrate-kindle-library.py --apply --copy-sdr
```

A PW2 `.sdr` directory is eligible only after an unambiguous destination is
known and current source-book identity is proved. Normally that proof is a
matching KOReader `partial_md5_checksum` in metadata. For the audited stale
metadata above, the proof instead uses the current adjacent PW2 PDF's size and
KOReader-style partial hash against the Nutstore PDF. Missing, ambiguous,
mismatched, unsafe, already-present, or failed sidecars are skipped; the
Nutstore PDF remains authoritative. The normal command never overwrites an
existing destination sidecar.

### Temporary keep-awake lifecycle

For the live network transfer, first capture the PW5SE's current
`com.lab126.powerd preventScreenSaver` value, temporarily set it to `1`, and
restore the captured value in cleanup whether the transfer succeeds or fails.
Verify the restored value before declaring the run finished. This is a
temporary transfer guard, not a permanent never-sleep setting. SSH transport
keepalives run every 30 seconds, and the same migration command remains
resumable if Wi-Fi or SSH still drops.

For the completed PDF/sidecar apply and the independent sidecar audit, the
original `preventScreenSaver` value was `0` and was verified restored to `0`.

### Final cleanup evidence

The two noncanonical `A Brief History of Time` root paths were confirmed absent:

```text
/mnt/us/documents/LinguaLeaf/A Brief History of Time (...).pdf
/mnt/us/documents/PocketPolished/A Brief History of Time (...).pdf
```

The ellipses above intentionally avoid restating the long multilingual
filename; cleanup used the exact literal paths and was hash-gated. The one
canonical copy remains in `LinguaLeaf/en-jp-zh-blackwhite`.

### Portable Kindle-only identity

The migration and current Kindle Book Sender use the intentionally published
Handoff/PDF identity. Its pinned fingerprint is:

```text
SHA256:Q/RgMY4wzHjQYuC3sfHDykwp8ejp9C7wyfAZLE8OMJE
```

The key contents must not be printed in logs or documentation. This is a
convenience key with an intentionally distributed private half: anyone who
obtains the repository, app bundle, or handoff material may authenticate while
KOReader SSH is reachable on a paired Kindle. Authorize it only on these
personally owned Kindles, never on a computer, router, server, or unrelated
device. Keep the separate PW5SE recovery key authorized as the administrative
fallback.
