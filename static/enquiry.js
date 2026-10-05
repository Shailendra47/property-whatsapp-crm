const OPTIONS = {
  planning_to_buy: [
    "Immediately", "Within 1 Month", "Within 3 Months", "Within 6 Months",
    "Within 12 Months", "More Than 1 Year", "Just Exploring / Researching",
  ],
  budget_range: [
    "Up to 25 lakh", "25 lakh - 50 lakh", "50 lakh - 1 crore",
    "1 crore - 2 crore", "Above 2 crore",
  ],
  payment_option: [
    "Bank Finance with EMI", "Full Cash Payment", "Home Loan (Mortgage)",
    "Down Payment Plan", "Construction-Linked Payment Plan (CLP)",
    "Possession-Linked Payment Plan (PLP)", "Installment Payment Plan",
    "Developer Financing", "Rent-to-Own Scheme", "Part Cash + Home Loan",
    "Part Payment with Balance at Registration", "Flexible Payment Plan",
    "Subvention Scheme (Developer Pays Pre-EMI)",
    "Joint Home Loan (Co-applicant Financing)",
    "NRI Payment Plan (for Overseas Buyers)",
  ],
  bhk_preference: [
    "1 RK", "1 BHK", "2 BHK", "2.5 BHK", "3 BHK", "3.5 BHK",
    "4 BHK", "5 BHK+", "Villa", "Penthouse",
  ],
};

const form = document.getElementById("enquiryForm");
const submitBtn = document.getElementById("submitBtn");
const mobile = document.getElementById("mobile_number");
const popup = document.getElementById("successPopup");

function showPopup() {
  popup.hidden = false;
  document.getElementById("popupOk").focus();
}
function hidePopup() {
  popup.hidden = true;
}
document.getElementById("popupOk").addEventListener("click", hidePopup);
document.getElementById("popupClose").addEventListener("click", hidePopup);
popup.addEventListener("click", (e) => { if (e.target === popup) hidePopup(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hidePopup(); });

// Fill the dropdowns
for (const [id, list] of Object.entries(OPTIONS)) {
  const select = document.getElementById(id);
  select.add(new Option("Select an option", ""));
  list.forEach((item) => select.add(new Option(item, item)));
}

// Mobile: optional +, then 10-15 digits (spaces and hyphens allowed)
function checkMobile() {
  const digits = mobile.value.replace(/[\s-]/g, "");
  mobile.setCustomValidity(/^\+?[0-9]{10,15}$/.test(digits) ? "" : "invalid");
}
mobile.addEventListener("input", checkMobile);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  checkMobile();

  if (!form.checkValidity()) {
    form.classList.add("was-validated");
    form.querySelector(":invalid").focus();
    return;
  }

  const payload = {};
  new FormData(form).forEach((value, key) => (payload[key] = value.trim()));

  submitBtn.disabled = true;
  submitBtn.textContent = "Submitting...";

  try {
    const res = await fetch("/api/enquiry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (res.ok) {
      form.reset();
      form.classList.remove("was-validated");
      showPopup();
    } else if (res.status === 422) {
      alert("Please check your details and try again.");
    } else {
      alert(data.detail || "Something went wrong.");
    }
  } catch (err) {
    alert("Could not reach the server. Please try again.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit Enquiry";
  }
});

// ---- Location suggestions while typing (OpenStreetMap data via the free Photon service)
const locInput = document.getElementById("location_preference");
const locList = document.getElementById("locList");
let locTimer, locAbort, locItems = [], locActive = -1;

function locParts(p) {
  const seen = new Set();
  return [p.name, p.locality, p.district, p.city, p.county, p.state].filter((v) => {
    if (!v || seen.has(v.toLowerCase())) return false;
    seen.add(v.toLowerCase());
    return true;
  });
}

function hideLocations() {
  locList.hidden = true;
  locActive = -1;
}

function showLocMessage(text) {
  locItems = [];
  locActive = -1;
  locList.innerHTML = "";
  const li = document.createElement("li");
  li.className = "muted";
  li.textContent = text;
  locList.appendChild(li);
  locList.hidden = false;
}

function renderLocations() {
  if (!locItems.length) {
    showLocMessage("No matching place found - you can type your own");
    return;
  }
  locList.innerHTML = "";
  locActive = -1;
  locItems.forEach((parts, i) => {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.dataset.i = i;
    li.textContent = parts[0];
    if (parts.length > 1) {
      const sub = document.createElement("small");
      sub.textContent = parts.slice(1).join(", ");
      li.appendChild(sub);
    }
    locList.appendChild(li);
  });
  locList.hidden = false;
}

function pickLocation(i) {
  locInput.value = locItems[i].join(", ");
  hideLocations();
}

function setActive(n) {
  const opts = locList.querySelectorAll("li[data-i]");
  if (!opts.length) return;
  locActive = (n + opts.length) % opts.length;
  opts.forEach((o, idx) => o.classList.toggle("active", idx === locActive));
  opts[locActive].scrollIntoView({ block: "nearest" });
}

async function searchLocations(q) {
  if (locAbort) locAbort.abort();
  locAbort = new AbortController();
  showLocMessage("Searching...");
  const params = new URLSearchParams({ q, limit: 10, lang: "en", bbox: "68.1,6.7,97.4,35.7" }); // India
  try {
    const res = await fetch("https://photon.komoot.io/api/?" + params, { signal: locAbort.signal });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    const seen = new Set();
    locItems = data.features
      .filter((f) => (f.properties.countrycode ? f.properties.countrycode === "IN" : f.properties.country === "India"))
      .map((f) => locParts(f.properties))
      .filter((parts) => {
        const key = parts.join(", ").toLowerCase();
        if (!parts.length || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 5);
    renderLocations();
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Location search failed:", err);
    showLocMessage("Suggestions are unavailable right now - you can type your own"); // the field still works as plain text
  }
}

locInput.addEventListener("input", () => {
  clearTimeout(locTimer);
  const q = locInput.value.trim();
  if (q.length < 3) { hideLocations(); return; }
  locTimer = setTimeout(() => searchLocations(q), 350);
});
locInput.addEventListener("keydown", (e) => {
  if (locList.hidden) return;
  if (e.key === "ArrowDown") { e.preventDefault(); setActive(locActive + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setActive(locActive - 1); }
  else if (e.key === "Enter" && locActive >= 0) { e.preventDefault(); pickLocation(locActive); }
  else if (e.key === "Escape") { hideLocations(); }
});
locInput.addEventListener("blur", hideLocations);
locList.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li[data-i]");
  if (li) { e.preventDefault(); pickLocation(Number(li.dataset.i)); }
});