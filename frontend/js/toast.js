/* === toast.js === */
function showToast(message, type) {
    type = type || 'info';
    var toast = document.createElement('div');
    toast.className = 'toast-notification toast-' + type;
    toast.textContent = message;
    toast.style.cssText = 'position:fixed;bottom:20px;right:20px;padding:12px 24px;border-radius:8px;color:#fff;font-size:14px;z-index:99999;animation:fadeIn 0.3s ease;box-shadow:0 4px 12px rgba(0,0,0,0.15);';
    if (type === 'error') toast.style.background = '#ff3b30';
    else if (type === 'warning') toast.style.background = '#ff9500';
    else if (type === 'success') toast.style.background = '#34c759';
    else toast.style.background = '#0071e3';
    document.body.appendChild(toast);
    setTimeout(function() {
        toast.style.animation = 'fadeOut 0.3s ease';
        setTimeout(function() { toast.remove(); }, 300);
    }, 3000);
}
