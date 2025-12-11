const translations = {
    ar: {
        logo: "نظام التذاكر",
        dashboard: "اللوحة الرئيسية",
        tickets: "التذاكر",
        settings: "الإعدادات",
        active_tickets: "التذاكر النشطة",
        new_tickets: "التذاكر الجديدة",
        resolved_tickets: "التذاكر المحلولة",
        onhold_tickets: "تذاكر قيد الانتظار",
        recent_tickets: "آخر التذاكر",
        ticket_id: "رقم",
        subject: "الموضوع",
        status: "الحالة",
        assignee: "المسؤول"
    },

    en: {
        logo: "IT Ticketing",
        dashboard: "Dashboard",
        tickets: "Tickets",
        settings: "Settings",
        active_tickets: "Active Tickets",
        new_tickets: "New Tickets",
        resolved_tickets: "Resolved Tickets",
        onhold_tickets: "On Hold Tickets",
        recent_tickets: "Recent Tickets",
        ticket_id: "ID",
        subject: "Subject",
        status: "Status",
        assignee: "Assignee"
    }
};

let currentLang = "ar";

document.addEventListener("DOMContentLoaded", function () {
    const toggleBtn = document.getElementById("langToggle");

    toggleBtn.addEventListener("click", function () {
        currentLang = currentLang === "ar" ? "en" : "ar";
        applyLanguage(currentLang);

        document.documentElement.dir = currentLang === "ar" ? "rtl" : "ltr";

        toggleBtn.textContent = currentLang === "ar" ? "English" : "عربي";

    });

    applyLanguage(currentLang);
});

function applyLanguage(lang) {
    document.querySelectorAll("[data-lang]").forEach(el => {
        const key = el.getAttribute("data-lang");
        el.textContent = translations[lang][key];
    });
}

