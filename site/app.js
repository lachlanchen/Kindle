(function () {
  "use strict";

  var bundle = window.KINDLE_I18N;
  if (!bundle || !bundle.messages || !bundle.messages.en) {
    return;
  }

  var supported = Object.keys(bundle.messages);
  var timezone = "";
  try {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (error) {
    timezone = "";
  }

  function normalizeLanguage(value) {
    if (!value) {
      return null;
    }

    var code = String(value).trim().replace(/_/g, "-").toLowerCase();
    if (code.indexOf("zh") === 0) {
      if (
        code.indexOf("hant") >= 0 ||
        /-(tw|hk|mo)(-|$)/.test(code) ||
        /Asia\/(Taipei|Hong_Kong|Macau)/i.test(timezone)
      ) {
        return "zh-Hant";
      }
      return "zh-Hans";
    }

    var shortCode = code.split("-")[0];
    var match = supported.find(function (item) {
      return item.toLowerCase() === shortCode;
    });
    return match || null;
  }

  function languageFromTimezone() {
    var zones = [
      [/Asia\/(Hong_Kong|Taipei|Macau)/i, "zh-Hant"],
      [/Asia\/(Shanghai|Chongqing|Harbin|Urumqi)/i, "zh-Hans"],
      [/Asia\/Tokyo/i, "ja"],
      [/Asia\/Seoul/i, "ko"],
      [/Asia\/(Ho_Chi_Minh|Saigon)/i, "vi"],
      [/Asia\/(Riyadh|Dubai|Baghdad|Qatar|Kuwait|Beirut|Amman)/i, "ar"],
      [/Europe\/(Paris|Brussels|Monaco)/i, "fr"],
      [/Europe\/(Madrid|Andorra)/i, "es"],
      [/Europe\/(Berlin|Vienna|Zurich)/i, "de"],
      [/Europe\/(Moscow|Kaliningrad|Samara)/i, "ru"]
    ];

    for (var index = 0; index < zones.length; index += 1) {
      if (zones[index][0].test(timezone)) {
        return zones[index][1];
      }
    }
    return null;
  }

  function initialLanguage() {
    var queryLanguage = normalizeLanguage(new URLSearchParams(window.location.search).get("lang"));
    if (queryLanguage) {
      return queryLanguage;
    }

    try {
      var savedLanguage = normalizeLanguage(window.localStorage.getItem("kindle-sender-language"));
      if (savedLanguage) {
        return savedLanguage;
      }
    } catch (error) {
      // Storage can be unavailable in strict privacy modes.
    }

    var browserLanguages = navigator.languages && navigator.languages.length
      ? navigator.languages
      : [navigator.language];

    for (var index = 0; index < browserLanguages.length; index += 1) {
      var browserLanguage = normalizeLanguage(browserLanguages[index]);
      if (browserLanguage) {
        return browserLanguage;
      }
    }

    return languageFromTimezone() || "en";
  }

  var currentLanguage = initialLanguage();

  function text(key) {
    var local = bundle.messages[currentLanguage] || bundle.messages.en;
    return local[key] || bundle.messages.en[key] || key;
  }

  function operatingSystem() {
    var source = "";
    if (navigator.userAgentData && navigator.userAgentData.platform) {
      source = navigator.userAgentData.platform;
    } else {
      source = navigator.platform + " " + navigator.userAgent;
    }

    if (/Win/i.test(source)) {
      return "windows";
    }
    if (/Mac|iPhone|iPad/i.test(source)) {
      return "mac";
    }
    if (/Linux|X11/i.test(source)) {
      return "linux";
    }
    return "generic";
  }

  var detectedOS = operatingSystem();

  function updatePrimaryDownload() {
    var label = document.querySelector("[data-primary-label]");
    if (label) {
      label.textContent = text("cta." + detectedOS);
    }
  }

  function updateUrl(language) {
    var url = new URL(window.location.href);
    url.searchParams.set("lang", language);
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
  }

  function applyLanguage(language, persist) {
    currentLanguage = language;
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";

    document.querySelectorAll("[data-i18n]").forEach(function (element) {
      element.textContent = text(element.getAttribute("data-i18n"));
    });

    document.title = text("meta.title");
    var description = document.querySelector('meta[name="description"]');
    var ogTitle = document.querySelector('meta[property="og:title"]');
    var ogDescription = document.querySelector('meta[property="og:description"]');
    if (description) {
      description.content = text("meta.description");
    }
    if (ogTitle) {
      ogTitle.content = text("meta.title");
    }
    if (ogDescription) {
      ogDescription.content = text("meta.description");
    }

    var select = document.querySelector("[data-language-select]");
    if (select) {
      select.value = language;
      select.setAttribute("aria-label", text("a11y.language"));
    }

    var menu = document.querySelector("[data-menu-button]");
    if (menu) {
      menu.setAttribute("aria-label", text("a11y.menu"));
    }

    updatePrimaryDownload();
    updateUrl(language);

    if (persist) {
      try {
        window.localStorage.setItem("kindle-sender-language", language);
      } catch (error) {
        // The selected language still applies for this visit.
      }
    }
  }

  applyLanguage(currentLanguage, false);

  var languageSelect = document.querySelector("[data-language-select]");
  if (languageSelect) {
    languageSelect.addEventListener("change", function (event) {
      applyLanguage(event.target.value, true);
    });
  }

  var menuButton = document.querySelector("[data-menu-button]");
  var navigation = document.querySelector("[data-nav]");

  function closeMenu() {
    if (!menuButton || !navigation) {
      return;
    }
    menuButton.setAttribute("aria-expanded", "false");
    navigation.classList.remove("open");
  }

  if (menuButton && navigation) {
    menuButton.addEventListener("click", function () {
      var isOpen = menuButton.getAttribute("aria-expanded") === "true";
      menuButton.setAttribute("aria-expanded", String(!isOpen));
      navigation.classList.toggle("open", !isOpen);
    });

    navigation.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeMenu);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeMenu();
      }
    });
  }

  var header = document.querySelector("[data-header]");
  function updateHeader() {
    if (header) {
      header.classList.toggle("scrolled", window.scrollY > 10);
    }
  }
  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  var revealItems = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var delay = Number(entry.target.getAttribute("data-delay") || 0);
          window.setTimeout(function () {
            entry.target.classList.add("visible");
          }, delay);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -30px" });

    revealItems.forEach(function (item) {
      observer.observe(item);
    });
  } else {
    revealItems.forEach(function (item) {
      item.classList.add("visible");
    });
  }

  var year = document.querySelector("[data-year]");
  if (year) {
    year.textContent = String(new Date().getFullYear());
  }

  var releasePage = "https://github.com/lachlanchen/Kindle/releases/latest";
  var apiUrl = "https://api.github.com/repos/lachlanchen/Kindle/releases/latest";
  var assetLinks = {};

  function findAsset(assets, predicates) {
    return assets.find(function (asset) {
      var name = asset.name.toLowerCase();
      return predicates.every(function (predicate) {
        return predicate.test(name);
      });
    });
  }

  function bindAssets(assets) {
    var windows = findAsset(assets, [/win/, /\.exe$/]);
    var macArm = findAsset(assets, [/(mac|darwin)/, /(arm|aarch64|apple)/]);
    var macIntel = findAsset(assets, [/(mac|darwin)/, /(intel|x64|x86_64)/]);
    var linux = findAsset(assets, [/linux/, /(tar\.gz|appimage)$/]);

    assetLinks.windows = windows && windows.browser_download_url;
    assetLinks.macArm = macArm && macArm.browser_download_url;
    assetLinks.macIntel = macIntel && macIntel.browser_download_url;
    assetLinks.linux = linux && linux.browser_download_url;

    Object.keys(assetLinks).forEach(function (platform) {
      var link = document.querySelector('[data-download="' + platform + '"]');
      if (link && assetLinks[platform]) {
        link.href = assetLinks[platform];
      }
    });

    var primary = document.querySelector("[data-primary-download]");
    if (!primary) {
      return;
    }
    if (detectedOS === "windows" && assetLinks.windows) {
      primary.href = assetLinks.windows;
    } else if (detectedOS === "linux" && assetLinks.linux) {
      primary.href = assetLinks.linux;
    } else {
      primary.href = detectedOS === "mac" ? "#downloads" : releasePage;
    }
  }

  fetch(apiUrl, { headers: { Accept: "application/vnd.github+json" } })
    .then(function (response) {
      if (!response.ok) {
        throw new Error("Release lookup failed");
      }
      return response.json();
    })
    .then(function (release) {
      bindAssets(release.assets || []);
    })
    .catch(function () {
      // Static release links remain usable when GitHub API access is unavailable.
    });
})();
