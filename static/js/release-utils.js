/**
 * Shared utility functions for Release and Change management
 */

/**
 * Handle response from creating a Change from a Release
 * @param {Event} event - HTMX after-request event
 */
function handleCreateChangeResponse(event) {
    const xhr = event.detail.xhr;
    
    if (xhr.status === 200) {
        try {
            const response = JSON.parse(xhr.responseText);
            if (response.success) {
                showToast('success', 'Success', response.message);
                // Redirect to the new change detail page
                setTimeout(() => {
                    window.location.href = `/changes/${response.change_id}/`;
                }, 1000);
            } else {
                showToast('error', 'Error', response.error || 'Failed to create change');
            }
        } catch (e) {
            showToast('error', 'Error', 'Unexpected response from server');
        }
    } else {
        showToast('error', 'Error', 'Failed to create change');
    }
}
