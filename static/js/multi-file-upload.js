/**
 * Multi-file Upload Component with Drag & Drop and Progress Tracking
 * 
 * Usage:
 * new MultiFileUpload({
 *   dropZoneId: 'drop-zone',
 *   fileInputId: 'file-input',
 *   uploadUrl: '/upload/',
 *   csrfToken: 'token',
 *   onSuccess: (response) => {},
 *   onError: (error) => {}
 * });
 */

class MultiFileUpload {
    constructor(options) {
        this.dropZone = document.getElementById(options.dropZoneId);
        this.fileInput = document.getElementById(options.fileInputId);
        this.uploadUrl = options.uploadUrl;
        this.csrfToken = options.csrfToken;
        this.onSuccess = options.onSuccess || (() => {});
        this.onError = options.onError || (() => {});
        this.onAllComplete = options.onAllComplete || (() => {});
        this.maxFileSize = options.maxFileSize || 25 * 1024 * 1024; // 25MB default
        this.allowedTypes = options.allowedTypes || null; // null = all types allowed
        
        this.uploadQueue = [];
        this.activeUploads = 0;
        this.maxConcurrentUploads = 3;
        
        // Bind event handlers to preserve 'this' context and allow cleanup
        this.boundPreventDefaults = (e) => this.preventDefaults(e);
        this.boundAddDragOver = () => this.dropZone.classList.add('drag-over');
        this.boundRemoveDragOver = () => this.dropZone.classList.remove('drag-over');
        this.boundHandleDrop = (e) => {
            this.preventDefaults(e);  // Ensure browser doesn't open the file
            const dt = e.dataTransfer;
            const files = dt.files;
            this.handleFiles(files);
        };
        this.boundHandleFileInputChange = (e) => this.handleFiles(e.target.files);
        this.boundClickHandler = (e) => {
            // Don't trigger if clicking on the file input itself
            if (e.target.tagName !== 'INPUT') {
                e.preventDefault();
                e.stopPropagation();
                this.fileInput.click();
            }
        };
        
        this.init();
    }
    
