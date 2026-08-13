---
name: kindle-pw5se-commission
description: Audit, prepare, jailbreak, and commission the documented Kindle Paperwhite 11th generation / PW5SE on firmware 5.15.1 with guarded WinterBreak2, Universal Hotfix, KOReader kindlepw2, key-only SSH, resumable Nutstore library migration, reversible multi-mode KOReader autostart, gesture-crash recovery, and brightness/warmth control. Use for this repo's PW5SE workflow, recovery checks, KOReader or SSH setup, autostart/stability/lighting control, or repeatable Kindle book copying; do not use it for a different model or firmware without a fresh compatibility audit.
---

# Commission the audited PW5SE

Work from the repository root. Treat physical Kindle UI steps as explicit human
gates and keep the device in Airplane Mode during USB staging.

## Guardrails

- Run `scripts/pw5se-winterbreak.ps1 -Action Diagnose` first. Stop for firmware
  other than `5.15.1`, an unexpected device, or an existing
  `documents/JAILBROKEN.txt` marker.
- Never print or commit the full serial, Wi-Fi credential, private SSH key, or
  `authorized_keys` content.
- The user explicitly selected `Handoff/keys/kindle_handoff_rsa` as the
  portable GUI/PDF identity. Its private half is published, so authorize it
  only on these Kindles, never on a computer, router, server, or other account.
- Keep `/mnt/us/emergency.sh` absent. Universal Hotfix treats it as an escape
  hatch and returns before its normal KMC/MKK repair work, so it is not a safe
  composable KOReader boot launcher.
- Do not force-install KPM's `kindlehf` KOReader package. This firmware requires
  the pinned `kindlepw2` archive.
- The original Store/Mesquito WinterBreak route failed cleanly after its one
  full LocalStorage replacement: no marker, no OTA, and all staged payload
  files unchanged. Preserve its records and do not repeat or restore that route.
- Use WinterBreak2 only through the dedicated guarded
  `scripts/pw5se-winterbreak.ps1` identity-binding and
  `StageWinterBreak2` actions. Require firmware `5.15.1`, the matching device
  fingerprint, an owned 50-90 MiB free-space guard, and the official `wb2.zip`
  `1.0.0` hash.
- Keep the stock `jb.sh` from `wb2.zip` unchanged. Never splice in a modern
  bootstrap, mix Store-WinterBreak files into WB2, or use the generic legacy
  `scripts/kindle-jailbreak.ps1` staging implementation.
- Prefer the official hosted WinterBreak2 page. During a hosted-page outage,
  use only `scripts/winterbreak2-local-server.ps1`: inspect with `Status`, start
  the pinned official clone only on an unoccupied port, and stop only a process
  whose exact recorded identity is still valid. Never adopt or stop an
  unmanaged listener. The optional Windows firewall change requires the
  explicit `-AllowPrivateSubnetFirewall` switch and remains Private-profile,
  exact-address/port, and `LocalSubnet` scoped.
- Never use generic `StagePostJailbreak` on this device. After WB2, install only
  the pinned Universal Hotfix `2.5.0` first; do not mix MRPI, KUAL, or KOReader
  into that persistence step.
- Do not infer hotfix persistence from `winterbreak.log`, a consumed update, or
  the runner booklet alone. Use the nonce-bound `StageHotfixProbe` and
  `VerifyHotfix` actions. Keep the owned filler exact until that proof is
  published; never create or edit its result manually.
- Keep public `RemoveFiller` closed after WB2. Only `StageKOReader`, with the
  verified device-bound hotfix proof and its own durable removal authorization,
  may remove or resume removal of the exact owned filler.
- Do not use destructive LanguageBreak or a factory reset without a new,
  explicit compatibility and recovery decision.
- Exit KOReader before USB mass-storage work.
- Boot-test KOReader autostart with USB **data** disconnected. A wall charger or
  charge-only cable is safe; USB drive mode exports `/mnt/us`, where both the
  launcher and recovery marker live, so the job must wait/fail closed.
