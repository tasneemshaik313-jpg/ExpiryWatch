const form = document.getElementById("analyzeForm");
let latestAnalysis = null;

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? "";
}

function renderRisk(score, label, level) {
    const box = document.getElementById("rRisk");
    const labelBox = document.getElementById("rRiskLabel");
    if (!box || !labelBox) return;

    if (score === null || score === undefined) {
        box.textContent = "Not calculated";
        labelBox.textContent = "A valid expiry date is required.";
        box.className = "risk-score";
        return;
    }

    box.textContent = `${score}/100`;
    box.className = `risk-score risk-${level}`;
    labelBox.textContent = label;
}

function updateVerificationVisibility(data, confidence) {
    const verification = document.getElementById("verificationBox");
    if (!verification) return;

    const needsReview = !data.expiry_date || !data.manufacturing_date || confidence < 90;
    if (needsReview) {
        verification.classList.remove("hidden");
        document.getElementById("verifyMfg").value = data.manufacturing_date || "";
        document.getElementById("verifyExpiry").value = data.expiry_date || data.estimated_expiry || "";
        document.getElementById("verifyExpiry").readOnly = false;
    } else {
        verification.classList.add("hidden");
    }
}

if (form) {
    const resultBox = document.getElementById("analysisResult");
    const loading = document.getElementById("loading");
    const button = document.getElementById("analyzeBtn");

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        button.disabled = true;
        loading.classList.remove("hidden");
        resultBox.classList.add("hidden");

        try {
            const response = await fetch("/analyze", {
                method: "POST",
                body: new FormData(form)
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Analysis failed.");

            latestAnalysis = data;

            setText("rProduct", data.product_name || "Unknown Product");
            setText("rCategory", data.category || "Others");
            setText("rBarcode", data.barcode || "Not found");
            setText("rMfg", data.manufacturing_date || "Not found");
            setText("rExpiry", data.expiry_date || data.estimated_expiry || "Not available");

            if (data.expiry_date) {
                setText("rEstimated", "Printed on package");
            } else if (data.estimated_expiry) {
                setText("rEstimated", `MFG + ${data.shelf_life_months || "package"} months`);
            } else {
                setText("rEstimated", "Not calculated");
            }

            setText("rStatus", data.status || "Unknown");
            setText("rShelf", data.shelf_life_months ? `${data.shelf_life_months} months` : "Not stated");
            setText("rNote", data.note || "");
            setText("rOCR", data.ocr_text || "No OCR text detected");

            document.getElementById("sQuantity").value =
                form.querySelector('[name="quantity"]').value || 1;

            const confidence = Math.round((data.confidence || 0) * 100);
            setText("confidenceBadge", `Confidence ${confidence}%`);

            const confidenceNote = document.getElementById("confidenceNote");
            if (confidence < 90 || !data.expiry_date) {
                confidenceNote.textContent =
                    "⚠️ Please verify the detected date. If the date could not be captured, enter it manually below.";
            } else {
                confidenceNote.textContent = "✓ Date detection confidence is good.";
            }

            updateVerificationVisibility(data, confidence);
            renderRisk(data.risk_score, data.risk_label, data.risk_level);

            document.getElementById("sProduct").value = data.product_name || "Unknown Product";
            document.getElementById("sCategory").value = data.category || "Others";
            document.getElementById("sBarcode").value = data.barcode || "";
            document.getElementById("sMfg").value = data.manufacturing_date || "";
            document.getElementById("sExpiry").value = data.expiry_date || "";
            document.getElementById("sEstimated").value = data.estimated_expiry || "";
            document.getElementById("sPhoto").value = data.photo || "";
            document.getElementById("sExtraPhoto").value = data.extra_photo || "";
            document.getElementById("sOCR").value = data.ocr_text || "";
            document.getElementById("sConfidence").value = data.confidence || 0;

            resultBox.classList.remove("hidden");
        } catch (error) {
            alert(error.message);
        } finally {
            button.disabled = false;
            loading.classList.add("hidden");
        }
    });
}

async function applyVerification() {
    if (!latestAnalysis) return;

    const mfg = document.getElementById("verifyMfg").value.trim();
    const manuallyEnteredExpiry = document.getElementById("verifyExpiry").value.trim();

    if (!mfg && !manuallyEnteredExpiry) {
        return alert("Enter the MFG date or expiry date.");
    }

    let expiry = manuallyEnteredExpiry || latestAnalysis.expiry_date || null;
    let basis = "Manual date entered by user.";

    if (!expiry && mfg && latestAnalysis.shelf_life_months) {
        const response = await fetch("/api/recalculate-expiry", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                manufacturing_date: mfg,
                shelf_life_months: latestAnalysis.shelf_life_months
            })
        });

        const data = await response.json();
        if (!response.ok) return alert(data.error || "Could not calculate expiry.");

        expiry = data.expiry_date;
        basis = `MFG + ${latestAnalysis.shelf_life_months} months`;
    }

    if (!expiry && mfg) {
        return alert("Expiry could not be calculated. Enter the expiry date manually.");
    }

    setText("rMfg", mfg || latestAnalysis.manufacturing_date || "Not found");
    setText("rExpiry", expiry || "Not available");
    setText("rEstimated", basis);
    setText("rStatus", getStatusFromDate(expiry));

    document.getElementById("sMfg").value = mfg;
    document.getElementById("sExpiry").value =
        manuallyEnteredExpiry ? manuallyEnteredExpiry : (latestAnalysis.expiry_date || "");
    document.getElementById("sEstimated").value =
        manuallyEnteredExpiry ? "" : (expiry || "");

    latestAnalysis.manufacturing_date = mfg || latestAnalysis.manufacturing_date;
    latestAnalysis.expiry_date = manuallyEnteredExpiry || latestAnalysis.expiry_date;
    latestAnalysis.estimated_expiry = manuallyEnteredExpiry ? null : expiry;

    setText(
        "rNote",
        manuallyEnteredExpiry
            ? "✓ Expiry date manually confirmed."
            : "✓ Expiry calculated from MFG and package shelf life."
    );

    // Recalculate the visual risk score in the browser.
    const days = getDaysLeft(expiry);
    let score = null, label = "Unknown", level = "unknown";

    if (days !== null) {
        if (days < 0) {
            score = 100; label = "Expired"; level = "expired";
        } else if (days <= 10) {
            score = Math.max(80, 100 - days * 2); label = "High Risk"; level = "high";
        } else if (days <= 60) {
            score = 40 + Math.floor((60 - days) * 40 / 50); label = "Medium Risk"; level = "medium";
        } else {
            score = Math.max(0, 39 - Math.floor(Math.min(days - 60, 390) / 10));
            label = "Low Risk"; level = "low";
        }
    }

    renderRisk(score, label, level);
    document.getElementById("verificationBox").classList.add("hidden");
}

