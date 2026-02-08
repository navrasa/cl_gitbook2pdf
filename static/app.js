const form = document.getElementById("convert-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const subpagesToggle = document.getElementById("subpages-toggle");
const statusSection = document.getElementById("status");
const statusText = document.getElementById("status-text");
const spinner = document.getElementById("spinner");
const logArea = document.getElementById("log");
const downloadBtn = document.getElementById("download-btn");
const errorMsg = document.getElementById("error-msg");

let currentJobId = null;
let currentEvtSource = null;

function setConverting(active) {
    urlInput.disabled = active;
    subpagesToggle.disabled = active;
    if (active) {
        submitBtn.textContent = "Stop conversion";
        submitBtn.classList.add("stop-btn");
        submitBtn.disabled = false;
    } else {
        submitBtn.textContent = "Convert";
        submitBtn.classList.remove("stop-btn");
        submitBtn.disabled = false;
    }
}

function setDownloadEnabled(enabled) {
    if (enabled) {
        downloadBtn.classList.remove("disabled");
        downloadBtn.removeAttribute("tabindex");
    } else {
        downloadBtn.classList.add("disabled");
        downloadBtn.setAttribute("tabindex", "-1");
    }
}

function resetUI() {
    statusSection.hidden = true;
    downloadBtn.hidden = true;
    setDownloadEnabled(false);
    errorMsg.hidden = true;
    logArea.textContent = "";
    statusText.textContent = "Converting...";
    spinner.className = "spinner";
}

function showError(message) {
    errorMsg.textContent = message;
    errorMsg.hidden = false;
    downloadBtn.hidden = true;
    setConverting(false);
    spinner.className = "spinner failed";
    statusText.textContent = "Failed";
}

async function cancelJob() {
    if (!currentJobId) return;
    try {
        await fetch(`/jobs/${currentJobId}/cancel`, { method: "POST" });
    } catch (_) {
        // ignore network errors during cancel
    }
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    // If already converting, stop it
    if (currentJobId) {
        await cancelJob();
        return;
    }

    const url = urlInput.value.trim();
    if (!url) return;

    resetUI();
    setConverting(true);
    statusSection.hidden = false;

    let resp;
    try {
        resp = await fetch("/convert", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url, include_subpages: subpagesToggle.checked }),
        });
    } catch (err) {
        showError("Network error: could not reach the server.");
        return;
    }

    if (!resp.ok) {
        const text = await resp.text();
        showError("Server error: " + text);
        return;
    }

    const { job_id } = await resp.json();
    currentJobId = job_id;

    const evtSource = new EventSource(`/jobs/${job_id}/status`);
    currentEvtSource = evtSource;

    evtSource.addEventListener("progress", (e) => {
        logArea.textContent += e.data + "\n";
        logArea.scrollTop = logArea.scrollHeight;
    });

    evtSource.addEventListener("done", (e) => {
        logArea.textContent += "Conversion complete!\n";
        logArea.scrollTop = logArea.scrollHeight;
        statusText.textContent = "Complete";
        spinner.className = "spinner done";
        downloadBtn.href = `/jobs/${job_id}/download`;
        downloadBtn.hidden = false;
        setDownloadEnabled(true);
        setConverting(false);
        currentJobId = null;
        currentEvtSource = null;
        evtSource.close();
    });

    evtSource.addEventListener("failed", (e) => {
        showError(e.data);
        currentJobId = null;
        currentEvtSource = null;
        evtSource.close();
    });

    evtSource.onerror = () => {
        if (!evtSource.CLOSED) {
            showError("Connection to server lost.");
            currentJobId = null;
            currentEvtSource = null;
            evtSource.close();
        }
    };

    evtSource.addEventListener("ping", () => {
        // keepalive, ignore
    });
});