- Require exactly one regular mode marker. `DISABLE_KOREADER_AUTOSTART` is
  native/disabled, `_DISABLE_KOREADER_AUTOSTART` is standard `--asap`, and
  `_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP` is lower-memory mode. Switch
  only by same-directory rename; missing/multiple markers or any directory,
  symlink, or special file must fail closed. Never enable over USB.

## Workflow

1. Read `docs/paperwhite5-5.15.1-winterbreak-koreader.md` completely.
2. Download and hash-check inputs:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action Download
   ```

3. Confirm the existing USB-visible backups and Store-stage audit records are
   intact. Confirm the user has saved a working Wi-Fi profile on the Kindle,
   enabled Airplane Mode, restarted, and reconnected USB. USB mass storage
   cannot safely create the system Wi-Fi profile.
4. Do not rerun `Prepare`, `ResetStoreCache`, or a Store-sandbox restore. The
   original stage and owned filler are already present and audited; `Diagnose`
   must confirm the current device and firmware before the dedicated WB2 stage.
5. Treat the original Store route as closed. Its final English-language trigger
   showed the ordinary Store, and the offline audit found no jailbreak marker,
   no root OTA, and all 17 payload files unchanged. Do not run another Store
   trigger, cache replacement, or Store-sandbox restore.
6. Confirm Airplane Mode, re-run `Diagnose`, then stage only the dedicated
   official browser fallback:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action BindDeviceIdentity -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action StageWinterBreak2 -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action Eject
   ```

   `BindDeviceIdentity` is explicit and idempotent. It stores only a
   domain-separated SHA-256 of the Windows volume serial and size, never the raw
   identifier, and later actions must reject a different device. The staging
   action must preserve the Store-attempt records, verify the stock WB2 files,
   create a separate reversible manifest, and leave 50-90 MiB free.
7. Let the user turn Airplane Mode off, connect the already-saved Wi-Fi, open
   Experimental Browser, visit `https://winterbreak2.now.sh/`, and press
   **Jailbreak** once. Amazon registration is not required. Wait for completion,
   immediately return to Airplane Mode, and reconnect USB.

   If the hosted page is unavailable, run the local helper's read-only status
   first:

   ```powershell
   .\scripts\winterbreak2-local-server.ps1 -Action Status
   ```

   Start only when there is no managed state and no listener occupying the
   chosen port. The default changes no firewall state; opt in only if necessary:

   ```powershell
   .\scripts\winterbreak2-local-server.ps1 -Action Start
   # Or, for a new run that needs the narrow Private/LocalSubnet rule:
   .\scripts\winterbreak2-local-server.ps1 -Action Start -AllowPrivateSubnetFirewall
   ```

   On the Kindle visit `http://<PC-LAN-IP>/` (or include `:<PORT>` for a custom
   port), press once, then use `-Action Stop` only if `Status` says `managed:
   true`. The helper must keep an existing unmanaged listener observation-only.
8. Inspect for a root `update.bin.tmp.partial`; remove only that incomplete OTA
   file if present. Then require the completion evidence in `winterbreak.log`:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action VerifyWinterBreak2
   ```

   Require successful developer-key installation, developer flag, `mntus` exec
   flag, the final completion line, and the prompt to install the hotfix. Do not
   infer success from file presence.
9. Install the pinned Universal Hotfix `2.5.0`
   (`Update_hotfix_universal.bin`, SHA-256
   `94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59`)
   by staging it alone and safely ejecting:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action StageHotfix -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action Eject
   ```

   `StageHotfix` must require the matching executed-WB2 audit and exact hotfix
   hash. On the Kindle, choose **Update Your Kindle**, wait for reboot, then
   open **Run Hotfix**. Return to Airplane Mode and reconnect USB. Require the
   exact UTF-8 `2.5.0\n` runner marker, consumed root package, no root OTA,
   unchanged WB2 log, and intact owned filler. Stage only the proof and eject:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action StageHotfixProbe -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action Eject
   ```

   Open **Verify Hotfix** once, wait for its success message, return to
   Airplane Mode, reconnect USB, and require its exact nonce-bound result:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action VerifyHotfix -ConfirmedAirplaneMode
   ```

   The active record may reconcile an interrupted copy/state write only when
   the probe hash is exact. Never replace its nonce or manufacture its result.
   If and only if the original verifier reports `START_LOG` while every current
   persistence gate passed, use the same record's `StageHotfixDiagnostic`, run
   **Diagnose Hotfix** once, then `ReadHotfixDiagnostic` and
   `AcceptHotfixPersistentState`. Record proof mode `persistent-state-v2` and
   explicitly leave the historical 13-job sequence unclaimed. Do not rerun or
   wrap the root Hotfix script to recreate log history.
