# LinguaLeaf Books to Kindle KOReader

Date: 2026-06-11

## Goal

Sync the color LinguaLeaf PDF books to a folder that is easy to open from
KOReader on the Kindle.

## Source Files

```text
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Wuthering Heights（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/One Hundred Years of Solitude（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/The Count of Monte Cristo（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Les Misérables（日文注）.pdf
/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Notre-Dame de Paris（日文注）.pdf
```

Observed sizes before sync:

```text
Wuthering Heights（日文注）.pdf                 14M
One Hundred Years of Solitude（日文注）.pdf    16M
The Count of Monte Cristo（日文注）.pdf         27M
Les Misérables（日文注）.pdf                   28M
Notre-Dame de Paris（日文注）.pdf              17M
```

Total size is about 102 MB.

## Kindle Target Folder

USB mount path from Ubuntu:

```text
/media/lachlan/Kindle/documents/LinguaLeaf/en-main-color/
```

The same folder as seen by KOReader on the Kindle:

```text
/mnt/us/documents/LinguaLeaf/en-main-color/
```

Reason for using `documents/LinguaLeaf/en-main-color`:

- `documents/` is the easiest folder to reach from KOReader's file browser.
- The books remain available to the stock Kindle document browser if needed.
- The `LinguaLeaf/en-main-color` subfolder keeps generated language-learning
  PDFs separated from normal Kindle books.

## Script

Sync script:

```bash
/home/lachlan/Projects/Kindle/scripts/sync-lingualleaf-books.sh
```

Usage with auto-detected Kindle mount:

```bash
/home/lachlan/Projects/Kindle/scripts/sync-lingualleaf-books.sh
```

Usage with explicit mount root:

```bash
/home/lachlan/Projects/Kindle/scripts/sync-lingualleaf-books.sh /media/lachlan/Kindle
```

The script:

1. Detects the Kindle root if no path is supplied.
2. Verifies all five source PDFs exist.
3. Creates `documents/LinguaLeaf/en-main-color/` on the Kindle.
4. Uses `rsync -a --info=progress2` to copy each PDF.
5. Runs `sync`.
6. Prints the copied PDF list.

## How to Read in KOReader

On the Kindle:

1. Open KUAL.
2. Launch KOReader.
3. In KOReader's file browser, open `documents`.
4. Open `LinguaLeaf`.
5. Open `en-main-color`.
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
/home/lachlan/Projects/Kindle/packages/koreader-kindlepw2-v2026.03/koreader/frontend/device/kindle/device.lua
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
