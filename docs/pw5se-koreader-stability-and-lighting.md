# PW5SE KOReader stability and lighting controls

This record applies only to the personally owned Paperwhite 11th generation /
PW5SE on firmware `5.15.1`, running KOReader `kindlepw2` v2026.07.1. The live
audit and guarded installation were performed on 2026-08-13. Serial numbers,
private keys, and private log contents are intentionally omitted.

## What caused the apparent freezes

The evidence showed two KOReader problems and one independent lighting
controller, not a kernel or storage failure:

1. The KOReader crash log contains one definitive wake-time crash at
   `frontend/device/gesturedetector.lua:295`. A malformed two-contact frame
   left `initial_tev` unset; `Contact:isTwoFingerTap` dereferenced it and
   terminated `reader.lua`. The managed Upstart job deliberately does not
   respawn, so its correct post-crash result was the stock Kindle interface.
2. While a very large PDF was open, KOReader repeatedly logged that only about
   19% (roughly 91-95 MiB of 474 MiB) was free and evicted half its document
   cache. Live RSS was approximately 111 MiB for KOReader, 101 MiB for Amazon
   `cvm`, and 23 MiB for `KPPMainApp`. No OOM kill, kernel panic, filesystem
   error, watchdog death, or reader segfault was found.
3. KOReader AutoWarmth was off, but Amazon `powerd` still reported `flAuto=1`
   and live ALS activity. That controller can alter brightness underneath
   KOReader. Amazon's warmth schedule and night-light controls were already
   off, and KOReader Automatic Dimmer was also off.

