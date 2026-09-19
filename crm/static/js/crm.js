/**
 * Sweet Scribbles CRM Frontend Scripts
 * Handles live radar polling and interactive sales actions.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Live Radar Activity Ticker Polling
    const liveFeedContainer = document.getElementById('crmLiveActivityStream');
    if (liveFeedContainer) {
        let lastSeenId = 0;
        
        setInterval(async function () {
            try {
                const res = await fetch('/api/radar-feed');
                if (!res.ok) return;
                const data = await res.json();
                if (data.success && data.events && data.events.length > 0) {
                    const topEvent = data.events[0];
                    if (topEvent.id !== lastSeenId && lastSeenId !== 0) {
                        // Pulse the ticker badge
                        const tickerBadge = document.getElementById('liveRadarPulse');
                        if (tickerBadge) {
                            tickerBadge.classList.add('badge-hot-pulse');
                            setTimeout(() => tickerBadge.classList.remove('badge-hot-pulse'), 3000);
                        }
                    }
                    lastSeenId = topEvent.id;
                }
            } catch (e) {}
        }, 12000);
    }

    // 2. Clipboard Tracking Link Copy
    document.querySelectorAll('.btn-copy-link').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const url = this.getAttribute('data-url');
            if (url) {
                navigator.clipboard.writeText(url).then(() => {
                    const origText = this.innerHTML;
                    this.innerHTML = '<i class="bi bi-check-lg me-1"></i>Copied!';
                    this.classList.replace('btn-outline-warning', 'btn-success');
                    setTimeout(() => {
                        this.innerHTML = origText;
                        this.classList.replace('btn-success', 'btn-outline-warning');
                    }, 2000);
                });
            }
        });
    });
});
