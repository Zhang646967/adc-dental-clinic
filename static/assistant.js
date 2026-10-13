(function () {
  "use strict";
  var root = document.querySelector("[data-assistant]");
  if (!root) return;
  var form = root.querySelector(".assistant-form"), input = form.querySelector("textarea");
  var log = root.querySelector(".chat-log"), status = root.querySelector(".request-status");
  var submit = form.querySelector('[type="submit"]');
  var speechStatus = root.querySelector(".speech-status"), readButton = root.querySelector(".read-answer");
  var lastAnswer = "", voice = null, controller = null;
  function node(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text; // No HTML/Markdown interpretation.
    return el;
  }
  function detectVoice() {
    if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
      speechStatus.textContent = "本浏览器不支持朗读，请使用文本或系统辅助功能。"; return;
    }
    voice = window.speechSynthesis.getVoices().find(function (v) { return v.localService === true && /^zh(-|_)/i.test(v.lang); }) || null;
    speechStatus.textContent = voice ? "已找到设备本地中文声音。点击后朗读，不自动播放。" : "没有可用的本地中文声音；保留文本，不改用云端朗读。";
    readButton.disabled = !voice || !lastAnswer;
  }
  detectVoice();
  if ("speechSynthesis" in window) window.speechSynthesis.addEventListener("voiceschanged", detectVoice);
  function stopSpeech() { if ("speechSynthesis" in window) window.speechSynthesis.cancel(); }
  root.querySelector(".stop-reading").addEventListener("click", stopSpeech);
  window.addEventListener("pagehide", stopSpeech);
  readButton.addEventListener("click", function () {
    if (!voice || !lastAnswer) return;
    stopSpeech();
    var utterance = new SpeechSynthesisUtterance(lastAnswer);
    utterance.voice = voice; utterance.lang = voice.lang; utterance.rate = .92;
    window.speechSynthesis.speak(utterance);
  });
  root.querySelectorAll(".quick-prompt").forEach(function (button) {
    button.addEventListener("click", function () {
      input.value = button.dataset.prompt; input.focus();
      status.textContent = "已填入常用问题，请点击发送。";
    });
  });
  function renderAnswer(data) {
    var card = node("article", "message assistant");
    card.appendChild(node("div", "badge", data.mode_label));
    card.appendChild(node("h3", "", data.title));
    card.appendChild(node("p", "answer", data.answer));
    if (Array.isArray(data.facts) && data.facts.length) {
      var list = node("ul", "facts");
      data.facts.forEach(function (text) { list.appendChild(node("li", "", text)); });
      card.appendChild(list);
    }
    var links = node("div", "message-links");
    (data.links || []).forEach(function (link) {
      // A second defence. Backend creates links from named Django routes only.
      if (typeof link.url !== "string" || !link.url.startsWith("/") || link.url.startsWith("//") || /[\\\r\n]/.test(link.url)) return;
      var a = node("a", "button secondary", link.label); a.href = link.url; links.appendChild(a);
    });
    card.appendChild(links);
    card.appendChild(node("p", "source", "来源：" + data.source + "\n查询时间：" + data.as_of + "\n" + data.notice));
    log.appendChild(card);
    lastAnswer = data.title + "。" + data.answer + "。" + (data.facts || []).join("。") + "。" + data.notice;
    detectVoice();
    log.scrollTop = log.scrollHeight;
  }
  root.querySelector(".clear-chat").addEventListener("click", function () {
    if (controller) controller.abort();
    stopSpeech(); log.replaceChildren(); lastAnswer = ""; input.value = "";
    status.textContent = "本页对话已清空。服务器不保存对话正文，只保留不含正文的调用元数据。";
    detectVoice(); input.focus();
  });
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    var message = input.value.trim();
    if (!message || message.length > 800 || submit.disabled) return;
    stopSpeech();
    submit.disabled = true; root.setAttribute("aria-busy", "true"); status.textContent = "正在查询办理方式…";
    log.appendChild(node("p", "message user", message));
    controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 26000);
    try {
      var consent = form.querySelector('[name="consent"]');
      var response = await fetch(root.dataset.endpoint, {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: {"Content-Type": "application/json", "X-ADC-Workspace": (document.querySelector('meta[name="adc-workspace"]') || {}).content || "", "X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]').value},
        body: JSON.stringify({message: message, consent: Boolean(consent && consent.checked)})
      });
      var data;
      try { data = await response.json(); } catch (_) { throw new Error("服务暂时没有返回有效响应，请刷新页面确认登录状态。"); }
      if (!response.ok) throw new Error(data.error || "助手暂时不可用，请使用普通按钮。");
      renderAnswer(data); input.value = ""; status.textContent = "已完成。本次对话没有修改业务记录。";
    } catch (err) {
      status.textContent = err.name === "AbortError" ? "请求已停止或超时。未自动重试；可以继续使用普通按钮。" : err.message;
    } finally {
      clearTimeout(timeout); controller = null; submit.disabled = false; root.removeAttribute("aria-busy");
    }
  });
})();
