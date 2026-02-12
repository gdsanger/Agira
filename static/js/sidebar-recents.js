/**
 * Agira Sidebar Recents & Pinned Feature
 * Manages recently viewed and pinned items in localStorage
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        MAX_RECENTS: 20,
        MAX_PINNED: 5,
        STORAGE_KEYS: {
            RECENTS: 'agira.sidebar.recents.v1',
            PINNED: 'agira.sidebar.pinned.v1'
        }
    };

    // Internal state
    let recents = [];
    let pinned = [];

    /**
     * Initialize the module
     */
    function init() {
        loadFromStorage();
        renderSidebar();
        setupEventListeners();
        checkForRecentTouch();
    }

    /**
     * Load data from localStorage
     */
    function loadFromStorage() {
        try {
            const recentsData = localStorage.getItem(CONFIG.STORAGE_KEYS.RECENTS);
            const pinnedData = localStorage.getItem(CONFIG.STORAGE_KEYS.PINNED);
            
            recents = recentsData ? JSON.parse(recentsData) : [];
            pinned = pinnedData ? JSON.parse(pinnedData) : [];
        } catch (error) {
            console.error('Error loading from localStorage:', error);
            recents = [];
            pinned = [];
        }
    }

    /**
     * Save data to localStorage
     */
    function saveToStorage() {
        try {
            localStorage.setItem(CONFIG.STORAGE_KEYS.RECENTS, JSON.stringify(recents));
            localStorage.setItem(CONFIG.STORAGE_KEYS.PINNED, JSON.stringify(pinned));
        } catch (error) {
            console.error('Error saving to localStorage:', error);
        }
    }

    /**
     * Touch a recent item (add or update)
     */
    function touchRecent(entry) {
        // Remove if already exists (to avoid duplicates)
        recents = recents.filter(item => !(item.type === entry.type && item.id === entry.id));
        
        // Add timestamp
        entry.ts = new Date().toISOString();
        
        // Add to beginning
        recents.unshift(entry);
        
        // Enforce limit
        if (recents.length > CONFIG.MAX_RECENTS) {
            recents = recents.slice(0, CONFIG.MAX_RECENTS);
        }
        
        saveToStorage();
        renderSidebar();
    }

    /**
     * Pin an item
     */
    function pinItem(entry) {
        // Check if already pinned
        if (pinned.some(item => item.type === entry.type && item.id === entry.id)) {
            showToast('Item ist bereits angepinnt.', 'info');
            return;
        }
        
        // Check limit
        if (pinned.length >= CONFIG.MAX_PINNED) {
            showToast(`Maximal ${CONFIG.MAX_PINNED} Items können angepinnt werden.`, 'warning');
            return;
        }
        
        // Remove from recents if present
        recents = recents.filter(item => !(item.type === entry.type && item.id === entry.id));
        
        // Add to pinned
        pinned.push(entry);
        
        saveToStorage();
        renderSidebar();
        showToast('Item wurde angepinnt.', 'success');
    }

    /**
     * Unpin an item
     */
    function unpinItem(entry) {
        pinned = pinned.filter(item => !(item.type === entry.type && item.id === entry.id));
        
        // Optionally add back to recents with current timestamp
        entry.ts = new Date().toISOString();
        recents.unshift(entry);
        
        // Enforce limit
        if (recents.length > CONFIG.MAX_RECENTS) {
            recents = recents.slice(0, CONFIG.MAX_RECENTS);
        }
        
        saveToStorage();
        renderSidebar();
        showToast('Item wurde entpinnt.', 'success');
    }

    /**
     * Remove an item from recents
     */
    function removeRecent(entry) {
        recents = recents.filter(item => !(item.type === entry.type && item.id === entry.id));
        saveToStorage();
        renderSidebar();
    }

    /**
     * Remove an item from pinned
     */
    function removePinned(entry) {
        pinned = pinned.filter(item => !(item.type === entry.type && item.id === entry.id));
        saveToStorage();
        renderSidebar();
    }

    /**
     * Clear all recents
     */
    function clearRecents() {
        if (confirm('Möchten Sie wirklich alle zuletzt geöffneten Items löschen?')) {
            recents = [];
            saveToStorage();
            renderSidebar();
            showToast('Zuletzt geöffnete Items wurden gelöscht.', 'success');
        }
    }

    /**
     * Get icon for item type
     */
    function getTypeIcon(type) {
        const icons = {
            'issue': 'bi-exclamation-circle',
            'project': 'bi-folder'
        };
        return icons[type] || 'bi-file-text';
    }

    /**
     * Get label for item type
     */
    function getTypeLabel(type) {
        const labels = {
            'issue': 'Issue',
            'project': 'Projekt'
        };
        return labels[type] || type;
    }

    /**
     * Format status display
     */
    function formatStatus(status) {
        if (!status) return '';
        return status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    /**
     * Render a single entry
     */
    function renderEntry(entry, isPinned) {
        const currentUrl = window.location.pathname;
        const isActive = currentUrl === entry.url;
        const activeClass = isActive ? 'active' : '';
        
        const typeIcon = getTypeIcon(entry.type);
        const typeLabel = getTypeLabel(entry.type);
        const statusDisplay = entry.status ? formatStatus(entry.status) : '';
        
        // Escape HTML entities in title for safe attribute usage
        const escapedTitle = entry.title
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        
        const pinButton = isPinned
            ? `<button class="btn btn-sm btn-link text-warning p-0 ms-1 recents-action" data-action="unpin" title="Entpinnen">
                   <i class="bi bi-pin-fill"></i>
               </button>`
            : `<button class="btn btn-sm btn-link text-muted p-0 ms-1 recents-action" data-action="pin" title="Anpinnen">
                   <i class="bi bi-pin"></i>
               </button>`;
        
        const removeButton = `<button class="btn btn-sm btn-link text-danger p-0 ms-1 recents-action" data-action="remove" title="Entfernen">
                                  <i class="bi bi-x-circle"></i>
                              </button>`;
        
        // Build status container with HTMX attributes for periodic updates
        // Only add HTMX for issue types that have an ID (not projects currently)
        let statusHtml = '';
        if (entry.type === 'issue' && entry.id) {
            // Status container with HTMX polling
            statusHtml = `<span 
                id="recent-status-${entry.id}" 
                class="recents-entry-status"
                hx-get="/items/${entry.id}/status/"
                hx-trigger="load, every 30s"
                hx-swap="innerHTML">${statusDisplay}</span>`;
        } else if (statusDisplay) {
            // Fallback for non-HTMX status display
            statusHtml = `<span class="recents-entry-status">${statusDisplay}</span>`;
        }
        
        return `
            <a href="${entry.url}" 
               class="recents-entry ${activeClass}" 
               data-type="${entry.type}" 
               data-id="${entry.id}"
               data-is-pinned="${isPinned}"
               data-bs-toggle="tooltip"
               title="${escapedTitle}">
                <div class="recents-entry-content">
                    <div class="recents-entry-header">
                        <i class="bi ${typeIcon} me-1"></i>
                        <span class="recents-entry-title">${entry.title}</span>
                    </div>
                    <div class="recents-entry-meta">
                        <span class="recents-entry-type">${typeLabel}</span>
                        ${statusHtml}
                    </div>
                </div>
                <div class="recents-entry-actions">
                    ${pinButton}
                    ${removeButton}
                </div>
            </a>
        `;
    }

    /**
     * Render the sidebar
     */
    function renderSidebar() {
        const container = document.getElementById('recents-pinned-container');
        if (!container) return;
        
        // Dispose tooltips before clearing container
        disposeTooltips();
        
        let html = '';
        
        // Render pinned items
        if (pinned.length > 0) {
            html += '<div class="recents-section">';
            html += '<div class="recents-section-header">';
            html += '<span class="recents-section-title">Gepinnt</span>';
            html += `<span class="recents-section-count">${pinned.length}/${CONFIG.MAX_PINNED}</span>`;
            html += '</div>';
            html += '<div class="recents-list">';
            pinned.forEach(entry => {
                html += renderEntry(entry, true);
            });
            html += '</div>';
            html += '</div>';
        }
        
        // Render recents
        if (recents.length > 0) {
            html += '<div class="recents-section">';
            html += '<div class="recents-section-header">';
            html += '<span class="recents-section-title">Zuletzt geöffnet</span>';
            html += `<span class="recents-section-count">${recents.length}/${CONFIG.MAX_RECENTS}</span>`;
            html += '</div>';
            html += '<div class="recents-list">';
            recents.forEach(entry => {
                html += renderEntry(entry, false);
            });
            html += '</div>';
            html += '<div class="recents-clear">';
            html += '<button class="btn btn-sm btn-link text-muted" id="clear-recents">Alle löschen</button>';
            html += '</div>';
            html += '</div>';
        }
        
        // Show empty state if no items
        if (pinned.length === 0 && recents.length === 0) {
            html = '<div class="recents-empty">Keine zuletzt geöffneten Items</div>';
        }
        
        container.innerHTML = html;
        
        // Process HTMX attributes in the newly rendered content
        if (typeof htmx !== 'undefined') {
            htmx.process(container);
        }
        
        // Initialize Bootstrap tooltips for the rendered entries
        initializeTooltips();
    }
    
    /**
     * Dispose of existing tooltips to prevent memory leaks
     */
    function disposeTooltips() {
        const existingTooltips = document.querySelectorAll('.recents-entry[data-bs-toggle="tooltip"]');
        existingTooltips.forEach(el => {
            const tooltipInstance = bootstrap.Tooltip.getInstance(el);
            if (tooltipInstance) {
                tooltipInstance.dispose();
            }
        });
    }
    
    /**
     * Initialize Bootstrap tooltips for recent entries
     */
    function initializeTooltips() {
        // Initialize tooltips for all recent entries
        const tooltipTriggerList = document.querySelectorAll('.recents-entry[data-bs-toggle="tooltip"]');
        tooltipTriggerList.forEach(tooltipTriggerEl => {
            new bootstrap.Tooltip(tooltipTriggerEl, {
                placement: 'left',
                trigger: 'hover'
            });
        });
    }

    /**
     * Setup event listeners
     */
    function setupEventListeners() {
        // Use event delegation for dynamically created elements
        document.addEventListener('click', function(e) {
            // Handle action buttons
            const actionButton = e.target.closest('.recents-action');
            if (actionButton) {
                e.preventDefault();
                e.stopPropagation();
                
                const action = actionButton.dataset.action;
                const entry = actionButton.closest('.recents-entry');
                if (!entry) return;
                
                // Validate and parse ID
                const idValue = entry.dataset.id;
                const parsedId = parseInt(idValue, 10);
                if (isNaN(parsedId) || parsedId <= 0) {
                    console.error('Invalid entry ID:', idValue);
                    return;
                }
                
                const entryData = {
                    type: entry.dataset.type,
                    id: parsedId,
                    title: entry.querySelector('.recents-entry-title').textContent,
                    url: entry.getAttribute('href'),
                    status: entry.querySelector('.recents-entry-status')?.textContent || ''
                };
                
                const isPinned = entry.dataset.isPinned === 'true';
                
                if (action === 'pin') {
                    pinItem(entryData);
                } else if (action === 'unpin') {
                    unpinItem(entryData);
                } else if (action === 'remove') {
                    if (isPinned) {
                        removePinned(entryData);
                    } else {
                        removeRecent(entryData);
                    }
                }
            }
            
            // Handle clear recents button
            if (e.target.id === 'clear-recents' || e.target.closest('#clear-recents')) {
                e.preventDefault();
                clearRecents();
            }
        });
    }

    /**
     * Check if current page has a recent-touch marker
     */
    function checkForRecentTouch() {
        const touchMarker = document.querySelector('[data-recent-touch="1"]');
        if (!touchMarker) return;
        
        // Validate and parse ID
        const idValue = touchMarker.dataset.recentId;
        const parsedId = parseInt(idValue, 10);
        if (isNaN(parsedId) || parsedId <= 0) {
            console.error('Invalid recent touch ID:', idValue);
            return;
        }
        
        const entry = {
            type: touchMarker.dataset.recentType,
            id: parsedId,
            title: touchMarker.dataset.recentTitle,
            status: touchMarker.dataset.recentStatus || '',
            url: touchMarker.dataset.recentUrl
        };
        
        // Check if this item is pinned - if so, don't add to recents
        if (!pinned.some(item => item.type === entry.type && item.id === entry.id)) {
            touchRecent(entry);
        }
    }

    /**
     * Show toast notification (uses global showToast if available)
     */
    function showToast(message, severity) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, severity);
        } else {
            console.log(`[${severity}] ${message}`);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export for external access if needed
    window.AgiraSidebarRecents = {
        touchRecent,
        pinItem,
        unpinItem,
        clearRecents
    };
})();
