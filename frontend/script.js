const API_URL = "http://localhost:8000/execute";

const codeInput = document.getElementById("code");
const runBtn = document.getElementById("run-btn");
const statusEl = document.getElementById("status");
const stdoutEl = document.getElementById("stdout");
const stderrEl = document.getElementById("stderr");
const exitCodeEl = document.getElementById("exit-code");
const durationEl = document.getElementById("duration");

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#f97373" : "#9ca3af";
}

async function executeCode() {
  const code = codeInput.value;
  if (!code.trim()) {
    setStatus("Введите код перед запуском", true);
    return;
  }

  runBtn.disabled = true;
  setStatus("Выполнение кода...");
  stdoutEl.textContent = "";
  stderrEl.textContent = "";
  exitCodeEl.textContent = "-";
  durationEl.textContent = "-";

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ code }),
    });

    const data = await response.json();

    if (!response.ok) {
      const detail = data?.detail || "Ошибка выполнения запроса";
      setStatus(`Ошибка: ${detail}`, true);
      stderrEl.textContent = detail;
      return;
    }

    stdoutEl.textContent = data.stdout || "";
    stderrEl.textContent = data.stderr || "";
    exitCodeEl.textContent = data.exit_code;
    durationEl.textContent = data.duration_ms;

    setStatus("Готово");
  } catch (error) {
    console.error(error);
    setStatus("Не удалось связаться с backend. Проверьте docker-compose.", true);
    stderrEl.textContent = String(error);
  } finally {
    runBtn.disabled = false;
  }
}

runBtn.addEventListener("click", () => {
  executeCode();
});

codeInput.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "Enter") {
    executeCode();
  }
});

