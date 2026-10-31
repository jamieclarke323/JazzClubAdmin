/* Shared helpers: fetch with CSRF, toasts with undo, bottom sheets, polling. */
(function () {
  "use strict";

  const App = (window.App = window.App || {});

  App.api = async function (url, data, method) {
    method = method || "POST";
    const res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": window.APP.csrf,
        "X-Requested-With": "fetch",
        Accept: "application/json",
      },
      body: method === "GET" ? undefined : JSON.stringify(data || {}),
    });
    let body = {};
    try {
      body = await res.json();
    } catch (_) {
      /* non-JSON response */
    }
    if (body && body.redirect) {
      window.location.href = body.redirect;
      throw new Error("redirect");
    }
    if (!res.ok || body.ok === false) {
      const message = (body && body.error) || "Something went wrong";
      App.toast(message, { type: "error" });
      throw new Error(message);
    }
    return body;
  };

  App.fetchHTML = async function (url) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
    });
    if (res.redirected && /\/auth\/login/.test(res.url)) {
      window.location.href = res.url;
      throw new Error("redirect");
    }
    if (!res.ok) throw new Error("Failed to load");
    return res.text();
  };

  /* ---- Toasts ---- */
  const toasts = document.getElementById("toasts");
  App.toast = function (message, opts) {
    opts = opts || {};
    const el = document.createElement("div");
    el.className = "toast " + (opts.type || "");
    el.setAttribute("role", "status");
    el.textContent = message;
    let timer;
    const dismiss = () => {
      clearTimeout(timer);
      if (el.parentNode) el.parentNode.removeChild(el);
    };
    if (opts.undo) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = opts.undoLabel || "Undo";
      btn.addEventListener("click", () => {
        dismiss();
        opts.undo();
      });
      el.appendChild(btn);
    }
    while (toasts.children.length >= 3) toasts.removeChild(toasts.firstChild);
    toasts.appendChild(el);
    timer = setTimeout(dismiss, opts.duration || (opts.undo ? 6000 : 2600));
    return dismiss;
  };

  App.haptic = function () {
    if (navigator.vibrate) navigator.vibrate(8);
  };

  /* ---- Bottom sheets (native <dialog>) ---- */
  App.openSheet = function (dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  };
  App.closeSheet = function (dialog) {
    if (dialog.open) dialog.close();
  };
  document.querySelectorAll("dialog.sheet").forEach((dialog) => {
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close();
    });
    dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
  });

  /* ---- Radios inside chips: set by value ---- */
  App.setRadio = function (form, name, value) {
    const radios = form.querySelectorAll(`input[type=radio][name="${name}"]`);
    let matched = false;
    radios.forEach((r) => {
      r.checked = String(r.value) === String(value == null ? "" : value);
      if (r.checked) matched = true;
    });
    if (!matched && radios.length) radios[0].checked = true;
  };

  /* ---- Local date helpers ---- */
  App.isoDate = function (d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };
  App.quickDate = function (key) {
    const d = new Date();
    d.setHours(12, 0, 0, 0);
    if (key === "today") return App.isoDate(d);
    if (key === "tomorrow") {
      d.setDate(d.getDate() + 1);
      return App.isoDate(d);
    }
    if (key === "weekend") {
      const day = d.getDay();
      const add = day === 6 ? 7 : (6 - day + 7) % 7 || 7;
      d.setDate(d.getDate() + add);
      return App.isoDate(d);
    }
    if (key === "nextweek") {
      const day = d.getDay();
      const toMonday = ((8 - day) % 7) || 7;
      d.setDate(d.getDate() + toMonday);
      return App.isoDate(d);
    }
    return "";
  };

  /* ---- Polling for changes made by other household members ---- */
  App.poll = function (opts) {
    let current = opts.version;
    let timer = null;
    const interval = opts.interval || 12000;

    async function check() {
      if (document.visibilityState !== "visible") return;
      try {
        const res = await fetch(opts.versionUrl, {
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch", Accept: "application/json" },
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data.version !== undefined && String(data.version) !== String(current)) {
          current = data.version;
          opts.onChange(data.version);
        }
      } catch (_) {
        /* offline; try again later */
      }
    }
    function schedule() {
      clearInterval(timer);
      timer = setInterval(check, interval);
    }
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") check();
    });
    window.addEventListener("focus", check);
    window.addEventListener("online", check);
    schedule();
    return {
      setVersion(v) {
        current = v;
      },
    };
  };

  /* ---- Confirm forms ---- */
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  /* ---- Copy / share buttons ---- */
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const input = document.querySelector(btn.dataset.copy);
      try {
        await navigator.clipboard.writeText(input.value);
        App.toast("Invite link copied", { type: "success" });
      } catch (_) {
        input.select();
        document.execCommand("copy");
        App.toast("Invite link copied", { type: "success" });
      }
    });
  });
  const share = document.getElementById("share-invite");
  if (share && navigator.share) {
    share.hidden = false;
    share.addEventListener("click", () => {
      navigator.share({ title: share.dataset.shareTitle, url: share.dataset.shareUrl }).catch(() => {});
    });
  }

  /* ---- Flash messages ---- */
  (window.APP.flashes || []).forEach(([category, message]) => {
    App.toast(message, { type: category === "error" ? "error" : category === "success" ? "success" : "", duration: 4000 });
  });

  /* ---- Nav badge helpers ---- */
  App.setBadge = function (id, count) {
    const el = document.getElementById(id);
    if (!el) return;
    count = Number(count) || 0;
    el.textContent = count;
    el.hidden = count === 0;
  };

  /* ---- Service worker ---- */
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  }
})();