function getDaysLeft(value) {
    if (!value) return null;

    const parts = value.split(/[\/-]/).map(Number);
    let d;

    if (parts.length === 3) {
        // DD/MM/YYYY
        if (parts[2] > 1000) {
            d = new Date(parts[2], parts[1] - 1, parts[0]);
        } else {
            d = new Date(parts[0], parts[1] - 1, parts[2]);
        }
    } else if (parts.length === 2) {
        // MM/YYYY
        d = new Date(parts[1], parts[0] - 1, 1);
    } else {
        return null;
    }

    if (Number.isNaN(d.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.ceil((d - today) / 86400000);
}

function getStatusFromDate(value) {
    const days = getDaysLeft(value);
    if (days === null) return "Unknown";
    if (days < 0) return "Expired";
    if (days === 0) return "Expires Today";
    if (days <= 10) return "Expiring Soon";
    return "Safe";
}

document.getElementById("applyVerification")?.addEventListener("click", applyVerification);

async function loadNotifications() {
    const count = document.getElementById("notifyCount");
    const panel = document.getElementById("notificationPanel");
    const list = document.getElementById("notificationList");
    if (!count) return;

    try {
        const response = await fetch("/api/notifications", {cache: "no-store"});
        const payload = await response.json();
        const notices = payload.notifications || [];

        count.textContent = notices.length;

        const status = document.getElementById("emailStatus");
        if (status) {
            status.textContent = notices.length
                ? `${notices.length} expiry alert${notices.length > 1 ? "s" : ""} need attention.`
                : "No expiry alerts right now.";
        }

        if (notices.length) {
            panel.classList.remove("hidden");

            list.innerHTML = notices.map(n => `
                <div class="notice ${n.level}" role="button" tabindex="0"
                     data-product-url="${n.url}">
                    <strong>${escapeHtml(n.message)}</strong>
                    <span>Expiry: ${escapeHtml(n.expiry || "Not available")} · Tap to view product</span>
                </div>
            `).join("");

            list.querySelectorAll(".notice").forEach(item => {
                const open = () => window.location.href = item.dataset.productUrl;
                item.addEventListener("click", open);
                item.addEventListener("keydown", e => {
                    if (e.key === "Enter" || e.key === " ") open();
                });
            });
        } else {
            panel.classList.add("hidden");
            list.innerHTML = "";
        }
    } catch (e) {
        console.log("Notification load error:", e);
    }
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

document.getElementById("notifyBtn")?.addEventListener("click", async () => {
    const panel = document.getElementById("notificationPanel");
    await loadNotifications();
    panel?.scrollIntoView({behavior: "smooth"});
});

document.getElementById("enableAlertsBtn")?.addEventListener("click", async () => {
    await loadNotifications();
    document.getElementById("notificationPanel")?.scrollIntoView({behavior: "smooth"});
});

async function loadStats() {
    const total = document.getElementById("total");
    if (!total) return;

    try {
        const response = await fetch("/api/stats");
        const data = await response.json();
        total.textContent = data.total;
        document.getElementById("safe").textContent = data.safe;
        document.getElementById("soon").textContent = data.soon;
        document.getElementById("expired").textContent = data.expired;
    } catch (e) {
        console.log(e);
    }
}

loadStats();
loadNotifications();
setInterval(loadNotifications, 30000);

// Front-photo preview
const frontInput = document.querySelector('input[name="front_product_image"]');
const frontPreview = document.getElementById("frontPreview");
frontInput?.addEventListener("change", () => {
    const file = frontInput.files?.[0];
    if (!file || !frontPreview) return;
    frontPreview.src = URL.createObjectURL(file);
    frontPreview.classList.remove("hidden");
});

// Back/extra photo preview
const extraInput = document.querySelector('input[name="product_images"]');
const extraPreview = document.getElementById("extraPreview");
extraInput?.addEventListener("change", () => {
    const file = extraInput.files?.[0];
    if (!file || !extraPreview) return;
    extraPreview.src = URL.createObjectURL(file);
    extraPreview.classList.remove("hidden");
});
