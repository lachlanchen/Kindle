(function () {
  "use strict";

  var releaseBase = "https://github.com/lachlanchen/Kindle/releases/latest/download/";
  var downloads = {
    windows: {
      label: "Download for Windows",
      kicker: "Windows 10 or 11 · x64",
      url: releaseBase + "Kindle-Book-Sender-Windows-x64.exe"
    },
    linux: {
      label: "Download for Ubuntu",
      kicker: "Ubuntu / Linux · x86_64",
      url: releaseBase + "Kindle-Book-Sender-Linux-x86_64.tar.gz"
    },
    mac: {
      label: "Choose your Mac build",
      kicker: "Apple Silicon or Intel",
      url: "#mac-downloads"
    },
    unknown: {
      label: "Choose your platform",
      kicker: "Windows · Ubuntu · macOS",
      url: "#downloads"
    }
  };

  function detectPlatform() {
    var value = "";
    if (navigator.userAgentData && navigator.userAgentData.platform) {
      value = navigator.userAgentData.platform.toLowerCase();
    } else {
      value = (navigator.platform || navigator.userAgent || "").toLowerCase();
    }
    if (value.indexOf("win") !== -1) return "windows";
    if (value.indexOf("mac") !== -1) return "mac";
    if (value.indexOf("linux") !== -1 || value.indexOf("ubuntu") !== -1) return "linux";
    return "unknown";
  }

  var platform = detectPlatform();
  var selected = downloads[platform];
  var primary = document.getElementById("primary-download");
  var label = document.getElementById("primary-download-label");
  var kicker = document.getElementById("primary-download-kicker");
  if (primary && label && kicker) {
    primary.href = selected.url;
    label.textContent = selected.label;
    kicker.textContent = selected.kicker;
  }

  var detectedCard = document.querySelector('[data-platform-card="' + platform + '"]');
  if (detectedCard) detectedCard.classList.add("detected");

  var toggle = document.querySelector(".nav-toggle");
  var navigation = document.querySelector(".site-nav");
  if (toggle && navigation) {
    toggle.addEventListener("click", function () {
      var open = navigation.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    navigation.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        navigation.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -35px" });
    reveals.forEach(function (item) { observer.observe(item); });
  } else {
    reveals.forEach(function (item) { item.classList.add("visible"); });
  }
}());
