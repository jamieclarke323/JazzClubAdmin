/* Tasks page behaviour. */
(function () {
  "use strict";
  const App = window.App;
  const board = document.getElementById("task-board");
  const quickAdd = document.getElementById("quick-add");
  const titleInput = document.getElementById("qa-title");
  const moreBtn = document.getElementById("qa-more");
  const options = document.getElementById("qa-options");
  const sheet = document.getElementById("task-sheet");
  const editForm = document.getElementById("task-edit");
  if (!board || !quickAdd) return;

  let refreshing = null;
  const poller = App.poll({
    versionUrl: board.dataset.versionUrl,
    version: currentVersion(),
    onChange: () => refresh(),
  });

  function currentVersion() {
    const meta = document.getElementById("board-meta");
    return meta ? meta.dataset.version : "";
  }

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
          App.setBadge("nav-tasks-count", meta.dataset.dueCount);
        }
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  /* ---- Quick add ---- */
  moreBtn.addEventListener("click", () => {
    const open = options.hidden;
    options.hidden = !open;
    moreBtn.setAttribute("aria-expanded", String(open));
  });

  function readForm(form) {
    const fd = new FormData(form);
    const data = {
      title: fd.get("title") || "",
      description: fd.get("description") || "",
      assignee_id: fd.get("assignee_id") || "",
      priority: fd.get("priority") || "0",
      category: fd.get("category") || "",
      recurrence: fd.get("recurrence") || "",
    };
    const quick = fd.get("due_date_quick");
    const picked = fd.get("due_date") || "";
    if (quick === undefined || quick === null) data.due_date = picked;
    else if (quick === "custom") data.due_date = picked;
    else data.due_date = quick ? App.quickDate(quick) : "";
    return data;
  }

  // Picking a date in the "Pick…" chip selects that chip automatically.
  quickAdd.querySelectorAll(".date-input").forEach((input) => {
    input.addEventListener("change", () => {
      const radio = input.closest(".chip").querySelector("input[type=radio]");
      if (input.value && radio) radio.checked = true;
    });
  });

  function resetQuickAdd() {
    const keepAssignee = quickAdd.querySelector('input[name="assignee_id"]:checked');
    const keepValue = keepAssignee ? keepAssignee.value : "";
    quickAdd.reset();
    App.setRadio(quickAdd, "assignee_id", keepValue);
    options.hidden = true;
    moreBtn.setAttribute("aria-expanded", "false");
  }

  quickAdd.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = readForm(quickAdd);
    if (!data.title.trim()) return;
    const submit = quickAdd.querySelector('button[type=submit]');
    submit.disabled = true;
    try {
      await App.api("/tasks", data);
      App.haptic();
      resetQuickAdd();
      titleInput.focus();
      await refresh();
    } catch (_) {
      /* toast already shown */
    } finally {
      submit.disabled = false;
    }
  });

  /* ---- Board interactions (delegated) ---- */
  board.addEventListener("click", async (e) => {
    const link = e.target.closest("a[data-list-url]");
    if (link) {
      e.preventDefault();
      board.dataset.listUrl = link.dataset.listUrl;
      history.replaceState(null, "", link.getAttribute("href"));
      const view = link.dataset.view;
      if (view) {
        // In "Mine" default new tasks to me; elsewhere leave unassigned.
        App.setRadio(quickAdd, "assignee_id", view === "mine" ? window.APP.user.id : "");
      }
      refresh();
      return;
    }

    const check = e.target.closest(".check");
    if (check) {
      const li = check.closest(".task");
      toggleDone(li);
      return;
    }

    const body = e.target.closest(".task-body");
    if (body) openEdit(body.closest(".task"));
  });

  board.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("task-body")) {
      e.preventDefault();
      openEdit(e.target.closest(".task"));
    }
  });

  async function toggleDone(li) {
    const id = li.dataset.id;
    const wasDone = li.classList.contains("is-done");
    const title = li.querySelector(".task-title").textContent;
    App.haptic();
    li.classList.toggle("is-done", !wasDone);
    li.classList.add("removing");
    setTimeout(() => li.remove(), 220);
    try {
      await App.api(`/tasks/${id}/${wasDone ? "uncomplete" : "complete"}`);
      await refresh();
      if (!wasDone) {
        App.toast(`Done: ${title}`, {
          undo: async () => {
            await App.api(`/tasks/${id}/uncomplete`);
            refresh();
          },
        });
      }
    } catch (_) {
      refresh();
    }
  }

  /* ---- Edit sheet ---- */
  function openEdit(li) {
    const task = JSON.parse(li.dataset.task);
    editForm.elements.id.value = task.id;
    editForm.elements.title.value = task.title;
    editForm.elements.description.value = task.description;
    editForm.elements.due_date.value = task.due_date;
    editForm.elements.category.value = task.category;
    editForm.elements.recurrence.value = task.recurrence;
    App.setRadio(editForm, "assignee_id", task.assignee_id);
    App.setRadio(editForm, "priority", task.priority);
    App.openSheet(sheet);
  }

  editForm.querySelector("[data-clear]").addEventListener("click", () => {
    editForm.elements.due_date.value = "";
  });

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(editForm);
    const id = fd.get("id");
    const data = {
      title: fd.get("title"),
      description: fd.get("description"),
      assignee_id: fd.get("assignee_id") || "",
      due_date: fd.get("due_date") || "",
      priority: fd.get("priority") || "0",
      category: fd.get("category") || "",
      recurrence: fd.get("recurrence") || "",
    };
    try {
      await App.api(`/tasks/${id}`, data);
      App.closeSheet(sheet);
      refresh();
    } catch (_) {
      /* toast shown */
    }
  });

  document.getElementById("task-delete").addEventListener("click", async () => {
    const id = editForm.elements.id.value;
    if (!window.confirm("Delete this task?")) return;
    await App.api(`/tasks/${id}/delete`);
    App.closeSheet(sheet);
    App.toast("Task deleted");
    refresh();
  });
})();
