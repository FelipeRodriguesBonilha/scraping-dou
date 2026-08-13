const form = document.querySelector("#search-form");
const dateInput = document.querySelector("#date");
const keywordsInput = document.querySelector("#keywords");
const submitButton = document.querySelector("#submit-button");
const refreshButton = document.querySelector("#refresh-button");
const message = document.querySelector("#form-message");
const statusBadge = document.querySelector("#status-badge");
const statusSummary = document.querySelector("#status-summary");
const logs = document.querySelector("#logs");
const results = document.querySelector("#results");
const resultsSummary = document.querySelector("#results-summary");

let pollTimer = null;

async function request(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || "Não foi possível concluir a solicitação.");
  }
  return body;
}

function setMessage(text = "", isSuccess = false) {
  message.textContent = text;
  message.classList.toggle("success", isSuccess);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value) {
  const matchedDate = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  if (!matchedDate) return value || "";
  const [, year, month, day] = matchedDate;
  return `${day}/${month}/${year}`;
}

const windows1252Bytes = new Map([
  ["€", 0x80], ["‚", 0x82], ["ƒ", 0x83], ["„", 0x84], ["…", 0x85],
  ["†", 0x86], ["‡", 0x87], ["ˆ", 0x88], ["‰", 0x89], ["Š", 0x8a],
  ["‹", 0x8b], ["Œ", 0x8c], ["Ž", 0x8e], ["‘", 0x91], ["’", 0x92],
  ["“", 0x93], ["”", 0x94], ["•", 0x95], ["–", 0x96], ["—", 0x97],
  ["˜", 0x98], ["™", 0x99], ["š", 0x9a], ["›", 0x9b], ["œ", 0x9c],
  ["ž", 0x9e], ["Ÿ", 0x9f],
]);

const mojibakeSequence = /(?:Ã[\u0080-\u00bf]|Â[\u0080-\u00bf]|â[\u0080-\u00bf€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ]{2})/g;
const utf8Decoder = new TextDecoder("utf-8", { fatal: true });

function normalizeLogText(value) {
  return String(value || "").replace(mojibakeSequence, (sequence) => {
    const bytes = Uint8Array.from(sequence, (character) => (
      windows1252Bytes.get(character) ?? character.charCodeAt(0)
    ));
    try {
      return utf8Decoder.decode(bytes);
    } catch {
      return sequence;
    }
  });
}

function statusLabel(status) {
  return {
    idle: "Aguardando",
    running: "Coletando",
    finished: "Concluída",
    failed: "Falhou",
  }[status] || status;
}

function elapsedSince(value) {
  const started = Date.parse(value || "");
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes) return `${minutes} min ${remainingSeconds}s`;
  return `${remainingSeconds}s`;
}

function formatActivity(value) {
  const timestamp = Date.parse(value || "");
  if (Number.isNaN(timestamp)) return "";
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

function updateStatus(job) {
  const status = job.status || "idle";
  statusBadge.dataset.status = status;
  statusBadge.textContent = statusLabel(status);
  submitButton.disabled = status === "running";

  if (status === "running") {
    const elapsed = elapsedSince(job.startedAt);
    const activity = formatActivity(job.lastActivityAt);
    const detail = activity
      ? ` Último log às ${activity}.`
      : " Aguardando o primeiro log do processo.";
    statusSummary.textContent = `Coleta em andamento para ${formatDate(job.date)}${elapsed ? ` há ${elapsed}` : ""}. Os arquivos aparecerão abaixo assim que forem salvos.${detail}`;
  } else if (status === "finished") {
    const result = job.returncode === 0 ? "concluída sem falhas" : "concluída com avisos";
    statusSummary.textContent = `Coleta ${result} (${formatDate(job.date) || "data não informada"}).`;
  } else if (status === "failed") {
    statusSummary.textContent = `A coleta não pôde ser iniciada: ${job.error || "erro desconhecido"}.`;
  } else {
    statusSummary.textContent = "Nenhuma coleta iniciada nesta sessão.";
  }

  const output = (job.logs || []).map(normalizeLogText).join("\n");
  logs.hidden = !output;
  logs.textContent = output;
  if (output) logs.scrollTop = logs.scrollHeight;
}

function createResultItem(file) {
  const item = document.createElement("li");
  const link = document.createElement("a");
  link.className = "result-link";
  link.href = file.url;
  link.target = "_blank";
  link.rel = "noopener";

  const left = document.createElement("span");
  const tag = document.createElement("span");
  tag.className = `tag${file.kind === "ocorrência" ? " occurrence" : ""}`;
  tag.textContent = file.kind;
  const name = document.createElement("span");
  name.className = "file-name";
  name.textContent = file.name;
  left.append(tag, name);

  const size = document.createElement("span");
  size.className = "file-meta";
  size.textContent = formatSize(file.size);
  link.append(left, size);
  item.append(link);
  return item;
}

function renderResults(files, date) {
  results.replaceChildren();
  if (!files.length) {
    const empty = document.createElement("p");
    empty.className = "empty-results";
    empty.textContent = "Nenhum PDF ou texto de ocorrência foi encontrado para esta data.";
    results.append(empty);
    resultsSummary.textContent = `0 arquivos em ${formatDate(date)}.`;
    return;
  }

  const groups = new Map();
  for (const file of files) {
    const key = `${file.state} · ${file.keyword}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(file);
  }
  for (const [name, groupFiles] of groups) {
    const group = document.createElement("article");
    group.className = "result-group";
    const heading = document.createElement("h3");
    heading.textContent = name;
    const list = document.createElement("ul");
    list.className = "result-list";
    groupFiles.forEach((file) => list.append(createResultItem(file)));
    group.append(heading, list);
    results.append(group);
  }
  resultsSummary.textContent = `${files.length} arquivo${files.length === 1 ? "" : "s"} em ${formatDate(date)}.`;
}

async function refreshResults() {
  if (!dateInput.value) return;
  try {
    const payload = await request(`/api/files?date=${encodeURIComponent(dateInput.value)}`);
    renderResults(payload.files, payload.date);
  } catch (error) {
    resultsSummary.textContent = error.message;
  }
}

async function refreshStatus() {
  try {
    const job = await request("/api/status");
    updateStatus(job);
    if (job.status === "running") {
      await refreshResults();
      if (!pollTimer) pollTimer = window.setInterval(refreshStatus, 1800);
    } else if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
      await refreshResults();
    }
  } catch (error) {
    statusSummary.textContent = error.message;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage();
  try {
    const job = await request("/api/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: dateInput.value,
        keywords: keywordsInput.value,
      }),
    });
    updateStatus(job);
    setMessage("Coleta iniciada. O andamento será atualizado automaticamente.", true);
    await refreshResults();
    if (!pollTimer) pollTimer = window.setInterval(refreshStatus, 1800);
  } catch (error) {
    setMessage(error.message);
  }
});

refreshButton.addEventListener("click", refreshResults);
dateInput.addEventListener("change", refreshResults);

(async function initialize() {
  try {
    const payload = await request("/api/config");
    dateInput.value = payload.date;
    await refreshStatus();
    await refreshResults();
  } catch (error) {
    setMessage(error.message);
  }
})();
