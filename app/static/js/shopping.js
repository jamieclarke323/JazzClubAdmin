/* Shopping list behaviour. */
(function () {
  "use strict";
  const App = window.App;
  const board = document.getElementById("shop-board");
  const form = document.getElementById("shop-add");
  const input = document.getElementById("shop-input");
  const suggestBox = document.getElementById("shop-suggest");
  const sheet = document.getElementById("shop-sheet");
  const editForm = document.getElementById("shop-edit");
  const groupToggle = document.getElementById("group-toggle");
  if (!board || !form) return;

  let refreshing = null;
  const poller = App.poll({
    versionUrl: board.dataset.versionUrl,
    version: (document.getElementById("board-meta") || {}).dataset?.version,
    onChange: () => refresh(),
  });

  async function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      try {
        const html = await App.fetchHTML(board.dataset.listUrl);
        const y = window.scrollY;
        board.innerHTML = html;
        window.scrollTo(0, y);
        const meta = document.getElementById("board-meta");
        if (meta) {
          poller.setVersion(meta.dataset.version);
          App.setBadge("nav-shopping-count", meta.dataset.remaining);
        }
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  /* ---- Adding ---- */
  async function addItem(name, extra) {
    const data = Object.assign({ name }, extra || {});
    const res = await App.api("/shopping/items", data);
    App.haptic();
    if (res.status === "exists") {
      App.toast(`${res.item.name} is already on the list`);
      flash(res.item.id);
    } else if (res.status === "restored") {
      App.toast(`${res.item.name} is back on the list`, { type: "success" });
    }
    await refresh();
    if (res.status === "exists") flash(res.item.id);
    return res;
  }

  function flash(id) {
    const li = board.querySelector(`.item[data-id="${id}"]`);
    if (!li) return;
    li.style.transition = "background .3s";
    li.style.background = "var(--accent-soft)";
    setTimeout(() => (li.style.background = ""), 900);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = input.value.trim();
    if (!name) return;
    input.value = "";
    hideSuggestions();
    try {
      await addItem(name);
    } catch (_) {
      input.value = name;
    }
    input.focus();
  });

  /* ---- Suggestions while typing ---- */
  let suggestTimer = null;
  let suggestSeq = 0;
  input.addEventListener("input", () => {
    clearTimeout(suggestTimer);
    const q = input.value.trim();
    if (q.length < 1) return hideSuggestions();
    suggestTimer = setTimeout(() => loadSuggestions(q), 140);
  });
  input.addEventListener("blur", () => setTimeout(hideSuggestions, 150));
  input.addEventListener("focus", () => {
    if (input.value.trim()) loadSuggestions(input.value.trim());
  });

  async function loadSuggestions(q) {
    const seq = ++suggestSeq;
    try {
      const res = await fetch(`/shopping/suggest?q=${encodeURIComponent(q)}`, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch", Accept: "application/json" },
      });
      if (!res.ok || seq !== suggestSeq) return;
      const data = await res.json();
      renderSuggestions(data.suggestions || [], q);
    } catch (_) {
      hideSuggestions();
    }
  }

  function renderSuggestions(items, q) {
    const filtered = items.filter((s) => s.name.toLowerCase() !== q.toLowerCase() || s.on_list);
    if (!filtered.length) return hideSuggestions();
    suggestBox.innerHTML = "";
    filtered.forEach((s) => {
      const b = document.createElement("button");
      b.type = "button";
      const name = document.createElement("span");
      name.textContent = s.name;
      b.appendChild(name);
      if (s.on_list) {
        const on = document.createElement("span");
        on.className = "s-on";
        on.textContent = "on list";
        b.appendChild(on);
      }
      const cat = document.createElement("span");
      cat.className = "s-cat";
      cat.textContent = s.category;
      b.appendChild(cat);
      b.addEventListener("pointerdown", (e) => e.preventDefault());
      b.addEventListener("click", async () => {
        input.value = "";
        hideSuggestions();
        await addItem(s.name, { category: s.category });
        input.focus();
      });
      suggestBox.appendChild(b);
    });
    suggestBox.hidden = false;
  }

  function hideSuggestions() {
    suggestBox.hidden = true;
    suggestBox.innerHTML = "";
  }

  /* ---- Board interactions ---- */
  board.addEventListener("click", async (e) => {
    const again = e.target.closest(".chip-add");
    if (again) {
      again.disabled = true;
      try {
        await addItem(again.dataset.name, { category: again.dataset.category });
      } finally {
        again.disabled = false;
      }
      return;
    }

    const clear = e.target.closest("#clear-checked");
    if (clear) {
      if (clear.dataset.armed !== "1") {
        clear.dataset.armed = "1";
        clear.textContent = `Clear ${clear.dataset.count} — tap to confirm`;
        setTimeout(() => {
          if (clear.isConnected) {
            clear.dataset.armed = "0";
            clear.textContent = "Clear";
          }
        }, 3000);
        return;
      }
      await App.api("/shopping/clear-checked");
      App.toast("Basket cleared");
      refresh();
      return;
    }

    const edit = e.target.closest(".edit");
    if (edit) {
      openEdit(edit.closest(".item"));
      return;
    }

    const li = e.target.closest(".item");
    if (li && (e.target.closest(".check") || e.target.closest(".item-body"))) {
      toggleItem(li);
    }
  });

  board.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("item-body")) {
      e.preventDefault();
      toggleItem(e.target.closest(".item"));
    }
  });

  async function toggleItem(li) {
    const id = li.dataset.id;
    const wasChecked = li.classList.contains("is-checked");
    App.haptic();
    li.classList.toggle("is-checked", !wasChecked);
    li.classList.add("removing");
    try {
      await App.api(`/shopping/items/${id}/toggle`);
      await refresh();
      if (!wasChecked) {
        const name = JSON.parse(li.dataset.item).name;
        App.toast(`${name} ticked off`, {
          undo: async () => {
            await App.api(`/shopping/items/${id}/toggle`);
            refresh();
          },
          duration: 4000,
        });
      }
    } catch (_) {
      refresh();
    }
  }

  /* ---- Edit sheet ---- */
  function openEdit(li) {
    const item = JSON.parse(li.dataset.item);
    editForm.elements.id.value = item.id;
    editForm.elements.name.value = item.name;
    editForm.elements.quantity.value = item.quantity;
    App.setRadio(editForm, "category", item.category);
    App.openSheet(sheet);
  }

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(editForm);
    try {
      await App.api(`/shopping/items/${fd.get("id")}`, {
        name: fd.get("name"),
        quantity: fd.get("quantity") || "",
        category: fd.get("category") || "groceries",
      });
      App.closeSheet(sheet);
      refresh();
    } catch (_) {
      /* toast shown */
    }
  });

  document.getElementById("shop-delete").addEventListener("click", async () => {
    const id = editForm.elements.id.value;
    await App.api(`/shopping/items/${id}/delete`);
    App.closeSheet(sheet);
    App.toast("Item removed");
    refresh();
  });

  /* ---- Grouping toggle ---- */
  if (groupToggle) {
    groupToggle.addEventListener("click", async () => {
      const res = await App.api("/shopping/group");
      groupToggle.textContent = res.grouped ? "Ungroup" : "Group";
      groupToggle.setAttribute("aria-pressed", String(res.grouped));
      refresh();
    });
  }
})();
