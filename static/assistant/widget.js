(function () {
  var toggle = document.getElementById("field-help-toggle");
  var panel = document.getElementById("field-help-panel");
  var closeBtn = document.getElementById("field-help-close");
  var form = document.getElementById("field-help-form");
  var input = document.getElementById("field-help-input");
  var log = document.getElementById("field-help-log");
  if (!toggle || !panel) return;

  toggle.addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });
  closeBtn.addEventListener("click", function () { panel.hidden = true; });

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? match.pop() : "";
  }

  // Guess the form being edited from the admin URL so answers can be scoped.
  function currentModel() {
    var m = window.location.pathname.match(/\/admin\/campaigns\/(\w+)\//);
    if (!m) return null;
    var map = { campaign: "Campaign", creator: "Creator",
                socialaccount: "SocialAccount", participation: "Participation" };
    return map[m[1]] || null;
  }

  function addMessage(text, cls) {
    var p = document.createElement("p");
    p.className = cls;
    p.textContent = text;
    log.appendChild(p);
    log.scrollTop = log.scrollHeight;
    return p;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var question = input.value.trim();
    if (!question) return;
    addMessage(question, "fh-user");
    input.value = "";
    var pending = addMessage("…", "fh-bot");

    fetch("/assistant/ask/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify({ question: question, model: currentModel() })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (res.ok) {
          pending.textContent = res.data.answer;
        } else {
          pending.className = "fh-err";
          pending.textContent = res.data.error || "Something went wrong.";
        }
      })
      .catch(function () {
        pending.className = "fh-err";
        pending.textContent = "Could not reach the assistant.";
      });
  });
})();
