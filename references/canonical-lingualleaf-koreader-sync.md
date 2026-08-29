# Canonical LinguaLeaf library sync to PW5SE

Date: 2026-08-29

This is the current schema-2 workflow. The earlier flat/language-combination
snapshot remains documented in `references/lingualleaf-koreader-sync.md` for
historical recovery only.

## Contents

- [Authority and layout](#authority-and-layout)
- [Audit snapshot](#audit-snapshot)
- [Move, upload, and reading-state policy](#move-upload-and-reading-state-policy)
- [Run and resume](#run-and-resume)
- [Explicit replacement cleanup](#explicit-replacement-cleanup)
- [Completion evidence](#completion-evidence)

## Authority and layout

Use Nutstore's `LinguaLeaf/CANONICAL-LIBRARY.json` as the authority. The tool
requires schema version 2 and validates these invariants before contacting the
Kindle:

- 286 logical books in black-and-white mode;
- 286 black-and-white PDF rows with positive byte counts and SHA-256 values;
- 29 leaf categories beneath exactly eight numbered top-level categories; and
- exactly 10 logical `replacements` entries.

The 286 PDFs are published under:

```text
/mnt/us/documents/LinguaLeaf/blackwhite/01-Chinese-Classics/...
...
/mnt/us/documents/LinguaLeaf/blackwhite/08-Fantasy-and-Science-Fiction/...
```

The same run also reconciles five requested standalone PDFs: two under
`/mnt/us/documents/LazyEarn` and three under
`/mnt/us/documents/LazyTravel`. Repeated command-line requests do not create
duplicate destinations.

Keep documentation outside the book tree. Five LinguaLeaf root documents and
the 29 category `README.md` files are mirrored under the sibling
`/mnt/us/documents/LinguaLeaf-Notes` tree. A verified run also writes
`SYNC-2026-08-29.md` there from its actual results.

## Audit snapshot

The read-only audit on 2026-08-29 established the following plan. These are
planning facts, not a claim that the live apply completed:

| Planned action | Count | Meaning |
| --- | ---: | --- |
| Canonical in-device PDF moves | 191 | Existing Kindle bytes had the complete canonical SHA-256. |
| Canonical PDF uploads | 95 | No safely movable exact copy existed. |
| Standalone PDF uploads | 5 | Two LazyEarn and three LazyTravel destinations. |
| Supplied note uploads | 34 | Five root notes plus 29 category notes. |
| Legacy PDF + sidecar moves | 17 | Sixteen LinguaLeaf pairs plus the changed LazyTravel Xian pair. |

Eight of the 191 exact canonical PDF moves also had an unambiguous adjacent
sidecar eligible to move with the PDF. The dry-run action summary was therefore
`move=191`, `legacy-move=17`, and `upload=134`. A resumed plan can show some
earlier moves as `reuse`; that is expected only after their destination bytes
verify again.

The old and requested Xian PDFs were different editions. The old 47,245,345-byte
PDF had reading state; the requested PDF was 49,536,558 bytes. The plan preserves
the old PDF and its sidecar together under
`LazyTravel-Legacy-with-reading-state` before publishing the requested file.

## Move, upload, and reading-state policy

Run `scripts/sync-kindle-canonical-library.py`. It follows these rules:

1. Treat Nutstore as the only source of requested book bytes and the manifest
   size/SHA-256 as the canonical identity.
2. Prefer an in-device rename only after a complete remote SHA-256 match. This
   is the lightweight path and does not retransmit the PDF.
3. Move an adjacent `book.sdr` directory only with a byte-identical PDF and
   only when the destination has no conflicting sidecar.
4. Never attach old reading state to changed PDF bytes. Move each incompatible
   PDF and `book.sdr` together to the sibling
   `LinguaLeaf-Legacy-with-reading-state` shelf. Use the analogous LazyEarn or
   LazyTravel legacy shelf for a changed standalone book.
5. Rewrite only exact old paths in KOReader history/settings, stage the edits,
   and publish them atomically with the corresponding move.
6. Upload only missing or changed content through an owned temporary file.
   Hash the local stream while uploading, hash the remote temporary, publish
   atomically, then verify the final SHA-256.
7. Verify every requested destination before any cleanup and again after
   cleanup. Do not create persistent backups on the Kindle.

## Run and resume

Exit KOReader and temporarily prevent autostart before apply. Switch the one
regular mode marker only by same-directory rename; do not delete it or create a
second marker. The sync tool checks that `reader.lua` is stopped but does not
change or restore the autostart marker itself.

Plan first; the default is Kindle read-only:

```powershell
python .\scripts\sync-kindle-canonical-library.py
```

Review the action counts, every refusal, and the JSON report, then apply:

```powershell
python .\scripts\sync-kindle-canonical-library.py --apply
```

The default host, port, key, known-hosts file, source roots, ledger, and report
can all be overridden with the script's named options. SSH is strict-host-key,
key-only. The ignored host-side state is:

```text
device-backups/kindle-canonical-library-sync/resume.json
device-backups/kindle-canonical-library-sync/report.json
```

Repeat the same `--apply` after an interruption. The resume ledger is bound to
the host, port, and complete source-plan fingerprint. Each destination is
rechecked before it is reused; stale path rewrites and an interrupted
keep-awake transaction are recovered through the ledger.

Apply refuses a running KOReader and insufficient free space. It captures
`com.lab126.powerd preventScreenSaver`, temporarily sets it to `1`, and restores
the captured value on normal or handled-error cleanup. If an operator set the
value before launching the tool, that external original value must still be
recorded and restored after the whole canonical-sync and cleanup sequence.
Restore the original autostart marker only after final verification.

## Explicit replacement cleanup

The manifest's 10 logical replacements are not authority to delete an unknown
old file. The canonical sync deliberately defers those removals. Use the
separate fixed allowlist after the canonical successors have verified:

```powershell
python .\scripts\cleanup-kindle-explicit-replacements.py
python .\scripts\cleanup-kindle-explicit-replacements.py --apply
```

The first command is remote read-only. Require all 10 candidates to be either
`eligible` or `already-absent`, with zero `refuse` results, before apply. Each
candidate is fixed in code by exact path, byte count, and SHA-256 and is gated
on the exact schema-2 successor. Apply also requires KOReader stopped, no open
candidate file, no adjacent sidecar, and regular non-symlink files. It never
performs fuzzy or general duplicate discovery.

Its ignored host-side evidence is under:

```text
device-backups/kindle-explicit-replacement-cleanup/
```

Before restoring the external power and autostart guards, run the independent
full verifier in guarded-state mode:

```powershell
python .\scripts\verify-kindle-canonical-library.py --expected-state guarded
```

The verifier is read-only with respect to the Kindle. It validates both local
reports against the current source manifest, enforces the exact canonical tree,
hashes every requested or intentionally retained file, checks sidecars and
legacy pairs, confirms all 10 allowlisted old paths are absent, and refuses
owned synchronization temporaries. After restoring the original marker and
power value, check the final operational state without repeating all hashes:

```powershell
python .\scripts\verify-kindle-canonical-library.py --expected-state restored --state-only
```

## Completion evidence

The 2026-08-29 live workflow completed and passed independent verification:

- The canonical report reached `complete` at `2026-08-29T06:37:20Z`. Its final
  resumed plan recorded `move=23`, `reuse=168`, `legacy-move=17`, and
  `upload=134`. All 325 requested destinations verified before cleanup and
  again afterward.
- Exact KOReader metadata rewrites were 13 in
  `/mnt/us/koreader/history.lua` and one in
  `/mnt/us/koreader/settings.reader.lua`.
- The explicit cleanup transaction completed at `2026-08-29T06:47:54Z` with
  no failure and all 10 allowlisted candidates deleted.
- The guarded full verifier passed at `2026-08-29T06:55:10Z`: 286 canonical
  PDFs, five requested standalone PDFs, the intentionally retained LazyEarn
  V2 PDF, 35 notes, eight canonical sidecars, 17 legacy PDF/sidecar pairs, and
  all 10 explicit old paths absent. It verified 344 complete remote hashes,
  found zero owned temporaries, and measured 18,767,028,224 bytes free.
- The restored-state verifier passed at `2026-08-29T06:56:21Z`. The original
  `_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP` marker was regular; temporary
  `DISABLE_KOREADER_AUTOSTART`, standard `_DISABLE_KOREADER_AUTOSTART`, and
  `/mnt/us/emergency.sh` were absent; `preventScreenSaver` was `0`; and
  `reader.lua` was stopped.

One apply attempt was interrupted by a host-side Windows atomic-journal
`WinError`. Repeating the same apply with its bound ledger safely revalidated
completed destinations as reuse and finished the remaining work. This is
observed resume evidence, not permission to bypass any identity check.

Exact inventory enforcement remains deliberately scoped to
`LinguaLeaf/blackwhite`. Unreviewed old-layout LinguaLeaf siblings are retained;
only the 10 path/size/SHA-256 allowlisted replacements were removed. Continue
to use the JSON reports and independent verifier, rather than the historical
planning counts, as final-state authority.