    init() {
        if (!this.dropZone || !this.fileInput) {
            console.error('Drop zone or file input not found');
            return;
        }
        
        // File input change handler
        this.fileInput.addEventListener('change', this.boundHandleFileInputChange);
        
        // Click handler for drop zone to trigger file input
        this.dropZone.addEventListener('click', this.boundClickHandler, false);
        
        // Drag and drop handlers for drop zone
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            this.dropZone.addEventListener(eventName, this.boundPreventDefaults, false);
        });
        
        ['dragenter', 'dragover'].forEach(eventName => {
            this.dropZone.addEventListener(eventName, this.boundAddDragOver, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            this.dropZone.addEventListener(eventName, this.boundRemoveDragOver, false);
        });
        
        this.dropZone.addEventListener('drop', this.boundHandleDrop, false);
        
        // Prevent default drag and drop behavior on the entire document
        // This prevents the browser from opening files when dropped outside the drop zone
        ['dragenter', 'dragover', 'drop'].forEach(eventName => {
            document.addEventListener(eventName, this.boundPreventDefaults, false);
        });
    }
    
    preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    handleFiles(files) {
        const fileArray = Array.from(files);
        
        fileArray.forEach(file => {
            // Validate file
            const validation = this.validateFile(file);
            if (!validation.valid) {
                this.showError(file.name, validation.error);
                return;
            }
            
            // Add to queue
            const uploadItem = {
                id: this.generateId(),
                file: file,
                progress: 0,
                status: 'queued'
            };
            
            this.uploadQueue.push(uploadItem);
            this.createProgressElement(uploadItem);
        });
        
        // Start processing queue
        this.processQueue();
    }
    
    validateFile(file) {
        // Check file size
        if (file.size > this.maxFileSize) {
            return {
                valid: false,
                error: `File size exceeds maximum allowed size of ${this.formatBytes(this.maxFileSize)}`
            };
        }
        
        // Check file type if restrictions exist
        if (this.allowedTypes && this.allowedTypes.length > 0) {
            const fileType = file.type || '';
            const fileName = file.name || '';
            const fileExtension = fileName.split('.').pop().toLowerCase();
            
            const isAllowed = this.allowedTypes.some(type => {
                if (type.startsWith('.')) {
                    return fileExtension === type.substring(1).toLowerCase();
                }
                return fileType.match(type);
            });
            
            if (!isAllowed) {
                return {
                    valid: false,
                    error: `File type not allowed. Allowed types: ${this.allowedTypes.join(', ')}`
                };
            }
        }
        
        return { valid: true };
    }
    
    generateId() {
        return 'upload-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    }
    
    createProgressElement(uploadItem) {
        const progressContainer = document.getElementById('upload-progress-container');
        if (!progressContainer) return;
        
        const progressElement = document.createElement('div');
        progressElement.id = uploadItem.id;
        progressElement.className = 'upload-item mb-2';
        progressElement.innerHTML = `
            <div class="d-flex align-items-center justify-content-between mb-1">
                <span class="upload-filename text-truncate" style="max-width: 70%;">
                    ${this.escapeHtml(uploadItem.file.name)}
                </span>
                <span class="upload-size text-muted small">
                    ${this.formatBytes(uploadItem.file.size)}
                </span>
            </div>
            <div class="progress" style="height: 20px;">
                <div class="progress-bar progress-bar-striped progress-bar-animated" 
                     role="progressbar" 
                     style="width: 0%"
                     aria-valuenow="0" 
                     aria-valuemin="0" 
                     aria-valuemax="100">0%</div>
            </div>
            <div class="upload-status small mt-1 text-muted">Queued...</div>
        `;
        
        progressContainer.appendChild(progressElement);
    }
    
    updateProgress(uploadItem, percent) {
        const element = document.getElementById(uploadItem.id);
        if (!element) return;
        
        const progressBar = element.querySelector('.progress-bar');
        const statusText = element.querySelector('.upload-status');
        
        progressBar.style.width = percent + '%';
        progressBar.setAttribute('aria-valuenow', percent);
        progressBar.textContent = Math.round(percent) + '%';
        
        if (percent > 0 && percent < 100) {
            statusText.textContent = 'Uploading...';
        }
    }
    
    markComplete(uploadItem, success = true, message = '') {
        const element = document.getElementById(uploadItem.id);
        if (!element) return;
        
        const progressBar = element.querySelector('.progress-bar');
        const statusText = element.querySelector('.upload-status');
        
        if (success) {
            progressBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            progressBar.classList.add('bg-success');
            statusText.textContent = 'Upload complete ✓';
            statusText.classList.remove('text-muted');
            statusText.classList.add('text-success');
            
            // Remove after 3 seconds
            setTimeout(() => {
                element.style.transition = 'opacity 0.3s';
                element.style.opacity = '0';
                setTimeout(() => element.remove(), 300);
            }, 3000);
        } else {
            progressBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            progressBar.classList.add('bg-danger');
            statusText.textContent = message || 'Upload failed ✗';
            statusText.classList.remove('text-muted');
            statusText.classList.add('text-danger');
        }
    }
    
    processQueue() {
        if (this.activeUploads >= this.maxConcurrentUploads) {
            return;
        }
        
        const nextUpload = this.uploadQueue.find(item => item.status === 'queued');
        if (!nextUpload) {
            // Check if all uploads are complete
            if (this.activeUploads === 0 && this.uploadQueue.length > 0) {
                this.onAllComplete();
            }
            return;
        }
        
        nextUpload.status = 'uploading';
        this.activeUploads++;
        
        this.uploadFile(nextUpload).finally(() => {
            this.activeUploads--;
            this.processQueue(); // Process next in queue
        });
    }
    
    uploadFile(uploadItem) {
        return new Promise((resolve, reject) => {
            const formData = new FormData();
            formData.append('file', uploadItem.file);
            
            const xhr = new XMLHttpRequest();
            
            // Progress tracking
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percentComplete = (e.loaded / e.total) * 100;
                    uploadItem.progress = percentComplete;
                    this.updateProgress(uploadItem, percentComplete);
                }
            });
            
            // Upload complete
            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    uploadItem.status = 'complete';
                    this.markComplete(uploadItem, true);
                    this.onSuccess(xhr.responseText, uploadItem.file);
                    resolve();
                } else {
                    uploadItem.status = 'error';
                    const errorMsg = xhr.responseText || 'Upload failed';
                    this.markComplete(uploadItem, false, errorMsg);
                    this.onError(errorMsg, uploadItem.file);
                    reject(new Error(errorMsg));
                }
            });
            
            // Upload error
            xhr.addEventListener('error', () => {
                uploadItem.status = 'error';
                const errorMsg = 'Network error occurred';
                this.markComplete(uploadItem, false, errorMsg);
                this.onError(errorMsg, uploadItem.file);
                reject(new Error(errorMsg));
            });
            
            // Upload abort
            xhr.addEventListener('abort', () => {
                uploadItem.status = 'error';
                const errorMsg = 'Upload cancelled';
                this.markComplete(uploadItem, false, errorMsg);
                reject(new Error(errorMsg));
            });
            
            xhr.open('POST', this.uploadUrl);
            xhr.setRequestHeader('X-CSRFToken', this.csrfToken);
            xhr.send(formData);
        });
    }
    
    showError(filename, message) {
        const progressContainer = document.getElementById('upload-progress-container');
        if (!progressContainer) {
            console.error(`${filename}: ${message}`);
            return;
        }
        
        const errorElement = document.createElement('div');
        errorElement.className = 'alert alert-danger alert-dismissible fade show mb-2';
        errorElement.innerHTML = `
            <strong>${this.escapeHtml(filename)}:</strong> ${this.escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        
        progressContainer.insertBefore(errorElement, progressContainer.firstChild);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            errorElement.style.transition = 'opacity 0.3s';
            errorElement.style.opacity = '0';
            setTimeout(() => errorElement.remove(), 300);
        }, 5000);
    }
    
    formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * Cleanup method to remove event listeners
     * Call this when the component is no longer needed
     */
    destroy() {
        // Remove document-level event listeners
        ['dragenter', 'dragover', 'drop'].forEach(eventName => {
            document.removeEventListener(eventName, this.boundPreventDefaults, false);
        });
        
        // Remove all drop zone event listeners
        if (this.dropZone) {
            // Remove drag and drop preventDefault handlers
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                this.dropZone.removeEventListener(eventName, this.boundPreventDefaults, false);
            });
            
            // Remove drag over styling handlers
            ['dragenter', 'dragover'].forEach(eventName => {
                this.dropZone.removeEventListener(eventName, this.boundAddDragOver, false);
            });
            
            ['dragleave', 'drop'].forEach(eventName => {
                this.dropZone.removeEventListener(eventName, this.boundRemoveDragOver, false);
            });
            
            // Remove drop handler
            this.dropZone.removeEventListener('drop', this.boundHandleDrop, false);
            
            // Remove click handler
            this.dropZone.removeEventListener('click', this.boundClickHandler, false);
        }
        
        // Remove file input change handler
        if (this.fileInput) {
            this.fileInput.removeEventListener('change', this.boundHandleFileInputChange);
        }
    }
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MultiFileUpload;
}
