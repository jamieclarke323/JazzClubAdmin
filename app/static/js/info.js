/* Info page: items with attached photos/PDFs. */
(function () {
  "use strict";
  const App = window.App;
  const board = document.getElementById("info-board");
  const addForm = document.getElementById("info-add");
  const titleInput = document.getElementById("info-title");
  const filesInput = document.getElementById("info-files");
  const filesCount = document.getElementById("info-files-count");
  const previews = document.getElementById("info-previews");
  const search = document.getElementById("info-search");
  const sheet = document.getElementById("info-sheet");
  const editForm = document.getElementById("info-edit");
  const editAttachments = document.getElementById("edit-attachments");
  const editPreviews = document.getElementById("edit-previews");
  const lightbox = document.getElementById("lightbox");
  if (!board || !addForm) return;

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
        if (meta) poller.setVersion(meta.dataset.version);
        applySearch();
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  /* ---- Upload helper (multipart, CSRF header) ---- */
  async function upload(url, formData) {
    const res = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": window.APP.csrf, "X-Requested-With": "fetch", Accept: "application/json" },
      body: formData,
    });
    let body = {};
    try {
      body = await res.json();
    } catch (_) {
      /* ignore */
    }
    if (body.redirect) {
      window.location.href = body.redirect;
      throw new Error("redirect");
    }
    if (!res.ok || body.ok === false) {
      const msg = body.error || (res.status === 413 ? "That upload is too large." : "Something went wrong");
      App.toast(msg, { type: "error", duration: 5000 });
      throw new Error(msg);
    }
    return body;
  }

  /* ---- File previews ---- */
  function renderPreviews(input, container) {
    container.innerHTML = "";
    const files = Array.from(input.files || []);
    container.hidden = files.length === 0;
    files.forEach((file) => {
      const el = document.createElement("div");
      el.className = "preview";
      if (file.type.startsWith("image/")) {
        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.onload = () => URL.revokeObjectURL(img.src);
        img.alt = file.name;
        el.appendChild(img);
      } else {
        el.classList.add("preview-doc");
        el.textContent = file.name;
      }
      container.appendChild(el);
    });
  }

  filesInput.addEventListener("change", () => {
    const n = filesInput.files.length;
    filesCount.textContent = n;
    filesCount.hidden = n === 0;
    renderPreviews(filesInput, previews);
    if (n && !titleInput.value) titleInput.focus();
  });
  editForm.elements.files.addEventListener("change", () => renderPreviews(editForm.elements.files, editPreviews));

  /* ---- Add ---- */
  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!titleInput.value.trim()) return;
    const submit = addForm.querySelector("button[type=submit]");
    submit.disabled = true;
    submit.textContent = filesInput.files.length ? "Uploading…" : "Adding…";
    try {
      await upload("/info", new FormData(addForm));
      App.haptic();
      addForm.reset();
      filesCount.hidden = true;
      previews.hidden = true;
      previews.innerHTML = "";
      App.toast("Saved", { type: "success" });
      await refresh();
    } catch (_) {
      /* toast shown */
    } finally {
      submit.disabled = false;
      submit.textContent = "Add";
    }
  });

  /* ---- Search (client-side) ---- */
  function applySearch() {
    const q = search.value.trim().toLowerCase();
    let shown = 0;
    board.querySelectorAll(".info-item").forEach((el) => {
      const hit = !q || el.dataset.search.includes(q);
      el.hidden = !hit;
      if (hit) shown++;
    });
    let none = board.querySelector(".search-empty");
    if (q && shown === 0) {
      if (!none) {
        none = document.createElement("div");
        none.className = "empty search-empty";
        none.innerHTML = "<p>No matches.</p>";
        board.appendChild(none);
      }
    } else if (none) {
      none.remove();
    }
  }
  search.addEventListener("input", applySearch);

  /* ---- Board interactions ---- */
  board.addEventListener("click", (e) => {
    const thumb = e.target.closest(".thumb[data-src]");
    if (thumb) {
      openLightbox(thumb.dataset.src, thumb.dataset.name);
      return;
    }
    const edit = e.target.closest(".edit");
    if (edit) openEdit(edit.closest(".info-item"));
  });

  function openLightbox(src, name) {
    const img = document.getElementById("lightbox-img");
    img.src = src;
    img.alt = name;
    const dl = document.getElementById("lightbox-download");
    dl.href = src + (src.includes("?") ? "&" : "?") + "download=1";
    App.openSheet(lightbox);
  }
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox || e.target.id === "lightbox-img") lightbox.close();
  });
  lightbox.querySelector("[data-close]").addEventListener("click", () => lightbox.close());

  /* ---- Edit sheet ---- */
  function renderEditAttachments(item) {
    editAttachments.innerHTML = "";
    if (!item.attachments.length) {
      editAttachments.innerHTML = '<span class="muted small">No attachments yet.</span>';
      return;
    }
    item.attachments.forEach((a) => {
      const row = document.createElement("div");
      row.className = "attach-row";
      const name = document.createElement("span");
      name.className = "attach-name";
      name.textContent = a.name;
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "linkbtn danger";
      rm.textContent = "Remove";
      rm.addEventListener("click", async () => {
        if (!window.confirm(`Remove ${a.name}?`)) return;
        const res = await App.api(`/info/files/${a.id}/delete`);
        renderEditAttachments(res.item);
        refresh();
      });
      row.append(name, rm);
      editAttachments.appendChild(row);
    });
  }

  function openEdit(card) {
    const item = JSON.parse(card.dataset.item);
    editForm.reset();
    editPreviews.hidden = true;
    editPreviews.innerHTML = "";
    editForm.elements.id.value = item.id;
    editForm.elements.title.value = item.title;
    editForm.elements.notes.value = item.notes;
    renderEditAttachments(item);
    App.openSheet(sheet);
  }

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = editForm.elements.id.value;
    const fd = new FormData(editForm);
    fd.delete("id");
    const submit = editForm.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      await upload(`/info/${id}`, fd);
      App.closeSheet(sheet);
      refresh();
    } catch (_) {
      /* toast shown */
    } finally {
      submit.disabled = false;
    }
  });

  document.getElementById("info-delete").addEventListener("click", async () => {
    const id = editForm.elements.id.value;
    if (!window.confirm("Delete this and its attachments?")) return;
    await App.api(`/info/${id}/delete`);
    App.closeSheet(sheet);
    App.toast("Deleted");
    refresh();
  });
})();
