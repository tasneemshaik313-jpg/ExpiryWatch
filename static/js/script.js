const form = document.getElementById("analyzeForm");
let latestAnalysis = null;

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
            const response = await fetch("/analyze", { method: "POST", body: new FormData(form) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Analysis failed.");
            latestAnalysis = data;

            document.getElementById("rProduct").textContent = data.product_name || "Unknown Product";
            document.getElementById("rCategory").textContent = data.category || "Others";
            document.getElementById("rBarcode").textContent = data.barcode || "Not found";
            document.getElementById("rMfg").textContent = data.manufacturing_date || "Not found";
            document.getElementById("rExpiry").textContent = data.expiry_date || data.estimated_expiry || "Not available";
            document.getElementById("rEstimated").textContent = data.expiry_date ? "Printed on package" : (data.estimated_expiry ? `MFG + ${data.shelf_life_months} months` : "Not calculated");
            document.getElementById("rStatus").textContent = data.status || "Unknown";
            document.getElementById("rShelf").textContent = data.shelf_life_months ? `${data.shelf_life_months} months` : "Not stated";
            document.getElementById("rNote").textContent = data.note || "";
            document.getElementById("rOCR").textContent = data.ocr_text || "No OCR text detected";
            document.getElementById("sQuantity").value = form.querySelector('[name="quantity"]').value || 1;

            const confidence = Math.round((data.confidence || 0) * 100);
            document.getElementById("confidenceBadge").textContent = `Confidence ${confidence}%`;

            const verification = document.getElementById("verificationBox");
            const needsMfgEdit = !!data.manufacturing_date && !data.expiry_date;
            if (needsMfgEdit || confidence < 90) {
                verification.classList.remove("hidden");
                document.getElementById("verifyMfg").value = data.manufacturing_date || "";
                document.getElementById("verifyExpiry").value = data.expiry_date || data.estimated_expiry || "";
                document.getElementById("verifyExpiry").readOnly = true;
            } else {
                verification.classList.add("hidden");
            }

            document.getElementById("sProduct").value = data.product_name || "Unknown Product";
            document.getElementById("sCategory").value = data.category || "Others";
            document.getElementById("sBarcode").value = data.barcode || "";
            document.getElementById("sMfg").value = data.manufacturing_date || "";
            document.getElementById("sExpiry").value = data.expiry_date || "";
            document.getElementById("sEstimated").value = data.estimated_expiry || "";
            document.getElementById("sPhoto").value = data.photo || "";
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
    if (!mfg) return alert("Enter the correct MFG date, e.g. 03/2024.");

    let expiry = latestAnalysis.expiry_date || null;
    if (!expiry && latestAnalysis.shelf_life_months) {
        const response = await fetch("/api/recalculate-expiry", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ manufacturing_date: mfg, shelf_life_months: latestAnalysis.shelf_life_months })
        });
        const data = await response.json();
        if (!response.ok) return alert(data.error || "Could not calculate expiry.");
        expiry = data.expiry_date;
    }

    document.getElementById("rMfg").textContent = mfg;
    document.getElementById("rExpiry").textContent = expiry || "Not available";
    document.getElementById("rEstimated").textContent = expiry ? (latestAnalysis.expiry_date ? "Printed on package" : `MFG + ${latestAnalysis.shelf_life_months} months`) : "Not calculated";
    document.getElementById("sMfg").value = mfg;
    document.getElementById("sExpiry").value = latestAnalysis.expiry_date || "";
    document.getElementById("sEstimated").value = latestAnalysis.expiry_date ? "" : (expiry || "");
    document.getElementById("rNote").textContent = expiry ? "✓ MFG confirmed. Expiry recalculated from the package shelf-life rule." : "✓ MFG confirmed. No package shelf-life rule was available.";
    document.getElementById("verificationBox").classList.add("hidden");
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
        const emailStatus = document.getElementById("emailStatus");
        if (emailStatus) emailStatus.textContent = payload.email_configured ? `Email alerts active · ${payload.email}` : "Browser alerts active · Email setup required";
        if (notices.length) {
            panel.classList.remove("hidden");
            list.innerHTML = notices.map(n => `<div class="notice ${n.level}"><strong>${n.message}</strong><span>Expiry: ${n.expiry}</span></div>`).join("");
            if ("Notification" in window && Notification.permission === "granted") {
                const todayKey = new Date().toISOString().slice(0,10);
                notices.forEach(n => {
                    const key = `expirywatch-${todayKey}-${n.product}-${n.days}`;
                    if (!localStorage.getItem(key)) {
                        new Notification("ExpiryWatch alert", {body: `${n.product}: ${n.days === 0 ? "expires today" : `expires in ${n.days} days`}.`});
                        localStorage.setItem(key, "1");
                    }
                });
            }
        } else {
            panel.classList.add("hidden");
        }
    } catch(e) { console.log(e); }
}

document.getElementById("notifyBtn")?.addEventListener("click", async () => {
    if (!("Notification" in window)) return alert("Browser notifications are not supported in this browser.");
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
        new Notification("ExpiryWatch alerts enabled", {body: "You will receive expiry reminders while this app is open."});
        loadNotifications();
    } else {
        alert("Please allow notifications in the browser permission popup.");
    }
});
document.getElementById("enableAlertsBtn")?.addEventListener("click", async () => {
    if (!("Notification" in window)) return alert("Browser notifications are not supported in this browser.");
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
        new Notification("ExpiryWatch alerts enabled", {body: "Real expiry reminders are now enabled on this browser."});
        loadNotifications();
    } else {
        alert("Please allow notifications when Chrome asks.");
    }
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
    } catch (e) { console.log(e); }
}
loadStats();
loadNotifications();
setInterval(loadNotifications, 30000);

// Instant front-photo preview: makes the scanner feel like an app, without
// uploading anything until the user presses Analyze Product.
const frontInput = document.querySelector('input[name="front_product_image"]');
const frontPreview = document.getElementById('frontPreview');
frontInput?.addEventListener('change', () => {
    const file = frontInput.files?.[0];
    if (!file || !frontPreview) return;
    frontPreview.src = URL.createObjectURL(file);
    frontPreview.classList.remove('hidden');
});
