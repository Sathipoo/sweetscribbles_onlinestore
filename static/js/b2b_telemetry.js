/**
 * Sweet Scribbles B2B Clickstream & Engagement Telemetry Tracker
 * Lightweight, non-blocking telemetry capturing prospect pageviews, hamper inspections,
 * budget slider adjustments, and quotation CTAs.
 */

(function () {
    'use strict';

    // 1. Resolve or Initialize Persistent Visitor ID
    function getVisitorId() {
        let vid = localStorage.getItem('ss_b2b_vid');
        if (!vid) {
            vid = 'vid_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
            try {
                localStorage.setItem('ss_b2b_vid', vid);
            } catch (e) {
                // Private browsing fallback
            }
        }
        return vid;
    }

    // 2. Resolve Campaign Tracking Token from URL (?trk=...)
    function getTrackingToken() {
        const urlParams = new URLSearchParams(window.location.search);
        const tokenFromUrl = urlParams.get('trk') || urlParams.get('token');
        if (tokenFromUrl) {
            try {
                sessionStorage.setItem('ss_b2b_trk_token', tokenFromUrl);
            } catch (e) {}
            return tokenFromUrl;
        }
        try {
            return sessionStorage.getItem('ss_b2b_trk_token') || null;
        } catch (e) {
            return null;
        }
    }

    // 3. Dispatch Telemetry Event to Storefront Receiver
    function sendTelemetry(eventType, metadata, elementIdentifier) {
        const payload = {
            event_type: eventType,
            page_url: window.location.pathname + window.location.search,
            page_title: document.title,
            element_identifier: elementIdentifier || null,
            event_metadata: metadata || null,
            tracking_token: getTrackingToken(),
            visitor_id: getVisitorId()
        };

        const endpoint = '/b2b/api/telemetry';
        const dataStr = JSON.stringify(payload);

        if (navigator.sendBeacon) {
            const blob = new Blob([dataStr], { type: 'application/json' });
            navigator.sendBeacon(endpoint, blob);
        } else {
            fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: dataStr,
                keepalive: true
            }).catch(function () {});
        }
    }

    // Expose global tracker helper
    window.ssTrackEvent = sendTelemetry;

    // 4. Initial Page View Tracking
    document.addEventListener('DOMContentLoaded', function () {
        sendTelemetry('page_view', {
            referrer: document.referrer || null,
            screen_width: window.innerWidth,
            path: window.location.pathname
        });

        // 5. Automatic Click Tracking for B2B CTAs and Products
        document.addEventListener('click', function (e) {
            const target = e.target.closest('a, button, [data-telemetry-cta], [data-telemetry-product]');
            if (!target) return;

            // Product card / Detail link
            const productEl = target.closest('[data-telemetry-product]') || (target.href && target.href.includes('/b2b/product/') ? target : null);
            if (productEl) {
                const productName = productEl.getAttribute('data-product-name') || productEl.innerText.trim().slice(0, 60);
                const productId = productEl.getAttribute('data-product-id') || null;
                sendTelemetry('product_view', {
                    product_name: productName,
                    product_id: productId,
                    action: 'click'
                }, 'product-card-' + (productId || 'link'));
                return;
            }

            // Exclude internal authentication/login buttons or explicit telemetry opt-outs
            if (target.closest('[data-no-telemetry="true"]') ||
                target.closest('#b2bLoginStepPhone, #b2bLoginStepVerify') ||
                window.location.pathname.includes('/b2b/login')) {
                return;
            }

            // CTA Buttons (Inquire, Request Quote, Catalog Download, Sample Request)
            const isCTA = target.hasAttribute('data-telemetry-cta') ||
                target.classList.contains('btn-inquire') ||
                target.classList.contains('btn-premium') ||
                /inquire|quote|proposal|catalogue|sample|brochure/i.test(target.innerText);

            if (isCTA) {
                const ctaText = target.innerText.trim().slice(0, 80);
                const ctaId = target.id || target.getAttribute('data-telemetry-cta') || 'btn-cta';
                sendTelemetry('cta_click', {
                    cta_label: ctaText,
                    target_modal: target.getAttribute('data-bs-target') || null
                }, ctaId);
            }
        });

        // 6. Range / Budget Slider Interaction (Debounced)
        let sliderTimeout = null;
        document.addEventListener('input', function (e) {
            const input = e.target;
            if (input.type === 'range' || input.classList.contains('b2b-slider') || input.id.includes('range') || input.id.includes('Qty') || input.id.includes('qty')) {
                if (sliderTimeout) clearTimeout(sliderTimeout);
                sliderTimeout = setTimeout(function () {
                    const qtyVal = input.value;
                    let budgetVal = input.getAttribute('data-calculated-budget');
                    if (!budgetVal) {
                        const totalEl = document.getElementById('calcHamperTotalEstimate') || document.querySelector('.total-budget-estimate');
                        if (totalEl) budgetVal = totalEl.innerText.trim();
                    }
                    sendTelemetry('slider_change', {
                        slider_id: input.id || 'budget-slider',
                        quantity: qtyVal,
                        budget_estimate: budgetVal
                    }, input.id || 'slider');
                }, 400);
            }
        });
    });
})();