10. Only after a matching full-history proof or explicit
    `persistent-state-v2` acceptance is published, install and verify KOReader:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action StageKOReader -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action VerifyKOReaderStage
   ```

   This validates the archive/tree before recording filler-removal authority.
   On interruption, rerun `StageKOReader`; its device-bound stage record permits
   the filler to remain absent while repairing only KOReader. Do not invoke
   public `RemoveFiller`.

11. Configure the fresh admin recovery key first:

   ```powershell
   .\scripts\configure-koreader-usb.ps1 -Action Configure -ConfirmedAirplaneMode
   ```

   `Configure` first requires the proof-bound completed KOReader stage, refuses
   any root `emergency.sh`, installs the exact secure-SSH and manual ambient-
   brightness patches, and writes exactly one expected recovery key. It must
   fail closed if a different/additional key or foreign patch already exists.
12. Safely eject, manually launch KOReader, connect the already-saved Wi-Fi
   profile, and prove admin key-only SSH on port `2222`. Then install the
   explicitly selected portable GUI/PDF identity while retaining recovery:

   ```powershell
   .\scripts\pair-kindle-book-sender.ps1 -KindleIp <kindle-ip>
   ```

   Require exactly two managed identities, successful portable BatchMode
   login, and no unknown key. The portable private key is already public; keep
   it Kindle-only. Ensure password/empty-password authentication still fails.
13. For the documented Nutstore library migration, read
   `references/lingualleaf-koreader-sync.md`, then run the planner before apply:

   ```powershell
   python .\scripts\migrate-kindle-library.py
   python .\scripts\migrate-kindle-library.py --apply
   ```

   PDF bytes must come only from Nutstore. Use the old PW2 only for relative
   folder mapping and optional compatible `.sdr` metadata. The apply path must
   upload one temporary file at a time, atomically publish it, verify SHA-256,
   and save an atomic host-bound resume ledger. Do not create backups on the
   new Kindle. Run `--copy-sdr` only as a separate best-effort choice after all
   books pass. KOReader maps `book.pdf` to the adjacent `book.sdr` directory,
   not `book.pdf.sdr`. Copy only one unambiguous, symlink-free sidecar and never
   overwrite existing PW5 state. Accept it when its recorded KOReader partial
   checksum matches Nutstore, or when stale metadata is backed by the current
   adjacent PW2 PDF having the exact Nutstore size and KOReader partial MD5.
   Recheck that identity immediately before copy, require the PW5 PDF to match
   Nutstore size and full SHA-256, publish the sidecar atomically, and record
   the result in the host-bound resume ledger. Never guess between differently
   named or different-edition sidecars.

   If Nutstore gains books after a completed run, extend the schema-1 ledger
   only when the new plan is a strict append-only superset: every prior
   destination must retain its exact SHA-256 and size, hosts must match, and
   only new destinations may be added as pending. Refuse removals, changed
   books, same-count source drift, malformed state, or collisions.

   Existing PW5 sidecars remain protected by default. When the owner has
   explicitly chosen the PW2 state as authoritative, close the target book and
   use the opt-in replacement only with both other mutation flags:

   ```powershell
   python .\scripts\migrate-kindle-library.py --apply --copy-sdr --replace-existing-sdr
   ```

   The tool must refuse an open destination PDF, re-hash both sidecar trees,
   park the existing tree under the transaction-owned rollback name, publish
   the verified PW2 tree, restore the old tree on failure, and remove the
   rollback after success. A successful transaction leaves no backup.
14. Read `docs/pw5se-koreader-autostart-design.md` and
   `docs/pw5se-koreader-stability-and-lighting.md` completely before changing
   boot, gesture, or light behavior. Require the exact v2 Upstart asset SHA-256
   `87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd`
   and pass `test-koreader-autostart.ps1`, `test-koreader-stability.ps1`, and
   `test-koreader-ambient-brightness.ps1`. Installation must establish the
   active disable switch first, publish only the pinned job, register it, leave
   the running reader untouched, and restore `/` read-only.
15. Select exactly one mode with `enable-standard` or
   `enable-framework-stop`. Disconnect USB data, reboot, and require the
   reboot-scoped
   trace `/tmp/lazying-koreader-autostart.trace` to reach:

   ```text
   phase=started
   phase=native-ready
   phase=ambient-brightness-applied mode=0
   phase=launching mode=<selected-mode>
   ```

   Require `reader.lua`, job `start/running`, both managed SSH logins, the
   selected regular marker, pinned job/source/patch hashes, manual brightness,
   and a read-only root. Test sleep/wake and Wi-Fi/SSH. Exit KOReader and wait
   at least 45 seconds; require job `stop/waiting`, no `reader.lua`, no relaunch,
   and—especially in framework-stop mode—a restored stock UI.

## Recovery

- Preserve the completed Store-attempt manifests and backups; its rollback and
  regeneration actions are no longer part of the active route.
- Before the browser exploit runs, use only
  `UndoWinterBreak2 -ConfirmedAirplaneMode`. It restores/removes unchanged files
  in its own manifest and leaves the Store record intact.
- After `winterbreak.log` records execution, never use `UndoWinterBreak2`.
  Keep Airplane Mode enabled, remove a partial root OTA if present, install and
  run Universal Hotfix, prove it with `VerifyHotfix`, then repair only the
  failed later layer.
- If the hotfix probe or KOReader copy is interrupted, rerun its same guarded
  action. Preserve the recorded nonce and result; after durable KOReader filler
  authorization, do not recreate the filler.
- If a root `emergency.sh` appears, do not run it or overwrite it. Identify its
  owner and keep commissioning stopped until it is safely removed.
- Use `scripts/sync-kindle-book.ps1` for literal Unicode paths and verify the
  destination SHA-256. It backs up differing destination files locally under
  ignored `device-backups/`.
- To disable boot launch, rename whichever single underscore mode marker exists
  to `DISABLE_KOREADER_AUTOSTART` over USB, or use the SSH manager's `disable`
  action. Select a mode only through the audited SSH manager; USB-only enable
  is forbidden because USB cannot inspect the root job.
- For the observed `initial_tev` wake crash, use only
  `manage-koreader-stability.sh`; require the exact original/patched/rollback
  hashes and never hand-edit an unknown source. Upload the current repository
  manager before maintenance; it resumes owned interruption states, refuses
  foreign rollback-directory entries, and accepts uninstall only at exact
  `original:absent`. It takes effect next launch and its uninstall restores the
  pinned original.
- Absence of `/mnt/us/ENABLE_AMAZON_AUTO_BRIGHTNESS` means manual brightness;
  an exact regular file opts in. KOReader AutoWarmth is a separate time/sun
  warmth scheduler. Avoid competing schedulers and direct backlight sysfs writes.
- If an enabled boot remains in USB drive mode, disconnect USB data and leave
  the screen untouched. The bounded job can continue after `/mnt/us` returns;
  otherwise open KOReader manually and read its reboot-scoped `/tmp` trace.

Report each gate as completed or pending. Never describe the Kindle as fully
commissioned until managed-key SSH, verified library state, automatic KOReader
boot launch, normal exit, and the no-respawn recovery test have all passed.
