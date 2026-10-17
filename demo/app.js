(function () {
  "use strict";

  var STORAGE_KEY = "flowremote.demo.v2";
  var DEMO_PASSWORD = "flowremote-demo";

  /* ---------------------------------------------------------------- data */

  function exception(record, issue, fields, original, suggestion, confidence, reason) {
    return {
      record: record,
      issue: issue,
      fields: fields,
      original: original,
      suggestion: suggestion,
      confidence: confidence,
      reason: reason,
      status: "unresolved",
      resolvedValue: null,
      reviewer: null,
      decidedAt: null
    };
  }

  function taskOne() {
    var missingIds = ["ORD-005", "ORD-018", "ORD-023", "ORD-037", "ORD-044", "ORD-052", "ORD-061", "ORD-078"];
    var missingQty = ["ORD-009", "ORD-033", "ORD-081"];
    var items = [];
    missingIds.forEach(function (record, index) {
      items.push(exception(record, "Missing Customer ID", "customer_id", "(blank)",
        "C-" + (1001 + index * 3), 0.98, "AI unique match from customer registry."));
    });
    missingQty.forEach(function (record) {
      items.push(exception(record, "Missing Quantity", "quantity", "(blank)",
        "", 0.84, "No historical data available for this order line quantity."));
    });
    items.push(exception("ORD-099", "Missing Name + ID", "customer_name, customer_id",
      "(both blank)", "Unreliable - skip recommended", 0.68,
      "Multiple possible matches, none above confidence threshold."));
    return {
      id: "TASK-1001",
      workflow: "Order Data Validation & Sync",
      status: "review_required",
      sourceFile: "Orders_September.xlsx",
      sourceLocation: "Company Workspace",
      primaryTarget: "OA - Order Administration",
      secondaryTarget: "BI - Business Intelligence",
      batch: 100,
      passed: 88,
      flagged: 12,
      ownerId: "USR-0001",
      updatedAt: "2026-09-30T14:31:00Z",
      approval: null,
      exceptions: items
    };
  }

  function taskTwo() {
    return {
      id: "TASK-1002",
      workflow: "Invoice Reconciliation",
      status: "review_required",
      sourceFile: "Invoices_Q3.xlsx",
      sourceLocation: "Company Workspace",
      primaryTarget: "OA - Order Administration",
      secondaryTarget: "BI - Business Intelligence",
      batch: 40,
      passed: 36,
      flagged: 4,
      ownerId: "USR-0002",
      updatedAt: "2026-09-29T09:10:00Z",
      approval: null,
      exceptions: [
        exception("ORD-201", "Missing Customer ID", "customer_id", "(blank)", "C-1044", 0.97, "AI unique match from customer registry."),
        exception("ORD-208", "Missing Quantity", "quantity", "(blank)", "", 0.84, "No historical data available for this order line quantity."),
        exception("ORD-215", "Missing Name + ID", "customer_name, customer_id", "(both blank)", "Unreliable - skip recommended", 0.68, "Multiple possible matches, none above confidence threshold."),
        exception("ORD-222", "Missing Customer ID", "customer_id", "(blank)", "C-1058", 0.96, "AI unique match from customer registry.")
      ]
    };
  }

  function taskThree() {
    return {
      id: "TASK-0999",
      workflow: "Weekly Price Sync",
      status: "complete",
      sourceFile: "PriceList_Week39.xlsx",
      sourceLocation: "Company Workspace",
      primaryTarget: "OA - Order Administration",
      secondaryTarget: "BI - Business Intelligence",
      batch: 60,
      passed: 60,
      flagged: 0,
      ownerId: "USR-0001",
      updatedAt: "2026-09-26T17:40:00Z",
      approval: { approved: 60, skipped: 0, by: "Alex Morgan", at: "2026-09-26T17:38:00Z" },
      exceptions: []
    };
  }

  function seedState() {
    return {
      version: 2,
      users: [
        { id: "USR-0001", name: "Alex Morgan", email: "alex.morgan@example.com", password: DEMO_PASSWORD, role: "operator" },
        { id: "USR-0002", name: "Bea Chen", email: "bea.chen@example.com", password: DEMO_PASSWORD, role: "operator" },
        { id: "USR-0003", name: "Ada Admin", email: "admin@example.com", password: DEMO_PASSWORD, role: "admin" }
      ],
      tasks: [taskOne(), taskTwo(), taskThree()],
      session: null,
      nextUser: 4
    };
  }

  /* ------------------------------------------------------------- storage */

  var state = null;

  function loadState() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        var parsed = JSON.parse(raw);
        if (parsed && parsed.version === 2 && parsed.users && parsed.tasks) return parsed;
      }
    } catch (error) { /* private mode or file:// restrictions */ }
    return null;
  }

  function saveState() {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch (error) { /* keep working in memory */ }
  }

  /* ------------------------------------------------------------- helpers */

  var view = document.getElementById("view");
  var who = document.getElementById("who");
  var whoRole = document.getElementById("who-role");
  var whoName = document.getElementById("who-name");
  var signout = document.getElementById("signout");
  var reset = document.getElementById("reset");

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function percent(value) {
    return typeof value === "number" ? Math.round(value * 100) + "%" : "no suggestion";
  }

  function statusLabel(task) {
    var labels = {
      ready: "Ready",
      validating: "Validating",
      review_required: "Review required",
      pending_approval: "Pending approval",
      executing: "Executing",
      complete: "Complete"
    };
    return labels[task.status] || task.status;
  }

  function exceptionLabel(status) {
    return { unresolved: "Unresolved", accepted: "Accepted", manual: "Manual", skipped: "Skipped" }[status] || status;
  }

  function currentUser() {
    if (!state.session) return null;
    for (var i = 0; i < state.users.length; i += 1) {
      if (state.users[i].id === state.session.userId) return state.users[i];
    }
    return null;
  }

  function visibleTasks(user) {
    if (!user) return [];
    return state.tasks.filter(function (task) {
      return user.role === "admin" || task.ownerId === user.id;
    });
  }

  function findTask(id) {
    for (var i = 0; i < state.tasks.length; i += 1) {
      if (state.tasks[i].id === id) return state.tasks[i];
    }
    return null;
  }

  function counts(task) {
    var tally = { unresolved: 0, accepted: 0, manual: 0, skipped: 0 };
    task.exceptions.forEach(function (item) {
      tally[item.status] = (tally[item.status] || 0) + 1;
    });
    tally.ready = tally.accepted + tally.manual;
    tally.total = task.exceptions.length;
    return tally;
  }

  function updateChrome() {
    var user = currentUser();
    if (!user) { who.hidden = true; return; }
    who.hidden = false;
    whoRole.textContent = user.role;
    whoRole.className = "badge badge-" + user.role;
    whoName.textContent = user.name;
  }

  /* ------------------------------------------------------------ actions */

  function decideOn(taskId, record, action, value) {
    var task = findTask(taskId);
    var user = currentUser();
    if (!task || !user || task.status !== "review_required") return false;
    var item = null;
    task.exceptions.forEach(function (candidate) {
      if (candidate.record === record) item = candidate;
    });
    if (!item || item.status !== "unresolved") return false;
    if (action === "accept") {
      if (!item.suggestion) return false;
      item.status = "accepted";
      item.resolvedValue = item.suggestion;
    } else if (action === "edit") {
      var cleaned = String(value || "").trim();
      if (!cleaned) return false;
      item.status = "manual";
      item.resolvedValue = cleaned;
    } else if (action === "skip") {
      item.status = "skipped";
      item.resolvedValue = null;
    } else {
      return false;
    }
    item.reviewer = user.name;
    item.decidedAt = new Date().toISOString();
    saveState();
    return true;
  }

  function proceed(taskId) {
    var task = findTask(taskId);
    if (!task || task.status !== "review_required") return false;
    if (counts(task).unresolved !== 0) return false;
    task.status = "pending_approval";
    saveState();
    return true;
  }

  function approve(taskId) {
    var task = findTask(taskId);
    var user = currentUser();
    if (!task || !user || task.approval) return false;
    if (task.status !== "pending_approval") return false;
    var tally = counts(task);
    if (tally.unresolved !== 0 || tally.ready === 0) return false;
    task.status = "executing";
    task.approval = {
      approved: tally.ready,
      skipped: tally.skipped,
      by: user.name,
      at: new Date().toISOString().slice(0, 19) + "Z"
    };
    saveState();
    return true;
  }

  function backToReview(taskId) {
    var task = findTask(taskId);
    if (!task || task.approval) return false;
    task.status = "review_required";
    saveState();
    return true;
  }

  /* -------------------------------------------------------------- render */

  function renderLogin(message) {
    view.innerHTML =
      '<section class="auth"><div class="auth-card">' +
        "<h1>FlowRemote AI-RPA</h1>" +
        '<p class="sub">Review and control business workflows from your phone.</p>' +
        (message ? '<p class="alert">' + esc(message) + "</p>" : "") +
        '<form id="login-form">' +
          "<label>Work email<input type=\"email\" name=\"email\" required autofocus></label>" +
          "<label>Password<input type=\"password\" name=\"password\" required></label>" +
          '<button class="btn-primary" type="submit">Log in</button>' +
        "</form>" +
        '<p class="hint">No account yet? <a href="#/signup">Create one</a></p>' +
        '<div class="accounts"><p>Demo accounts - tap to fill</p>' +
          '<button type="button" data-email="alex.morgan@example.com">Alex Morgan<small>operator · sees only their own task</small></button>' +
          '<button type="button" data-email="bea.chen@example.com">Bea Chen<small>operator · a second, separate account</small></button>' +
          '<button type="button" data-email="admin@example.com">Ada Admin<small>admin · sees every task</small></button>' +
        "</div>" +
      "</div></section>";

    var form = document.getElementById("login-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var email = form.email.value.trim().toLowerCase();
      var password = form.password.value;
      var user = null;
      state.users.forEach(function (candidate) {
        if (candidate.email.toLowerCase() === email) user = candidate;
      });
      if (!user || user.password !== password) {
        renderLogin("That email and password do not match an account.");
        return;
      }
      state.session = { userId: user.id };
      saveState();
      location.hash = "#/";
      route();
    });

    Array.prototype.forEach.call(view.querySelectorAll(".accounts button"), function (button) {
      button.addEventListener("click", function () {
        form.email.value = button.getAttribute("data-email");
        form.password.value = DEMO_PASSWORD;
        form.email.focus();
      });
    });
  }

  function renderSignup(message) {
    view.innerHTML =
      '<section class="auth"><div class="auth-card">' +
        "<h1>Create your account</h1>" +
        '<p class="sub">Every person signs in with their own work email.</p>' +
        (message ? '<p class="alert">' + esc(message) + "</p>" : "") +
        '<form id="signup-form">' +
          '<label>Name<input type="text" name="name" required autofocus></label>' +
          "<label>Work email<input type=\"email\" name=\"email\" required></label>" +
          '<label>Password<input type="password" name="password" minlength="8" required></label>' +
          '<label>Password again<input type="password" name="password_again" minlength="8" required></label>' +
          '<button class="btn-primary" type="submit">Create account</button>' +
        "</form>" +
        '<p class="hint">Already registered? <a href="#/login">Log in</a></p>' +
      "</div></section>";

    var form = document.getElementById("signup-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var name = form.name.value.trim();
      var email = form.email.value.trim().toLowerCase();
      var password = form.password.value;
      if (!name) { renderSignup("Please enter your name."); return; }
      if (email.indexOf("@") < 1) { renderSignup("Please enter a valid email address."); return; }
      if (password.length < 8) { renderSignup("The password must be at least 8 characters."); return; }
      if (password !== form.password_again.value) { renderSignup("The two passwords do not match."); return; }
      var taken = state.users.some(function (user) { return user.email.toLowerCase() === email; });
      if (taken) { renderSignup("An account with that email already exists."); return; }
      var user = {
        id: "USR-" + (1000 + state.nextUser),
        name: name,
        email: email,
        password: password,
        role: "operator"
      };
      state.nextUser += 1;
      state.users.push(user);
      state.session = { userId: user.id };
      saveState();
      location.hash = "#/";
      route();
    });
  }

  function renderHome(user) {
    var tasks = visibleTasks(user);
    var cards = tasks.map(function (task) {
      var tally = counts(task);
      return '<a class="task-card" href="#/tasks/' + encodeURIComponent(task.id) + '">' +
        '<div class="task-top">' +
          '<span class="task-id">' + esc(task.id) + "</span>" +
          '<span class="badge ' + (task.status === "complete" ? "badge-complete" : "badge-state") + '">' +
            esc(statusLabel(task)) + "</span>" +
        "</div>" +
        "<h2>" + esc(task.workflow) + "</h2>" +
        '<p class="task-file">' + esc(task.sourceFile) + " · " + task.batch + " records</p>" +
        '<div class="stats">' +
          '<div><span class="n">' + task.passed + '</span><span class="l">passed</span></div>' +
          '<div><span class="n">' + task.exceptions.length + '</span><span class="l">exceptions</span></div>' +
          '<div><span class="n">' + tally.unresolved + '</span><span class="l">unresolved</span></div>' +
        "</div></a>";
    }).join("");

    view.innerHTML =
      '<div class="page-head"><h1>Tasks</h1><p class="sub">' +
        (user.role === "admin" ? "Every task in the workspace (admin view)" : "Tasks you own") +
      "</p></div>" +
      (cards ? '<div class="task-list">' + cards + "</div>"
             : '<div class="empty"><p>No tasks yet.</p><p class="muted">Ask an admin to assign one to you.</p></div>');
  }

  function gateBlock(task, tally) {
    if (task.approval) {
      return '<div class="gate gate-open"><div><strong>Approved</strong>' +
        '<span class="small muted">' + task.approval.approved + " records approved by " +
        esc(task.approval.by) + " · " + esc(task.approval.at) + "</span></div>" +
        '<span class="badge badge-state">' + esc(statusLabel(task)) + "</span></div>";
    }
    if (task.status === "pending_approval") {
      return '<div class="gate gate-open"><div><strong>Ready for approval</strong>' +
        '<span class="small muted">Every exception is resolved.</span></div>' +
        '<a class="btn-gate" href="#/tasks/' + encodeURIComponent(task.id) + '/approval">Open approval</a></div>';
    }
    if (tally.unresolved === 0) {
      return '<div class="gate gate-open"><div><strong>Proceed to approval</strong>' +
        '<span class="small muted">Every exception is resolved.</span></div>' +
        '<button class="btn-gate" type="button" data-act="proceed" data-task="' +
        esc(task.id) + '">Proceed</button></div>';
    }
    return '<div class="gate gate-closed"><div><strong>Proceed to approval</strong>' +
      '<span class="small muted">' + tally.unresolved +
      " unresolved exception(s) still block approval.</span></div>" +
      '<button class="btn-gate" type="button" disabled>Blocked</button></div>';
  }

  function renderTask(taskId, user) {
    var task = findTask(taskId);
    var maySee = task && (user.role === "admin" || task.ownerId === user.id);
    if (!maySee) {
      view.innerHTML =
        '<a class="back" href="#/">&larr; All tasks</a>' +
        '<div class="empty"><h2>Task not found</h2>' +
        '<p class="muted">This demo only shows tasks that belong to the signed-in account.</p></div>';
      return;
    }

    var tally = counts(task);
    var rows = task.exceptions.map(function (item) {
      var action = "";
      if (item.status === "unresolved" && task.status === "review_required") {
        action =
          '<form class="action-form" data-task="' + esc(task.id) + '" data-record="' + esc(item.record) + '">' +
            '<button class="btn-mini" type="button" data-act="accept" data-task="' + esc(task.id) +
              '" data-record="' + esc(item.record) + '"' +
              (item.suggestion ? "" : ' disabled title="No suggestion to accept"') + ">Accept</button>" +
            '<button class="btn-mini btn-mini-skip" type="button" data-act="skip" data-task="' +
              esc(task.id) + '" data-record="' + esc(item.record) + '">Skip</button>' +
            '<input class="mini-input" type="text" name="value" placeholder="value" size="6"' +
              ' aria-label="New value for ' + esc(item.record) + '">' +
            '<button class="btn-mini" type="button" data-act="edit" data-task="' + esc(task.id) +
              '" data-record="' + esc(item.record) + '">Save</button>' +
          "</form>";
      } else if (item.status !== "unresolved") {
        action = '<span class="muted small">' + esc(item.resolvedValue || "-") +
          (item.reviewer ? " · " + esc(item.reviewer) : "") + "</span>";
      } else {
        action = '<span class="muted small">review closed</span>';
      }
      return "<tr>" +
        '<td class="mono">' + esc(item.record) + "</td>" +
        "<td>" + esc(item.issue) + "</td>" +
        '<td class="mono small">' + esc(item.fields) + "</td>" +
        '<td class="muted">' + esc(item.original) + "</td>" +
        "<td>" + esc(item.suggestion || "(none)") + "</td>" +
        '<td class="mono">' + percent(item.confidence) + "</td>" +
        '<td><span class="badge badge-' + esc(item.status) + '">' +
          esc(exceptionLabel(item.status)) + "</span></td>" +
        '<td class="actions">' + action + "</td>" +
      "</tr>";
    }).join("");

    view.innerHTML =
      '<a class="back" href="#/">&larr; All tasks</a>' +
      '<div class="page-head">' +
        '<p class="eyebrow">' + esc(task.id) + " · " + esc(statusLabel(task)) + "</p>" +
        "<h1>" + esc(task.workflow) + "</h1>" +
        '<p class="sub">' + esc(task.sourceFile) + " · " + esc(task.sourceLocation) + "</p>" +
      "</div>" +
      '<div class="stats stats-wide">' +
        '<div><span class="n">' + task.batch + '</span><span class="l">input</span></div>' +
        '<div><span class="n">' + task.passed + '</span><span class="l">passed</span></div>' +
        '<div><span class="n">' + task.flagged + '</span><span class="l">flagged</span></div>' +
        '<div><span class="n">' + tally.unresolved + '</span><span class="l">unresolved</span></div>' +
        '<div><span class="n">' + tally.ready + '</span><span class="l">ready to write</span></div>' +
      "</div>" +
      gateBlock(task, tally) +
      '<h2 class="section">Exceptions</h2>' +
      (rows
        ? '<div class="table-wrap"><table class="table"><thead><tr>' +
            "<th>Record</th><th>Issue</th><th>Field(s)</th><th>Original</th>" +
            "<th>Suggestion</th><th>Match</th><th>Status</th><th>Action</th>" +
          "</tr></thead><tbody>" + rows + "</tbody></table></div>"
        : '<p class="muted">No exceptions in this batch.</p>') +
      '<p class="note">Accept keeps the AI value, Edit saves your own value, Skip removes the record ' +
        "from the run. This demo keeps its data in your browser.</p>";
  }

  function renderApproval(taskId, user) {
    var task = findTask(taskId);
    var maySee = task && (user.role === "admin" || task.ownerId === user.id);
    if (!maySee) {
      view.innerHTML = '<div class="empty"><h2>Task not found</h2></div>';
      return;
    }
    if (task.status !== "pending_approval" && task.status !== "executing") {
      location.replace("#/tasks/" + encodeURIComponent(task.id));
      return;
    }
    var tally = counts(task);
    var approved = task.approval
      ? '<div class="gate gate-open"><div><strong>Approved</strong>' +
          '<span class="small muted">' + task.approval.approved + " records approved by " +
          esc(task.approval.by) + " · " + esc(task.approval.at) + "</span></div>" +
          '<span class="badge badge-state">' + esc(statusLabel(task)) + "</span></div>"
      : '<div class="panel"><h2>Source document</h2>' +
          '<p class="mono">' + esc(task.sourceFile) + ' <span class="badge">XLSX data feed</span></p>' +
          '<p class="muted small">' + esc(task.sourceLocation) + "</p></div>" +
        '<div class="panel"><h2>Target endpoints and actions</h2>' +
          '<ul class="targets">' +
            "<li><strong>" + esc(task.primaryTarget) + '</strong><span class="badge">Primary target</span>' +
              '<span class="muted small">Write ' + tally.ready + " approved records</span></li>" +
            "<li><strong>" + esc(task.secondaryTarget) + '</strong><span class="badge">Secondary sync</span>' +
              '<span class="muted small">Sync the same ' + tally.ready +
              " records, never a second copy</span></li>" +
          "</ul></div>" +
        '<p class="notice">Validation does not write to OA or BI. Only this approval releases the write.</p>' +
        '<div class="approval-actions">' +
          '<button class="btn-primary" type="button" data-act="approve" data-task="' + esc(task.id) +
            '">Approve &amp; Execute</button>' +
          '<button class="btn-ghost" type="button" data-act="back" data-task="' + esc(task.id) +
            '">Back to review</button>' +
        "</div>";

    view.innerHTML =
      '<a class="back" href="#/tasks/' + encodeURIComponent(task.id) + '">&larr; ' + esc(task.id) + "</a>" +
      '<div class="page-head"><p class="eyebrow">' + esc(task.id) + " · Approval stage</p>" +
        "<h1>Execution Approval</h1>" +
        '<p class="sub">Review the validation results before approving the write to ' +
        esc(task.primaryTarget) + " and " + esc(task.secondaryTarget) + ".</p></div>" +
      '<div class="stats stats-wide">' +
        '<div><span class="n">' + task.batch + '</span><span class="l">input</span></div>' +
        '<div><span class="n">' + tally.skipped + '</span><span class="l">skipped</span></div>' +
        '<div><span class="n">' + tally.ready + '</span><span class="l">ready</span></div>' +
        '<div><span class="n">' + tally.unresolved + '</span><span class="l">unresolved</span></div>' +
      "</div>" + approved +
      '<p class="note">Execution progress and results would come next; this demo ends at the approval.</p>';
  }

  function renderNotFound() {
    view.innerHTML = '<div class="empty"><h2>Page not found</h2>' +
      '<p><a href="#/">Back to tasks</a></p></div>';
  }

  /* -------------------------------------------------------------- router */

  function route() {
    var hash = location.hash || "#/";
    var user = currentUser();

    if (!user && hash !== "#/login" && hash !== "#/signup") {
      location.replace("#/login");
      return;
    }
    if (user && (hash === "#/login" || hash === "#/signup")) {
      location.replace("#/");
      return;
    }

    updateChrome();

    if (hash === "#/login") return renderLogin("");
    if (hash === "#/signup") return renderSignup("");
    if (hash === "#/" || hash === "#") return renderHome(user);
    if (hash.indexOf("#/tasks/") === 0) {
      var rest = decodeURIComponent(hash.slice("#/tasks/".length));
      if (rest.slice(-9) === "/approval") {
        return renderApproval(rest.slice(0, -9), user);
      }
      return renderTask(rest, user);
    }
    return renderNotFound();
  }

  /* --------------------------------------------------------------- wiring */

  view.addEventListener("click", function (event) {
    var button = event.target && event.target.getAttribute
      ? event.target.closest("button[data-act]")
      : null;
    if (!button) return;
    var action = button.getAttribute("data-act");
    var taskId = button.getAttribute("data-task");
    var record = button.getAttribute("data-record");

    if (action === "proceed") {
      if (proceed(taskId)) {
        location.hash = "#/tasks/" + encodeURIComponent(taskId) + "/approval";
        route();
      }
      return;
    }
    if (action === "approve") {
      if (approve(taskId)) {
        location.hash = "#/tasks/" + encodeURIComponent(taskId);
        route();
      }
      return;
    }
    if (action === "back") {
      if (backToReview(taskId)) {
        location.hash = "#/tasks/" + encodeURIComponent(taskId);
        route();
      }
      return;
    }

    var value = null;
    if (action === "edit") {
      var form = button.closest("form");
      var input = form ? form.querySelector("input[name=value]") : null;
      value = input ? input.value : "";
    }
    if (decideOn(taskId, record, action, value)) {
      route();
    }
  });

  signout.addEventListener("click", function () {
    state.session = null;
    saveState();
    location.hash = "#/login";
    route();
  });

  reset.addEventListener("click", function () {
    if (!window.confirm("Reset the demo accounts and data?")) return;
    state = seedState();
    saveState();
    location.hash = "#/login";
    route();
  });

  window.addEventListener("hashchange", route);

  state = loadState();
  if (!state) {
    state = seedState();
    saveState();
  }
  route();

  // A small hook for the automated check and for experimenting in the console.
  window.FlowRemoteDemo = {
    decideOn: decideOn,
    proceed: proceed,
    approve: approve,
    backToReview: backToReview,
    render: route,
    getState: function () { return state; }
  };
})();
