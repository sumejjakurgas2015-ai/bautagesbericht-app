// traži dozvolu
if (Notification.permission !== "granted") {
    Notification.requestPermission();
}

// funkcija za notifikaciju
function showReminder() {
    new Notification("Bautagesbericht", {
        body: "Vrijeme je da popuniš izvještaj!",
        icon: "/static/icon-192.png"
    });
}

// provjera vremena
function checkTime() {
    const now = new Date();
    const day = now.getDay(); // 0 = nedjelja
    const hours = now.getHours();
    const minutes = now.getMinutes();

    // pon-pet (1-5) u 15:30
    if (day >= 1 && day <= 5 && hours === 15 && minutes === 30) {
        showReminder();
    }
}

// provjera svake minute
setInterval(checkTime, 60000);