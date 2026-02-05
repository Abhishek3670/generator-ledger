/* ============================================================================
   Generator Booking Ledger - JavaScript
   ============================================================================ */

// Utility functions
async function fetchAPI(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Fetch error:', error);
        throw error;
    }
}

function setupSimpleTableFilter(inputId, tableId) {
    const input = document.getElementById(inputId);
    const table = document.getElementById(tableId);
    if (!input || !table) return;

    input.addEventListener('keyup', function() {
        const filter = input.value.toUpperCase();
        const tbody = table.getElementsByTagName('tbody')[0];
        if (!tbody) return;
        const rows = tbody.getElementsByTagName('tr');

        for (let i = 0; i < rows.length; i++) {
            const text = rows[i].textContent.toUpperCase();
            rows[i].style.display = text.includes(filter) ? '' : 'none';
        }
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Page loaded');
    setupSimpleTableFilter('itemFilter', 'itemTable');
});
