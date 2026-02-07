const form = document.getElementById("convert-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const statusSection = document.getElementById("status");
const statusText = document.getElementById("status-text");
const spinner = document.getElementById("spinner");
const logArea = document.getElementById("log");
const downloadBtn = document.getElementById("download-btn");
const errorMsg = document.getElementById("error-msg");

function setFormDisabled(disabled) {
    urlInput.disabled = disabled;
    submitBtn.disabled = disabled;
}

function resetUI() {
    statusSection.hidden = true;
    downloadBtn.hidden = true;
    errorMsg.hidden = true;
    logArea.textContent = "";
    statusText.textContent = "Converting...";
    spinner.classList.remove("done");
}

function showError(message) {
    errorMsg.textContent = message;
    errorMsg.hidden = false;
    setFormDisabled(false);
    spinner.classList.add("done");
    statusText.textContent = "Failed";
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const url = urlInput.value.trim();
    if (!url) return;

    resetUI();
    setFormDisabled(true);
    statusSection.hidden = false;

    let resp;
    try {
        resp = await fetch("/convert", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
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

    const evtSource = new EventSource(`/jobs/${job_id}/status`);

    evtSource.addEventListener("progress", (e) => {
        logArea.textContent += e.data + "\n";
        logArea.scrollTop = logArea.scrollHeight;
    });

    evtSource.addEventListener("done", (e) => {
        logArea.textContent += "Conversion complete!\n";
        logArea.scrollTop = logArea.scrollHeight;
        statusText.textContent = "Done!";
        spinner.classList.add("done");
        downloadBtn.href = `/jobs/${job_id}/download`;
        downloadBtn.hidden = false;
        setFormDisabled(false);
        evtSource.close();
    });

    evtSource.addEventListener("error", (e) => {
        if (e.data) {
            showError("Conversion failed: " + e.data);
        } else {
            showError("Connection to server lost.");
        }
        evtSource.close();
    });

    evtSource.addEventListener("ping", () => {
        // keepalive, ignore
    });
});
