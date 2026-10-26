
"use strict";

/* ==========================================
   AI HEALTH PREDICTION APP - SCRIPT.JS
   ========================================== */

document.addEventListener("DOMContentLoaded", () => {
    initializePatientSearch();
    initializePatientForm();
    initializeDeleteConfirmation();
    initializeFlashMessages();
});


/* ==========================================
   1. PATIENT TABLE SEARCH
   ========================================== */

function initializePatientSearch() {
    const searchInput = document.getElementById("searchInput");
    const patientTable = document.getElementById("patientTable");

    if (!searchInput || !patientTable) {
        return;
    }

    searchInput.addEventListener("input", () => {
        const searchTerm = searchInput.value.trim().toLowerCase();
        const rows = patientTable.querySelectorAll("tbody tr");

        rows.forEach((row) => {
            // Ignore the empty-table message.
            if (row.querySelectorAll("td").length <= 1) {
                return;
            }

            const rowText = row.innerText.toLowerCase();
            row.style.display = rowText.includes(searchTerm) ? "" : "none";
        });
    });
}


/* ==========================================
   2. PATIENT FORM VALIDATION
   ========================================== */

function initializePatientForm() {
    const patientForm = document.getElementById("patientForm");

    if (!patientForm) {
        return;
    }

    patientForm.addEventListener("submit", (event) => {
        const nameInput = patientForm.querySelector(
            '[name="full_name"]'
        );

        const dobInput = patientForm.querySelector(
            '[name="date_of_birth"]'
        );

        const emailInput = patientForm.querySelector(
            '[name="email"]'
        );

        const numericFields = [
            "glucose",
            "haemoglobin",
            "cholesterol"
        ];

        if (!nameInput || !dobInput || !emailInput) {
            return;
        }

        const fullName = nameInput.value.trim();
        const email = emailInput.value.trim();
        const dob = parsePatientDate(dobInput.value.trim());

        if (!fullName) {
            event.preventDefault();
            alert("Please enter the patient's full name.");
            nameInput.focus();
            return;
        }

        if (!isValidEmail(email)) {
            event.preventDefault();
            alert("Please enter a valid email address.");
            emailInput.focus();
            return;
        }

        if (!dob) {
            event.preventDefault();
            alert(
                "Invalid date of birth. Use DD/MM/YYYY or DD.MM.YYYY."
            );
            dobInput.focus();
            return;
        }

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        if (dob > today) {
            event.preventDefault();
            alert("Date of birth cannot be in the future.");
            dobInput.focus();
            return;
        }

        for (const fieldName of numericFields) {
            const input = patientForm.querySelector(
                `[name="${fieldName}"]`
            );

            if (!input) {
                continue;
            }

            const value = input.value.trim();
            const number = Number(value);

            if (
                value === "" ||
                !Number.isFinite(number) ||
                number < 0 ||
                number > 100000
            ) {
                event.preventDefault();

                alert(
                    `${fieldName} must be a valid non-negative number.`
                );

                input.focus();
                return;
            }
        }

        // Prevent accidental repeated submissions.
        const submitButton = patientForm.querySelector(
            'button[type="submit"]'
        );

        if (submitButton && !submitButton.disabled) {
            submitButton.disabled = true;
            submitButton.textContent = "Processing...";
        }
    });
}


/* ==========================================
   3. DATE VALIDATION
   Supports DD/MM/YYYY, DD.MM.YYYY,
   and YYYY-MM-DD.
   ========================================== */

function parsePatientDate(value) {
    let day;
    let month;
    let year;

    let match = value.match(
        /^(\d{2})[/.](\d{2})[/.](\d{4})$/
    );

    if (match) {
        day = Number(match[1]);
        month = Number(match[2]);
        year = Number(match[3]);
    } else {
        match = value.match(
            /^(\d{4})-(\d{2})-(\d{2})$/
        );

        if (!match) {
            return null;
        }

        year = Number(match[1]);
        month = Number(match[2]);
        day = Number(match[3]);
    }

    if (
        year < 1 ||
        month < 1 ||
        month > 12 ||
        day < 1 ||
        day > 31
    ) {
        return null;
    }

    const parsedDate = new Date(year, month - 1, day);

    // Reject impossible dates such as 31 November.
    if (
        parsedDate.getFullYear() !== year ||
        parsedDate.getMonth() !== month - 1 ||
        parsedDate.getDate() !== day
    ) {
        return null;
    }

    parsedDate.setHours(0, 0, 0, 0);

    return parsedDate;
}


/* ==========================================
   4. EMAIL VALIDATION
   ========================================== */

function isValidEmail(email) {
    const pattern =
        /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/;

    return email.length <= 254 && pattern.test(email);
}


/* ==========================================
   5. DELETE CONFIRMATION
   ========================================== */

function initializeDeleteConfirmation() {
    const deleteForms = document.querySelectorAll(
        'form[action*="/patients/delete/"]'
    );

    deleteForms.forEach((form) => {
        form.addEventListener("submit", (event) => {
            const confirmed = window.confirm(
                "Are you sure you want to delete this patient record? " +
                "This action cannot be undone."
            );

            if (!confirmed) {
                event.preventDefault();
            }
        });
    });
}


/* ==========================================
   6. FLASH MESSAGE AUTO-DISMISS
   ========================================== */

function initializeFlashMessages() {
    const alerts = document.querySelectorAll(".alert");

    alerts.forEach((alert) => {
        // Keep error messages visible so users can read them.
        if (alert.classList.contains("error")) {
            return;
        }

        window.setTimeout(() => {
            alert.style.transition = "opacity 0.4s ease";
            alert.style.opacity = "0";

            window.setTimeout(() => {
                alert.remove();
            }, 400);
        }, 5000);
    });
});
