KINDLE + KOREADER HANDOFF PACKAGE
=================================

Prepared by AgInTi Flow, LazyingArt LLC
https://flow.lazying.art
https://lazying.art

Recommended app, product page, and guides:
  https://lazying.art/eink
  https://github.com/lachlanchen/Kindle/releases/latest
  https://lachlanchen.github.io/Kindle/?stay=1  (original site, no redirect)

Kindle Book Sender 1.3 remembers devices and transfer history, displays Kindle
storage usage, supports 11 interface languages, starts maximized, and adapts to
smaller windows. The packaged Windows app can add itself to Start and request a
taskbar pin without administrator access.

Start with:
  kindle-koreader-handoff.pdf
  kindle-koreader-handoff-zh-CN.pdf

Contents:
  kindle-koreader-handoff.tex      XeLaTeX source
  connect-kindle.cmd               Connect to KOReader SSH
  send-books-to-kindle.ps1         Send books over Wi-Fi
  install-public-key-usb.ps1       Install the public key by USB
  ssh-config.example               Optional SSH alias template
  build-guide.ps1                  Rebuild the PDF
  keys\kindle_handoff_rsa          PRIVATE Kindle-only key
  keys\kindle_handoff_rsa.pub      Public key to authorize on Kindle

SECURITY WARNING
----------------
The private key has no passphrase and is deliberately embedded in the PDF
for appliance-style handoff. It must be used ONLY for the owner's paired
KOReader Kindles. Never authorize it on a computer, server, router,
source-hosting account, cloud account, unrelated Kindle, or any other device.
Anyone with this package can access a paired Kindle while KOReader SSH is
running and reachable.

Quick SSH:
  connect-kindle.cmd 192.168.1.109

Quick wireless transfer:
  powershell -ExecutionPolicy Bypass -File .\send-books-to-kindle.ps1 -KindleIp 192.168.1.109 "C:\Books\Example.pdf"

New-computer pairing:
  In KOReader, stop SSH, enable Login without password, and start SSH again.
  In Kindle Book Sender, enter the displayed address, check the no-password
  first-connection option, and connect. The app installs and verifies its own
  per-computer public key automatically.

Rebuild:
  powershell -ExecutionPolicy Bypass -File .\build-guide.ps1

The IP address is an example and may change. KOReader SSH uses port 2222.
Automatic KOReader launch is intentionally disabled until a safe launcher
with a USB recovery marker has been installed and tested.
