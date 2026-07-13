KINDLE + KOREADER HANDOFF PACKAGE
=================================

Prepared by AgInTi Flow, LazyingArt LLC
https://flow.lazying.art
https://lazying.art

Recommended app and downloads:
  https://lachlanchen.github.io/Kindle/

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
  keys\kindle_handoff_rsa.pub      Public key installed on Kindle

SECURITY WARNING
----------------
The private key has no passphrase and is deliberately embedded in the PDF
for appliance-style handoff. It must be used ONLY for this Kindle. Never
authorize it on a computer, server, router, source-hosting account, cloud
account, or any other device. Anyone with this package can access the Kindle
while KOReader SSH is running and reachable.

Quick SSH:
  connect-kindle.cmd 192.168.1.109

Quick wireless transfer:
  powershell -ExecutionPolicy Bypass -File .\send-books-to-kindle.ps1 -KindleIp 192.168.1.109 "C:\Books\Example.pdf"

Rebuild:
  powershell -ExecutionPolicy Bypass -File .\build-guide.ps1

The IP address is an example and may change. KOReader SSH uses port 2222.
Automatic KOReader launch is intentionally disabled until a safe launcher
with a USB recovery marker has been installed and tested.