The upstream history confirms that broken Kindle multi-touch frames are a
known class of problem: [issue #13706](https://github.com/koreader/koreader/issues/13706)
and [PR #13714](https://github.com/koreader/koreader/pull/13714). The exact
v2026.07.1 source still dereferences all four contact-event fields without a
final nil guard, so this repository adds a narrow, reversible last line of
defense for the crash actually observed on this device.

## Installed stability guard

`assets/koreader-lazy/manage-koreader-stability.sh` manages only:

```text
/mnt/us/koreader/frontend/device/gesturedetector.lua
```

It is firmware-gated and pins both states:

```text
original  3a2d733a66f94e5cb1cc003c7ba736a03006e7c9242211adc243d74bc2c67db8
patched   8abc677d5eee22ae59f5454530eb79831f0e0f96717536edb76589de40f84ad5
```

The guard checks `self` and the buddy contact for complete `current_tev` and
`initial_tev` values. An incomplete two-finger tap is ignored and logged rather
than crashing all of KOReader. Valid gestures follow the original code path.

The exact original is retained at:

```text
/mnt/us/koreader/.lazying-art-stability/gesturedetector-v2026.07.1.original.lua
```

The manager refuses links, special files, unknown hashes, or an unsafe rollback
state. It stages and verifies a same-directory temporary file, publishes by
atomic rename, and never signals the running reader. The repository manager was
additionally hardened after the live installation to resume interruption after
rollback-directory creation, rollback staging/publication, target restoration,
and rollback cleanup; it refuses foreign directory entries and reports success
only at exact `original:absent`. Its repository SHA-256 is
`dec93aa616d09587328af68e87efcd0d17e6119d8313186d51690128b5f93706`.
The live install used the earlier manager hash
`681f4e2afe6eb0bdb3672e1e425337cbe480f2721f60d7a8864b273340cf87b5`
and reached the clean `patched:original` state, so the installed guard is safe;
upload the current repository manager before future uninstall or maintenance.
Installation takes effect on the next KOReader launch. Revert only through the
current manager:

```sh
/bin/sh /tmp/manage-koreader-stability.sh status
/bin/sh /tmp/manage-koreader-stability.sh uninstall
```

## Lower-memory boot modes

Autostart v2 retains one non-respawning Upstart job and rotates exactly one
regular marker file among three modes:

| Exact `/mnt/us` marker | Next-boot behavior |
| --- | --- |
| `DISABLE_KOREADER_AUTOSTART` | Native Kindle UI; KOReader autostart disabled |
| `_DISABLE_KOREADER_AUTOSTART` | KOReader `--asap`; Amazon framework remains resident |
| `_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP` | KOReader `--framework_stop`; Amazon framework is stopped while reading and restored on KOReader exit |

Missing, multiple, linked, directory, or special-file markers fail closed to
the native UI. Mode changes are same-filesystem renames; USB may disable either
enabled mode, but only the audited SSH manager may enable or select one:

```sh
/bin/sh /tmp/manage-koreader-autostart.sh enable-standard
/bin/sh /tmp/manage-koreader-autostart.sh enable-framework-stop
/bin/sh /tmp/manage-koreader-autostart.sh disable
```

The exact v2 job SHA-256 is:

```text
87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd
```

The manager recognizes only the exact accepted v1 hash as an upgrade source,
first establishes the disabled marker, replaces the root-owned job atomically,
reloads Upstart without restarting the live session, and restores `/` to its
original read-only state. The repository manager was further hardened offline
after deployment: if an exact legacy job has a malformed three-marker topology,
it first creates the active v1 stop marker when absent, preserves all suspect
objects, and only then refuses strict v2 validation. This future-upgrade change
does not alter the already installed v2 job or its hash.

Framework-stop is selected for the next boot because it removes the two large
Amazon UI processes from the active reading memory budget. It uses KOReader's
unchanged upstream launcher, which restarts `lab126_gui` during cleanup. This
new mode has been installed and statically/live audited, but it was deliberately
not reboot-tested while the owner was reading. Treat the first disconnected-USB
reboot as its acceptance test. If anything is wrong, exit KOReader normally;
for the following boot, rename the framework-stop marker to
`DISABLE_KOREADER_AUTOSTART` over USB or run the manager's `disable` action over
SSH. Never kill the launcher: normal exit is what restores the framework and
`volumd`.

## Brightness and warmth: what is automatic

There are three distinct features:

- **Amazon auto brightness** uses the PW5SE ambient-light sensor and changes
  brightness. It was the unexpected controller found active.
- **KOReader AutoWarmth** changes warmth based on time, a schedule, or sun
  position. It is not ambient auto brightness.
- **KOReader Automatic Dimmer** dims after inactivity. It is currently off
  (`autodim_starttime_minutes=-1`).

Amazon's runtime auto-brightness value was set to `0`, but its persistent stock
configuration still recorded `1`; a one-time LIPC write is therefore not a
durable fix. The pinned KOReader user patch
`2-lazying-art-ambient-brightness.lua` applies the selected value at every
KOReader startup and again one second after each resume, after Amazon finishes
restoring the light. It uses typed LIPC through KOReader's existing `powerd`
handle and never writes backlight sysfs directly.

Manual brightness is the safe default. To opt into Amazon ambient auto
brightness, create this exact **regular file** in the Kindle USB root:

```text
ENABLE_AMAZON_AUTO_BRIGHTNESS
```

To turn ambient auto brightness off again, remove that opt-in file. The choice
is applied on the next KOReader start or sleep/wake cycle. A link, directory, or
other special file is treated as off. The current deployed state has no opt-in
file, so ambient auto brightness is off.

For manual light control inside KOReader:

1. Tap the top of the screen.
2. Open **Settings** (gear) -> **Frontlight**.
3. Adjust **Brightness** and **Warmth** independently.

Default gestures can also explain an accidental change:

- left-edge swipe up/down changes brightness;
- right-edge swipe up/down changes warmth;
- two-finger swipe up/down changes brightness;
- bottom-left corner tap toggles the frontlight.

Change or disable them under **Settings -> Taps and gestures -> Gesture
manager**.

To enable automatic warmth, use **Settings -> Screen -> Auto warmth and night
mode -> Activate**, then choose sun position, fixed schedule, closer to noon,
or closer to midnight. Configure its location/schedule and warmth values in the
same submenu. To turn it off, tap the currently checked activation choice so
no mode remains checked. If the submenu is missing, enable the plugin under
**Tools -> More tools -> Plugin management** and restart KOReader when asked.
Do not enable both Amazon's warmth schedule and KOReader AutoWarmth; two
schedulers would compete.

## Live state left on 2026-08-13

- The current KOReader session remained running and was not restarted.
- The gesture source is the exact patched hash and its rollback is the exact
  original hash; both compile/state checks passed.
- The ambient-brightness patch is installed with SHA-256
  `b762305949d6c06cd3bd1415a689e058959ed502ebcff9c69b91810c0302fb0c`.
- Runtime `flAuto=0`; AutoWarmth, Amazon warmth scheduling/night light, and
  Automatic Dimmer are off.
- The v2 job matches its pin, is registered, and framework-stop is selected for
  the next boot. `/` is read-only, `preventScreenSaver=0`, and
  `/mnt/us/emergency.sh` remains absent.
- Repository transaction managers were hardened after disconnection; their
  improvements affect only future maintenance and do not require the Kindle to
  remain connected for the current clean job/guard state.
- No owned transfer temporary file remains. *Fathers and Sons* is present at
  `documents/LinguaLeaf/en-jp-zh-blackwhite` with SHA-256
  `bb922e485a882a957ee26e96ff4d23e76c6ece3f27c54538d019be7826337926`.
- No post-change reboot claim is made. On the first boot, disconnect USB data,
  allow the 30-second recovery window, then verify KOReader, sleep/wake,
  brightness, Wi-Fi/SSH, and a clean **Exit KOReader** return to the stock UI.
