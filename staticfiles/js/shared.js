/**
 * Shared utilities for Sales Agent
 * Single source of truth for common functions used across all pages.
 */

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(isoString) {
    try {
        const d = new Date(isoString);
        return d.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch (e) {
        return isoString;
    }
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
}

function copyToClipboard(text, message) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(message || 'Copied to clipboard', 'success');
        }).catch(() => {
            showToast('Failed to copy', 'error');
        });
    } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showToast(message || 'Copied to clipboard', 'success');
        } catch (e) {
            showToast('Failed to copy', 'error');
        }
        document.body.removeChild(textarea);
    }
}

function animateCount(element, targetValue, duration = 500) {
    if (!element) return;
    const startValue = 0;
    const startTime = Date.now();
    const updateCount = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const currentValue = Math.floor(startValue + (targetValue - startValue) * progress);
        element.textContent = currentValue;
        if (progress < 1) requestAnimationFrame(updateCount);
    };
    updateCount();
}

function createSkeletonCard() {
    return `
        <div class="animate-pulse bg-slate-800/50 border border-slate-700 rounded-2xl p-4 h-48">
            <div class="h-4 bg-slate-700 rounded w-3/4 mb-3"></div>
            <div class="h-3 bg-slate-700 rounded w-1/2 mb-2"></div>
            <div class="h-3 bg-slate-700 rounded w-2/3 mb-2"></div>
            <div class="h-3 bg-slate-700 rounded w-1/2"></div>
        </div>
    `;
}

function showToast(message, type = 'info') {
    const existing = document.getElementById('shared-toast-container');
    let container = existing;
    if (!container) {
        container = document.createElement('div');
        container.id = 'shared-toast-container';
        container.className = 'fixed top-4 right-4 z-50 flex flex-col gap-3 max-w-sm';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const colors = {
        success: 'bg-green-600',
        error: 'bg-red-600',
        warning: 'bg-yellow-600',
        info: 'bg-blue-600'
    };
    const icons = {
        success: 'M5 13l4 4L19 7',
        error: 'M6 18L18 6M6 6l12 12',
        warning: 'M12 9v4m0 4h.01',
        info: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
    };

    toast.className = `${colors[type] || colors.info} text-white px-4 py-3 rounded-lg shadow-xl flex items-start gap-3 transform translate-x-0 transition-all duration-300`;
    toast.innerHTML = `
        <svg class="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${icons[type] || icons.info}"/>
        </svg>
        <span class="text-sm flex-1">${message}</span>
        <button onclick="this.closest('#shared-toast-container').removeChild(this.parentElement)" class="text-white/70 hover:text-white flex-shrink-0">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
        </button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => { if (toast.parentElement) toast.parentElement.removeChild(toast); }, 300);
    }, 5000);
}
