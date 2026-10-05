const form = document.getElementById("contactForm");
const submitBtn = document.getElementById("submitBtn");
const popup = document.getElementById("successPopup");
const successMessage = document.getElementById("successMessage");
const errorPopup = document.getElementById("errorPopup");
const errorMessage = document.getElementById("errorMessage");
let fieldToFocusAfterError = null;

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
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    hidePopup();
    if (!errorPopup.hidden) hideErrorPopup();
  }
});

function hideErrorPopup() {
  errorPopup.hidden = true;
  if (fieldToFocusAfterError) fieldToFocusAfterError.focus();
}
document.getElementById("errorRetry").addEventListener("click", hideErrorPopup);
errorPopup.addEventListener("click", (e) => { if (e.target === errorPopup) hideErrorPopup(); });

function fieldLabel(fieldName) {
  const labels = {
    full_name: "Full name", email: "Email", contact_number: "Contact number",
    whatsapp_opt_in: "WhatsApp preference",
  };
  return labels[fieldName] || "Form";
}

function presentApiError(data, status) {
  fieldToFocusAfterError = null;
  const detail = data?.detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.at(-1) : "";
      if (location && location !== "body") fieldToFocusAfterError = form.elements.namedItem(location);
      const reason = item.msg === "Field required" ? "is required" : item.msg;
      return `${fieldLabel(location)} ${reason}.`;
    });
    return messages.join(" ");
  }
  if (typeof detail === "string") {
    const match = detail.match(/(?:Enter|Please enter) (?:the )?(?:WhatsApp )?number/i);
    if (match) fieldToFocusAfterError = form.elements.namedItem("contact_number");
    return detail;
  }
  return status === 422
    ? "Some information could not be validated. Please check your entries and try again."
    : "We could not send your enquiry right now. Please try again in a moment.";
}

function showError(message) {
  errorMessage.textContent = message;
  errorPopup.hidden = false;
  document.getElementById("errorRetry").focus();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!form.checkValidity()) {
    form.classList.add("was-validated");
    return;
  }

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  submitBtn.disabled = true;
  submitBtn.textContent = "Sending...";

  try {
    const res = await fetch("/api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (res.ok) {
      form.reset();
      form.classList.remove("was-validated");
      successMessage.textContent = data.whatsapp_status === "accepted"
        ? "Your enquiry is saved and Twilio accepted the WhatsApp start message. Open WhatsApp and reply to continue with the property questions."
        : data.whatsapp_status === "not_requested"
          ? "Your enquiry is saved. You did not select WhatsApp questionnaire delivery."
        : data.whatsapp_status === "configuration_missing"
          ? `Your enquiry is saved, but WhatsApp is not configured yet. Add these settings to the server .env file, then restart the app: ${(data.whatsapp_missing_settings || []).join(", ")}.`
          : "Your enquiry is saved, but Twilio rejected the WhatsApp start message. Check the app terminal and Twilio Messaging Logs for the error. Sandbox messaging only supports its pre-approved templates.";
      showPopup();
    } else {
      showError(presentApiError(data, res.status));
    }
  } catch (err) {
    showError("We couldn't reach the server. Check your connection and try submitting again.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Send Enquiry";
  }
});
