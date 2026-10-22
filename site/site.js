// Copy buttons on code blocks and a light/dark toggle. The site works without this file.
(function () {
  "use strict";

  var root = document.documentElement;

  function storedTheme() {
    try {
      var value = window.localStorage.getItem("wenchang-theme");
      return value === "light" || value === "dark" ? value : null;
    } catch (e) {
      return null;
    }
  }

  function saveTheme(value) {
    try {
      window.localStorage.setItem("wenchang-theme", value);
    } catch (e) {
      // Storage can be blocked; the choice then lasts for this page view only.
    }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }

  var saved = storedTheme();
  if (saved) {
    root.setAttribute("data-theme", saved);
  }

  function currentTheme() {
    return root.getAttribute("data-theme") || systemTheme();
  }

  function addThemeToggle() {
    var slot = document.querySelector(".site-header .inner");
    if (!slot) {
      return;
    }
    var button = document.createElement("button");
    button.type = "button";
    button.className = "theme-toggle";

    function label() {
      var next = currentTheme() === "dark" ? "light" : "dark";
      button.textContent = next === "dark" ? "Dark mode" : "Light mode";
      button.setAttribute("aria-label", "Switch to " + next + " mode");
    }

    button.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      saveTheme(next);
      label();
    });
    label();
    slot.appendChild(button);
  }

  function addCopyButtons() {
    var blocks = document.querySelectorAll(".content pre");
    Array.prototype.forEach.call(blocks, function (pre) {
      var wrap = document.createElement("div");
      wrap.className = "code-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      var button = document.createElement("button");
      button.type = "button";
      button.className = "copy-btn";
      button.textContent = "Copy";
      button.setAttribute("aria-label", "Copy code to clipboard");
      button.addEventListener("click", function () {
        var text = pre.innerText;
        function done(ok) {
          button.textContent = ok ? "Copied" : "Press Ctrl+C";
          window.setTimeout(function () {
            button.textContent = "Copy";
          }, 1800);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(
            function () {
              done(true);
            },
            function () {
              done(false);
            }
          );
        } else {
          done(false);
        }
      });
      wrap.appendChild(button);
    });
  }

  function init() {
    addThemeToggle();
    addCopyButtons();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
